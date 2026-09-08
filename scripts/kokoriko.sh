#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$root/build/kokoriko" --model-after-draft "$root/engine/models/default.nnue" "$@"
