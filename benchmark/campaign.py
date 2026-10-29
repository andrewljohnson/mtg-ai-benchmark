"""Durable, coverage-first Old School evaluation campaign."""
from __future__ import annotations

import argparse
import fcntl
import gzip
import itertools
import json
import math
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .core import ENGINE_COMMIT, MODELS, PROMPT, aggregate, digest, model_view
from .pilots import CallBudget, FilePilot, atomic_json

ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(timezone.utc).isoformat()


def cells(agents, decks):
    competitors = list(itertools.product(agents, decks))
    return [{"id": digest([a, b])[:16], "a": list(a), "b": list(b)}
            for a, b in itertools.combinations_with_replacement(competitors, 2)]


def job_for(cell, replicate, swapped):
    seed = int(digest(["old-school-v2", cell["id"], replicate])[:16], 16)
    policy_seeds = [int(digest(["policy", cell["id"], replicate, i])[:16], 16) for i in [0, 1]]
    competitors = [cell["a"], cell["b"]]
    if swapped:
        competitors.reverse()
        policy_seeds.reverse()
    return {"id": digest([cell["id"], replicate, swapped])[:20], "cellId": cell["id"],
            "replicate": replicate, "seatSwap": swapped, "agents": [x[0] for x in competitors],
            "decks": [x[1] for x in competitors], "seed": seed, "policySeeds": policy_seeds,
            "format": "old-school-93-94", "maxActions": 100000}


def connect(directory):
    db = sqlite3.connect(directory / "queue.sqlite", timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY, cell TEXT, replicate INTEGER, swap INTEGER, record TEXT)")
    if db.execute("SELECT count(*) FROM games").fetchone()[0] == 0:
        campaign_id = json.loads((directory / "plan.json").read_text())["id"]
        for path in sorted((ROOT / "results" / campaign_id / "batches").glob("*.jsonl")):
            for line in path.read_text().splitlines():
                record = json.loads(line)
                db.execute("INSERT OR IGNORE INTO games VALUES(?,?,?,?,?)",
                           (record["id"], record["cellId"], record["replicate"], int(record["seatSwap"]), json.dumps(record)))
        db.commit()
    return db


def next_pair(plan, db, kind):
    complete = {row[0]: json.loads(row[1]) for row in db.execute("SELECT id,record FROM games")}
    eligible = [c for c in plan["cells"] if (any(a in MODELS for a in [c["a"][0], c["b"][0]])) == (kind == "model")]
    for replicate in range(plan["targetSeedPairs"]):
        for cell in eligible:
            jobs = [job_for(cell, replicate, swapped) for swapped in [False, True]]
            unfinished = [j for j in jobs if complete.get(j["id"], {}).get("status") != "complete"]
            if unfinished:
                return unfinished
    return []


def infer(values, family_size, target=738):
    n = len(values)
    if not n:
        return {"pairs": 0, "scoreRate": None, "pairCI95": None, "familyCI95": None,
                "inferenceReady": False}
    mean = sum(values) / n
    radius = math.sqrt(math.log(2 / .05) / (2 * n))
    family_radius = math.sqrt(math.log(2 * family_size / .05) / (2 * n))
    interval = lambda width: [max(0, mean - width), min(1, mean + width)]
    return {"pairs": n, "scoreRate": mean, "pairCI95": interval(radius),
            "familyCI95": interval(family_radius), "inferenceReady": n >= target and radius <= .05}


def summary(plan, records):
    grouped = {}
    for record in records:
        grouped.setdefault(record["cellId"], {}).setdefault(record["replicate"], {})[bool(record["seatSwap"])] = record
    result = []
    for cell in plan["cells"]:
        values = []
        completed = 0
        unfinished = 0
        for replicate, orientations in grouped.get(cell["id"], {}).items():
            pair = [orientations.get(swapped) for swapped in [False, True]]
            completed += sum(bool(r and r["status"] == "complete") for r in pair)
            unfinished += sum(bool(r and r["status"] != "complete") for r in pair)
            if all(r and r["status"] == "complete" for r in pair):
                score = []
                for r, seat in zip(pair, ["p1", "p2"]):
                    score.append(.5 if r["result"] == "draw" else float(r["result"] == seat))
                values.append(sum(score) / 2)
        result.append({**cell, **infer(values, len(plan["cells"]), plan["targetSeedPairs"]),
                       "completedGames": completed, "unfinishedGames": unfinished,
                       "mirrorControl": cell["a"] == cell["b"]})
    return result


def initialize(directory):
    adapter_hash = digest({"source": (ROOT / "native/src/main.rs").read_text(),
                           "lock": (ROOT / "native/Cargo.lock").read_text()})
    if (directory / "plan.json").exists():
        plan = json.loads((directory / "plan.json").read_text())
        if plan.get("adapterSourceHash", adapter_hash) != adapter_hash:
            raise ValueError("Native adapter or dependency lock changed; start a new campaign")
        plan["adapterSourceHash"] = adapter_hash
        atomic_json(directory / "plan.json", plan)
        return plan
    directory.mkdir(parents=True, exist_ok=True)
    published = ROOT / "results/old-school-v2/run.json"
    if published.exists():
        plan = json.loads(published.read_text())
        if plan.get("adapterSourceHash", adapter_hash) != adapter_hash:
            raise ValueError("Published campaign has a different native adapter")
        plan["adapterSourceHash"] = adapter_hash
        atomic_json(directory / "plan.json", plan)
        return plan
    sys.path.insert(0, str(ROOT / ".engine"))
    import penta
    decks = penta.deck_names(format="old-school-93-94")
    plan = {"id": "old-school-v2", "createdAt": now(), "format": "old-school-93-94",
            "engineCommit": ENGINE_COMMIT, "agents": ["random", "handcrafted", "luna"],
            "decks": decks, "targetSeedPairs": 738, "targetGamesPerCell": 1476,
            "cells": cells(["random", "handcrafted", "luna"], decks),
            "models": {"luna": MODELS["luna"]}, "prompt": PROMPT, "promptHash": digest(PROMPT),
            "randomPolicy": "splitmix64-rejection-uniform-index-v1", "adapterVersion": "2.0.0",
            "adapterSourceHash": adapter_hash,
            "precision": "738 independent seed pairs; fixed-horizon Hoeffding pointwise 95% +/-5pp bound",
            "inference": "Fixed-horizon paired-score Hoeffding bounds; Bonferroni across all cells; exploratory until target reached",
            "training": False, "contextPolicy": "Fresh native Luna context per game and separate context per seat; no cross-seat observations",
            "subscriptionUsageCeilingPercent": 75, "billing": "subscription-only"}
    plan["targetGames"] = len(plan["cells"]) * plan["targetGamesPerCell"]
    atomic_json(directory / "plan.json", plan)
    return plan


def read_partial(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def game(plan, job, directory, sessions, lane=None):
    work = directory / "work"
    work.mkdir(exist_ok=True)
    path = work / f"{job['id']}.jsonl"
    prior = read_partial(path)
    actions = [e for e in prior if e["type"] == "action"]
    prior_calls = sum(e["type"] == "model" for e in prior)
    budget = CallBudget(2000 - prior_calls)
    pilots = {seat: FilePilot(sessions / seat, budget, timeout=900) for seat in ["p1", "p2"]}
    for seat in ["p1", "p2"]:
        atomic_json(sessions / seat / "observation.json", {"waiting": True})
    atomic_json(directory / f"active-{lane or ('model' if any(a in MODELS for a in job['agents']) else 'baseline')}.json",
                {"gameId": job["id"], "agents": job["agents"], "decks": job["decks"],
                 "sessions": str(sessions), "pid": os.getpid(), "status": "running"})
    started = time.monotonic()
    config = dict(job, replay=actions)
    if plan.get("nativeModelRole"):
        config["agents"] = [plan["nativeModelRole"] if a in plan["models"] else a for a in job["agents"]]
    host = subprocess.Popen([str(ROOT / "native/target/release/mtg-benchmark-host")], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    record = dict(job, seed=str(job["seed"]), policySeeds=[str(x) for x in job["policySeeds"]],
                  runId=plan["id"], status="deferred", result=None, modelCalls=prior_calls,
                  journalVersion=2, startedAt=now())
    if plan.get("nativeModelRole"):
        record["nativeAgents"] = config["agents"]
        record["models"] = {a: plan["models"][a] for a in job["agents"] if a in plan["models"]}
    host.stdin.write(json.dumps(config) + "\n")
    host.stdin.flush()
    sys.path.insert(0, str(ROOT / ".engine"))
    import penta
    catalog = json.loads(penta.catalog(format=job["format"]))["cards"]
    try:
        with path.open("a") as journal:
            for line in host.stdout:
                event = json.loads(line)
                if event["type"] == "start":
                    fingerprint = event["fingerprint"]
                    if plan.get("simulationFingerprint") and plan["simulationFingerprint"] != fingerprint:
                        raise ValueError("Campaign engine fingerprint changed")
                    record["simulationFingerprint"] = fingerprint
                elif event["type"] == "observe":
                    seat = event["seat"]
                    pending = next((e for e in prior if e["type"] == "model" and e["position"] == event["position"]), None)
                    if pending:
                        if pending["observation"] != event["observation"]:
                            raise ValueError("Pending model observation changed during recovery")
                        choice = pending["index"]
                    else:
                        choice, receipt = pilots[seat].choose(model_view(event["observation"], catalog),
                                                             {"id": job["agents"][0 if seat == "p1" else 1],
                                                              **plan["models"][job["agents"][0 if seat == "p1" else 1]]})
                        journal.write(json.dumps({"type": "model", "seat": seat, "position": event["position"],
                                                  "observation": event["observation"], "index": choice, "receipt": receipt}) + "\n")
                    journal.flush()
                    os.fsync(journal.fileno())
                    host.stdin.write(json.dumps({"index": choice}) + "\n")
                    host.stdin.flush()
                elif event["type"] == "action":
                    journal.write(json.dumps(event) + "\n")
                    journal.flush()
                elif event["type"] == "result":
                    record.update({k: event[k] for k in ["status", "result", "decisions"]})
                    break
                elif event["type"] == "error":
                    raise RuntimeError(event["error"])
            else:
                raise RuntimeError("Native engine ended without a result")
    except Exception as error:
        record["error"] = str(error)
    finally:
        host.terminate()
        host.wait(timeout=10)
    record["modelCalls"] = prior_calls + budget.calls
    record["durationSeconds"] = round(time.monotonic() - started, 3)
    if record["status"] == "complete":
        target = directory / "journals" / f"{job['id']}.jsonl.gz"
        target.parent.mkdir(exist_ok=True)
        with gzip.open(target, "wt") as output:
            output.write(path.read_text())
        record["journal"] = f"journals/{target.name}"
        record["journalSHA256"] = __import__("hashlib").sha256(target.read_bytes()).hexdigest()
    for seat in ["p1", "p2"]:
        atomic_json(sessions / seat / "observation.json", {"done": True, "gameId": job["id"],
                                                         "status": record["status"], "result": record["result"]})
    atomic_json(directory / f"active-{lane or ('model' if any(a in MODELS for a in job['agents']) else 'baseline')}.json",
                {"gameId": job["id"], "status": record["status"], "pid": None})
    return record


def export(directory, plan, db):
    with (directory / "export.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return export_locked(directory, plan, db)[0]


def export_locked(directory, plan, db, published_only=False):
    records = [json.loads(r[0]) for r in db.execute("SELECT record FROM games ORDER BY rowid")]
    if published_only:
        records = [r for r in records if r["status"] != "complete" or r.get("journalArchive")]
    target = ROOT / "results" / plan["id"]
    target.mkdir(exist_ok=True)
    for record in records:
        record["seed"] = str(record["seed"])
        record["policySeeds"] = [str(x) for x in record["policySeeds"]]
    completed = [r for r in records if r["status"] == "complete"]
    payload_pilots = {a: sum(a in r["agents"] for r in completed) for a in plan["agents"]}
    payload = {**plan, "runId": plan["id"], "state": "finished" if len(completed) == plan["targetGames"] else "running", "selectedGames": plan["targetGames"],
               "plannedGames": plan["targetGames"], "recordedGames": len(records),
               "completedGames": len(completed), "deckLists": {plan["format"]: plan["decks"]},
               "pilotBackend": "native-separated-seats", "tokenUsage": None,
               "coverage": {"cells": len(plan["cells"]), "targetSeedPairs": plan["targetSeedPairs"]},
               "deferredGames": len(records) - len(completed),
               "updatedAt": now(), "apiSpendUSD": 0, "pilotUniqueGames": payload_pilots,
               "ledgerIsRecentWindow": True, "fullLedgerDirectory": "batches"}
    atomic_json(target / "run.json", payload)
    atomic_json(target / "coverage.json", summary(plan, records))
    ledger = target / "games.jsonl"
    temporary = ledger.with_suffix(".tmp")
    temporary.write_text("".join(json.dumps(r) + "\n" for r in records[-500:]))
    temporary.replace(ledger)
    atomic_json(target / "aggregate.json", aggregate(records))
    batches = target / "batches"
    batches.mkdir(exist_ok=True)
    for offset in range(0, len(records), 1000):
        batch_path = batches / f"{offset // 1000:06}.jsonl"
        content = "".join(json.dumps(r) + "\n" for r in records[offset:offset + 1000])
        if not batch_path.exists() or batch_path.read_text() != content:
            temporary = batch_path.with_suffix(".tmp")
            temporary.write_text(content)
            temporary.replace(batch_path)
    return target, records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "work", "status", "export"])
    parser.add_argument("--directory", type=Path, default=ROOT / ".campaign")
    parser.add_argument("--kind", choices=["baseline", "model"], default="baseline")
    parser.add_argument("--games", type=int, default=50)
    parser.add_argument("--cell")
    parser.add_argument("--lane", help="Explicit parallel model cell; requires --cell")
    parser.add_argument("--publish-every", type=int, default=0)
    parser.add_argument("--sessions", type=Path, default=ROOT / ".sessions/campaign")
    args = parser.parse_args()
    if args.lane and (args.kind != "model" or not args.cell or not args.lane.replace("-", "").isalnum()):
        parser.error("--lane requires model kind, an explicit cell, and an alphanumeric lane name")
    plan = initialize(args.directory)
    db = connect(args.directory)
    if args.command in {"init", "status", "export"}:
        export(args.directory, plan, db)
        print(json.dumps({"campaign": plan["id"], "cells": len(plan["cells"]), "targetGames": plan["targetGames"],
                          "recordedGames": db.execute("SELECT count(*) FROM games").fetchone()[0]}))
        return
    with (args.directory / f"{args.kind}.lock").open("w") as lock:
        try:
            fcntl.flock(lock, (fcntl.LOCK_SH if args.lane else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another worker already holds this campaign lane")
        cell_lock = None
        if args.lane:
            cell_lock = (args.directory / f"model-{args.cell}.lock").open("w")
            try:
                fcntl.flock(cell_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SystemExit("Another worker already holds this matchup")
        count = 0
        while count < args.games:
            selection = dict(plan, cells=[c for c in plan["cells"] if not args.cell or c["id"] == args.cell])
            jobs = next_pair(selection, db, args.kind)
            if not jobs:
                break
            for job in jobs:
                if count >= args.games:
                    break
                previous_row = db.execute("SELECT record FROM games WHERE id=?", (job["id"],)).fetchone()
                previous = json.loads(previous_row[0]) if previous_row else None
                record = game(plan, job, args.directory, args.sessions / job["id"], args.lane)
                record["attempts"] = (previous.get("attempts", 1) if previous else 0) + 1
                if previous:
                    record["previousAttempts"] = previous.get("previousAttempts", []) + [
                        {k: previous.get(k) for k in ["status", "error", "modelCalls", "decisions", "durationSeconds"]}]
                db.execute("INSERT OR REPLACE INTO games VALUES(?,?,?,?,?)",
                           (job["id"], job["cellId"], job["replicate"], int(job["seatSwap"]), json.dumps(record)))
                db.commit()
                if record.get("simulationFingerprint"):
                    plan = initialize(args.directory)
                    plan["simulationFingerprint"] = record["simulationFingerprint"]
                    atomic_json(args.directory / "plan.json", plan)
                count += 1
                print(json.dumps({"game": record["id"], "agents": record["agents"], "status": record["status"],
                                  "result": record["result"], "gamesThisBatch": count}), flush=True)
                if record["status"] != "complete":
                    export(args.directory, plan, db)
                    return
            export(args.directory, plan, db)
            if args.publish_every and count % args.publish_every == 0:
                from .publish import publish
                publish(args.directory)
    export(args.directory, plan, db)
    if args.publish_every:
        from .publish import publish
        publish(args.directory)


if __name__ == "__main__":
    main()
