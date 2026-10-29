"""Exchange only redacted observations and validated action indices with a running harness."""
import argparse
import json
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("session", type=Path)
parser.add_argument("--request", type=int)
parser.add_argument("--index", type=int)
args = parser.parse_args()
cursor = args.session / "client-cursor.json"
last_request = args.request
if last_request is None and cursor.exists():
    last_request = json.loads(cursor.read_text()).get("requestId")
if args.index is not None:
    if args.request is None:
        parser.error("--index requires --request")
    observation = json.loads((args.session / "observation.json").read_text())
    legal = observation.get("view", {}).get("observation", {}).get("legalActions", [])
    if observation.get("requestId") != args.request or args.index not in {a["index"] for a in legal}:
        print(json.dumps({"error": "Choice does not match the current request and legal indices", "currentRequest": observation}))
        raise SystemExit(1)
    target = args.session / "action.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"requestId": args.request, "index": args.index}))
    temporary.replace(target)
    cursor.write_text(json.dumps({"requestId": args.request}))
deadline = time.monotonic() + 20
while time.monotonic() < deadline:
    target = args.session / "observation.json"
    if target.exists():
        value = json.loads(target.read_text())
        if value.get("done") or value.get("requestId") != last_request:
            if "view" in value:
                value["view"]["cardReference"] = [
                    {k: v for k, v in card.items() if k not in {"printings", "structure"}}
                    for card in value["view"]["cardReference"]
                ]
            print(json.dumps(value))
            break
    time.sleep(.1)
else:
    print(json.dumps({"waiting": True}))
