"""Build the pinned upstream engine without copying its source into this repository."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark.core import ENGINE_COMMIT

root = Path(__file__).resolve().parents[1]
engine = root / ".engine"
source = engine / "source"
engine.mkdir(exist_ok=True)
if not source.exists():
    subprocess.run(["git", "clone", "https://github.com/lacker/penta.git", str(source)], check=True)
subprocess.run(["git", "checkout", "--detach", ENGINE_COMMIT], cwd=source, check=True)
subprocess.run(["cargo", "build", "--release", "--locked"], cwd=source / "bindings/penta-py",
               env={**os.environ, "PYO3_PYTHON": sys.executable}, check=True)
library = "libpenta.dylib" if sys.platform == "darwin" else "libpenta.so"
shutil.copy2(source / "bindings/penta-py/target/release" / library, engine / "penta.so")
sys.path.insert(0, str(engine))
import penta

(engine / "provenance.json").write_text(json.dumps({
    "upstream": "https://github.com/lacker/penta", "commit": ENGINE_COMMIT,
    "fingerprint": penta.simulation_fingerprint(), "protocol": penta.protocol_version(),
    "version": penta.engine_version()}, indent=2) + "\n")
print("Pinned Penta engine ready")
