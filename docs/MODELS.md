# Evaluation models

The launcher uses handcrafted evaluation throughout deployment searches and the bundled model for battle. `--model FILE` loads a model for both phases; `--model-after-draft FILE` keeps deployment handcrafted.

## Bundled model

`engine/models/default.nnue` is a 53-coefficient, 244-byte linear model (format 8), trained from self-play, search teachers, and paired-game coefficient tuning. It is distributed under the MIT License.

SHA-256: `9de816c63d72dd8e35a3a94c27c35ddebe695094772df4e657461e4c2eb11a11`

The first 45 features cover piece counts, mobility, advancement, and marshal support. Eight more cover towers, marshal safety, betrayal, and drop space. `linear_basis` with `extended:true` returns feature names, values, and initial coefficients. See [Benchmarks](../BENCHMARK.md) for match results.

## Training

```bash
.venv/bin/python scripts/train_linear.py --data artifacts/teachers \
  --out models/linear --limit 20000 --steps 2000
```

| Task | Tool / options |
| --- | --- |
| NNUE training | `train.py`; `--hidden 64`, `--relative`, `--residual` |
| Strategic coefficient fitting | `train_linear.py --base-model MODEL --groups tower,king,betrayal,drops` |
| Match-based tuning | `tune_spsa.py --engine ENGINE --model MODEL --out DIRECTORY` |
| Deeper search labels | `thin_samples.py`, `parallel_relabel.py`, `check_relabel.py` |
| Corpus validation | `validate_corpus.py` |
| Evaluation and accumulator timing | `bench_evaluation`, `bench_accumulator.py` |

Training and validation keep matching starts and source-game descendants together, removing intermediate duplicates across partitions. `--validation-family` and `--validation-type` provide explicit holdouts. Depth-zero searches are excluded; repetition and ply-limit endings provide no outcome label. Residual training requires handcrafted `static_score` labels.

NNUE checkpoints retain model, optimizer, random states, and data identity. `--resume` requires matching data and settings; exports use the best validation epoch. Tool outputs are candidates: validate strength on unused positions under the [match procedure](ARENA.md) before replacing the bundled model. See [Development](DEVELOPMENT.md) for setup and each tool's `--help` for options.

## File formats

All formats use a 32-byte little-endian `<8sIIIIQ` header: `KOKONN01`, input count, two layer widths, format number, and payload checksum.

| Format | Evaluation |
| --- | --- |
| 0 / 1 / 2 | Absolute NNUE: float32 / scale-256 integer / scale-512 integer |
| 3 / 4 | Side-relative NNUE: float32 / scale-512 integer |
| 5 / 6 | Side-relative residual NNUE, added to handcrafted evaluation |
| 7 / 8 | Linear: 45 / 53 signed int32 coefficients |

NNUE uses 6,954 inputs and layers of 64 or 256, then 32, then 1. Relative models rotate the board and swap sides for the upper player. Linear scores are clamped to ±20,000. Loading validates dimensions, bounds, and checksum. Exact encoding and arithmetic are defined in [network.cpp](../engine/network.cpp); [network tests](../tests/network_test.cpp) compare full and incremental evaluation through moves and undo.
