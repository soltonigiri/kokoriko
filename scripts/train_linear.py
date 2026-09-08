"""Fit bounded classical evaluation coefficients to held-out search teachers."""

import argparse
import hashlib
import json
import struct
from pathlib import Path

from client import Engine, atomic_json
from resources import check_space


def export(weights, path):
    if len(weights) not in (45, 53) or any(abs(int(w)) > 30000 for w in weights):
        raise ValueError("invalid linear weights")
    size = len(weights)
    body = struct.pack(f"<{size}i", *map(int, weights))
    checksum = 1469598103934665603
    for value in body:
        checksum = ((checksum ^ value) * 1099511628211) & ((1 << 64) - 1)
    payload = (
        struct.pack(
            "<8sIIIIQ", b"KOKONN01", size, 1, 1, 8 if size == 53 else 7, checksum
        )
        + body
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return hashlib.sha256(payload).hexdigest()


def read_weights(path):
    data = Path(path).read_bytes()
    if len(data) < 32:
        raise ValueError("truncated linear model")
    magic, size, hidden, output, version, expected = struct.unpack(
        "<8sIIIIQ", data[:32]
    )
    if (
        magic != b"KOKONN01"
        or (size, hidden, output, version) not in ((45, 1, 1, 7), (53, 1, 1, 8))
        or len(data) != 32 + size * 4
    ):
        raise ValueError("invalid linear model header")
    checksum = 1469598103934665603
    for value in data[32:]:
        checksum = ((checksum ^ value) * 1099511628211) & ((1 << 64) - 1)
    weights = list(struct.unpack(f"<{size}i", data[32:]))
    if checksum != expected or any(abs(w) > 30000 for w in weights):
        raise ValueError("invalid linear model payload")
    return weights


def main():
    import numpy as np
    import torch
    from train import dataset

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--engine", type=Path, default=Path("build/kokoriko"))
    ap.add_argument("--limit", type=int, default=20000)
    ap.add_argument("--steps", type=int, default=2000)
    ap.add_argument("--base-model", type=Path)
    ap.add_argument(
        "--groups", default="", help="comma-separated tower,king,betrayal,drops"
    )
    ap.add_argument("--validation-family", action="append", default=[])
    ap.add_argument("--validation-type", action="append", default=[])
    args = ap.parse_args()
    group_indices = {
        "tower": [45, 46],
        "king": [47, 48],
        "betrayal": [49, 50],
        "drops": [51, 52],
    }
    groups = [g for g in args.groups.split(",") if g]
    if any(g not in group_indices for g in groups):
        ap.error("unknown feature group")
    extended = bool(groups)
    if args.steps < 1:
        ap.error("steps must be positive")
    check_space()
    torch.set_num_threads(1)
    torch.manual_seed(20260908)
    training, validation, manifest = dataset(
        args.data,
        args.limit,
        relative=True,
        residual=True,
        teacher_mix=1,
        validation_families=args.validation_family,
        validation_types=args.validation_type,
    )
    matrices = []
    with Engine(args.engine) as engine:
        classical = np.array(engine.call("linear_basis")["weights"], dtype=np.int64)
        defaults = np.array(
            engine.call("linear_basis", extended=extended)["weights"], dtype=np.int64
        )
        weights = (
            np.array(read_weights(args.base_model), dtype=np.int64)
            if args.base_model
            else classical.copy()
        )
        if extended and len(weights) == 45:
            weights = np.concatenate([weights, np.zeros(8, dtype=np.int64)])
        if len(weights) != len(defaults):
            raise ValueError("base model does not match requested features")
        for rows in (training, validation):
            matrix = []
            for row in rows:
                engine.call("position", position=json.loads(row[2]))
                basis = engine.call("linear_basis", extended=extended)["features"]
                if int(np.dot(basis[:45], classical)) != row[4]:
                    raise ValueError(f"static teacher mismatch: {row[3]}")
                matrix.append(basis)
            matrices.append(torch.tensor(matrix, dtype=torch.float32))
    config = {
        "architecture": [len(weights), 1],
        "groups": groups,
        "format": 8 if extended else 7,
        "engine_sha256": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
        "manifest": manifest,
        "training_ids": [row[3] for row in training],
        "validation_ids": [row[3] for row in validation],
        "teacher_mix": 1,
        "score_scale": 600,
        "steps": args.steps,
        "learning_rate": 0.01,
        "regularization": 0.01,
        "material_multiplier_bounds": [0.5, 1.5],
        "positional_multiplier_bounds": [-1, 3],
        "default_weights": weights.tolist(),
    }
    config_path = args.out / "config.json"
    if config_path.exists() and json.loads(config_path.read_text()) != config:
        raise ValueError("linear training configuration changed")
    atomic_json(config_path, config)
    base = torch.tensor(weights, dtype=torch.float32)
    targets = [
        torch.tensor([row[1] for row in rows]) for rows in (training, validation)
    ]
    loss_fn = torch.nn.functional.binary_cross_entropy_with_logits
    active = torch.zeros(len(weights)) if extended else torch.ones(len(weights))
    if extended:
        for group in groups:
            active[group_indices[group]] = 1
    else:
        active[[0, 14, 28]] = 0
    scale = torch.tensor(np.maximum(np.abs(defaults), 1), dtype=torch.float32)
    delta = torch.nn.Parameter(torch.zeros(len(weights)))
    optimizer = torch.optim.Adam([delta], lr=0.01)
    best_loss = float(loss_fn(matrices[1] @ base / 600, targets[1]))
    baseline_loss = best_loss
    best_weights, best_step, history = weights.copy(), 0, []
    for step in range(1, args.steps + 1):
        optimizer.zero_grad()
        candidate = base + delta * scale * active
        loss = loss_fn(matrices[0] @ candidate / 600, targets[0])
        objective = loss + 0.01 * (delta * active).square().mean()
        objective.backward()
        optimizer.step()
        with torch.no_grad():
            delta.clamp_(-3, 3)
            if not extended:
                delta[:42].clamp_(-0.5, 0.5)
                delta[42:45].clamp_(-2, 2)
            quantized = torch.round(base + delta * scale * active)
            validation_loss = float(loss_fn(matrices[1] @ quantized / 600, targets[1]))
            if validation_loss < best_loss:
                best_loss, best_step = validation_loss, step
                best_weights = quantized.to(torch.int64).numpy().copy()
            if step == 1 or step % 25 == 0 or step == args.steps:
                history.append(
                    dict(
                        step=step,
                        training_loss=float(loss),
                        validation_loss=validation_loss,
                    )
                )
    model_sha = export(best_weights, args.out / "model-int.nnue")
    result = {
        "training": len(training),
        "validation": len(validation),
        "baseline_validation_loss": baseline_loss,
        "best_validation_loss": best_loss,
        "best_step": best_step,
        "weights": best_weights.tolist(),
        "model_sha256": model_sha,
        "history": history,
    }
    atomic_json(args.out / "result.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "history"}), flush=True)


if __name__ == "__main__":
    main()
