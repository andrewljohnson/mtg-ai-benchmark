"""Create the independently versioned Sol extension to the Old School campaign."""
from .campaign import ROOT, cells, connect, export, initialize, now
from .core import MODELS
from .pilots import atomic_json


def main():
    directory = ROOT / ".campaign-sol"
    if not (directory / "plan.json").exists():
        base = initialize(ROOT / ".campaign")
        agents = ["random", "handcrafted", "luna", "sol"]
        selected = [c for c in cells(agents, base["decks"]) if "sol" in [c["a"][0], c["b"][0]]]
        plan = {**base, "id": "old-school-sol-v1", "createdAt": now(), "agents": agents,
                "cells": selected, "models": {a: MODELS[a] for a in ["luna", "sol"]},
                "targetGames": len(selected) * base["targetGamesPerCell"],
                "contextPolicy": "Fresh native model context per game and separate context per seat; no cross-seat observations",
                "nativeModelRole": "luna",
                "nativeModelRoleExplanation": "The pinned native bridge names its external decision channel luna. This is a transport role, not the model identity. Game agents, models and model receipts identify the actual pilot; nativeAgents preserves exact replay routing.",
                "scope": "All matchups involving Sol; existing random, handcrafted and Luna-only cells remain in old-school-v2"}
        atomic_json(directory / "plan.json", plan)
    plan = initialize(directory)
    export(directory, plan, connect(directory))
    print(f"{plan['id']}: {len(plan['cells'])} matchup cells")


if __name__ == "__main__":
    main()
