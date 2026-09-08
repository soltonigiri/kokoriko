"""Distinct deployment families, reached exclusively through legal engine moves."""

import random
from deployment import ROSTER, TARGETS

FAMILIES = ("balanced8", "balanced12", "balanced18", "tower", "reserve", "flank")


def family_opening(engine, seed, family="mixed"):
    mixed = family == "mixed"
    family = FAMILIES[seed % len(FAMILIES)] if mixed else family
    if family not in FAMILIES:
        raise ValueError("unknown opening family")
    rng = random.Random(seed)
    initial = engine.call("new", first=(seed // len(FAMILIES) if mixed else seed) % 2)
    moves = []
    if family == "tower":
        roster = [0, 1, 9, 13, 2, 9, 4, 5, 8, 11]
        targets = [76, 67, 67, 67, 69, 69, 65, 57, 73, 79]
    elif family == "reserve":
        roster = [0, 1, 2, 9, 13, 5]
        targets = [76, 65, 69, 58, 67, 73]
    else:
        count = (
            int(family.removeprefix("balanced"))
            if family.startswith("balanced")
            else 12
        )
        roster, targets = ROSTER[:count], TARGETS[:count]
    # Permute files while retaining repeated squares in tower deployments.
    files = list(range(9))
    rng.shuffle(files)
    if family == "flank":
        files[4], files[1] = files[1], files[4]
    targets = [q // 9 * 9 + files[q % 9] for q in targets]
    for kind, target in zip(roster, targets, strict=True):
        for _ in range(2):
            state = engine.call("state")
            to = target if state["turn"] == 0 else 80 - target
            legal = [
                m
                for m in engine.call("legal")
                if m["action"] == "drop" and not m["betray"]
            ]
            choices = [m for m in legal if m["piece"] == kind] or legal
            if not choices:
                raise ValueError("deployment family has no legal continuation")
            move = min(
                choices,
                key=lambda m: (
                    m["to"] != to,
                    abs(m["to"] // 9 - to // 9) * 3 + abs(m["to"] % 9 - to % 9),
                ),
            )
            engine.call("play", move=move)
            moves.append(move)
    for _ in range(52):
        if not engine.call("state")["draft"]:
            break
        legal = engine.call("legal")
        move = next((m for m in legal if m["action"] == "done"), None)
        if move is None:
            move = rng.choice(legal)
        engine.call("play", move=move)
        moves.append(move)
    state = engine.call("state")
    if state["draft"]:
        raise ValueError("deployment family failed to finish")
    return state, dict(initial=initial, moves=moves, family=family)


def position_types(position, check=False, betrayal=False):
    board = position["board"]
    tags = []
    if any(len(tower) == 3 for tower in board):
        tags.append("thick_tower")
    if any(len({(p - 1) // 14 for p in tower}) > 1 for tower in board):
        tags.append("mixed_tower")
    if betrayal:
        tags.append("betrayal")
    if sum(sum(hand) for hand in position["hand"]) >= 20:
        tags.append("reserve_rich")
    if check:
        tags.append("check")
    if sum(map(len, board)) <= 10:
        tags.append("endgame")
    return tags or ["balanced"]
