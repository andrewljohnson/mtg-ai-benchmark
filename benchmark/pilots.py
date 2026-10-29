from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from .core import PROMPT, validate_choice


class BudgetStop(Exception):
    pass


class CallBudget:
    def __init__(self, limit):
        self.limit = limit
        self.calls = 0
        self.usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}

    def reserve(self):
        if self.calls >= self.limit:
            raise BudgetStop("Model call limit reached")
        self.calls += 1


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    temporary.replace(path)


class FilePilot:
    def __init__(self, directory, budget, timeout=300):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.budget = budget
        self.timeout = timeout

    def choose(self, view, agent):
        self.budget.reserve()
        request_id = self.budget.calls
        action_path = self.directory / "action.json"
        action_path.unlink(missing_ok=True)
        atomic_json(self.directory / "observation.json", {
            "requestId": request_id, "agent": agent,
            "instructions": PROMPT, "view": view,
        })
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if action_path.exists():
                try:
                    answer = json.loads(action_path.read_text())
                except json.JSONDecodeError:
                    time.sleep(.05)
                    continue
                if answer.get("requestId") == request_id:
                    return validate_choice(answer.get("index"), view["observation"]), {"backend": "file-pilot", "usage": None}
            time.sleep(.1)
        raise TimeoutError("Pilot did not answer before the decision deadline")


class CodexPilot:
    def __init__(self, budget, timeout=180):
        self.budget = budget
        self.timeout = timeout

    def choose(self, view, agent):
        self.budget.reserve()
        with tempfile.TemporaryDirectory(prefix="mtg-pilot-") as directory:
            schema = Path(directory) / "answer-schema.json"
            schema.write_text(json.dumps({"type": "object", "properties": {"index": {"type": "integer"}},
                                          "required": ["index"], "additionalProperties": False}))
            env = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "OPENAI_BASE_URL"}}
            result = subprocess.run([
                "codex", "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                "--sandbox", "read-only", "--json", "--model", agent["model"],
                "-c", 'features.shell_tool=false', "-c", 'web_search="disabled"',
                "-c", f'model_reasoning_effort="{agent["effort"]}"',
                "--output-schema", str(schema), "-"],
                input=PROMPT + "\n" + json.dumps(view), text=True, capture_output=True,
                cwd=directory, env=env, timeout=self.timeout)
        if result.returncode:
            raise RuntimeError("Codex model call failed; verify subscription model availability")
        message = None
        usage = None
        for line in result.stdout.splitlines():
            event = json.loads(line)
            if event["type"] == "item.completed":
                item = event["item"]
                if item["type"] == "agent_message":
                    message = item["text"]
                elif item["type"] not in {"reasoning"}:
                    raise RuntimeError("Unexpected pilot tool or error event")
            if event["type"] == "turn.completed":
                usage = event.get("usage")
            if event["type"] in {"error", "turn.failed"}:
                raise RuntimeError("Codex model call failed")
        if message is None or usage is None:
            raise RuntimeError("Missing final pilot response or usage receipt")
        for key in self.budget.usage:
            self.budget.usage[key] += usage.get(key, 0)
        return validate_choice(json.loads(message).get("index"), view["observation"]), {
            "backend": "codex-subscription", "configuredModel": agent["model"], "usage": usage}
