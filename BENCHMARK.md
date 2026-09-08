# Benchmarks

An earlier KOKORIKO build (basic search, handcrafted evaluation) was tested against Komugi’s classical `battle-only-compat-v1` variant on September 8, 2026. The current public release has not yet been tested against an external engine.

| Games | Wins | Losses | Repetitions | Ply-limit endings | Score | 95% interval |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 200 | 61 | 5 | 131 | 3 | **64.0%** | 60.75–67.50% |

Score is `(wins + 0.5 × unresolved games) / games`. Repetitions normally require a rematch; this test assigned half a point without replaying them. The interval uses 4,000 bootstrap resamples of paired starting positions.

## Conditions

- 100 distinct positions after deployment, each played with sides swapped; seed 301000.
- Both engines: 50 ms per move, one thread, 1 MiB transposition table, 220-ply limit.
- Mean wall time per move: KOKORIKO 51.87 ms, Komugi variant 57.02 ms. Median completed depth was zero for both engines, so fallback moves affected play.
- All pairs completed; zero failures. This was a screening trial. CPU model and host load were not recorded in the summary.

## Scope

The opponent came from `jwyce/komugi` at `293a0f4cd2547fb6b3d1cdeda3dab0827a73c72d`, with changes to betrayal, repetition, stalemate, insufficient-material draws, time checks, and incomplete-search handling. The adapter preserved full move history. This result applies to that modified classical engine, not unmodified Komugi or its NNUE configuration; deployment and longer time controls were not evaluated.

Historical binaries, the adapter, patch, and game records are not included, so the public checkout alone cannot reproduce this trial. See [Match testing](docs/ARENA.md) for the evaluation procedure.
