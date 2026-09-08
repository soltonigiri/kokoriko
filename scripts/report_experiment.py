"""Export a compact, reproducible experiment record without copying game data."""

import argparse
import collections
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from arena import summarize
from client import ROOT, atomic_json


def portable(value):
    if isinstance(value, dict):
        return {k: portable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [portable(v) for v in value]
    if isinstance(value, str) and value.startswith(str(ROOT) + "/"):
        return value[len(str(ROOT)) + 1 :]
    return value


def distribution(values):
    if not values:
        return None
    ordered = sorted(values)
    return {
        "count": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "max": ordered[-1],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--label", required=True)
    args = ap.parse_args()
    config = json.loads((args.directory / "config.json").read_text())
    summary = summarize(args.directory, config["pairs"])
    counts = collections.Counter(wins=0, losses=0, unresolved=0)
    timing = {side: collections.defaultdict(list) for side in ("a", "b")}
    manifest = []
    openings = set()
    draft_trial = False
    for file in sorted(args.directory.glob("pair-*.json")):
        data = file.read_bytes()
        record = json.loads(data)
        manifest.append({"file": file.name, "sha256": hashlib.sha256(data).hexdigest()})
        if "error" in record:
            continue
        start = {
            k: v for k, v in record["games"][0]["initial"].items() if k != "history"
        }
        openings.add(
            hashlib.sha256(json.dumps(start, sort_keys=True).encode()).hexdigest()
        )
        for game in record["games"]:
            draft_trial |= game["initial"]["draft"]
            key = (
                "unresolved"
                if game["winner"] is None
                else "wins"
                if game["winner"] == game["a_side"]
                else "losses"
            )
            counts[key] += 1
            # Timings do not encode the player. Consecutive draft turns make
            # parity unreliable, so report combined timing for draft trials.
            for ply, item in enumerate(game["timings"]):
                if game["initial"]["draft"]:
                    side = "a"
                else:
                    side = (
                        "a"
                        if (game["initial"]["turn"] + ply) % 2 == game["a_side"]
                        else "b"
                    )
                for metric in ("wall_ms", "engine_ms", "depth", "nodes"):
                    timing[side][metric].append(item[metric])
    report = {
        "label": args.label,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "local_data": portable(str(args.directory.resolve())),
        "config": portable(config),
        "summary": summary,
        "outcomes_for_a": dict(counts),
        "unique_openings": len(openings),
        "timing_grouping": "combined (stored as a)" if draft_trial else "per engine",
        "timing": {
            side: {metric: distribution(values) for metric, values in metrics.items()}
            for side, metrics in timing.items()
        },
        "game_files": manifest,
    }
    runs = args.directory / "runs.jsonl"
    if runs.exists():
        report["execution_events"] = [
            json.loads(line) for line in runs.read_text().splitlines() if line.strip()
        ]
    atomic_json(args.out, report)
    print(
        json.dumps(
            {"output": str(args.out), "summary": summary, "outcomes": dict(counts)}
        )
    )


if __name__ == "__main__":
    main()
