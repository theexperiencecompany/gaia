/* ============================================================================
   tpl-paper.js (round 2) — The Library Card, The Menu and The Invoice on a
   540 px portrait canvas (export at 3x). Body 17 px or larger.
   Reading order: headline -> the brief's blocks in GAIA's order (EXPLORER.blocks)
   -> stats; each block drawn in the family's idiom.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  // "GitHub, Gmail and Slack": the apps the brief read, named the way a sentence names them.
  const andList = (names) => (names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`);
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
  const grain = (id, freq) =>
    `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  /* ==========================================================================
     THE LIBRARY CARD — signature moves from the desktop original:
       a buff circulation card on a dark desk; EX LIBRIS · GAIA CIRCULATION;
       a big typewriter title with CARD No; a DATE / ITEM / DUE ruled table;
       red rubber date-stamps in the date column and status stamps in the
       due column; a librarian's signature line; the card sitting in a
       manila pocket marked RETURN TO GAIA CIRCULATION.
     Added detail: stamp ink variance (tilt, density, voids), a stitched
     pocket seam, a thumb notch, ruled-card blue lines with a red margin.
     ======================================================================== */
  EXPLORER.register({
    id: "librarycard",
    name: "The Library Card",
    axes: {
      stock: [
        { id: "buff", label: "buff card", card: "#efdfb6", rule: "#9fb5d3", pocket: "#d9bf8a", desk: "#4b4842" },
        { id: "salmon", label: "salmon card", card: "#f3d2be", rule: "#a6abd0", pocket: "#d8b48f", desk: "#2f3b4d" },
        { id: "green", label: "green card", card: "#dbe7cb", rule: "#93b0c3", pocket: "#c8b688", desk: "#4a2a2c" },
      ],
      ink: [
        { id: "red", label: "red pad", stamp: "#8c1c14" },
        { id: "violet", label: "violet pad", stamp: "#4a3290" },
        { id: "black", label: "black pad", stamp: "#26231f" },
      ],
      face: [
        { id: "elite", label: "Special Elite", stack: "'Special Elite', monospace" },
      ],
    },
    css: `
.t-librarycard { box-sizing: border-box; width: 540px; padding: 34px 26px 40px; background: radial-gradient(120% 80% at 30% 0%, color-mix(in srgb, var(--desk) 75%, #ffffff) 0%, var(--desk) 70%); }
.t-librarycard * { box-sizing: border-box; margin: 0; padding: 0; }
.t-librarycard .stack { position: relative; }
.t-librarycard .card { position: relative; isolation: isolate; background: var(--card); color: #211d17; padding: 26px 24px 120px; font: 400 17px/1.45 var(--face); transform: rotate(.5deg);
  box-shadow: 0 2px 2px rgba(0,0,0,.2), 0 16px 26px -12px rgba(0,0,0,.5); }
.t-librarycard .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .16; z-index: -1; }
.t-librarycard .notch { position: absolute; top: -1px; left: 50%; width: 56px; height: 14px; margin-left: -28px; border-radius: 0 0 28px 28px; background: var(--desk); }
.t-librarycard .lib { display: flex; justify-content: space-between; font-size: 14px; letter-spacing: 0; color: #4a4338; }
.t-librarycard .tt { display: flex; justify-content: space-between; align-items: flex-end; margin-top: 14px; padding-bottom: 10px; border-bottom: 2.5px solid #211d17; }
.t-librarycard h1 { font-size: 34px; line-height: 1.02; font-weight: 700; text-transform: uppercase; letter-spacing: .01em; }
.t-librarycard .no { text-align: right; font-size: 14px; letter-spacing: 0; }
.t-librarycard .no b { display: block; font-size: 26px; letter-spacing: 0; }
.t-librarycard .deck { margin-top: 12px; font-size: 19px; line-height: 1.4; font-weight: 700; }
.t-librarycard .cols { display: grid; grid-template-columns: 86px 1fr 92px; margin-top: 10px; padding-bottom: 4px; border-bottom: 1px solid #211d17; font-size: 14px; letter-spacing: 0; }
.t-librarycard .cols span:last-child { text-align: right; }
.t-librarycard .sl { font-size: 15px; font-weight: 700; letter-spacing: 0; color: #4a4338; padding: 12px 0 4px; border-bottom: 1px solid var(--rule); }
.t-librarycard .row { position: relative; display: grid; grid-template-columns: 86px 1fr 92px; align-items: center; padding: 7px 0; border-bottom: 1px solid var(--rule); }
.t-librarycard .row::before { content: ""; position: absolute; left: 80px; top: 0; bottom: 0; border-left: 1px solid #c45a4b; }
.t-librarycard .row .it { padding-left: 8px; }
.t-librarycard .row .it svg { display: block; }
.t-librarycard .row .due { text-align: right; font-variant-numeric: tabular-nums; line-height: 1; }
.t-librarycard .deck { margin-bottom: 16px; }
/* The typewriter's line sits loose in its box, so each block takes 6px more air to stay 2x the item gap clear. */
.t-librarycard .bk { padding-block: 6px; }
.t-librarycard .blk { padding: 20px 0; font-size: 17px; line-height: 1.45; text-wrap: pretty; }
.t-librarycard .q p:first-child { font-size: 18px; }
.t-librarycard .q .by { margin-top: 6px; font-size: 15px; color: #4f483c; }
.t-librarycard .verso { margin-top: 30px; padding: 26px 24px 30px; transform: rotate(-.4deg); }
.t-librarycard .vb + .vb { margin-top: 28px; }
.t-librarycard .vb .sl { border-bottom: 0; padding-top: 14px; color: #211d17; font-size: 17px; }
.t-librarycard .cap { font-size: 14px; color: #4a4338; }
.t-librarycard .say { margin-top: 10px; font-size: 15px; line-height: 1.45; text-wrap: pretty; }
.t-librarycard .plot { padding: 14px 0 6px; border-bottom: 1px solid var(--rule); }
.t-librarycard .key { display: flex; align-items: center; gap: 8px; margin-top: 10px; font-size: 15px; color: #4a4338; }
.t-librarycard .key i { display: inline-block; width: 14px; height: 14px; }
.t-librarycard .key i:not(:first-child) { margin-left: 10px; }
/* Special Elite has one weight: a typed card emphasises in the stamp ink and by size, never a faux bold. */
.t-librarycard { --rs-title-weight: 400; --rs-font: var(--face); --rs-font-h: var(--face); --rs-ink: #211d17; --rs-muted: #4f483c; --rs-acc: var(--stamp); --rs-base: 14px; --rs-kick-case: none; --rs-kick-track: 0; }
.t-librarycard .sign { display: flex; justify-content: space-between; align-items: flex-end; margin-top: 42px; font-size: 15px; }
.t-librarycard .sign span:first-child { flex: 1; border-top: 1px solid #211d17; padding-top: 4px; margin-right: 18px; }
.t-librarycard .sign i { font: italic 400 22px/1 'Pinyon Script', cursive; display: block; margin-bottom: -2px; transform: translateY(-26px); height: 0; color: #2a3a7a; }
.t-librarycard .rec { margin-top: 16px; font-size: 15px; line-height: 1.5; text-wrap: pretty; }
.t-librarycard .src { margin-top: 10px; font-size: 15px; line-height: 1.5; color: #4a4338; text-wrap: pretty; }
.t-librarycard .src .logos { display: flex; gap: 12px; margin-bottom: 6px; color: #211d17; }
.t-librarycard .src .mk { width: 16px; height: 16px; }
.t-librarycard .pocket { position: relative; z-index: 2; margin: -96px -8px 0; height: 118px; background: linear-gradient(180deg, rgba(255,255,255,.18), transparent 30%), var(--pocket);
  clip-path: polygon(0 18px, 34% 18px, 40% 0, 60% 0, 66% 18px, 100% 18px, 100% 100%, 0 100%); box-shadow: 0 -2px 4px rgba(0,0,0,.18); text-align: center; padding-top: 46px; color: #3b3021; }
.t-librarycard .pocket::before { content: ""; position: absolute; left: 10px; right: 10px; top: 28px; bottom: 10px; border: 1.5px dashed rgba(59,48,33,.45); border-top: 0; }
.t-librarycard .pocket b { display: block; font: 400 14px/1.4 var(--face); letter-spacing: 0; }
.t-librarycard .pocket small { font: 400 14px/1.4 var(--face); letter-spacing: 0; }
`,
    render(ed, skin) {
      const B = EXPLORER.blocks;
      const INK = "#211d17";
      const SOFT = "#4f483c";
      // The verso's measure: the card's width inside the desk and its own padding.
      const W = 440;
      const BAR_W = W - 86 - 92 - 8;
      const PLOT = { font: "Special Elite", size: 14, ink: INK, soft: SOFT, rule: "var(--rule)", base: INK, valueWeight: 400 };
      // A black pad prints the same tone as the ribbon, so GAIA's share takes a worn grey impression.
      const fills = [INK, skin.ink.id === "black" ? "#8a8274" : "var(--stamp)"];
      const swatch = (k) => `<i style="background:${fills[k % 2]}"></i>`;
      // Charts are typed on a second card from the same drawer: the circulation record, ruled like the front.
      const chart = (c) => {
        let body;
        if (c.chart === "bar" || c.chart === "stacked_bar") {
          const sums = B.totals(c);
          const max = Math.max(...sums);
          const rows = c.x.map((lab, i) => {
            let x = 0;
            const segs = c.series.map((s, k) => {
              const w = (s.values[i] / max) * BAR_W;
              const seg = B.rect(x, 0, w, 14, fills[k % 2]);
              x += w;
              return seg;
            });
            return `<div class="row br"><span>${esc(lab)}</span><span class="it">${B.svg(BAR_W, 14, segs.join(""))}</span><span class="due">${esc(B.fmt(sums[i]))}</span></div>`;
          });
          const key = c.series.length > 1 ? `<p class="key">${B.legend(c, swatch).join("")}</p>` : "";
          body = `<div class="cols"><span>Date</span><span>${esc(cap(c.unit || c.series[0].unit))}</span><span>In all</span></div>${rows.join("")}${key}`;
        } else if (c.chart === "line") {
          const plot = B.line(c, { ...PLOT, w: W, h: 150, gutter: 30, lines: [{ color: "var(--stamp)", width: 2 }, { color: INK, width: 2, dash: "5 4" }] });
          const key = c.series.length > 1 ? `<p class="key">${c.series.map((s, k) => `${swatch(k)}${esc(s.name)} ${esc(s.total)}`).join("")}</p>` : "";
          body = `<div class="plot">${plot}</div>${key}`;
        } else {
          const sp = c.series[0];
          body = `<div class="row br"><span>${esc(c.x[0])}&ndash;${esc(c.x[c.x.length - 1])}</span><span class="it">${B.spark(c, { ...PLOT, w: BAR_W, h: 34, line: "var(--stamp)" })}</span><span class="due">${esc(sp.total)}</span></div>`;
        }
        return `<div class="vb" data-block="chart"><div class="sl">${esc(c.title)}</div><p class="cap">${esc(B.facts(c))}</p>${body}<p class="say">${esc(c.takeaway)}</p></div>`;
      };
      const progress = (p) =>
        `<div class="vb" data-block="progress"><div class="sl">${esc(p.statement)}</div><div class="row br"><span>To date</span><span class="it">${B.cells(p, { w: BAR_W, h: 18, gap: 6, on: "var(--stamp)", offStroke: INK })}</span><span class="due">${p.done} of ${p.total}</span></div></div>`;
      const verso = [];
      const R = {
        lead: (b) => `<div class="bk">${B.lead(b, { kicker: "Reserved for you" })}</div>`,
        items: (b) => `<div class="bk">${B.section(b.heading, B.items(b))}</div>`,
        calendar: (b) => `<div class="bk">${B.section("Checked out today", B.events(b, { clock: "t24", allDay: "All day" }))}</div>`,
        quote: (q) => `<div class="blk q" data-block="quote"><p>&ldquo;${esc(q.text)}&rdquo;</p><p class="by">&mdash; ${esc(q.author)}, by ${esc(q.app)}</p></div>`,
        note: (n) => `<div class="blk" data-block="note"><p><b>Librarian's note.</b> ${esc(n.text)}</p></div>`,
        chart: (c) => (verso.push(chart(c)), ""),
        progress: (p) => (verso.push(progress(p)), ""),
      };
      const parts = B.layout(ed, R);
      const s = ed.stats;
      const back = verso.length
        ? `<div class="card verso">${grain("lc-g2", 0.8)}<div class="lib"><span>Circulation record · GAIA</span><span>Card No ${ed.editionNo}, verso</span></div>${verso.join("")}</div>`
        : "";
      return `<article class="t-librarycard" style="--card:${skin.stock.card}; --rule:${skin.stock.rule}; --pocket:${skin.stock.pocket}; --desk:${skin.stock.desk}; --stamp:${skin.ink.stamp}; --face:${skin.face.stack}">
<div class="stack"><div class="card" data-paper>${grain("lc-g", 0.8)}<i class="notch" aria-hidden="true"></i>
  <div class="lib"><span>Ex libris · GAIA circulation</span><span>${esc(ed.dateLong)}</span></div>
  <div class="tt"><h1>The ${esc(ed.weekday)}<br>Brief</h1><div class="no">Card<b>No ${ed.editionNo}</b></div></div>
  <p class="deck">${esc(ed.deck)}</p>
  ${EXPLORER.fold(parts).join("")}
  <div class="sign"><span><i>GAIA</i>Prepared by GAIA — librarian on duty</span><span>Issued ${esc(ed.time24)}</span></div>
  ${s ? `<p class="rec">This card's record: items returned ${s.done}${s.you && s.gaia ? ` (${s.you} by your hand, ${s.gaia} by GAIA)` : ""}.${s.mail ? ` Correspondence filed ${s.mail}.` : ""}${s.focus ? ` Focus held ${esc(s.focus)}.` : ""}</p>` : ""}
  ${ed.sources.length ? `<div class="src" data-block="sources"><p class="logos">${ed.sources.map((a) => B.logo(a.logo, { cls: "mk" })).join("")}</p><p>Catalogued from your ${esc(andList(ed.sources.map((a) => a.name)))}.</p></div>` : ""}
</div>
<div class="pocket"><b>Return to GAIA circulation</b><small>Date due is stamped · card No ${ed.editionNo}</small></div></div>
${back}
</article>`;
    },
  });

  /* ==========================================================================
     THE MENU — signature moves from the desktop original:
       a framed card; G A I A spaced; an italic "menu du jour"; spaced-caps
       date line; courses headed "— FIRST —", "— SECOND —", "— TO FINISH —";
       dish names in Playfair; times spelled out in small caps ("HALF PAST
       ONE"); italic descriptions; "prepared overnight"; "awaiting the
       table's decision" with gold "to approve —"; "digestif — the evening is
       yours."; a couverts colophon.
     Added detail: gold-foil rules with a sheen, a bevelled card edge,
     letterpress impression, laid-paper texture.
     ======================================================================== */
  EXPLORER.register({
    id: "menu",
    name: "The Menu",
    axes: {
      card: [
        { id: "cream", label: "cream + gold", ground: "#f5efe0", card: "#fbf7ec", ink: "#2a221a", soft: "#5f5244", gold: "#7a5915", foil: "#c9a24a" },
        { id: "noir", label: "noir + gold", ground: "#100e0b", card: "#1a1713", ink: "#f1e8d4", soft: "#c4b9a2", gold: "#d8b46c", foil: "#d8b46c" },
        { id: "sage", label: "sage + rust", ground: "#dfe6d6", card: "#f1f4ec", ink: "#1e2a21", soft: "#45544a", gold: "#8a3a17", foil: "#b4673f" },
        { id: "blush", label: "blush + bordeaux", ground: "#f1dcd4", card: "#f9ece6", ink: "#2b1b1e", soft: "#5f464a", gold: "#7c1d2c", foil: "#a8495a" },
      ],
      face: [
        { id: "cormorant", label: "Cormorant + EB Garamond", disp: "'Cormorant', serif", text: "'EB Garamond', serif" },
      ],
      border: [
        { id: "foil", label: "foil keyline" },
        { id: "double", label: "double keyline" },
      ],
    },
    css: `
.t-menu { box-sizing: border-box; width: 540px; padding: 30px 28px; background: var(--ground); }
.t-menu * { box-sizing: border-box; margin: 0; padding: 0; }
.t-menu .card { position: relative; isolation: isolate; background: repeating-linear-gradient(0deg, rgba(0,0,0,.018) 0 1px, transparent 1px 6px), var(--card); color: var(--ink); text-align: center;
  font: 400 18px/1.45 var(--text); padding: 44px 36px 40px; box-shadow: inset 0 0 0 1px rgba(255,255,255,.4), inset 0 0 0 10px var(--card), inset 0 0 0 11px var(--foil), 0 10px 26px -12px rgba(0,0,0,.4), 0 1px 0 rgba(0,0,0,.08);
  text-shadow: 0 .5px 0 rgba(0,0,0,.12); }
.t-menu .card.dbl { box-shadow: inset 0 0 0 1px rgba(255,255,255,.4), inset 0 0 0 10px var(--card), inset 0 0 0 11px var(--foil), inset 0 0 0 15px var(--card), inset 0 0 0 16px var(--foil), 0 10px 26px -12px rgba(0,0,0,.4), 0 1px 0 rgba(0,0,0,.08); }
.t-menu .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .12; z-index: -1; }
.t-menu .sc { font-variant-caps: small-caps; letter-spacing: .04em; }
.t-menu .house { font-size: 17px; letter-spacing: .3em; padding-left: .3em; }
.t-menu h1 { font: italic 400 40px/1.1 var(--disp); margin-top: 10px; }
.t-menu .date { font-size: 16px; color: var(--soft); margin-top: 10px; }
.t-menu .deck { font-style: italic; font-size: 20px; line-height: 1.4; margin: 18px auto 0; max-width: 24em; }
.t-menu .foil { width: 90px; height: 2px; margin: 26px auto; background: linear-gradient(90deg, transparent, var(--foil) 20%, #fff3c9 50%, var(--foil) 80%, transparent); }
.t-menu .mq { padding: 4px 0; }
.t-menu .mq .q { font: italic 400 22px/1.35 var(--disp); max-width: 20em; margin: 0 auto; text-wrap: balance; }
.t-menu .mq .when { font-size: 16px; color: var(--soft); margin-top: 8px; }
.t-menu .mnote { font-style: italic; font-size: 18px; line-height: 1.45; color: var(--soft); max-width: 22em; margin: 0 auto; text-wrap: balance; }
.t-menu { --rs-title-weight: 600; --rs-font: var(--text); --rs-font-h: var(--disp); --rs-ink: var(--ink); --rs-muted: var(--soft); --rs-acc: var(--gold); --rs-base: 15px; --rs-h-style: italic; --rs-kick-case: none; --rs-kick-variant: small-caps; --rs-kick-track: .08em; }
.t-menu .dig { font: italic 400 23px/1.2 var(--disp); }
.t-menu .cov { margin-top: 22px; font-size: 16px; line-height: 1.6; text-wrap: balance; color: var(--soft); }
.t-menu .src { margin-top: 22px; }
.t-menu .src .cov { margin-top: 8px; }
.t-menu .src .logos { display: flex; justify-content: center; gap: 14px; color: var(--soft); }
.t-menu .src .mk { width: 16px; height: 16px; }
`,
    render(ed, skin) {
      const B = EXPLORER.blocks;
      const foil = `<div class="foil" aria-hidden="true"></div>`;
      // A menu prints dishes and prose: no plotted chart and no goal have a line on its card (capabilities.py).
      const R = {
        lead: (b) => B.lead(b, { kicker: "Chef's note" }),
        items: (b) => B.section(b.heading, B.items(b)),
        calendar: (b) => B.section("The day's courses", B.events(b, { clock: "t24", allDay: "All day" })),
        quote: (q) => `<div class="mq" data-block="quote"><p class="q">&ldquo;${esc(q.text)}&rdquo;</p><p class="when sc">${esc(q.author)}, by ${esc(q.app)}</p></div>`,
        note: (n) => `<p class="mnote" data-block="note">${esc(n.text)}</p>`,
      };
      const parts = B.layout(ed, R);
      const s = ed.stats;
      return `<article class="t-menu" style="--ground:${skin.card.ground}; --card:${skin.card.card}; --ink:${skin.card.ink}; --soft:${skin.card.soft}; --gold:${skin.card.gold}; --foil:${skin.card.foil}; --disp:${skin.face.disp}; --text:${skin.face.text}">
<div class="card${skin.border.id === "double" ? " dbl" : ""}" data-paper>${grain("mn-g", 0.8)}
  <div class="house">GAIA</div>
  <h1>menu du jour</h1>
  <p class="date sc">${esc(ed.weekday)} · ${ed.day} ${esc(ed.month)} ${ed.year} · service No ${ed.editionNo}</p>
  <p class="deck">${esc(ed.deck)}</p>
  ${foil}${EXPLORER.fold(parts).join(foil)}${foil}
  <p class="dig">digestif — the evening is yours.</p>
  ${s ? `<p class="cov sc">Couverts ${s.done}${s.you && s.gaia ? ` — ${s.you} by your hand, ${s.gaia} by the kitchen` : ""}${s.mail ? ` · correspondence ${s.mail}` : ""}${s.focus ? ` · ${esc(s.focus)} of focus` : ""}</p>` : ""}
  ${ed.sources.length ? `<div class="src" data-block="sources"><p class="logos">${ed.sources.map((a) => B.logo(a.logo, { cls: "mk" })).join("")}</p><p class="cov sc">With produce from your ${esc(andList(ed.sources.map((a) => a.name)))}</p></div>` : ""}
  <p class="cov sc">GAIA · service No ${ed.editionNo} · seated ${esc(ed.time24)}</p>
</div></article>`;
    },
  });

  /* ==========================================================================
     THE INVOICE — signature moves from the desktop original:
       the bracketed [GAIA Studios] wordmark and a big Invoice title; a
       ruled line-item table with section rows; grey 0.00 amounts on work
       GAIA prepaid overnight; a right-hand totals block ending in
       "Balance due: 1 Friday"; payment-pending items; a QR panel.
     Round 5 re-composition: an amount-due panel up top (where real
     invoices put the number that matters), approvals as tick-box lines,
     a rubber "Paid in advance" stamp on the prepaid section, and a
     perforated remittance slip. No tracked capitals anywhere.
     ======================================================================== */
  EXPLORER.register({
    id: "invoice",
    name: "The Invoice",
    axes: {
      paper: [
        { id: "vermilion", label: "vermilion on cream", paper: "#f8f3ea", ink: "#1d1a17", soft: "#57504a", hair: "#e2d8c8", desk: "#c9b9a2", acc: "#c0301c", tint: "#f6e1d6" },
        { id: "cobalt", label: "cobalt on white", paper: "#fbfbf8", ink: "#141824", soft: "#4f5566", hair: "#dfe2ea", desk: "#b2bccf", acc: "#2147c4", tint: "#e3e9f8" },
        { id: "green", label: "racing green on bone", paper: "#f4f2ea", ink: "#141a16", soft: "#4c534d", hair: "#dcdcd0", desk: "#aab3a3", acc: "#0f6640", tint: "#dcebe0" },
        { id: "ink", label: "black on white", paper: "#f9f8f5", ink: "#121317", soft: "#55565c", hair: "#e0dfda", desk: "#c4c2bb", acc: "#121317", tint: "#ebeae5" },
      ],
      figures: [
        { id: "heros", label: "TeX Gyre Heros figures", fig: "'TeX Gyre Heros', sans-serif" },
      ],
      stub: [
        { id: "remit", label: "remittance slip" },
        { id: "none", label: "no slip" },
      ],
    },
    css: `
.t-invoice { box-sizing: border-box; width: 540px; padding: 30px 22px 38px; background: var(--desk); color: var(--ink); font: 400 17px/1.45 'TeX Gyre Heros', sans-serif; }
.t-invoice * { box-sizing: border-box; margin: 0; padding: 0; }
.t-invoice .doc { position: relative; filter: drop-shadow(0 14px 18px rgba(0,0,0,.2)) drop-shadow(0 1px 2px rgba(0,0,0,.16)); }
.t-invoice .sheet, .t-invoice .slip { position: relative; isolation: isolate; background: var(--paper); overflow: hidden; }
.t-invoice .sheet { padding: 30px 28px 30px; }
.t-invoice .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .1; z-index: -1; }
.t-invoice .hd { display: flex; justify-content: space-between; align-items: flex-start; }
.t-invoice .brand { font-size: 19px; font-weight: 800; letter-spacing: -.01em; color: var(--acc); }
.t-invoice .brand span { display: block; font-size: 14px; font-weight: 400; color: var(--soft); margin-top: 2px; letter-spacing: 0; }
.t-invoice h1 { font-size: 52px; line-height: .9; font-weight: 800; letter-spacing: -.045em; text-align: right; }
.t-invoice h1 small { display: block; font: 400 15px/1.4 var(--fig); letter-spacing: 0; color: var(--soft); margin-top: 8px; }
.t-invoice .due { display: grid; grid-template-columns: 1fr auto; align-items: end; gap: 16px; margin-top: 26px; padding: 18px 20px; background: var(--tint); border-radius: 4px; }
.t-invoice .due .k { font-size: 15px; color: var(--soft); }
.t-invoice .due b { display: block; font-size: 40px; line-height: 1.05; font-weight: 800; letter-spacing: -.03em; color: var(--acc); }
.t-invoice .due .r { text-align: right; font-size: 15px; line-height: 1.5; }
.t-invoice .parties { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 24px; }
.t-invoice .k { font-size: 15px; color: var(--soft); }
.t-invoice .src { display: flex; align-items: center; gap: 12px; margin-top: 30px; padding-top: 14px; border-top: 1px solid var(--hair); }
.t-invoice .src .logos { display: flex; gap: 8px; flex: none; color: var(--ink); }
.t-invoice .src .mk { width: 16px; height: 16px; }
.t-invoice .li > span:first-child { text-wrap: pretty; }
.t-invoice .memo { margin-top: 26px; font-size: 22px; line-height: 1.3; font-weight: 700; letter-spacing: -.01em; }
.t-invoice section { margin-top: 34px; }
.t-invoice h2 { display: flex; justify-content: space-between; align-items: baseline; font-size: 20px; font-weight: 800; letter-spacing: -.01em; padding-bottom: 10px; border-bottom: 2px solid var(--ink); }
.t-invoice h2 > span:last-child { font: 400 15px/1 var(--fig); color: var(--soft); }
.t-invoice small.n { display: block; font-size: 15px; color: var(--soft); }
.t-invoice .li { display: grid; grid-template-columns: 1fr 60px; gap: 10px; padding: 11px 0; border-bottom: 1px solid var(--hair); align-items: baseline; }
.t-invoice .li .f { font: 400 16px/1.4 var(--fig); font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.t-invoice .cols { display: grid; grid-template-columns: 1fr 60px; gap: 10px; padding: 10px 0 2px; font-size: 15px; color: var(--soft); }
.t-invoice .cols span + span { text-align: right; }
.t-invoice .tot { margin: 26px 0 0 auto; width: 300px; }
.t-invoice .tot div { display: flex; justify-content: space-between; padding: 6px 0; font-size: 16px; }
.t-invoice .tot b { font: 400 16px/1.4 var(--fig); font-variant-numeric: tabular-nums; }
.t-invoice .tot .bal { margin-top: 6px; padding-top: 10px; border-top: 3px double var(--ink); font-size: 19px; font-weight: 800; }
.t-invoice .tot .bal b { font: 800 19px/1.4 var(--fig); color: var(--acc); }
.t-invoice .perf { position: relative; height: 24px; background: var(--paper); }
.t-invoice .perf::before { content: ""; position: absolute; left: 0; right: 0; top: 11px; height: 2px; background: radial-gradient(circle, var(--desk) 1.3px, transparent 1.7px) 0 0 / 7px 2px repeat-x; }
.t-invoice .perf span { position: absolute; right: 22px; top: 1px; font-size: 14px; font-style: italic; color: var(--soft); background: var(--paper); padding: 0 8px; }
.t-invoice .slip { display: grid; grid-template-columns: 1fr 108px; gap: 20px; align-items: center; padding: 22px 28px 24px; }
.t-invoice .slip b { display: block; font-size: 26px; font-weight: 800; letter-spacing: -.02em; color: var(--acc); }
.t-invoice .qr { width: 108px; height: 108px; display: block; }
.t-invoice .ref { font: 400 14px/1.3 var(--fig); text-align: center; margin-top: 6px; color: var(--soft); }
.t-invoice .memo { margin-bottom: 16px; }
.t-invoice section { margin-bottom: 14px; }
.t-invoice .wk { display: grid; gap: 8px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--hair); font-size: 16px; }
.t-invoice .wk .f { font: 400 16px/1.4 var(--fig); font-variant-numeric: tabular-nums; text-align: right; }
.t-invoice .wk svg { display: block; }
.t-invoice .wk.cols2 { font-size: 15px; color: var(--soft); border-bottom: 0; padding: 10px 0 2px; }
.t-invoice .wk.cols2 span:nth-child(n+3) { text-align: right; white-space: nowrap; }
.t-invoice .wk i, .t-invoice .sw { display: inline-block; width: 9px; height: 9px; margin-right: 5px; }
.t-invoice .wk.sum { border-top: 3px double var(--ink); border-bottom: 0; margin-top: -1px; font-weight: 800; }
.t-invoice .wk.sum .f { font-weight: 800; }
.t-invoice .plot { padding: 12px 0 8px; border-bottom: 1px solid var(--hair); }
.t-invoice .say { margin-top: 12px; font-size: 16px; line-height: 1.45; text-wrap: pretty; }
.t-invoice .spk, .t-invoice .cells { display: block; margin-top: 8px; }
.t-invoice .q { margin-top: 12px; font-size: 18px; line-height: 1.4; text-wrap: pretty; }
.t-invoice small.n { margin-top: 4px; }
.t-invoice .nb { margin-top: 12px; padding: 12px 14px; background: var(--tint); border-radius: 4px; font-size: 16px; line-height: 1.45; text-wrap: pretty; }
.t-invoice { --rs-font: 'TeX Gyre Heros', sans-serif; --rs-font-h: 'TeX Gyre Heros', sans-serif; --rs-ink: var(--ink); --rs-muted: var(--soft); --rs-acc: var(--acc); --rs-base: 15px; }
`,
    render(ed, skin) {
      const B = EXPLORER.blocks;
      const no = String(ed.editionNo).padStart(4, "0");
      const owed = ed.awaiting ? `${ed.awaiting} item${ed.awaiting > 1 ? "s" : ""}` : "Nothing";
      const LOGO = { mode: "color" };
      // The sheet's measure inside its padding, and the figure columns a line-item table keeps.
      const W = 440;
      const FIG = 52;
      const GAP = 8;
      // The black-only paper has no accent to tell the second series by, so it takes the soft grey.
      const second = skin.paper.acc === skin.paper.ink ? "var(--soft)" : "var(--acc)";
      const fills = ["var(--ink)", second];
      const PLOT = { font: "TeX Gyre Heros", size: 14, ink: "var(--ink)", soft: "var(--soft)", rule: "var(--hair)", base: "var(--ink)", valueWeight: 700 };
      const head = (title, right) => `<h2>${esc(title)}<span>${esc(right)}</span></h2>`;
      // Bars are billed as a line-item table: one line per day, its bar, a figure per series, totals on a double rule.
      const table = (c) => {
        const k = c.series.length;
        const figs = k > 1 ? k + 1 : 1;
        const bw = W - 64 - figs * FIG - (figs + 1) * GAP;
        const cols = `grid-template-columns: 64px minmax(0, 1fr) repeat(${figs}, ${FIG}px)`;
        const sums = B.totals(c);
        const max = Math.max(...sums);
        const line = (lab, i) => {
          let x = 0;
          const segs = c.series.map((s, j) => {
            const w = (s.values[i] / max) * bw;
            const seg = B.rect(x, 0, w, 10, k > 1 ? fills[j % 2] : second);
            x += w;
            return seg;
          });
          const each = k > 1 ? c.series.map((s) => `<span class="f">${esc(s.shown[i])}</span>`).join("") : "";
          return `<div class="wk" style="${cols}"><span>${esc(lab)}</span><span>${B.svg(bw, 10, segs.join(""))}</span>${each}<span class="f">${esc(B.fmt(sums[i]))}</span></div>`;
        };
        const named = k > 1 ? c.series.map((s, j) => `<span><i style="background:${fills[j % 2]}"></i>${esc(s.name)}</span>`).join("") + "<span>Total</span>" : `<span>${esc(cap(c.unit || c.series[0].unit))}</span>`;
        const total = B.fmt(sums.reduce((a, v) => a + v, 0));
        const sum = `<div class="wk sum" style="${cols}"><span>In all</span><span></span>${k > 1 ? c.series.map((s) => `<span class="f">${esc(s.total)}</span>`).join("") : ""}<span class="f">${esc(total)}</span></div>`;
        return `<div class="wk cols2" style="${cols}"><span>Day</span><span>${k > 1 ? esc(cap(c.unit || "")) : ""}</span>${named}</div>${c.x.map(line).join("")}${sum}`;
      };
      const usage = (c) => {
        const plot = B.line(c, { ...PLOT, w: W, h: 150, gutter: 30, lines: [{ color: second, width: 2 }, { color: "var(--ink)", width: 2, dash: "5 4" }] });
        const key = c.series.length > 1 ? `<div class="cols"><span>${c.series.map((s, j) => `<i class="sw" style="background:${j ? "var(--ink)" : second}"></i>${esc(s.name)}`).join("&ensp;")}</span><span></span></div>` : "";
        const lines = c.series.map((s) => `<div class="li"><span>${esc(s.name)}, ${c.x.length} days</span><span class="f">${esc(s.total)}</span></div>`).join("");
        return `${key}<div class="plot">${plot}</div>${lines}`;
      };
      const spark = (c) => {
        const s = c.series[0];
        return `<div class="li sp"><span>${esc(s.name)}<span class="spk">${B.spark(c, { ...PLOT, w: 260, h: 34, line: "var(--acc)" })}</span></span><span class="f">${esc(s.total)}</span></div>`;
      };
      const R = {
        lead: (b) => B.lead(b, { kicker: "Line 1", ...LOGO }),
        items: (b) => B.section(b.heading, B.items(b, LOGO)),
        calendar: (b) => B.section("Today, billable", B.events(b, { clock: "t24", allDay: "All day", ...LOGO })),
        chart: (c) => {
          const body = c.chart === "line" ? usage(c) : c.chart === "spark" ? spark(c) : table(c);
          return `<section data-block="chart">${head(c.title, B.facts(c))}${body}<p class="say">${esc(c.takeaway)}</p></section>`;
        },
        quote: (q) => `<section data-block="quote">${head("Correspondence", q.app)}<p class="q">&ldquo;${esc(q.text)}&rdquo;</p><small class="n">${esc(q.author)}, by ${esc(q.app)}</small></section>`,
        progress: (p) => `<section data-block="progress">${head("Plans", `${p.done} of ${p.total}`)}<div class="li goal"><span>${esc(p.statement)}<span class="cells">${B.cells(p, { w: 220, h: 12, gap: 4, on: "var(--acc)", offStroke: "var(--soft)" })}</span></span><span class="f">${p.done} of ${p.total}</span></div></section>`,
        note: (n) => `<section data-block="note">${head("Notes", "")}<p class="nb">${esc(n.text)}</p></section>`,
      };
      const secs = B.layout(ed, R);
      const s = ed.stats;
      const tot = s ? `<div class="tot"><div><span>Settled yesterday</span><b>${s.done}${s.you && s.gaia ? ` (${s.you} you, ${s.gaia} GAIA)` : ""}</b></div>${s.mail ? `<div><span>Correspondence</span><b>${s.mail} filed</b></div>` : ""}${s.focus ? `<div><span>Focus held today</span><b>${esc(s.focus)}</b></div>` : ""}<div class="bal"><span>Awaiting you</span><b>${owed}</b></div></div>` : "";
      const slip = skin.stub.id === "remit"
        ? `<div class="perf"><span>Detach and return</span></div><div class="slip">${grain("iv-g2", 0.9)}<div><span class="k">Remittance for invoice ${no}</span><b>${owed}</b><span class="k">Payable to GAIA Studios, on waking</span></div><div>${EXPLORER.code(ed.codes.qr, "qr")}<p class="ref">Ref. GA-${no}</p></div></div>`
        : "";
      return `<article class="t-invoice" style="--paper:${skin.paper.paper}; --ink:${skin.paper.ink}; --soft:${skin.paper.soft}; --hair:${skin.paper.hair}; --desk:${skin.paper.desk}; --acc:${skin.paper.acc}; --tint:${skin.paper.tint}; --fig:${skin.figures.fig}">
<div class="doc" data-paper>
  <div class="sheet">${grain("iv-g", 0.9)}
    <div class="hd"><div class="brand">[GAIA Studios]<span>Your desk, ${esc(ed.dateLong)}</span></div><h1>Invoice<small>No. ${no}</small></h1></div>
    <div class="due"><div><span class="k">Awaiting you</span><b>${owed}</b></div><div class="r">Issued ${esc(ed.time24)}<br>Due on waking</div></div>
    <div class="parties"><div><span class="k">Billed to</span><br>${ed.recipient ? esc(ed.recipient.name) : "You"}</div><div><span class="k">From</span><br>GAIA Studios, edition ${ed.editionNo}</div></div>
    <p class="memo">${esc(ed.deck)}</p>
    ${EXPLORER.fold(secs).join("")}
    ${tot}
    ${ed.sources.length ? `<div class="src" data-block="sources"><span class="logos">${ed.sources.map((a) => B.logo(a.logo, { mode: "color", cls: "mk" })).join("")}</span><span class="k">Prepared from your ${esc(andList(ed.sources.map((a) => a.name)))}</span></div>` : ""}
  </div>
  ${slip}
</div></article>`;
    },
  });
})();
