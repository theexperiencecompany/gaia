#!/usr/bin/env node
/**
 * Renders <out>/review.html from report/data.json (+ report/changelog.json when
 * present). Self-contained page; images load lazily from shots/ and report/diff/.
 *
 *   node review/html.mjs [--out DIR]
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { AREAS, DEFAULT_OUT } from "./config.mjs";

const argv = process.argv.slice(2);
const i = argv.indexOf("--out");
const OUT = resolve(i === -1 ? DEFAULT_OUT : argv[i + 1]);
const data = JSON.parse(readFileSync(join(OUT, "report/data.json"), "utf8"));
const clPath = join(OUT, "report/changelog.json");
const changelog = existsSync(clPath) ? JSON.parse(readFileSync(clPath, "utf8")) : null;
const sha = (p) => (existsSync(p) ? readFileSync(p, "utf8").trim().slice(0, 10) : null);
const meta = {
  beforeSha: sha(join(OUT, "before.sha")),
  afterSha: sha(join(OUT, "after.sha")),
  areas: AREAS,
};

const json = (v) => JSON.stringify(v).replace(/</g, "\\u003c");

const html = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GAIA HeroUI v2 to v3 review</title>
<style>
:root{color-scheme:dark;--bg:#0a0a0b;--panel:#131316;--line:#25252b;--fg:#ececef;--dim:#8b8b94;--faint:#55555d;--red:#ff4d4d;--amber:#f5a524;--green:#3ccf7a;--blue:#00bbff}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--fg);font:13px/1.5 Inter,ui-sans-serif,system-ui,sans-serif;display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:16px;padding:10px 16px;border-bottom:1px solid var(--line)}
header h1{font-size:14px;margin:0;font-weight:600}
header .meta{color:var(--dim);font-size:12px}
.tabs{display:flex;gap:4px;margin-left:auto}
button,select,input{font:inherit;color:var(--fg);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:5px 10px}
button{cursor:pointer;color:var(--dim)}button[aria-pressed=true]{color:#fff;border-color:var(--blue);background:#00bbff1c}
main{flex:1;min-height:0;display:flex}
.hidden{display:none!important}
#side{width:320px;flex:0 0 320px;border-right:1px solid var(--line);display:flex;flex-direction:column;min-height:0}
.filters{padding:10px;border-bottom:1px solid var(--line);display:flex;flex-direction:column;gap:8px}
.chips{display:flex;flex-wrap:wrap;gap:4px}.chips button{padding:2px 8px;font-size:11.5px;border-radius:99px}
#list{overflow:auto;flex:1;padding:6px}
#list .grp{color:var(--faint);font-size:10.5px;text-transform:uppercase;letter-spacing:.08em;padding:10px 6px 4px}
#list a{display:flex;gap:8px;align-items:center;padding:5px 7px;border-radius:7px;color:var(--dim);text-decoration:none;cursor:pointer}
#list a:hover{background:#1b1b20;color:#fff}#list a[aria-current=true]{background:#00bbff1c;color:#fff}
#list a .t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#list a .s{font-size:11px;color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:110px}
.sev{font:600 10.5px/1 ui-monospace,monospace;padding:3px 6px;border-radius:99px;white-space:nowrap}
.sev.none{color:var(--green);background:#3ccf7a1a}.sev.low{color:var(--amber);background:#f5a5241a}.sev.high{color:var(--red);background:#ff4d4d1f}.sev.err{color:#fff;background:#ff4d4d}.sev.pend{color:var(--dim);background:#ffffff10}
#stage{flex:1;min-width:0;display:flex;flex-direction:column}
#bar{display:flex;gap:10px;align-items:center;padding:8px 14px;border-bottom:1px solid var(--line);flex-wrap:wrap}
#bar h2{font-size:14px;margin:0;font-weight:600}#bar .sub{color:var(--dim);font-size:12px}
#bar .modes{margin-left:auto;display:flex;gap:4px}
#note{padding:8px 14px;color:var(--dim);font-size:12px;border-bottom:1px solid var(--line)}
#note b{color:var(--fg)}
#view{flex:1;overflow:auto;padding:14px}
.grid{display:grid;gap:12px;align-items:start}.grid.two{grid-template-columns:1fr 1fr}.grid.three{grid-template-columns:1fr 1fr 1fr}
.pane{background:#111;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.pane h3{margin:0;padding:6px 10px;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim);border-bottom:1px solid var(--line);font-weight:500;position:sticky;top:0;background:var(--panel);z-index:3}
.wrap{position:relative}.wrap img{display:block;width:100%}
.box{position:absolute;border:2px solid var(--red);border-radius:3px;background:#ff4d4d12;pointer-events:none}
.missing{padding:40px 20px;color:var(--dim);text-align:center}
.slider{position:relative}.slider .top{position:absolute;inset:0;overflow:hidden}.slider .top img{width:100%}
.slider input{position:sticky;top:0;width:100%;z-index:4;margin:0 0 8px}
.slider .handle{position:absolute;top:0;bottom:0;width:2px;background:var(--blue);z-index:2;pointer-events:none}
#regions{display:flex;gap:6px;flex-wrap:wrap}#regions button{font-size:11px;padding:2px 8px}
#code{display:block;flex:1;overflow:auto;padding:16px 20px}
#code .file{border:1px solid var(--line);border-radius:10px;margin-bottom:10px;background:var(--panel)}
#code summary{cursor:pointer;padding:9px 12px;display:flex;gap:10px;align-items:center}
#code summary .p{font-family:ui-monospace,monospace;font-size:12px;flex:1}
#code .body{padding:4px 14px 12px}
table{border-collapse:collapse;width:100%;font-size:12px}td,th{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}th{color:var(--dim);font-weight:500}
code{font-family:ui-monospace,monospace;font-size:11.5px;color:#d6d6dc}
.arrow{color:var(--blue);padding:0 6px}
#about{display:block;flex:1;overflow:auto;padding:24px 28px;color:#cfcfd6}#about>*,#code>*{max-width:1100px}#about h2{color:#fff;font-size:18px}#about h3{color:#fff;font-size:14px;margin-top:22px}
kbd{border:1px solid var(--line);border-radius:4px;padding:0 5px;font-size:11px}
</style>
<header>
  <h1>HeroUI v2 to v3: what changed on screen</h1>
  <span class="meta" id="meta"></span>
  <nav class="tabs"><button type="button" data-tab="screens" aria-pressed="true">Screens</button><button type="button" data-tab="code" aria-pressed="false">Code changes</button><button type="button" data-tab="about" aria-pressed="false">How to read this</button></nav>
</header>
<main id="screens">
  <aside id="side">
    <div class="filters">
      <input id="q" placeholder="Search route or state  ( / )">
      <div class="chips" id="areas"></div>
      <div class="chips" id="sevs"></div>
      <div class="chips" id="vps"></div>
    </div>
    <div id="list"></div>
  </aside>
  <section id="stage">
    <div id="bar"><div><h2 id="title"></h2><div class="sub" id="sub"></div></div><div class="modes" id="modes"></div></div>
    <div id="note"></div>
    <div id="view"></div>
  </section>
</main>
<main id="code" class="hidden"></main>
<main id="about" class="hidden"></main>
<script>
const DATA = ${json(data)};
const CHANGELOG = ${json(changelog)};
const META = ${json(meta)};
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const hasAfter = !!DATA.after;

function severity(r) {
  if (r.beforeIssue || (hasAfter && r.afterIssue)) return { cls: "err", label: "issue", rank: 4 };
  if (!hasAfter || r.changedPct == null) return { cls: "pend", label: "v3 pending", rank: 0 };
  if (r.changedPct === 0) return { cls: "none", label: "same", rank: 1 };
  if (r.changedPct < 0.5) return { cls: "low", label: r.changedPct.toFixed(2) + "%", rank: 2 };
  return { cls: "high", label: r.changedPct.toFixed(1) + "%", rank: 3 };
}
const SEVS = [["all", "All"], ["changed", "Changed"], ["high", "Over 0.5%"], ["err", "Issues"], ["none", "Unchanged"]];
const state = { area: "all", sev: hasAfter ? "changed" : "all", vp: "desktop", q: "", idx: 0, mode: hasAfter ? "sbs" : "before", boxes: true };

const NOISE = DATA.noise;
const fmtNoise = (k) => NOISE[k]?.shots ? NOISE[k].stableShots + "/" + NOISE[k].shots + " shots identical across two runs" : "single run";
$("#meta").textContent = "before " + (META.beforeSha ?? "?") + " (v2)  ·  after " + (META.afterSha ?? "not captured yet") + " (v3)  ·  noise: " + fmtNoise("before");

function chipRow(el, items, key, render) {
  el.innerHTML = items.map(([v, l]) => '<button type="button" data-v="' + esc(v) + '" aria-pressed="' + (state[key] === v) + '">' + esc(l) + "</button>").join("");
  el.onclick = (e) => { const b = e.target.closest("button"); if (!b) return; state[key] = b.dataset.v; state.idx = 0; render(); };
}
function rows() {
  const q = state.q.toLowerCase();
  return DATA.rows.filter((r) => r.vp === state.vp
    && (state.area === "all" || r.area === state.area)
    && (!q || (r.label + " " + r.key + " " + r.stateLabel).toLowerCase().includes(q))
    && (() => { const s = severity(r); return state.sev === "all" || (state.sev === "changed" && s.rank >= 2) || (state.sev === "high" && s.rank >= 3) || (state.sev === "err" && s.rank === 4) || (state.sev === "none" && s.rank === 1); })());
}
function counts(area) { return DATA.rows.filter((r) => r.vp === state.vp && (area === "all" || r.area === area)).length; }

function renderList() {
  const areas = [["all", "All areas (" + counts("all") + ")"], ...META.areas.filter((a) => counts(a)).map((a) => [a, a + " (" + counts(a) + ")"])];
  chipRow($("#areas"), areas, "area", renderAll);
  chipRow($("#sevs"), SEVS, "sev", renderAll);
  chipRow($("#vps"), [["desktop", "Desktop 1440"], ["mobile", "Mobile 390"]], "vp", renderAll);
  const list = rows();
  let html = "", grp = null;
  list.forEach((r, i) => {
    if (r.area !== grp) { grp = r.area; html += '<div class="grp">' + esc(grp) + "</div>"; }
    const s = severity(r);
    html += '<a data-i="' + i + '" aria-current="' + (i === state.idx) + '"><span class="t">' + esc(r.key) + '</span><span class="s">' + esc(r.state === "base" ? "" : r.stateLabel) + '</span><span class="sev ' + s.cls + '">' + esc(s.label) + "</span></a>";
  });
  $("#list").innerHTML = html || '<div class="missing">Nothing matches these filters.</div>';
  $("#list").onclick = (e) => { const a = e.target.closest("a"); if (!a) return; state.idx = +a.dataset.i; renderAll(); };
  return list;
}

function img(src, r) {
  if (!src) return '<div class="missing">not captured</div>';
  const boxes = state.boxes && r.regions && r.w ? r.regions.map((g, k) => '<div class="box" id="rg' + k + '" style="left:' + (100 * g.x / r.w) + "%;top:" + (100 * g.y / r.h) + "%;width:" + (100 * g.w / r.w) + "%;height:" + (100 * g.h / r.h) + '%"></div>').join("") : "";
  return '<div class="wrap"><img loading="lazy" src="' + esc(src) + '" alt="">' + boxes + "</div>";
}
function pane(title, body) { return '<section class="pane"><h3>' + esc(title) + "</h3>" + body + "</section>"; }

function renderStage(list) {
  const r = list[state.idx];
  const modes = hasAfter ? [["sbs", "Side by side"], ["slider", "Slider"], ["diff", "Diff"], ["before", "Before"], ["after", "After"]] : [["before", "Before (v2)"]];
  $("#modes").innerHTML = modes.map(([m, l], k) => '<button type="button" data-m="' + m + '" aria-pressed="' + (state.mode === m) + '" title="key ' + (k + 1) + '">' + l + "</button>").join("") + (hasAfter ? '<button type="button" data-m="boxes" aria-pressed="' + state.boxes + '" title="key r">Regions</button>' : "");
  $("#modes").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; if (b.dataset.m === "boxes") state.boxes = !state.boxes; else state.mode = b.dataset.m; renderStage(rows()); };
  if (!r) { $("#title").textContent = ""; $("#sub").textContent = ""; $("#note").innerHTML = ""; $("#view").innerHTML = ""; return; }
  $("#title").textContent = r.key + (r.state === "base" ? "" : "  —  " + r.stateLabel);
  $("#sub").innerHTML = esc(r.area) + " · " + esc(r.vp) + " · " + esc(r.kind) + " · <code>" + esc(r.file) + "</code>";
  const s = severity(r);
  const notes = [];
  if (r.beforeIssue) notes.push("<b>v2:</b> " + esc(r.beforeIssue));
  if (hasAfter && r.afterIssue) notes.push("<b>v3:</b> " + esc(r.afterIssue));
  if (s.rank >= 2) notes.push("<b>" + esc(r.changedPct.toFixed(3)) + "%</b> of pixels changed in " + r.regions.length + " region" + (r.regions.length === 1 ? "" : "s") + " (noise masked: v2 " + (r.beforeNoisePct ?? 0).toFixed(3) + "%, v3 " + (r.afterNoisePct ?? 0).toFixed(3) + "%)");
  if (s.rank === 1) notes.push("Pixel-identical after masking run-to-run noise.");
  if (!hasAfter) notes.push("v3 has not been captured yet; this is the v2 reference.");
  const regionBtns = r.regions?.length ? '<div id="regions">' + r.regions.map((g, k) => '<button type="button" data-k="' + k + '">region ' + (k + 1) + " · " + g.w + "x" + g.h + "</button>").join("") + "</div>" : "";
  $("#note").innerHTML = notes.join("  ·  ") + regionBtns;
  const v = $("#view");
  if (state.mode === "sbs") v.innerHTML = '<div class="grid two">' + pane("before · v2", img(r.before, r)) + pane("after · v3", img(r.after, r)) + "</div>";
  else if (state.mode === "diff") v.innerHTML = '<div class="grid two">' + pane("diff · red changed, blue masked noise", img(r.diff, r)) + pane("after · v3", img(r.after, r)) + "</div>";
  else if (state.mode === "before") v.innerHTML = '<div class="grid">' + pane("before · v2", img(r.before, r)) + "</div>";
  else if (state.mode === "after") v.innerHTML = '<div class="grid">' + pane("after · v3", img(r.after, r)) + "</div>";
  else if (state.mode === "slider") {
    v.innerHTML = '<div class="grid">' + pane("slider · left of the line v2, right v3", '<div class="slider"><input type="range" min="0" max="100" value="50" id="sl"><div class="wrap"><img src="' + esc(r.before) + '" alt=""><div class="top" id="st"><img src="' + esc(r.after) + '" alt=""></div><div class="handle" id="sh"></div></div></div>') + "</div>";
    const set = () => { const p = $("#sl").value; $("#st").style.clipPath = "inset(0 0 0 " + p + "%)"; $("#sh").style.left = p + "%"; };
    $("#sl").oninput = set; set();
  }
  const rg = $("#regions");
  if (rg) rg.onclick = (e) => { const b = e.target.closest("button"); if (!b) return; const el = document.getElementById("rg" + b.dataset.k); el?.scrollIntoView({ block: "center" }); };
  v.scrollTop = 0;
}

function renderAll() { const list = renderList(); state.idx = Math.min(state.idx, Math.max(0, list.length - 1)); renderStage(list); document.querySelector('#list a[aria-current="true"]')?.scrollIntoView({ block: "nearest" }); }

$("#q").oninput = (e) => { state.q = e.target.value; state.idx = 0; renderAll(); };
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") { if (e.key === "Escape") e.target.blur(); return; }
  const list = rows();
  if (e.key === "j" || e.key === "ArrowDown") { state.idx = Math.min(list.length - 1, state.idx + 1); renderAll(); e.preventDefault(); }
  else if (e.key === "k" || e.key === "ArrowUp") { state.idx = Math.max(0, state.idx - 1); renderAll(); e.preventDefault(); }
  else if (e.key === "/") { $("#q").focus(); e.preventDefault(); }
  else if (e.key === "r") { state.boxes = !state.boxes; renderStage(list); }
  else if (e.key === "m") { state.vp = state.vp === "desktop" ? "mobile" : "desktop"; renderAll(); }
  else if (/^[1-5]$/.test(e.key) && hasAfter) { state.mode = ["sbs", "slider", "diff", "before", "after"][+e.key - 1]; renderStage(list); }
});

function renderCode() {
  const el = $("#code");
  if (!CHANGELOG) { el.innerHTML = '<div class="missing">The code change log is generated once the v3 build is captured.</div>'; return; }
  // Files that touch HeroUI first, the rest (copy, tests, styles) after.
  const files = [...CHANGELOG.files].sort((a, b) => (b.components.length > 0) - (a.components.length > 0) || a.file.localeCompare(b.file));
  const fmt = (o) => Object.entries(o).map(([k, n]) => "<code>" + esc(k) + "</code>" + (n > 1 ? " x" + n : "")).join(", ") || "<span style=color:var(--faint)>none</span>";
  const totals = files.reduce((t, f) => { for (const p of f.props) if (p.from && p.to) t.remaps++; t.comps += f.components.length; return t; }, { remaps: 0, comps: 0 });
  const byRoot = {};
  for (const f of files) for (const c of f.components) {
    const r = (byRoot[c.root] ??= { files: 0, v2: {}, v3: {} });
    r.files++;
    for (const [k, n] of Object.entries(c.v2)) r.v2[k] = (r.v2[k] ?? 0) + n;
    for (const [k, n] of Object.entries(c.v3)) r.v3[k] = (r.v3[k] ?? 0) + n;
  }
  const overview = '<p style="color:var(--dim)">Every HeroUI component across the app: the v2 parts it was built from and the v3 compound parts that replaced them.</p><table style="margin:10px 0 18px"><tr><th>Component</th><th>Files</th><th>v2 parts</th><th></th><th>v3 parts</th></tr>' + Object.entries(byRoot).sort((a, b) => b[1].files - a[1].files).map(([root, r]) => "<tr><td><b>" + esc(root) + "</b></td><td>" + r.files + "</td><td>" + fmt(r.v2) + '</td><td class="arrow">to</td><td>' + fmt(r.v3) + "</td></tr>").join("") + "</table>";
  el.innerHTML = overview + '<h2 style="font-size:16px">' + files.length + " changed files, " + totals.comps + " component migrations, " + totals.remaps + ' prop remaps</h2><p style="color:var(--dim)">From <code>git diff ' + esc(CHANGELOG.before.slice(0, 10)) + " " + esc(CHANGELOG.after.slice(0, 10)) + '</code>. Each file lists the HeroUI v2 parts it used and the v3 parts that replaced them, then every prop that changed and the rule behind it (the codemod\\'s Button table, a <code>decisions.json</code> mapping, or a manual choice).</p><input id="cq" placeholder="Filter files or components" style="width:100%;margin:8px 0 14px"><div id="cfiles"></div>';
  const draw = (q) => {
    $("#cfiles").innerHTML = files.filter((f) => !q || (f.file + JSON.stringify(f.components)).toLowerCase().includes(q)).map((f) => {
      const comps = f.components.map((c) => "<tr><td><b>" + esc(c.root) + "</b></td><td>" + fmt(c.v2) + '</td><td class="arrow">to</td><td>' + fmt(c.v3) + "</td></tr>").join("");
      const props = f.props.map((p) => "<tr><td><code>" + esc(p.component ?? "") + "</code></td><td>" + (p.from ? "<code>" + esc(p.from) + "</code>" : "") + '</td><td class="arrow">to</td><td>' + (p.to ? "<code>" + esc(p.to) + "</code>" : '<span style="color:var(--faint)">removed</span>') + '</td><td style="color:var(--dim)">' + esc(p.rule ?? "added") + "</td></tr>").join("");
      return '<details class="file"><summary><span class="p">' + esc(f.file) + '</span><span style="color:var(--green)">+' + f.added + '</span><span style="color:var(--red)">-' + f.removed + "</span><span style=color:var(--dim)>" + f.components.map((c) => esc(c.root)).join(", ") + '</span></summary><div class="body">' + (comps ? '<table><tr><th>Component</th><th>v2 parts</th><th></th><th>v3 parts</th></tr>' + comps + "</table>" : "") + (props ? '<table style="margin-top:10px"><tr><th>On</th><th>v2 prop</th><th></th><th>v3 prop</th><th>Why</th></tr>' + props + "</table>" : "") + "</div></details>";
    }).join("");
  };
  draw("");
  $("#cq").oninput = (e) => draw(e.target.value.toLowerCase());
}

function renderAbout() {
  const sk = DATA.skipped.map((s) => "<li><code>" + esc(s.pattern) + "</code>: " + esc(s.reason) + "</li>").join("");
  const nz = (k) => NOISE[k]?.shots ? NOISE[k].stableShots + " of " + NOISE[k].shots + " shots were pixel-identical across two captures; " + NOISE[k].noisyPixelPct.toFixed(4) + "% of all pixels differed and are masked." : "captured once.";
  $("#about").innerHTML = "<h2>How to read this review</h2>"
    + "<p>Every page of the web app was rendered twice per build in a headless browser, once with HeroUI v2 (before) and once with v3 (after), against the same local API and the same seeded account. Each screen is shown at desktop (1440x900) and mobile (390x844).</p>"
    + "<h3>Screens</h3><p>The left list is every route and every interaction state: each menu, select, popover, tooltip, tab, accordion and modal the page has, opened the same way on both builds. Pick an <b>area</b> and a <b>severity</b> to narrow it. The badge is the share of the screen's pixels that changed: <span class=\\"sev none\\">same</span> nothing changed, <span class=\\"sev low\\">0.12%</span> under half a percent, <span class=\\"sev high\\">3.4%</span> more, <span class=\\"sev err\\">issue</span> the screen failed to render or its trigger was not found on one side.</p>"
    + "<p><b>Side by side</b> shows both with red boxes around changed regions; <b>Slider</b> lays v3 over v2 so you can drag across; <b>Diff</b> paints changed pixels red and masked noise blue. Keys: <kbd>j</kbd>/<kbd>k</kbd> next and previous, <kbd>1</kbd>-<kbd>5</kbd> modes, <kbd>r</kbd> regions, <kbd>m</kbd> desktop or mobile, <kbd>/</kbd> search.</p>"
    + "<h3>Noise</h3><p>Anything that changes between two captures of the same build (an animation frame, a lazily decoded image) is not a migration change, so it is masked before the builds are compared. v2: " + nz("before") + " v3: " + nz("after") + "</p>"
    + "<h3>Code changes</h3><p>For every changed file: the v2 components it used, the v3 compound parts that replaced them, and every prop that was remapped, with the rule that decided it.</p>"
    + "<h3>Not covered</h3><ul>" + sk + "</ul>"
    + (DATA.blockedMutations.before.length ? "<h3>Writes blocked during capture</h3><p>Captures never change the seeded data: these requests were blocked.</p><ul>" + DATA.blockedMutations.before.map((m) => "<li><code>" + esc(m) + "</code></li>").join("") + "</ul>" : "");
}

document.querySelector(".tabs").onclick = (e) => {
  const b = e.target.closest("button"); if (!b) return;
  for (const x of document.querySelectorAll(".tabs button")) x.setAttribute("aria-pressed", String(x === b));
  for (const id of ["screens", "code", "about"]) document.getElementById(id).classList.toggle("hidden", id !== b.dataset.tab);
};
renderAll(); renderCode(); renderAbout();
</script></html>`;

writeFileSync(join(OUT, "review.html"), html);
// The served directory holds thousands of shots; its root opens the review instead of a listing.
writeFileSync(join(OUT, "index.html"), '<!doctype html><meta http-equiv="refresh" content="0; url=review.html">');
console.log(`wrote ${join(OUT, "review.html")} (${data.rows.length} shots)`);
