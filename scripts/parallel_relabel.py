"""Distribute independent teacher-label pairs, preserving resumable pair files."""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from client import ROOT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    args, rest = ap.parse_known_args()
    if not 1 <= args.workers <= max(1, min(6, (os.cpu_count() or 2) - 2)):
        ap.error("invalid worker count")
    out = Path(rest[rest.index("--out") + 1])
    out.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(ROOT / "scripts/relabel.py"), *rest]
    subprocess.run(command + ["--start-pair", "0", "--end-pair", "0"], check=True)
    expected = len(json.loads((out / "relabel-config.json").read_text())["files"])
    with (out / "runs.jsonl").open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "event": "launch",
                    "workers": args.workers,
                    "completed_pairs_at_launch": len(list(out.glob("pair-*.json"))),
                }
            )
            + "\n"
        )
    workers, streams = [], []
    try:
        for index in range(args.workers):
            stream = (out / f"worker-{index}.log").open("w")
            streams.append(stream)
            workers.append(
                subprocess.Popen(
                    command
                    + ["--start-pair", str(index), "--stride", str(args.workers)],
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                )
            )
        last = -1
        while any(worker.poll() is None for worker in workers):
            completed = len(list(out.glob("pair-*.json")))
            if completed != last:
                print(
                    json.dumps({"completed_pairs": completed, "expected": expected}),
                    flush=True,
                )
                last = completed
            if any(worker.returncode not in (None, 0) for worker in workers):
                raise RuntimeError("teacher worker failed; inspect worker log")
            time.sleep(5)
        if any(worker.returncode for worker in workers):
            raise RuntimeError("teacher worker failed")
        completed = len(list(out.glob("pair-*.json")))
        if completed != expected:
            raise RuntimeError("teacher labels are incomplete")
        print(
            json.dumps({"completed_pairs": completed, "expected": expected}), flush=True
        )
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
        for worker in workers:
            worker.wait()
        for stream in streams:
            stream.close()


if __name__ == "__main__":
    main()
