"""Reproducible deployment alternatives, evaluated with the same battle engine."""

from client import Engine

ROSTER = [0, 1, 2, 4, 5, 6, 9, 9, 8, 11, 7, 3, 9, 9, 5, 5, 10, 12]
TARGETS = [76, 73, 79, 65, 67, 69, 57, 59, 58, 66, 68, 60, 55, 61, 64, 70, 75, 77]


def choose_balanced(state, moves, target=12):
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
    for kind, square in zip(ROSTER[:target], TARGETS[:target]):
        wanted[kind] += 1
        if count[kind] >= wanted[kind]:
            continue
        choices = [
            m
            for m in moves
            if m["action"] == "drop"
            and m["piece"] == kind
            and not state["board"][m["to"]]
        ]
        if not choices:
            continue
        q = square if state["turn"] == 0 else 80 - square
        return min(
            choices,
            key=lambda m: abs(m["to"] // 9 - q // 9) * 3 + abs(m["to"] % 9 - q % 9),
        )
    return next((m for m in moves if m["action"] == "done"), moves[0])


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


class DeploymentEngine(Engine):
    def __init__(self, executable, policy, args=()):
        super().__init__(executable, args)
        self.policy = policy
        self.state = None

    def call(self, cmd, timeout=30, **kwargs):
        if cmd == "search" and self.state["draft"] and self.policy != "search":
            legal = super().call("legal")
            move = choose_balanced(self.state, legal, int(self.policy))
            return dict(move=move, score=0, depth=0, nodes=0, elapsed_ms=0, pv=[move])
        result = super().call(cmd, timeout, **kwargs)
        if cmd in ("new", "position", "play", "undo", "state"):
            self.state = result
        return result
