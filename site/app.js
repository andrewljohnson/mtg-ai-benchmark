const $ = (id) => document.getElementById(id);
const names = {
  luna: "Luna",
  sol: "Sol",
  astra: "Astra",
  terra: "Terra",
  random: "Random",
  handcrafted: "Handcrafted",
};
const labels = {
  "old-school-93-94": "Old School 93/94",
  premodern: "Premodern",
  legacy: "Legacy",
  vintage: "Vintage",
  "isd-m14-standard": "Standard · ISD–M14",
  "woe-hob-standard": "Standard · WOE–HOB",
  cedh: "cEDH",
  "duel-commander": "Duel Commander",
};
const esc = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const percent = (n) => (n == null ? "—" : `${(n * 100).toFixed(1)}%`);
let data,
  page = 0,
  filteredGames = [];
function options(id, values, allLabel) {
  const el = $(id),
    old = el.value;
  el.replaceChildren();
  if (allLabel) el.add(new Option(allLabel, ""));
  for (const [value, text] of values) el.add(new Option(text, value));
  if ([...el.options].some((o) => o.value === old)) el.value = old;
}
function counts(rows) {
  return rows.reduce(
    (a, r) => {
      for (const k of ["wins", "losses", "draws", "errors", "truncated"])
        a[k] += r[k];
      return a;
    },
    { wins: 0, losses: 0, draws: 0, errors: 0, truncated: 0 },
  );
}
function total(c) {
  return c.wins + c.losses + c.draws;
}
function ci(w, n) {
  if (!n) return null;
  const z = 1.959963984540054,
    p = w / n,
    d = 1 + (z * z) / n,
    c = (p + (z * z) / (2 * n)) / d,
    h = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return [Math.max(0, c - h), Math.min(1, c + h)];
}
function selectedRun() {
  return data.runs.find((r) => r.runId === $("run").value);
}
function updateFilters() {
  const run = selectedRun();
  const formats = Object.keys(run?.deckLists ?? {});
  options(
    "format",
    formats.map((f) => [f, labels[f] ?? f]),
  );
  const decks = run?.deckLists[$("format").value] ?? [];
  for (const id of ["deck", "opponent-deck"])
    options(
      id,
      decks.map((d) => [d, d]),
      "Every deck",
    );
  options(
    "deck-agent",
    (run?.agents ?? []).map((a) => [a, names[a] ?? a]),
  );
}
function selectedRows() {
  return data.rows.filter(
    (r) =>
      r.runId === $("run").value &&
      r.format === $("format").value &&
      (!$("deck").value || r.deck === $("deck").value) &&
      (!$("opponent-deck").value ||
        r.opponentDeck === $("opponent-deck").value) &&
      (!$("seat").value || r.seat === $("seat").value),
  );
}
function heat(c) {
  const n = total(c),
    rate = n ? c.wins / n : null;
  return `<td class="heat-cell" style="background:${n ? `rgba(162,207,108,${0.04 + 0.28 * rate})` : "#151b17"}" title="${c.wins} wins, ${c.losses} losses, ${c.draws} draws, ${c.errors + c.truncated} unfinished">${percent(rate)}<small>${n ? `${n} games` : "No completed games"}</small></td>`;
}
function matrix(rowNames, columnNames, match) {
  return `<table class="matrix"><thead><tr><th>PILOT / OPPONENT →</th>${columnNames.map((n) => `<th>${esc(names[n] ?? n)}</th>`).join("")}</tr></thead><tbody>${rowNames.map((a) => `<tr><th scope="row">${esc(names[a] ?? a)}</th>${columnNames.map((b) => heat(counts(match(a, b)))).join("")}</tr>`).join("")}</tbody></table>`;
}
function render() {
  const run = selectedRun(),
    rows = selectedRows(),
    agents = run?.agents ?? [];
  const grouped = agents
    .map((a) => ({ agent: a, ...counts(rows.filter((r) => r.agent === a)) }))
    .sort((a, b) => {
      const ar = total(a) ? a.wins / total(a) : -1,
        br = total(b) ? b.wins / total(b) : -1;
      return br - ar;
    });
  $("standings").innerHTML =
    grouped
      .map((c, i) => {
        const n = total(c),
          rate = n ? c.wins / n : null,
          range = ci(c.wins, n),
          model = run?.models?.[c.agent] ?? data.models[c.agent];
        return `<tr><td><span class="rank">${String(i + 1).padStart(2, "0")}</span><span class="pilot-name">${esc(names[c.agent] ?? c.agent)}</span><div class="pilot-meta">${esc(model ? `${model.model} · ${model.effort} effort` : c.agent === "random" ? "Uniform legal-action policy" : "Penta native rules-based policy")}</div></td><td><span class="rate">${percent(rate)}</span>${n ? `<span class="bar"><i style="width:${rate * 100}%"></i></span>` : ""}</td><td class="quiet">${range ? range.map(percent).join(" – ") : "No completed games"}</td><td>${c.wins} / ${c.losses} / ${c.draws}</td><td>${n}</td><td class="quiet">${c.errors + c.truncated}</td></tr>`;
      })
      .join("") ||
    '<tr><td colspan="6">No games match these filters.</td></tr>';
  $("matrix").innerHTML = matrix(agents, agents, (a, b) =>
    rows.filter((r) => r.agent === a && r.opponent === b),
  );
  const decks = run?.deckLists[$("format").value] ?? [],
    agent = $("deck-agent").value;
  $("deck-matrix").innerHTML = matrix(decks, decks, (a, b) =>
    rows.filter(
      (r) => r.agent === agent && r.deck === a && r.opponentDeck === b,
    ),
  );
  filteredGames = data.games.filter(
    (g) =>
      g.runId === $("run").value &&
      g.format === $("format").value &&
      [0, 1].some(
        (i) =>
          (!$("deck").value || g.decks[i] === $("deck").value) &&
          (!$("opponent-deck").value ||
            g.decks[1 - i] === $("opponent-deck").value) &&
          (!$("seat").value || $("seat").value === (i ? "p2" : "p1")),
      ),
  );
  page = 0;
  renderGames();
  $("manifest").textContent = JSON.stringify(run ?? {}, null, 2);
  const completed = data.games.filter(
      (g) =>
        g.status === "complete" &&
        !data.runs.find((r) => r.runId === g.runId)?.supersededByRunId,
    ),
    tested = new Set(
      completed.flatMap((g) => g.decks.map((d) => g.format + ":" + d)),
    ),
    pilots = new Set(completed.flatMap((g) => g.agents));
  const activeRuns = data.runs.filter((r) => !r.supersededByRunId);
  const completedTotal = activeRuns.reduce(
    (n, r) =>
      n +
      (r.completedGames ?? completed.filter((g) => g.runId === r.runId).length),
    0,
  );
  $("games-stat").textContent = completedTotal.toLocaleString();
  $("decks-stat").textContent = tested.size;
  $("pilots-stat").textContent = pilots.size;
  const selected = data.games.filter((g) => g.runId === run?.runId),
    finished =
      run?.completedGames ??
      selected.filter((g) => g.status === "complete").length;
  $("run-status").textContent = run
    ? `${finished} / ${run.selectedGames} complete${run.state === "running" ? " · snapshot" : ""}`
    : "No runs yet";
  const modelAgents = agents.filter((a) => data.models[a]);
  $("coverage-notice").textContent = !run
    ? "No completed experiments have been published yet."
    : modelAgents.length
      ? `Exploratory model pilot · ${modelAgents.map((a) => names[a]).join(", ")} · ${run.billing}. This sample is too small to rank models. Other model/deck matchups remain untested. ${selected.filter((g) => g.status !== "complete").length} unfinished games are disclosed.`
      : `Baseline calibration · ${Object.values(run.deckLists).reduce((n, d) => n + d.length, 0)} decks selected · random versus Penta's handcrafted policy. Model scores are pending until real games are recorded. ${run.pairs} seed pair${run.pairs === 1 ? "" : "s"} per deck matchup.`;
  const coverage = data.coverageByRun?.[run?.runId] ?? [];
  const evidenceLinks = (run?.sourceRuns ?? (run ? [run] : [])).map((r) => `<a href="https://github.com/andrewljohnson/mtg-ai-benchmark/tree/main/results/${encodeURIComponent(r.resultDirectory)}">${esc(r.agents.includes("sol") ? "Sol worker records" : "Luna and control worker records")} ↗</a>`).join(" · ");
  $("leaderboard").querySelector(".footnote").textContent = coverage.length
    ? "Descriptive pilot-seat standings only: a pilot mirror contributes both a win and a loss (or two draws). Global totals count each physical game once. Use Coverage & confidence for independent paired samples and adjusted inference."
    : "Standings reflect the selected experiment and its opponent mix. Small pilots are exploratory; rates are not evidence of model superiority.";
  if (coverage.length) {
    const covered = coverage.filter((c) => c.pairs > 0).length;
    const ready = coverage.filter((c) => c.inferenceReady).length;
    $("coverage-summary").textContent =
      `${covered} / ${coverage.length} matchups started · ${ready} at precision target`;
    const filtered = coverage.filter(
      (c) =>
        (!$("deck").value || [c.a[1], c.b[1]].includes($("deck").value)) &&
        (!$("opponent-deck").value ||
          [c.a[1], c.b[1]].includes($("opponent-deck").value)),
    );
    $("coverage-rows").innerHTML = filtered
      .slice(0, 100)
      .map(
        (c) =>
          `<tr><td>${esc(names[c.a[0]])}<div class="quiet">${esc(c.a[1])}</div></td><td>${esc(names[c.b[0]])}<div class="quiet">${esc(c.b[1])}</div></td><td>${c.pairs} / ${run.targetSeedPairs}</td><td>${c.completedGames} / ${run.targetGamesPerCell}</td><td>${percent(c.scoreRate)}</td><td>${c.pairCI95 ? c.pairCI95.map(percent).join(" – ") : "—"}</td><td>${c.familyCI95 ? c.familyCI95.map(percent).join(" – ") : "—"}</td><td>${c.mirrorControl ? "Mirror control" : c.inferenceReady ? "Fixed target reached" : "Exploratory"}</td></tr>`,
      )
      .join("");
    $("coverage-ledger").innerHTML = `Showing ${Math.min(100, filtered.length)} of ${filtered.length} matchups; use deck filters to narrow. ${evidenceLinks}. One benchmark with parallel worker queues; records retain their source and replay journals. Standings count seat appearances; mirrors contribute two appearances per physical game. Family intervals account for all ${coverage.length} matchups.`;
    $("coverage-notice").textContent =
      `Old School campaign · ${run.agents.length} pilots × ${run.decks.length} decks · ${coverage.length} matchup combinations · ${finished.toLocaleString()} / ${run.targetGames.toLocaleString()} games complete · ${ready} / ${coverage.length} matchup targets reached. Evaluation only; no model weights are trained. Subscription-only model pilots; queued as allowance permits.`;
  } else {
    $("coverage-summary").textContent = "Legacy pilot run";
    $("coverage-rows").innerHTML =
      '<tr><td colspan="8">This legacy run predates the full campaign. Select Old School v2 for complete permutation coverage.</td></tr>';
    $("coverage-ledger").textContent = "";
  }
  $("pilot-cards").innerHTML = Object.entries(data.models)
    .map(([a, m]) => {
      const games = (run ? [run] : []).reduce(
        (n, r) =>
          n +
          (r.pilotUniqueGames?.[a] ??
            completed.filter((g) => g.runId === r.runId && g.agents.includes(a))
              .length),
        0,
      );
      return `<article class="pilot-card ${games ? "" : "pending"}"><b>${names[a]}</b><p>${esc(m.model)} · ${m.effort} effort</p><span>${games ? `${games} unique completed games · selected run` : "AWAITING BENCHMARK GAMES"}</span></article>`;
    })
    .join("");
}
function renderGames() {
  const size = 25,
    pages = Math.max(1, Math.ceil(filteredGames.length / size));
  page = Math.max(0, Math.min(page, pages - 1));
  $("game-rows").innerHTML =
    filteredGames
      .slice(page * size, (page + 1) * size)
      .map(
        (g) =>
          `<tr><td class="quiet"><a title="Download the compressed game journal" href="${g.journalArchive ? esc(g.journalArchive) : `https://github.com/andrewljohnson/mtg-ai-benchmark/blob/main/results/${encodeURIComponent(selectedRun().resultDirectory)}/${esc(g.journal)}`}">${esc(g.id.slice(0, 8))} ↗</a></td>${[0, 1].map((i) => `<td>${esc(names[g.agents[i]] ?? g.agents[i])}<div class="quiet" style="font-size:10px;margin-top:5px">${esc(g.decks[i])}</div></td>`).join("")}<td>${g.status === "complete" ? (g.result === "draw" ? "Draw" : `${esc(names[g.agents[g.result === "p1" ? 0 : 1]])} wins`) : esc(g.status)}${g.error ? `<div class="quiet" style="font-size:10px;margin-top:5px">${esc(g.error)}</div>` : ""}</td><td>${g.seed}</td><td>${g.modelCalls ?? 0}</td></tr>`,
      )
      .join("") || '<tr><td colspan="6">No recorded games.</td></tr>';
  $("page-label").textContent =
    `${filteredGames.length} games · page ${page + 1} of ${pages}`;
  $("prev").disabled = page === 0;
  $("next").disabled = page === pages - 1;
}
for (const id of ["run", "format"])
  $(id).addEventListener("change", () => {
    updateFilters();
    render();
  });
for (const id of ["deck", "opponent-deck", "seat", "deck-agent"])
  $(id).addEventListener("change", render);
$("reset").onclick = () => {
  for (const id of ["deck", "opponent-deck", "seat"]) $(id).value = "";
  render();
};
const tabButtons = [...document.querySelectorAll("[role=tab]")];
function activate(button) {
  for (const tab of tabButtons) {
    const active = tab === button;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    $(tab.getAttribute("aria-controls")).hidden = !active;
  }
}
for (const [i, button] of tabButtons.entries()) {
  button.tabIndex = i ? -1 : 0;
  button.onclick = () => activate(button);
  button.onkeydown = (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? tabButtons.length - 1
          : (i + (event.key === "ArrowRight" ? 1 : -1) + tabButtons.length) %
            tabButtons.length;
    activate(tabButtons[next]);
    tabButtons[next].focus();
  };
}
$("prev").onclick = () => {
  page--;
  renderGames();
};
$("next").onclick = () => {
  page++;
  renderGames();
};
$("download").onclick = () => {
  const blob = new Blob([JSON.stringify(filteredGames, null, 2)], {
      type: "application/json",
    }),
    url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = "mtg-ai-benchmark-games.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
try {
  const response = await fetch(`data.json${new URL(import.meta.url).search}`, { cache: "no-store" });
  if (!response.ok) throw Error(`Result data unavailable (${response.status})`);
  data = await response.json();
  options(
    "run",
    data.runs.map((r) => [
      r.runId,
      `${r.runId === "old-school-benchmark" ? "MTG AI Benchmark · Random, Handcrafted, Luna & Sol" : r.agents.map((a) => names[a] ?? a).join(" vs ") + " · " + r.runId}${r.supersededByRunId ? " · archived" : ""}`,
    ]),
  );
  updateFilters();
  render();
} catch (error) {
  $("error").hidden = false;
  $("error").textContent =
    `Could not load benchmark data. ${error.message}. Serve this dashboard over HTTP or use the published website.`;
}
