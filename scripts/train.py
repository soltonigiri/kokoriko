"""Sparse NNUE training, deterministic checkpoints, portable float/int exports."""

from __future__ import annotations
import argparse
import copy
import hashlib
import json
import random
import struct
from pathlib import Path
import numpy as np
import torch
from torch import nn
from client import atomic_json
from resources import check_space

FEATURES, HIDDEN, SECOND = 6954, 256, 32


def relative_position(p):
    """Rotate and exchange colors so the player to move is always side zero."""
    result = {k: v for k, v in p.items() if k != "history"}
    if not p["turn"]:
        return result
    result["board"] = [
        [1 + ((v - 1 + 14) % 28) for v in tower] for tower in reversed(p["board"])
    ]
    result["hand"] = list(reversed(p["hand"]))
    result["done"] = list(reversed(p["done"]))
    result["first"] = 1 - p["first"]
    result["turn"] = 0
    return result


def features(p, relative=False):
    if relative:
        p = relative_position(p)
    result = [
        (q * 3 + t) * 28 + v - 1
        for q, tower in enumerate(p["board"])
        for t, v in enumerate(tower)
    ]
    result.extend(
        6804 + (c * 14 + k) * 5 + n
        for c, hand in enumerate(p["hand"])
        for k, n in enumerate(hand)
    )
    result.extend(
        [
            6944 + p["turn"],
            6946 + int(p["draft"]),
            6948 + p["first"],
            6950 + int(p["done"][0]),
            6952 + int(p["done"][1]),
        ]
    )
    return result


class Net(nn.Module):
    def __init__(self, hidden=HIDDEN):
        super().__init__()
        self.embedding = nn.EmbeddingBag(FEATURES, hidden, mode="sum")
        self.bias = nn.Parameter(torch.zeros(hidden))
        self.middle = nn.Linear(hidden, SECOND)
        self.output = nn.Linear(SECOND, 1)
        nn.init.normal_(self.embedding.weight, std=0.02)

    def forward(self, indices, offsets):
        x = (self.embedding(indices, offsets) + self.bias).clamp(0, 1)
        x = self.middle(x).clamp(0, 1)
        return self.output(x).flatten()


def dataset(directory, limit, relative=False, residual=False, teacher_mix=0.7):
    train, valid = [], []
    seen_train = set()
    seen_valid = set()
    files = []
    # Split entire opening pairs, so color-reversed games never leak across sets.
    for path in sorted(Path(directory).glob("pair-*.json")):
        raw = path.read_bytes()
        record = json.loads(raw)
        if "error" in record:
            continue
        initial = {
            k: v for k, v in record["games"][0]["initial"].items() if k != "history"
        }
        if relative:
            initial = relative_position(initial)
        opening_hash = hashlib.sha256(
            json.dumps(initial, sort_keys=True).encode()
        ).hexdigest()
        validation = int(opening_hash[:8], 16) % 5 == 0
        files.append(
            dict(
                path=path.name,
                sha256=hashlib.sha256(raw).hexdigest(),
                opening_sha256=opening_hash,
                split="validation" if validation else "training",
            )
        )
        for gi, game in enumerate(record["games"]):
            for sample in game.get("samples", []):
                if sample["depth"] < 1:
                    continue
                p = sample["position"]
                key = json.dumps(
                    relative_position(p) if relative else p,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                label = float(
                    torch.sigmoid(torch.tensor(np.clip(sample["score"] / 600, -20, 20)))
                )
                if game["winner"] is not None:
                    label = teacher_mix * label + (1 - teacher_mix) * float(
                        game["winner"] == p["turn"]
                    )
                row = (
                    features(p, relative),
                    label,
                    key,
                    f"{record['seed']}:{gi}:{sample['ply']}",
                )
                if residual:
                    row += (sample["static_score"],)
                (valid if validation else train).append(row)
                (seen_valid if validation else seen_train).add(key)
        if len(train) + len(valid) >= limit:
            break
    overlap = seen_train & seen_valid
    train = [r for r in train if r[2] not in overlap]
    if not train or not valid:
        raise ValueError("need separate training and validation games")
    return (
        train,
        valid,
        dict(
            files=files,
            split_method=(
                "hash of relative starting position; color-rotated starts stay together"
                if relative
                else "hash of complete starting position; both colors and repeated starts stay together"
            ),
            overlap_positions_removed=len(overlap),
            training=len(train),
            validation=len(valid),
        ),
    )


def batch(rows, device):
    lengths = [len(r[0]) for r in rows]
    indices = torch.tensor(
        [f for row in rows for f in row[0]], dtype=torch.long, device=device
    )
    offsets = torch.tensor(
        np.cumsum([0] + lengths[:-1]), dtype=torch.long, device=device
    )
    labels = torch.tensor([r[1] for r in rows], dtype=torch.float32, device=device)
    return indices, offsets, labels


def export(net, path, quantized=False, relative=False, residual=False):
    params = [
        net.embedding.weight,
        net.bias,
        net.middle.weight,
        net.middle.bias,
        net.output.weight,
        net.output.bias,
    ]
    arrays = []
    for i, p in enumerate(params):
        a = p.detach().cpu().numpy()
        if quantized:
            scale = 512 if i in (0, 1, 2, 4) else 262144
            dtype = "<i4" if i in (1, 3, 5) else "<i2"
            a = np.rint(a * scale)
            bounds = np.iinfo(np.dtype(dtype))
            if a.min() < bounds.min or a.max() > bounds.max:
                raise ValueError("quantization overflow")
            arrays.append(a.astype(dtype).tobytes())
        else:
            arrays.append(a.astype("<f4").tobytes())
    body = b"".join(arrays)
    h = 1469598103934665603
    for b in body:
        h = ((h ^ b) * 1099511628211) & ((1 << 64) - 1)
    payload = (
        struct.pack(
            "<8sIIIIQ",
            b"KOKONN01",
            FEATURES,
            net.embedding.embedding_dim,
            SECOND,
            (6 if quantized else 5)
            if residual
            else (4 if quantized else 3)
            if relative
            else (2 if quantized else 0),
            h,
        )
        + body
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_bytes(payload)
    temp.replace(path)
    return hashlib.sha256(payload).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--limit", type=int, default=10000)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--relative", action="store_true")
    ap.add_argument("--residual", action="store_true")
    ap.add_argument("--teacher-mix", type=float, default=0.7)
    ap.add_argument("--hidden", type=int, choices=[64, 256], default=256)
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args()
    if args.residual and not args.relative:
        ap.error("residual evaluation requires relative features")
    if not 0 <= args.teacher_mix <= 1:
        ap.error("teacher-mix must be in [0, 1]")
    check_space()
    torch.set_num_threads(2)
    random.seed(20260908)
    np.random.seed(20260908)
    torch.manual_seed(20260908)
    device = torch.device(args.device)
    train, valid, manifest = dataset(
        args.data, args.limit, args.relative, args.residual, args.teacher_mix
    )
    args.out.mkdir(parents=True, exist_ok=True)
    net = Net(args.hidden).to(device)
    optimizer = torch.optim.AdamW(net.parameters(), lr=0.001)
    config = dict(
        dataset=manifest,
        batch=args.batch,
        architecture=[FEATURES, args.hidden, SECOND, 1],
        teacher_mix=args.teacher_mix,
        seed=20260908,
        loss_aggregation="per_sample",
    )
    if args.relative:
        config["feature_mode"] = "relative"
    if args.residual:
        config["residual"] = True
    epoch = 0
    history = []
    best_loss = float("inf")
    best_epoch = 0
    best_model = None
    checkpoint = args.out / "checkpoint.pt"
    if args.resume:
        saved = torch.load(checkpoint, map_location=device, weights_only=False)
        # Older checkpoints selected epochs using the mean of batch means.
        # Preserve that experiment's metric when resuming it.
        if "loss_aggregation" not in saved["config"]:
            config.pop("loss_aggregation")
        if saved["config"] != config:
            raise ValueError("resume config or dataset changed")
        net.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        epoch = saved["epoch"]
        history = saved["history"]
        best_loss = saved.get("best_loss", history[-1]["validation"])
        best_epoch = saved.get("best_epoch", epoch)
        best_model = saved.get("best_model", copy.deepcopy(saved["model"]))
        random.setstate(saved["random"])
        np.random.set_state(saved["numpy"])
        torch.set_rng_state(saved["torch"].cpu())
        if device.type == "cuda":
            torch.cuda.set_rng_state_all([x.cpu() for x in saved["cuda"]])
    per_sample = "loss_aggregation" in config
    atomic_json(args.out / "config.json", config)
    while epoch < args.epochs:
        check_space()
        net.train()
        order = list(range(len(train)))
        random.shuffle(order)
        losses = []
        for offset in range(0, len(order), args.batch):
            rows = [train[i] for i in order[offset : offset + args.batch]]
            ix, ofs, y = batch(rows, device)
            optimizer.zero_grad(set_to_none=True)
            logits = net(ix, ofs)
            if args.residual:
                logits = logits + torch.tensor(
                    [row[4] / 600 for row in rows], device=device
                )
            loss = nn.functional.binary_cross_entropy_with_logits(logits, y)
            loss.backward()
            optimizer.step()
            losses.append(loss.item() * (len(rows) if per_sample else 1))
        net.eval()
        losses_valid = []
        with torch.no_grad():
            for start in range(0, len(valid), args.batch):
                rows = valid[start : start + args.batch]
                ix, ofs, y = batch(rows, device)
                logits = net(ix, ofs)
                if args.residual:
                    logits = logits + torch.tensor(
                        [row[4] / 600 for row in rows], device=device
                    )
                losses_valid.append(
                    nn.functional.binary_cross_entropy_with_logits(logits, y).item()
                    * (len(rows) if per_sample else 1)
                )
        epoch += 1
        row = dict(
            epoch=epoch,
            train=float(sum(losses) / len(train) if per_sample else np.mean(losses)),
            validation=float(
                sum(losses_valid) / len(valid) if per_sample else np.mean(losses_valid)
            ),
        )
        if device.type == "cuda":
            row["peak_vram_bytes"] = torch.cuda.max_memory_allocated()
        history.append(row)
        if row["validation"] < best_loss:
            best_loss, best_epoch = row["validation"], epoch
            best_model = {
                k: v.detach().cpu().clone() for k, v in net.state_dict().items()
            }
        print(json.dumps(row), flush=True)
        saved = dict(
            model=net.state_dict(),
            optimizer=optimizer.state_dict(),
            epoch=epoch,
            config=config,
            history=history,
            random=random.getstate(),
            numpy=np.random.get_state(),
            torch=torch.get_rng_state(),
            cuda=torch.cuda.get_rng_state_all() if device.type == "cuda" else [],
            best_loss=best_loss,
            best_epoch=best_epoch,
            best_model=best_model,
        )
        temp = checkpoint.with_suffix(".tmp")
        torch.save(saved, temp)
        temp.replace(checkpoint)
        atomic_json(args.out / "history.json", history)
    if best_model is not None:
        net.load_state_dict(best_model)
    atomic_json(
        args.out / "selection.json",
        dict(
            epoch=best_epoch,
            validation=best_loss,
            policy="minimum validation loss; strength acceptance requires a separate match",
        ),
    )
    hashes = {
        fmt: export(
            net,
            args.out / f"model-{fmt}.nnue",
            fmt == "int",
            args.relative,
            args.residual,
        )
        for fmt in ("float", "int")
    }
    atomic_json(args.out / "exports.json", hashes)
    examples = []
    with torch.no_grad():
        for row in valid[:50]:
            ix, ofs, _ = batch([row], device)
            examples.append(
                dict(features=row[0], score=float(net(ix, ofs).item() * 600))
            )
    atomic_json(args.out / "parity.json", examples)


if __name__ == "__main__":
    main()
