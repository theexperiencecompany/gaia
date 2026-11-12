/* ============================================================================
   tpl-image.js (round 2) — The Horizon, The Exhibition and The Week on a
   540 px portrait canvas (export at 3x). Body 17 px or larger.
   Each family draws the brief's composed blocks (ed.blocks) in GAIA's order, in its own idiom,
   with the shared item anatomy and plots of EXPLORER.blocks.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const grain = (id, freq) =>
    `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  /* Primed-canvas weave: two fine crossing thread patterns. */
  const WEAVE = "repeating-linear-gradient(0deg, rgba(0,0,0,.035) 0 1px, transparent 1px 3px), repeating-linear-gradient(90deg, rgba(255,255,255,.05) 0 1px, transparent 1px 3px)";
  // A skin's hex ink at an alpha: the second series is the same ink thinned, never a new colour.
  const alpha = (hex, a) => `rgba(${[1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(",")},${a})`;
  const B = EXPLORER.blocks;

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
        { id: "schibsted", label: "Schibsted Grotesk", head: "'Schibsted Grotesk', sans-serif", w: 700 },
      ],
      weave: [
        { id: "canvas", label: "canvas weave", op: ".7" },
        { id: "smooth", label: "smooth gesso", op: ".25" },
      ],
    },
    css: `
.t-gradient { position: relative; isolation: isolate; box-sizing: border-box; width: 540px; padding: 36px 30px 34px; color: var(--ink); font: 400 17px/1.45 'JetBrains Mono', monospace;
  background-color: var(--mid); background-image: ${WEAVE}, linear-gradient(180deg, var(--a) 0%, var(--b) 55%, var(--c) 100%); }
.t-gradient * { box-sizing: border-box; margin: 0; padding: 0; }
.t-gradient .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: soft-light; opacity: var(--weave); z-index: -1; }
.t-gradient .k { display: flex; justify-content: space-between; font-size: 15px; letter-spacing: 0; }
.t-gradient h1 { font-family: var(--head); font-weight: var(--w); font-size: 46px; line-height: 1.04; letter-spacing: -.03em; margin: 26px 0 0; text-wrap: pretty; }
.t-gradient section { margin-top: 28px; }
.t-gradient { --rs-font: 'JetBrains Mono', monospace; --rs-font-h: var(--head); --rs-ink: var(--ink); --rs-muted: var(--soft); --rs-acc: var(--ink); --rs-base: 14px; --rs-verb-case: uppercase; --rs-title-track: -.01em; --rs-h-track: -.02em; }
.t-gradient section.lead { margin-top: 8px; }
.t-gradient section.fig { margin-top: 56px; }
.t-gradient .fig h2 { font-family: var(--head); font-size: 23px; font-weight: 700; letter-spacing: -.02em; line-height: 1.2; margin-bottom: 6px; text-wrap: balance; }
.t-gradient .sub { font-size: 14px; color: var(--soft); margin-bottom: 12px; }
.t-gradient .key { display: flex; gap: 20px; font-size: 14px; margin-bottom: 10px; }
.t-gradient .key i { display: inline-block; width: 10px; height: 10px; margin-right: 8px; }
.t-gradient .say { margin-top: 12px; font-size: 15px; line-height: 1.5; text-wrap: pretty; }
.t-gradient .fig[data-block="note"] .say { margin-top: 0; font-size: 17px; }
.t-gradient .q { font-family: var(--head); font-weight: 700; font-size: 27px; line-height: 1.15; letter-spacing: -.02em; text-wrap: balance; margin-bottom: 10px; }
.t-gradient .r { display: grid; grid-template-columns: 82px 1fr; padding: 2px 0 10px; line-height: 1.5; font-size: 15px; }
.t-gradient .r .t { font-weight: 700; font-variant-numeric: tabular-nums; }
.t-gradient .foot { display: flex; justify-content: space-between; margin-top: 44px; font-size: 15px; line-height: 1.6; letter-spacing: 0; }
.t-gradient .foot b { font-weight: 700; }
.t-gradient .foot .r2 { text-align: right; }
.t-gradient .src { margin-top: 18px; font-size: 15px; line-height: 1.6; }
.t-gradient .src .logos { display: flex; gap: 12px; margin-bottom: 6px; }
.t-gradient .src .xb-logo { width: 15px; height: 15px; }
`,
    render(ed, skin) {
      const k = skin.palette;
      const thin = alpha(k.ink, 0.34);
      const PLOT = { w: 480, font: "JetBrains Mono", size: 13, ink: k.ink, soft: k.soft, rule: alpha(k.ink, 0.16), base: k.ink };
      const key = (fill, label) => `<span><i style="background:${fill}"></i>${label}</span>`;
      const sec = (kind, html) => `<section class="fig" data-block="${kind}">${html}</section>`;
      const R = {
        lead: (b) => `<section class="lead">${B.lead(b, { kicker: "Signal" })}</section>`,
        items: (b) => `<section>${B.section(b.heading, B.items(b))}</section>`,
        calendar: (b) => `<section>${B.section("Today", B.events(b, { clock: "t24", allDay: "All day" }))}</section>`,
        chart: (c) => {
          const plot = c.chart === "line"
            ? B.line(c, { ...PLOT, h: 150, lines: [{ color: k.ink, width: 2 }, { color: thin, width: 2, dash: "5 4" }], gutter: 30 })
            : c.chart === "spark"
              ? B.spark(c, { ...PLOT, h: 48, line: k.ink })
              : B.bars(c, { ...PLOT, h: 160, fills: [k.ink, thin], gapRatio: 0.44 });
          const legend = c.series.length > 1 ? `<p class="key">${c.series.map((x, i) => key(i ? thin : k.ink, `${esc(x.name)} ${esc(x.total)}`)).join("")}</p>` : "";
          return sec("chart", `<h2>${esc(c.title)}</h2><p class="sub">${esc(B.facts(c))}</p>${legend}${plot}<p class="say">${esc(c.takeaway)}</p>`);
        },
        quote: (q) => sec("quote", `<p class="q">&ldquo;${esc(q.text)}&rdquo;</p><p class="sub">${esc(q.author)}, ${esc(q.app)}</p>`),
        progress: (p) => sec("progress", `<h2>${esc(p.statement)}</h2><div class="r"><span class="t">${p.done}/${p.total}</span><span>done, ${p.total - p.done} open</span></div><div class="cells">${B.cells(p, { w: 480, h: 12, gap: 6, on: k.ink, offStroke: thin })}</div>`),
        note: (n) => sec("note", `<p class="say">${esc(n.text)}</p>`),
      };
      const s = ed.stats;
      return `<article class="t-gradient" style="--a:${k.a}; --b:${k.b}; --c:${k.c}; --mid:${k.mid}; --ink:${k.ink}; --soft:${k.soft}; --head:${skin.face.head}; --w:${skin.face.w}; --weave:${skin.weave.op}">
${grain("hz-g", 0.7)}
<div class="k"><span>GAIA · ${esc(ed.weekday)}</span><span>No ${ed.editionNo} · ${esc(ed.time24)}</span></div>
<h1>${esc(ed.deck)}</h1>
${EXPLORER.fold(B.layout(ed, R)).join("")}
<div class="foot"><span><b>The ${esc(ed.weekday)} Brief</b><br>Edition No ${ed.editionNo}<br>${esc(ed.dateLong)}</span>${s ? `<span class="r2">Done ${s.done}${s.mail ? ` · mail ${s.mail}` : ""}${s.focus ? ` · focus ${esc(s.focus)}` : ""}${s.you && s.gaia ? `<br>${s.you} by you · ${s.gaia} by GAIA` : ""}</span>` : ""}</div>
${ed.sources.length ? `<p class="src" data-block="sources"><span class="logos">${ed.sources.map((x) => B.logo(x.logo, { cls: "" })).join("")}</span>Made from your ${esc(EXPLORER.blocks.appList(ed.sources))}</p>` : ""}
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
        { id: "bodoni", label: "Bodoni Moda", head: "'Bodoni Moda', serif" },
      ],
    },
    css: `
.t-exhibition { position: relative; box-sizing: border-box; width: 540px; background: var(--wall); color: var(--ink); font: 400 17px/1.45 'TeX Gyre Heros', sans-serif; padding-bottom: 34px; }
.t-exhibition * { box-sizing: border-box; margin: 0; padding: 0; }
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
.t-exhibition { --rs-font: 'TeX Gyre Heros', sans-serif; --rs-font-h: var(--head); --rs-ink: var(--ink); --rs-muted: var(--soft); --rs-acc: var(--acc); --rs-base: 15px; --rs-h-style: italic; --rs-h-track: 0; }
.t-exhibition .grp { margin-top: 16px; }
.t-exhibition .feat { margin-top: 30px; background: #fbfaf6; padding: 0 22px 20px; box-shadow: 0 6px 12px -6px rgba(0,0,0,.35);
  --rs-ink: #1b1a17; --rs-muted: #5a554c; --rs-acc: #a8361f; }
.t-exhibition .fig { margin-top: 48px; }
.t-exhibition .fig h3 { font: italic 400 25px/1.2 var(--head); margin-bottom: 6px; text-wrap: balance; }
.t-exhibition .cap { font-size: 14px; color: var(--soft); margin-bottom: 12px; }
.t-exhibition .cap b { font-weight: 700; color: var(--ink); }
.t-exhibition .key { display: flex; gap: 20px; font-size: 14px; margin-bottom: 12px; }
.t-exhibition .key i { display: inline-block; width: 10px; height: 10px; margin-right: 8px; }
.t-exhibition .say { margin-top: 12px; font-size: 16px; line-height: 1.45; text-wrap: pretty; }
.t-exhibition .q p { font: italic 400 27px/1.22 var(--head); text-wrap: balance; }
.t-exhibition .q cite { display: block; margin-top: 12px; font-style: normal; font-size: 14px; line-height: 1.5; color: var(--soft); }
.t-exhibition .wall { font-size: 17px; line-height: 1.5; padding-left: 16px; border-left: 2px solid var(--acc); text-wrap: pretty; }
.t-exhibition .foot { margin-top: 26px; padding-top: 12px; border-top: 1px solid var(--ink); font-size: 15px; line-height: 1.6; }
.t-exhibition .src { margin-top: 18px; font-size: 14px; line-height: 1.6; color: var(--soft); }
.t-exhibition .src .logos { display: flex; gap: 12px; margin-bottom: 6px; }
.t-exhibition .src .xb-logo { width: 16px; height: 16px; }
`,
    render(ed, skin) {
      const k = skin.wall;
      const PLOT = { w: 484, font: "TeX Gyre Heros", size: 13, ink: k.ink, soft: k.soft, rule: k.hair, base: k.ink };
      const key = (fill, label) => `<span><i style="background:${fill}"></i>${label}</span>`;
      const fig = (kind, html) => `<div class="fig" data-block="${kind}">${html}</div>`;
      const R = {
        // The featured work: a second label pinned to the wall, under the deck.
        lead: (b) => `<div class="feat">${B.lead(b, { kicker: "Featured work", mode: "color" })}</div>`,
        items: (b) => `<div class="grp">${B.section(b.heading, B.items(b, { mode: "color" }))}</div>`,
        calendar: (b) => `<div class="grp">${B.section("Today", B.events(b, { clock: "t12", allDay: "All day", mode: "color" }))}</div>`,
        chart: (c) => {
          const plot = c.chart === "line"
            ? B.line(c, { ...PLOT, h: 150, lines: [{ color: k.acc, width: 2 }, { color: k.ink, width: 2, dash: "5 4" }], gutter: 28 })
            : c.chart === "spark"
              ? B.spark(c, { ...PLOT, h: 48, line: k.acc })
              : B.bars(c, { ...PLOT, h: 168, fills: [k.ink, k.acc], gapRatio: 0.46 });
          const legend = c.series.length > 1 ? `<p class="key">${c.series.map((x, i) => key(i ? k.acc : k.ink, `${esc(x.name)} ${esc(x.total)}`)).join("")}</p>` : "";
          return fig("chart", `<h3>${esc(c.title)}</h3><p class="cap">${esc(B.facts(c))}</p>${legend}${plot}<p class="say">${esc(c.takeaway)}</p>`);
        },
        // Someone's own words hung as wall text: large Bodoni italic, the caption beneath.
        quote: (q) => fig("quote", `<blockquote class="q"><p>&ldquo;${esc(q.text)}&rdquo;</p><cite>${esc(q.author)}<br>${esc(q.app)}</cite></blockquote>`),
        progress: (p) => fig("progress", `<h3>${esc(p.statement)}</h3><p class="cap"><b>${p.done} of ${p.total}</b> done</p><div class="cells">${B.cells(p, { w: 484, h: 12, gap: 6, on: k.acc, offStroke: k.soft })}</div>`),
        note: (n) => fig("note", `<p class="wall">${esc(n.text)}</p>`),
      };
      const s = ed.stats;
      const a = ed.art;
      return `<article class="t-exhibition" style="--wall:${k.wall}; --ink:${k.ink}; --soft:${k.soft}; --acc:${k.acc}; --hair:${k.hair}; --plate:${k.plate}; --pos:${skin.crop.pos}; --head:${skin.face.head}">
<div class="art"><img src="${a.src}" alt="${esc(a.title)}, ${esc(a.artist)}, ${a.year}">${grain("ex-g", 1.1)}</div>
<div class="plate"><div class="k">One day only · ${esc(ed.dateLong)}</div><h1 style="font-size:${Math.min(104, Math.floor(480 / (ed.weekday.length * 0.82)))}px">The<br>${esc(ed.weekday)}<br>Brief</h1></div>
<div class="body" data-fold>
  <div class="label"><b>${esc(a.artist)}</b>${esc(a.title)}, ${a.year}<br>${esc(a.medium)} · Edition No ${ed.editionNo}</div>
  <p class="deck">${esc(ed.deck)}</p>
  ${B.layout(ed, R).join("")}
  ${s ? `<p class="foot">Yesterday ${s.done} done${s.you && s.gaia ? ` (you ${s.you} / GAIA ${s.gaia})` : ""}${s.mail || s.focus ? `<br>${[s.mail ? `${s.mail} emails handled` : "", s.focus ? `${esc(s.focus)} of focus today` : ""].filter(Boolean).join(" · ")}` : ""}<br>Brief generated ${esc(ed.time)}</p>` : ""}
  ${ed.sources.length ? `<p class="src" data-block="sources"><span class="logos">${ed.sources.map((x) => B.logo(x.logo, { mode: "color", cls: "" })).join("")}</span>Made from your ${esc(EXPLORER.blocks.appList(ed.sources))}</p>` : ""}
</div></article>`;
    },
  });

  /* ==========================================================================
     THE WEEK — signature moves from the desktop original:
       a white editorial page; "GAIA · WEEKLY REVIEW"; a towering Newsreader
       "The Week" with No 6 and the date range set right; an italic deck;
       sections headed in Newsreader with Heros standfirsts; big figures in
       The numbers; the week ahead with day labels. What the week shipped and
       handled, and its charts, are the blocks GAIA composed.
     Added detail: a folio line, magazine paper grain, chart gridlines.
     ======================================================================== */
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
    },
    css: `
.t-weekly { position: relative; isolation: isolate; box-sizing: border-box; width: 540px; padding: 32px 30px 34px; background: var(--paper); color: var(--ink); font: 400 17px/1.45 'TeX Gyre Heros', sans-serif; }
.t-weekly * { box-sizing: border-box; margin: 0; padding: 0; }
.t-weekly .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .12; z-index: -1; }
.t-weekly .k { font-size: 14px; font-weight: 700; letter-spacing: 0; color: var(--soft); }
.t-weekly .mast { display: flex; justify-content: space-between; align-items: flex-end; padding-bottom: 12px; border-bottom: 2px solid var(--ink); box-shadow: 0 4px 0 -3px var(--ink); margin-top: 6px; }
.t-weekly h1 { font: 700 82px/.95 'Newsreader', serif; letter-spacing: -.02em; }
.t-weekly .no { text-align: right; font-size: 14px; color: var(--soft); }
.t-weekly .no b { display: block; font: 700 30px/1 'Newsreader', serif; color: var(--ink); }
.t-weekly .deck { font: italic 500 25px/1.3 'Newsreader', serif; margin-top: 18px; padding-bottom: 20px; border-bottom: 1px solid var(--hair); }
.t-weekly section { margin-top: 42px; }
.t-weekly h2 { font: 700 23px/1.2 'Newsreader', serif; }
.t-weekly h2 small { display: block; font: 400 14px/1.4 'TeX Gyre Heros', sans-serif; color: var(--soft); margin-top: 2px; }
.t-weekly { --rs-font: 'TeX Gyre Heros', sans-serif; --rs-font-h: 'Newsreader', serif; --rs-ink: var(--ink); --rs-muted: var(--soft); --rs-acc: var(--accText); --rs-base: 15px; --rs-h-track: -.01em; }
.t-weekly section.fig { margin-top: 48px; }
.t-weekly .figs { display: grid; grid-template-columns: 1fr; gap: 18px; margin-top: 12px; }
.t-weekly .figs b { display: block; font: 700 46px/1 'Newsreader', serif; font-variant-numeric: lining-nums; }
.t-weekly .figs .of { font: 400 17px/1 'TeX Gyre Heros', sans-serif; color: var(--soft); }
.t-weekly .figs span { display: block; font-size: 15px; margin-top: 4px; text-wrap: pretty; }
.t-weekly .figs small { display: block; font-size: 14px; color: var(--soft); }
.t-weekly .cells { margin-top: 10px; }
.t-weekly .facts { font-size: 14px; color: var(--soft); margin-top: 10px; }
.t-weekly .legend { display: flex; gap: 16px; margin-top: 6px; font-size: 14px; font-weight: 700; letter-spacing: 0; color: var(--soft); }
.t-weekly .legend i { display: inline-block; width: 11px; height: 11px; margin-right: 6px; vertical-align: -1px; }
.t-weekly .plot { margin-top: 14px; }
.t-weekly .spk { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 14px; }
.t-weekly .spk b { display: block; font: 700 46px/1 'Newsreader', serif; font-variant-numeric: lining-nums; }
.t-weekly .spk span { display: block; font-size: 14px; color: var(--soft); margin-top: 4px; }
.t-weekly .ax { font-size: 14px; color: var(--soft); margin-top: 6px; text-align: right; }
.t-weekly .ednote { font: italic 500 22px/1.35 'Newsreader', serif; text-wrap: pretty; padding-top: 16px; border-top: 1px solid var(--hair); }
.t-weekly .foot { margin-top: 26px; padding-top: 10px; border-top: 1px solid var(--ink); font-size: 14px; letter-spacing: 0; color: var(--soft); line-height: 1.6; }
.t-weekly .src { display: block; margin-top: 10px; }
.t-weekly .src .logos { display: flex; gap: 12px; margin-bottom: 4px; color: var(--ink); }
.t-weekly .src .xb-logo { width: 15px; height: 15px; }
`,
    render(ed, skin) {
      const k = { ...skin.accent, ...skin.paper };
      const end = new Date(ed.year, FULL.indexOf(ed.month), ed.day);
      const start = new Date(ed.year, FULL.indexOf(ed.month), ed.day - 6);
      const range = `${start.getDate()} ${MO[start.getMonth()]} – ${end.getDate()} ${MO[end.getMonth()]} ${end.getFullYear()}`;
      const weekNo = Math.ceil(ed.editionNo / 7);
      const PLOT = { w: 480, font: "TeX Gyre Heros", size: 14, weight: 700, ink: k.ink, soft: k.soft, rule: k.hair, base: k.ink, valueWeight: 700 };
      const key = (fill, label) => `<span><i style="background:${fill}"></i>${label}</span>`;
      const sec = (kind, html) => `<section class="fig" data-block="${kind}">${html}</section>`;
      const R = {
        items: (b) => `<section>${B.section(b.heading, B.items(b))}</section>`,
        calendar: (b) => `<section>${B.section("The week ahead", B.events(b, { clock: "t24", allDay: "All day" }))}</section>`,
        chart: (c) => {
          if (c.chart === "spark") {
            // A figure, magazine-style: the week's total large, its run of days beside it.
            const s = c.series[0];
            return sec("chart", `<h2>${esc(c.title)}<small>${esc(c.takeaway)}</small></h2><div class="spk"><div><b>${esc(s.total)}</b><span>${esc(c.unit || s.unit)}, ${esc(c.range || "")}</span></div>${B.spark(c, { ...PLOT, w: 260, h: 56, line: k.acc, lineW: 2.5, dot: 3.5 })}</div><p class="ax">${esc(c.x[0])} to ${esc(c.x[c.x.length - 1])}</p>`);
          }
          const plot = c.chart === "line"
            ? B.line(c, { ...PLOT, h: 170, lines: [{ color: k.acc, width: 2.5 }, { color: k.ink, width: 2, dash: "5 4" }], gutter: 28, dot: 4 })
            : B.bars(c, { ...PLOT, h: 200, fills: [k.ink, k.acc], gapRatio: 0.4 });
          const legend = c.series.length > 1 ? `<div class="legend">${c.series.map((x, i) => key(i ? k.acc : k.ink, `${esc(x.name)} ${esc(x.total)}`)).join("")}</div>` : "";
          return sec("chart", `<h2>${esc(c.title)}<small>${esc(c.takeaway)}</small></h2><p class="facts">${esc(B.facts(c))}</p>${legend}<div class="plot">${plot}</div>`);
        },
        progress: (p) => sec("progress", `<h2>Goal</h2><div class="figs"><div><b>${p.done}<i class="of"> of ${p.total}</i></b><span>${esc(p.statement)}</span><div class="cells">${B.cells(p, { w: 200, h: 8, gap: 3, on: k.acc, off: k.hair })}</div></div></div>`),
        note: (n) => sec("note", `<p class="ednote">${esc(n.text)}</p>`),
      };
      const parts = B.layout(ed, R);
      const s = ed.stats;
      if (s) {
        const numbers = `<section><h2>The numbers</h2><div class="figs"><div><b>${s.done}</b><span>${s.done === 1 ? "task" : "tasks"} done</span>${s.you && s.gaia ? `<small>${s.you} by you · ${s.gaia} by GAIA</small>` : ""}</div></div></section>`;
        const at = ed.blocks.findIndex((b) => b.kind === "chart" || b.kind === "progress");
        parts.splice(at < 0 ? parts.length : at, 0, numbers);
      }
      return `<article class="t-weekly" style="--acc:${k.acc}; --accText:${k.accText}; --accLite:${k.accLite}; --paper:${k.paper}; --ink:${k.ink}; --soft:${k.soft}; --hair:${k.hair}">
${grain("wk-g", 0.85)}
<div class="k">GAIA · weekly review</div>
<div class="mast"><h1>The Week</h1><div class="no"><b>No ${weekNo}</b>${esc(range)}</div></div>
<p class="deck">${esc(ed.deck)}</p>
${EXPLORER.fold(parts).join("")}
<p class="foot">Weekly review · compiled by GAIA ${esc(ed.dateLong)} · week No&nbsp;${weekNo} · from daily edition No&nbsp;${ed.editionNo}${ed.sources.length ? `<span class="src" data-block="sources"><span class="logos">${ed.sources.map((x) => B.logo(x.logo, { cls: "" })).join("")}</span>Made from your ${esc(EXPLORER.blocks.appList(ed.sources))}</span>` : ""}</p>
</article>`;
    },
  });
})();
