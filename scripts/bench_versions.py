"""Compare standard configurations on replayed positions at several time budgets.

This measures search behavior, not match strength. Both binaries use the same
explicit after-draft model policy; all executable and model hashes are recorded.
"""

import argparse
import json
import statistics
from pathlib import Path

from arena import engine_flags, sha
from client import Engine, atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", type=Path, required=True)
    parser.add_argument("--b", type=Path, required=True)
    parser.add_argument("--model-a", type=Path, required=True)
    parser.add_argument("--model-b", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--times", type=int, nargs="+", default=[300, 1000, 5000])
    parser.add_argument("--plies", type=int, nargs="+", default=[0, 8, 16, 24, 32, 48])
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--hash-mb", type=int, default=32)
    args = parser.parse_args()
    if args.repeat < 1 or any(t < 1 or t > 3600000 for t in args.times):
        parser.error("positive repeats and time budgets in 1..3600000 required")
    if not 1 <= args.hash_mb <= 512:
        parser.error("hash-mb must be in 1..512")
    game = json.loads(args.game.read_text())["games"][0]
    positions = []
    with Engine(args.b) as referee:
        state = referee.call("position", position=game["initial"])
        for ply in range(len(game["moves"]) + 1):
            if ply in args.plies and referee.call("legal"):
                positions.append((ply, state))
            if ply == len(game["moves"]) or ply >= max(args.plies):
                break
            state = referee.call("play", move=game["moves"][ply])
    if not positions:
        raise ValueError("no nonterminal benchmark positions")
    flags = {
        s: engine_flags(getattr(args, f"model_{s}"), mode="tuned") for s in ("a", "b")
    }
    report = dict(
        source_sha256=sha(args.game),
        a_sha256=sha(args.a),
        b_sha256=sha(args.b),
        model_a_sha256=sha(args.model_a),
        model_b_sha256=sha(args.model_b),
        engine_args=flags,
        hash_mb=args.hash_mb,
        threads=1,
        purpose="search diagnostics; does not establish playing strength",
        positions=[dict(ply=ply, position=p) for ply, p in positions],
        measurements=[],
    )
    with Engine(args.a, flags["a"]) as a, Engine(args.b, flags["b"]) as b:
        for repeat in range(args.repeat):
            for ms in args.times:
                for ply, position in positions:
                    row = dict(repeat=repeat, ms=ms, ply=ply)
                    engines = [("a", a), ("b", b)]
                    if (repeat + ply + args.times.index(ms)) % 2:
                        engines.reverse()
                    for label, engine in engines:
                        engine.call("position", position=position)
                        legal = engine.call("legal")
                        result = engine.call(
                            "search",
                            ms=ms,
                            hash_mb=args.hash_mb,
                            timeout=ms / 1000 + 10,
                        )
                        if (
                            result["move"] not in legal
                            or engine.call("state") != position
                        ):
                            raise ValueError(
                                f"illegal move or changed state: {label} ply {ply}"
                            )
                        row[label] = result
                    report["measurements"].append(row)
                    atomic_json(args.out, report)
                    print(
                        json.dumps(
                            dict(
                                ms=ms,
                                ply=ply,
                                repeat=repeat,
                                depth_a=row["a"]["depth"],
                                depth_b=row["b"]["depth"],
                            )
                        ),
                        flush=True,
                    )
    report["summary"] = []
    for ms in args.times:
        rows = [r for r in report["measurements"] if r["ms"] == ms]
        report["summary"].append(
            dict(
                ms=ms,
                searches_per_engine=len(rows),
                move_agreements=sum(r["a"]["move"] == r["b"]["move"] for r in rows),
                **{
                    s: dict(
                        median_depth=statistics.median(r[s]["depth"] for r in rows),
                        median_nodes=statistics.median(r[s]["nodes"] for r in rows),
                        max_elapsed_ms=max(r[s]["elapsed_ms"] for r in rows),
                    )
                    for s in ("a", "b")
                },
            )
        )
    atomic_json(args.out, report)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
