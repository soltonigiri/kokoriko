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
| `search` | `ms`, `depth`, `hash_mb`, `qdepth`, `nodes`, `tuned`, `selective`, `reuse_moves`, `reuse_scores`, `qchecks`, `qevasions`, `exposure_order` | Move, score, completed depth, nodes, elapsed time, and principal variation |
| `stop` | None | No separate response; the running search stops and returns its response |
| `perft` | `depth`: 0–5 | Leaf count at the requested depth |
| `quit` | None | Exit |

PVS is the default. `--basic-search` / `tuned:false` selects basic search; `--selective-search` / `selective:true` enables reduced-depth probes. A request's `tuned` overrides the startup mode and disables selective search unless explicitly enabled.

Search preserves the current position, accepts `stop` and `quit`, and returns a legal fallback if no depth completes. Repetition scores zero during search.

Squares are numbered 0–80. Pieces are encoded as `1 + side * 14 + piece_type`; see [RULES.md](../RULES.md) for type IDs. Each square is an array ordered from bottom to top. Move actions are `move`, `stack`, `capture`, `drop`, and `done`. `piece` identifies the piece type for a drop, and `betray` indicates whether to perform the full exchange.

A position's `history` is an array of hexadecimal full-state keys. Input without history starts a new history at that position. Save the initial position and every move for exact replay. The engine does not verify that externally supplied history is reachable through an actual game.

## Evaluation

`--model FILE` loads a model for both phases; `--model-after-draft FILE` keeps the entire deployment search handcrafted. Without a model, evaluation is handcrafted. Invalid models fail at startup. See [Models](MODELS.md) for formats.

| Command | Result |
| --- | --- |
| `features` | NNUE feature indices or 45/53 linear feature values |
| `network` | Incremental and full model evaluation; residual models return the residual |
| `linear_basis` | 45 features and handcrafted coefficients; `extended:true` returns 53 features and names |

## Search controls

`qchecks` accepts 0–2 quiet checks and `qevasions` accepts 0–8 extra evasions; both default to 0. `reuse_moves`, `reuse_scores`, and `exposure_order` default to true. Extensions stop at search ply 72.

Move hints use the current position; retained scores also require matching repetition counts and evaluator/search settings. `new`, `position`, and evaluator changes clear retained information. Results expose `score_hits` for diagnostics.

Library callers must set a nonzero `SearchOptions::evaluator_tag` identifying an immutable evaluator to retain scores across searches. Call `Searcher::clear()` when rules or the evaluator change.
