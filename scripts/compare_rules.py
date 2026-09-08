"""Differential replay against a frozen engine, including ordered legal moves."""

import argparse
import hashlib
import json
from pathlib import Path

from client import Engine, atomic_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True)
    ap.add_argument("--b", type=Path, required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    count = games = 0
    with Engine(args.a) as a, Engine(args.b) as b:
        for file in sorted(args.data.glob("pair-*.json")):
            for game in json.loads(file.read_text())["games"]:
                for e in (a, b):
                    e.call("position", position=game["initial"])
                for ply, move in enumerate(game["moves"]):
                    assert a.call("status") == b.call("status"), (
                        file.name,
                        ply,
                        "status",
                    )
                    assert a.call("legal") == b.call("legal"), (file.name, ply, "legal")
                    assert a.call("play", move=move) == b.call("play", move=move), (
                        file.name,
                        ply,
                        "state",
                    )
                    count += 1
                games += 1
            print(json.dumps({"file": file.name, "plies": count}), flush=True)
    report = {
        "a_sha256": hashlib.sha256(args.a.read_bytes()).hexdigest(),
        "b_sha256": hashlib.sha256(args.b.read_bytes()).hexdigest(),
        "games": games,
        "plies": count,
        "ordered_legal_moves_status_and_full_state": "exact match",
    }
    assert count > 0
    atomic_json(args.out, report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
