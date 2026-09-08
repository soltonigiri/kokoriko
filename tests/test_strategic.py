"""Check added features against legal moves, model arithmetic and color rotation."""

import copy
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from client import Engine
from train_linear import export, read_weights


def rotate(p):
    q = copy.deepcopy(p)
    q.pop("history", None)
    q["board"] = [
        [1 + (v - 1 + 14) % 28 for v in tower] for tower in reversed(p["board"])
    ]
    q["hand"] = list(reversed(p["hand"]))
    q["done"] = list(reversed(p["done"]))
    q["turn"], q["first"] = 1 - p["turn"], 1 - p["first"]
    return q


class StrategicTest(unittest.TestCase):
    def fixture(self, engine):
        p = engine.call("new")
        p.pop("history")
        p.update(draft=False, done=[True, True])
        p["hand"] = [[0] * 14 for _ in range(2)]
        p["board"][76] = [1]
        p["board"][4] = [15]
        p["board"][40] = [10, 14]
        p["board"][30] = [24, 24]
        return p

    def test_betrayal_reserves_and_legality(self):
        with Engine() as e:
            p = self.fixture(e)
            for count in (1, 2):
                p["hand"][0][9] = count
                e.call("position", position=p)
                state = e.call("state")
                basis = e.call("linear_basis", extended=True)["features"]
                betrayals = [m for m in e.call("legal") if m["betray"]]
                self.assertEqual(basis[49], 20 if count == 2 else 0)
                self.assertEqual(basis[50], len({m["to"] for m in betrayals}))
                self.assertEqual(e.call("state"), state)

    def test_flights_and_drop_spaces_match_legal_moves(self):
        with Engine() as e:
            p = self.fixture(e)
            p["hand"][0][9] = 2
            p["hand"][1][5] = 1
            e.call("position", position=p)
            basis = e.call("linear_basis", extended=True)["features"]
            flights = spaces = 0
            for side in (0, 1):
                q = copy.deepcopy(p)
                q["turn"] = side
                e.call("position", position=q)
                legal = e.call("legal")
                king = 76 if side == 0 else 4
                sign = 1 if side == 0 else -1
                flights += sign * len({m["to"] for m in legal if m["from"] == king})
                kinds = sum(n > 0 for n in q["hand"][side])
                spaces += (
                    sign
                    * min(4, kinds)
                    * len({m["to"] for m in legal if m["action"] == "drop"})
                )
            self.assertEqual(basis[48], flights)
            self.assertEqual(basis[51], spaces)

    def test_extended_model_and_color_symmetry(self):
        with tempfile.TemporaryDirectory() as directory, Engine() as e:
            model = Path(directory) / "extended.nnue"
            weights = e.call("linear_basis", extended=True)["weights"]
            export(weights, model)
            self.assertEqual(read_weights(model), weights)
            rng = random.Random(39)
            p = e.call("new")
            with Engine(args=["--model", str(model)]) as fitted:
                for _ in range(70):
                    e.call("position", position=p)
                    basis = e.call("linear_basis", extended=True)["features"]
                    legal = e.call("legal")
                    e.call("position", position=rotate(p))
                    self.assertEqual(
                        e.call("linear_basis", extended=True)["features"], basis
                    )
                    fitted.call("position", position=p)
                    self.assertEqual(fitted.call("features"), basis)
                    expected = max(
                        -20000,
                        min(
                            20000,
                            sum(a * b for a, b in zip(weights, basis, strict=True)),
                        ),
                    )
                    self.assertEqual(fitted.call("status")["eval"], expected)
                    if not legal:
                        break
                    e.call("position", position=p)
                    p = e.call("play", move=rng.choice(legal))


if __name__ == "__main__":
    unittest.main()
