"""Recheck a frozen tactical corpus with its original teacher and a new candidate."""

import argparse
import json
from pathlib import Path
from arena import engine_flags, sha
from client import Engine, atomic_json
from tactics import move_value


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--teacher", type=Path, required=True)
    ap.add_argument("--engine", type=Path, required=True)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ms", type=int, default=1000)
    ap.add_argument("--qchecks", type=int, choices=[0, 1, 2], default=0)
    ap.add_argument("--require-solved", type=int, default=0)
    args = ap.parse_args()
    corpus = json.loads(args.corpus.read_text())
    if (
        sha(args.teacher) != corpus["config"]["engine_sha256"]
        or sha(args.model) != corpus["config"]["model_sha256"]
    ):
        raise ValueError("reference teacher/model does not match frozen corpus")
    rows = []
    flags = engine_flags(args.model, mode="tuned")
    with (
        Engine(args.teacher, flags) as teacher,
        Engine(args.engine, flags) as candidate,
    ):
        for entry in corpus["positions"]:
            position = entry["position"]
            expected = entry["verified_values"]["teacher"]
            reference = move_value(
                teacher,
                position,
                entry["results"]["teacher"]["move"],
                entry["child_depth"],
            )
            if reference != expected:
                raise ValueError("reference score no longer reproduces")
            candidate.call("position", position=position)
            result = candidate.call(
                "search", ms=args.ms, qchecks=args.qchecks, timeout=args.ms / 1000 + 10
            )
            value = move_value(teacher, position, result["move"], entry["child_depth"])
            rows.append(
                dict(
                    move=result["move"],
                    value=value,
                    expected=expected,
                    solved=value is not None and value >= expected - 30,
                )
            )
    report = dict(
        corpus_sha256=sha(args.corpus),
        candidate_sha256=sha(args.engine),
        ms=args.ms,
        qchecks=args.qchecks,
        solved=sum(r["solved"] for r in rows),
        total=len(rows),
        rows=rows,
    )
    atomic_json(args.out, report)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}))
    if report["solved"] < args.require_solved:
        raise SystemExit("tactical regression threshold failed")


if __name__ == "__main__":
    main()
