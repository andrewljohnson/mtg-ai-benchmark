# MTG AI Benchmark

An open benchmark of AI pilots playing **Magic: The Gathering** in [Penta](https://github.com/lacker/penta).

**[Explore the dashboard](https://andrewljohnson.github.io/mtg-ai-benchmark/)** · [Match records](results/) · [Methodology](#methodology)

The question: how well do Luna, Sol, Astra, and other models pilot each deck, against random, a handcrafted policy, and each other? This repository contains the runner, real game records, replay verifier, and public dashboard. Missing results remain missing: no synthetic scores or estimated wins.

## Current scope

Initial release: a complete Old School baseline matrix across all 15 built-in decks, plus a subscription-based Luna pilot: one completed win against random and one game truncated by the 120-decision cap. These are calibration and feasibility results, **not a completed model leaderboard**. Sol, Astra, Terra, additional decks, and direct model-versus-model results are pending actual runs.

The harness discovers all built-in decks in each selected format. `--format all` selects every constructed/Commander profile with registered built-in decks at the pinned commit; profiles with no built-in decks and fixed-list cubes are excluded. Initial published games are Old School only.

## Quick start

Requires **Python 3.13+**, Git, and Rust/rustup. Penta's pinned Rust toolchain is installed by rustup when building. The benchmark itself uses only Python's standard library; no API key or Python dependency install is needed.

```sh
git clone https://github.com/andrewljohnson/mtg-ai-benchmark.git
cd mtg-ai-benchmark
python3 scripts/setup_engine.py
python3 -m unittest discover -s tests -v
```

The setup script builds a separate, unmodified checkout of Penta at commit `581e7ce37cc1113b0cec4873da4e089b0b8ccd6d` under ignored `.engine/`. It records the simulation fingerprint, protocol epoch, and engine version. Engine source and binaries are not committed here.

### Free baseline calibration

```sh
# Every ordered deck pairing; same seeds in both starting seats.
python3 -m benchmark.run --agents random,handcrafted --pairs 2 \
  --out results/my-baseline

# Small smoke run: two decks, eight games, no model calls.
python3 -m benchmark.run --agents random,handcrafted \
  --decks '["Sligh", "White Weenie"]' --pairs 1 \
  --out results/my-smoke
```

Output directories are immutable: choose a fresh directory for each experiment. Each run records its full plan, limits, and actual games. A complete two-pilot run has `decks² × seed_pairs × 2` games. With more pilots, multiply by the number of distinct unordered pilot pairs. Same-pilot mirrors are not scheduled.

### Models using a ChatGPT subscription

Sign into a current Codex CLI with `codex login`, then verify `codex login status` says **ChatGPT**, not API-key authentication. Model access depends on the account and client; a model rejection is an error, never an invitation to substitute another model.

```sh
# Two-game Luna feasibility pilot; the call cap stops further model decisions.
python3 -m benchmark.run --agents luna,random \
  --decks '["Sligh"]' --max-games 2 --max-model-calls 120 \
  --out results/my-luna-pilot

# Full selected-deck round robin, including both baselines and model head-to-head.
# This is intentionally NOT run automatically: begin with a small pilot.
python3 -m benchmark.run --agents luna,sol,astra,random,handcrafted \
  --decks '["Sligh", "White Weenie"]' --pairs 5 --max-model-calls 1000 \
  --out results/my-round-robin
```

Configured defaults are `gpt-6-luna`, `gpt-6.1-sol`, `gpt-6-astra`, and `gpt-6.1-terra`, all at low reasoning effort. Use `--effort medium` (or `high`, `xhigh`, `max`) to compare reasoning settings in a separate run. See `benchmark/core.py` for model IDs. Retain the resulting run manifest.

The Codex adapter uses an ephemeral read-only session per nonforced decision, disables shell and web search, ignores user configuration, removes API-key environment variables, validates the structured answer against legal indices, and records usage receipts. It does not call the OpenAI API. Subscription allowance may still be consumed; a call cap is not a dollar or token cap. Do not enable credit overage to run an unattended benchmark.

**Initial host limitation:** Codex CLI 0.144.4 rejected `gpt-6-luna` with ChatGPT authentication. The published Luna pilot therefore uses the desktop's native model agent and the file adapter below. Native pilots and stateless CLI pilots are different conditions. Native model selection is configured by the host; we do not claim an independently attested provider model response ID or per-turn token receipt for that pilot.

### File adapter for native pilots

The engine lives in the harness process; a pilot receives only a seat-visible JSON request and returns one legal index. This supports subscription-native agents without exporting credentials or needing API access.

```sh
# Organizer terminal
python3 -m benchmark.run --agents luna,random --decks '["Sligh"]' \
  --pilot file --session .sessions/luna --max-model-calls 120 \
  --out results/my-native-luna

# Pilot terminal: observe; then submit the chosen index for that request.
python3 scripts/pilot_client.py .sessions/luna
python3 scripts/pilot_client.py .sessions/luna --request 1 --index 0
```

The submitted `--index` above is only an example: the pilot must choose from the current request's legal actions. Stale request IDs do not advance the game. A 300-second decision timeout is recorded as an error. The client omits bulky card printing/structure metadata when presenting the catalog reference. Each nonforced move must be chosen by the model, with no scripted fallback. `done:true` ends the pilot.

The file adapter assumes a cooperative pilot. Same-user agents can access local files; this is a hidden-information protocol, **not an OS security boundary**. Native agents must not inspect seeds, journals, source, or game internals. Model-call counts in this mode count requested decisions; token totals are unavailable unless independently supplied.

### Build and inspect the site

```sh
python3 scripts/build_site.py
python3 -m http.server 8000 --directory dist
```

Open `http://localhost:8000`. The static dashboard includes experiment, format, deck, opponent-deck and seat filters; standings with uncertainty; pilot and deck matchup matrices; a paginated ledger; filtered JSON download; and run manifests. It never pools separate runs. Site data is a **published snapshot**, regenerated on each push, not a live query to ongoing matches.

The GitHub Actions workflow runs the unit tests and publishes `dist/` through GitHub Pages. It never runs models or spends allowance in CI. Pull requests test and build without deployment.

### Replay a game

```sh
python3 scripts/replay.py results/my-baseline GAME_ID_FROM_GAMES_JSONL
```

The verifier requires the original simulation fingerprint, replays every external action, checks every recorded observation, and verifies the final result. Native handcrafted actions are regenerated deterministically by Penta. Journals contain full redacted observations for the external seats, not an omniscient engine dump. Replaying a logged game is deterministic; asking a generative model to play again need not produce the same actions.

## Methodology

- **Unit:** one completed Penta game (`one-conclusion`), not a best-of-three match; no sideboarding. Penta p1 begins on the play.
- **Pairing:** every distinct pilot pair, every ordered deck assignment, and both starting seats for each selected seed. Pilots keep their decks when swapping seats. Every matchup reuses the same replicate seeds for comparability.
- **Information:** `observe(seat)` only. The prompt includes the complete legal-action list and catalog entries for visible card definitions. The reconstruction checkpoint is omitted from model prompts. No seed, opposing hidden hand, or library order is supplied. There is no open-decklist disclosure in these experiments.
- **Baselines:** `handcrafted` is Penta's native policy; `random` is uniform selection over legal action indices with Python's seeded RNG. Native built-in policy RNG algorithms differ; the initial file pilot used Penta's native random opponent and records that exception. Baseline experiments and model pilots remain separate.
- **Forced actions:** exactly one legal move advances without a model call. No other moves are supplied by heuristics. Automatic native opponents run inside Penta.
- **Failures:** invalid/malformed replies, model-access failures and timeouts are errors, not losses. The external action cap or model-call cap produces an unfinished/truncated game, not a draw. Three game errors stop a run. Report completion rate alongside win rate; failing games can bias completed-only scores.
- **Scoring:** strict win rate is `wins / (wins + losses + draws)`. The data also contains score rate `(wins + 0.5 × draws) / completed`. Wilson 95% intervals are descriptive and do not correct for seed pairing or correlated games; do not use them as a significance test. Balanced, much larger held-out samples are needed to compare models.
- **Provenance:** pin engine commit/fingerprint, format, decks, seeds, pilot config, prompt hash, backend, harness/runtime versions, caps, actions, results, and available usage. Requested model/effort and observed provider identity are distinct evidence. Exact fingerprint replay may require the same build environment.
- **Coverage:** Penta is an evolving simulator, not the full Magic Comprehensive Rules. See upstream [format coverage](https://github.com/lacker/penta/blob/main/docs/formats.md). Engines, prompts, backends, reasoning settings, and format changes define separate experiments.

## Data layout

```text
results/<experiment>/run.json                 full configuration and provenance
results/<experiment>/games.jsonl              one authoritative record per game
results/<experiment>/journals/<id>.jsonl.gz    redacted observations and action indices
site/                                        static dashboard source
benchmark/                                   scheduler, policies, runner and aggregation
scripts/                                     engine setup, replay, file client and site build
```

## Next experiments

1. Finish and audit the low-cost Luna feasibility pilot, monitoring subscription usage.
2. Expand Luna versus random and handcrafted across every Old School deck with balanced seats.
3. Add Sol on the identical plan, then direct Luna-versus-Sol games.
4. Add Astra/Terra only after inspecting allowance and per-game demand.
5. Expand to other Penta formats and more held-out seeds; publish complete coverage and failure rates.

Contributions should include reproducible run manifests and raw game records. No automatic model substitutions or fabricated placeholder results. Keep account credentials and private host telemetry out of commits.

## License and attribution

Benchmark code is [MIT licensed](LICENSE). Penta is a separate [Apache-2.0 licensed project](https://github.com/lacker/penta/blob/main/LICENSE) by lacker and contributors. Card names, rules text, and Magic: The Gathering are owned by their respective rights holders; this repository's license does not relicense those materials. This is an independent fan/research project, unaffiliated with Wizards of the Coast or OpenAI.
