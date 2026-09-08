import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from client import Engine, ROOT, atomic_json


class ReplayValidationTest(unittest.TestCase):
    def test_sample_alignment_and_stale_output_guard(self):
        with tempfile.TemporaryDirectory() as temporary, Engine() as engine:
            root = Path(temporary)
            initial = engine.call("new")
            state, moves, samples = initial, [], []
            for ply in range(3):
                samples.append(
                    dict(
                        ply=ply,
                        position={k: v for k, v in state.items() if k != "history"},
                        score=0,
                        depth=1,
                    )
                )
                move = engine.call("legal")[0]
                state = engine.call("play", move=move)
                moves.append(move)
            game = dict(initial=initial, moves=moves, samples=samples, final=state)
            original = dict(seed=1, games=[game])
            for index, fault in enumerate((None, "position", "duplicate", "range")):
                record = copy.deepcopy(original)
                rows = record["games"][0]["samples"]
                if fault == "position":
                    rows[1]["position"]["turn"] = 1 - rows[1]["position"]["turn"]
                elif fault == "duplicate":
                    rows.append(copy.deepcopy(rows[0]))
                elif fault == "range":
                    rows[0]["ply"] = 3
                atomic_json(root / "input" / f"pair-{index:05d}.json", record)
            command = [
                sys.executable,
                str(ROOT / "scripts/validate_corpus.py"),
                "--data",
                str(root / "input"),
                "--out",
                str(root / "output"),
                "--engine",
                str(ROOT / "build/kokoriko"),
            ]
            for _ in range(2):
                subprocess.run(command, capture_output=True, text=True, check=True)
            result = json.loads((root / "output/validation.json").read_text())
            self.assertEqual(len(result["accepted"]), 1)
            self.assertEqual(len(result["rejected"]), 3)
            self.assertIn("sample position differs", result["rejected"][0]["error"])
            self.assertEqual(len(list((root / "output").glob("pair-*.json"))), 1)
            previous = (root / "output/pair-00000.json").read_bytes()
            original["seed"] = 2
            atomic_json(root / "input/pair-00000.json", original)
            failed = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("inputs or referee changed", failed.stderr)
            self.assertEqual((root / "output/pair-00000.json").read_bytes(), previous)


@unittest.skipUnless(
    importlib.util.find_spec("torch"), "optional training dependencies absent"
)
class TrainingDataTest(unittest.TestCase):
    def test_relative_features_and_color_rotated_openings(self):
        from train import dataset, features, relative_position

        def rotate(p):
            q = copy.deepcopy(p)
            q["board"] = [
                [1 + (v - 1 + 14) % 28 for v in t] for t in reversed(p["board"])
            ]
            q["hand"] = list(reversed(p["hand"]))
            q["done"] = list(reversed(p["done"]))
            q["first"] = 1 - p["first"]
            q["turn"] = 1 - p["turn"]
            q.pop("history", None)
            return q

        with Engine() as e:
            base = e.call("new")
        examples = {}
        for square in range(54, 81):
            p = copy.deepcopy(base)
            p.pop("history")
            p["board"][square] = [1]
            p["hand"][0][0] = 0
            key = json.dumps(relative_position(p), sort_keys=True)
            validation = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 5 == 0
            examples.setdefault(validation, p)
            self.assertEqual(features(p, True), features(rotate(p), True))
            self.assertEqual(
                features(rotate(p), True), sorted(features(rotate(p), True))
            )
        self.assertEqual(len(examples), 2)
        with tempfile.TemporaryDirectory() as directory:
            for i, p in enumerate(
                [
                    examples[True],
                    rotate(examples[True]),
                    examples[False],
                    rotate(examples[False]),
                ]
            ):
                game = dict(
                    initial=p,
                    winner=None,
                    samples=[dict(position=p, score=0, depth=1, ply=0)],
                )
                Path(directory, f"pair-{i:05d}.json").write_text(
                    json.dumps(dict(seed=i, games=[game, game]))
                )
            train, valid, manifest = dataset(directory, 100, relative=True)
            self.assertEqual(
                [f["split"] for f in manifest["files"]],
                ["validation", "validation", "training", "training"],
            )
            self.assertFalse({r[2] for r in train} & {r[2] for r in valid})

    def test_identical_openings_never_cross_split_even_with_different_seeds(self):
        from train import dataset

        with Engine() as e:
            base = e.call("new")
        examples = {}
        for q in range(54, 81):
            p = copy.deepcopy(base)
            p["board"][q] = [1]
            p["hand"][0][0] = 0
            p.pop("history")
            group = (
                int(
                    hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[
                        :8
                    ],
                    16,
                )
                % 5
                == 0
            )
            examples.setdefault(group, p)
        self.assertEqual(len(examples), 2)
        with tempfile.TemporaryDirectory() as d:
            for i, validation in enumerate((True, True, False, False)):
                p = examples[validation]
                game = dict(
                    initial=p,
                    winner=None,
                    samples=[dict(position=p, score=0, depth=1, ply=0)],
                )
                Path(d, f"pair-{i:05d}.json").write_text(
                    json.dumps(dict(seed=i, games=[game, game]))
                )
            train, valid, manifest = dataset(d, 100)
            self.assertEqual(len(train), 4)
            self.assertEqual(len(valid), 4)
            splits = [f["split"] for f in manifest["files"]]
            self.assertEqual(
                splits, ["validation", "validation", "training", "training"]
            )
            self.assertFalse({r[2] for r in train} & {r[2] for r in valid})


if __name__ == "__main__":
    unittest.main()
