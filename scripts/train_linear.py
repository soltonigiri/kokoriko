"""Fit bounded classical evaluation coefficients to held-out search teachers."""

import argparse
import hashlib
import json
import struct
from pathlib import Path

from client import Engine, atomic_json
from resources import check_space


def export(weights, path):
    if len(weights) != 45 or any(abs(int(w)) > 30000 for w in weights):
        raise ValueError("invalid linear weights")
    body = struct.pack("<45i", *map(int, weights))
    checksum = 1469598103934665603
    for value in body:
        checksum = ((checksum ^ value) * 1099511628211) & ((1 << 64) - 1)
    payload = struct.pack("<8sIIIIQ", b"KOKONN01", 45, 1, 1, 7, checksum) + body
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return hashlib.sha256(payload).hexdigest()


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
    args = ap.parse_args()
    if args.steps < 1:
        ap.error("steps must be positive")
    check_space()
    torch.set_num_threads(1)
    torch.manual_seed(20260908)
    training, validation, manifest = dataset(
        args.data, args.limit, relative=True, residual=True, teacher_mix=1
    )
    matrices = []
    with Engine(args.engine) as engine:
        weights = np.array(engine.call("linear_basis")["weights"], dtype=np.int64)
        for rows in (training, validation):
            matrix = []
            for row in rows:
                engine.call("position", position=json.loads(row[2]))
                basis = engine.call("linear_basis")["features"]
                if int(np.dot(basis, weights)) != row[4]:
                    raise ValueError(f"static teacher mismatch: {row[3]}")
                matrix.append(basis)
            matrices.append(torch.tensor(matrix, dtype=torch.float32))
    config = {
        "architecture": [45, 1],
        "format": 7,
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
    inputs = [matrix * base / 600 for matrix in matrices]
    multiplier = torch.nn.Parameter(torch.ones(45))
    optimizer = torch.optim.Adam([multiplier], lr=0.01)
    loss_fn = torch.nn.functional.binary_cross_entropy_with_logits
    best_loss = float(loss_fn(inputs[1] @ multiplier, targets[1]).detach())
    baseline_loss = best_loss
    best_weights = weights.copy()
    best_step = 0
    history = []
    for step in range(1, args.steps + 1):
        optimizer.zero_grad()
        loss = loss_fn(inputs[0] @ multiplier, targets[0])
        objective = loss + 0.01 * (multiplier - 1).square().mean()
        objective.backward()
        optimizer.step()
        with torch.no_grad():
            multiplier[:42].clamp_(0.5, 1.5)
            multiplier[42:].clamp_(-1, 3)
            multiplier[[0, 14, 28]] = 1
            quantized = torch.round(base * multiplier)
            validation_loss = float(loss_fn(matrices[1] @ quantized / 600, targets[1]))
            if validation_loss < best_loss:
                best_loss = validation_loss
                best_step = step
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
