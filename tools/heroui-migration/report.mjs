#!/usr/bin/env node
/**
 * Side-by-side diff report for a HeroUI migration.
 * Zero dependencies. Diffs every changed source file between two git refs
 * (or the working tree) and renders one self-contained HTML page.
 *
 * Usage:
 *   node tools/heroui-migration/report.mjs --base origin/main
 *   node tools/heroui-migration/report.mjs --base origin/main --head heroui/v3 --out m.html
 *   node tools/heroui-migration/report.mjs --base main --staged
 *   node tools/heroui-migration/report.mjs --base main --only Button,Chip
 */
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";

const args = process.argv.slice(2);
const flag = (name, def = null) => {
  const i = args.indexOf(`--${name}`);
  return i === -1 ? def : args[i + 1] ?? true;
};
const BASE = flag("base", "HEAD");
const HEAD = flag("head", null);
const OUT = flag("out", "tools/heroui-migration/report.html");
const ONLY = flag("only", null);
const STAGED = args.includes("--staged");

const git = (...a) => execFileSync("git", a, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
const tryGit = (...a) => {
  try {
    return git(...a);
  } catch {
    return "";
  }
};

function changedFiles() {
  if (STAGED) return tryGit("diff", "--cached", "--name-only").split("\n").filter(Boolean);
  if (HEAD) return tryGit("diff", "--name-only", `${BASE}...${HEAD}`).split("\n").filter(Boolean);
  return [...tryGit("diff", "--name-only", BASE).split("\n"), ...tryGit("diff", "--name-only").split("\n")].filter(Boolean);
}

function readAt(ref, path) {
  // ref may be "WORKTREE"
  if (ref === "WORKTREE") return readFileSync(path, "utf8");
  return tryGit("show", `${ref}:${path}`);
}

/** LCS line diff -> aligned rows. */
function diffLines(a, b) {
  const A = a.split("\n");
  const B = b.split("\n");
  const n = A.length;
  const m = B.length;
  // O(n*m) is fine for source files; guard against absurd sizes.
  if (n * m > 25_000_000) return [[...A.map((l) => ["-", l, ""])], B.map((l) => ["+", "", l])].flat();
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const rows = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) {
      rows.push([" ", A[i], B[j]]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push(["-", A[i], ""]);
      i++;
    } else {
      rows.push(["+", "", B[j]]);
      j++;
    }
  }
  while (i < n) rows.push(["-", A[i++], ""]);
  while (j < m) rows.push(["+", "", B[j++]]);
  // pair adjacent -/+ into single side-by-side rows
  const out = [];
  for (let k = 0; k < rows.length; k++) {
    if (rows[k][0] === "-" && rows[k + 1]?.[0] === "+") {
      out.push(["~", rows[k][1], rows[k + 1][2]]);
      k++;
    } else out.push(rows[k]);
  }
  return out;
}

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const files = changedFiles().filter(
  (f) => /\.(tsx?|jsx?|css|mjs|cjs)$/.test(f) && !f.includes("node_modules") && !f.includes(".next/"),
);

let entries = [];
for (const f of files) {
  const before = readAt(BASE, f);
  const after = HEAD ? readAt(HEAD, f) : readFileSync(f, "utf8").toString();
  if (before === after) continue;
  const rows = diffLines(before, after);
  const adds = rows.filter((r) => r[0] === "+" || r[0] === "~").length;
  const dels = rows.filter((r) => r[0] === "-" || r[0] === "~").length;
  // only keep files that actually touch HeroUI-ish code
  const touches = /@heroui|HeroUI|heroui\(/.test(before + after);
  entries.push({ f, rows, adds, dels, touches });
}

if (ONLY) {
  const want = ONLY.split(",").map((s) => s.trim().toLowerCase());
  entries = entries.filter((e) => want.some((w) => e.f.toLowerCase().includes(w)) || want.some((w) => e.rows.some((r) => (r[1] || "").toLowerCase().includes(w) || (r[2] || "").toLowerCase().includes(w))));
}

entries.sort((a, b) => Number(b.touches) - Number(a.touches) || b.adds + b.dels - (a.adds + a.dels));

const body = entries
  .map((e, idx) => {
    const rows = e.rows
      .map(([t, l, r], i) => {
        const lcls = t === "-" ? "del" : t === "~" ? "chg" : t === "+" ? "gap" : "";
        const rcls = t === "+" ? "add" : t === "~" ? "chg" : t === "-" ? "gap" : "";
        return `<tr><td class="ln">${t === "+" ? "" : i + 1}</td><td class="code ${lcls}">${esc(l)}</td><td class="ln">${t === "-" ? "" : i + 1}</td><td class="code ${rcls}">${esc(r)}</td></tr>`;
      })
      .join("");
    return `<section id="f${idx}" class="file" data-touches="${e.touches}">
  <h2><span class="badge ${e.touches ? "hot" : ""}">${e.touches ? "HEROUI" : "other"}</span> ${esc(e.f)}
    <span class="stat"><b class="a">+${e.adds}</b> <b class="d">-${e.dels}</b></span></h2>
  <table class="diff"><thead><tr><th colspan="2">BEFORE (${esc(BASE)})</th><th colspan="2">AFTER (${esc(HEAD || "working tree")})</th></tr></thead><tbody>${rows}</tbody></table>
</section>`;
  })
  .join("\n");

const nav = entries
  .map((e, idx) => `<a href="#f${idx}" class="${e.touches ? "hot" : ""}">${esc(e.f)}<span>+${e.adds} -${e.dels}</span></a>`)
  .join("");

const html = `<!doctype html><meta charset="utf-8"><title>HeroUI v2 → v3 diff</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:#0d1117;color:#c9d1d9;display:flex}
nav{position:sticky;top:0;height:100vh;overflow:auto;width:320px;flex:0 0 320px;border-right:1px solid #21262d;padding:12px;background:#010409}
nav h1{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#8b949e;margin:0 0 12px}
nav a{display:flex;justify-content:space-between;gap:8px;padding:5px 6px;color:#8b949e;text-decoration:none;border-radius:4px;font-size:11.5px}
nav a:hover{background:#161b22;color:#e6edf3}
nav a.hot{color:#e6edf3}
nav a span{color:#484f58;white-space:nowrap}
main{flex:1;min-width:0;padding:16px 20px}
.file{margin-bottom:36px}
h2{font-size:12.5px;font-weight:600;color:#e6edf3;display:flex;align-items:center;gap:8px;position:sticky;top:0;background:#0d1117;padding:8px 0;margin:0 0 6px;border-bottom:1px solid #21262d}
.badge{font-size:9px;padding:2px 6px;border-radius:99px;background:#21262d;color:#8b949e;letter-spacing:.06em}
.badge.hot{background:#1f6feb33;color:#79c0ff}
.stat{margin-left:auto;font-weight:400}.stat .a{color:#3fb950}.stat .d{color:#f85149}
table.diff{width:100%;border-collapse:collapse;table-layout:fixed}
table.diff th{font-size:10px;color:#484f58;text-align:left;padding:3px 6px;font-weight:400;border-bottom:1px solid #21262d}
td{vertical-align:top;padding:0 6px;white-space:pre-wrap;word-break:break-word}
td.ln{width:36px;color:#30363d;text-align:right;user-select:none;font-size:11px}
td.code{width:calc(50% - 36px);border-left:2px solid transparent}
td.del{background:#f851491a}td.add{background:#3fb9501a}td.chg{background:#d2992217}
td.gap{background:#010409}
</style>
<nav><h1>HeroUI v2 → v3 · ${entries.length} files</h1>${nav}</nav>
<main>${body || "<p>No changed source files.</p>"}</main>`;

writeFileSync(OUT, html);
console.log(`wrote ${OUT} (${entries.length} files, ${entries.filter((e) => e.touches).length} touching HeroUI)`);
