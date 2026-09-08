"""Portable coefficient models preserve classical scores and reject bad payloads."""

import random
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from client import Engine, ROOT
from train_linear import export


class LinearTest(unittest.TestCase):
    def test_battle_only_model_preserves_whole_deployment_search(self):
        with tempfile.TemporaryDirectory() as temporary, Engine() as baseline:
            model = Path(temporary) / "zero.nnue"
            export([0] * 45, model)
            position = baseline.call("new")
            position.pop("history")
            position["board"][76] = [1]
            position["board"][4] = [15]
            position["hand"] = [[0] * 14 for _ in range(2)]
            position["hand"][1][9] = 1
            position.update(turn=1, first=0, draft=True, done=[True, False])
            with (
                Engine(args=["--model-after-draft", str(model)]) as staged,
                Engine(args=["--model", str(model)]) as always,
            ):
                engines = (baseline, staged, always)
                for engine in engines:
                    engine.call("position", position=position)
                self.assertEqual(staged.call("status"), baseline.call("status"))
                self.assertNotEqual(staged.call("status"), always.call("status"))

                def search(engine):
                    result = engine.call(
                        "search", ms=60000, depth=3, qdepth=0, hash_mb=1
                    )
                    self.assertEqual(result["depth"], 3)
                    result.pop("elapsed_ms")
                    return result

                # A Done variation crosses into battle inside this search.
                # Selecting the evaluator per leaf would change its score.
                self.assertEqual(search(staged), search(baseline))
                done = next(
                    move for move in baseline.call("legal") if move["action"] == "done"
                )
                for engine in engines:
                    self.assertFalse(engine.call("play", move=done)["draft"])
                self.assertEqual(staged.call("status"), always.call("status"))
                self.assertNotEqual(staged.call("status"), baseline.call("status"))
                self.assertEqual(search(staged), search(always))
                for engine in engines:
                    self.assertTrue(engine.call("undo")["draft"])
                self.assertEqual(staged.call("status"), baseline.call("status"))

    def test_scores_search_and_invalid_models(self):
        with tempfile.TemporaryDirectory() as temporary, Engine() as baseline:
            directory = Path(temporary)
            default_weights = baseline.call("linear_basis")["weights"]
            changed_weights = default_weights.copy()
            changed_weights[1] += 91
            changed_weights[9] -= 17
            changed_weights[42:] = [7, -2, 11]
            original = directory / "default.nnue"
            changed = directory / "changed.nnue"
            export(default_weights, original)
            export(changed_weights, changed)
            rng = random.Random(1729)
            with (
                Engine(args=["--model", str(original)]) as identical,
                Engine(args=["--model", str(changed)]) as modified,
            ):
                observed_change = False
                for ply in range(180):
                    position = baseline.call("state")
                    basis = baseline.call("linear_basis")["features"]
                    for engine in (identical, modified):
                        engine.call("position", position=position)
                        self.assertEqual(engine.call("features"), basis)
                    default_score = sum(w * f for w, f in zip(default_weights, basis))
                    expected = max(
                        -20000,
                        min(20000, sum(w * f for w, f in zip(changed_weights, basis))),
                    )
                    self.assertEqual(default_score, baseline.call("status")["eval"])
                    self.assertEqual(identical.call("status"), baseline.call("status"))
                    self.assertEqual(
                        modified.call("network"),
                        dict(full=expected, incremental=expected),
                    )
                    self.assertEqual(modified.call("status")["eval"], expected)
                    observed_change |= expected != default_score
                    if ply in (20, 40, 80):
                        options = dict(ms=60000, nodes=1500, depth=3, hash_mb=1)
                        a = baseline.call("search", **options)
                        b = identical.call("search", **options)
                        a.pop("elapsed_ms")
                        b.pop("elapsed_ms")
                        self.assertEqual(a, b)
                    moves = baseline.call("legal")
                    if not moves:
                        break
                    baseline.call("play", move=rng.choice(moves))
                self.assertGreater(ply, 30)
                self.assertTrue(observed_change)
            broken = directory / "broken.nnue"
            for mutation, message in [
                ("checksum", "checksum"),
                ("value", "invalid model value"),
                ("dimension", "dimensions"),
                ("length", "payload"),
            ]:
                payload = bytearray(original.read_bytes())
                if mutation == "checksum":
                    payload[-1] ^= 1
                elif mutation == "value":
                    struct.pack_into("<i", payload, 32, 2147483647)
                elif mutation == "dimension":
                    struct.pack_into("<I", payload, 8, 46)
                else:
                    payload += b"extra"
                if mutation != "checksum":
                    checksum = 1469598103934665603
                    for value in payload[32:]:
                        checksum = ((checksum ^ value) * 1099511628211) & (
                            (1 << 64) - 1
                        )
                    struct.pack_into("<Q", payload, 24, checksum)
                broken.write_bytes(payload)
                result = subprocess.run(
                    [str(ROOT / "build/kokoriko"), "--model", str(broken)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(message, result.stderr)


if __name__ == "__main__":
    unittest.main()
