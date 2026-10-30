import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark.core import MODELS, aggregate

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--results", type=Path, default=root / "results")
parser.add_argument("--out", type=Path, default=root / "dist")
args = parser.parse_args()
runs, games, rows, coverage = [], [], [], {}
for path in sorted(args.results.glob("*/run.json")):
    run = json.loads(path.read_text())
    run["resultDirectory"] = path.parent.name
    runs.append(run)
    records = [json.loads(line) for line in (path.parent / "games.jsonl").read_text().splitlines()]
    games.extend(records)
    row_path = path.parent / "aggregate.json"
    rows.extend(json.loads(row_path.read_text()) if row_path.exists() else aggregate(records))
    coverage_path = path.parent / "coverage.json"
    if coverage_path.exists():
        coverage[run["runId"]] = json.loads(coverage_path.read_text())
superseded = {}
for run in runs:
    parent = run.get("supersedesRunId")
    if parent:
        if parent in superseded:
            raise ValueError("Multiple continuation branches would double-count inherited games")
        superseded[parent] = run["runId"]
for run in runs:
    run["supersededByRunId"] = superseded.get(run["runId"])
runs.sort(key=lambda r: (not bool(r["supersededByRunId"]), r["createdAt"]), reverse=True)
campaigns = [r for r in runs if r["runId"] in {"old-school-v2", "old-school-sol-v1"}]
if len(campaigns) == 2:
    import copy
    import math
    source_ids = {r["runId"] for r in campaigns}
    combined = copy.deepcopy(next(r for r in campaigns if r["runId"] == "old-school-v2"))
    combined.update(runId="old-school-benchmark", id="old-school-benchmark", agents=["random", "handcrafted", "luna", "sol"],
                    models={k: v for r in campaigns for k, v in r["models"].items()},
                    sourceRuns=campaigns, resultDirectory="", scope="One benchmark; parallel Luna and Sol worker queues")
    for key in ["completedGames", "recordedGames", "plannedGames", "targetGames", "selectedGames"]:
        combined[key] = sum(r.get(key, 0) for r in campaigns)
    combined["pilotUniqueGames"] = {a: sum(r.get("pilotUniqueGames", {}).get(a, 0) for r in campaigns) for a in combined["agents"]}
    combined_coverage = []
    seen_cells = set()
    for r in campaigns:
        for cell in coverage.get(r["runId"], []):
            cell = dict(cell, sourceRunId=r["runId"])
            identity = tuple(sorted((tuple(cell["a"]), tuple(cell["b"]))))
            if identity in seen_cells:
                raise ValueError("Duplicate matchup across parallel worker queues")
            seen_cells.add(identity)
            combined_coverage.append(cell)
    for cell in combined_coverage:
        if cell["pairs"]:
            radius = math.sqrt(math.log(2 * len(combined_coverage) / .05) / (2 * cell["pairs"]))
            cell["familyCI95"] = [max(0, cell["scoreRate"] - radius), min(1, cell["scoreRate"] + radius)]
    coverage[combined["runId"]] = combined_coverage
    combined["coverage"] = {"cells": len(combined_coverage), "targetSeedPairs": combined["targetSeedPairs"]}
    for record in games + rows:
        if record["runId"] in source_ids:
            record["sourceRunId"] = record["runId"]
            record["runId"] = combined["runId"]
    runs = [combined] + [r for r in runs if r["runId"] not in source_ids]
args.out.mkdir(parents=True, exist_ok=True)
for path in (root / "site").iterdir():
    if path.is_file():
        shutil.copy2(path, args.out / path.name)
payload = {"generatedAt": datetime.now(timezone.utc).isoformat(), "runs": runs,
           "models": MODELS, "rows": rows, "games": games, "coverageByRun": coverage}
(args.out / "data.json").write_text(json.dumps(payload, separators=(",", ":")))
revision = hashlib.sha256((args.out / "data.json").read_bytes() + (args.out / "app.js").read_bytes()).hexdigest()[:16]
index = args.out / "index.html"
index.write_text(index.read_text().replace('src="app.js"', f'src="app.js?v={revision}"'))
(args.out / ".nojekyll").touch()
print(f"Built dashboard: {len(runs)} runs, {len(games)} games")
