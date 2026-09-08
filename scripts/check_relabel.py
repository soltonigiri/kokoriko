"""Verify that teacher refresh changes only the intended labels in frozen games."""

import argparse
import json
import statistics
from pathlib import Path

from arena import sha
from client import atomic_json


def check(source, data):
    config = json.loads((data / "relabel-config.json").read_text())
    names = {entry["name"] for entry in config["files"]}
    if {p.name for p in data.glob("pair-*.json")} != names:
        raise ValueError("teacher data incomplete or contains unexpected pairs")
    rows, depths, previous_depths = [], [], []
    total = refreshed = 0
    for entry in config["files"]:
        original_path = source / entry["name"]
        updated_path = data / entry["name"]
        if sha(original_path) != entry["sha256"]:
            raise ValueError("teacher input changed")
        original = json.loads(original_path.read_text())
        updated = json.loads(updated_path.read_text())
        for old_game, game in zip(original["games"], updated["games"], strict=True):
            for old, sample in zip(old_game["samples"], game["samples"], strict=True):
                total += 1
                if old["ply"] % config["every"] == 0:
                    if (
                        sample["original_score"] != old["score"]
                        or sample["original_depth"] != old["depth"]
                        or sample["teacher_ms"] != config["ms"]
                        or not -30000 <= sample["score"] <= 30000
                        or not 0 <= sample["depth"] <= 32
                    ):
                        raise ValueError("teacher label provenance or range mismatch")
                    if (
                        config.get("static_score")
                        and type(sample["static_score"]) is not int
                    ):
                        raise ValueError("static teacher score missing or invalid")
                    refreshed += 1
                    depths.append(sample["depth"])
                    previous_depths.append(sample["original_depth"])
                    sample["score"], sample["depth"] = old["score"], old["depth"]
                    for key in (
                        "original_score",
                        "original_depth",
                        "teacher_ms",
                        "static_score",
                    ):
                        if key in old:
                            sample[key] = old[key]
                        else:
                            sample.pop(key, None)
        if updated != original:
            raise ValueError(
                "teacher refresh changed game, position or sample metadata"
            )
        rows.append(
            dict(
                file=entry["name"],
                input_sha256=entry["sha256"],
                output_sha256=sha(updated_path),
            )
        )
    return dict(
        pairs=len(rows),
        samples=total,
        refreshed=refreshed,
        teacher_ms=config["ms"],
        teacher_engine_sha256=config["engine_sha256"],
        mean_teacher_depth=statistics.mean(depths),
        mean_original_depth=statistics.mean(previous_depths),
        teacher_depth_zero=sum(depth == 0 for depth in depths),
        original_games_positions_and_metadata="exact match after restoring label fields",
        files=rows,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    result = check(args.source, args.data)
    atomic_json(args.out, result)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)


if __name__ == "__main__":
    main()
