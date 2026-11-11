/* ============================================================================
   tpl-print.js (round 2) — The Memo and The Almanac on a 540 px portrait
   canvas (export at 3x). Body text 17 px or larger.
   Reading order: headline -> the brief's blocks in GAIA's order (EXPLORER.blocks)
   -> stats; each block drawn in the family's idiom.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  // "GitHub, Gmail and Slack": the apps the brief read, named the way a sentence names them.
  const andList = (names) => (names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`);
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
  const sentence = (s) => (/[.!?]$/.test(s) ? s : s + ".");
  const ord = (n) => {
    const v = n % 100;
    return n + (v >= 11 && v <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th");
  };
  /* Paper grain: inline SVG fractal noise, multiplied over the sheet at low opacity. */
  const grain = (id, freq) =>
    `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  /* Rubber-stamp ink: a noise mask knocks small voids out of the impression. */
  const inkMask = (id) =>
    `<svg width="0" height="0" style="position:absolute" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="2" seed="4" result="n"/><feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -1.5 1.55" result="m"/><feComposite in="SourceGraphic" in2="m" operator="in"/></filter></svg>`;

  /* ==========================================================================
     THE MEMO — signature moves from the desktop original:
       a typed sheet laid on a desk with a real shadow; two punch holes;
       MEMORANDUM spaced caps; a TO / FROM / DATE / RE header on a tab stop;
       a dashed typed rule; underlined section heads; numbered typed lists;
       a RECEIVED rubber stamp with the time; dot-leader numbers; "# # #".
     Added detail: a steel paper clip, uneven typewriter ink, a faint carbon
     ghost of the header, worn stamp ink.
     ======================================================================== */
  EXPLORER.register({
    id: "memo",
    name: "The Memo",
    axes: {
      desk: [
        { id: "putty", label: "putty desk", desk: "#b9b3a8", deskB: "#a49d91" },
        { id: "oxblood", label: "oxblood leather", desk: "#6d2a31", deskB: "#541e25" },
        { id: "cobalt", label: "cobalt blotter", desk: "#2c4b94", deskB: "#213a75" },
        { id: "green", label: "green blotter", desk: "#2f5a40", deskB: "#234631" },
      ],
      paper: [
        { id: "bond", label: "bond white", paper: "#f6f3e9", rule: "#b8b1a2" },
        { id: "canary", label: "canary second sheet", paper: "#f5e9b4", rule: "#c9b773" },
      ],
      face: [
        { id: "courierprime", label: "Courier Prime", stack: "'Courier Prime', monospace", size: "18px" },
      ],
      stamp: [
        { id: "red", label: "red stamp", ink: "#b02a22" },
        { id: "violet", label: "violet stamp", ink: "#5a3a9a" },
      ],
    },
    css: `
.t-memo { box-sizing: border-box; width: 540px; padding: 40px 24px 48px; background: radial-gradient(120% 80% at 30% 0%, var(--desk) 0%, var(--deskB) 100%); }
.t-memo * { box-sizing: border-box; margin: 0; padding: 0; }
.t-memo .sheet { position: relative; isolation: isolate; background: var(--paper); color: #24221d; font: 400 var(--size)/1.55 var(--face);
  padding: 48px 34px 40px 52px; transform: rotate(-.4deg);
  text-shadow: 0 0 .5px rgba(36,34,29,.55);
  box-shadow: 0 1px 1px rgba(0,0,0,.18), 0 18px 30px -14px rgba(0,0,0,.5); }
.t-memo .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .13; z-index: -1; }
.t-memo .hole { position: absolute; left: 18px; width: 15px; height: 15px; border-radius: 50%; background: var(--deskB);
  box-shadow: inset 0 2px 3px rgba(0,0,0,.55), 0 1px 0 rgba(255,255,255,.5); }
.t-memo .clip { position: absolute; top: -16px; left: 70px; width: 26px; height: 74px; }
.t-memo .title { text-align: center; font-size: 24px; letter-spacing: .5em; padding-left: .5em; }
.t-memo .stamp { position: absolute; top: 96px; right: 26px; transform: rotate(8deg); color: var(--ink); border: 2.5px solid var(--ink); border-radius: 3px;
  padding: 4px 10px 5px; text-align: center; font: 700 15px/1.2 'Courier Prime', monospace; letter-spacing: .14em; text-shadow: none; opacity: .92; filter: url(#mm-ink); }
.t-memo .stamp b { display: block; font-size: 19px; }
.t-memo .head { position: relative; display: grid; grid-template-columns: 76px 1fr; row-gap: 2px; margin-top: 30px; }
.t-memo .head.ghost { position: absolute; top: 0; left: 0; right: 0; margin: 0; color: #2b3f7a; opacity: .09; transform: translate(2px, 3px); text-shadow: none; }
.t-memo .typed-rule { margin: 20px 0 22px; overflow: hidden; white-space: nowrap; letter-spacing: 0; }
.t-memo .typed-rule::before { content: "- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -"; }
.t-memo .deck { font-size: 22px; line-height: 1.4; }
.t-memo section { margin-top: 38px; }
.t-memo h3 { font-weight: 400; letter-spacing: 0; text-decoration: underline; text-underline-offset: 5px; margin-bottom: 12px; }
.t-memo .verb { color: var(--ink); }
.t-memo .num { display: grid; gap: 4px; font-variant-numeric: tabular-nums; }
.t-memo .num div { display: flex; align-items: baseline; gap: 8px; }
.t-memo .num i { flex: 1; border-bottom: 2px dotted #6d685c; transform: translateY(-5px); }
.t-memo .end { text-align: center; margin-top: 34px; letter-spacing: .4em; }
.t-memo .enc { display: grid; grid-template-columns: 76px 1fr; margin-top: 34px; }
.t-memo .via { white-space: nowrap; }
.t-memo .via .mk { width: 1.2cap; height: 1.2cap; vertical-align: -0.1cap; margin-right: .35em; color: #24221d; }
.t-memo .colo { text-align: center; font-size: 14px; letter-spacing: .04em; margin-top: 6px; color: #4f4b42; }
.t-memo .deck { margin-bottom: 20px; }
.t-memo .rs-h { text-decoration: underline; text-underline-offset: 5px; text-decoration-thickness: 1px; }
.t-memo .aside { color: #4f4b42; margin: -6px 0 10px; text-wrap: balance; }
.t-memo .sw { display: inline-block; width: 7.8px; height: 11px; margin-right: 1ch; vertical-align: -1px; background: #24221d; }
.t-memo .sw.hollow { background: none; box-shadow: inset 0 0 0 1.2px #24221d; }
.t-memo .tbl { font-variant-numeric: tabular-nums; }
.t-memo .tr { display: grid; column-gap: 10px; align-items: center; }
.t-memo .tr span:nth-child(n+3) { text-align: right; }
.t-memo .tr svg { display: block; }
.t-memo .tr.th { margin-bottom: 4px; }
.t-memo .tr.th span:not(:empty) { text-decoration: underline; text-underline-offset: 5px; text-decoration-thickness: 1px; }
.t-memo .tr.dash { line-height: 1; margin-top: 2px; }
.t-memo .tbl + .aside { margin: 10px 0 0; }
.t-memo .say { margin-top: 12px; text-wrap: pretty; }
.t-memo blockquote { padding-left: 2ch; text-wrap: pretty; }
.t-memo blockquote span { display: block; color: #4f4b42; margin-top: 4px; }
.t-memo .tbar { margin-top: 6px; letter-spacing: 0; white-space: nowrap; }
.t-memo { --rs-font: var(--face); --rs-font-h: var(--face); --rs-ink: #24221d; --rs-muted: #5b5548; --rs-acc: var(--ink); --rs-base: 14px; }
`,
    render(ed, skin) {
      const B = EXPLORER.blocks;
      const RIBBON = "#24221d";
      // One typewriter cell of the 18px face, and the sheet's measure inside its margins.
      const CH = 10.8;
      const W = 406;
      let attachment = 0;
      // A typewriter states figures; a bar is typed as a run of cells, the second series struck hollow.
      const typed = (values, max, cells) => {
        let x = 0;
        let out = "";
        values.forEach((v, k) => {
          const n = Math.round((v / max) * cells);
          for (let i = 0; i < n; i++, x++) {
            out += k ? `<rect x="${(x * CH + 1.5).toFixed(2)}" y="1.5" width="${(CH * 0.72 - 1).toFixed(2)}" height="10" fill="none" stroke="${RIBBON}" stroke-width="1.2"/>` : B.rect(x * CH + 1, 1, CH * 0.72, 11, RIBBON);
          }
        });
        return out;
      };
      const table = (c) => {
        const k = c.series.length;
        const figs = k > 1 ? k + 1 : 1;
        const barW = W - 6 * CH - figs * 4.5 * CH - 10 * (figs + 1);
        const cells = Math.floor(barW / CH);
        const sums = B.totals(c);
        const max = Math.max(...sums);
        const row = (cellsHtml, cls = "") => `<div class="tr ${cls}" style="grid-template-columns: 6ch ${barW}px repeat(${figs}, 4.5ch)">${cellsHtml.map((x) => `<span>${x}</span>`).join("")}</div>`;
        const heads = k > 1 ? [...c.series.map((s) => esc(s.name)), "Total"] : [esc(cap(c.unit || c.series[0].unit))];
        const figures = (i) => (k > 1 ? [...c.series.map((s) => esc(s.shown[i])), esc(B.fmt(sums[i]))] : [esc(B.fmt(sums[i]))]);
        const body = c.x.map((lab, i) => row([esc(lab), B.svg(barW, 13, typed(c.series.map((s) => s.values[i]), max, cells)), ...figures(i)]));
        const all = k > 1 ? [...c.series.map((s) => esc(s.total)), esc(B.fmt(sums.reduce((a, v) => a + v, 0)))] : [esc(c.series[0].total)];
        const key = k > 1 ? `<p class="aside key"><i class="sw"></i>${esc(c.series[0].name)}&nbsp;&nbsp; <i class="sw hollow"></i>${esc(c.series[1].name)}</p>` : "";
        return `<div class="tbl">${row(["Day", "", ...heads], "th")}${body.join("")}${row(["", "", ...all.map(() => "--")], "dash")}${row(["In all", "", ...all], "tf")}</div>${key}`;
      };
      const progressBar = (p) => {
        const n = Math.min(p.total, 20);
        const done = Math.round((p.done / p.total) * n);
        return `[${"X".repeat(done)}${"-".repeat(n - done)}]`;
      };
      const R = {
        lead: (b) => B.lead(b, { kicker: "Re:" }),
        items: (b) => B.section(b.heading, B.items(b)),
        calendar: (b) => B.section("Today", B.events(b, { clock: "t12", allDay: "All day" })),
        chart: (c) => {
          const letter = String.fromCharCode(65 + attachment++);
          return `<section data-block="chart"><h3>Attachment ${letter}: ${esc(c.title)}</h3><p class="aside">${esc(B.facts(c, " -- "))}</p>${table(c)}<p class="say">${esc(sentence(c.takeaway))}</p></section>`;
        },
        quote: (q) => `<section data-block="quote"><blockquote>"${esc(q.text)}"<span>-- ${esc(q.author)}, by ${esc(q.app)}</span></blockquote></section>`,
        progress: (p) => `<section data-block="progress"><h3>On the goal</h3><p>${esc(sentence(p.statement))}</p><p class="tbar">${progressBar(p)}&nbsp; ${p.done} of ${p.total} done</p></section>`,
        note: (n) => `<section data-block="note"><p><span class="verb">N.B.</span> ${esc(sentence(n.text))}</p></section>`,
      };
      const sections = B.layout(ed, R);
      const s = ed.stats;
      if (s) {
        const split = [s.you ? `you ${s.you}` : "", s.gaia ? `GAIA ${s.gaia}` : ""].filter(Boolean).join(", ");
        sections.push(`<section><h3>By the numbers</h3><div class="num">${s.done ? `<div>Done yesterday<i></i>${s.done}${split ? ` (${split})` : ""}</div>` : ""}${s.mail ? `<div>Emails handled<i></i>${s.mail}</div>` : ""}${s.focus ? `<div>Focus time today<i></i>${esc(s.focus)}</div>` : ""}</div></section>`);
      }
      const head = `<span>TO:</span><span>${ed.recipient ? esc(ed.recipient.first) : "You"}</span><span>FROM:</span><span>GAIA</span><span>DATE:</span><span>${esc(ed.dateLong)}</span><span>RE:</span><span>Your ${esc(ed.weekday)} -- Edition No.&nbsp;${ed.editionNo}</span>`;
      const clip = `<svg class="clip" viewBox="0 0 26 74" aria-hidden="true"><path d="M8 66 V12 a5 5 0 0 1 10 0 V58 a8 8 0 0 1 -16 0 V18" fill="none" stroke="#8d939b" stroke-width="2.4" stroke-linecap="round"/><path d="M8 66 V12 a5 5 0 0 1 10 0" fill="none" stroke="#e9edf1" stroke-width=".8" stroke-linecap="round" transform="translate(-.6 -.4)"/></svg>`;
      return `<article class="t-memo" style="--desk:${skin.desk.desk}; --deskB:${skin.desk.deskB}; --paper:${skin.paper.paper}; --rule:${skin.paper.rule}; --face:${skin.face.stack}; --size:${skin.face.size}; --ink:${skin.stamp.ink}">
${inkMask("mm-ink")}
<div class="sheet" data-paper>${grain("mm-g", 0.85)}
  <i class="hole" style="top:150px"></i><i class="hole" style="bottom:150px"></i>${clip}
  <div class="title">MEMORANDUM</div>
  <div class="stamp">RECEIVED<b>${esc(ed.time)}</b></div>
  <div class="head"><div class="head ghost" aria-hidden="true">${head}</div>${head}</div>
  <div class="typed-rule" aria-hidden="true"></div>
  <p class="deck">${esc(ed.deck)}</p>
  ${EXPLORER.fold(sections).join("")}
  ${ed.sources.length ? `<div class="enc" data-block="sources"><span>VIA:</span><span>Your ${ed.sources.map((a) => `<span class="via">${B.logo(a.logo, { cls: "mk" })}${esc(a.name)}</span>`).join(", ")}.</span></div>` : ""}
  <p class="end">###</p>
  <p class="colo">EDITION NO. ${ed.editionNo} -- TYPED ${esc(ed.time)} BY GAIA</p>
</div></article>`;
    },
  });

  /* ==========================================================================
     THE ALMANAC — signature moves from the desktop original:
       a centred small-caps title page ("Being a faithful account of the
       day's business", "for the 3rd Day of July, Anno 2026"); fleuron
       ornaments; a double-ruled "Calculations for the Day" table; small-caps
       section heads over hairlines; pilcrow-led paragraphs; a framed
       engraved plate of the painting; a "Reckoning of the day" colophon.
     Added detail: letterpress impression, foxing spots, a deckled edge.
     ======================================================================== */
  const fleuron = `<svg class="fleu" viewBox="0 0 40 24" aria-hidden="true"><circle cx="20" cy="6" r="3.4"/><circle cx="13" cy="17" r="3.4"/><circle cx="27" cy="17" r="3.4"/></svg>`;
  EXPLORER.register({
    id: "almanac",
    name: "The Almanac",
    axes: {
      paper: [
        { id: "tallow", label: "aged tallow", paper: "#efe5c9", hair: "#bcaa80", fox: "rgba(140,96,40,.16)" },
        { id: "linen", label: "linen", paper: "#f3eee2", hair: "#c3b89e", fox: "rgba(120,90,50,.12)" },
        { id: "sage", label: "sage wrapper", paper: "#dfe6d0", hair: "#a6b48f", fox: "rgba(90,90,40,.14)" },
      ],
      rubric: [
        { id: "vermilion", label: "vermilion rubric", rub: "#9e2e1b" },
        { id: "ink", label: "black only", rub: "#2a241a" },
      ],
      face: [
        { id: "baskerville", label: "Libre Baskerville", stack: "'Libre Baskerville', serif" },
      ],
      plate: [
        { id: "engraving", label: "engraved plate" },
        { id: "none", label: "no plate" },
      ],
    },
    css: `
.t-almanac { position: relative; isolation: isolate; box-sizing: border-box; width: 540px; padding: 44px 40px 48px; color: #2a241a;
  background: radial-gradient(130% 90% at 50% 45%, transparent 55%, var(--fox) 100%), var(--paper);
  font: 400 18px/1.55 var(--face); text-shadow: 0 .4px 0 rgba(42,36,26,.35); }
.t-almanac * { box-sizing: border-box; margin: 0; padding: 0; }
.t-almanac .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .16; z-index: -1; }
.t-almanac .spot { position: absolute; border-radius: 50%; background: var(--fox); filter: blur(1.5px); z-index: -1; }
.t-almanac .c { text-align: center; }
.t-almanac .sc { font-variant-caps: small-caps; letter-spacing: .03em; }
.t-almanac .eyebrow { font-size: 16px; color: var(--rub); }
.t-almanac h1 { font-weight: 400; font-variant-caps: small-caps; font-size: 44px; line-height: 1.05; letter-spacing: .02em; margin-top: 10px; }
.t-almanac .sub { font-style: italic; font-size: 19px; margin-top: 10px; }
.t-almanac .for { font-size: 17px; margin-top: 10px; text-wrap: balance; }
.t-almanac .fleu { display: block; width: 30px; height: 18px; margin: 20px auto; fill: var(--rub); }
.t-almanac .deck { font-style: italic; font-size: 23px; line-height: 1.38; text-align: center; padding: 0 8px; }
.t-almanac h2 { font-weight: 400; text-align: center; font-size: 19px; color: var(--rub); padding-bottom: 6px; border-bottom: 1px solid var(--hair); margin: 0 18px 14px; }
.t-almanac .p { display: grid; grid-template-columns: 22px 1fr; padding: 5px 0; }
.t-almanac .p .pil { color: var(--rub); }
.t-almanac .p > span:last-child { text-wrap: pretty; }
.t-almanac .p em { font-style: italic; }
.t-almanac .p em.rub { color: var(--rub); }
.t-almanac .calc { margin-top: 30px; border-top: 3px double #2a241a; border-bottom: 3px double #2a241a; padding: 8px 0 10px; }
.t-almanac .calc h2 { border: 0; margin: 0 0 4px; padding: 0; font-size: 16px; }
.t-almanac .calc .row { display: grid; grid-template-columns: repeat(3, 1fr); text-align: center; }
.t-almanac .calc b { display: block; font-weight: 400; font-size: 30px; line-height: 1.1; font-variant-numeric: lining-nums tabular-nums; }
.t-almanac .calc span { font-size: 15px; }
.t-almanac figure { margin: 34px auto 0; width: 300px; }
.t-almanac .frame { padding: 6px; border: 3px double #2a241a; }
.t-almanac .frame img { display: block; width: 100%; height: 200px; object-fit: cover; filter: grayscale(1) contrast(1.35) brightness(.98) sepia(.2); }
.t-almanac figcaption { text-align: center; font-size: 15px; margin-top: 8px; line-height: 1.4; text-wrap: balance; }
.t-almanac .reck { margin-top: 30px; text-align: center; font-size: 17px; line-height: 1.5; font-style: italic; text-wrap: balance; }
.t-almanac .reck .sc { font-style: normal; }
.t-almanac .src { margin-top: 18px; }
.t-almanac .src .reck { margin-top: 6px; }
.t-almanac .src .logos { display: flex; justify-content: center; gap: 14px; color: #2a241a; }
.t-almanac .src .mk { width: 16px; height: 16px; }
.t-almanac .defs { position: absolute; }
.t-almanac .deck { margin-bottom: 20px; }
.t-almanac .fg { margin: 28px 0 24px; width: auto; }
.t-almanac .fg .h { text-align: center; font-size: 17px; color: var(--rub); padding-bottom: 6px; border-bottom: 1px solid var(--hair); margin: 0 18px 14px; }
.t-almanac .fg svg { margin: 0 auto; }
.t-almanac .fg figcaption { text-align: center; font-size: 15px; font-style: italic; margin: 8px 0 6px; text-wrap: balance; }
.t-almanac .fg figcaption .sc { font-style: normal; }
.t-almanac .ep { margin: 24px 30px; text-align: center; font-style: italic; font-size: 19px; line-height: 1.42; text-wrap: balance; }
.t-almanac .ep cite { display: block; font-size: 15px; margin-top: 6px; color: #5a4f3c; }
.t-almanac .blk { margin: 20px 0; }
.t-almanac .cells { display: block; margin: 8px 0 2px; }
.t-almanac { --rs-font: var(--face); --rs-font-h: var(--face); --rs-ink: #2a241a; --rs-muted: #5e5443; --rs-acc: var(--rub); --rs-base: 16px; --rs-kick-case: none; --rs-kick-variant: small-caps; --rs-kick-track: .06em; --rs-h-variant: small-caps; }
`,
    render(ed, skin) {
      const B = EXPLORER.blocks;
      const INK = "#2a241a";
      const SOFT = "#5a4f3c";
      const W = 460;
      const PLOT = { font: "Libre Baskerville", size: 13, ink: INK, soft: SOFT, rule: "var(--hair)", base: INK };
      // Engraved fills: the first series solid, the second hatched, as a copperplate prints a second tone.
      const fills = [INK, "url(#al-hatch)"];
      const tone = ["solid", "hatched"];
      const p = (lead, body, rub) => `<div class="p"><span class="pil">¶</span><span>${lead ? `<em${rub ? ' class="rub"' : ""}>${lead}</em> — ` : ""}${body}</span></div>`;
      let fig = 0;
      const figure = (c) => {
        const plot = c.chart === "line"
          ? B.line(c, { ...PLOT, w: W, h: 160, gutter: 30, dot: 3.2, lines: [{ color: INK, width: 1.6 }, { color: "var(--rub)", width: 1.6, dash: "5 3" }] })
          : c.chart === "spark"
            ? B.spark(c, { ...PLOT, w: W, h: 48, line: INK, lineW: 1.6 })
            : B.bars(c, { ...PLOT, w: W, h: 170, fills, gapRatio: 0.42, ruleW: 1 });
        const legend = c.series.length > 1
          ? ` ${c.series.map((s, k) => `${(k ? (x) => x : cap)(c.chart === "line" ? (k ? "the broken line" : "the full line") : tone[k])}, ${esc(s.name)} (${esc(s.total)})`).join("; ")}.`
          : "";
        return `<figure class="fg" data-block="chart"><div class="h sc">${esc(c.title)}</div>${plot}<figcaption><span class="sc">Fig. ${++fig}.</span> — ${esc(B.facts(c, "; in "))}.${legend}</figcaption>${p("", esc(sentence(c.takeaway)))}</figure>`;
      };
      const R = {
        lead: (b) => B.lead(b, { kicker: "Of first importance" }),
        items: (b) => B.section(b.heading, B.items(b)),
        calendar: (b) => B.section("To-day", B.events(b, { clock: "t12", allDay: "All day" })),
        chart: figure,
        quote: (q) => `<blockquote class="ep" data-block="quote">${esc(q.text)}<cite><span class="sc">${esc(q.author)}</span>, by ${esc(q.app)}</cite></blockquote>`,
        progress: (g) => `<div class="blk" data-block="progress">${p("Of the goal", `${esc(sentence(g.statement))} ${g.done} of ${g.total} accomplished.<span class="cells">${B.cells(g, { w: Math.min(g.total, 12) * 22 - 6, h: 12, gap: 6, on: INK, offStroke: INK })}</span>`, true)}</div>`,
        note: (n) => `<div class="blk" data-block="note">${p("Observed", esc(sentence(n.text)), true)}</div>`,
      };
      const secs = B.layout(ed, R);
      const s = ed.stats;
      const calc = s ? `<div class="calc"><h2 class="sc">Calculations for the day</h2><div class="row">${s.done ? `<div><b>${s.done}</b><span class="sc">${s.done === 1 ? "task" : "tasks"} done</span></div>` : ""}${s.mail ? `<div><b>${s.mail}</b><span class="sc">letters</span></div>` : ""}${s.focus ? `<div><b>${esc(s.focus)}</b><span class="sc">focus hours</span></div>` : ""}</div></div>` : "";
      const a = ed.art;
      const plate = skin.plate.id === "engraving" ? `<figure><div class="frame"><img src="${a.src}" alt="${esc(a.title)}, ${esc(a.artist)}"></div><figcaption><span class="sc">Plate I. — ${esc(a.title)}</span><br><i>${esc(a.artist)}, ${a.year}, ${esc(a.medium)}</i></figcaption></figure>` : "";
      return `<article class="t-almanac" style="--paper:${skin.paper.paper}; --hair:${skin.paper.hair}; --fox:${skin.paper.fox}; --rub:${skin.rubric.rub}; --face:${skin.face.stack}">
${grain("al-g", 0.7)}<svg width="0" height="0" class="defs" aria-hidden="true"><defs><pattern id="al-hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="1.4" height="4" fill="#2a241a"/></pattern></defs></svg><i class="spot" style="top:12%; left:8%; width:9px; height:7px"></i><i class="spot" style="top:58%; right:6%; width:12px; height:10px"></i><i class="spot" style="bottom:9%; left:20%; width:6px; height:6px"></i>
<div class="c"><div class="eyebrow sc">The Almanac</div><h1>The ${esc(ed.weekday)} Brief</h1><p class="sub">Being a faithful account of the day's business</p><p class="for sc">for the ${ord(ed.day)} day of ${esc(ed.month)}, anno ${ed.year} — No.&nbsp;${ed.editionNo}</p></div>
${fleuron}
<p class="deck">${esc(ed.deck)}</p>
${EXPLORER.fold(secs).join("")}
${calc}
${plate}
${fleuron}
<p class="reck"><span class="sc">Reckoning of the day</span>${s ? ` — ${s.done} tasks accomplished${s.you && s.gaia ? `, whereof ${s.you} by your own hand and ${s.gaia} by the machine` : ""}` : ""}. Printed at ${esc(ed.time)} by GAIA.</p>
${ed.sources.length ? `<div class="src" data-block="sources"><p class="logos">${ed.sources.map((a) => B.logo(a.logo, { cls: "mk" })).join("")}</p><p class="reck"><span class="sc">Sources consulted</span> — your ${esc(andList(ed.sources.map((a) => a.name)))}.</p></div>` : ""}
</article>`;
    },
  });
})();
