"""Compare direct and feature-diff NNUE searches at fixed depth and fixed time."""

import argparse
import json
import statistics
from pathlib import Path
from arena import engine_flags, sha
from client import Engine, atomic_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", type=Path, required=True)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--book", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args()
    entries = json.loads(args.book.read_text())["positions"][: args.limit]
    flags = engine_flags(args.model, mode="tuned")
    rows = []
    with (
        Engine(args.engine, flags) as direct,
        Engine(args.engine, flags + ["--network-diff"]) as diff,
    ):
        for index, entry in enumerate(entries):
            row = dict(position=index)
            for label, engine in (("direct", direct), ("diff", diff)):
                engine.call("position", position=entry["position"])
                row[label] = engine.call("search", depth=2, ms=60000, timeout=65)
                engine.call("position", position=entry["position"])
                row[label + "_timed"] = engine.call("search", ms=300)
            for key in ("move", "score", "depth", "nodes"):
                if row["direct"][key] != row["diff"][key]:
                    raise ValueError(f"direct/diff mismatch in {key} at {index}")
            rows.append(row)
    report = dict(
        engine_sha256=sha(args.engine),
        model_sha256=sha(args.model),
        book_sha256=sha(args.book),
        fixed_depth_identical=True,
        rows=rows,
        median_elapsed_ratio=statistics.median(
            r["direct"]["elapsed_ms"] / max(0.001, r["diff"]["elapsed_ms"])
            for r in rows
        ),
    )
    atomic_json(args.out, report)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}))


if __name__ == "__main__":
    main()
