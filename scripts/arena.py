"""Reproducible paired matches with resumable game files and explicit adjudication."""

from __future__ import annotations
import argparse
import collections
import hashlib
import inspect
import json
import random
import statistics
import time
from pathlib import Path
from client import Engine, ROOT, atomic_json, replay
from resources import check_space
from deployment import (
    DeploymentEngine,
    draft_opening,
    partial_draft_opening,
    initial_draft_opening,
)

from opening_families import FAMILIES, family_opening, position_types

RULES = "product-advanced-2026-09-all-betrayal-v1"


def engine_flags(model, phase="after-draft", mode=None):
    flags = [f"--{mode}-search"] if mode else []
    if model:
        flags += [
            "--model-after-draft" if phase == "after-draft" else "--model",
            str(model),
        ]
    return flags


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def opening(engine, seed, family="template"):
    if family != "template":
        return family_opening(engine, seed, family)
    rng = random.Random(seed)
    initial = engine.call("new", first=seed % 2)
    moves = []
    # Balanced templates: back rank, middle supports, front pawns. Vary files and reserves.
    back = rng.sample(list(range(9)), 4)
    middle = rng.sample(list(range(9)), 3)
    front = rng.sample(list(range(9)), 5)
    squares = (
        [72 + q for q in back[:3]]
        + [63 + q for q in middle]
        + [54 + q for q in front]
        + [72 + back[3]]
    )
    kinds = [0, 1, 2, 4, 5, 6, 9, 9, 8, 11, 7, 3]
    if seed % 3 == 1:
        squares = [q // 9 * 9 + 8 - q % 9 for q in squares]
    swap = rng.randrange(3, 6)
    kinds[swap], kinds[swap + 1] = kinds[swap + 1], kinds[swap]
    count = 8 + seed % 5
    for i in range(count):
        for _ in range(2):
            state = engine.call("state")
            c = state["turn"]
            to = squares[i] if c == 0 else 80 - squares[i]
            legal = engine.call("legal")
            selected = [
                m
                for m in legal
                if m["action"] == "drop"
                and m["piece"] == kinds[i]
                and m["to"] == to
                and not m["betray"]
            ]
            if not selected:
                selected = [
                    m
                    for m in legal
                    if m["action"] == "drop"
                    and m["piece"] == kinds[i]
                    and not m["betray"]
                ]
            if not selected:
                raise ValueError("opening template is not legal")
            m = selected[0]
            engine.call("play", move=m)
            moves.append(m)
    while engine.call("state")["draft"]:
        m = next(m for m in engine.call("legal") if m["action"] == "done")
        engine.call("play", move=m)
        moves.append(m)
    return engine.call("state"), dict(initial=initial, moves=moves)


def winner(state, reason):
    if reason in ("checkmate", "stalemate"):
        return 1 - state["turn"]
    if reason == "capture":
        present = {
            ((p - 1) // 14)
            for tower in state["board"]
            for p in tower
            if (p - 1) % 14 == 0
        }
        return next(iter(present)) if len(present) == 1 else None
    return None


def play_game(
    a,
    b,
    ref,
    start,
    milliseconds,
    max_plies,
    a_side,
    sample=False,
    exploration=0,
    seed=0,
    hash_mb=32,
):
    rng = random.Random(seed)
    for e in (a, b, ref):
        e.call("position", position=start)
    record = dict(
        initial=start, moves=[], samples=[], timings=[], reason="limit", winner=None
    )
    for ply in range(max_plies):
        status = ref.call("status")
        if status["outcome"] != "ongoing":
            record["reason"] = status["outcome"]
            break
        state = ref.call("state")
        player = a if state["turn"] == a_side else b
        began = time.monotonic()
        result = player.call(
            "search",
            ms=milliseconds,
            hash_mb=hash_mb,
            timeout=max(10, milliseconds / 1000 + 5),
        )
        elapsed = (time.monotonic() - began) * 1000
        legal = ref.call("legal")
        if result["move"] not in legal:
            raise ValueError("engine returned illegal move")
        # Host scheduling is reported separately from the engine's internal clock.
        record["timings"].append(
            dict(
                wall_ms=elapsed,
                engine_ms=result["elapsed_ms"],
                depth=result["depth"],
                nodes=result["nodes"],
            )
        )
        if sample:
            compact = {k: v for k, v in state.items() if k != "history"}
            record["samples"].append(
                dict(
                    ply=ply,
                    position=compact,
                    score=result["score"],
                    depth=result["depth"],
                    position_types=position_types(
                        state, status["check"], any(m["betray"] for m in legal)
                    ),
                )
            )
        if exploration and rng.random() < exploration:
            tactical = [
                m
                for m in legal
                if m["betray"]
                or (
                    m["action"] == "stack"
                    and state["board"][m["to"]]
                    and (state["board"][m["to"]][-1] - 1) // 14 != state["turn"]
                )
            ]
            result["move"] = rng.choice(
                tactical if tactical and rng.random() < 0.5 else legal
            )
        for e in (a, b, ref):
            e.call("play", move=result["move"])
        record["moves"].append(result["move"])
    record["final"] = ref.call("state")
    status = ref.call("status")
    if status["outcome"] != "ongoing":
        record["reason"] = status["outcome"]
    record["winner"] = winner(record["final"], record["reason"])
    return record


def summarize(directory, expected_pairs):
    records = [
        json.loads(p.read_text()) for p in sorted(Path(directory).glob("pair-*.json"))
    ]
    scores = []
    clusters = collections.defaultdict(list)
    reasons = collections.Counter()
    failures = 0
    for record in records:
        if "error" in record:
            failures += 1
            continue
        points = []
        for game in record["games"]:
            reasons[game["reason"]] += 1
            points.append(
                0.5
                if game["winner"] is None
                else float(game["winner"] == game["a_side"])
            )
        scores.append(statistics.mean(points))
        clusters[record.get("source_group", str(len(scores)))].append(scores[-1])
    interval = None
    if len(clusters) > 1:
        rng = random.Random(82026)
        groups = list(clusters.values())
        boot = []
        for _ in range(4000):
            sampled = rng.choices(groups, k=len(groups))
            boot.append(sum(map(sum, sampled)) / sum(map(len, sampled)))
        boot.sort()
        interval = [boot[100], boot[3899]]
    config_path = Path(directory) / "config.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    stage = config.get("trial_stage", "screen")
    passes = (
        len(scores) == expected_pairs
        and failures == 0
        and interval is not None
        and interval[0] > 0.5
        and not (Path(directory) / "INVALIDATED.txt").exists()
    )
    summary = dict(
        expected_pairs=expected_pairs,
        complete_pairs=len(scores),
        failed_pairs=failures,
        score=statistics.mean(scores) if scores else None,
        ci95=interval,
        reasons=dict(reasons),
        interval_method="percentile bootstrap by source group; fixed 4000 replicates",
        independent_source_groups=len(clusters),
        trial_stage=stage,
        passes_score_threshold=passes,
        adopted=passes and stage == "confirmation" and len(clusters) >= 500,
    )
    atomic_json(Path(directory) / "summary.json", summary)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, default=ROOT / "build/kokoriko")
    ap.add_argument("--b", type=Path, default=ROOT / "build/kokoriko")
    for side in ("a", "b"):
        ap.add_argument(f"--model-{side}", type=Path)
        ap.add_argument(f"--deployment-table-{side}", type=Path)
        ap.add_argument(
            f"--model-phase-{side}",
            choices=["after-draft", "always"],
            default="after-draft",
        )
        ap.add_argument(
            f"--standard-{side}",
            action="store_true",
            help="use the bundled model after deployment, matching kokoriko.sh",
        )
    ap.add_argument(
        "--opening-family", choices=["template", "mixed", *FAMILIES], default="template"
    )
    ap.add_argument("--opening-book", type=Path)
    for side in ("a", "b"):
        ap.add_argument(f"--qchecks-{side}", type=int, choices=[0, 1, 2], default=0)
        ap.add_argument(f"--no-score-cache-{side}", action="store_true")
        ap.add_argument(f"--no-move-cache-{side}", action="store_true")
        ap.add_argument(f"--no-exposure-order-{side}", action="store_true")
        ap.add_argument(f"--qevasions-{side}", type=int, choices=range(9), default=0)
        ap.add_argument(f"--network-diff-{side}", action="store_true")
    ap.add_argument("--ref", type=Path, default=ROOT / "build/kokoriko")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pairs", type=int, default=10)
    ap.add_argument("--start-pair", type=int, default=0)
    ap.add_argument("--end-pair", type=int)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--ms", type=int, default=25)
    ap.add_argument("--hash-mb", type=int, default=32)
    ap.add_argument("--max-plies", type=int, default=300)
    ap.add_argument("--seed", type=int, default=10000)
    ap.add_argument("--samples", action="store_true")
    ap.add_argument("--explore", type=float, default=0)
    ap.add_argument("--confirmation", action="store_true")
    ap.add_argument(
        "--deployment-a",
        choices=["search", "8", "12", "18", "tower", "flank", "adaptive"],
    )
    ap.add_argument(
        "--deployment-b",
        choices=["search", "8", "12", "18", "tower", "flank", "adaptive"],
    )
    ap.add_argument(
        "--draft-start", choices=["initial", "marshal", "partial"], default="marshal"
    )
    for side in ("a", "b"):
        modes = ap.add_mutually_exclusive_group()
        modes.add_argument(f"--tuned-{side}", action="store_true")
        modes.add_argument(f"--basic-{side}", action="store_true")
        modes.add_argument(f"--selective-{side}", action="store_true")
    args = ap.parse_args()
    if args.stride < 1:
        ap.error("stride must be positive")
    if bool(args.deployment_a) != bool(args.deployment_b):
        ap.error("specify both deployment policies")
    if args.draft_start != "marshal" and not args.deployment_a:
        ap.error("draft starts require both deployment policies")
    if args.pairs < 1:
        ap.error("pairs must be positive")
    if not 1 <= args.hash_mb <= 512:
        ap.error("hash-mb must be in 1..512")
    unique_limit = {"initial": 2, "marshal": 162}.get(args.draft_start)
    if (
        args.deployment_a
        and not args.opening_book
        and unique_limit
        and args.pairs > unique_limit
    ):
        ap.error(
            f"{args.draft_start} starts have only {unique_limit} unique positions; use --draft-start partial for larger trials"
        )
    if args.opening_family != "template" and (args.deployment_a or args.opening_book):
        ap.error("opening-family cannot be combined with a book or deployment trial")
    policy_tables = {}
    for side in ("a", "b"):
        path = getattr(args, f"deployment_table_{side}")
        if path and getattr(args, f"deployment_{side}") != "adaptive":
            ap.error("deployment-table requires adaptive policy")
        policy_tables[side] = (
            json.loads(path.read_text())["responses"] if path else None
        )
    flags = {}
    search_options = {}
    for side in ("a", "b"):
        if getattr(args, f"standard_{side}"):
            if (
                getattr(args, f"model_{side}")
                or getattr(args, f"model_phase_{side}") != "after-draft"
                or getattr(args, f"basic_{side}")
                or getattr(args, f"selective_{side}")
            ):
                ap.error(
                    f"--standard-{side} requires bundled after-draft model and tuned search"
                )
            setattr(args, f"model_{side}", ROOT / "engine/models/default.nnue")
        mode = (
            "basic"
            if getattr(args, f"basic_{side}")
            else "selective"
            if getattr(args, f"selective_{side}")
            else "tuned"
            if getattr(args, f"tuned_{side}") or getattr(args, f"standard_{side}")
            else None
        )
        flags[side] = engine_flags(
            getattr(args, f"model_{side}"), getattr(args, f"model_phase_{side}"), mode
        )
        if getattr(args, f"network_diff_{side}"):
            flags[side].append("--network-diff")
        search_options[side] = dict(
            qchecks=getattr(args, f"qchecks_{side}"),
            reuse_scores=not getattr(args, f"no_score_cache_{side}"),
            reuse_moves=not getattr(args, f"no_move_cache_{side}"),
            exposure_order=not getattr(args, f"no_exposure_order_{side}"),
            qevasions=getattr(args, f"qevasions_{side}"),
        )
    generate = (
        {
            "initial": initial_draft_opening,
            "marshal": draft_opening,
            "partial": partial_draft_opening,
        }[args.draft_start]
        if args.deployment_a
        else opening
    )
    check_space()
    args.out.mkdir(parents=True, exist_ok=True)
    config = dict(
        rules=RULES,
        a=str(args.a.resolve()),
        b=str(args.b.resolve()),
        a_sha256=sha(args.a),
        b_sha256=sha(args.b),
        referee_sha256=sha(args.ref),
        pairs=args.pairs,
        ms=args.ms,
        max_plies=args.max_plies,
        seed=args.seed,
        replay_policy="repetition requests replay; experiment scores unresolved original as half point, no replay",
        samples=args.samples,
        exploration=args.explore,
        threads=1,
        hash_mb=args.hash_mb,
        engine_args=flags,
        search_options=search_options,
        opening_helpers_sha256=sha(ROOT / "scripts/opening_families.py"),
        arena_source_sha256=sha(Path(__file__)),
        opening_family=(
            "book"
            if args.opening_book
            else f"draft-{args.draft_start}"
            if args.deployment_a
            else args.opening_family
        ),
        opening_generator_sha256=hashlib.sha256(
            inspect.getsource(generate).encode()
        ).hexdigest(),
    )
    if args.opening_book:
        config["opening_book_sha256"] = sha(args.opening_book)
    if args.tuned_a or args.tuned_b:
        config["tuned_search"] = dict(a=args.tuned_a, b=args.tuned_b)
    if args.basic_a or args.basic_b:
        config["basic_search"] = dict(a=args.basic_a, b=args.basic_b)
    if args.selective_a or args.selective_b:
        config["selective_search"] = dict(a=args.selective_a, b=args.selective_b)
    if args.confirmation:
        if args.pairs < 500:
            ap.error("confirmation needs at least 500 pairs")
        config["trial_stage"] = "confirmation"
    if args.deployment_a:
        config["deployment"] = dict(
            a=args.deployment_a,
            b=args.deployment_b,
            source_sha256=sha(ROOT / "scripts/deployment.py"),
        )
    for side in ("a", "b"):
        path = getattr(args, f"deployment_table_{side}")
        if path:
            config[f"deployment_table_{side}_sha256"] = sha(path)
    if args.model_a:
        config["model_a_sha256"] = sha(args.model_a)
    if args.model_b:
        config["model_b_sha256"] = sha(args.model_b)
    path = args.out / "config.json"
    if path.exists() and json.loads(path.read_text()) != config:
        raise SystemExit(
            "configuration differs from existing run; use a new output directory"
        )
    if (args.out / "INVALIDATED.txt").exists():
        raise SystemExit("trial invalidated; choose a new output directory")
    if not path.exists():
        atomic_json(path, config)
    opening_path = args.out / "openings.json"
    if not opening_path.exists():
        starts = []
        unique = set()
        book = (
            json.loads(args.opening_book.read_text())["positions"]
            if args.opening_book
            else None
        )
        if book is not None and len(book) < args.pairs:
            raise ValueError("opening book has too few independent positions")
        with Engine(args.ref) as referee:
            for pair in range(args.pairs):
                metadata = {}
                if book is not None:
                    entry = book[pair]
                    start, setup = entry["position"], entry["setup"]
                    if replay(referee, setup) != start:
                        raise ValueError("opening book replay does not match position")
                    metadata = {
                        k: v for k, v in entry.items() if k not in ("position", "setup")
                    }
                elif args.deployment_a:
                    start, setup = generate(referee, args.seed + pair)
                else:
                    start, setup = opening(
                        referee, args.seed + pair, args.opening_family
                    )
                key = json.dumps(
                    {k: v for k, v in start.items() if k != "history"}, sort_keys=True
                )
                if key in unique:
                    raise ValueError("duplicate opening in trial")
                unique.add(key)
                starts.append(dict(position=start, setup=setup, **metadata))
        atomic_json(opening_path, starts)
    starts = json.loads(opening_path.read_text())
    if len(starts) != args.pairs:
        raise ValueError("wrong opening count")
    with (
        DeploymentEngine(
            args.a,
            args.deployment_a or "search",
            args=flags["a"],
            search_options=search_options["a"],
            policy_table=policy_tables["a"],
        ) as a,
        DeploymentEngine(
            args.b,
            args.deployment_b or "search",
            args=flags["b"],
            search_options=search_options["b"],
            policy_table=policy_tables["b"],
        ) as b,
        Engine(args.ref) as ref,
    ):
        for pair in range(
            args.start_pair,
            args.pairs if args.end_pair is None else min(args.pairs, args.end_pair),
            args.stride,
        ):
            dest = args.out / f"pair-{pair:05d}.json"
            if dest.exists():
                continue
            check_space()
            seed = args.seed + pair
            try:
                start = starts[pair]["position"]
                opening_record = starts[pair]["setup"]
                games = []
                for a_side in (0, 1):
                    game = play_game(
                        a,
                        b,
                        ref,
                        start,
                        args.ms,
                        args.max_plies,
                        a_side,
                        args.samples,
                        args.explore,
                        seed * 2 + a_side,
                        args.hash_mb,
                    )
                    game["a_side"] = a_side
                    games.append(game)
                atomic_json(
                    dest,
                    dict(
                        pair=pair,
                        seed=seed,
                        opening=opening_record,
                        games=games,
                        opening_family=opening_record.get(
                            "family", config["opening_family"]
                        ),
                        source_group=starts[pair].get(
                            "source_group", f"{args.seed + pair}"
                        ),
                        source_opening=starts[pair].get("source_opening", start),
                        position_types=starts[pair].get("tags", []),
                    ),
                )
            except (ValueError, RuntimeError, TimeoutError) as exc:
                atomic_json(dest, dict(pair=pair, seed=seed, error=str(exc)))
                raise
            print(
                json.dumps(
                    dict(
                        pair=pair + 1,
                        total=args.pairs,
                        reasons=[g["reason"] for g in games],
                        plies=[len(g["moves"]) for g in games],
                    )
                ),
                flush=True,
            )
    print(json.dumps(summarize(args.out, args.pairs), indent=2))


if __name__ == "__main__":
    main()
