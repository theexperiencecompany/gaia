/* ============================================================================
   tpl-image.js (round 2) — The Horizon, The Exhibition and The Week on a
   540 px portrait canvas (export at 3x). Body 17 px or larger.
   Reading order: headline -> needs you -> today -> done overnight -> stats;
   empty sections are omitted.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const grain = (id, freq) =>
    `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  /* Primed-canvas weave: two fine crossing thread patterns. */
  const WEAVE = "repeating-linear-gradient(0deg, rgba(0,0,0,.035) 0 1px, transparent 1px 3px), repeating-linear-gradient(90deg, rgba(255,255,255,.05) 0 1px, transparent 1px 3px)";

  /* ==========================================================================
     THE HORIZON — signature moves from the desktop original:
       the whole page is one sky, cool at the top warming to the horizon at
       the foot; a huge Helvetica headline set straight into the sky; the
       lists in small monospace with tabular times; a mono colophon split
       left / right at the foot.
     Added detail: a primed-canvas weave and grain across the sky so the
     gradient reads as a painted field rather than a screen fill.
     ======================================================================== */
  EXPLORER.register({
    id: "gradient",
    name: "The Horizon",
    axes: {
      palette: [
        { id: "dawn", label: "dawn (blue to rose)", a: "#a9c1e6", b: "#f6ecdf", c: "#f0b3a8", mid: "#f3e3d6", ink: "#17171c", soft: "#3e3d45" },
        { id: "dusk", label: "dusk (violet to amber)", a: "#c5b6e3", b: "#f7e3cf", c: "#f3b97c", mid: "#f4dccb", ink: "#1a1620", soft: "#3f3846" },
        { id: "night", label: "night sky (ink to ember)", a: "#1b2340", b: "#3b3a5c", c: "#c9705a", mid: "#36365a", ink: "#f4efe8", soft: "#d9d2cc" },
        { id: "sea", label: "sea (teal to sand)", a: "#9fd2cf", b: "#eef1e4", c: "#e9cf9f", mid: "#e9ecdf", ink: "#13201f", soft: "#334542" },
        { id: "meadow", label: "meadow (sage to butter)", a: "#b7d1a3", b: "#f2f1dd", c: "#f0d382", mid: "#eceed6", ink: "#18200f", soft: "#3a4430" },
        { id: "ember", label: "ember (peach to terracotta)", a: "#f5c79c", b: "#f8e8d6", c: "#dd8466", mid: "#f4e0cc", ink: "#1f1410", soft: "#4a352b" },
        { id: "rosewater", label: "rosewater (blush to apricot)", a: "#efc0c8", b: "#fbefe7", c: "#f4c595", mid: "#f8e6de", ink: "#22151a", soft: "#4a3840" },
        { id: "aurora", label: "aurora (deep teal to green)", a: "#0e2a33", b: "#1c4747", c: "#5aa985", mid: "#1b4040", ink: "#eef5ef", soft: "#cfe0d6" },
      ],
      face: [
        { id: "helvetica", label: "Helvetica Neue", head: "'Helvetica Neue', Helvetica, Arial, sans-serif", w: 700 },
        { id: "aeonik", label: "Aeonik Extended", head: "'Aeonik Extended', 'Helvetica Neue', sans-serif", w: 700 },
      ],
      weave: [
        { id: "canvas", label: "canvas weave", op: ".7" },
        { id: "smooth", label: "smooth gesso", op: ".25" },
      ],
    },
    css: `
.t-gradient { position: relative; isolation: isolate; box-sizing: border-box; width: 540px; padding: 36px 30px 34px; color: var(--ink); font: 400 17px/1.45 Menlo, 'SF Mono', monospace;
  background-color: var(--mid); background-image: ${WEAVE}, linear-gradient(180deg, var(--a) 0%, var(--b) 55%, var(--c) 100%); }
.t-gradient * { box-sizing: border-box; margin: 0; padding: 0; }
.t-gradient .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: soft-light; opacity: var(--weave); z-index: -1; }
.t-gradient .k { display: flex; justify-content: space-between; font-size: 15px; letter-spacing: 0; }
.t-gradient h1 { font-family: var(--head); font-weight: var(--w); font-size: 46px; line-height: 1.04; letter-spacing: -.03em; margin: 26px 0 0; text-wrap: pretty; }
.t-gradient section { margin-top: 48px; }
.t-gradient h2 { font-family: var(--head); font-size: 23px; font-weight: 700; letter-spacing: -.02em; margin-bottom: 12px; }
.t-gradient .r { display: grid; grid-template-columns: 82px 1fr; padding: 6px 0; line-height: 1.5; }
.t-gradient .r .t { font-variant-numeric: tabular-nums; }
.t-gradient .r > span:last-child { text-wrap: pretty; }
.t-gradient .r .n { display: block; font-size: 15px; color: var(--soft); }
.t-gradient .foot { display: flex; justify-content: space-between; margin-top: 44px; font-size: 15px; line-height: 1.6; letter-spacing: 0; }
.t-gradient .foot b { font-weight: 700; }
.t-gradient .foot .r2 { text-align: right; }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const r = (t, label, note) => `<div class="r" data-role="body"><span class="t">${esc(t)}</span><span>${esc(label)}${note ? `<span class="n">${esc(note)}</span>` : ""}</span></div>`;
      const secs = [];
      if (needs.length) secs.push(`<section><h2>Needs your call</h2>${needs.map((d) => r(d.verb, d.label, d.note)).join("")}</section>`);
      if (c.today.length) secs.push(`<section><h2>Today</h2>${c.today.map((e) => r(e.t24 || "EOD", e.label, e.note)).join("")}</section>`);
      if (c.overnight.length) secs.push(`<section><h2>Handled overnight</h2>${c.overnight.map((e) => r(e.t24, e.label, e.note)).join("")}</section>`);
      if (c.running.length) secs.push(`<section><h2>Still in progress</h2>${c.running.map((e) => r(e.t24, e.label, e.note)).join("")}</section>`);
      const s = c.stats;
      const k = skin.palette;
      return `<article class="t-gradient" style="--a:${k.a}; --b:${k.b}; --c:${k.c}; --mid:${k.mid}; --ink:${k.ink}; --soft:${k.soft}; --head:${skin.face.head}; --w:${skin.face.w}; --weave:${skin.weave.op}">
${grain("hz-g", 0.7)}
<div class="k"><span>GAIA · ${esc(ed.weekday)}</span><span>No ${ed.editionNo} · ${esc(ed.time24)}</span></div>
<h1>${esc(ed.deck)}</h1>
${secs.join("")}
<div class="foot"><span><b>The ${esc(ed.weekday)} Brief</b><br>Edition No ${ed.editionNo}<br>${esc(ed.dateLong)}</span>${s ? `<span class="r2">Done ${s.done}${s.mail ? ` · mail ${s.mail}` : ""}${s.focus ? ` · focus ${esc(s.focus)}` : ""}${s.you && s.gaia ? `<br>${s.you} by you · ${s.gaia} by GAIA` : ""}</span>` : ""}</div>
</article>`;
    },
  });

  /* ==========================================================================
     THE EXHIBITION — signature moves from the desktop original:
       the painting hung full bleed; a black title plate carrying "THE
       FRIDAY BRIEF" in huge Didot caps with a spaced-caps "ONE DAY ONLY"
       kicker; a mono wall caption (artist, title, year / medium / edition);
       the deck in italic; "PROGRAMME FOR THE DAY" with mono times, tags in
       spaced caps and red verbs.
     Added detail: canvas weave and craquelure-like grain on the painting,
     a gilt frame lip, a museum label card pinned to the wall.
     ======================================================================== */
  EXPLORER.register({
    id: "exhibition",
    name: "The Exhibition",
    axes: {
      wall: [
        { id: "bone", label: "bone wall", wall: "#f3efe6", ink: "#161411", soft: "#5a554c", acc: "#a8361f", hair: "#d9d2c4", plate: "#121110" },
        { id: "grey", label: "gallery grey", wall: "#e3e2de", ink: "#141414", soft: "#4f4f4c", acc: "#9c2f1a", hair: "#c8c7c1", plate: "#161616" },
        { id: "green", label: "museum green", wall: "#1f4636", ink: "#eef0e6", soft: "#c3d0c5", acc: "#f3bd86", hair: "#355e4e", plate: "#0f1f18" },
        { id: "oxblood", label: "salon oxblood", wall: "#5d1a21", ink: "#f6ede2", soft: "#e2cbbf", acc: "#f2c25e", hair: "#7c3a40", plate: "#170c0d" },
      ],
      crop: [
        { id: "sky", label: "crop: the sky", pos: "45% 20%" },
        { id: "cypress", label: "crop: the cypress", pos: "78% 50%" },
      ],
      face: [
        { id: "didot", label: "Didot", head: "Didot, 'Bodoni 72', serif" },
        { id: "bodoni", label: "Bodoni 72", head: "'Bodoni 72', Didot, serif" },
      ],
    },
    css: `
.t-exhibition { position: relative; box-sizing: border-box; width: 540px; background: var(--wall); color: var(--ink); font: 400 17px/1.45 'Helvetica Neue', Helvetica, Arial, sans-serif; padding-bottom: 34px; }
.t-exhibition * { box-sizing: border-box; margin: 0; padding: 0; }
.t-exhibition .mono { font-family: Menlo, 'SF Mono', monospace; }
.t-exhibition .art { position: relative; height: 360px; overflow: hidden; border-bottom: 4px solid #8a6a2a; }
.t-exhibition .art img { display: block; width: 100%; height: 100%; object-fit: cover; object-position: var(--pos); transform: scale(1.12); filter: saturate(1.05) contrast(1.04); }
.t-exhibition .art::after { content: ""; position: absolute; inset: 0; background: ${WEAVE}; mix-blend-mode: multiply; }
.t-exhibition .art .grain { position: absolute; inset: 0; width: 100%; height: 100%; mix-blend-mode: overlay; opacity: .45; z-index: 1; }
.t-exhibition .plate { background: var(--plate); color: #f4efe6; padding: 24px 28px 26px; }
.t-exhibition .plate .k { font-size: 14px; font-weight: 700; letter-spacing: 0; }
.t-exhibition .plate h1 { font-family: var(--head); font-weight: 400; font-size: 76px; line-height: .92; letter-spacing: .005em; text-transform: uppercase; margin-top: 12px; }
.t-exhibition .body { padding: 0 28px; }
.t-exhibition .label { position: relative; margin: -14px 0 0 auto; width: 300px; background: #fbfaf6; color: #1b1a17; padding: 12px 14px; font-size: 14px; line-height: 1.5; box-shadow: 0 6px 12px -6px rgba(0,0,0,.35); }
.t-exhibition .label b { display: block; font-size: 15px; }
.t-exhibition .deck { font: italic 400 24px/1.35 var(--head); margin-top: 22px; text-wrap: balance; }
.t-exhibition h2 { font-size: 15px; font-weight: 700; letter-spacing: 0; margin-top: 30px; padding-bottom: 8px; border-bottom: 2px solid var(--ink); }
.t-exhibition h3 { font: italic 400 25px/1.2 var(--head); margin: 38px 0 10px; }
.t-exhibition .w { display: grid; grid-template-columns: 96px 1fr; padding: 8px 0; line-height: 1.5; }
.t-exhibition .w > span:last-child { text-wrap: pretty; }
.t-exhibition .w .k2 { font-size: 15px; padding-top: 1px; }
.t-exhibition .w .k2.acc { color: var(--acc); font-weight: 700; }
.t-exhibition .w b { font-weight: 700; }
.t-exhibition .w .n { display: block; font-size: 15px; color: var(--soft); }
.t-exhibition .w .tag { display: block; font: italic 15px/1.4 var(--head); color: var(--soft); margin-top: 2px; }
.t-exhibition .foot { margin-top: 26px; padding-top: 12px; border-top: 1px solid var(--ink); font-size: 15px; line-height: 1.6; }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const w = (k, acc, label, note, tag) => `<div class="w" data-role="body"><span class="k2 mono${acc ? " acc" : ""}">${esc(k)}${tag ? `<span class="tag">${esc(tag.toLowerCase())}</span>` : ""}</span><span>${esc(label)}${note ? `<span class="n">${esc(note)}</span>` : ""}</span></div>`;
      const parts = [];
      if (needs.length) parts.push(`<h3>Awaiting your decision</h3>${needs.map((d) => w(d.verb, true, d.label, d.note)).join("")}`);
      if (c.today.length) parts.push(`<h3>Today</h3>${c.today.map((e) => w(e.time || "EOD", false, e.label, e.note, e.tag)).join("")}`);
      if (c.overnight.length) parts.push(`<h3>Overnight, while you slept</h3>${c.overnight.map((e) => w(e.t24, false, e.label, e.note, e.tag)).join("")}`);
      if (c.running.length) parts.push(`<h3>Still in progress</h3>${c.running.map((e) => w(e.t24, false, e.label, e.note, e.tag)).join("")}`);
      const s = c.stats;
      const a = ed.art;
      return `<article class="t-exhibition" style="--wall:${skin.wall.wall}; --ink:${skin.wall.ink}; --soft:${skin.wall.soft}; --acc:${skin.wall.acc}; --hair:${skin.wall.hair}; --plate:${skin.wall.plate}; --pos:${skin.crop.pos}; --head:${skin.face.head}">
<div class="art"><img src="${a.src}" alt="${esc(a.title)}, ${esc(a.artist)}, ${a.year}">${grain("ex-g", 1.1)}</div>
<div class="plate"><div class="k">One day only · ${esc(ed.dateLong)}</div><h1 style="font-size:${Math.min(104, Math.floor(480 / (ed.weekday.length * 0.82)))}px">The<br>${esc(ed.weekday)}<br>Brief</h1></div>
<div class="body">
  <div class="label mono"><b>${esc(a.artist)}</b>${esc(a.title)}, ${a.year}<br>${esc(a.medium)} · Edition No ${ed.editionNo}</div>
  <p class="deck">${esc(ed.deck)}</p>
  ${parts.length ? `<h2>Programme for the day</h2>${parts.join("")}` : ""}
  ${s ? `<p class="foot mono">Yesterday ${s.done} done${s.you && s.gaia ? ` (you ${s.you} / GAIA ${s.gaia})` : ""}${s.mail || s.focus ? `<br>${[s.mail ? `${s.mail} emails handled` : "", s.focus ? `${esc(s.focus)} of focus today` : ""].filter(Boolean).join(" · ")}` : ""}<br>Brief generated ${esc(ed.time)}</p>` : ""}
</div></article>`;
    },
  });

  /* ==========================================================================
     THE WEEK — signature moves from the desktop original:
       a white editorial page; "GAIA · WEEKLY REVIEW"; a towering Playfair
       "The Week" with No 6 and the date range set right; an italic deck; the
       shape of the week as a stacked you / GAIA bar chart with totals and a
       dimmed weekend; four big figures; Shipped this week with Playfair
       numerals; Handled quietly; Still yours to call with accent verbs; The
       week ahead with day labels.
     Weekly rollups are DEMO data: the daily `ed` carries no weekly
     aggregates. Decisions and the next-up list come from `ed.content`.
     Added detail: a folio line, magazine paper grain, chart gridlines.
     ======================================================================== */
  const DAYS = ["M", "T", "W", "T", "F", "S", "S"];
  const MO = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  EXPLORER.register({
    id: "weekly",
    name: "The Week (weekly review)",
    axes: {
      accent: [
        { id: "blue", label: "editorial blue", acc: "#2f6fd0", accText: "#245cb3", accLite: "#a9c3ea" },
        { id: "red", label: "editorial red", acc: "#c43b25", accText: "#a8301c", accLite: "#ecb5aa" },
        { id: "green", label: "editorial green", acc: "#1f8a55", accText: "#16714a", accLite: "#a9d8bf" },
        { id: "orange", label: "editorial orange", acc: "#e0731e", accText: "#a8500c", accLite: "#f3c9a3" },
      ],
      paper: [
        { id: "white", label: "white", paper: "#fbfbf9", ink: "#141414", soft: "#55554f", hair: "#dcdbd5" },
        { id: "cream", label: "cream", paper: "#f6f1e6", ink: "#1b1813", soft: "#5c554a", hair: "#ddd4c3" },
      ],
      chart: [
        { id: "stacked", label: "stacked bars" },
        { id: "paired", label: "paired bars" },
      ],
    },
    css: `
.t-weekly { position: relative; isolation: isolate; box-sizing: border-box; width: 540px; padding: 32px 30px 34px; background: var(--paper); color: var(--ink); font: 400 17px/1.45 'Helvetica Neue', Helvetica, Arial, sans-serif; }
.t-weekly * { box-sizing: border-box; margin: 0; padding: 0; }
.t-weekly .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .12; z-index: -1; }
.t-weekly .pf { font-family: 'Playfair Display', Georgia, serif; }
.t-weekly .k { font-size: 14px; font-weight: 700; letter-spacing: 0; color: var(--soft); }
.t-weekly .mast { display: flex; justify-content: space-between; align-items: flex-end; padding-bottom: 12px; border-bottom: 2px solid var(--ink); box-shadow: 0 4px 0 -3px var(--ink); margin-top: 6px; }
.t-weekly h1 { font: 700 82px/.95 'Playfair Display', Georgia, serif; letter-spacing: -.02em; }
.t-weekly .no { text-align: right; font-size: 14px; color: var(--soft); }
.t-weekly .no b { display: block; font: 700 30px/1 'Playfair Display', Georgia, serif; color: var(--ink); }
.t-weekly .deck { font: italic 500 25px/1.3 'Playfair Display', Georgia, serif; margin-top: 18px; padding-bottom: 20px; border-bottom: 1px solid var(--hair); }
.t-weekly section { margin-top: 42px; }
.t-weekly h2 { font: 700 23px/1.2 'Playfair Display', Georgia, serif; }
.t-weekly h2 small { display: block; font: 400 14px/1.4 'Helvetica Neue', Helvetica, sans-serif; color: var(--soft); margin-top: 2px; }
.t-weekly .list { margin-top: 8px; border-top: 1px solid var(--ink); }
.t-weekly .li { display: grid; grid-template-columns: 58px 1fr; padding: 8px 0; line-height: 1.5; }
.t-weekly .li > span:last-child { text-wrap: pretty; }
.t-weekly .list.ruled .li { border-bottom: 1px solid var(--hair); }
.t-weekly .li.one { grid-template-columns: 1fr; }
.t-weekly .li .num { font: 400 19px/1.3 'Playfair Display', Georgia, serif; }
.t-weekly .li .day { font: italic 700 17px/1.5 'Playfair Display', Georgia, serif; font-variant-numeric: lining-nums tabular-nums; }
.t-weekly .li b { color: var(--accText); }
.t-weekly .li .n { display: block; font-size: 15px; color: var(--soft); }
.t-weekly .figs { display: grid; grid-template-columns: 1fr 1fr; gap: 18px 18px; margin-top: 12px; }
.t-weekly .figs b { display: block; font: 700 46px/1 'Playfair Display', Georgia, serif; font-variant-numeric: lining-nums; }
.t-weekly .figs span { display: block; font-size: 15px; margin-top: 4px; }
.t-weekly .figs small { display: block; font-size: 14px; color: var(--soft); }
.t-weekly .legend { display: flex; gap: 16px; margin-top: 10px; font-size: 14px; font-weight: 700; letter-spacing: 0; color: var(--soft); }
.t-weekly .legend i { display: inline-block; width: 11px; height: 11px; margin-right: 6px; vertical-align: -1px; }
.t-weekly .chart { position: relative; display: grid; grid-template-columns: repeat(7, 1fr); align-items: end; height: 220px; margin-top: 12px; border-bottom: 1.5px solid var(--ink);
  background: linear-gradient(var(--hair) 1px, transparent 1px) 0 0 / 100% 55px; }
.t-weekly .col { display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; }
.t-weekly .col .tot { font-size: 14px; font-weight: 700; margin-bottom: 4px; font-variant-numeric: tabular-nums; }
.t-weekly .col .b { width: 44px; }
.t-weekly .col .pair { display: flex; align-items: flex-end; gap: 3px; }
.t-weekly .col .pair .b { width: 20px; }
.t-weekly .col .you { background: var(--ink); }
.t-weekly .col .gaia { background: var(--acc); }
.t-weekly .col.we .b { opacity: .45; }
.t-weekly .days { display: grid; grid-template-columns: repeat(7, 1fr); text-align: center; font-size: 14px; font-weight: 700; color: var(--soft); padding-top: 6px; }
.t-weekly .foot { margin-top: 26px; padding-top: 10px; border-top: 1px solid var(--ink); font-size: 14px; letter-spacing: 0; color: var(--soft); line-height: 1.6; }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const end = new Date(ed.year, FULL.indexOf(ed.month), ed.day);
      const start = new Date(ed.year, FULL.indexOf(ed.month), ed.day - 6);
      const range = `${start.getDate()} ${MO[start.getMonth()]} – ${end.getDate()} ${MO[end.getMonth()]} ${end.getFullYear()}`;
      const weekNo = Math.ceil(ed.editionNo / 7);
      const secs = [];
      if (needs.length) secs.push(`<section><h2>Still yours to call<small>${needs.length} still open this morning</small></h2><div class="list ruled">${needs.map((d) => `<div class="li one" data-role="body"><span><b>${esc(d.verb)}</b> — ${esc(d.label)}${d.note ? `<span class="n">${esc(d.note)}</span>` : ""}</span></div>`).join("")}</div></section>`);
      const wk = ed.week || { days: [], shipped: [], handled: [], ahead: [] };
      if (wk.ahead.length) secs.push(`<section><h2>The week ahead</h2><div class="list">${wk.ahead.map((e) => `<div class="li" data-role="body"><span class="day">${esc(e.day)}</span><span>${esc(e.label)}</span></div>`).join("")}</div></section>`);
      if (wk.shipped.length) secs.push(`<section><h2>Shipped this week</h2><div class="list">${wk.shipped.map((x, i) => `<div class="li" data-role="body"><span class="num">${i + 1}</span><span>${esc(x)}</span></div>`).join("")}</div></section>`);
      if (wk.handled.length) secs.push(`<section><h2>Handled quietly<small>Done by GAIA, no nudge needed</small></h2><div class="list">${wk.handled.map((x) => `<div class="li one" data-role="body"><span>${esc(x)}</span></div>`).join("")}</div></section>`);
      const YOU = wk.days.map((d) => d.you);
      const GAIA = wk.days.map((d) => d.gaia);
      const you = YOU.reduce((a, b) => a + b, 0);
      const gaia = GAIA.reduce((a, b) => a + b, 0);
      if (you + gaia > 0) {
        const paired = skin.chart.id === "paired";
        const max = paired ? Math.max(...YOU, ...GAIA) : Math.max(...YOU.map((v, i) => v + GAIA[i]));
        const H = 180;
        const bar = (v, cls) => `<div class="b ${cls}" style="height:${Math.round((v / max) * H)}px"></div>`;
        const cols = DAYS.map((_, i) => `<div class="col${i > 4 ? " we" : ""}">${YOU[i] + GAIA[i] ? `<span class="tot">${YOU[i] + GAIA[i]}</span>` : ""}${paired ? `<div class="pair">${bar(YOU[i], "you")}${bar(GAIA[i], "gaia")}</div>` : bar(YOU[i], "you") + bar(GAIA[i], "gaia")}</div>`).join("");
        secs.push(`<section><h2>The numbers</h2><div class="figs"><div><b>${you + gaia}</b><span>tasks done</span>${you && gaia ? `<small>${you} by you · ${gaia} by GAIA</small>` : ""}</div></div></section>`);
        secs.push(`<section><h2>The shape of the week<small>Tasks handled each day, yours and GAIA's</small></h2><div class="legend"><span><i style="background:var(--ink)"></i>You</span><span><i style="background:var(--acc)"></i>GAIA</span><span style="font-weight:400">Weekend shown lighter</span></div><div class="chart">${cols}</div><div class="days">${DAYS.map((d) => `<span>${d}</span>`).join("")}</div></section>`);
      }
      return `<article class="t-weekly" style="--acc:${skin.accent.acc}; --accText:${skin.accent.accText}; --accLite:${skin.accent.accLite}; --paper:${skin.paper.paper}; --ink:${skin.paper.ink}; --soft:${skin.paper.soft}; --hair:${skin.paper.hair}">
${grain("wk-g", 0.85)}
<div class="k">GAIA · weekly review</div>
<div class="mast"><h1>The Week</h1><div class="no"><b>No ${weekNo}</b>${esc(range)}</div></div>
<p class="deck">${esc(ed.deck)}</p>
${secs.join("")}
<p class="foot">Weekly review · compiled by GAIA ${esc(ed.dateLong)} · week No ${weekNo} · from daily edition No ${ed.editionNo}</p>
</article>`;
    },
  });
})();
