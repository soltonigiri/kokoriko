import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from client import Engine
from deployment import DeploymentEngine, draft_opening


class DeploymentTest(unittest.TestCase):
    def test_each_policy_finishes_legally(self):
        for target in (8, 12, 18):
            with DeploymentEngine("build/kokoriko", str(target)) as e:
                state = e.call("new", first=target % 2)
                plies = 0
                while state["draft"]:
                    move = e.call("search")["move"]
                    self.assertIn(move, e.call("legal"))
                    state = e.call("play", move=move)
                    plies += 1
                    self.assertLessEqual(plies, 52)
                for side in (0, 1):
                    self.assertEqual(
                        sum(
                            (p - 1) // 14 == side
                            for tower in state["board"]
                            for p in tower
                        ),
                        target,
                    )

    def test_trial_starts_are_distinct(self):
        starts = set()
        with Engine() as e:
            for seed in range(81000, 81100):
                state, _ = draft_opening(e, seed)
                key = tuple(tuple(t) for t in state["board"]), state["first"]
                self.assertNotIn(key, starts)
                starts.add(key)


if __name__ == "__main__":
    unittest.main()
