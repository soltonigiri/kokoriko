"""Select samples across each full game before paying for deeper teacher searches."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

from client import atomic_json
from resources import check_space


def select_samples(samples, maximum):
    if len(samples) <= maximum:
        return samples
    return [samples[i * (len(samples) - 1) // (maximum - 1)] for i in range(maximum)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--per-game", type=int, default=50)
    args = ap.parse_args()
    if args.per_game < 2:
        ap.error("per-game must be at least two")
    check_space()
    files = sorted(args.data.glob("pair-*.json"))
    config = {
        "per_game": args.per_game,
        "selection": "equally spaced sample indices including first and last",
        "files": [
            {"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in files
        ],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    config_path = args.out / "selection-config.json"
    if config_path.exists() and json.loads(config_path.read_text()) != config:
        raise ValueError("selection input or configuration changed")
    atomic_json(config_path, config)
    total = 0
    for path in files:
        record = json.loads(path.read_text())
        if "error" in record:
            raise ValueError(f"failed source pair: {path.name}")
        original = copy.deepcopy(record)
        for game, source in zip(record["games"], original["games"]):
            game["samples"] = select_samples(source["samples"], args.per_game)
            total += len(game["samples"])
            assert {k: v for k, v in game.items() if k != "samples"} == {
                k: v for k, v in source.items() if k != "samples"
            }
            assert len({s["ply"] for s in game["samples"]}) == len(game["samples"])
            assert all(s in source["samples"] for s in game["samples"])
        dest = args.out / path.name
        if dest.exists() and json.loads(dest.read_text()) != record:
            raise ValueError(f"existing selection differs: {dest.name}")
        atomic_json(dest, record)
    print(json.dumps({"pairs": len(files), "samples": total}))


if __name__ == "__main__":
    main()
