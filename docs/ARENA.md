# Match testing

A pair plays the same position with sides swapped. Give both engines equal time, search threads, and hash-table capacity; use positions excluded from training and tuning.

```bash
.venv/bin/python scripts/parallel_arena.py --workers 3 \
  --a build/kokoriko --b build-baseline/kokoriko --ref build/kokoriko \
  --model-a engine/models/default.nnue --model-b models/baseline.nnue \
  --out artifacts/screen --pairs 100 --ms 300 --seed 81000
```

Model loading defaults to battle only; deployment searches use handcrafted evaluation. Without model options, evaluation is handcrafted. `--standard-a --standard-b` selects the bundled model for both sides. Keep a separate baseline model when comparing versions. PVS and 32 MiB tables are defaults.

## Results and acceptance

- Report wins, losses, repetitions, ply-limit endings, failures, and planned pairs. Repetition and limit endings score 0.5 for testing; official repetition requires a rematch.
- Illegal moves, exits, and timeouts fail the whole pair. Failed pairs are excluded from strength statistics and block acceptance.
- Screen on 100 pairs, then confirm on at least 500 unused pairs with `--confirmation`. Accept only after all pairs complete without failures and the 95% interval's lower bound exceeds 50%.
- Bootstrap intervals resample independent source groups, keeping both colors and related positions together. Small runs check integration, not strength.

Records include moves, timing, settings, and executable/model hashes. Rerun the same command to resume; changed inputs require a new output directory. Worker count may change without discarding completed pairs. Host contention affects elapsed time.

## Other comparisons

| Purpose | Options or tool |
| --- | --- |
| Diverse battle starts | `--opening-family mixed` or `--opening-book BOOK` |
| Deployment | `--deployment-a search --deployment-b search --draft-start partial` |
| Basic or selective search | `--basic-a/b` or `--selective-a/b` |
| Search controls | `--qchecks-a/b`, `--qevasions-a/b`, `--no-score-cache-a/b`, `--no-move-cache-a/b`, `--no-exposure-order-a/b` |
| Fixed-position timing | `bench_versions.py` at 300 ms, 1 s, and 5 s |
| Position collection / tactics | `collect_positions.py`, `tactics.py`, `check_tactics.py` |

Deployment starts `initial` and `marshal` contain only two and 162 unique positions, respectively; neither supports 500-pair confirmation. `partial` tests unfinished deployments. Search timing and teacher-based tactics are diagnostics, not substitutes for matches. See each tool's `--help` for arguments and [Benchmarks](../BENCHMARK.md) for results.
