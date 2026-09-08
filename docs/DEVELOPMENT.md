# Development

Requires Linux, a C++20 compiler, Ninja, and uv.

## Build and test

```bash
./scripts/bootstrap.sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Bootstrap creates the Python environment, builds Release, and runs C++ tests. Python tests requiring optional training packages are skipped when unavailable.

For address and undefined-behavior checks:

```bash
.venv/bin/cmake -S . -B build-sanitize -G Ninja -DCMAKE_BUILD_TYPE=Debug -DKOKORIKO_SANITIZE=ON
.venv/bin/cmake --build build-sanitize -j 2
.venv/bin/ctest --test-dir build-sanitize --output-on-failure
```

## Generate data and train

```bash
.venv/bin/python scripts/parallel_arena.py --workers 1 \
  --a build/kokoriko --b build/kokoriko --ref build/kokoriko \
  --out artifacts/selfplay --pairs 10 --ms 50 --max-plies 220 \
  --seed 91000 --samples --explore 0.15
uv pip install --python .venv/bin/python -r requirements-train.txt
.venv/bin/python scripts/train.py --data artifacts/selfplay \
  --out models/example --epochs 20 --limit 10000
```

This is a small workflow check. Rerun matches to resume completed pairs; add `--resume` to training to continue a checkpoint. Changed data, binaries, models, or settings require a new output directory. Data-writing tools stop below 10 GiB free; `KOKORIKO_STORAGE_PATH` selects the volume to check.

See [Models](MODELS.md) for training choices and [Match testing](ARENA.md) for strength validation. Each Python tool provides `--help`.

## Code

`engine/` contains rules, search, evaluation, and the JSON CLI; `scripts/` contains data and training tools; `tests/` contains C++ and Python checks. Dependencies are pinned in `requirements-dev.txt` and `requirements-train.txt`. External libraries retain their own licenses.
