# Benchmarks

Current KOKORIKO (bundled 53-coefficient model) versus Komugi classical, tested September 9, 2026 (JST).

| Time / sample | Games | Wins | Losses | Unresolved | Score | 95% interval |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 300 ms / all 100 starts | 200 | 195 | 2 | 3 | **98.25%** | 96.50–99.50% |
| 300 ms / matched 20 starts | 40 | 39 | 1 | 0 | **97.50%** | 92.50–100.00% |
| 5 seconds / same 20 starts | 40 | 39 | 0 | 1 | **98.75%** | 96.25–100.00% |

The 20 starts were fixed before the five-second trial. The matched 300 ms row is a subset of the 200-game screen. The longer trial covers only 20 starts.

## Conditions

- Six post-deployment opening families; sides swapped for every start. One search thread, 32 MiB tables, 220-ply limit; no failures.
- Wins score 1; unresolved repetitions and ply-limit endings score 0.5 without replay. Intervals use 4,000 bootstrap resamples of starting-position groups. The five-second trial ended with one repetition; the full 300 ms screen had three ply-limit endings.

| Matched sample | Mean move time, KOKORIKO / Komugi | Median depth | Depth-zero moves |
| --- | --- | --- | --- |
| 300 ms | 273.60 / 362.21 ms | 2 / 1 | 1 of 529 / 180 of 510 |
| 5 seconds | 4565.25 / 5028.93 ms | 3 / 2 | 0 of 735 / 0 of 716 |

Depth-zero searches return fallback moves. Equal requested time does not imply equal depth; interpret scores within the tested time control.

The opponent is [jwyce/komugi](https://github.com/jwyce/komugi/tree/293a0f4cd2547fb6b3d1cdeda3dab0827a73c72d), adjusted for betrayal, repetition, game endings, and time handling. NNUE and deployment strength were not evaluated.

Historical binaries, the adapter, and records are not distributed, so the public checkout alone cannot reproduce these results. [Match testing](docs/ARENA.md) · [Model](docs/MODELS.md)
