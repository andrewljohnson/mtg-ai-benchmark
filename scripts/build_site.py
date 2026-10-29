import argparse
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
args.out.mkdir(parents=True, exist_ok=True)
for path in (root / "site").iterdir():
    if path.is_file():
        shutil.copy2(path, args.out / path.name)
payload = {"generatedAt": datetime.now(timezone.utc).isoformat(), "runs": runs,
           "models": MODELS, "rows": rows, "games": games, "coverageByRun": coverage}
(args.out / "data.json").write_text(json.dumps(payload, separators=(",", ":")))
(args.out / ".nojekyll").touch()
print(f"Built dashboard: {len(runs)} runs, {len(games)} games")
