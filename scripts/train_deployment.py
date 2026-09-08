"""Fit a small opponent-profile response table from paired deployment matches."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from arena import sha
from client import ROOT, atomic_json


def fit(trials):
    responses, evidence = {}, {}
    for profile in ("reserve", "wide", "tower"):
        rows = [r for r in trials if r["profile"] == profile]
        if not rows or any(
            r["summary"]["failed_pairs"]
            or r["summary"]["complete_pairs"] != r["summary"]["expected_pairs"]
            for r in rows
        ):
            raise ValueError("incomplete deployment training")
        # Equal budgets and matched starting positions; ties favor smaller plans.
        best = max(rows, key=lambda r: (r["summary"]["score"], -int(r["candidate"])))
        responses[profile] = best["candidate"]
        evidence[profile] = [
            {
                "policy": r["candidate"],
                "score": r["summary"]["score"],
                "ci95": r["summary"]["ci95"],
            }
            for r in rows
        ]
    return dict(
        responses=responses,
        evidence=evidence,
        adopted=False,
        selection="highest paired score within opponent profile; independent validation required",
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine", type=Path, required=True)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pairs", type=int, default=6)
    ap.add_argument("--ms", type=int, default=100)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--seed", type=int, default=271000)
    args = ap.parse_args()
    config = dict(
        engine_sha256=sha(args.engine),
        model_sha256=sha(args.model),
        pairs=args.pairs,
        ms=args.ms,
        seed=args.seed,
        source_sha256=sha(Path(__file__)),
        deployment_sha256=sha(ROOT / "scripts/deployment.py"),
    )
    cp = args.out / "config.json"
    if cp.exists() and json.loads(cp.read_text()) != config:
        raise ValueError("deployment training configuration changed")
    atomic_json(cp, config)
    trials = []
    for index, (profile, opponent) in enumerate(
        (("reserve", "8"), ("wide", "12"), ("tower", "tower"))
    ):
        for candidate in ("8", "12", "18"):
            out = args.out / f"{profile}-{candidate}"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/parallel_arena.py"),
                    "--workers",
                    str(args.workers),
                    "--a",
                    str(args.engine),
                    "--b",
                    str(args.engine),
                    "--ref",
                    str(args.engine),
                    "--model-a",
                    str(args.model),
                    "--model-b",
                    str(args.model),
                    "--tuned-a",
                    "--tuned-b",
                    "--deployment-a",
                    candidate,
                    "--deployment-b",
                    opponent,
                    "--ms",
                    str(args.ms),
                    "--pairs",
                    str(args.pairs),
                    "--max-plies",
                    "140",
                    "--seed",
                    str(args.seed + 1000 * index),
                    "--out",
                    str(out),
                ],
                check=True,
            )
            trials.append(
                dict(
                    profile=profile,
                    candidate=candidate,
                    summary=json.loads((out / "summary.json").read_text()),
                )
            )
    table = fit(trials)
    table["config"] = config
    atomic_json(args.out / "table.json", table)
    print(json.dumps(table), flush=True)


if __name__ == "__main__":
    main()
