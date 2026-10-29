"""Verify a game's external actions and observations against its exact engine build."""
import argparse
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
sys.path.insert(0, str(root))

manifest = json.loads((args.run / "run.json").read_text())
from benchmark.replay import restore_game

record = next(json.loads(line) for line in (args.run / "games.jsonl").read_text().splitlines()
              if json.loads(line)["id"] == args.game_id)
game, entries, _, _ = restore_game(penta, record, manifest, args.run)
print(f"Verified {len(entries)} decisions; result={game.result()}")
