"""Check unchanged search behavior at a fixed node budget and compare elapsed time."""

import argparse
import hashlib
import json
import statistics
from pathlib import Path

from client import Engine, atomic_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True)
    ap.add_argument("--b", type=Path, required=True)
    ap.add_argument("--game", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", type=Path)
    ap.add_argument("--nodes", type=int, default=20000)
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()
    game = json.loads(args.game.read_text())["games"][0]
    positions = []
    with Engine(args.b) as e:
        state = e.call("position", position=game["initial"])
        for ply, move in enumerate(game["moves"][:65]):
            if ply in (0, 8, 16, 24, 32, 48, 64):
                positions.append((ply, state))
            state = e.call("play", move=move)
    rows = []
    flags = ["--tuned-search"] + (["--model", str(args.model)] if args.model else [])
    with (
        Engine(args.a, args=flags) as a,
        Engine(args.b, args=flags) as b,
    ):
        for repetition in range(args.repeat):
            for ply, position in positions:
                result = {}
                times = {}
                engines = [("a", a), ("b", b)]
                if repetition % 2:
                    engines.reverse()
                for label, e in engines:
                    e.call("position", position=position)
                    e.call("legal")  # Warm the movement table before timing.
                    r = e.call(
                        "search",
                        ms=60000,
                        nodes=args.nodes,
                        depth=16,
                        hash_mb=1,
                        timeout=70,
                    )
                    times[label] = r.pop("elapsed_ms")
                    result[label] = r
                    assert e.call("state") == position
                assert result["a"] == result["b"], (ply, result)
                rows.append(
                    {
                        "ply": ply,
                        "repeat": repetition,
                        "a_ms": times["a"],
                        "b_ms": times["b"],
                        "nodes": result["a"]["nodes"],
                        "depth": result["a"]["depth"],
                    }
                )
    report = {
        "a_sha256": hashlib.sha256(args.a.read_bytes()).hexdigest(),
        "b_sha256": hashlib.sha256(args.b.read_bytes()).hexdigest(),
        "source_game_sha256": hashlib.sha256(args.game.read_bytes()).hexdigest(),
        "search_mode": "PVS",
        "requested_nodes": args.nodes,
        "threads": 1,
        "hash_mb": 1,
        "search_results_except_time": "exact match",
        "speed_ratio_a_over_b": sum(r["b_ms"] for r in rows)
        / sum(r["a_ms"] for r in rows),
        "median_paired_ratio": statistics.median(r["b_ms"] / r["a_ms"] for r in rows),
        "measurements": rows,
    }
    if args.model:
        report["model_sha256"] = hashlib.sha256(args.model.read_bytes()).hexdigest()
    atomic_json(args.out, report)
    print(json.dumps({k: v for k, v in report.items() if k != "measurements"}))


if __name__ == "__main__":
    main()
