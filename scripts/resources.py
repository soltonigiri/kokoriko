"""Check available space on the configured storage volume."""

import json
import os
import shutil
from pathlib import Path

from client import ROOT

GIB = 1024**3


def check_space(minimum_free_gib=10):
    volume = Path(os.environ.get("KOKORIKO_STORAGE_PATH", str(ROOT))).resolve()
    free = shutil.disk_usage(volume).free
    if free < minimum_free_gib * GIB:
        raise RuntimeError(
            f"{volume}: {free / GIB:.2f} GiB free; need {minimum_free_gib} GiB. "
            "Completed files are preserved; resume after freeing space."
        )
    return dict(volume=str(volume), free_bytes=free, minimum_free_gib=minimum_free_gib)


if __name__ == "__main__":
    print(json.dumps(check_space(), indent=2))
