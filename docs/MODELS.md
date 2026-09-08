# Evaluation models and training data

The standard launcher uses handcrafted evaluation during deployment and the bundled 45-coefficient model after battle begins. `engine/models/default.nnue` is 212 bytes. Experimental models and training data are stored locally; experiment records retain conditions, hashes, and acceptance decisions. The handcrafted C++ evaluator also serves as the baseline for residual models.

`--model FILE` uses a model during both deployment and battle. `--model-after-draft FILE` uses it only after battle begins. During deployment, the entire search uses handcrafted evaluation, even along lines that finish deployment. Undoing back into deployment restores handcrafted evaluation. This preserves deployment decisions when using a model evaluated only for battle.

## Features and model formats

Board features comprise `81 squares × 3 tiers × 28 piece identities = 6804` inputs. Reserves contribute 140 one-hot features for side, piece type, and counts 0–4. Side to move, deployment phase, original turn order, and each side's deployment completion state bring the total to 6954. Formats 0–2 use absolute coordinates and sides, with scores expressed from the side to move.

The default architecture is an EmbeddingBag feature sum → 256 → 32 → 1. `--hidden 64` reduces the first layer to 64 units to lower computation and model size. The header records a first-layer width of 64 or 256, which the engine uses for evaluation. Hidden outputs are clamped to 0–1, and the final output is multiplied by 600 to match the engine's evaluation scale. C++ adds and subtracts feature differences from the previous position and is checked against full Python evaluation. Search updates features on moves and undo.

Files are little-endian. The 32-byte header uses `<8sIIIIQ`: magic `KOKONN01`, input count, first-layer width, second-layer width, format number, and a 64-bit payload checksum. The payload contains first-layer weights and biases, second-layer weights and biases, then output weights and biases. The checksum detects content corruption; experiment records also retain SHA-256 hashes.

Format 0 uses float32. Format 1 uses integers at scale 256 for initial validation. Format 2 uses scale 512, with int16 weights and int32 biases. Second-layer and output accumulation use int64. First-layer biases use scale 512; second-layer and output biases use scale 512². Loading limits weights and biases to a floating-point-equivalent absolute value of 64 to keep integer accumulation in range. Integer incremental and full evaluation must match exactly; validation requires the maximum score difference from the floating-point model to remain below 30.

Format 3 uses float32 features relative to the side to move; format 4 uses the same features with scale-512 integers. When the upper side moves, rotate the board 180 degrees and swap sides, reserves, deployment completion flags, and original turn order. The moving side is always input as side 0. The `features` request follows the loaded model's feature convention. Incremental accumulators are retained for both perspectives to avoid summing all feature weights again on every turn change.

Formats 5 and 6 are residual models relative to the side to move, using float32 and scale-512 integers respectively. Train with `--relative --residual`; the NNUE output is added to handcrafted evaluation. `network` returns the residual, while `status` and search use the combined score. Training data must include `static_score` from the same handcrafted evaluator. `relabel.py --static-score` can save it alongside the search teacher.

Use `--relative` for relative-feature training. Starting positions equivalent under rotation and side swapping belong to the same training or validation group; intermediate duplicates are removed using the same convention. Because this changes the split, validation losses are not directly comparable with absolute-feature models. Assess strength in independent matches.

## Linear evaluation model

Format 7 is a lightweight evaluator with 45 coefficients: 14 top-piece counts, 14 buried-piece counts, 14 reserve-piece counts, non-marshal mobility, non-marshal advancement, and friendly pieces around the marshal. Each feature is the moving side's value minus the opponent's. The marshal's neighborhood includes its own square to match the handcrafted formula.

Header dimensions are 45, 1, and 1, with format number 7. The payload contains 45 little-endian int32 coefficients. Coefficients are bounded by an absolute value of 30000. The dot product uses int64, and the score is clamped to ±20000. Tests verify that the default coefficients reproduce handcrafted evaluation.

`train_linear.py` uses the same starting-position split as NNUE and learns search teachers, such as evaluations from 500 ms searches. For every input, it verifies that the default coefficients reproduce `static_score`. Piece coefficients are constrained to 0.5–1.5 times their original values; the final three coefficients are constrained to −1–3 times their originals. A penalty discourages deviation from the original coefficients. The step with the lowest validation loss after integer rounding is selected. The run saves configuration, input hashes, position IDs, losses, coefficients, and output hashes. Short full-batch runs reproduce from the beginning with identical settings and reject reruns with changed settings. Confirm strength in independent matches.

```bash
.venv/bin/python scripts/train_linear.py --data artifacts/teachers \
  --out models/linear --limit 20000 --steps 2000
```

## Data and resuming

Two games from the same initial deployment with sides swapped form a pair. A hash of the full initial position assigns it to training or validation, so identical deployments from different seeds stay in the same partition. Intermediate positions present in both sets are removed from training. The split does not use seed remainders, which correlate with starting piece counts.

Teacher labels apply a sigmoid to search scores. By default, positions from games with a decisive result mix 70% search evaluation with 30% game outcome. `--teacher-mix 1` uses only search evaluation. Repetition and ply-limit endings receive no outcome label. Positions whose search finishes at depth zero are excluded from training. Deeper relabeling reconstructs repetition history from the initial position and every move.

`checkpoint.pt` stores the last completed epoch's model, optimizer, random states, data manifest, training history, and model with the lowest validation loss. `--resume` requires matching data and settings, then continues after the last completed epoch. An interrupted epoch is repeated. Exported `.nnue` files use the model with the lowest validation loss; `selection.json` records the selected epoch.

New training runs weight every position equally when aggregating loss, including a smaller final batch, and record `loss_aggregation: "per_sample"`. Resuming older checkpoints without this field preserves their unweighted mean of batch means. Do not directly compare loss values aggregated by different methods.

`validate_corpus.py` replays every game and excludes any entire pair containing an illegal move. It preserves the source and writes validated data to a separate output directory.

It also verifies that each training position matches the game state immediately before its recorded ply. Pairs with duplicate or out-of-range plies or mismatched positions are excluded. The output retains input-file and engine hashes and permits reruns with the same configuration. Use a different output directory if the input or engine changes, or if an older output directory has no manifest. Source and output directories must differ.

## Evaluation speed

A JSON array of positions lets you compare handcrafted evaluation with full and incremental evaluation of floating-point and integer models in the same order. Each position is evaluated 100 times, measuring CPU time without model loading. `*_evaluator_incremental` measures the evaluator called by search, including handcrafted evaluation for residual models. `*_incremental` measures only model predictions. Assess playing strength separately in matches that include search.

```bash
.venv/bin/cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
.venv/bin/cmake --build build --target bench_evaluation -j 2
build/bench_evaluation artifacts/bench-positions.json \
  models/example/model-float.nnue models/example/model-int.nnue
```

For deeper relabeling, `thin_samples.py` can select up to 50 positions across each game, and `parallel_relabel.py` distributes work by pair. Initial positions, complete move sequences, and termination reasons are preserved. Completed pairs are skipped on reruns. Resuming is rejected if the generation version, input-file hashes, search time, or sampling interval differs.

```bash
.venv/bin/python scripts/thin_samples.py --data artifacts/selfplay \
  --out artifacts/thinned --per-game 50
.venv/bin/python scripts/parallel_relabel.py --workers 3 \
  --data artifacts/thinned --out artifacts/teachers \
  --engine build/kokoriko --ms 500 --every 1 \
  --max-pairs 200 --static-score
.venv/bin/python scripts/check_relabel.py --source artifacts/thinned \
  --data artifacts/teachers --out artifacts/teachers-check.json
```

`check_relabel.py` checks that every planned pair exists and verifies source hashes, original scores and depths, and teacher search time. It restores the original labels in memory to verify that game records, positions, and other fields match the source.

The bundled `default.nnue` is a format 7 model trained from this project's self-play and search teachers. Its SHA-256 is `290efe92722fd434b8c888858c71f5878af66916c50316f91432bdcbe7809d98`. It is distributed under the MIT License.
