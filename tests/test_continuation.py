import gzip
import json
import random
import tempfile
import unittest
from pathlib import Path

from benchmark.pilots import CallBudget
from benchmark.replay import restore_game
from benchmark.run import play


class Game:
    def __init__(self, *args, **kwargs):
        self.position = 0

    def observe(self, seat):
        return json.dumps({"seat": seat, "position": self.position,
                           "legalActions": [{"index": 1}, {"index": 2}]})

    def decision_seat(self):
        return "p1" if self.position < 3 else None

    def act(self, index):
        if index not in {1, 2}:
            raise ValueError("Illegal index")
        self.position += 1

    def result(self):
        return "p1" if self.position == 3 else None


class Engine:
    Game = Game

    @staticmethod
    def simulation_fingerprint():
        return "test-fingerprint"


class Pilot:
    def __init__(self, budget):
        self.budget = budget

    def choose(self, view, agent):
        self.budget.reserve()
        return 1, {"backend": "file-pilot"}


class ContinuationTests(unittest.TestCase):
    job = {"agents": ["luna", "sol"], "decks": ["A", "B"], "seed": 1,
           "replicate": 0, "seatSwap": False}
    manifest = {"engine": {"fingerprint": "test-fingerprint"},
                "randomPolicy": "python-uniform-legal-actions-v1"}

    def test_per_game_cap_resets_without_resetting_whole_run_budget(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            (output / "journals").mkdir()
            pilot = Pilot(CallBudget(10))
            first = play(Engine, self.job, "f", "r1", pilot, [], output, 10, 1)
            second = play(Engine, self.job, "f", "r2", pilot, [], output, 10, 1)
            self.assertEqual((first["modelCalls"], second["modelCalls"], pilot.budget.calls), (1, 1, 2))
            self.assertEqual(second["error"], "Per-game model call limit reached")

    def test_resume_replays_history_and_only_budgets_new_decisions(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            (output / "journals").mkdir()
            first = play(Engine, self.job, "f", "r1", Pilot(CallBudget(10)), [], output, 10, 1)
            original = (output / first["journal"]).read_bytes()
            restored = restore_game(Engine, first, self.manifest, output)
            pilot = Pilot(CallBudget(10))
            continued = play(Engine, self.job, "f", "r2", pilot, [], output, 10, 5, resume=restored)
            self.assertEqual((continued["status"], continued["result"], continued["modelCalls"]), ("complete", "p1", 3))
            self.assertEqual(pilot.budget.calls, 2)
            self.assertEqual((output / first["journal"]).read_bytes(), original)
            restored_final = restore_game(Engine, continued, self.manifest, output)
            self.assertEqual(len(restored_final[1]), 3)

    def test_global_cap_still_stops_calls_below_per_game_cap(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            (output / "journals").mkdir()
            result = play(Engine, self.job, "f", "r", Pilot(CallBudget(1)), [], output, 10, 500)
            self.assertEqual((result["status"], result["modelCalls"], result["error"]),
                             ("truncated", 1, "Model call limit reached"))

    def test_restoration_advances_random_rng_and_rejects_observation_drift(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            rng = random.Random(1 ^ 0x00B07B07)
            game = Game()
            observation = json.loads(game.observe("p1"))
            choice = rng.choice(observation["legalActions"])["index"]
            entry = {"seat": "p1", "observation": observation, "index": choice,
                     "receipt": {"backend": "seeded-python-random"}}
            record = self.job | {"journal": "game.gz", "format": "f", "result": None}
            with gzip.open(output / "game.gz", "wt") as stream:
                stream.write(json.dumps(entry) + "\n")
            restored = restore_game(Engine, record, self.manifest, output)
            self.assertEqual(restored[2].getstate(), rng.getstate())
            entry["observation"]["position"] = 100
            with gzip.open(output / "game.gz", "wt") as stream:
                stream.write(json.dumps(entry) + "\n")
            with self.assertRaisesRegex(ValueError, "Observation mismatch"):
                restore_game(Engine, record, self.manifest, output)
