import itertools
import unittest

from benchmark.campaign import cells, infer, job_for, next_pair, summary


class FakeDB:
    def __init__(self, records):
        self.records = records

    def execute(self, query):
        import json
        return [(r["id"], json.dumps(r)) for r in self.records]


class CampaignTests(unittest.TestCase):
    def test_canonical_cells_cover_every_directed_pilot_deck_permutation(self):
        agents = ["random", "handcrafted", "luna"]
        decks = [str(i) for i in range(15)]
        matrix = cells(agents, decks)
        self.assertEqual(len(matrix), 1035)
        covered = set()
        for cell in matrix:
            for swapped in [False, True]:
                job = job_for(cell, 0, swapped)
                covered.add(tuple(zip(job["agents"], job["decks"])))
        competitors = list(itertools.product(agents, decks))
        self.assertEqual(covered, set(itertools.product(competitors, repeat=2)))

    def test_swapping_seats_keeps_identity_rng_and_seed_together(self):
        cell = cells(["random"], ["A", "B"])[1]
        first, second = [job_for(cell, 3, swap) for swap in [False, True]]
        self.assertEqual(first["policySeeds"], second["policySeeds"][::-1])
        self.assertEqual(first["decks"], second["decks"][::-1])
        self.assertEqual(first["seed"], second["seed"])
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotEqual(first["seed"], job_for(cell, 4, False)["seed"])

    def test_partial_pair_is_not_an_independent_observation_and_retries_keep_job_identity(self):
        cell = cells(["random"], ["A"])[0]
        plan = {"cells": [cell], "targetSeedPairs": 2}
        first, second = [job_for(cell, 0, swap) | {"status": "complete", "result": "p1"} for swap in [False, True]]
        partial = summary(plan, [first])[0]
        self.assertEqual((partial["pairs"], partial["completedGames"]), (0, 1))
        self.assertEqual(next_pair(plan, FakeDB([first]), "baseline")[0]["id"], second["id"])
        paired = summary(plan, [first, second])[0]
        self.assertEqual((paired["pairs"], paired["scoreRate"]), (1, .5))
        deferred = second | {"status": "deferred", "result": None}
        self.assertEqual(summary(plan, [first, deferred])[0]["pairs"], 0)
        self.assertEqual(next_pair(plan, FakeDB([first, deferred]), "baseline")[0]["id"], second["id"])

    def test_family_bounds_are_wider_and_perfect_small_samples_do_not_look_certain(self):
        early = infer([1, 1], 1035)
        self.assertFalse(early["inferenceReady"])
        self.assertLess(early["pairCI95"][0], .1)
        final = infer([.5] * 738, 1035)
        self.assertTrue(final["inferenceReady"])
        self.assertLessEqual((final["pairCI95"][1] - final["pairCI95"][0]) / 2, .05)
        self.assertLess(final["familyCI95"][0], final["pairCI95"][0])
