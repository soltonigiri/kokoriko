"""Replay every recorded move with a fixed referee and quarantine invalid pairs."""

import argparse
import json
from pathlib import Path
from client import Engine, atomic_json
from resources import check_space
from arena import sha


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--engine", type=Path, default=Path("build/kokoriko"))
    args = ap.parse_args()
    check_space()
    if args.data.resolve() == args.out.resolve():
        raise ValueError("validation output must differ from source data")
    files = sorted(args.data.glob("pair-*.json"))
    config = dict(
        files=[dict(file=p.name, sha256=sha(p)) for p in files],
        referee_sha256=sha(args.engine),
        sample_positions_checked=True,
    )
    config_path = args.out / "validation-config.json"
    if config_path.exists():
        if json.loads(config_path.read_text()) != config:
            raise ValueError("validation inputs or referee changed; use new output")
    elif any(args.out.glob("pair-*.json")):
        raise ValueError("existing output lacks a validation manifest; use new output")
    atomic_json(config_path, config)
    result = dict(
        referee_sha256=sha(args.engine), accepted=[], rejected=[], plies=0, samples=0
    )
    with Engine(args.engine) as e:
        for file in files:
            record = json.loads(file.read_text())
            valid = True
            if "error" in record:
                result["rejected"].append(dict(file=file.name, error=record["error"]))
                continue
            for gi, game in enumerate(record["games"]):
                p = e.call("position", position=game["initial"])
                samples = {s["ply"]: s for s in game["samples"]}
                if len(samples) != len(game["samples"]) or any(
                    type(ply) is not int or not 0 <= ply < len(game["moves"])
                    for ply in samples
                ):
                    result["rejected"].append(
                        dict(
                            file=file.name, game=gi, error="invalid sample ply indices"
                        )
                    )
                    valid = False
                    break
                for ply, m in enumerate(game["moves"]):
                    try:
                        if ply in samples and samples[ply]["position"] != {
                            k: v for k, v in p.items() if k != "history"
                        }:
                            raise ValueError("sample position differs from replay")
                        p = e.call("play", move=m)
                        if min(n for h in p["hand"] for n in h) < 0:
                            raise ValueError("negative hand")
                    except ValueError as exc:
                        result["rejected"].append(
                            dict(
                                file=file.name, game=gi, ply=ply, move=m, error=str(exc)
                            )
                        )
                        valid = False
                        break
                if not valid:
                    break
                if p != game["final"]:
                    raise ValueError(f"{file}: final state mismatch")
            if valid:
                atomic_json(args.out / file.name, record)
                result["accepted"].append(dict(file=file.name, sha256=sha(file)))
                result["plies"] += sum(len(g["moves"]) for g in record["games"])
                result["samples"] += sum(len(g["samples"]) for g in record["games"])
    atomic_json(args.out / "validation.json", result)
    print(
        json.dumps(
            dict(
                accepted=len(result["accepted"]),
                rejected=len(result["rejected"]),
                plies=result["plies"],
                samples=result["samples"],
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
