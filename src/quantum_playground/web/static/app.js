/* Quantum Playground Studio — single-page front-end (no external dependencies). */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { info: null, experiments: [], currentExp: null };

async function api(method, path, body) {
  const opts = { method, headers: { "X-QPlay": "1" } };
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (_) { data = { error: res.statusText }; }
  if (!res.ok) { const err = new Error(data.error || res.statusText); err.data = data; err.status = res.status; throw err; }
  return data;
}

function toast(msg, ms = 3500) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), ms);
}

function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

function fmt(v) {
  if (typeof v === "number") {
    if (!isFinite(v)) return String(v);
    if (Number.isInteger(v)) return String(v);
    if (v !== 0 && (Math.abs(v) < 1e-3 || Math.abs(v) >= 1e6)) return v.toExponential(3);
    return v.toFixed(4);
  }
  if (Array.isArray(v)) return v.map(fmt).join(", ");
  if (v && typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/* ------------------------------------------------------------------ theme & tabs */
(function theme() {
  let t = null;
  try { t = localStorage.getItem("qplay-theme"); } catch (_) {}
  if (t) document.documentElement.dataset.theme = t;
  $("#themeToggle").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme;
    const dark = cur ? cur === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("qplay-theme", next); } catch (_) {}
  });
})();

$$("#tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
function showTab(name) {
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + name));
  if (name === "jobs") loadJobs();
  if (name === "settings") loadIbmStatus();
  if (name === "tutor") loadTutor();
  try { history.replaceState(null, "", "#" + name); } catch (_) {}
}

/* ------------------------------------------------------------------ charts (SVG) */
const SERIES_COLORS = ["var(--s1)", "var(--s2)", "var(--s3)"];
function chartSVG(chart) {
  const labels = chart.labels || [];
  const names = Object.keys(chart.series || {});
  if (!labels.length || !names.length) return "";
  const W = 640, H = 230, L = 46, R = 10, T = 10, B = labels.length > 12 ? 62 : 34;
  const all = names.flatMap((n) => chart.series[n]).filter((v) => isFinite(v));
  let lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  if (hi - lo < 1e-12) hi = lo + 1;
  const pad = (hi - lo) * 0.06; hi += pad; if (lo < 0) lo -= pad;
  const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const iw = (W - L - R) / labels.length;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(chart.title)}">`;
  for (let k = 0; k <= 4; k++) {
    const v = lo + (hi - lo) * k / 4, yy = y(v);
    s += `<line x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}" stroke="var(--line)"/>`;
    s += `<text x="${L - 6}" y="${yy + 4}" text-anchor="end" font-size="10" fill="var(--muted)">${esc(fmtAxis(v))}</text>`;
  }
  if (lo < 0) s += `<line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="var(--muted)"/>`;
  if (chart.kind === "line") {
    names.forEach((n, si) => {
      const pts = chart.series[n].map((v, i) => `${L + iw * (i + 0.5)},${y(v)}`).join(" ");
      s += `<polyline fill="none" stroke="${SERIES_COLORS[si % 3]}" stroke-width="2" points="${pts}"/>`;
      chart.series[n].forEach((v, i) => { s += `<circle cx="${L + iw * (i + 0.5)}" cy="${y(v)}" r="2.8" fill="${SERIES_COLORS[si % 3]}"><title>${esc(labels[i])}: ${esc(fmt(v))}</title></circle>`; });
    });
  } else {
    const bw = Math.max(1, (iw * 0.8) / names.length);
    names.forEach((n, si) => {
      chart.series[n].forEach((v, i) => {
        const x = L + iw * i + iw * 0.1 + si * bw, y0 = y(Math.max(0, v)), h = Math.abs(y(v) - y(0));
        s += `<rect x="${x}" y="${y0}" width="${bw - 1}" height="${Math.max(0.5, h)}" fill="${SERIES_COLORS[si % 3]}" rx="2"><title>${esc(labels[i])} ${esc(n)}: ${esc(fmt(v))}</title></rect>`;
      });
    });
  }
  const step = Math.ceil(labels.length / 40);
  labels.forEach((lab, i) => {
    if (i % step) return;
    const x = L + iw * (i + 0.5), yy = H - B + 14;
    s += labels.length > 12
      ? `<text transform="translate(${x},${yy}) rotate(-60)" text-anchor="end" font-size="10" fill="var(--muted)" font-family="ui-monospace,monospace">${esc(lab)}</text>`
      : `<text x="${x}" y="${yy}" text-anchor="middle" font-size="11" fill="var(--muted)" font-family="ui-monospace,monospace">${esc(lab)}</text>`;
  });
  s += "</svg>";
  const legend = names.length > 1 ? `<div class="legend">${names.map((n, i) => `<span><i style="background:${SERIES_COLORS[i % 3]}"></i>${esc(n)}</span>`).join("")}</div>` : "";
  return `<div class="chart-title">${esc(chart.title)}</div>${legend}<div class="chart">${s}</div>`;
}
function fmtAxis(v) { return Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? v.toFixed(2) : v.toFixed(2); }

/* ------------------------------------------------------------------ report rendering */
function renderReport(out) {
  const r = out.report;
  if (!r) {
    return `<div class="card report"><h2>${esc(out.experiment || "Job")} <span class="badge ${esc(out.status)}">${esc(out.status)}</span></h2>
      <p>${esc(out.message || "Waiting for results.")}</p><p class="muted small">Job ID <code>${esc(out.job_id)}</code> on ${esc(out.backend)}</p></div>`;
  }
  let h = `<div class="card report"><h2>${esc(r.title)} ${r.verdict ? `<span class="badge ${esc(r.verdict)}">${esc(r.verdict)}</span>` : ""}</h2>`;
  h += `<p class="muted small">Job <code>${esc(out.job_id)}</code> · backend <b>${esc(out.backend)}</b></p>`;
  if (r.summary?.length) h += `<ul class="summary">${r.summary.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>`;
  const m = r.metrics || {};
  if (Object.keys(m).length) h += `<div class="metrics">${Object.entries(m).map(([k, v]) => `<div class="metric"><span>${esc(k)}</span>${esc(fmt(v))}</div>`).join("")}</div>`;
  (r.charts || []).forEach((c) => { h += chartSVG(c); });
  (r.tables || []).forEach((t) => { h += tableHTML(t.title, t.columns, t.rows); });
  (r.notes || []).forEach((n) => { h += `<p class="muted small">ⓘ ${esc(n)}</p>`; });
  if (out.preflight && out.preflight.circuits?.length && out.preflight.circuits[0].best_seed !== undefined) h += preflightHTML(out.preflight, true);
  return h + "</div>";
}
function tableHTML(title, cols, rows) {
  return `<div class="chart-title">${esc(title)}</div><div class="scroll"><table class="tbl"><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>${rows.map((r) => `<tr>${r.map((c) => `<td>${esc(fmt(c))}</td>`).join("")}</tr>`).join("")}</table></div>`;
}
function preflightHTML(p, compact = false) {
  const rows = p.circuits.map((c) => [c.name || "", c.depth, c.two_qubit, c.multi_qubit, c.size, c.best_seed ?? "-", c.error_estimate == null ? "-" : Number(c.error_estimate).toExponential(2)]);
  let h = compact ? `<details><summary>Transpilation preflight (${esc(p.backend)})</summary>` : `<div class="card"><h2>Preflight — ${esc(p.backend)} ${p.blocked ? '<span class="badge fail">blocked</span>' : '<span class="badge pass">ok</span>'}</h2>`;
  h += tableHTML("Per circuit", ["circuit", "depth", "2q", "multi-q", "size", "seed", "error product"], rows);
  (p.warnings || []).forEach((w) => { h += `<p class="small" style="color:var(--warn)">⚠ ${esc(w)}</p>`; });
  (p.reasons || []).forEach((w) => { h += `<p class="small err">⛔ ${esc(w)}</p>`; });
  if (p.settings && Object.keys(p.settings).length) h += `<p class="muted small">${esc(JSON.stringify(p.settings))}</p>`;
  return h + (compact ? "</details>" : "</div>");
}

/* ------------------------------------------------------------------ overview */
async function loadInfo() {
  state.info = await api("GET", "/api/info");
  $("#version").textContent = "v" + state.info.version;
  const avail = state.info.backends.filter((b) => b.available).length;
  $("#stats").innerHTML = [
    ["Experiments", state.info.experiments], ["Backends ready", `${avail}/${state.info.backends.length}`],
    ["IBM credentials", state.info.has_ibm_token ? esc(state.info.ibm.source) : "saved account or none"],
  ].map(([k, v]) => `<div class="stat"><span class="muted small">${k}</span><b>${v}</b></div>`).join("");
  $("#backendTable").innerHTML = "<tr><th>spec</th><th>description</th><th>status</th></tr>" + state.info.backends.map((b) =>
    `<tr><td><code>${esc(b.spec)}</code></td><td>${esc(b.label)}</td><td><span class="dot ${b.available ? "on" : "off"}"></span>${b.available ? (b.remote ? "cloud" : "ready") : "SDK missing"}</td></tr>`).join("");
  $$(".backend-select").forEach((sel) => {
    sel.innerHTML = state.info.backends.map((b) => `<option value="${esc(b.spec)}" ${b.available ? "" : "disabled"}>${esc(b.label)}${b.remote ? " ☁" : ""}</option>`).join("");
  });
}

/* ------------------------------------------------------------------ circuit lab */
const lab = { n: 3, cols: 14, ops: [], sel: "h", pending: null, theta: "pi/2" };
const PALETTE = [
  ["h", "H"], ["x", "X"], ["y", "Y"], ["z", "Z"], ["s", "S"], ["sdg", "S†"], ["t", "T"], ["tdg", "T†"], ["sx", "√X"], "|",
  ["rx", "RX"], ["ry", "RY"], ["rz", "RZ"], ["p", "P"], "|",
  ["cx", "CX"], ["cz", "CZ"], ["swap", "SWAP"], ["ccx", "CCX"], ["cp", "CP"], "|", ["measure", "M"], ["erase", "⌫"],
];
const PARAM_GATES = new Set(["rx", "ry", "rz", "p", "cp"]);
const ARITY = { cx: 2, cz: 2, swap: 2, cp: 2, ccx: 3 };

function parseAngle(text) {
  const m = String(text).trim().match(/^(-)?\s*(\d*\.?\d+)?\s*\*?\s*(pi|π)?\s*(?:\/\s*(\d*\.?\d+))?$/i);
  if (!m || (!m[2] && !m[3])) throw new Error("angle like pi/2, 0.7, -3*pi/4");
  let v = m[2] ? parseFloat(m[2]) : 1;
  if (m[3]) v *= Math.PI;
  if (m[4]) v /= parseFloat(m[4]);
  return m[1] ? -v : v;
}

function buildPalette() {
  const p = $("#palette");
  p.innerHTML = PALETTE.map((g) => g === "|" ? '<span class="sep"></span>' : `<button data-g="${g[0]}" class="${g[0] === lab.sel ? "sel" : ""}">${g[1]}</button>`).join("")
    + `<label>θ <input id="labTheta" value="${esc(lab.theta)}" class="num mono" aria-label="rotation angle"></label>`;
  $$("button", p).forEach((b) => b.addEventListener("click", () => { lab.sel = b.dataset.g; lab.pending = null; buildPalette(); drawComposer(); }));
  $("#labTheta").addEventListener("change", (e) => { lab.theta = e.target.value; });
}

function opQubits(op) { return [...op.controls, ...op.targets]; }
function removeAt(col, qs) {
  const lo = Math.min(...qs), hi = Math.max(...qs);
  lab.ops = lab.ops.filter((op) => op.col !== col || opQubits(op).every((q) => q < lo || q > hi) && !(Math.min(...opQubits(op)) < lo && Math.max(...opQubits(op)) > hi));
}

function clickCell(q, col) {
  const g = lab.sel;
  if (g === "erase") { lab.ops = lab.ops.filter((op) => !(op.col === col && Math.min(...opQubits(op)) <= q && q <= Math.max(...opQubits(op)))); return refreshLab(); }
  let params = [];
  if (PARAM_GATES.has(g)) { try { params = [parseAngle(lab.theta)]; } catch (e) { toast(e.message); return; } }
  if (ARITY[g]) {
    if (!lab.pending || lab.pending.col !== col || lab.pending.gate !== g) lab.pending = { gate: g, col, picked: [] };
    if (lab.pending.picked.includes(q)) return;
    lab.pending.picked.push(q);
    if (lab.pending.picked.length < ARITY[g]) return drawComposer();
    const picked = lab.pending.picked; lab.pending = null;
    removeAt(col, picked);
    if (g === "swap") lab.ops.push({ name: g, controls: [], targets: picked, params, col });
    else lab.ops.push({ name: g, controls: picked.slice(0, -1), targets: picked.slice(-1), params, col });
    return refreshLab();
  }
  removeAt(col, [q]);
  lab.ops.push({ name: g, controls: [], targets: [q], params, col });
  refreshLab();
}

function drawComposer() {
  const el = $("#composer");
  el.style.gridTemplateColumns = `max-content repeat(${lab.cols}, var(--cell, 46px))`;
  const occ = {};
  lab.ops.forEach((op) => {
    const qs = opQubits(op), lo = Math.min(...qs), hi = Math.max(...qs);
    for (let q = lo; q <= hi; q++) occ[`${q}:${op.col}`] = { op, lo, hi };
  });
  let h = "";
  for (let q = 0; q < lab.n; q++) {
    h += `<div class="qlabel">q${q}</div>`;
    for (let c = 0; c < lab.cols; c++) {
      const o = occ[`${q}:${c}`];
      const pend = lab.pending && lab.pending.col === c && lab.pending.picked.includes(q);
      let inner = "";
      if (o) {
        const { op, lo, hi } = o;
        if (hi > lo) {
          const top = q === lo ? "50%" : "0", bot = q === hi ? "50%" : "0";
          inner += `<span class="vline" style="top:${top};bottom:${bot}"></span>`;
        }
        if (op.controls.includes(q)) inner += `<span class="ctrl"></span>`;
        else if (op.targets.includes(q)) {
          if (op.name === "cx" || op.name === "ccx") inner += `<span class="tgt">+</span>`;
          else if (op.name === "cz") inner += `<span class="ctrl"></span>`;
          else if (op.name === "swap") inner += `<span class="tgt">×</span>`;
          else if (op.name === "measure") inner += `<span class="g m">M</span>`;
          else {
            const lab2 = (PALETTE.find((p) => p[0] === op.name) || [0, op.name])[1];
            inner += `<span class="g" title="${esc(op.name)}${op.params.length ? "(" + op.params[0].toFixed(3) + ")" : ""}">${esc(lab2)}</span>`;
          }
        }
      }
      h += `<div class="cell${pend ? " pending" : ""}" data-q="${q}" data-c="${c}">${inner}</div>`;
    }
  }
  el.innerHTML = h;
  $$(".cell", el).forEach((d) => d.addEventListener("click", () => clickCell(+d.dataset.q, +d.dataset.c)));
}

function labCircuit() {
  const ops = [...lab.ops].filter((op) => opQubits(op).every((q) => q < lab.n)).sort((a, b) => a.col - b.col);
  const hasMeasure = ops.some((op) => op.name === "measure");
  const ins = ops.map((op) => op.name === "measure"
    ? { name: "measure", qubits: op.targets, clbits: op.targets }
    : { name: op.name, qubits: [...op.controls, ...op.targets], params: op.params });
  return { format: "qplay-circuit/1", name: "composer", qregs: [{ name: "q", size: lab.n }],
           cregs: hasMeasure ? [{ name: "c", size: lab.n }] : [], instructions: ins };
}

const simulateLab = debounce(async () => {
  try {
    const d = await api("POST", "/api/circuit/simulate", { circuit: labCircuit(), shots: 2000 });
    const probs = d.probabilities || d.exact || {};
    const keys = Object.keys(probs).sort();
    $("#labProbs").innerHTML = chartSVG({ title: "", labels: keys, series: { probability: keys.map((k) => probs[k]) }, kind: "bar" });
    $("#labProfile").textContent = `${d.profile.size} ops · depth ${d.profile.depth}`;
    $("#labBloch").innerHTML = (d.bloch || []).map((b, q) => blochSVG(b, q, (d.entropy || [])[q])).join("") || '<p class="muted small">Not available after mid-circuit measurement.</p>';
    $("#labAmps").innerHTML = d.amplitudes ? ampTable(d.amplitudes) : '<p class="muted small">Amplitude table shown for ≤ 6 qubits.</p>';
    $("#labQasm").textContent = d.qasm3;
    $("#labDraw").textContent = d.drawing;
  } catch (e) { toast(e.message); }
}, 180);

function ampTable(amps) {
  return `<table class="tbl"><tr><th>basis</th><th>amplitude</th><th>P</th><th>phase</th></tr>${amps.map((a) => {
    const hue = ((a.phase + Math.PI) / (2 * Math.PI)) * 360;
    return `<tr><td class="mono">|${esc(a.basis)}⟩</td><td class="mono">${a.re.toFixed(3)}${a.im >= 0 ? "+" : "−"}${Math.abs(a.im).toFixed(3)}i</td>
      <td><div style="background:var(--s1);height:8px;border-radius:4px;width:${Math.round(a.p * 100)}%;min-width:${a.p > 1e-9 ? 2 : 0}px"></div></td>
      <td>${a.p > 1e-9 ? `<span title="${a.phase.toFixed(3)} rad" style="display:inline-block;width:12px;height:12px;border-radius:50%;background:hsl(${hue},70%,55%)"></span>` : ""}</td></tr>`;
  }).join("")}</table>`;
}

function blochSVG(b, q, ent) {
  const [x, y, z, purity] = b, r = 38, cx = 50, cy = 50;
  const px = cx + r * (y * 0.95 - x * 0.45), py = cy - r * z * 0.95 + r * x * 0.3;
  return `<div class="bloch"><svg width="100" height="100" viewBox="0 0 100 100" role="img" aria-label="Bloch sphere q${q}">
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--line)" stroke-width="1.5"/>
    <ellipse cx="${cx}" cy="${cy}" rx="${r}" ry="${r * 0.3}" fill="none" stroke="var(--line)" stroke-dasharray="3 3"/>
    <line x1="${cx}" y1="${cy - r}" x2="${cx}" y2="${cy + r}" stroke="var(--line)"/>
    <text x="${cx}" y="9" text-anchor="middle" font-size="9" fill="var(--muted)">|0⟩</text>
    <text x="${cx}" y="99" text-anchor="middle" font-size="9" fill="var(--muted)">|1⟩</text>
    <line x1="${cx}" y1="${cy}" x2="${px}" y2="${py}" stroke="var(--accent)" stroke-width="2.5"/>
    <circle cx="${px}" cy="${py}" r="3.5" fill="var(--accent)"/></svg>
    <div>q${q} · purity ${purity.toFixed(2)}${ent > 0.01 ? " · S=" + ent.toFixed(2) : ""}</div></div>`;
}

function refreshLab() { drawComposer(); simulateLab(); }

const PRESETS = {
  bell: () => [{ name: "h", controls: [], targets: [0], params: [], col: 0 }, { name: "cx", controls: [0], targets: [1], params: [], col: 1 }],
  ghz: () => [{ name: "h", controls: [], targets: [0], params: [], col: 0 }, ...Array.from({ length: lab.n - 1 }, (_, i) => ({ name: "cx", controls: [i], targets: [i + 1], params: [], col: i + 1 }))],
  grover2: () => [
    ...[0, 1].map((q) => ({ name: "h", controls: [], targets: [q], params: [], col: 0 })),
    { name: "cz", controls: [0], targets: [1], params: [], col: 1 },
    ...[0, 1].map((q) => ({ name: "h", controls: [], targets: [q], params: [], col: 2 })),
    ...[0, 1].map((q) => ({ name: "x", controls: [], targets: [q], params: [], col: 3 })),
    { name: "cz", controls: [0], targets: [1], params: [], col: 4 },
    ...[0, 1].map((q) => ({ name: "x", controls: [], targets: [q], params: [], col: 5 })),
    ...[0, 1].map((q) => ({ name: "h", controls: [], targets: [q], params: [], col: 6 }))],
  qft3: () => [
    { name: "x", controls: [], targets: [0], params: [], col: 0 }, { name: "x", controls: [], targets: [2], params: [], col: 0 },
    { name: "h", controls: [], targets: [2], params: [], col: 1 }, { name: "cp", controls: [1], targets: [2], params: [Math.PI / 2], col: 2 },
    { name: "cp", controls: [0], targets: [2], params: [Math.PI / 4], col: 3 }, { name: "h", controls: [], targets: [1], params: [], col: 4 },
    { name: "cp", controls: [0], targets: [1], params: [Math.PI / 2], col: 5 }, { name: "h", controls: [], targets: [0], params: [], col: 6 },
    { name: "swap", controls: [], targets: [0, 2], params: [], col: 7 }],
  phase: () => [{ name: "x", controls: [], targets: [1], params: [], col: 0 }, { name: "h", controls: [], targets: [0], params: [], col: 1 },
    { name: "cp", controls: [0], targets: [1], params: [Math.PI / 2], col: 2 }, { name: "h", controls: [], targets: [0], params: [], col: 3 }],
  w: () => [...[0, 1, 2].map((q) => ({ name: "h", controls: [], targets: [q], params: [], col: 0 })),
    { name: "t", controls: [], targets: [0], params: [], col: 1 }, { name: "s", controls: [], targets: [1], params: [], col: 1 }],
};

function initLab() {
  buildPalette();
  $("#labQubits").addEventListener("change", (e) => { lab.n = Math.max(1, Math.min(8, +e.target.value || 1)); refreshLab(); });
  $("#labCols").addEventListener("change", (e) => { lab.cols = Math.max(4, Math.min(40, +e.target.value || 14)); refreshLab(); });
  $("#labClear").addEventListener("click", () => { lab.ops = []; lab.pending = null; refreshLab(); });
  $("#labPreset").addEventListener("change", (e) => {
    const p = PRESETS[e.target.value]; if (!p) return;
    if (lab.n < 3 && ["qft3", "w"].includes(e.target.value)) { lab.n = 3; $("#labQubits").value = 3; }
    if (lab.n < 2) { lab.n = 2; $("#labQubits").value = 2; }
    lab.ops = p(); e.target.value = ""; refreshLab();
  });
  $("#labRun").addEventListener("click", async () => {
    const btn = $("#labRun"); btn.disabled = true; $("#labReport").innerHTML = '<p class="muted">Running…</p>';
    try {
      const out = await api("POST", "/api/run", { experiment: "custom", params: { circuit: JSON.stringify(labCircuit()) },
        backend: $("#labBackend").value, shots: +$("#labShots").value, confirm: $("#labConfirm").checked });
      $("#labReport").innerHTML = renderReport(out);
    } catch (e) { $("#labReport").innerHTML = errorHTML(e); } finally { btn.disabled = false; }
  });
  lab.ops = PRESETS.bell();
  refreshLab();
}

function errorHTML(e) {
  if (e.data?.preflight) return preflightHTML(e.data.preflight) + `<p class="err">${esc(e.message)}</p>`;
  return `<p class="err">${esc(e.message)}</p>`;
}

/* ------------------------------------------------------------------ experiments */
async function loadExperiments() {
  const d = await api("GET", "/api/experiments");
  state.experiments = d.experiments;
  let cat = null, h = "";
  d.experiments.filter((e) => e.id !== "custom").forEach((e) => {
    if (e.category !== cat) { cat = e.category; h += `<h4>${esc(cat)}</h4>`; }
    h += `<button data-id="${esc(e.id)}">${esc(e.title)}</button>`;
  });
  $("#expList").innerHTML = h;
  $$("#expList button").forEach((b) => b.addEventListener("click", () => selectExperiment(b.dataset.id)));
}

function paramInput(p) {
  const id = `param-${p.name}`;
  const label = `${esc(p.name)} <span class="muted">${esc(p.help)}</span>`;
  if (p.kind === "bool") return `<label class="chk"><input type="checkbox" id="${id}" ${p.default ? "checked" : ""}> ${label}</label>`;
  if (p.kind === "choice") return `<label>${label}<select id="${id}">${p.choices.map((c) => `<option ${c === p.default ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label>`;
  if (p.kind === "int" || p.kind === "float") {
    return `<label>${label}<input type="number" id="${id}" value="${esc(p.default)}" ${p.min != null ? `min="${p.min}"` : ""} ${p.max != null ? `max="${p.max}"` : ""} step="${p.kind === "int" ? 1 : "any"}"></label>`;
  }
  return `<label class="full">${label}<input id="${id}" class="mono" value="${esc(p.default)}"></label>`;
}

function selectExperiment(id) {
  const e = state.experiments.find((x) => x.id === id);
  if (!e) return;
  state.currentExp = e;
  $$("#expList button").forEach((b) => b.classList.toggle("active", b.dataset.id === id));
  $("#expDetail").innerHTML = `<h2>${esc(e.title)} ${e.has_tutor ? '<span class="badge pass" style="text-transform:none">📘 tutor</span>' : ""}</h2>
    <p>${esc(e.summary)}</p>${e.description ? `<p class="muted small">${esc(e.description)}</p>` : ""}
    ${e.hardware_notes ? `<p class="small"><b>Hardware:</b> ${esc(e.hardware_notes)}</p>` : ""}
    <div class="form-grid">${e.params.map(paramInput).join("")}</div>`;
  $("#expShots").value = e.default_shots;
  $("#expRunCard").classList.remove("hidden");
  $("#expOutput").innerHTML = "";
  try { history.replaceState(null, "", "#experiments/" + id); } catch (_) {}
}

function expParams() {
  const out = {};
  state.currentExp.params.forEach((p) => {
    const el = $(`#param-${p.name}`);
    out[p.name] = p.kind === "bool" ? el.checked : el.value;
  });
  return out;
}
function ibmOptions() {
  return { optimization_level: +$("#ibmLevel").value, seeds: +$("#ibmSeeds").value, max_two_qubit: +$("#ibmMax2q").value,
           dynamical_decoupling: $("#ibmDD").checked, twirling: $("#ibmTwirl").checked, measure_twirling: $("#ibmTwirl").checked,
           override_caps: $("#ibmOverride").checked };
}
async function expAction(kind) {
  const e = state.currentExp; if (!e) return;
  const busy = $("#expBusy"); busy.textContent = kind === "run" ? "Running… (cloud & fake-device runs can take a while)" : "Working…";
  $$("#expRunCard button").forEach((b) => (b.disabled = true));
  const body = { experiment: e.id, params: expParams(), backend: $("#expBackend").value, shots: +$("#expShots").value || null,
                 mitigate_readout: $("#expMitigate").checked, confirm: $("#expConfirm").checked, ibm_options: ibmOptions() };
  try {
    if (kind === "preview") {
      const d = await api("POST", `/api/experiments/${encodeURIComponent(e.id)}/circuits`, { params: body.params });
      $("#expOutput").innerHTML = `<div class="card"><h2>Circuits (${d.total})</h2>${d.circuits.map((c) =>
        `<h3>${esc(c.name)} <span class="muted small">${c.profile.qubits} qubits · ${c.profile.size} ops · depth ${c.profile.depth} · 2q ${c.profile.two_qubit} · multi ${c.profile.multi_qubit}</span></h3><pre class="code">${esc(c.drawing)}</pre>`).join("")}</div>`;
    } else if (kind === "preflight") {
      $("#expOutput").innerHTML = preflightHTML(await api("POST", "/api/preflight", body));
    } else {
      const out = await api("POST", "/api/run", body);
      $("#expOutput").innerHTML = renderReport(out);
      if (out.status !== "DONE") toast("Submitted — follow it in the Jobs tab.");
    }
  } catch (err) { $("#expOutput").innerHTML = `<div class="card">${errorHTML(err)}</div>`; }
  finally { busy.textContent = ""; $$("#expRunCard button").forEach((b) => (b.disabled = false)); }
}

/* ------------------------------------------------------------------ enigma */
const QWERTZ = ["QWERTZUIO", "ASDFGHJK", "PYXCVBNML"];
function enigmaRotorSlots() {
  const m4 = $("#enModel").value === "M4";
  const info = state.info.enigma;
  const defaults = m4 ? ["BETA", "II", "IV", "I"] : ["I", "II", "III"];
  const names = m4 ? ["Greek", "Left", "Middle", "Right"] : ["Left", "Middle", "Right"];
  $("#enRotors").innerHTML = defaults.map((d, i) => {
    const choices = m4 && i === 0 ? info.greek : info.rotors;
    return `<div class="rotor"><b>${names[i]}</b><select class="enRotor">${choices.map((c) => `<option ${c === d ? "selected" : ""}>${c}</option>`).join("")}</select>
      <label>Ring <input type="number" class="enRing num" min="1" max="26" value="1"></label>
      <label>Start <input class="enPos num mono" maxlength="1" value="A"></label></div>`;
  }).join("");
  $("#enReflector").innerHTML = (m4 ? ["B-THIN", "C-THIN"] : ["B", "C", "A"]).map((r) => `<option>${r}</option>`).join("");
  $$("#enRotors select, #enRotors input").forEach((el) => el.addEventListener("input", encryptNow));
}
function enigmaConfig() {
  return { rotors: $$(".enRotor").map((s) => s.value).join(" "), rings: $$(".enRing").map((s) => s.value || 1).join(" "),
           positions: $$(".enPos").map((s) => (s.value || "A").toUpperCase()).join(""), reflector: $("#enReflector").value,
           plugboard: $("#enPlug").value };
}
const encryptNow = debounce(async () => {
  try {
    const d = await api("POST", "/api/enigma/encrypt", { config: enigmaConfig(), text: $("#enInput").value, keep: $("#enKeep").checked, trace: true });
    $("#enOutput").textContent = d.grouped;
    $("#enDescribe").textContent = d.describe;
    $("#enWindows").innerHTML = d.final_window.split("").map((c) => `<div>${esc(c)}</div>`).join("");
    const last = d.trace && d.trace[d.trace.length - 1];
    $$(".lamp").forEach((l) => l.classList.toggle("lit", !!last && l.dataset.k === last.output));
    $$(".lamp").forEach((l) => l.classList.toggle("key", !!last && l.dataset.k === last.input));
    $("#enPath").innerHTML = last ? `<span>key <b>${esc(last.input)}</b></span>` + last.path.map((s) => `<span>${esc(s.stage)} <b>${esc(s.letter)}</b></span>`).join("") : "";
  } catch (e) { $("#enOutput").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
}, 150);

function initEnigma() {
  $("#lampboard").innerHTML = QWERTZ.map((row) => `<div class="lamprow">${row.split("").map((k) => `<div class="lamp" data-k="${k}" role="button" aria-label="${k}">${k}</div>`).join("")}</div>`).join("");
  $$(".lamp").forEach((l) => l.addEventListener("click", () => { $("#enInput").value += l.dataset.k; encryptNow(); }));
  $("#enModel").addEventListener("change", () => { enigmaRotorSlots(); encryptNow(); });
  ["#enReflector", "#enPlug", "#enInput", "#enKeep"].forEach((s) => $(s).addEventListener("input", encryptNow));
  enigmaRotorSlots(); encryptNow();
  $("#scanRun").addEventListener("click", async () => {
    try {
      const d = await api("POST", "/api/enigma/scan", { config: enigmaConfig(), ciphertext: $("#scanCipher").value, crib: $("#scanCrib").value });
      $("#scanOut").innerHTML = `<p>${d.tested.toLocaleString()} windows tested · <b>${d.matches}</b> consistent</p>` +
        tableHTML("Matches", ["start window", "decryption"], d.results.map((r) => [r.positions, r.grouped]));
    } catch (e) { $("#scanOut").innerHTML = errorHTML(e); }
  });
  $("#qCompare").addEventListener("click", async () => {
    try {
      const text = ($("#enInput").value.toUpperCase().match(/[A-Z]/g) || ["H"]).join("");
      const d = await api("POST", "/api/enigma/oracle-compare", { config: enigmaConfig(), crib: text.slice(0, +$("#qCrib").value),
        key_bits: +$("#qKeyBits").value, first: $("#qFirst").value || "A" });
      $("#qOut").innerHTML = tableHTML(`Raw reversible-oracle cost (candidates ${d.candidates.join(", ")})`, ["synthesis", "operations", "depth", "multi-controlled gates"],
        d.rows.map((r) => [r.synthesis, r.size, r.depth, r.multi_qubit])) + `<p class="muted small">Logical (untranspiled) counts for one encryption pass. Use Preflight on an IBM backend for native gate counts.</p>`;
    } catch (e) { $("#qOut").innerHTML = errorHTML(e); }
  });
  $("#qRun").addEventListener("click", async () => {
    const cfg = enigmaConfig();
    const btn = $("#qRun"); btn.disabled = true; $("#qOut").innerHTML = '<p class="muted">Building oracle and running…</p>';
    try {
      const out = await api("POST", "/api/run", { experiment: "enigma_grover", backend: $("#qBackend").value, confirm: $("#qConfirm").checked,
        params: { model: "historical", message: $("#enInput").value, crib_length: +$("#qCrib").value, rotors: cfg.rotors.split(" ").slice(-3).join(" "),
                  rings: cfg.rings.split(" ").slice(-3).join(" "), reflector: ["B", "C", "A"].includes(cfg.reflector) ? cfg.reflector : "B",
                  plugboard: cfg.plugboard, secret_window: cfg.positions.slice(-3), key_bits: +$("#qKeyBits").value,
                  first: ($("#qFirst").value || "A").toUpperCase(), synthesis: $("#qSynth").value } });
      $("#qOut").innerHTML = renderReport(out);
    } catch (e) { $("#qOut").innerHTML = errorHTML(e); } finally { btn.disabled = false; }
  });
}

/* ------------------------------------------------------------------ tutor */
const LEVEL_LABEL = { foundations: "Foundations", algorithms: "Algorithms", applications: "Applications", hardware: "Hardware" };
let tutorData = null;

async function loadTutor() {
  if (tutorData) return;
  try {
    tutorData = await api("GET", "/api/tutor");
    let level = null, h = "";
    tutorData.curriculum.forEach((l) => {
      if (l.level !== level) { level = l.level; h += `<h4>${esc(LEVEL_LABEL[level] || level)}</h4>`; }
      h += `<button data-lesson="${esc(l.id)}">${esc(l.title)}</button>`;
    });
    $("#tutorList").innerHTML = h;
    $$("#tutorList button").forEach((b) => b.addEventListener("click", () => showLesson(b.dataset.lesson)));
    renderGlossary("");
    $("#glossarySearch").addEventListener("input", (e) => renderGlossary(e.target.value));
    if (tutorData.curriculum[0]) showLesson(tutorData.curriculum[0].id);
  } catch (e) { toast(e.message); }
}

function showLesson(id) {
  const l = tutorData.curriculum.find((x) => x.id === id);
  if (!l) return;
  $$("#tutorList button").forEach((b) => b.classList.toggle("active", b.dataset.lesson === id));
  const field = (label, body) => body ? `<h3>${esc(label)}</h3><p>${esc(body)}</p>` : "";
  let h = `<h2>${esc(l.title)} <span class="badge pass" style="text-transform:none">${esc(LEVEL_LABEL[l.level] || l.level)}</span></h2>`;
  h += field("The big idea", l.big_idea);
  h += field("Key intuition", l.key_intuition);
  h += field("Common misconception", l.common_misconception);
  h += field("Why it matters", l.real_world_use);
  h += `<h3>Try it in the playground</h3><p>${esc(l.try_what_to_look_for)}</p>
        <button class="primary" data-run="${esc(l.try_experiment)}">Open ${esc(l.try_experiment)} →</button>`;
  if (l.steps && l.steps.length) h += `<h3>Steps</h3><ol class="steps">${l.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>`;
  if (l.further_reading && l.further_reading.length)
    h += `<h3>Further reading</h3><ul>${l.further_reading.map((r) => `<li><a href="${esc(r.url)}" target="_blank" rel="noreferrer noopener">${esc(r.title)}</a></li>`).join("")}</ul>`;
  $("#lessonDetail").innerHTML = h;
  const btn = $("#lessonDetail [data-run]");
  if (btn) btn.addEventListener("click", () => { showTab("experiments"); selectExperiment(btn.dataset.run); });
  try { history.replaceState(null, "", "#tutor/" + id); } catch (_) {}
}

function renderGlossary(filter) {
  const g = tutorData.glossary;
  const q = (filter || "").toLowerCase();
  const keys = Object.keys(g).filter((k) => !q || k.toLowerCase().includes(q) || g[k].toLowerCase().includes(q)).sort();
  $("#glossary").innerHTML = keys.map((k) => `<div class="gterm"><b>${esc(k)}</b><span>${esc(g[k])}</span></div>`).join("")
    || '<p class="muted small">No matching terms.</p>';
}

function tutorPanel(t, title) {
  const li = (label, body) => body ? `<div class="tsec"><span>${esc(label)}</span><p>${esc(body)}</p></div>` : "";
  let h = `<div class="card tutorcard"><h2>📘 ${esc(title)} — tutor</h2>`;
  h += li("The idea", t.concept);
  h += li("How it works", t.how_it_works);
  h += li("Intuition", t.intuition);
  h += li("Common misconception", t.misconception);
  h += li("What to look for", t.what_to_look_for);
  h += li("Why it matters", t.real_world_use);
  h += li("Going deeper", t.going_deeper);
  if (t.try_this && t.try_this.length)
    h += `<div class="tsec"><span>Try this</span><ul class="steps">${t.try_this.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>`;
  if (t.references && t.references.length)
    h += `<div class="tsec"><span>References</span><ul>${t.references.map((r) => `<li><a href="${esc(r.url)}" target="_blank" rel="noreferrer noopener">${esc(r.title)}</a></li>`).join("")}</ul></div>`;
  return h + "</div>";
}

async function showExperimentTutor() {
  const e = state.currentExp; if (!e) return;
  try {
    const d = await api("GET", `/api/experiments/${encodeURIComponent(e.id)}/tutor`);
    $("#expOutput").innerHTML = tutorPanel(d.tutor, d.title);
  } catch (err) { $("#expOutput").innerHTML = `<div class="card"><p class="muted">No tutor for this experiment.</p></div>`; }
}

/* ------------------------------------------------------------------ jobs */
async function loadJobs() {
  try {
    const d = await api("GET", "/api/jobs");
    $("#jobsTable").innerHTML = "<tr><th>created</th><th>status</th><th>backend</th><th>experiment</th><th>job id</th><th></th></tr>" +
      d.jobs.map((j) => `<tr class="clickable" data-id="${esc(j.job_id)}"><td>${new Date(j.created_at * 1000).toLocaleString()}</td>
        <td><span class="badge ${esc(j.status)}">${esc(j.status)}</span></td><td>${esc(j.backend)}</td><td>${esc(j.experiment || "")}</td>
        <td class="mono small">${esc(j.job_id)}</td><td><button class="ghost" data-refresh="${esc(j.job_id)}">refresh</button>
        <button class="ghost" data-del="${esc(j.job_id)}">✕</button></td></tr>`).join("");
    $$("#jobsTable tr.clickable").forEach((tr) => tr.addEventListener("click", (ev) => { if (ev.target.tagName !== "BUTTON") showJob(tr.dataset.id); }));
    $$("#jobsTable [data-refresh]").forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try { const out = await api("POST", `/api/jobs/${encodeURIComponent(b.dataset.refresh)}/refresh`); $("#jobDetail").innerHTML = renderReport(out); loadJobs(); }
      catch (e) { toast(e.message); } finally { b.disabled = false; }
    }));
    $$("#jobsTable [data-del]").forEach((b) => b.addEventListener("click", async () => { await api("DELETE", `/api/jobs/${encodeURIComponent(b.dataset.del)}`); loadJobs(); }));
  } catch (e) { toast(e.message); }
}
async function showJob(id) { try { $("#jobDetail").innerHTML = renderReport(await api("GET", `/api/jobs/${encodeURIComponent(id)}`)); } catch (e) { toast(e.message); } }

/* ------------------------------------------------------------------ IBM settings */
async function loadIbmStatus() {
  try { const d = await api("GET", "/api/ibm/status"); $("#ibmStatus").textContent = JSON.stringify(d.credentials, null, 2); } catch (e) { toast(e.message); }
}
function initSettings() {
  const send = async (save) => {
    try {
      const d = await api("POST", "/api/ibm/credentials", { token: $("#ibmToken").value, instance: $("#ibmInstance").value, save });
      $("#ibmToken").value = "";
      $("#ibmStatus").textContent = JSON.stringify(d.credentials, null, 2);
      toast(save ? "Saved to Qiskit's account store." : "Key held in memory for this session.");
      loadInfo();
    } catch (e) { toast(e.message); }
  };
  $("#ibmUse").addEventListener("click", () => send(false));
  $("#ibmSave").addEventListener("click", () => send(true));
  $("#ibmClear").addEventListener("click", async () => { const d = await api("DELETE", "/api/ibm/credentials"); $("#ibmStatus").textContent = JSON.stringify(d.credentials, null, 2); loadInfo(); });
  $("#ibmDevices").addEventListener("click", async () => {
    $("#ibmDeviceList").innerHTML = '<p class="muted">Contacting IBM Quantum…</p>';
    try {
      const d = await api("GET", "/api/ibm/devices");
      $("#ibmDeviceList").innerHTML = tableHTML("Devices", ["name", "qubits", "operational", "pending jobs"], d.devices.map((x) => [x.name, x.num_qubits, x.operational, x.pending_jobs ?? "?"]));
    } catch (e) { $("#ibmDeviceList").innerHTML = errorHTML(e); }
  });
}

/* ------------------------------------------------------------------ boot */
(async function boot() {
  try {
    await loadInfo();
    initLab();
    initEnigma();
    initSettings();
    await loadExperiments();
    $("#expLearn").addEventListener("click", showExperimentTutor);
    $("#expPreview").addEventListener("click", () => expAction("preview"));
    $("#expPreflight").addEventListener("click", () => expAction("preflight"));
    $("#expRun").addEventListener("click", () => expAction("run"));
    $("#jobsReload").addEventListener("click", loadJobs);
    const hash = location.hash.replace("#", "");
    if (hash.startsWith("experiments/")) { showTab("experiments"); selectExperiment(hash.split("/")[1]); }
    else if (hash.startsWith("tutor/")) { showTab("tutor"); await loadTutor(); showLesson(hash.split("/")[1]); }
    else if (hash) showTab(hash);
  } catch (e) {
    document.querySelector("main").insertAdjacentHTML("afterbegin", `<div class="card err">Could not reach the qplay server: ${esc(e.message)}</div>`);
  }
})();
