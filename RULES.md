# KOKORIKO Gungi rules

Rule version: `product-advanced-2026-09-all-betrayal-v1`

The engine implements the 2022 commercial game’s advanced rules. R-numbers refer to [sources](docs/SOURCES.md); rule IDs map to tests in `tests/rules_test.cpp`. Betrayal and stalemate interpretations below are engine choices, not additional official rulings.

## Board and coordinates

The board is 9×9, with up to three pieces per square, ordered from bottom to top. Side 0 moves forward from the bottom toward the top; side 1 moves from the top toward the bottom. API square indices run from 0 to 80 in row order from the top (`row * 9 + column`). Side identity and turn order are independent: `first` identifies the original first player, and `turn` identifies the current player.

## Movement table

Sources: R1 pp. 3–5, 8, 12. `t` is the moving piece's starting tier. Unless an interval is given, a distance includes every square from one through the limit. Forward, backward, left, and right are relative to the piece's owner. Ordinary movement cannot jump over intervening pieces. Tests: `movement_table`, `movement_symmetry`, `blocking`.

The labels below are the symbols printed on the pieces. Orthogonal means forward, backward, left, and right; diagonal includes both forward and backward diagonals.

| ID | Piece label | Count per side | Tier 1 | Tier 2 | Tier 3 |
| --- | --- | --- | --- | --- | --- |
| 0 | 帥 | 1 | All eight directions 1 | All eight directions 2 | All eight directions 3 |
| 1 | 大 | 1 | Orthogonal unlimited; diagonal 1 | Orthogonal unlimited; diagonal 2 | Orthogonal unlimited; diagonal 3 |
| 2 | 中 | 1 | Diagonal unlimited; orthogonal 1 | Diagonal unlimited; orthogonal 2 | Diagonal unlimited; orthogonal 3 |
| 3 | 小 | 2 | Orthogonal and forward diagonal 1 | Orthogonal and forward diagonal 2 | Orthogonal and forward diagonal 3 |
| 4 | 侍 | 2 | Forward, backward, and forward diagonal 1 | Forward, backward, and forward diagonal 2 | Forward, backward, and forward diagonal 3 |
| 5 | 槍 | 3 | Forward 2; backward and forward diagonal 1 | Forward 3; backward and forward diagonal 2 | Forward 4; backward and forward diagonal 3 |
| 6 | 馬 | 2 | Forward/backward 2; left/right 1 | Forward/backward 3; left/right 2 | Forward/backward 4; left/right 3 |
| 7 | 忍 | 2 | Diagonal 2 | Diagonal 3 | Diagonal 4 |
| 8 | 砦 | 2 | Forward, left/right, and backward diagonal 1 | Forward, left/right, and backward diagonal 2 | Forward, left/right, and backward diagonal 3 |
| 9 | 兵 | 4 | Forward/backward 1 | Forward/backward 2 | Forward/backward 3 |
| 10 | 砲 | 1 | Forward exactly 3; left/right/backward 1 | Forward 3–4; left/right/backward 2 | Forward 3–5; left/right/backward 3 |
| 11 | 弓 | 2 | Archer forward paths at tier 1; backward 1 | Archer forward paths at tier 2; backward 2 | Archer forward paths at tier 3; backward 3 |
| 12 | 筒 | 1 | Forward exactly 2; backward diagonal 1 | Forward 2–3; backward diagonal 2 | Forward 2–4; backward diagonal 3 |
| 13 | 謀 | 1 | Forward diagonal and backward 1 | Forward diagonal and backward 2 | Forward diagonal and backward 3 |

Pieces 砲, 筒, and 弓 can jump over pieces at the same or lower tier along their special forward paths. Taller towers block those paths. Piece 砲 always skips the first two forward squares; 筒 skips the first forward square. Ordinary backward or sideways movement does not jump.

For the archer (弓), with forward represented by negative y, forward destinations are `(0, -1-k)`, `(-k, -1-k)`, and `(k, -1-k)` for `k=1..t`. A taller tower at `(0,-1)` blocks every forward path. Taller towers at `(-1,-1)` or `(1,-1)` also block the respective diagonal wing. Beyond those squares, taller towers block the corresponding paths connecting the destinations. Source: R5 diagrams 1–7. Tests: `archer_001`–`archer_007`.

## Deployment and moves

| ID / test | Rule | Source |
| --- | --- | --- |
| `draft` | Players alternate placements within their own three rows, starting with the marshal (帥). Towers remain limited to three tiers, and nothing may be placed above a marshal. No additional minimum deployment count is imposed. | R1 p. 6 |
| `draft_done` | Once the first player finishes deployment, the second may place consecutively. Deployment ends when the second player finishes. Exhausting a player's reserve is treated as finishing. Battle starts with the original first player. | R1 p. 6, R3, R4; automatic completion on reserve exhaustion is an implementation transition |
| `move_top` | Only the top piece moves. Pieces left on the origin square retain their order. | R1 pp. 8–9 |
| `stack` | A piece may stack onto a tower no taller than its starting tier, provided the result is at most three tiers. Nothing may stack above a marshal. In advanced rules, the marshal itself may stack onto other pieces. | R1 pp. 7–9, 14, R3 |
| `capture` | A capture is available if the destination's top piece is hostile and its tower is no taller than the starting tier. Remove every enemy piece there, preserve the order of friendly pieces, and place the moving piece on top. Captured pieces cannot be reused. | R1 pp. 7, 9, R3 |
| `arata` | Add one reserve piece to end the turn. It must be on or behind the row of the foremost friendly top piece, on an empty square or a tower with a friendly top. It cannot go above a marshal or a three-tier tower. | R1 pp. 10–11, R3 |
| `betrayal_all` | On the turn a tactician (謀) stacks, the player may exchange every enemy piece beneath it for matching friendly reserve pieces. Every required type and copy must be available. Declining the exchange is allowed. Dropping a tactician onto a friendly top piece also qualifies. Betrayal cannot be combined with capture. | R1 p. 13, R3; all-or-nothing exchange is this engine's interpretation |

Betrayal exchanges all enemy tiers or none. Duplicate types require duplicate reserve pieces; when dropping a tactician, deduct the dropped piece before checking the exchange.

## Check and game endings

- **Check:** discard moves that leave the marshal capturable, accounting for paths, blockers, and tower heights.
- **Loss:** checkmate, marshal capture, or resignation. Having no legal move, including drops, also loses even without check; this stalemate rule is an engine interpretation (R1 p. 13).
- **Repetition:** the fourth occurrence of the same board, reserves, turn, phase, and deployment rights requires a rematch (R1 p. 13). The initial position counts. It is not an automatic draw or loss.
- **Undo:** restores the complete previous state and repetition history. Passing during battle is prohibited.

Time controls and ply limits belong to [match testing](docs/ARENA.md).
