"""Verify a game's external actions and observations against its exact engine build."""
import argparse
import gzip
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("run", type=Path)
parser.add_argument("game_id")
args = parser.parse_args()
sys.path.insert(0, str(root / ".engine"))
import penta

manifest = json.loads((args.run / "run.json").read_text())
if penta.simulation_fingerprint() != manifest["engine"]["fingerprint"]:
    raise SystemExit("Simulation fingerprint mismatch; rebuild the original engine")
record = next(json.loads(line) for line in (args.run / "games.jsonl").read_text().splitlines()
              if json.loads(line)["id"] == args.game_id)
native_seat = record["agents"].index("handcrafted") if "handcrafted" in record["agents"] else None
if manifest.get("randomPolicy") is None and "random" in record["agents"] and native_seat is None:
    native_seat = record["agents"].index("random")
game = penta.Game(*record["decks"], opponent=record["agents"][native_seat] if native_seat is not None else "external",
                  opponent_seat="p1" if native_seat == 0 else "p2", seed=record["seed"], format=record["format"])
count = 0
with gzip.open(args.run / record["journal"], "rt") as stream:
    for line in stream:
        entry = json.loads(line)
        if game.decision_seat() != entry["seat"] or json.loads(game.observe(entry["seat"])) != entry["observation"]:
            raise SystemExit(f"Observation mismatch at decision {count}")
        game.act(entry["index"])
        count += 1
if game.result() != record["result"]:
    raise SystemExit("Final result mismatch")
print(f"Verified {count} decisions; result={game.result()}")
