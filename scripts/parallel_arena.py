"""Partition independent pairs over local processes, preserving a single fixed trial."""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from arena import summarize
from client import ROOT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    args, rest = ap.parse_known_args()
    worker_limit = max(1, min(6, (os.cpu_count() or 2) - 2))
    if not 1 <= args.workers <= worker_limit:
        raise SystemExit(f"workers must be 1..{worker_limit}")
    out = Path(rest[rest.index("--out") + 1])
    pairs = int(rest[rest.index("--pairs") + 1])
    out.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(ROOT / "scripts/arena.py"), *rest]
    subprocess.run(
        command + ["--start-pair", "0", "--end-pair", "0"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    with (out / "runs.jsonl").open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "event": "launch",
                    "workers": args.workers,
                    "logical_cpus": os.cpu_count(),
                    "completed_pairs_at_launch": len(list(out.glob("pair-*.json"))),
                }
            )
            + "\n"
        )
    workers = []
    streams = []
    try:
        for i in range(args.workers):
            stream = (out / f"worker-{i}.log").open("w")
            streams.append(stream)
            workers.append(
                subprocess.Popen(
                    command
                    + [
                        "--start-pair",
                        str(i),
                        "--end-pair",
                        str(pairs),
                        "--stride",
                        str(args.workers),
                    ],
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                )
            )
        last = -1
        while any(w.poll() is None for w in workers):
            complete = len(list(out.glob("pair-*.json")))
            if complete != last:
                print(
                    json.dumps(dict(complete_pairs=complete, total=pairs)), flush=True
                )
                last = complete
            if any(w.returncode not in (None, 0) for w in workers):
                raise RuntimeError("worker failed; inspect worker log")
            time.sleep(5)
        if any(w.returncode for w in workers):
            raise RuntimeError("worker failed")
        print(json.dumps(summarize(out, pairs), indent=2))
    finally:
        for w in workers:
            if w.poll() is None:
                w.terminate()
        for w in workers:
            w.wait()
        for stream in streams:
            stream.close()


if __name__ == "__main__":
    main()
