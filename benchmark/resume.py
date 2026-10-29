"""Continue truncated games into a new run without rewriting original evidence."""
import argparse
import importlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .core import MODELS, digest
from .pilots import CallBudget, FilePilot, atomic_json
from .replay import restore_game
from .run import play


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--engine", type=Path, default=Path(".engine"))
    parser.add_argument("--max-model-calls", type=int, default=2000)
    parser.add_argument("--max-model-calls-per-game", type=int, default=500)
    parser.add_argument("--max-actions", type=int)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists; original runs must remain unchanged")
    if args.max_model_calls < 1 or args.max_model_calls_per_game < 1:
        parser.error("Model call limits must be positive")
    metadata = json.loads((args.from_run / "run.json").read_text())
    if metadata["state"] == "running" or metadata["pilotBackend"] != "file":
        parser.error("Resume requires a stopped file-pilot run")
    records = [json.loads(line) for line in (args.from_run / "games.jsonl").read_text().splitlines()]
    if not any(r["status"] == "truncated" for r in records):
        parser.error("No truncated games to continue")
    max_actions = args.max_actions if args.max_actions is not None else metadata["maxActions"]
    if any(r["decisions"] >= max_actions for r in records if r["status"] == "truncated"):
        parser.error("Increase --max-actions beyond the recorded action count to make progress")
    if any(r["modelCalls"] >= args.max_model_calls_per_game for r in records if r["status"] == "truncated"):
        parser.error("Per-game ceiling must exceed the recorded decision count")
    engine = args.engine.resolve()
    sys.path.insert(0, str(engine))
    penta = importlib.import_module("penta")
    if Path(penta.__file__).resolve().parent != engine:
        parser.error("Penta did not load from the selected engine directory")
    if penta.simulation_fingerprint() != metadata["engine"]["fingerprint"]:
        parser.error("Engine fingerprint mismatch")
    restored = {r["id"]: restore_game(penta, r, metadata, args.from_run)
                for r in records if r["status"] == "truncated"}
    for agent, config in metadata.get("models", {}).items():
        MODELS[agent] = config
    original_run = metadata["runId"]
    metadata["parentAuditNotes"] = metadata.pop("auditNotes", {})
    metadata["auditNotes"] = {"continuation": "Prior actions verified and replayed; source run is preserved unchanged",
                              "randomOpponent": metadata["parentAuditNotes"].get("randomOpponent", metadata.get("randomPolicy")),
                              "callAccounting": "Total decisions include inherited history; newModelCalls counts only this continuation"}
    created_at = datetime.now(timezone.utc).isoformat()
    run_id = digest({"parent": original_run, "createdAt": created_at,
                     "perGameCap": args.max_model_calls_per_game, "runCap": args.max_model_calls})[:16]
    metadata.update({"runId": run_id, "createdAt": created_at, "state": "running",
                     "supersedesRunId": original_run, "harnessVersion": "1.1.0",
                     "maxModelCalls": args.max_model_calls,
                     "maxActions": max_actions,
                     "maxModelCallsPerGame": args.max_model_calls_per_game,
                     "continuation": {"sourceRunId": original_run,
                                      "inheritedModelCalls": sum(r["modelCalls"] for r in records),
                                      "context": "Native pilot retains prior context; exact actions replayed before continuation"},
                     "harnessSourceHash": digest({p.name: p.read_text() for p in sorted(Path(__file__).parent.glob("*.py"))})})
    metadata.pop("configHash", None)
    metadata.pop("recordedGames", None)
    metadata.pop("modelCalls", None)
    args.out.mkdir(parents=True)
    (args.out / "journals").mkdir()
    atomic_json(args.out / "run.json", metadata)
    budget = CallBudget(args.max_model_calls)
    pilot = FilePilot(args.session, budget)
    results = []
    with (args.out / "games.jsonl").open("w") as stream:
        for old in records:
            if old["status"] == "truncated":
                job = {k: old[k] for k in ["agents", "decks", "seed", "replicate", "seatSwap"]}
                record = play(penta, job, old["format"], run_id, pilot,
                              json.loads(penta.catalog(format=old["format"]))["cards"],
                              args.out, metadata["maxActions"], args.max_model_calls_per_game,
                              resume=restored[old["id"]])
            else:
                record = {**old, "runId": run_id, "inheritedFromRunId": original_run}
                shutil.copy2(args.from_run / old["journal"], args.out / old["journal"])
            results.append(record)
            stream.write(json.dumps(record) + "\n")
            stream.flush()
            print(f"{record['id']} {record['status']} {record['result']} total-decisions={record['modelCalls']}", flush=True)
    metadata.update({"state": "finished", "recordedGames": len(results),
                     "modelCalls": sum(r["modelCalls"] for r in results),
                     "newModelCalls": budget.calls, "tokenUsage": None, "tokenUsageAvailable": False})
    atomic_json(args.out / "run.json", metadata)
    atomic_json(args.session / "observation.json", {"done": True, "recordedGames": len(results)})
    return 1 if any(r["status"] == "error" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
