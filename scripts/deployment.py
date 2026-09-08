"""Reproducible deployment alternatives, evaluated with the same battle engine."""

from client import Engine
import random

ROSTER = [0, 1, 2, 4, 5, 6, 9, 9, 8, 11, 7, 3, 9, 9, 5, 5, 10, 12]
TARGETS = [76, 73, 79, 65, 67, 69, 57, 59, 58, 66, 68, 60, 55, 61, 64, 70, 75, 77]


def choose_balanced(
    state, moves, target=12, roster=ROSTER, targets=TARGETS, stacks=False
):
    count = [0] * 14
    for tower in state["board"]:
        for p in tower:
            if (p - 1) // 14 == state["turn"]:
                count[(p - 1) % 14] += 1
    if sum(count) >= target:
        done = next((m for m in moves if m["action"] == "done"), None)
        if done:
            return done
    wanted = [0] * 14
    for kind, square in zip(roster[:target], targets[:target]):
        wanted[kind] += 1
        if count[kind] >= wanted[kind]:
            continue
        choices = [
            m
            for m in moves
            if m["action"] == "drop"
            and m["piece"] == kind
            and (stacks or not state["board"][m["to"]])
        ]
        if not choices:
            continue
        q = square if state["turn"] == 0 else 80 - square
        return min(
            choices,
            key=lambda m: abs(m["to"] // 9 - q // 9) * 3 + abs(m["to"] % 9 - q % 9),
        )
    return next((m for m in moves if m["action"] == "done"), moves[0])


def opponent_profile(state):
    enemy = 1 - state["turn"]
    towers = [
        (q, t) for q, t in enumerate(state["board"]) if t and (t[-1] - 1) // 14 == enemy
    ]
    if any(len(t) >= 2 for _, t in towers):
        return "tower"
    if len(towers) >= 10:
        return "wide"
    return "reserve"


def choose_deployment(state, moves, policy, table=None):
    # This candidate is measured against each fixed policy before adoption.
    if policy == "adaptive":
        profile = opponent_profile(state)
        policy = (table or {}).get(
            profile, {"tower": "18", "wide": "12", "reserve": "8"}[profile]
        )
        if policy not in ("8", "12", "18", "tower", "flank"):
            raise ValueError("invalid deployment response")
    if policy == "tower":
        return choose_balanced(
            state,
            moves,
            10,
            [0, 1, 9, 13, 2, 9, 4, 5, 8, 11],
            [76, 67, 67, 67, 69, 69, 65, 57, 73, 79],
            True,
        )
    if policy == "flank":
        enemy = 1 - state["turn"]
        enemy_files = [
            q % 9
            for q, t in enumerate(state["board"])
            for p in t
            if (p - 1) // 14 == enemy
        ]
        right = sum(enemy_files) > 4 * len(enemy_files)
        targets = [
            q // 9 * 9 + (min(8, q % 9 + 1) if right else max(0, q % 9 - 1))
            for q in TARGETS
        ]
        return choose_balanced(state, moves, 12, targets=targets)
    return choose_balanced(state, moves, int(policy))


def draft_opening(engine, seed):
    initial = engine.call("new", first=seed % 2)
    moves = []
    files = [(seed // 2) % 9, (seed // 18) % 9]
    for _ in range(2):
        state = engine.call("state")
        side = state["turn"]
        q = (72 if side == 0 else 0) + files[side]
        m = next(
            m
            for m in engine.call("legal")
            if m["action"] == "drop" and m["piece"] == 0 and m["to"] == q
        )
        engine.call("play", move=m)
        moves.append(m)
    return engine.call("state"), dict(initial=initial, moves=moves)


def initial_draft_opening(engine, seed):
    state = engine.call("new", first=seed % 2)
    return state, dict(initial=state, moves=[])


def partial_draft_opening(engine, seed):
    """Reach varied unfinished deployments through legal play, including stacks."""
    state, setup = draft_opening(engine, seed)
    rng = random.Random(seed)
    for _ in range(2 + 2 * (seed % 6)):
        legal = [m for m in engine.call("legal") if m["action"] == "drop"]
        if not legal:
            break
        move = rng.choice(legal)
        state = engine.call("play", move=move)
        setup["moves"].append(move)
    if not state["draft"]:
        raise ValueError("partial deployment unexpectedly reached battle")
    return state, setup


class DeploymentEngine(Engine):
    def __init__(
        self, executable, policy, args=(), search_options=None, policy_table=None
    ):
        super().__init__(executable, args)
        self.policy = policy
        if policy_table is not None and (
            not isinstance(policy_table, dict)
            or any(k not in ("reserve", "wide", "tower") for k in policy_table)
            or any(
                v not in ("8", "12", "18", "tower", "flank")
                for v in policy_table.values()
            )
        ):
            self.close()
            raise ValueError("invalid deployment response table")
        self.policy_table = policy_table
        self.search_options = search_options or {}
        self.state = None

    def call(self, cmd, timeout=30, **kwargs):
        if cmd == "search":
            kwargs = {**self.search_options, **kwargs}
        if cmd == "search" and self.state["draft"] and self.policy != "search":
            legal = super().call("legal")
            move = choose_deployment(self.state, legal, self.policy, self.policy_table)
            return dict(move=move, score=0, depth=0, nodes=0, elapsed_ms=0, pv=[move])
        result = super().call(cmd, timeout, **kwargs)
        if cmd in ("new", "position", "play", "undo", "state"):
            self.state = result
        return result
