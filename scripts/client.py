"""Line-oriented engine client. Each request is validated by the engine."""

from __future__ import annotations
import json
import selectors
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Engine:
    def __init__(self, executable=None, args=()):
        self.process = subprocess.Popen(
            [str(executable or ROOT / "build/kokoriko"), *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def call(self, cmd, timeout=30, **kwargs):
        if self.process.poll() is not None:
            raise RuntimeError(f"engine exited: {self.process.returncode}")
        self.process.stdin.write(json.dumps(dict(cmd=cmd, **kwargs)) + "\n")
        self.process.stdin.flush()
        if not self.selector.select(timeout):
            raise TimeoutError(f"engine timed out: {cmd}")
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("engine closed output")
        response = json.loads(line)
        if not response["ok"]:
            raise ValueError(response["error"])
        return response["result"]

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.selector.close()
        self.process.stdin.close()
        self.process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
    ) as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def replay(engine, record):
    state = engine.call("position", position=record["initial"])
    for move in record["moves"]:
        state = engine.call("play", move=move)
    if "final" in record and state != record["final"]:
        raise ValueError("replayed state differs from recorded state")
    return state
