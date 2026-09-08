"""Resumable paired-game SPSA for bounded strategic evaluation coefficients."""

import argparse
import json
import random
from pathlib import Path

from arena import engine_flags, play_game, sha
from client import Engine, atomic_json
from opening_families import family_opening
from resources import check_space
from train_linear import export, read_weights


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine", type=Path, required=True)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--iterations", type=int, default=20)
    ap.add_argument("--ms", type=int, default=100)
    ap.add_argument("--max-plies", type=int, default=120)
    ap.add_argument("--seed", type=int, default=171000)
    ap.add_argument("--indices", default="45,46,47,48,49,50,51,52")
    args = ap.parse_args()
    weights = read_weights(args.model)
    indices = [int(i) for i in args.indices.split(",")]
    if (
        args.iterations < 1
        or args.ms < 1
        or any(i < 0 or i >= len(weights) for i in indices)
    ):
        ap.error("invalid tuning limits or indices")
    config = dict(
        engine_sha256=sha(args.engine),
        model_sha256=sha(args.model),
        iterations=args.iterations,
        ms=args.ms,
        max_plies=args.max_plies,
        seed=args.seed,
        indices=indices,
        algorithm="paired SPSA",
        a=2,
        c=2,
        bounds=[-100, 100],
        source_sha256=sha(Path(__file__)),
    )
    cp = args.out / "config.json"
    if cp.exists() and json.loads(cp.read_text()) != config:
        raise ValueError("tuning configuration changed")
    atomic_json(cp, config)
    state_path = args.out / "state.json"
    state = (
        json.loads(state_path.read_text())
        if state_path.exists()
        else dict(iteration=0, weights=weights, history=[])
    )
    for iteration in range(state["iteration"], args.iterations):
        check_space()
        rng = random.Random(args.seed + iteration)
        c = 2 / (iteration + 1) ** 0.101
        a = 2 / (iteration + 1) ** 0.602
        signs = {i: rng.choice([-1, 1]) for i in indices}
        plus, minus = (
            list(map(round, state["weights"])),
            list(map(round, state["weights"])),
        )
        for i in indices:
            plus[i] = round(max(-100, min(100, state["weights"][i] + c * signs[i])))
            minus[i] = round(max(-100, min(100, state["weights"][i] - c * signs[i])))
        pp, mp = args.out / "plus.nnue", args.out / "minus.nnue"
        export(plus, pp)
        export(minus, mp)
        record_path = args.out / f"iteration-{iteration:04}.json"
        if record_path.exists():
            record = json.loads(record_path.read_text())
            if record["plus"] != plus or record["minus"] != minus:
                raise ValueError("resumed perturbation mismatch")
        else:
            games = []
            with (
                Engine(args.engine) as ref,
                Engine(args.engine, engine_flags(pp, mode="tuned")) as pe,
                Engine(args.engine, engine_flags(mp, mode="tuned")) as me,
            ):
                start, setup = family_opening(ref, args.seed + iteration, "mixed")
                for side in (0, 1):
                    game = play_game(pe, me, ref, start, args.ms, args.max_plies, side)
                    game["a_side"] = side
                    games.append(game)
            record = dict(plus=plus, minus=minus, setup=setup, games=games)
            atomic_json(record_path, record)
        # A draw is zero; color-paired wins minus losses estimate the signed response.
        response = (
            sum(
                0 if g["winner"] is None else (1 if g["winner"] == g["a_side"] else -1)
                for g in record["games"]
            )
            / 2
        )
        for i in indices:
            actual_c = (plus[i] - minus[i]) / 2
            if actual_c:
                state["weights"][i] = max(
                    -100, min(100, state["weights"][i] + a * response / actual_c)
                )
        state["iteration"] = iteration + 1
        state["history"].append(dict(iteration=iteration, response=response, a=a, c=c))
        atomic_json(state_path, state)
        print(json.dumps(state["history"][-1]), flush=True)
    digest = export(list(map(round, state["weights"])), args.out / "model-int.nnue")
    atomic_json(
        args.out / "result.json",
        dict(
            model_sha256=digest,
            weights=list(map(round, state["weights"])),
            iterations=args.iterations,
            adopted=False,
        ),
    )


if __name__ == "__main__":
    main()
