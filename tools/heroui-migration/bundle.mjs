#!/usr/bin/env node
/**
 * Measures what the migration actually ships: per-route JS, chunk uniqueness,
 * duplicate bytes across routes, and which packages survive into the bundle.
 *
 * Tree shaking is not a vibe — it's "how many bytes of Heroui/framer-motion are
 * still in .next/static". This reads the real build output, not package.json.
 *
 *   # on the v2 branch, after `pnpm -C apps/web build`
 *   node tools/heroui-migration/bundle.mjs --snapshot v2
 *
 *   # after the v3 switch + build
 *   node tools/heroui-migration/bundle.mjs --snapshot v3
 *   node tools/heroui-migration/bundle.mjs --compare v2 v3
 *
 *   # no build needed: static install-graph measurement
 *   node tools/heroui-migration/bundle.mjs --deps
 */
import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const argv = process.argv.slice(2);
const arg = (n, d = null) => {
  const i = argv.indexOf(`--${n}`);
  return i === -1 ? d : argv[i + 1];
};
const ROOT = process.cwd();
const NEXT = join(ROOT, "apps/web/.next");
const OUT_DIR = join(ROOT, "tools/heroui-migration");

const kb = (n) => (n / 1024).toFixed(1);
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");

/** Package markers to detect inside emitted chunks. */
const MARKERS = {
  "framer-motion": ["framer-motion", "motion-dom", "motion-utils"],
  "heroui-v3": ["@heroui/styles", "heroui/styles"],
  "react-aria": ["react-aria", "@react-aria"],
  "tailwind": ["@heroui/theme"],
};

function walk(dir, out = []) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.(js|mjs|css)$/.test(e.name)) out.push(p);
  }
  return out;
}

function readManifests() {
  const app = join(NEXT, "app-build-manifest.json");
  const build = join(NEXT, "build-manifest.json");
  const pages = {};
  if (existsSync(app)) {
    const m = JSON.parse(readFileSync(app, "utf8"));
    for (const [route, files] of Object.entries(m.pages || {})) pages[route] = files;
  }
  if (!Object.keys(pages).length && existsSync(build)) {
    const m = JSON.parse(readFileSync(build, "utf8"));
    for (const [route, files] of Object.entries(m.pages || {})) pages[route] = files;
  }
  return pages;
}

function sizeOf(rel) {
  const p = join(NEXT, rel);
  return existsSync(p) ? statSync(p).size : 0;
}

async function snapshot(label) {
  const base = arg("base", process.env.WEB_BASE_URL || "http://localhost:3000");
  const routesFile = join(OUT_DIR, "routes.json");
  const routes = JSON.parse(readFileSync(routesFile, "utf8"));

  const sizes = new Map(); // chunk url -> bytes
  const perRoute = [];
  const markers = {};
  for (const [pkg, needles] of Object.entries(MARKERS)) markers[pkg] = false;

  const cssSizes = new Map();
  const fetchBytes = async (url, into = sizes) => {
    if (into.has(url)) return into.get(url);
    const r = await fetch(base + url);
    const buf = await r.arrayBuffer();
    into.set(url, buf.byteLength);
    return buf.byteLength;
  };

  for (const route of routes) {
    try {
      const r = await fetch(base + route);
      if (!r.ok) { perRoute.push({ route, bytes: 0, chunks: 0, error: r.status }); continue; }
      const html = await r.text();
      const srcs = [...html.matchAll(/<script[^>]+src="(\/_next\/[^"]+\.js)"/g)].map((m) => m[1]);
      const cssHrefs = [...html.matchAll(/<link[^>]+href="(\/_next\/[^"]+\.css)"/g)].map((m) => m[1]);
      let cssTotal = 0;
      for (const u of new Set(cssHrefs)) { try { cssTotal += await fetchBytes(u, cssSizes); } catch {} }
      const uniq = [...new Set(srcs)];
      let total = 0;
      for (const u of uniq) {
        try { total += await fetchBytes(u); } catch {}
      }
      // marker scan over the JS this route actually loads
      for (const u of uniq) {
        try {
          const txt = await (await fetch(base + u)).text();
          for (const [pkg, needles] of Object.entries(MARKERS)) {
            if (!markers[pkg] && needles.some((n) => txt.includes(n))) markers[pkg] = true;
          }
        } catch {}
      }
      perRoute.push({ route, bytes: total, cssBytes: cssTotal, chunks: uniq.length });
    } catch (e) {
      perRoute.push({ route, bytes: 0, chunks: 0, error: String(e.message).slice(0, 60) });
    }
  }

  const uniqueBytes = [...sizes.values()].reduce((n, v) => n + v, 0);
  const sumBytes = perRoute.reduce((n, r) => n + r.bytes, 0);
  const data = {
    label,
    base,
    capturedAt: new Date().toISOString(),
    routes: perRoute.sort((a, b) => b.bytes - a.bytes),
    totals: {
      routes: perRoute.length,
      uniqueChunks: sizes.size,
      uniqueJsBytes: uniqueBytes,
      sumRouteJsBytes: sumBytes,
      duplicationFactor: uniqueBytes ? sumBytes / uniqueBytes : 0,
      cssBytes: perRoute.reduce((n, r) => n + (r.cssBytes || 0), 0),
      maxCssBytes: Math.max(0, ...perRoute.map((r) => r.cssBytes || 0)),
    },
    packages: markers,
    largestChunks: [...sizes.entries()]
      .map(([file, bytes]) => ({ file, bytes }))
      .sort((a, b) => b.bytes - a.bytes)
      .slice(0, 20),
  };

  const p = join(OUT_DIR, `bundle-${label}.json`);
  writeFileSync(p, JSON.stringify(data, null, 2));
  console.log(`\n  ${label}: ${perRoute.length} routes · ${sizes.size} unique chunks · ${kb(uniqueBytes)} kB unique JS (${kb(sumBytes)} kB summed)`);
  console.log(`  packages loaded client-side: ${Object.entries(markers).filter(([, v]) => v).map(([k]) => k).join(", ") || "none detected"}`);
  console.log(`\n  heaviest routes:`);
  for (const r of data.routes.slice(0, 8)) console.log(`    ${kb(r.bytes).padStart(9)} kB  ${r.route}`);
  console.log(`\n  wrote ${p}`);
}

function compare(a, b) {
  const pa = join(OUT_DIR, `bundle-${a}.json`);
  const pb = join(OUT_DIR, `bundle-${b}.json`);
  for (const p of [pa, pb]) {
    if (!existsSync(p)) {
      console.error(`missing ${p}`);
      process.exit(1);
    }
  }
  const A = JSON.parse(readFileSync(pa, "utf8"));
  const B = JSON.parse(readFileSync(pb, "utf8"));
  const mb = new Map(B.routes.map((r) => [r.route, r]));
  const rows = A.routes.map((ra) => {
    const rb = mb.get(ra.route) || { bytes: 0, cssBytes: 0 };
    return { route: ra.route, before: ra.bytes, after: rb.bytes, delta: rb.bytes - ra.bytes, cssDelta: rb.cssBytes - ra.cssBytes };
  });
  rows.sort((x, y) => y.delta - x.delta);

  const dUnique = B.totals.uniqueJsBytes - A.totals.uniqueJsBytes;
  const pct = (n, d) => (d ? ((n / d) * 100).toFixed(1) + "%" : "—");
  const sign = (n) => (n > 0 ? "+" : "") + kb(n);
  const cls = (n) => (n > 0 ? "up" : n < 0 ? "down" : "");

  const html = `<!doctype html><meta charset="utf-8"><title>bundle ${esc(a)} → ${esc(b)}</title>
<style>
:root{color-scheme:dark}
body{margin:0;background:#0a0a0b;color:#ececf0;font:13px/1.5 ui-sans-serif,system-ui,sans-serif;padding:24px}
h1{font-size:15px;margin:0 0 4px}
p.sub{color:#8a8a93;margin:0 0 20px;font-size:12px}
.cards{display:flex;gap:12px;margin-bottom:22px;flex-wrap:wrap}
.c{background:#131316;border:1px solid #26262b;border-radius:10px;padding:12px 16px;min-width:150px}
.c i{display:block;font-style:normal;font-size:9.5px;text-transform:uppercase;letter-spacing:.08em;color:#8a8a93;margin-bottom:3px}
.c b{font-size:19px;font-variant-numeric:tabular-nums}
table{border-collapse:collapse;width:100%;font-size:12px}
th{text-align:left;color:#8a8a93;font-weight:500;font-size:10px;text-transform:uppercase;letter-spacing:.07em;padding:6px 8px;border-bottom:1px solid #26262b}
td{padding:5px 8px;border-bottom:1px solid #1b1b1f;font-variant-numeric:tabular-nums}
td.n{text-align:right;font-family:ui-monospace,monospace}
.up{color:#ff5c5c}.down{color:#3fb950}
.bar{height:5px;background:#1b1b1f;border-radius:3px;overflow:hidden;width:120px}
.bar span{display:block;height:100%;background:#7c9cff}
</style>
<h1>bundle ${esc(a)} → ${esc(b)}</h1>
<p class="sub">unique client JS ${kb(A.totals.uniqueJsBytes)} kB → ${kb(B.totals.uniqueJsBytes)} kB (${sign(dUnique)} kB, ${pct(dUnique, A.totals.uniqueJsBytes)})</p>
<div class="cards">
  <div class="c"><i>unique js</i><b>${kb(B.totals.uniqueJsBytes)}<small> kB</small></b></div>
  <div class="c"><i>delta</i><b class="${cls(dUnique)}">${sign(dUnique)}<small> kB</small></b></div>
  <div class="c"><i>chunks</i><b>${B.totals.uniqueChunks}</b></div>
  <div class="c"><i>css</i><b>${kb(B.totals.cssBytes)}<small> kB</small></b></div>
  <div class="c"><i>framer-motion</i><b>${B.packages["framer-motion"] ? "present" : "gone"}</b></div>
</div>
<table><thead><tr><th>route</th><th class="n">${esc(a)}</th><th class="n">${esc(b)}</th><th class="n">delta</th><th></th></tr></thead><tbody>
${rows.map((r) => `<tr><td>${esc(r.route)}</td><td class="n">${kb(r.before)}</td><td class="n">${kb(r.after)}</td><td class="n ${cls(r.delta)}">${sign(r.delta)}</td><td><div class="bar"><span style="width:${Math.min(100, (Math.abs(r.delta) / (Math.max(...rows.map((x) => Math.abs(x.delta))) || 1)) * 100)}%"></span></div></td></tr>`).join("")}
</tbody></table>`;

  writeFileSync(join(OUT_DIR, "bundle-report.html"), html);
  console.log(`\n  unique JS ${kb(A.totals.uniqueJsBytes)} kB -> ${kb(B.totals.uniqueJsBytes)} kB (${sign(dUnique)} kB)`);
  console.log(`  framer-motion: ${A.packages["framer-motion"] ? "present" : "absent"} -> ${B.packages["framer-motion"] ? "present" : "absent"}`);
  console.log(`  wrote tools/heroui-migration/bundle-report.html`);
  const worst = rows.slice(0, 6);
  console.log("\n  biggest regressions:");
  for (const r of worst) if (r.delta > 0) console.log(`    ${sign(r.delta).padStart(10)} kB  ${r.route}`);
}

/** Static measurement: what the dependency graph says about tree-shaking headroom. */
function deps() {
  const dirs = [join(ROOT, "apps/web/node_modules"), join(ROOT, "node_modules")];
  const dirSize = (d) => {
    let n = 0;
    for (const e of readdirSync(d, { withFileTypes: true })) {
      const q = join(d, e.name);
      try {
        if (e.isDirectory()) n += dirSize(q);
        else n += statSync(q).size;
      } catch {}
    }
    return n;
  };
  const scan = (base) => {
    const scope = join(base, "@heroui");
    if (!existsSync(scope)) return [];
    return readdirSync(scope).map((name) => ({ name: `@heroui/${name}`, bytes: dirSize(join(scope, name)) }));
  };
  const found = [...scan(dirs[0]), ...scan(dirs[1])];
  const pkg = JSON.parse(readFileSync(join(ROOT, "apps/web/package.json"), "utf8"));
  const declared = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies }).filter((d) => d.startsWith("@heroui/"));
  const framer = pkg.dependencies?.["framer-motion"] ? "declared" : "absent";
  const total = found.reduce((n, f) => n + f.bytes, 0);
  console.log(`\n  ${declared.length} @heroui/* packages declared, ${framer} framer-motion`);
  console.log(`  installed @heroui/* on disk: ${kb(total)} kB`);
  console.log(`  v3 collapses these to 2 (@heroui/react + @heroui/styles)`);
  console.log(`\n  largest:`);
  for (const f of found.sort((a, b) => b.bytes - a.bytes).slice(0, 10)) console.log(`    ${kb(f.bytes).padStart(9)} kB  ${f.name}`);
}

const snap = arg("snapshot");
const cmp = argv.includes("--compare");
const d = argv.includes("--deps");
if (d) deps();
else if (cmp) {
  const i = argv.indexOf("--compare");
  compare(argv[i + 1], argv[i + 2]);
} else if (snap) { snapshot(snap).catch((e) => { console.error(e); process.exit(1); }); }
else {
  console.log("usage: bundle.mjs --snapshot <label> | --compare <a> <b> | --deps");
}
