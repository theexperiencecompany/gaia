#!/usr/bin/env node
/**
 * Variant mapping matrix for HeroUI v2 -> v3.
 *
 * Extracts the *real* variant vocabularies from the installed type definitions
 * instead of trusting docs prose:
 *   v2  <- @heroui/theme/dist/components/*.js        (tailwind-variants config)
 *   v3  <- @heroui/styles/dist/components/**\/*.d.ts  (TVReturnType generics)
 *
 * Then scans your source for which (component, prop, value) tuples you actually
 * use, so the matrix is prioritised by real usage, not by what exists.
 *
 *   node tools/heroui-migration/variants.mjs                  # built-in v3 snapshot
 *   node tools/heroui-migration/variants.mjs --v3-dir <path>  # re-extract from @heroui/styles
 */
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, join } from "node:path";

const argv = process.argv.slice(2);
const arg = (n, d = null) => {
  const i = argv.indexOf(`--${n}`);
  return i === -1 ? d : argv[i + 1];
};
const ROOT = process.cwd();
const TOOL = join(ROOT, "tools/heroui-migration");
const require_ = createRequire(join(ROOT, "apps/web/package.json"));

/* ---------------------------------- v2 ---------------------------------- */

function extractV2() {
  let themeDir;
  try {
    themeDir = join(require_.resolve("@heroui/theme/package.json"), "..", "dist", "components");
  } catch {
    return {};
  }
  if (!existsSync(themeDir)) return {};
  const out = {};
  for (const file of readdirSync(themeDir).filter((f) => f.endsWith(".js"))) {
    const comp = basename(file, ".js");
    let mod;
    try {
      mod = require_(join(themeDir, file));
    } catch {
      continue;
    }
    for (const exported of Object.values(mod)) {
      // tailwind-variants configs are callable objects: typeof === "function"
      if (!exported || (typeof exported !== "object" && typeof exported !== "function") || !exported.variants) continue;
      const dims = {};
      for (const [dim, vals] of Object.entries(exported.variants)) {
        if (!vals || typeof vals !== "object" || Array.isArray(vals)) continue;
        const keys = Object.keys(vals);
        if (keys.length && keys.every((k) => /^[a-z0-9-]+$/i.test(k)) && keys.some((k) => k !== "true" && k !== "false")) {
          dims[dim] = keys;
        }
      }
      if (Object.keys(dims).length) out[comp] = { ...(out[comp] || {}), ...dims };
    }
  }
  return out;
}

/* ---------------------------------- v3 ---------------------------------- */

/** Brace-matched scan: dims can hold strings OR nested `{ base: string }` objects. */
const DIMS = ["variant", "size", "color", "radius", "shape", "orientation", "placement", "fullWidth"];

function matchBrace(s, i) {
  let d = 0;
  for (let k = i; k < s.length; k++) {
    const c = s[k];
    if (c === '"' || c === "'" || c === "`") {
      const q = c;
      k++;
      while (k < s.length && s[k] !== q) { if (s[k] === "\\") k++; k++; }
      continue;
    }
    if (c === "{") d++;
    else if (c === "}") { d--; if (d === 0) return k; }
  }
  return -1;
}

function topLevelKeys(inner) {
  const keys = [];
  let d = 0, i = 0;
  while (i < inner.length) {
    const c = inner[i];
    if (c === '"' || c === "'") {
      if (d === 0) {
        const q = c;
        let j = i + 1;
        while (j < inner.length && inner[j] !== q) j++;
        let k = j + 1;
        while (k < inner.length && /\s/.test(inner[k])) k++;
        if (inner[k] === ":") keys.push(inner.slice(i + 1, j));
        i = j + 1;
        continue;
      }
      const q = c;
      i++;
      while (i < inner.length && inner[i] !== q) i++;
      i++;
      continue;
    }
    if (c === "{" || c === "[" || c === "(") d++;
    else if (c === "}" || c === "]" || c === ")") d--;
    else if (d === 0 && /[\w-]/.test(c)) {
      let j = i;
      while (j < inner.length && /[\w-]/.test(inner[j])) j++;
      let k = j;
      while (k < inner.length && /\s/.test(inner[k])) k++;
      if (inner[k] === ":") keys.push(inner.slice(i, j));
      i = j;
      continue;
    }
    i++;
  }
  return keys;
}

function dimsFromDts(text) {
  const dims = {};
  for (const dim of DIMS) {
    const re = new RegExp(`\\b${dim}\\s*:\\s*\\{`, "g");
    let m;
    while ((m = re.exec(text))) {
      const open = text.indexOf("{", m.index + dim.length);
      const close = matchBrace(text, open);
      if (close < 0) continue;
      const keys = topLevelKeys(text.slice(open + 1, close));
      if (keys.length) { dims[dim] = keys; break; }
    }
  }
  return dims;
}

function extractV3(dir) {
  const base = join(dir, "dist", "components");
  if (!existsSync(base)) return {};
  const out = {};
  for (const entry of readdirSync(base, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const comp = entry.name;
    const files = readdirSync(join(base, comp)).filter((f) => f.endsWith(".d.ts"));
    const dims = {};
    for (const f of files) {
      const txt = readFileSync(join(base, comp, f), "utf8");
      Object.assign(dims, dimsFromDts(txt));
    }
    // keep only plausible style dimensions
    const clean = {};
    for (const [k, v] of Object.entries(dims)) {
      if (["variant", "size", "color", "radius", "shape", "orientation", "placement", "fullWidth"].includes(k)) clean[k] = v;
    }
    if (Object.keys(clean).length) out[comp] = clean;
  }
  return out;
}

/* -------------------------------- usage --------------------------------- */

const NAME_MAP = {
  Divider: "divider",
  ScrollShadow: "scroll-shadow",
  NumberInput: "number-input",
  CircularProgress: "circular-progress",
  AutoComplete: "autocomplete",
  ButtonGroup: "button-group",
  CheckboxGroup: "checkbox-group",
  RadioGroup: "radio-group",
  InputOTP: "input-otp",
};
const REVERSE = Object.fromEntries(Object.entries(NAME_MAP).map(([k, v]) => [v, k]));
/** "scroll-shadow" -> "ScrollShadow"; NAME_MAP wins for odd casing (InputOTP). */
const pascalOf = (slug) =>
  REVERSE[slug] || slug.split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join("");

const CODE_EXT = new Set([".tsx", ".ts", ".jsx", ".js"]);
const SKIP = new Set(["node_modules", ".next", "dist", "build", ".turbo", ".git"]);

function walk(dir, out = []) {
  let entries = [];
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    if (SKIP.has(e.name)) continue;
    const p = join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (CODE_EXT.has(e.name.slice(e.name.lastIndexOf(".")))) out.push(p);
  }
  return out;
}

function readTag(src, start) {
  let i = start, brace = 0, quote = null;
  while (i < src.length) {
    const c = src[i];
    if (quote) { if (c === "\\") i++; else if (c === quote) quote = null; }
    else if (c === '"' || c === "'" || c === "`") quote = c;
    else if (c === "{") brace++;
    else if (c === "}") brace--;
    else if (c === ">" && brace === 0) return src.slice(start, i + 1);
    i++;
  }
  return src.slice(start, start + 3000);
}

function collectUsage(v2) {
  const files = [...walk(join(ROOT, "apps/web/src")), ...walk(join(ROOT, "libs"))];
  const usage = {}; // comp -> dim -> value -> count
  const components = new Set();
  for (const f of files) {
    const src = readFileSync(f, "utf8");
    if (!src.includes("@heroui/")) continue;
    for (const name of Object.keys(v2)) {
      const jsxName = pascalOf(name);
      const tagRe = new RegExp(`<${jsxName}(?=[\\s/>])`, "g");
      for (const m of src.matchAll(tagRe)) {
        const tag = readTag(src, m.index);
        work: for (const [dim, vals] of Object.entries(v2[name])) {
          const re = new RegExp(`\\b${dim}=(?:"([^"]*)"|'([^']*)'|\\{([^}]*)\\})`);
          const p = tag.match(re);
          if (!p) continue work;
          const value = p[1] ?? p[2] ?? (p[3] ? "{expr}" : null);
          if (value == null) continue work;
          components.add(name);
          usage[name] ??= {};
          usage[name][dim] ??= {};
          usage[name][dim][value] = (usage[name][dim][value] || 0) + 1;
        }
      }
    }
  }
  return usage;
}

/* ------------------------------- mapping -------------------------------- */

/** Documented v2 -> v3 mappings from the HeroUI migration guides. */
const DOCUMENTED = {
  button: {
    variant: {
      solid: "primary", bordered: "secondary", light: "tertiary", flat: "tertiary",
      faded: "secondary", shadow: "primary", ghost: "ghost",
    },
    color: { primary: "→ variant", default: "→ variant", secondary: "→ variant", success: "→ variant", warning: "→ variant", danger: "→ variant" },
    radius: "dropped",
  },
  chip: {
    variant: { solid: "primary", bordered: "secondary", faded: "secondary", flat: "tertiary", light: "tertiary", shadow: "primary", dot: "primary" },
    color: { primary: "accent", secondary: "accent" },
    radius: "dropped",
  },
  input: {
    variant: { flat: "primary", bordered: "secondary", underlined: "secondary", faded: "secondary" },
    color: "dropped", size: "dropped", radius: "dropped",
  },
};

function classify(comp, dim, value, v3) {
  if (value === "{expr}") return { to: "dynamic — typed at call site", status: "dynamic" };
  const doc = DOCUMENTED[comp]?.[dim];
  if (doc === "dropped") return { to: "use Tailwind class", status: "drop" };
  if (doc && typeof doc === "object" && doc[value]) {
    const to = doc[value];
    return { to, status: to.startsWith("→") ? "moved" : "rename" };
  }
  if (V3_REMOVED.has(comp)) return { to: "removed in v3 — use HTML", status: "removed" };
  const v3comp = v3[V3_ALIAS[comp] || comp];
  const v3vals = v3comp?.[dim] || [];
  if (v3vals.includes(value)) return { to: value, status: "same" };
  // component exists in v3 but this dimension does not -> the prop was removed
  if (v3comp && !v3vals.length) return { to: "use Tailwind class", status: "drop" };
  if (!v3comp) return { to: "component removed/renamed", status: "unknown" };
  return { to: v3vals.join(" | "), status: "decide" };
}

/* --------------------- joint color x variant combos --------------------- */

/** Real table from the Button guide: the colour folds INTO the variant. */
const BUTTON_PAIRS = {
  "default|solid": "primary", "primary|solid": "primary", "secondary|solid": "secondary",
  "success|solid": "primary", "warning|solid": "primary", "danger|solid": "danger",
  "primary|bordered": "secondary", "primary|light": "tertiary", "primary|flat": "tertiary",
  "primary|faded": "secondary", "primary|ghost": "ghost", "danger|flat": "danger-soft",
  "danger|bordered": "danger-soft", "default|bordered": "secondary", "default|flat": "tertiary",
  "default|light": "tertiary",
};
const CHIP_PAIRS = { solid: "primary", bordered: "secondary", faded: "secondary", flat: "tertiary", light: "tertiary", shadow: "primary", dot: "primary" };
const CHIP_COLORS = { primary: "accent", secondary: "accent" };

function collectCombos() {
  const files = [...walk(join(ROOT, "apps/web/src")), ...walk(join(ROOT, "libs"))];
  const button = {};
  const chip = {};
  for (const f of files) {
    const src = readFileSync(f, "utf8");
    if (!src.includes("@heroui/")) continue;
    for (const m of src.matchAll(/<Button(?=[\s/>])/g)) {
      const tag = readTag(src, m.index);
      const color = tag.match(/\bcolor=(?:"([^"]*)"|\{([^}]*)\})/);
      const variant = tag.match(/\bvariant=(?:"([^"]*)"|\{([^}]*)\})/);
      if (!color && !variant) continue;
      const c = color ? (color[1] ?? "{expr}") : "(none)";
      const v = variant ? (variant[1] ?? "{expr}") : "(none)";
      const key = `${c}|${v}`;
      button[key] = (button[key] || 0) + 1;
    }
    for (const m of src.matchAll(/<Chip(?=[\s/>])/g)) {
      const tag = readTag(src, m.index);
      const color = tag.match(/\bcolor=(?:"([^"]*)"|\{([^}]*)\})/);
      const variant = tag.match(/\bvariant=(?:"([^"]*)"|\{([^}]*)\})/);
      if (!color && !variant) continue;
      const c = color ? (color[1] ?? "{expr}") : "(none)";
      const v = variant ? (variant[1] ?? "{expr}") : "(none)";
      const key = `${c}|${v}`;
      chip[key] = (chip[key] || 0) + 1;
    }
  }
  const toRows = (map, pairs, colorMap) =>
    Object.entries(map)
      .map(([key, count]) => {
        const [c, v] = key.split("|");
        if (c === "{expr}" || v === "{expr}") return { key, count, to: "dynamic", status: "dynamic" };
        const vv = v === "(none)" ? "solid" : v;
        const cc = c === "(none)" ? "default" : c;
        const mapped = pairs[`${cc}|${vv}`];
        if (mapped) return { key, count, to: mapped, status: "mapped" };
        if (colorMap && colorMap[cc]) return { key, count, to: `${pairs[vv] || vv} + ${colorMap[cc]}`, status: "mapped" };
        return { key, count, to: "?", status: "decide" };
      })
      .sort((a, b) => b.count - a.count);

  return { button: toRows(button, BUTTON_PAIRS), chip: toRows(chip, CHIP_PAIRS, CHIP_COLORS) };
}

/* --------------------------------- main --------------------------------- */

/** v2 component -> v3 styles directory. */
const V3_ALIAS = {
  progress: "progress-bar", "circular-progress": "progress-circle", divider: "separator",
  autocomplete: "combo-box", "number-input": "number-field", "date-input": "date-field",
  "time-input": "time-field", listbox: "list-box",
};
/** v2 components with no v3 equivalent (replace with HTML). */
const V3_REMOVED = new Set(["snippet", "user", "code", "spacer", "navbar", "image", "ripple"]);

const V3_SNAPSHOT = join(TOOL, "v3-variants.json");
const v3dir = arg("v3-dir");
let v3;
if (v3dir) {
  v3 = extractV3(v3dir);
  writeFileSync(V3_SNAPSHOT, JSON.stringify(v3, null, 2));
} else if (existsSync(V3_SNAPSHOT)) {
  v3 = JSON.parse(readFileSync(V3_SNAPSHOT, "utf8"));
} else {
  console.error("no v3 variant snapshot and no --v3-dir; run with --v3-dir <node_modules/@heroui/styles>");
  process.exit(1);
}

const v2 = extractV2();
const usage = collectUsage(v2);

const rows = [];
for (const [comp, dims] of Object.entries(usage)) {
  if (!v2[comp]) continue;
  for (const [dim, vals] of Object.entries(dims)) {
    for (const [value, count] of Object.entries(vals)) {
      const { to, status } = classify(comp, dim, value, v3);
      rows.push({ comp, dim, value, count, to, status, v2Values: v2[comp][dim] || [], v3Values: v3[comp]?.[dim] || [] });
    }
  }
}
rows.sort((a, b) => b.count - a.count || a.comp.localeCompare(b.comp));

const combos = collectCombos();

const totals = {
  components: new Set(rows.map((r) => r.comp)).size,
  tuples: rows.length,
  sites: rows.reduce((n, r) => n + r.count, 0),
  byStatus: rows.reduce((acc, r) => ({ ...acc, [r.status]: (acc[r.status] || 0) + r.count }), {}),
};

writeFileSync(join(TOOL, "variants.json"), JSON.stringify({ generatedAt: new Date().toISOString(), totals, combos, rows }, null, 2));

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
const STATUS_LABEL = { removed: "removed", same: "same", rename: "rename", moved: "moved to variant", drop: "dropped → Tailwind", decide: "DECIDE", unknown: "removed", dynamic: "dynamic" };

const html = `<!doctype html><meta charset="utf-8"><title>variant matrix</title>
<style>
:root{color-scheme:dark}
body{margin:0;background:#0a0a0b;color:#ececf0;font:13px/1.5 ui-sans-serif,system-ui,sans-serif;padding:22px 24px}
h1{font-size:15px;margin:0 0 2px}p.sub{color:#8a8a93;margin:0 0 16px;font-size:12px}
.stats{display:flex;gap:10px;margin-bottom:18px;flex-wrap:wrap}
.s{background:#131316;border:1px solid #26262b;border-radius:9px;padding:9px 14px}
.s i{display:block;font-style:normal;font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:#8a8a93}
.s b{font-size:17px;font-variant-numeric:tabular-nums}
.bar{display:flex;gap:6px;margin-bottom:14px}
.bar button{background:#131316;border:1px solid #26262b;color:#8a8a93;padding:5px 11px;border-radius:7px;cursor:pointer;font-size:11.5px}
.bar button[aria-pressed=true]{color:#fff;border-color:#7c9cff;background:#7c9cff1f}
table{border-collapse:collapse;width:100%;font-size:12px}
th{text-align:left;font-weight:500;font-size:9.5px;text-transform:uppercase;letter-spacing:.08em;color:#8a8a93;padding:6px 8px;border-bottom:1px solid #26262b;position:sticky;top:0;background:#0a0a0b}
td{padding:5px 8px;border-bottom:1px solid #1a1a1e;vertical-align:top}
td.n{text-align:right;font-family:ui-monospace,monospace;font-variant-numeric:tabular-nums}
code{font-family:ui-monospace,monospace;font-size:11.5px;background:#1b1b20;padding:1px 5px;border-radius:4px}
.tag{font-size:9.5px;padding:2px 6px;border-radius:99px;text-transform:uppercase;letter-spacing:.05em;white-space:nowrap}
.same{background:#3fb95022;color:#3fb950}.rename{background:#7c9cff22;color:#7c9cff}
.moved{background:#e0a03a22;color:#e0a03a}.drop{background:#8a8a9322;color:#8a8a93}
.decide{background:#ff5c5c22;color:#ff5c5c}.removed{background:#b06cff22;color:#b06cff}.unknown{background:#b06cff22;color:#b06cff}.dynamic{background:#e0a03a22;color:#e0a03a}.mapped{background:#3fb95022;color:#3fb950}
tr:hover td{background:#ffffff06}
.comp{font-weight:600}
.dim{color:#8a8a93}
</style>
<h1>HeroUI v2 → v3 variant matrix</h1>
<p class="sub">v2 vocabulary read from <code>@heroui/theme</code>; v3 from <code>@heroui/styles</code> type definitions. Counts are your actual usage.</p>
<div class="stats">
  <div class="s"><i>components</i><b>${totals.components}</b></div>
  <div class="s"><i>distinct tuples</i><b>${totals.tuples}</b></div>
  <div class="s"><i>sites</i><b>${totals.sites}</b></div>
  <div class="s"><i>needs decision</i><b style="color:#ff5c5c">${totals.byStatus.decide || 0}</b></div>
  <div class="s"><i>folds into variant</i><b style="color:#e0a03a">${totals.byStatus.moved || 0}</b></div>
</div>
<div class="bar">
  <button data-f="all" aria-pressed="true">all</button>
  <button data-f="decide" aria-pressed="false">needs decision</button>
  <button data-f="moved" aria-pressed="false">moved/dropped</button>
</div>
<table><thead><tr><th>component</th><th>prop</th><th>v2 value</th><th class="n">uses</th><th>v3</th><th>status</th></tr></thead>
<tbody>
${rows.map((r) => `<tr data-s="${r.status}"><td class="comp">${esc(r.comp)}</td><td class="dim">${esc(r.dim)}</td><td><code>${esc(r.value)}</code></td><td class="n">${r.count}</td><td><code>${esc(r.to)}</code></td><td><span class="tag ${r.status}">${STATUS_LABEL[r.status]}</span></td></tr>`).join("")}
</tbody></table>
<h1 style="margin-top:30px">Joint colour × variant (Button / Chip)</h1>
<p class="sub">These are the combos your code actually uses. v3 folds colour INTO variant, so pairs must be mapped together — per-prop mapping is wrong.</p>
<table><thead><tr><th>component</th><th>v2 combo</th><th class="n">uses</th><th>v3</th><th>status</th></tr></thead><tbody>
${["button", "chip"].map((c) => combos[c].map((r) => `<tr data-s="${r.status}"><td class="comp">${c}</td><td><code>${esc(r.key)}</code></td><td class="n">${r.count}</td><td><code>${esc(r.to)}</code></td><td><span class="tag ${r.status}">${STATUS_LABEL[r.status] || r.status}</span></td></tr>`).join("")).join("")}
</tbody></table>
<script>
let f='all';
const apply=()=>document.querySelectorAll('tbody tr').forEach(t=>t.style.display=(f==='all'||t.dataset.s===f)?'':'none');
document.querySelectorAll('[data-f]').forEach(b=>b.onclick=()=>{
  f=b.dataset.f;document.querySelectorAll('[data-f]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));apply();
});
</script>`;

writeFileSync(join(TOOL, "variants-report.html"), html);

console.log(`\n  ${totals.components} components · ${totals.tuples} distinct (prop,value) tuples · ${totals.sites} sites`);
console.log(`  status: ${Object.entries(totals.byStatus).map(([k, v]) => `${k} ${v}`).join(" · ")}`);
console.log(`\n  needs decision:`);
for (const r of rows.filter((r) => r.status === "decide" || r.status === "unknown").slice(0, 15))
  console.log(`    ${String(r.count).padStart(3)}x  ${r.comp}.${r.dim}="${r.value}"  ->  ${r.to}`);
console.log(`\n  button combos (top):`);
for (const r of combos.button.slice(0, 6)) console.log(`    ${String(r.count).padStart(4)}x  color/variant ${r.key.padEnd(22)} -> ${r.to}`);
console.log(`\n  wrote variants-report.html, variants.json`);
