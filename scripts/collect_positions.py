"""Collect stratified starting positions with complete legal replay provenance."""

import argparse
import collections
import hashlib
import json
from pathlib import Path

from arena import sha
from client import Engine, atomic_json, replay
from opening_families import position_types
from resources import check_space

TYPES = (
    "betrayal",
    "mixed_tower",
    "check",
    "thick_tower",
    "endgame",
    "reserve_rich",
    "balanced",
)


def source_group(record):
    if "source_group" in record:
        return str(record["source_group"])
    trace = [dict(initial=g["initial"], moves=g["moves"]) for g in record["games"]]
    return hashlib.sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest()


def collect(directories, engine_path, per_type, per_source, every, types=TYPES):
    counts = collections.Counter()
    selected, inputs, rejected = [], [], []
    seen, source_counts = set(), collections.Counter()
    with Engine(engine_path) as engine:
        for directory in directories:
            for path in sorted(Path(directory).glob("pair-*.json")):
                record = json.loads(path.read_text())
                inputs.append(
                    dict(
                        directory=Path(directory).name, file=path.name, sha256=sha(path)
                    )
                )
                if "error" in record:
                    rejected.append(dict(file=path.name, error="failed source pair"))
                    continue
                group = source_group(record)
                if source_counts[group] >= per_source:
                    continue
                for game_index, game in enumerate(record["games"]):
                    setup = record.get("opening")
                    if not setup or "initial" not in setup or "moves" not in setup:
                        rejected.append(
                            dict(file=path.name, error="missing opening replay")
                        )
                        continue
                    position = replay(engine, setup)
                    if position != game["initial"]:
                        rejected.append(
                            dict(file=path.name, error="opening replay mismatch")
                        )
                        continue
                    prefix = list(setup["moves"])
                    for ply, move in enumerate(game["moves"]):
                        if (
                            not position["draft"]
                            and ply % every == 0
                            and source_counts[group] < per_source
                        ):
                            legal = engine.call("legal")
                            if not legal:
                                break
                            tags = position_types(
                                position,
                                engine.call("status")["check"],
                                any(m["betray"] for m in legal),
                            )
                            category = next(
                                (
                                    t
                                    for t in types
                                    if t in tags and counts[t] < per_type
                                ),
                                None,
                            )
                            key = json.dumps(
                                {k: v for k, v in position.items() if k != "history"},
                                sort_keys=True,
                            )
                            if category and key not in seen:
                                selected.append(
                                    dict(
                                        position=position,
                                        setup=dict(
                                            initial=setup["initial"],
                                            moves=list(prefix),
                                            family=record.get(
                                                "opening_family", "legacy"
                                            ),
                                        ),
                                        family=category,
                                        tags=tags,
                                        source_group=group,
                                        source_opening=record.get(
                                            "source_opening",
                                            record["games"][0]["initial"],
                                        ),
                                        source=dict(
                                            file=path.name,
                                            sha256=sha(path),
                                            game=game_index,
                                            ply=ply,
                                        ),
                                    )
                                )
                                counts[category] += 1
                                source_counts[group] += 1
                                seen.add(key)
                        try:
                            position = engine.call("play", move=move)
                        except ValueError as error:
                            rejected.append(
                                dict(
                                    file=path.name,
                                    game=game_index,
                                    ply=ply,
                                    error=str(error),
                                )
                            )
                            break
                        prefix.append(move)
                    if source_counts[group] >= per_source:
                        break
                if all(counts[t] >= per_type for t in types):
                    break
    return dict(
        positions=selected,
        counts=dict(counts),
        missing_types=[t for t in types if not counts[t]],
        source_groups=len(source_counts),
        source_files=inputs,
        rejected=rejected,
        referee_sha256=sha(engine_path),
        selection=dict(
            per_type=per_type, per_source=per_source, every=every, types=list(types)
        ),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, action="append", required=True)
    ap.add_argument("--engine", type=Path, default=Path("build/kokoriko"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--per-type", type=int, default=16)
    ap.add_argument("--per-source", type=int, default=2)
    ap.add_argument("--every", type=int, default=3)
    ap.add_argument("--types", nargs="+", choices=TYPES, default=TYPES)
    args = ap.parse_args()
    if min(args.per_type, args.per_source, args.every) < 1:
        ap.error("selection limits must be positive")
    check_space()
    report = collect(
        args.data, args.engine, args.per_type, args.per_source, args.every, args.types
    )
    if not report["positions"]:
        raise ValueError("no legal nonterminal positions found")
    if args.out.exists() and json.loads(args.out.read_text()) != report:
        raise ValueError("existing position book differs; choose a new output")
    atomic_json(args.out, report)
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in ("positions", "source_files", "rejected")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
