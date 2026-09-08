# Development

## Build and test

Install Linux, a C++20 compiler, Ninja, and uv. Development dependencies are pinned in `requirements-dev.txt`; training dependencies are pinned in `requirements-train.txt`.

```bash
./scripts/bootstrap.sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

The bootstrap script creates a Python 3.10 environment, builds in Release mode, and runs the C++ tests. Python tests cover JSON I/O, game replay, legal moves, and model consistency. Tests that require training dependencies are skipped when those dependencies are absent.

```bash
.venv/bin/cmake -S . -B build-sanitize -G Ninja -DCMAKE_BUILD_TYPE=Debug -DKOKORIKO_SANITIZE=ON
.venv/bin/cmake --build build-sanitize -j 2
.venv/bin/ctest --test-dir build-sanitize --output-on-failure
```

## Self-play

```bash
.venv/bin/python scripts/parallel_arena.py --workers 1 \
  --a build/kokoriko --b build/kokoriko --ref build/kokoriko \
  --out artifacts/selfplay --pairs 10 --ms 50 --max-plies 220 \
  --seed 91000 --samples --explore 0.15
```

This small run checks the data generation workflow. Repeating the command resumes the run and preserves completed pairs. Use a new output directory if the configuration, executable, or model changes. See [ARENA.md](ARENA.md) for comparison conditions and acceptance criteria.

The tools check free space before adding data and stop below 10 GiB. By default, they check the volume containing the repository. To check another volume, including the host volume of a virtualized environment, set `KOKORIKO_STORAGE_PATH` to a directory on that volume.

## Training

```bash
uv pip install --python .venv/bin/python -r requirements-train.txt
.venv/bin/python scripts/train.py --data artifacts/selfplay \
  --out models/example --epochs 20 --limit 10000
.venv/bin/python scripts/train.py --data artifacts/selfplay \
  --out models/example --epochs 30 --limit 10000 --resume
```

Training and validation are split by starting position, with duplicate intermediate positions removed. Checkpoints retain the model, optimizer, and random states. Assess playing strength in matches from unused starting positions; training loss alone does not establish strength.

[MODELS.md](MODELS.md) describes linear model training, NNUE formats, teacher relabeling, and data validation.

## Layout

- `engine/`: rules, search, evaluation models, and JSON CLI
- `scripts/`: building, matches, training, and data validation
- `tests/`: C++ and Python tests, with position fixtures
- `docs/`: protocol, evaluation models, and match testing specifications

External libraries are installed as dependencies. C++ JSON handling uses [nlohmann/json](https://github.com/nlohmann/json); training uses [PyTorch](https://pytorch.org/) and [NumPy](https://numpy.org/). Each dependency retains its own license.
