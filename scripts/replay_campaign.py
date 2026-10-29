"""Verify compact v2 native journals, regenerating both built-in policies."""
import argparse
import gzip
import hashlib
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("record_file", type=Path)
parser.add_argument("game_id")
parser.add_argument("--journal", type=Path, required=True)
args = parser.parse_args()
record = next(json.loads(line) for line in args.record_file.read_text().splitlines()
              if json.loads(line)["id"] == args.game_id)
if hashlib.sha256(args.journal.read_bytes()).hexdigest() != record["journalSHA256"]:
    raise SystemExit("Journal SHA-256 mismatch")
with gzip.open(args.journal, "rt") as stream:
    entries = [json.loads(line) for line in stream]
config = {k: record[k] for k in ["agents", "decks", "format", "maxActions"]}
config.update(seed=int(record["seed"]), policySeeds=[int(x) for x in record["policySeeds"]],
              replay=[e for e in entries if e["type"] == "action"])
result = subprocess.run([str(root / "native/target/release/mtg-benchmark-host")],
                        input=json.dumps(config) + "\n", text=True, capture_output=True, check=True)
events = [json.loads(line) for line in result.stdout.splitlines()]
if any(e["type"] == "error" for e in events):
    raise SystemExit(json.dumps(events))
if events[0]["fingerprint"] != record["simulationFingerprint"]:
    raise SystemExit("Engine fingerprint mismatch")
if events[-1]["type"] != "result" or events[-1]["result"] != record["result"]:
    raise SystemExit("Result mismatch")
print(f"Verified {events[-1]['decisions']} exact actions and observation hashes; result={record['result']}")
