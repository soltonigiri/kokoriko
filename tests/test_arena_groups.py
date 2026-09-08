import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from arena import summarize
from client import atomic_json


class SourceBootstrapTest(unittest.TestCase):
    def test_correlated_starts_do_not_create_independent_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for i in range(4):
                atomic_json(
                    root / f"pair-{i:05d}.json",
                    dict(
                        source_group="one-game",
                        games=[
                            dict(reason="checkmate", winner=0, a_side=0),
                            dict(reason="checkmate", winner=1, a_side=1),
                        ],
                    ),
                )
            summary = summarize(root, 4)
            self.assertEqual(summary["score"], 1)
            self.assertEqual(summary["independent_source_groups"], 1)
            self.assertIsNone(summary["ci95"])
            self.assertFalse(summary["passes_score_threshold"])
            path = root / "pair-00003.json"
            record = json.loads(path.read_text())
            record["source_group"] = "second-game"
            atomic_json(path, record)
            summary = summarize(root, 4)
            self.assertEqual(summary["independent_source_groups"], 2)
            self.assertEqual(summary["ci95"], [1, 1])
            self.assertFalse(summary["adopted"])


if __name__ == "__main__":
    unittest.main()
