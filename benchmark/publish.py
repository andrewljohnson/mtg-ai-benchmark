"""Archive full campaign journals and publish a bounded public progress snapshot."""
import argparse
import fcntl
import hashlib
import json
import subprocess
import sys
import time
import os
import tarfile
from pathlib import Path

from .campaign import ROOT, connect, export_locked, initialize, now
from .core import digest
from .pilots import atomic_json

REPO = "andrewljohnson/mtg-ai-benchmark"
TAG = "old-school-v2-journals"


def gh(*args, check=True):
    return subprocess.run(["gh", *args], cwd=ROOT, text=True, capture_output=True, check=check)


def publish(directory):
    with (directory / "publish.lock").open("w") as lock, (directory / "export.lock").open("w") as export_lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        fcntl.flock(export_lock, fcntl.LOCK_EX)
        branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
        if branch != "main":
            raise RuntimeError("Automatic publication requires the main branch")
        plan = initialize(directory)
        db = connect(directory)
        records = [json.loads(r[0]) for r in db.execute("SELECT record FROM games")]
        pending = [r for r in records if r["status"] == "complete" and not r.get("journalArchive")]
        snapshot = digest(sorted((r["id"], r["status"], r.get("result"), r.get("decisions"), r.get("modelCalls"), r.get("journalSHA256")) for r in records))
        previous = directory / "last-publication.json"
        if previous.exists() and json.loads(previous.read_text()).get("snapshot") == snapshot and not pending:
            return
        if pending:
            release = gh("release", "view", TAG, "--repo", REPO, "--json", "assets", check=False)
            if release.returncode:
                notes = directory / "release-notes.txt"
                notes.write_text("Full replayable journals for the Old School v2 evaluation campaign. Every archive is content-addressed; per-game and archive SHA-256 values are recorded in the public batch ledgers. No model credentials or account telemetry are included.\n")
                gh("release", "create", TAG, "--repo", REPO, "--title", "Old School v2 game journals",
                   "--notes-file", str(notes), "--target", "main")
                release = gh("release", "view", TAG, "--repo", REPO, "--json", "assets")
            existing = {a["name"] for a in json.loads(release.stdout)["assets"]}
            for offset in range(0, len(pending), 100):
                batch = sorted(pending[offset:offset + 100], key=lambda r: r["id"])
                identity = hashlib.sha256(json.dumps([(r["id"], r["journalSHA256"]) for r in batch]).encode()).hexdigest()
                name = f"journals-{identity[:20]}.tar.gz"
                archive = directory / "archives" / name
                archive.parent.mkdir(exist_ok=True)
                if not archive.exists():
                    with tarfile.open(archive, "w:gz") as output:
                        for record in batch:
                            output.add(directory / record["journal"], arcname=record["journal"])
                checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
                if name not in existing:
                    gh("release", "upload", TAG, str(archive), "--repo", REPO)
                for record in batch:
                    record.update({"journalArchive": f"https://github.com/{REPO}/releases/download/{TAG}/{name}",
                                   "journalArchiveSHA256": checksum})
                    db.execute("UPDATE games SET record=? WHERE id=?", (json.dumps(record), record["id"]))
                db.commit()
        _, records = export_locked(directory, plan, db, published_only=True)
        snapshot = digest(sorted((r["id"], r["status"], r.get("result"), r.get("decisions"), r.get("modelCalls"), r.get("journalSHA256")) for r in records))
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "scripts/build_site.py"], cwd=ROOT, check=True)
        subprocess.run(["git", "add", "--", f"results/{plan['id']}"], cwd=ROOT, check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
            return
        staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=ROOT, text=True).splitlines()
        if any(not p.startswith(f"results/{plan['id']}/") for p in staged):
            raise RuntimeError("Unrelated staged changes; refusing an automatic publication commit")
        subprocess.run(["git", "commit", "-q", "-m", "Update Old School campaign coverage and game evidence"], cwd=ROOT, check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, check=True)
        atomic_json(directory / "last-publication.json", {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                    "snapshot": snapshot, "completedGames": sum(r["status"] == "complete" for r in records),
                    "modelGames": sum(r["status"] == "complete" and "luna" in r["agents"] for r in records), "publishedAt": now()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / ".campaign")
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    if not args.watch:
        publish(args.directory)
        return
    with (args.directory / "publisher-watch.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Publisher watcher already running")
        atomic_json(args.directory / "publisher-state.json", {"pid": os.getpid(), "startedAt": now()})
        last = time.monotonic()
        while True:
            db = connect(args.directory)
            records = [json.loads(r[0]) for r in db.execute("SELECT record FROM games")]
            db.close()
            published = args.directory / "last-publication.json"
            previous = json.loads(published.read_text()) if published.exists() else {}
            completed = sum(r["status"] == "complete" for r in records)
            model = sum(r["status"] == "complete" and "luna" in r["agents"] for r in records)
            delta = completed - previous.get("completedGames", 0)
            if delta > 0 and (delta >= 50 or model > previous.get("modelGames", 0) or time.monotonic() - last >= 900):
                try:
                    publish(args.directory)
                    last = time.monotonic()
                except Exception as error:
                    atomic_json(args.directory / "publisher-error.json", {"at": now(), "error": str(error)})
                    print("Publication deferred; see private publisher-error.json", flush=True)
            time.sleep(15)


if __name__ == "__main__":
    main()
