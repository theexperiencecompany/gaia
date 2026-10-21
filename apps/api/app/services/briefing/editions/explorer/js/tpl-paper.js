/* ============================================================================
   tpl-paper.js (round 2) — The Library Card, The Menu and The Invoice on a
   540 px portrait canvas (export at 3x). Body 17 px or larger.
   Reading order: headline -> needs you -> today -> done overnight -> stats;
   empty sections are omitted.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
  const grain = (id, freq) =>
    `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  /* Rubber-stamp ink voids: a thresholded noise mask applied to the impression. */
  const inkMask = (id, seed) =>
    `<svg width="0" height="0" style="position:absolute" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="1.4" numOctaves="2" seed="${seed}" result="n"/><feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -1.4 1.5" result="m"/><feComposite in="SourceGraphic" in2="m" operator="in"/></filter></svg>`;
  /* Deterministic per-row variance so no two stamps land the same way. */
  const jitter = (i) => ({ r: [-4, 2, -1, 3, -3, 1, 4, -2][i % 8], o: [0.97, 0.88, 0.93, 0.86, 1, 0.9, 0.87, 0.95][i % 8] });

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
        { id: "amtype", label: "American Typewriter", stack: "'American Typewriter', 'Courier New', monospace" },
        { id: "courier", label: "Courier", stack: "'Courier New', Courier, monospace" },
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
.t-librarycard .cols { display: grid; grid-template-columns: 86px 1fr 92px; margin-top: 16px; padding-bottom: 4px; border-bottom: 1px solid #211d17; font-size: 14px; letter-spacing: 0; }
.t-librarycard .cols span:last-child { text-align: right; }
.t-librarycard .sl { font-size: 15px; letter-spacing: 0; color: #4a4338; padding: 12px 0 4px; border-bottom: 1px solid var(--rule); }
.t-librarycard .row { position: relative; display: grid; grid-template-columns: 86px 1fr 92px; align-items: start; padding: 9px 0; border-bottom: 1px solid var(--rule); }
.t-librarycard .row::before { content: ""; position: absolute; left: 80px; top: 0; bottom: 0; border-left: 1px solid #c45a4b; }
.t-librarycard .row .it { padding-left: 8px; text-wrap: pretty; }
.t-librarycard .ditto { display: inline-block; width: 64px; text-align: center; font-size: 24px; line-height: 1; color: #3a342b; }
.t-librarycard .row .it small { display: block; font-size: 15px; color: #4f483c; }
.t-librarycard .row .due { text-align: right; font-variant-numeric: tabular-nums; }
.t-librarycard .stamp { display: inline-block; border: 2px solid var(--stamp); color: var(--stamp); border-radius: 3px; padding: 1px 5px; font: 700 14px/1.25 'Courier New', monospace; letter-spacing: 0; filter: url(#lc-ink); }
.t-librarycard .verb { font-weight: 700; margin-right: 6px; }
.t-librarycard .sign { display: flex; justify-content: space-between; align-items: flex-end; margin-top: 42px; font-size: 15px; }
.t-librarycard .sign span:first-child { flex: 1; border-top: 1px solid #211d17; padding-top: 4px; margin-right: 18px; }
.t-librarycard .sign i { font: italic 600 22px/1 'Snell Roundhand', 'Apple Chancery', cursive; display: block; margin-bottom: -2px; transform: translateY(-26px); height: 0; color: #2a3a7a; }
.t-librarycard .rec { margin-top: 16px; font-size: 15px; line-height: 1.5; }
.t-librarycard .pocket { position: relative; z-index: 2; margin: -96px -8px 0; height: 118px; background: linear-gradient(180deg, rgba(255,255,255,.18), transparent 30%), var(--pocket);
  clip-path: polygon(0 18px, 34% 18px, 40% 0, 60% 0, 66% 18px, 100% 18px, 100% 100%, 0 100%); box-shadow: 0 -2px 4px rgba(0,0,0,.18); text-align: center; padding-top: 46px; color: #3b3021; }
.t-librarycard .pocket::before { content: ""; position: absolute; left: 10px; right: 10px; top: 28px; bottom: 10px; border: 1.5px dashed rgba(59,48,33,.45); border-top: 0; }
.t-librarycard .pocket b { display: block; font: 400 14px/1.4 var(--face); letter-spacing: 0; }
.t-librarycard .pocket small { font: 400 14px/1.4 var(--face); letter-spacing: 0; }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const mon = `${ed.monthShort.toUpperCase()} ${ed.day}`;
      let k = 0;
      const stamp = (txt) => {
        const j = jitter(k++);
        return `<span class="stamp" style="transform:rotate(${j.r}deg); opacity:${j.o}">${esc(txt)}</span>`;
      };
      let first = true;
      const row = (it, due) => {
        const date = first ? stamp(mon) : `<span class="ditto" aria-label="same date">"</span>`;
        first = false;
        return `<div class="row" data-role="body"><span>${date}</span><span class="it">${it}</span><span class="due">${due}</span></div>`;
      };
      const parts = [];
      if (needs.length) {
        first = true;
        parts.push(`<div class="sl">Awaiting your signature</div>${needs.map((d) => row(`<span class="verb">${esc(d.verb)}</span>${esc(d.label)}${d.note ? `<small>${esc(d.note)}</small>` : ""}`, "____")).join("")}`);
      }
      if (c.today.length) {
        first = true;
        parts.push(`<div class="sl">Checked out — today</div>${c.today.map((e) => row(`${esc(e.label)}${e.note ? `<small>${esc(e.note)}</small>` : ""}`, e.t24 ? esc(e.t24) : "EOD")).join("")}`);
      }
      if (c.overnight.length) {
        first = true;
        parts.push(`<div class="sl">Returned overnight by GAIA</div>${c.overnight.map((e) => row(`${esc(e.label)}${e.note ? `<small>${esc(e.note)}</small>` : ""}`, stamp(e.tag))).join("")}`);
      }
      const s = c.stats;
      return `<article class="t-librarycard" style="--card:${skin.stock.card}; --rule:${skin.stock.rule}; --pocket:${skin.stock.pocket}; --desk:${skin.stock.desk}; --stamp:${skin.ink.stamp}; --face:${skin.face.stack}">
${inkMask("lc-ink", 7)}
<div class="stack"><div class="card">${grain("lc-g", 0.8)}<i class="notch" aria-hidden="true"></i>
  <div class="lib"><span>Ex libris · GAIA circulation</span><span>${esc(ed.dateLong)}</span></div>
  <div class="tt"><h1>The ${esc(ed.weekday)}<br>Brief</h1><div class="no">Card<b>No ${ed.editionNo}</b></div></div>
  <p class="deck">${esc(ed.deck)}</p>
  <div class="cols"><span>Date</span><span>Item</span><span>Due</span></div>
  ${parts.join("")}
  <div class="sign"><span><i>GAIA</i>Prepared by GAIA — librarian on duty</span><span>Issued ${esc(ed.time24)}</span></div>
  ${s ? `<p class="rec">This card's record: items returned ${s.done}${s.you && s.gaia ? ` (${s.you} by your hand, ${s.gaia} by GAIA)` : ""}.${s.mail ? ` Correspondence filed ${s.mail}.` : ""}${s.focus ? ` Focus held ${esc(s.focus)}.` : ""}</p>` : ""}
</div>
<div class="pocket"><b>Return to GAIA circulation</b><small>Date due is stamped · card No ${ed.editionNo}</small></div></div>
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
  const NUM = ["twelve", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven"];
  const COURSE = ["First", "Second", "Third", "Fourth", "Fifth"];
  function spoken(t24) {
    if (!t24) return "before nightfall";
    const [h, m] = t24.split(":").map(Number);
    const hr = NUM[h % 12];
    const next = NUM[(h + 1) % 12];
    if (m === 0) return `${hr} o'clock`;
    if (m === 15) return `quarter past ${hr}`;
    if (m === 30) return `half past ${hr}`;
    if (m === 45) return `quarter to ${next}`;
    return `${hr} ${String(m).padStart(2, "0")}`;
  }
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
        { id: "playfair", label: "Playfair + Hoefler", disp: "'Playfair Display', Georgia, serif", text: "'Hoefler Text', Baskerville, Georgia, serif" },
        { id: "didot", label: "Didot + Baskerville", disp: "Didot, 'Bodoni 72', serif", text: "Baskerville, 'Hoefler Text', Georgia, serif" },
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
.t-menu .course { font-size: 16px; color: var(--gold); }
.t-menu .dish { margin-top: 6px; }
.t-menu .dish + .course { margin-top: 20px; }
.t-menu .name { font: 400 24px/1.2 var(--disp); text-wrap: balance; }
.t-menu .when { font-size: 16px; color: var(--soft); margin-top: 6px; }
.t-menu .desc { font-style: italic; font-size: 17px; color: var(--soft); margin-top: 4px; }
.t-menu h2 { font: italic 400 23px/1.2 var(--disp); margin-bottom: 14px; }
.t-menu .ask { margin-top: 10px; }
.t-menu .ask em { color: var(--gold); }
.t-menu .ask small { display: block; font-size: 16px; font-style: italic; color: var(--soft); }
.t-menu .prep p { margin-top: 8px; font-size: 17px; }
.t-menu .prep small { display: block; font-size: 16px; font-style: italic; color: var(--soft); }
.t-menu .dig { font: italic 400 23px/1.2 var(--disp); }
.t-menu .cov { margin-top: 22px; font-size: 16px; line-height: 1.6; text-wrap: balance; color: var(--soft); }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const foil = `<div class="foil" aria-hidden="true"></div>`;
      const parts = [];
      if (needs.length) parts.push(`<h2>awaiting the table's decision</h2>${needs.map((d) => `<p class="ask" data-role="body"><em>to ${esc(d.verb.toLowerCase())}</em> — ${esc(d.label)}${d.note ? `<small>${esc(d.note)}</small>` : ""}</p>`).join("")}`);
      if (c.today.length)
        parts.push(c.today.map((e, i) => `<div class="course sc">— ${c.today.length === 1 ? "Plat du jour" : i === c.today.length - 1 ? "To finish" : COURSE[i]} —</div><div class="dish" data-role="body"><p class="name">${esc(cap(e.label))}</p><p class="when sc">${esc(spoken(e.t24))}</p>${e.note ? `<p class="desc">${esc(e.note)}</p>` : ""}</div>`).join(""));
      if (c.overnight.length) parts.push(`<h2>prepared overnight</h2><div class="prep">${c.overnight.map((e) => `<p data-role="body">${esc(e.label)}${e.note ? `<small>${esc(e.note)}</small>` : ""}</p>`).join("")}</div>`);
      const s = c.stats;
      return `<article class="t-menu" style="--ground:${skin.card.ground}; --card:${skin.card.card}; --ink:${skin.card.ink}; --soft:${skin.card.soft}; --gold:${skin.card.gold}; --foil:${skin.card.foil}; --disp:${skin.face.disp}; --text:${skin.face.text}">
<div class="card${skin.border.id === "double" ? " dbl" : ""}">${grain("mn-g", 0.8)}
  <div class="house">GAIA</div>
  <h1>menu du jour</h1>
  <p class="date sc">${esc(ed.weekday)} · ${ed.day} ${esc(ed.month)} ${ed.year} · service No ${ed.editionNo}</p>
  <p class="deck">${esc(ed.deck)}</p>
  ${foil}${parts.join(foil)}${foil}
  <p class="dig">digestif — the evening is yours.</p>
  ${s ? `<p class="cov sc">Couverts ${s.done}${s.you && s.gaia ? ` — ${s.you} by your hand, ${s.gaia} by the kitchen` : ""}${s.mail ? ` · correspondence ${s.mail}` : ""}${s.focus ? ` · ${esc(s.focus)} of focus` : ""}</p>` : ""}
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
  function qr(seed) {
    const n = 21;
    let v = Math.imul(seed, 2654435761) >>> 0;
    const cells = [];
    const finder = (x, y) => (x < 8 && y < 8) || (x >= n - 8 && y < 8) || (x < 8 && y >= n - 8);
    for (let y = 0; y < n; y++)
      for (let x = 0; x < n; x++) {
        if (finder(x, y)) continue;
        v = (Math.imul(v, 1103515245) + 12345) >>> 0;
        if ((v >>> 7) % 2) cells.push(`<rect x="${x}" y="${y}" width="1" height="1"/>`);
      }
    const eye = (x, y) => `<rect x="${x}" y="${y}" width="7" height="7"/><rect x="${x + 1}" y="${y + 1}" width="5" height="5" fill="var(--paper)"/><rect x="${x + 2}" y="${y + 2}" width="3" height="3"/>`;
    return `<svg class="qr" viewBox="0 0 ${n} ${n}" shape-rendering="crispEdges" aria-hidden="true"><g fill="var(--ink)">${cells.join("")}${eye(0, 0)}${eye(n - 7, 0)}${eye(0, n - 7)}</g></svg>`;
  }
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
        { id: "helvetica", label: "Helvetica figures", fig: "'Helvetica Neue', Helvetica, sans-serif" },
        { id: "menlo", label: "Menlo figures", fig: "Menlo, 'Courier New', monospace" },
      ],
      stub: [
        { id: "remit", label: "remittance slip" },
        { id: "none", label: "no slip" },
      ],
    },
    css: `
.t-invoice { box-sizing: border-box; width: 540px; padding: 30px 22px 38px; background: var(--desk); color: var(--ink); font: 400 17px/1.45 'Helvetica Neue', Helvetica, Arial, sans-serif; }
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
.t-invoice .li > span:first-child, .t-invoice .ap > span { text-wrap: pretty; }
.t-invoice .memo { margin-top: 26px; font-size: 22px; line-height: 1.3; font-weight: 700; letter-spacing: -.01em; }
.t-invoice section { margin-top: 34px; }
.t-invoice h2 { display: flex; justify-content: space-between; align-items: baseline; font-size: 20px; font-weight: 800; letter-spacing: -.01em; padding-bottom: 10px; border-bottom: 2px solid var(--ink); }
.t-invoice h2 > span:last-child { font: 400 15px/1 var(--fig); color: var(--soft); }
.t-invoice h2 .ttl { font: inherit; color: inherit; }
.t-invoice .paid { font-style: normal; }
.t-invoice .ap { display: grid; grid-template-columns: 26px 1fr; gap: 12px; padding: 12px 0 4px; }
.t-invoice .box { width: 20px; height: 20px; border: 2px solid var(--acc); border-radius: 3px; margin-top: 2px; }
.t-invoice .ap b { color: var(--acc); }
.t-invoice small.n { display: block; font-size: 15px; color: var(--soft); }
.t-invoice .li { display: grid; grid-template-columns: 1fr 60px 64px; gap: 10px; padding: 11px 0; border-bottom: 1px solid var(--hair); align-items: baseline; }
.t-invoice .li .f { font: 400 16px/1.4 var(--fig); font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.t-invoice .li .f.zero { color: var(--soft); }
.t-invoice .cols { display: grid; grid-template-columns: 1fr 60px 64px; gap: 10px; padding: 10px 0 2px; font-size: 15px; color: var(--soft); }
.t-invoice .cols span + span { text-align: right; }
.t-invoice .paid { display: inline-block; margin-left: 12px; transform: rotate(-5deg); border: 3px double var(--acc); color: var(--acc); border-radius: 5px; padding: 1px 8px; font-size: 15px; font-weight: 800; vertical-align: 2px; }
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
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const no = String(ed.editionNo).padStart(4, "0");
      const note = (t) => (t ? `<small class="n">${esc(t)}</small>` : "");
      const secs = [];
      if (needs.length)
        secs.push(`<section><h2>Approval required<span>${needs.length}</span></h2>${needs.map((d) => `<div class="ap" data-role="body"><i class="box" aria-hidden="true"></i><span><b>${esc(d.verb)}</b> ${esc(d.label)}${note(d.note)}</span></div>`).join("")}</section>`);
      const cols = `<div class="cols"><span>Description</span><span>Time</span><span>Amount</span></div>`;
      if (c.today.length)
        secs.push(`<section><h2>Today, billable<span>${c.today.length} item${c.today.length > 1 ? "s" : ""}</span></h2>${cols}${c.today.map((e) => `<div class="li" data-role="body"><span>${esc(e.label)}${note(e.note)}</span><span class="f">${e.t24 ? esc(e.t24) : "EOD"}</span><span class="f">1 ${e.t24 ? "slot" : "ship"}</span></div>`).join("")}</section>`);
      if (c.overnight.length)
        secs.push(`<section><h2><span class="ttl">Overnight<i class="paid">Paid in advance</i></span><span>${c.overnight.length}</span></h2>${cols}${c.overnight.map((e) => `<div class="li" data-role="body"><span>${esc(e.label)}${note(e.note)}</span><span class="f">${esc(e.t24)}</span><span class="f zero">0.00</span></div>`).join("")}</section>`);
      const s = c.stats;
      const tot = s ? `<div class="tot"><div><span>Settled yesterday</span><b>${s.done}${s.you && s.gaia ? ` (${s.you} you, ${s.gaia} GAIA)` : ""}</b></div>${s.mail ? `<div><span>Correspondence</span><b>${s.mail} filed</b></div>` : ""}${s.focus ? `<div><span>Focus held today</span><b>${esc(s.focus)}</b></div>` : ""}<div class="bal"><span>Balance due</span><b>1 ${esc(ed.weekday)}</b></div></div>` : "";
      const slip = skin.stub.id === "remit"
        ? `<div class="perf"><span>Detach and return</span></div><div class="slip">${grain("iv-g2", 0.9)}<div><span class="k">Remittance for invoice ${no}</span><b>1 ${esc(ed.weekday)}</b><span class="k">Payable to GAIA Studios, on waking</span></div><div>${qr(ed.editionNo)}<p class="ref">Ref. GA-${no}</p></div></div>`
        : "";
      return `<article class="t-invoice" style="--paper:${skin.paper.paper}; --ink:${skin.paper.ink}; --soft:${skin.paper.soft}; --hair:${skin.paper.hair}; --desk:${skin.paper.desk}; --acc:${skin.paper.acc}; --tint:${skin.paper.tint}; --fig:${skin.figures.fig}">
<div class="doc">
  <div class="sheet">${grain("iv-g", 0.9)}
    <div class="hd"><div class="brand">[GAIA Studios]<span>Your desk, ${esc(ed.dateLong)}</span></div><h1>Invoice<small>No. ${no}</small></h1></div>
    <div class="due"><div><span class="k">Amount due</span><b>1 ${esc(ed.weekday)}</b></div><div class="r">Issued ${esc(ed.time24)}<br>Due on waking</div></div>
    <div class="parties"><div><span class="k">Billed to</span><br>${ed.recipient ? esc(ed.recipient.name) : "You"}</div><div><span class="k">From</span><br>GAIA Studios, edition ${ed.editionNo}</div></div>
    <p class="memo">${esc(ed.deck)}</p>
    ${secs.join("")}
    ${tot}
  </div>
  ${slip}
</div></article>`;
    },
  });
})();
