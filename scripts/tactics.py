"""Extract search-teacher tactics and score alternatives at a common child depth."""

import argparse
import json
from pathlib import Path

from arena import engine_flags, sha
from client import Engine, atomic_json


def move_value(engine, position, move, depth):
    engine.call("position", position=position)
    child = engine.call("play", move=move)
    status = engine.call("status")
    if status["outcome"] != "ongoing":
        return 0 if status["outcome"] == "repetition" else 29999
    result = engine.call(
        "search", depth=depth, ms=60000, qchecks=1, reuse_scores=False, timeout=65
    )
    if result["depth"] != depth:
        return None
    return result["score"] * (1 if child["turn"] == position["turn"] else -1)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book", type=Path, required=True)
    ap.add_argument("--engine", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=24)
    ap.add_argument("--teacher-ms", type=int, default=5000)
    ap.add_argument("--short-ms", type=int, default=100)
    ap.add_argument("--margin", type=int, default=100)
    args = ap.parse_args()
    config = dict(
        book_sha256=sha(args.book),
        engine_sha256=sha(args.engine),
        baseline_sha256=sha(args.baseline),
        model_sha256=sha(args.model),
        limit=args.limit,
        teacher_ms=args.teacher_ms,
        short_ms=args.short_ms,
        margin=args.margin,
        source_sha256=sha(Path(__file__)),
    )
    cp = args.out / "config.json"
    if cp.exists() and json.loads(cp.read_text()) != config:
        raise ValueError("tactics configuration changed")
    atomic_json(cp, config)
    positions = json.loads(args.book.read_text())["positions"][: args.limit]
    rows = []
    flags = engine_flags(args.model, mode="tuned")
    with (
        Engine(args.engine, flags) as teacher,
        Engine(args.baseline, flags) as baseline,
        Engine(args.engine, flags) as candidate,
    ):
        for index, entry in enumerate(positions):
            path = args.out / f"position-{index:04}.json"
            if path.exists():
                rows.append(json.loads(path.read_text()))
                continue
            position = entry["position"]
            teacher.call("position", position=position)
            long = teacher.call(
                "search",
                ms=args.teacher_ms,
                qchecks=1,
                timeout=args.teacher_ms / 1000 + 10,
            )
            baseline.call("position", position=position)
            short = baseline.call("search", ms=args.short_ms)
            results = {"baseline": short, "teacher": long}
            for checks in (0, 1):
                candidate.call("position", position=position)
                results[f"qchecks{checks}"] = candidate.call(
                    "search", ms=args.short_ms, qchecks=checks
                )
            depth = max(1, min(2, long["depth"] - 1))
            values, memo = {}, {}
            for name, result in results.items():
                key = json.dumps(result["move"], sort_keys=True)
                if key not in memo:
                    memo[key] = move_value(teacher, position, result["move"], depth)
                values[name] = memo[key]
            complete = all(v is not None for v in values.values())
            gap = values["teacher"] - values["baseline"] if complete else None
            row = dict(
                position=position,
                source=entry.get("source"),
                tags=entry.get("tags"),
                results=results,
                verified_values=values,
                child_depth=depth,
                verified_tactic=complete and gap >= args.margin,
                teacher_gap=gap,
            )
            atomic_json(path, row)
            rows.append(row)
            print(
                json.dumps(dict(index=index, tactic=row["verified_tactic"], gap=gap)),
                flush=True,
            )
    tactics = [r for r in rows if r["verified_tactic"]]
    summary = dict(
        examined=len(rows),
        verified_tactics=len(tactics),
        tolerance_cp=30,
        purpose="regression corpus; teacher search is not game-theoretic proof",
    )
    for name in ("baseline", "qchecks0", "qchecks1"):
        summary[name] = dict(
            solved=sum(
                r["verified_values"][name] >= r["verified_values"]["teacher"] - 30
                for r in tactics
            ),
            total=len(tactics),
        )
    atomic_json(args.out / "corpus.json", dict(config=config, positions=tactics))
    atomic_json(args.out / "summary.json", summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
