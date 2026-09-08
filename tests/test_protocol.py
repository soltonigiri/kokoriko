import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from client import Engine, replay


class ProtocolTest(unittest.TestCase):
    def test_request_mode_overrides_selective_cli_default(self):
        with Engine() as referee:
            position = referee.call("new")
        position["board"] = [[] for _ in range(81)]
        position["hand"] = [[0] * 14 for _ in range(2)]
        position.update(draft=False, done=[True, True])
        position.pop("history")
        for square, piece in [
            (76, 1),
            (4, 15),
            (67, 10),
            (13, 24),
            (62, 2),
            (22, 16),
            (52, 24),
        ]:
            position["board"][square] = [piece]
        results = []
        for tuned, flag in [(False, "--basic-search"), (True, "--tuned-search")]:
            with (
                Engine(args=[flag]) as baseline,
                Engine(args=["--selective-search"]) as selected,
            ):
                for engine in (baseline, selected):
                    engine.call("position", position=position)
                limits = dict(ms=60000, depth=3, qdepth=0, hash_mb=1)
                expected = baseline.call("search", **limits)
                actual = selected.call("search", tuned=tuned, **limits)
                expected.pop("elapsed_ms")
                actual.pop("elapsed_ms")
                self.assertEqual(actual, expected)
                results.append(expected)
        self.assertNotEqual(results[0], results[1])

    def test_record_replay_and_failure_atomicity(self):
        with Engine() as e:
            initial = e.call("new", first=1)
            with self.assertRaises(ValueError):
                e.call("play", move=dict(action="drop", to=999, piece=0))
            self.assertEqual(e.call("state"), initial)
            with self.assertRaises(ValueError):
                e.call("position", position={})
            self.assertEqual(e.call("state"), initial)
            rng = random.Random(31415)
            moves = []
            for _ in range(180):
                legal = e.call("legal")
                if not legal:
                    break
                move = rng.choice(legal)
                before = e.call("state")
                after = e.call("play", move=move)
                self.assertEqual(e.call("undo"), before)
                self.assertEqual(e.call("play", move=move), after)
                moves.append(move)
            final = e.call("state")
            status = e.call("status")
            self.assertGreater(len(moves), 30)
            self.assertEqual(
                replay(e, dict(initial=initial, moves=moves, final=final)), final
            )
            self.assertEqual(e.call("status"), status)


class IndependentUpdateTest(unittest.TestCase):
    def test_copy_update_matches_engine(self):
        import copy

        def reference(state, m):
            s = copy.deepcopy(state)
            s.pop("history", None)
            c = s["turn"]
            if m["action"] == "done":
                s["done"][c] = True
            else:
                if m["action"] == "drop":
                    v = 1 + c * 14 + m["piece"]
                    s["hand"][c][m["piece"]] -= 1
                else:
                    v = s["board"][m["from"]][-1]
                    s["board"][m["from"]] = s["board"][m["from"]][:-1]
                tower = s["board"][m["to"]]
                if m["action"] == "capture":
                    tower = [p for p in tower if (p - 1) // 14 == c]
                elif m["betray"]:
                    replaced = []
                    for p in tower:
                        if (p - 1) // 14 != c:
                            k = (p - 1) % 14
                            s["hand"][c][k] -= 1
                            p = 1 + c * 14 + k
                        replaced.append(p)
                    tower = replaced
                s["board"][m["to"]] = tower + [v]
            if s["draft"]:
                if sum(s["hand"][c]) == 0:
                    s["done"][c] = True
                if s["done"][1 - s["first"]]:
                    s["draft"] = False
                    s["turn"] = s["first"]
                    s["done"] = [True, True]
                else:
                    s["turn"] = c if s["done"][1 - c] else 1 - c
            else:
                s["turn"] = 1 - c
            return s

        with Engine() as e:
            rng = random.Random(11)
            s = e.call("new")
            for _ in range(120):
                moves = e.call("legal")
                if not moves:
                    break
                m = rng.choice(moves)
                expected = reference(s, m)
                s = e.call("play", move=m)
                actual = {k: v for k, v in s.items() if k != "history"}
                self.assertEqual(actual, expected)

    def test_stop_returns_legal_move(self):
        with Engine() as e:
            e.call("new")
            legal = e.call("legal")
            e.process.stdin.write(json.dumps(dict(cmd="search", ms=100000)) + "\n")
            e.process.stdin.write(json.dumps(dict(cmd="stop")) + "\n")
            e.process.stdin.flush()
            self.assertTrue(e.selector.select(3))
            reply = json.loads(e.process.stdout.readline())
            self.assertTrue(reply["ok"])
            self.assertIn(reply["result"]["move"], legal)
            self.assertEqual(e.call("state")["draft"], True)


if __name__ == "__main__":
    unittest.main()
