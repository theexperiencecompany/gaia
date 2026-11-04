#!/usr/bin/env node
/**
 * Clean, keyboard-first UI review: one route at a time, full-page BEFORE | AFTER.
 *
 *   node tools/heroui-migration/review.mjs
 *
 * Reads visual-report.json (written by visual/compare.mjs) and writes review.html.
 * Keys: ← → route · ↑ ↓ scroll · B/A/D  before/after/diff · S slider · / search
 */
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const ROOT = join(process.cwd(), "tools/heroui-migration");
const data = JSON.parse(readFileSync(join(ROOT, "visual-report.json"), "utf8"));

const routes = data.rows
  .filter((r) => Object.values(r.viewports).some((v) => v.page))
  .map((r) => ({
    route: r.route,
    regions: r.regionCount,
    px: r.px,
    vp: Object.fromEntries(
      Object.entries(r.viewports)
        .filter(([, v]) => v.page)
        .map(([k, v]) => [k, { page: v.page, regions: v.regions || [] }]),
    ),
  }));

const html = `<!doctype html><meta charset="utf-8"><title>UI review · ${data.a} → ${data.b}</title>
<style>
:root{color-scheme:dark;--bg:#0b0b0d;--panel:#141417;--line:#26262b;--fg:#ececf0;--dim:#8a8a93;--red:#ff5c5c;--blue:#7c9cff}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.45 ui-sans-serif,system-ui,sans-serif;display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:14px;padding:10px 16px;border-bottom:1px solid var(--line);flex:0 0 auto}
h1{font-size:13px;margin:0;font-weight:600;white-space:nowrap}
.badge{font:600 11px/1 ui-monospace,monospace;color:var(--red);border:1px solid #ff5c5c55;border-radius:99px;padding:4px 8px}
.spacer{flex:1}
button{background:var(--panel);border:1px solid var(--line);color:var(--dim);border-radius:7px;padding:6px 10px;font-size:11.5px;cursor:pointer}
button[aria-pressed=true]{color:#fff;border-color:var(--blue);background:#7c9cff1f}
.keys{color:#5a5a63;font-size:11px;font-family:ui-monospace,monospace}
main{flex:1;display:flex;min-height:0}
nav{width:250px;flex:0 0 250px;border-right:1px solid var(--line);overflow:auto;padding:8px}
nav a{display:flex;justify-content:space-between;gap:8px;padding:5px 7px;border-radius:6px;color:var(--dim);text-decoration:none;font-size:11.5px}
nav a:hover{background:#1a1a1f;color:#fff}
nav a[aria-current=true]{background:#7c9cff1f;color:#fff}
nav a span{color:#484f58;font-family:ui-monospace,monospace;font-size:10px}
#stage{flex:1;overflow:auto;padding:14px}
.panes{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}
.pane{background:#111;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.pane h2{margin:0;padding:6px 9px;font-size:10px;letter-spacing:.09em;text-transform:uppercase;color:var(--dim);border-bottom:1px solid var(--line);font-weight:500;position:sticky;top:0;background:#141417;z-index:2}
.pane img{display:block;width:100%}
.wrap{position:relative}
.box{position:absolute;border:1.5px solid var(--red);background:#ff5c5c14;pointer-events:none}
.single .pane:last-child{display:none}
.single .panes{grid-template-columns:1fr}
.hidden{display:none!important}
</style>
<header>
  <h1 id="title">—</h1>
  <span class="badge" id="nreg">—</span>
  <span class="keys">← → route · ↑ ↓ scroll · B before · A after · S side-by-side · D diff</span>
  <span class="spacer"></span>
  <button id="sbs" aria-pressed="true">side by side</button>
  <button id="before" aria-pressed="false">before</button>
  <button id="after" aria-pressed="false">after</button>
  <button id="diff" aria-pressed="false">show regions</button>
  <span id="count" class="keys"></span>
</header>
<main>
  <nav id="list"></nav>
  <div id="stage"><div class="panes">
    <section class="pane"><h2>before (${data.a})</h2><div class="wrap"><img id="ib" alt=""><div id="bb"></div></div></section>
    <section class="pane"><h2>after (${data.b})</h2><div class="wrap"><img id="ia" alt=""><div id="ba"></div></div></section>
  </div></div>
</main>
<script>
const DATA = ${JSON.stringify(routes)};
const listEl = document.getElementById('list');
const ib = document.getElementById('ib'), ia = document.getElementById('ia');
const bb = document.getElementById('bb'), ba = document.getElementById('ba');
let idx = 0, mode = 'sbs', showRegions = false;

listEl.innerHTML = DATA.map((r,i) => '<a href="#" data-i="'+i+'"><b>'+r.route+'</b><span>'+(r.regions||'')+'</span></a>').join('');
listEl.addEventListener('click', e => { const a = e.target.closest('a'); if(!a) return; e.preventDefault(); go(+a.dataset.i); });

function paint(){
  const r = DATA[idx];
  const vp = r.vp.desktop || r.vp.mobile;
  ib.src = vp.page.before; ia.src = vp.page.after;
  document.getElementById('title').textContent = r.route;
  document.getElementById('nreg').textContent = r.regions + ' regions';
  document.getElementById('count').textContent = (idx+1)+' / '+DATA.length;
  [...listEl.children].forEach((a,i)=>a.setAttribute('aria-current', String(i===idx)));
  const boxes = showRegions && vp.regions ? vp.regions.map(g =>
    '<div class="box" style="left:'+g.left+'%;top:'+g.top+'%;width:'+g.width+'%;height:'+g.height+'%"></div>').join('') : '';
  bb.innerHTML = boxes; ba.innerHTML = boxes;
  document.querySelector('.panes').classList.toggle('single', mode !== 'sbs');
  if(mode === 'before'){ ib.style.display='block'; ia.style.display='none'; }
  else if(mode === 'after'){ ib.style.display='none'; ia.style.display='block'; }
  else { ib.style.display='block'; ia.style.display='block'; }
  document.getElementById('stage').scrollTop = 0;
  document.querySelectorAll('header button').forEach(b=>b.setAttribute('aria-pressed','false'));
  const id = mode==='sbs'?'sbs':mode;
  document.getElementById(id).setAttribute('aria-pressed','true');
}
function go(i){ idx = (i + DATA.length) % DATA.length; paint(); }

document.getElementById('sbs').onclick = () => { mode='sbs'; paint(); };
document.getElementById('before').onclick = () => { mode='before'; paint(); };
document.getElementById('after').onclick = () => { mode='after'; paint(); };
document.getElementById('diff').onclick = () => { showRegions = !showRegions; paint(); };

document.addEventListener('keydown', e => {
  if(e.target.tagName === 'INPUT') return;
  if(e.key === 'ArrowRight'){ go(idx+1); e.preventDefault(); }
  else if(e.key === 'ArrowLeft'){ go(idx-1); e.preventDefault(); }
  else if(e.key === 'ArrowDown'){ document.getElementById('stage').scrollBy({top:600}); e.preventDefault(); }
  else if(e.key === 'ArrowUp'){ document.getElementById('stage').scrollBy({top:-600}); e.preventDefault(); }
  else if(e.key.toLowerCase() === 'b'){ mode='before'; paint(); }
  else if(e.key.toLowerCase() === 'a'){ mode='after'; paint(); }
  else if(e.key.toLowerCase() === 's'){ mode='sbs'; paint(); }
  else if(e.key.toLowerCase() === 'd'){ showRegions = !showRegions; paint(); }
});
paint();
</script>`;

writeFileSync(join(ROOT, "review.html"), html);
console.log(`wrote review.html — ${routes.length} routes`);
