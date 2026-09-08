"""Compare search cost on fixed positions reconstructed from a training game."""

import argparse
import hashlib
import json
from pathlib import Path

from client import Engine, ROOT, atomic_json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", type=Path, required=True)
    ap.add_argument("--engine", type=Path, default=ROOT / "build/kokoriko")
    ap.add_argument("--model", type=Path)
    ap.add_argument("--selective", action="store_true")
    ap.add_argument("--ms", type=int, default=200)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    game = json.loads(args.game.read_text())["games"][0]
    positions = []
    with Engine(args.engine) as referee:
        state = referee.call("position", position=game["initial"])
        for ply, move in enumerate(game["moves"]):
            if ply in (0, 8, 16, 24, 32, 48):
                positions.append((ply, state))
            state = referee.call("play", move=move)
    variants = [("basic", ["--basic-search"]), ("pvs", ["--tuned-search"])]
    if args.model:
        variants.append(("nnue", ["--basic-search", "--model", str(args.model)]))
    if args.selective:
        variants.append(("selective", ["--selective-search"]))
    results = []
    for label, flags in variants:
        with Engine(args.engine, args=flags) as engine:
            for ply, position in positions:
                engine.call("position", position=position)
                legal = engine.call("legal")
                result = engine.call("search", ms=args.ms, hash_mb=1)
                assert result["move"] in legal
                assert engine.call("state") == position
                results.append({"variant": label, "ply": ply, **result})
    atomic_json(
        args.out,
        {
            "source_game": args.game.name,
            "source_sha256": digest(args.game),
            "engine_sha256": digest(args.engine),
            "model_sha256": digest(args.model) if args.model else None,
            "requested_ms": args.ms,
            "threads": 1,
            "hash_mb": 1,
            "position_count": len(positions),
            "results": results,
        },
    )
    print(
        json.dumps(
            {
                "positions": len(positions),
                "searches": len(results),
                "out": str(args.out),
            }
        )
    )


if __name__ == "__main__":
    main()
