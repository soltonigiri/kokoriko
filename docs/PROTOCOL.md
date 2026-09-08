# Engine protocol

`build/kokoriko` reads one JSON request per line from standard input and writes a JSON response to standard output. Success uses `{"ok":true,"result":...}`; errors use `{"ok":false,"error":"..."}`. Diagnostics go to standard error. `stop` is a notification, as described below.

| cmd | Arguments | Result |
| --- | --- | --- |
| `new` | `first`: 0 or 1 | Initial position |
| `position` | `position`: a version 1 position | Validated and loaded position |
| `state` | None | Full state and repetition history |
| `legal` | None | Array of legal moves |
| `play` | `move`: a move returned by `legal` | Position after the move |
| `undo` | None | Position with the last move undone |
| `status` | None | Termination reason, check status, and evaluation from the side to move |
| `search` | `ms`, `depth`, `hash_mb`, `qdepth`, `nodes`, `tuned`, `selective` | Move, score, completed depth, nodes, elapsed time, and principal variation |
| `stop` | None | No separate response; the running search stops and returns its response |
| `perft` | `depth`: 0–5 | Leaf count at the requested depth |
| `quit` | None | Exit |

PVS is the default. Select basic search with CLI option `--basic-search` or request field `tuned:false`. `--tuned-search` or `tuned:true` explicitly selects PVS. `--selective-search` or `selective:true` adds reduced-depth probes for quiet moves to PVS. It does not reduce moves during deployment, while in check, or for captures, betrayals, or checking moves. At remaining depth three or greater, moves ranked ninth or later are searched one ply shallower and searched again at full depth if they may improve the score. Selective search requires explicit opt-in. A request's `tuned` field overrides the startup search mode and disables selective search unless `selective:true` is also supplied.

Search operates on a copy and does not change the current position. The engine accepts `stop` and `quit` while searching. Search returns a legal move even if no depth completes. A repetition rematch is evaluated as neutral zero during search; match management retains the termination reason.

Squares are numbered 0–80. Pieces are encoded as `1 + side * 14 + piece_type`; see [RULES.md](../RULES.md) for type IDs. Each square is an array ordered from bottom to top. Move actions are `move`, `stack`, `capture`, `drop`, and `done`. `piece` identifies the piece type for a drop, and `betray` indicates whether to perform the full exchange.

A position's `history` is an array of hexadecimal full-state keys. Input without history starts a new history at that position. Save the initial position and every move for exact replay. The engine does not verify that externally supplied history is reachable through an actual game.

## Evaluation models and game records

Startup option `--model FILE` loads an integer or floating-point NNUE model, or a format 7 linear model. `features` returns feature indices for NNUE, or 45 signed feature values for a linear model. `network` returns incremental and full evaluations; a linear model uses identical integer arithmetic for both. `linear_basis` returns the current position's 45 features in `features` and the handcrafted evaluator's default coefficients in `weights`. Without a model, the engine uses handcrafted evaluation. Startup fails if the model version, dimensions, or content checksum is invalid.

Startup option `--model-after-draft FILE` uses the model only after deployment. During deployment, the entire search uses handcrafted evaluation, including lines that enter the battle phase.
