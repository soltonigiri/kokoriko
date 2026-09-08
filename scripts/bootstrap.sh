#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then uv venv .venv --python 3.10; fi
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
.venv/bin/cmake --build build -j 3
.venv/bin/ctest --test-dir build --output-on-failure
