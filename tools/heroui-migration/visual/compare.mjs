#!/usr/bin/env node
/**
 * Visual diff for a HeroUI migration. The unit of review is a *changed region*,
 * not a percentage: every cluster of changed pixels becomes a crop of before and
 * after, so you look at what actually moved.
 *
 *   node tools/heroui-migration/visual/compare.mjs --a v2 --b v3
 *
 * Output:
 *   tools/heroui-migration/shots/diff/<route>-r<k>-{before,after}.png
 *   tools/heroui-migration/shots/diff/<route>-overlay.png
 *   tools/heroui-migration/visual-report.html
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { PNG } from "pngjs";
import pixelmatch from "pixelmatch";

const argv = process.argv.slice(2);
const arg = (n, d = null) => {
  const i = argv.indexOf(`--${n}`);
  return i === -1 ? d : argv[i + 1];
};

const A = arg("a");
const B = arg("b");
if (!A || !B) {
  console.error("usage: compare.mjs --a <label> --b <label>");
  process.exit(1);
}
const PIXEL_TOL = Number(arg("threshold", 0.1)); // pixelmatch colour tolerance
const MIN_CELLS = Number(arg("min-cells", 6)); // ignore specks smaller than this
const MAX_REGIONS = Number(arg("max-regions", 12)); // per route
const PAD = Number(arg("pad", 24)); // crop padding, px
const ROOT = join(process.cwd(), "tools/heroui-migration");
const DIFF_DIR = join(ROOT, "shots", "diff");

const manifestOf = (label) => {
  const p = join(ROOT, "shots", label, "manifest.json");
  if (!existsSync(p)) {
    console.error(`missing ${p} — run shoot.mjs --label ${label} first`);
    process.exit(1);
  }
  return JSON.parse(readFileSync(p, "utf8"));
};
const MA = manifestOf(A);
const MB = manifestOf(B);

const readPng = (p) => PNG.sync.read(readFileSync(p));
const slugOf = (route) => (route === "/" ? "_root" : route.replace(/^\//, "").replace(/\//g, "_"));

function align(a, b) {
  const w = Math.max(a.width, b.width);
  const h = Math.max(a.height, b.height);
  const pad = (img) => {
    if (img.width === w && img.height === h) return img;
    const out = new PNG({ width: w, height: h });
    out.data.fill(255);
    PNG.bitblt(img, out, 0, 0, Math.min(img.width, w), Math.min(img.height, h), 0, 0);
    return out;
  };
  return { a: pad(a), b: pad(b), w, h };
}

/** Cluster changed pixels into bounding boxes via coarse-grid flood fill. */
function findRegions(mask, W, H, step = 6) {
  const gw = Math.ceil(W / step);
  const gh = Math.ceil(H / step);
  const grid = new Uint8Array(gw * gh);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      if (mask[y * W + x]) grid[Math.floor(y / step) * gw + Math.floor(x / step)] = 1;
    }
  }
  const seen = new Uint8Array(gw * gh);
  const boxes = [];
  for (let i = 0; i < grid.length; i++) {
    if (!grid[i] || seen[i]) continue;
    const stack = [i];
    seen[i] = 1;
    let minx = 1e9, miny = 1e9, maxx = -1, maxy = -1, cells = 0;
    while (stack.length) {
      const j = stack.pop();
      const gx = j % gw;
      const gy = Math.floor(j / gw);
      cells++;
      if (gx < minx) minx = gx;
      if (gy < miny) miny = gy;
      if (gx > maxx) maxx = gx;
      if (gy > maxy) maxy = gy;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nx = gx + dx, ny = gy + dy;
        if (nx < 0 || ny < 0 || nx >= gw || ny >= gh) continue;
        const k = ny * gw + nx;
        if (grid[k] && !seen[k]) { seen[k] = 1; stack.push(k); }
      }
    }
    boxes.push({
      x: minx * step, y: miny * step,
      w: Math.min((maxx - minx + 1) * step, W - minx * step),
      h: Math.min((maxy - miny + 1) * step, H - miny * step),
      cells,
    });
  }
  // merge boxes that nearly touch (text lines, icon+label pairs)
  const merged = [];
  for (const b of boxes.sort((p, q) => q.cells - p.cells)) {
    const hit = merged.find(
      (m) => b.x < m.x + m.w + PAD && b.x + b.w + PAD > m.x && b.y < m.y + m.h + PAD && b.y + b.h + PAD > m.y,
    );
    if (hit) {
      const nx = Math.min(hit.x, b.x), ny = Math.min(hit.y, b.y);
      hit.w = Math.max(hit.x + hit.w, b.x + b.w) - nx;
      hit.h = Math.max(hit.y + hit.h, b.y + b.h) - ny;
      hit.x = nx; hit.y = ny; hit.cells += b.cells;
    } else merged.push({ ...b });
  }
  return merged
    .filter((b) => b.cells >= MIN_CELLS)
    .sort((p, q) => q.cells - p.cells)
    .slice(0, MAX_REGIONS);
}

function crop(img, box) {
  const x = Math.max(0, box.x - PAD);
  const y = Math.max(0, box.y - PAD);
  const w = Math.min(img.width - x, box.w + PAD * 2);
  const h = Math.min(img.height - y, box.h + PAD * 2);
  const out = new PNG({ width: w, height: h });
  PNG.bitblt(img, out, x, y, w, h, 0, 0);
  return out;
}

const routesB = new Map(MB.routes.map((r) => [r.route, r]));
const rows = [];

for (const ra of MA.routes) {
  const rb = routesB.get(ra.route);
  const viewports = {};
  for (const vp of MA.viewports) {
    const relA = ra.shots?.[vp]?.path;
    const relB = rb?.shots?.[vp]?.path;
    if (!relA || !relB) {
      viewports[vp] = { missing: true, regions: [] };
      continue;
    }
    const pa = join(ROOT, relA);
    const pb = join(ROOT, relB);
    if (!existsSync(pa) || !existsSync(pb)) {
      viewports[vp] = { missing: true, regions: [] };
      continue;
    }
    const { a, b, w, h } = align(readPng(pa), readPng(pb));
    const dimg = new PNG({ width: w, height: h });
    const changed = pixelmatch(a.data, b.data, dimg.data, w, h, {
      threshold: PIXEL_TOL,
      includeAA: false,
      diffColor: [255, 0, 0],
    });

    // mask = pixels pixelmatch painted pure red (AA pixels are yellow, so excluded)
    const mask = new Uint8Array(w * h);
    for (let i = 0; i < w * h; i++) {
      const r = dimg.data[i * 4], g = dimg.data[i * 4 + 1], bl = dimg.data[i * 4 + 2];
      if (r === 255 && g === 0 && bl === 0) mask[i] = 1;
    }

    const boxes = findRegions(mask, w, h);
    mkdirSync(DIFF_DIR, { recursive: true });
    const slug = slugOf(ra.route);
    const regions = boxes.map((box, k) => {
      const before = `shots/diff/${slug}-r${k}-before.png`;
      const after = `shots/diff/${slug}-r${k}-after.png`;
      writeFileSync(join(ROOT, before), PNG.sync.write(crop(a, box)));
      writeFileSync(join(ROOT, after), PNG.sync.write(crop(b, box)));
      return {
        k,
        before,
        after,
        x: box.x, y: box.y, w: box.w, h: box.h,
        px: box.cells,
        // percent coords for overlaying boxes on the full-page shot
        left: (box.x / w) * 100, top: (box.y / h) * 100,
        width: (box.w / w) * 100, height: (box.h / h) * 100,
      };
    });

    viewports[vp] = {
      missing: false,
      regions,
      changedPx: changed,
      totalPx: w * h,
      page: { before: ra.shots[vp].path, after: rb.shots[vp].path, w, h },
    };
  }
  const all = Object.values(viewports).flatMap((v) => v.regions ?? []);
  rows.push({
    route: ra.route,
    regionCount: all.length,
    px: Object.values(viewports).reduce((n, v) => n + (v.changedPx ?? 0), 0),
    viewports,
  });
}

rows.sort((x, y) => y.px - x.px);
const changed = rows.filter((r) => r.regionCount > 0);
const identical = rows.filter((r) => r.regionCount === 0);

const report = {
  a: A,
  b: B,
  generatedAt: new Date().toISOString(),
  viewports: MA.viewports,
  stats: {
    routes: rows.length,
    changed: changed.length,
    identical: identical.length,
    regions: rows.reduce((n, r) => n + r.regionCount, 0),
  },
  rows,
};

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");

const html = `<!doctype html><meta charset="utf-8"><title>UI diff · ${esc(A)} → ${esc(B)}</title>
<style>
:root{color-scheme:dark;--bg:#0a0a0b;--panel:#131316;--line:#26262b;--fg:#ececf0;--dim:#8a8a93;--red:#ff5c5c;--accent:#7c9cff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.45 ui-sans-serif,system-ui,-apple-system,sans-serif}
header{position:sticky;top:0;z-index:30;background:#0a0a0bee;backdrop-filter:blur(14px);border-bottom:1px solid var(--line);padding:12px 20px;display:flex;align-items:center;gap:20px;flex-wrap:wrap}
h1{font-size:13.5px;margin:0;font-weight:650;letter-spacing:-.01em;white-space:nowrap}
h1 em{font-style:normal;color:var(--dim);font-weight:400}
.stats{display:flex;gap:20px;margin-left:auto}
.stat{display:flex;flex-direction:column;line-height:1.1}
.stat b{font-size:15px;font-variant-numeric:tabular-nums}
.stat i{font-style:normal;font-size:9.5px;color:var(--dim);text-transform:uppercase;letter-spacing:.08em}
.controls{display:flex;gap:7px;align-items:center}
input[type=search]{background:var(--panel);border:1px solid var(--line);color:var(--fg);padding:6px 10px;border-radius:7px;width:190px;outline:none;font-size:12px}
input[type=search]:focus{border-color:var(--accent)}
button.f{background:var(--panel);border:1px solid var(--line);color:var(--dim);padding:6px 10px;border-radius:7px;cursor:pointer;font-size:11.5px;white-space:nowrap}
button.f[aria-pressed=true]{color:var(--fg);border-color:var(--accent);background:#7c9cff1f}
main{padding:16px 20px 60px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden;cursor:zoom-in;transition:border-color .12s,transform .12s}
.card:hover{border-color:#3d3d46;transform:translateY(-1px)}
.media{position:relative;background:#0f0f11;border-bottom:1px solid var(--line)}
.pair{display:flex;flex-direction:column}
.pair figure{margin:0;position:relative;overflow:hidden;background:#fff;max-height:118px;display:flex;align-items:center;justify-content:center}
.pair figure img{width:100%;display:block}
.pair figure+figure{border-top:1px solid var(--line)}
.pair figcaption{position:absolute;top:4px;left:5px;font-size:8.5px;letter-spacing:.09em;text-transform:uppercase;background:#000c;color:#fff;padding:2px 5px;border-radius:4px}
.nreg{position:absolute;top:8px;right:8px;font:600 10.5px/1 ui-monospace,monospace;padding:4px 7px;border-radius:99px;background:#000d;color:var(--red);border:1px solid #ff5c5c55}
.meta{padding:9px 11px;display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:12px}
.meta b{font-weight:520;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.meta span{color:var(--dim);font-size:10px;font-family:ui-monospace,monospace;white-space:nowrap}
section.h{grid-column:1/-1;display:flex;align-items:center;gap:10px;margin:22px 0 0;color:var(--dim);font-size:10.5px;text-transform:uppercase;letter-spacing:.09em}
section.h:after{content:"";flex:1;height:1px;background:var(--line)}
/* lightbox */
.lb{position:fixed;inset:0;background:#060608;z-index:100;display:none;flex-direction:column}
.lb[open]{display:flex}
.lb .top{display:flex;align-items:center;gap:14px;padding:10px 16px;border-bottom:1px solid var(--line)}
.lb h2{font-size:12.5px;margin:0;font-weight:600}
.seg{display:flex;gap:3px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:3px}
.seg button{background:none;border:0;color:var(--dim);padding:4px 9px;border-radius:6px;cursor:pointer;font-size:11px}
.seg button[aria-pressed=true]{background:#2a2a31;color:var(--fg)}
.lb .body{flex:1;display:flex;min-height:0}
.stage{flex:1;position:relative;overflow:auto;padding:16px;display:flex;justify-content:center;align-items:flex-start}
.shot{position:relative;line-height:0;box-shadow:0 0 0 1px var(--line)}
.shot img{max-width:100%;display:block}
.shot .af{position:absolute;inset:0;clip-path:inset(0 0 0 50%)}
.shot .af img{width:100%;height:100%;object-fit:cover;object-position:top left}
.boxes{position:absolute;inset:0;pointer-events:none}
.boxes i{position:absolute;border:1px solid var(--red);background:#ff5c5c14;box-shadow:0 0 0 1px #ff5c5c33}
.strip{width:250px;flex:0 0 250px;border-left:1px solid var(--line);overflow:auto;padding:10px}
.strip h3{font-size:9.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);margin:0 0 8px;font-weight:500}
.rg{border:1px solid var(--line);border-radius:8px;margin-bottom:8px;overflow:hidden;cursor:pointer;background:#0f0f11}
.rg[aria-pressed=true]{border-color:var(--accent)}
.rg .imgs img{width:100%;display:block;background:#fff}
.rg .imgs img+img{border-top:1px solid var(--line)}
.rg p{margin:0;padding:4px 6px;font:10px/1.3 ui-monospace,monospace;color:var(--dim);display:flex;justify-content:space-between}
.pane2{display:flex;gap:10px;align-items:flex-start}
.pane2 figure{margin:0;background:#fff;box-shadow:0 0 0 1px var(--line)}
.pane2 img{display:block;max-width:46vw}
.pane2 figcaption{font:9.5px/1 ui-monospace,monospace;color:var(--dim);padding:4px 0;text-transform:uppercase;letter-spacing:.08em}
.zoom{position:absolute;right:14px;bottom:14px;display:flex;gap:4px;background:#000c;border:1px solid var(--line);border-radius:8px;padding:3px}
.zoom button{background:none;border:0;color:var(--dim);padding:4px 8px;cursor:pointer;font-size:12px}
.zoom button:hover{color:var(--fg)}
</style>
<header>
  <h1>UI diff <em>${esc(A)} → ${esc(B)}</em></h1>
  <div class="stats">
    <div class="stat"><b>${report.stats.routes}</b><i>routes</i></div>
    <div class="stat"><b style="color:var(--red)">${report.stats.changed}</b><i>changed</i></div>
    <div class="stat"><b>${report.stats.regions}</b><i>regions</i></div>
    <div class="stat"><b style="color:#3fb950">${report.stats.identical}</b><i>identical</i></div>
  </div>
  <div class="controls">
    <input type="search" placeholder="filter routes…" id="q">
    <button class="f" data-filter="changed" aria-pressed="true">changed only</button>
  </div>
</header>
<main><div class="grid" id="grid"></div></main>
<div class="lb" id="lb">
  <div class="top">
    <h2 id="lbt"></h2>
    <div class="seg" id="seg">
      <button data-mode="slider" aria-pressed="true">slider</button>
      <button data-mode="diff" aria-pressed="false">overlay</button>
      <button data-mode="before" aria-pressed="false">before</button>
      <button data-mode="after" aria-pressed="false">after</button>
    </div>
    <div class="controls" style="margin-left:auto">
      <span id="lbn" class="f" style="cursor:default"></span>
      <span class="f" style="cursor:default;border-color:#333">← → route · D diff · S slider</span>
      <button class="f" id="lbx">close</button>
    </div>
  </div>
  <div class="body">
    <div class="stage"><div id="stageInner"></div></div>
    <aside class="strip" id="strip"></aside>
  </div>
</div>
<script>
const DATA = ${JSON.stringify(report).replace(/</g, "\\u003c")};
const grid = document.getElementById('grid');
const lb = document.getElementById('lb');

function card(row){
  const vp = row.viewports.desktop && !row.viewports.desktop.missing ? 'desktop' : (row.viewports.mobile && !row.viewports.mobile.missing ? 'mobile' : null);
  const v = vp ? row.viewports[vp] : null;
  const r0 = v && v.regions[0];
  const el = document.createElement('article');
  el.className = 'card'; el.tabIndex = 0;
  el.dataset.route = row.route;
  el.dataset.changed = row.regionCount > 0 ? '1' : '0';
  el.innerHTML = r0
    ? '<div class="media"><div class="pair">' +
        '<figure><img src="' + r0.before + '" loading="eager" alt=""><figcaption>before</figcaption></figure>' +
        '<figure><img src="' + r0.after + '" loading="eager" alt=""><figcaption>after</figcaption></figure>' +
      '</div><span class="nreg">' + v.regions.length + ' region' + (v.regions.length===1?'':'s') + '</span></div>'
    : '<div class="media" style="height:120px;display:grid;place-items:center;color:var(--dim);font-size:11px">identical</div>';
  el.innerHTML += '<div class="meta"><b>' + row.route + '</b><span>' + (row.regionCount? (row.px/1000).toFixed(1)+'k px':'—') + '</span></div>';
  el.onclick = () => openLb(row);
  el.onkeydown = (e) => { if (e.key === 'Enter') openLb(row); };
  return el;
}
function render(){
  grid.innerHTML = '';
  const changed = DATA.rows.filter(r => r.regionCount > 0);
  const same = DATA.rows.filter(r => r.regionCount === 0);
  const h1 = document.createElement('section'); h1.className='h'; h1.textContent = 'Changed · ' + changed.length; grid.appendChild(h1);
  changed.forEach(r => grid.appendChild(card(r)));
  const h2 = document.createElement('section'); h2.className='h'; h2.textContent = 'Identical · ' + same.length; grid.appendChild(h2);
  same.forEach(r => grid.appendChild(card(r)));
}
render();

let cur = null, curVp = 'desktop', mode = 'slider', zoom = 1;
function openLb(row){
  cur = row; curVp = row.viewports.desktop && !row.viewports.desktop.missing ? 'desktop' : 'mobile';
  document.getElementById('lbt').textContent = row.route;
  lb.setAttribute('open','');
  renderStrip(); setMode('slider'); draw();
}
function curData(){ return cur.viewports[curVp] || cur.viewports.desktop || cur.viewports.mobile; }
function renderStrip(){
  const d = curData();
  const strip = document.getElementById('strip');
  document.getElementById('lbn').textContent = cur.regionCount + ' regions';
  strip.innerHTML = '<h3>changed regions</h3>';
  (d.regions || []).forEach(r => {
    const el = document.createElement('div');
    el.className = 'rg'; el.tabIndex = 0;
    el.innerHTML = '<div class="imgs"><img src="'+r.before+'" alt=""><img src="'+r.after+'" alt=""></div>' +
      '<p><span>#'+(r.k+1)+'</span><span>'+r.w+'×'+r.h+'</span></p>';
    el.onclick = () => { document.querySelectorAll('.rg').forEach(x=>x.setAttribute('aria-pressed','false')); el.setAttribute('aria-pressed','true'); drawRegion(r); };
    strip.appendChild(el);
  });
}
function draw(){
  const d = curData();
  if(d.missing || !d.page){ document.getElementById('stageInner').textContent = 'no screenshot for this viewport'; return; }
  const p = d.page;
  document.getElementById('lbn').textContent = (d.regions||[]).length + ' region' + ((d.regions||[]).length===1?'':'s') + ' · ' + curVp;
  let inner = '';
  if(mode === 'slider'){
    inner = '<div class="shot" style="width:'+p.w*zoom+'px"><img src="'+p.before+'"><div class="af"><img src="'+p.after+'"></div><div class="boxes">' +
      d.regions.map(r=>'<i style="left:'+r.left+'%;top:'+r.top+'%;width:'+r.width+'%;height:'+r.height+'%"></i>').join('') + '</div></div>' +
      '<input type="range" min="0" max="100" value="50" id="sl" style="position:fixed;left:50%;bottom:22px;transform:translateX(-50%);width:360px;z-index:5">';
  } else if(mode === 'diff'){
    inner = '<div class="shot" style="width:'+p.w*zoom+'px"><img src="'+p.after+'"><div class="boxes">' +
      d.regions.map(r=>'<i style="left:'+r.left+'%;top:'+r.top+'%;width:'+r.width+'%;height:'+r.height+'%"></i>').join('') + '</div></div>';
  } else {
    inner = '<div class="shot" style="width:'+p.w*zoom+'px"><img src="'+(mode==='before'?p.before:p.after)+'"></div>';
  }
  document.getElementById('stageInner').innerHTML = inner +
    '<div class="zoom"><button data-z="-1">−</button><button data-z="1">+</button><button data-z="0">1:1</button></div>';
  const sl = document.getElementById('sl');
  if(sl) sl.oninput = e => {
    const af = document.querySelector('.shot .af');
    if(af) af.style.clipPath = 'inset(0 0 0 ' + e.target.value + '%)';
  };
  document.querySelectorAll('[data-z]').forEach(b => b.onclick = () => {
    const z = Number(b.dataset.z);
    zoom = z === 0 ? 1 : Math.max(0.25, Math.min(4, zoom + z * 0.25));
    if(mode === 'slider' || mode === 'diff') draw(); else draw();
  });
}
function drawRegion(r){
  document.getElementById('stageInner').innerHTML =
    '<div class="pane2">' +
      '<figure><figcaption>before</figcaption><img src="'+r.before+'"></figure>' +
      '<figure><figcaption>after</figcaption><img src="'+r.after+'"></figure>' +
    '</div>';
}
function setMode(m){
  mode = m;
  document.querySelectorAll('#seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode===m)));
  draw();
}
document.getElementById('seg').onclick = e => { if(e.target.dataset.mode) setMode(e.target.dataset.mode); };
document.getElementById('lbx').onclick = () => lb.removeAttribute('open');
lb.addEventListener('click', e => { if(e.target === lb) lb.removeAttribute('open'); });
document.addEventListener('keydown', e => {
  if(e.key === 'Escape'){ if(lb.hasAttribute('open')) lb.removeAttribute('open'); else return; }
  if(!lb.hasAttribute('open')) return;
  if(e.key === 'ArrowRight' || e.key === 'ArrowLeft'){
    const list = DATA.rows;
    const i = list.findIndex(r => r.route === cur.route);
    const next = list[(i + (e.key==='ArrowRight'?1:-1) + list.length) % list.length];
    if(next) openLb(next);
  }
  if(e.key === 'd' || e.key === 'D') setMode('diff');
  if(e.key === 's' || e.key === 'S') setMode('slider');
});
const q = document.getElementById('q');
let onlyChanged = true;
function apply(){
  const t = q.value.toLowerCase();
  document.querySelectorAll('.card').forEach(c => {
    const changed = c.dataset.changed === '1';
    const ok = c.dataset.route.toLowerCase().includes(t) && (!onlyChanged || changed);
    c.style.display = ok ? '' : 'none';
  });
  document.querySelectorAll('section.h').forEach(h => { h.style.display = h.nextElementSibling && h.nextElementSibling.style.display !== 'none' ? '' : 'none'; });
}
q.oninput = apply;
document.querySelector('[data-filter]').onclick = (e) => {
  onlyChanged = !onlyChanged;
  e.currentTarget.setAttribute('aria-pressed', String(onlyChanged));
  apply();
};
apply();
</script>`;

mkdirSync(DIFF_DIR, { recursive: true });
writeFileSync(join(ROOT, "visual-report.html"), html);
writeFileSync(join(ROOT, "visual-report.json"), JSON.stringify(report, null, 2));

const totalRegions = report.stats.regions;
console.log(`\n  ${report.stats.routes} routes · ${report.stats.changed} changed · ${totalRegions} regions · ${report.stats.identical} identical`);
console.log(`  wrote tools/heroui-migration/visual-report.html`);
const top = changed.slice(0, 10);
if (top.length) {
  console.log("\n  most changed:");
  for (const r of top) console.log(`    ${String(r.regionCount).padStart(3)} regions  ${(r.px / 1000).toFixed(1).padStart(7)}k px  ${r.route}`);
}
