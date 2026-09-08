import sys
import unittest
import json
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from client import Engine
from deployment import (
    DeploymentEngine,
    draft_opening,
    partial_draft_opening,
    initial_draft_opening,
)
from client import replay
from arena import engine_flags


class DeploymentTest(unittest.TestCase):
    def test_arena_config_and_early_limits(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "trial"
            command = [
                sys.executable,
                str(root / "scripts/arena.py"),
                "--out",
                str(out),
                "--pairs",
                "1",
                "--end-pair",
                "0",
                "--standard-a",
                "--standard-b",
            ]
            subprocess.run(command, capture_output=True, text=True, check=True)
            config = json.loads((out / "config.json").read_text())
            self.assertEqual(config["hash_mb"], 32)
            self.assertEqual(
                config["engine_args"]["a"][0:2],
                ["--tuned-search", "--model-after-draft"],
            )
            self.assertEqual(config["model_a_sha256"], config["model_b_sha256"])
            changed = subprocess.run(
                command + ["--model-phase-a", "always"], capture_output=True, text=True
            )
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn("requires bundled after-draft", changed.stderr)
            for family, limit in [("initial", 2), ("marshal", 162)]:
                invalid = Path(directory) / family
                failed = subprocess.run(
                    [
                        sys.executable,
                        str(root / "scripts/arena.py"),
                        "--out",
                        str(invalid),
                        "--pairs",
                        str(limit + 1),
                        "--deployment-a",
                        "search",
                        "--deployment-b",
                        "search",
                        "--draft-start",
                        family,
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn(f"only {limit} unique positions", failed.stderr)
                self.assertFalse(invalid.exists())

    def test_standard_model_flags(self):
        self.assertEqual(engine_flags(None), [])
        self.assertEqual(
            engine_flags("model.nnue", mode="tuned"),
            ["--tuned-search", "--model-after-draft", "model.nnue"],
        )
        self.assertEqual(
            engine_flags("model.nnue", "always", "basic"),
            ["--basic-search", "--model", "model.nnue"],
        )

    def test_marshal_limit_and_partial_diversity(self):
        starts = set()
        with Engine() as e:
            initial, setup = initial_draft_opening(e, 0)
            self.assertEqual(initial, e.call("new", first=0))
            self.assertEqual(setup["moves"], [])
            first, _ = draft_opening(e, 81000)
            repeated, _ = draft_opening(e, 81162)
            self.assertEqual(first, repeated)
            for seed in range(81000, 81500):
                state, setup = partial_draft_opening(e, seed)
                self.assertTrue(state["draft"])
                key = (
                    tuple(tuple(t) for t in state["board"]),
                    state["turn"],
                    state["first"],
                )
                self.assertNotIn(key, starts)
                starts.add(key)
                if seed % 100 == 0:
                    self.assertEqual(replay(e, setup), state)

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

    def test_adaptive_and_structured_policies_finish_legally(self):
        for policy in ("adaptive", "tower", "flank"):
            with DeploymentEngine("build/kokoriko", policy) as e:
                state = e.call("new")
                for _ in range(52):
                    if not state["draft"]:
                        break
                    move = e.call("search")["move"]
                    self.assertIn(move, e.call("legal"))
                    state = e.call("play", move=move)
                self.assertFalse(state["draft"])

    def test_measured_response_table_is_used(self):
        table = {"reserve": "18", "wide": "18", "tower": "18"}
        with DeploymentEngine("build/kokoriko", "adaptive", policy_table=table) as e:
            state = e.call("new")
            for _ in range(52):
                if not state["draft"]:
                    break
                state = e.call("play", move=e.call("search")["move"])
            self.assertFalse(state["draft"])
            self.assertEqual(sum(map(len, state["board"])), 36)

    def test_each_opening_family_covers_both_first_players(self):
        from opening_families import FAMILIES, family_opening

        seen = {family: set() for family in FAMILIES}
        with Engine() as e:
            for seed in range(12):
                state, setup = family_opening(e, seed, "mixed")
                seen[setup["family"]].add(state["first"])
                self.assertEqual(replay(e, setup), state)
        self.assertTrue(all(firsts == {0, 1} for firsts in seen.values()))

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
