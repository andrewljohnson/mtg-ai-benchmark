import unittest

from benchmark.core import aggregate, model_view, schedule, validate_choice, wilson


class BenchmarkTests(unittest.TestCase):
    def test_every_deck_pair_swaps_pilots_and_decks_at_the_same_seed(self):
        jobs = list(schedule(["luna", "random", "handcrafted"], ["A", "B"], 2, 17))
        self.assertEqual(len(jobs), 48)
        for first, second in zip(jobs[::2], jobs[1::2]):
            self.assertEqual(first["agents"], second["agents"][::-1])
            self.assertEqual(first["decks"], second["decks"][::-1])
            self.assertEqual(first["seed"], second["seed"])
        lunar = [j for j in jobs if j["agents"] == ["luna", "random"]]
        self.assertEqual({tuple(j["decks"]) for j in lunar}, {("A", "A"), ("A", "B"), ("B", "A"), ("B", "B")})

    def test_draws_stay_in_denominator_and_failures_are_not_losses(self):
        base = {"runId": "r", "format": "f", "agents": ["luna", "random"], "decks": ["A", "B"]}
        records = [base | {"status": status, "result": result} for status, result in
                   [("complete", "p1"), ("complete", "draw"), ("error", None), ("truncated", None)]]
        rows = aggregate(records)
        luna = next(r for r in rows if r["agent"] == "luna")
        opponent = next(r for r in rows if r["agent"] == "random")
        self.assertEqual((luna["winRate"], luna["scoreRate"], luna["losses"]), (.5, .75, 0))
        self.assertEqual((luna["errors"], luna["truncated"], luna["games"]), (1, 1, 4))
        self.assertEqual((opponent["wins"], opponent["losses"], opponent["draws"]), (0, 1, 1))
        only_error = aggregate([base | {"status": "error", "result": None}])[0]
        self.assertIsNone(only_error["winRate"])
        self.assertIsNone(only_error["winRateCI95"])

    def test_results_from_different_runs_are_never_pooled(self):
        record = {"runId": "r1", "format": "f", "agents": ["a", "b"], "decks": ["A", "B"],
                  "status": "complete", "result": "p1"}
        self.assertEqual(len(aggregate([record, record | {"runId": "r2"}])), 4)

    def test_legal_index_is_not_a_list_position_and_booleans_are_rejected(self):
        observation = {"legalActions": [{"index": 7}, {"index": 12}]}
        self.assertEqual(validate_choice(12, observation), 12)
        for choice in [0, True, "7", -1]:
            with self.assertRaises(ValueError):
                validate_choice(choice, observation)

    def test_reference_contains_only_visible_definitions_and_no_checkpoint(self):
        view = model_view({"hand": [{"definition": "seen"}], "checkpoint": {"definition": "hidden"},
                           "legalActions": [{"index": 0}]}, [{"definition": "seen"}, {"definition": "hidden"}])
        self.assertNotIn("checkpoint", view["observation"])
        self.assertEqual(view["cardReference"], [{"definition": "seen"}])

    def test_zero_and_perfect_scores_retain_uncertainty(self):
        self.assertIsNone(wilson(0, 0))
        self.assertAlmostEqual(wilson(0, 10)[1], .2775327998628892)
        self.assertAlmostEqual(wilson(10, 10)[0], .7224672001371107)


if __name__ == "__main__":
    unittest.main()
