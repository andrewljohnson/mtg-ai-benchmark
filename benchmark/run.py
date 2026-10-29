from __future__ import annotations

import argparse
import gzip
import importlib
import json
import platform
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .core import ENGINE_COMMIT, FORMATS, MODELS, PROMPT, digest, model_view, schedule
from .pilots import BudgetStop, CallBudget, CodexPilot, FilePilot, atomic_json


def play(penta, job, fmt, run_id, pilot, catalog, output, max_actions):
    game_id = digest({"runId": run_id, "format": fmt, **job})[:20]
    record = {**job, "id": game_id, "runId": run_id, "format": fmt,
              "result": None, "status": "error", "decisions": 0,
              "modelCalls": 0, "durationSeconds": 0}
    start = time.monotonic()
    start_calls = pilot.budget.calls
    native_seat = job["agents"].index("handcrafted") if "handcrafted" in job["agents"] else None
    opponent = job["agents"][native_seat] if native_seat is not None else "external"
    rng = random.Random(job["seed"] ^ 0x00B07B07)
    journal_path = output / "journals" / f"{game_id}.jsonl.gz"
    try:
        game = penta.Game(*job["decks"], opponent=opponent,
                          opponent_seat="p1" if native_seat == 0 else "p2",
                          seed=job["seed"], format=fmt, match_mode="one-conclusion")
        with gzip.open(journal_path, "wt", encoding="utf-8") as journal:
            for _ in range(max_actions):
                if game.result() is not None:
                    break
                seat = game.decision_seat()
                observation = json.loads(game.observe(seat))
                actions = observation["legalActions"]
                if not actions:
                    raise RuntimeError("Live game has no legal actions")
                agent = job["agents"][0 if seat == "p1" else 1]
                receipt = {"backend": "forced"}
                if len(actions) == 1:
                    choice = actions[0]["index"]
                elif agent == "random":
                    choice = rng.choice(actions)["index"]
                    receipt = {"backend": "seeded-python-random"}
                else:
                    choice, receipt = pilot.choose(model_view(observation, catalog), {"id": agent, **MODELS[agent]})
                journal.write(json.dumps({"seat": seat, "observation": observation,
                                          "index": choice, "receipt": receipt}) + "\n")
                journal.flush()
                game.act(choice)
                record["decisions"] += 1
            record["result"] = game.result()
            record["status"] = "complete" if record["result"] is not None else "truncated"
    except BudgetStop as error:
        record["status"] = "truncated"
        record["error"] = str(error)
    except Exception as error:
        record["errorType"] = type(error).__name__
        record["error"] = str(error)
    record["durationSeconds"] = round(time.monotonic() - start, 3)
    record["modelCalls"] = pilot.budget.calls - start_calls
    record["journal"] = f"journals/{game_id}.jsonl.gz"
    return record


def main():
    parser = argparse.ArgumentParser(description="Run real Penta games; subscription model access only")
    parser.add_argument("--engine", type=Path, default=Path(".engine"))
    parser.add_argument("--format", default="old-school-93-94", choices=FORMATS + ["all"])
    parser.add_argument("--agents", default="random,handcrafted")
    parser.add_argument("--decks", help="JSON array of deck names; omitted selects every built-in deck")
    parser.add_argument("--pairs", type=int, default=1, help="Seed pairs per ordered deck matchup")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--max-games", type=int)
    parser.add_argument("--max-actions", type=int, default=10000)
    parser.add_argument("--max-model-calls", type=int, default=100)
    parser.add_argument("--pilot", choices=["codex", "file"], default="codex")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], default="low")
    parser.add_argument("--session", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    agents = args.agents.split(",")
    if any(a not in {*MODELS, "random", "handcrafted"} for a in agents):
        parser.error("Unknown agent")
    for agent in agents:
        if agent in MODELS:
            MODELS[agent] = {**MODELS[agent], "effort": args.effort}
    if args.max_games is not None and (args.max_games < 2 or args.max_games % 2):
        parser.error("--max-games must be positive and even to preserve seat pairs")
    if args.max_actions < 1 or args.max_model_calls < 0:
        parser.error("Action limit must be positive and call limit nonnegative")
    if args.pilot == "file" and args.session is None:
        parser.error("--pilot file requires --session")
    if args.pilot == "codex" and any(a in MODELS for a in agents):
        import subprocess
        status = subprocess.run(["codex", "login", "status"], capture_output=True, text=True)
        if status.returncode or "ChatGPT" not in status.stdout + status.stderr:
            parser.error("Subscription-only benchmark requires Codex ChatGPT authentication")
    engine = args.engine.resolve()
    sys.path.insert(0, str(engine))
    penta = importlib.import_module("penta")
    if not str(Path(penta.__file__).resolve()).startswith(str(engine) + "/"):
        parser.error("Penta must load from the selected pinned engine directory")
    lock = json.loads((engine / "provenance.json").read_text())
    if lock["commit"] != ENGINE_COMMIT or lock["fingerprint"] != penta.simulation_fingerprint():
        parser.error("Engine provenance mismatch; rerun engine setup")
    if args.out.exists():
        parser.error("Output already exists; use a new directory to preserve prior runs")
    formats = [fmt for fmt in FORMATS if penta.deck_names(format=fmt)] if args.format == "all" else [args.format]
    plans = []
    deck_lists = {}
    for fmt in formats:
        available = penta.deck_names(format=fmt)
        decks = json.loads(args.decks) if args.decks else available
        if not decks or any(d not in available for d in decks):
            parser.error(f"Selected deck unavailable in {fmt}")
        deck_lists[fmt] = decks
        plans.extend((fmt, job) for job in schedule(agents, decks, args.pairs, args.seed))
    planned = len(plans)
    if args.max_games:
        plans = plans[:args.max_games]
    spec = {"engine": lock, "agents": agents, "models": {a: MODELS[a] for a in agents if a in MODELS},
            "deckLists": deck_lists, "pairs": args.pairs, "seed": args.seed,
            "maxGames": args.max_games, "maxActions": args.max_actions,
            "maxModelCalls": args.max_model_calls, "pilotBackend": args.pilot,
            "promptHash": digest(PROMPT), "prompt": PROMPT, "schemaVersion": 1,
            "harnessVersion": "1.0.0", "randomPolicy": "python-uniform-legal-actions-v1",
            "harnessSourceHash": digest({p.name: p.read_text() for p in sorted(Path(__file__).parent.glob("*.py"))}),
            "python": platform.python_version(), "platform": platform.platform()}
    created_at = datetime.now(timezone.utc).isoformat()
    run_id = digest({"spec": spec, "createdAt": created_at})[:16]
    args.out.mkdir(parents=True)
    (args.out / "journals").mkdir()
    metadata = {**spec, "runId": run_id, "configHash": digest(spec), "createdAt": created_at,
                "plannedGames": planned, "selectedGames": len(plans), "state": "running",
                "billing": "subscription-only", "apiSpendUSD": 0}
    atomic_json(args.out / "run.json", metadata)
    budget = CallBudget(args.max_model_calls)
    pilot = FilePilot(args.session, budget) if args.pilot == "file" else CodexPilot(budget)
    catalogs = {fmt: json.loads(penta.catalog(format=fmt))["cards"] for fmt in formats}
    count = 0
    errors = 0
    with (args.out / "games.jsonl").open("w") as stream:
        for fmt, job in plans:
            record = play(penta, job, fmt, run_id, pilot, catalogs[fmt], args.out, args.max_actions)
            stream.write(json.dumps(record) + "\n")
            stream.flush()
            count += 1
            errors += record["status"] == "error"
            if count % 20 == 0 or any(a in MODELS for a in agents):
                print(f"{count}/{len(plans)} {fmt} {record['status']} {record['result']} calls={budget.calls}", flush=True)
            if errors >= 3 or record.get("error") == "Model call limit reached":
                break
    metadata.update({"state": "finished" if count == len(plans) else "stopped",
                     "recordedGames": count, "modelCalls": budget.calls,
                     "tokenUsage": None if args.pilot == "file" and budget.calls else budget.usage,
                     "tokenUsageAvailable": args.pilot != "file" or budget.calls == 0})
    atomic_json(args.out / "run.json", metadata)
    if args.pilot == "file":
        atomic_json(args.session / "observation.json", {"done": True, "recordedGames": count})
    print(json.dumps({"runId": run_id, "games": count, "modelCalls": budget.calls, "errors": errors}), flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
