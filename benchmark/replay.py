import gzip
import json
import random


def restore_game(penta, record, manifest, directory):
    if penta.simulation_fingerprint() != manifest["engine"]["fingerprint"]:
        raise ValueError("Simulation fingerprint mismatch; rebuild the original engine")
    native_seat = record["agents"].index("handcrafted") if "handcrafted" in record["agents"] else None
    if manifest.get("randomPolicy") is None and "random" in record["agents"] and native_seat is None:
        native_seat = record["agents"].index("random")
    game = penta.Game(*record["decks"],
                      opponent=record["agents"][native_seat] if native_seat is not None else "external",
                      opponent_seat="p1" if native_seat == 0 else "p2",
                      seed=record["seed"], format=record["format"], match_mode="one-conclusion")
    rng = random.Random(record["seed"] ^ 0x00B07B07)
    entries = []
    with gzip.open(directory / record["journal"], "rt") as stream:
        for line in stream:
            entry = json.loads(line)
            observation = json.loads(game.observe(entry["seat"]))
            if game.decision_seat() != entry["seat"] or observation != entry["observation"]:
                raise ValueError(f"Observation mismatch at decision {len(entries)}")
            if entry["receipt"]["backend"] == "seeded-python-random":
                if rng.choice(observation["legalActions"])["index"] != entry["index"]:
                    raise ValueError("Random policy history mismatch")
            game.act(entry["index"])
            entries.append(entry)
    if game.result() != record["result"]:
        raise ValueError("Final result mismatch")
    return game, entries, rng, record
