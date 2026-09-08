"""Reconstruct history from each game and refresh a spaced subset of teacher scores."""

import argparse
import json
from pathlib import Path
from client import Engine, atomic_json
from arena import sha, engine_flags
from resources import check_space


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--engine", type=Path, required=True)
    ap.add_argument("--ms", type=int, default=500)
    ap.add_argument("--every", type=int, default=20)
    ap.add_argument("--max-pairs", type=int, default=40)
    ap.add_argument("--start-pair", type=int, default=0)
    ap.add_argument("--end-pair", type=int)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--static-score", action="store_true")
    ap.add_argument("--model", type=Path)
    ap.add_argument("--qchecks", type=int, choices=[0, 1, 2], default=0)
    ap.add_argument("--hash-mb", type=int, default=32)
    args = ap.parse_args()
    if args.stride < 1:
        ap.error("stride must be positive")
    args.out.mkdir(parents=True, exist_ok=True)
    files = sorted(args.data.glob("pair-*.json"))[: args.max_pairs]
    config = dict(
        files=[dict(name=p.name, sha256=sha(p)) for p in files],
        engine_sha256=sha(args.engine),
        ms=args.ms,
        every=args.every,
        teacher_args=engine_flags(args.model, mode="tuned"),
        model_sha256=sha(args.model) if args.model else None,
        qchecks=args.qchecks,
        hash_mb=args.hash_mb,
    )
    if args.static_score:
        config["static_score"] = True
    config_file = args.out / "relabel-config.json"
    if config_file.exists() and json.loads(config_file.read_text()) != config:
        raise ValueError("relabel configuration changed")
    atomic_json(config_file, config)
    with (
        Engine(args.engine, args=config["teacher_args"]) as engine,
        Engine(args.engine) as classical,
    ):
        for path in files[args.start_pair : args.end_pair : args.stride]:
            check_space()
            out = args.out / path.name
            if out.exists():
                continue
            record = json.loads(path.read_text())
            count = 0
            for game in record.get("games", []):
                engine.call("position", position=game["initial"])
                classical.call("position", position=game["initial"])
                selected = {
                    s["ply"]: s for s in game["samples"] if s["ply"] % args.every == 0
                }
                for ply, move in enumerate(game["moves"]):
                    if ply in selected:
                        old = selected[ply]
                        r = engine.call(
                            "search",
                            ms=args.ms,
                            hash_mb=args.hash_mb,
                            qchecks=args.qchecks,
                        )
                        old["original_score"] = old["score"]
                        old["original_depth"] = old["depth"]
                        old["score"] = r["score"]
                        old["depth"] = r["depth"]
                        old["teacher_ms"] = args.ms
                        if args.static_score:
                            old["static_score"] = classical.call("status")["eval"]
                        count += 1
                    engine.call("play", move=move)
                    classical.call("play", move=move)
            atomic_json(out, record)
            print(json.dumps(dict(file=path.name, refreshed=count)), flush=True)


if __name__ == "__main__":
    main()
