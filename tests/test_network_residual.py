import importlib.util
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from client import Engine


@unittest.skipUnless(importlib.util.find_spec("torch"), "optional torch absent")
class ResidualNetworkTest(unittest.TestCase):
    def test_zero_correction_preserves_classical_evaluation(self):
        for hidden in (64, 256):
            with self.subTest(hidden=hidden):
                self.check_zero_correction(hidden)

    def check_zero_correction(self, hidden):
        import torch
        from train import Net, export

        torch.set_num_threads(1)
        net = Net(hidden)
        for parameter in net.parameters():
            parameter.data.zero_()
        with tempfile.TemporaryDirectory() as directory:
            floating = Path(directory, "float.nnue")
            integer = Path(directory, "int.nnue")
            export(net, floating, relative=True, residual=True)
            export(net, integer, quantized=True, relative=True, residual=True)
            with (
                Engine() as base,
                Engine(args=["--model", str(floating)]) as f,
                Engine(args=["--model", str(integer)]) as q,
            ):
                rng = random.Random(614)
                base.call("new")
                saw_nonzero = False
                for _ in range(70):
                    position = base.call("state")
                    status = base.call("status")
                    saw_nonzero |= status["eval"] != 0
                    for engine in (f, q):
                        engine.call("position", position=position)
                        self.assertEqual(engine.call("status"), status)
                        self.assertEqual(
                            engine.call("network"), {"full": 0, "incremental": 0}
                        )
                    moves = base.call("legal")
                    if not moves:
                        break
                    base.call("play", move=rng.choice(moves))
                self.assertTrue(saw_nonzero)


if __name__ == "__main__":
    unittest.main()
