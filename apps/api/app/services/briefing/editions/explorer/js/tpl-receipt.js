/* ============================================================================
   tpl-receipt.js (round 2) — the thermal receipt, re-composed for a 540 px
   portrait canvas (export at 3x). Body 17 px Menlo.

   Signature moves kept from the desktop original:
     1. a single thermal tape lying on a desk, slightly rotated, real shadow
     2. torn (not cut) top and bottom edges, irregular and never mirrored
     3. monospace rhythm: ASCII dash / equals rules, uppercase line items with
        dotted leaders to a right-aligned value, indented notes
     4. paper texture: thermal banding, grain, edge yellowing
     5. the tender block, THANK YOU FOR WAKING, a barcode and its number
   Added for the phone: a double-height store header (focal, 3x body), the
   deck printed double-height, and a second thermal colour (red) reserved for
   what is awaiting payment.

   Reading order: deck -> awaiting payment -> today -> overnight -> totals.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const caps = (s) => esc(String(s).toUpperCase());
  const pad2 = (n) => String(n).padStart(2, "0");

  /* A tape is torn, not cut: a fine deterministic sawtooth, different tooth
     counts and depth bands top vs bottom so the two tears never mirror. */
  const frac = (x) => x - Math.floor(x);
  function tornTeeth(n, edge) {
    const flush = edge === "top" ? 100 : 0;
    const seed = edge === "top" ? 12.9898 : 78.233;
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const x = +((i / n) * 100).toFixed(2);
      if (i % 2 === 0) pts.push(`${x}% ${flush}%`);
      else {
        const j = frac(Math.sin(i * seed) * 43758.5453);
        const peak = edge === "top" ? 20 + j * 30 : 50 + j * 30;
        pts.push(`${x}% ${peak.toFixed(1)}%`);
      }
    }
    pts.push(edge === "top" ? "100% 100%" : "100% 0%");
    return `polygon(${pts.join(", ")})`;
  }
  const TEAR_TOP = tornTeeth(58, "top");
  const TEAR_BOT = tornTeeth(64, "bottom");

  /* Barcode bars derived from the edition number. */
  function barcode(seed) {
    const stops = [];
    let x = 0;
    let v = Math.imul(seed, 2654435761) >>> 0;
    for (let i = 0; i < 58; i++) {
      v = (Math.imul(v, 1103515245) + 12345) >>> 0;
      const w = 1 + (v % 3);
      if (i % 2 === 0) stops.push(`var(--ink) ${x}px ${x + w}px`);
      else stops.push(`transparent ${x}px ${x + w + 1}px`);
      x += w + (i % 2 ? 1 : 0);
    }
    return { bg: `linear-gradient(90deg, ${stops.join(", ")})`, w: x };
  }

  /* Paper grain: inline SVG fractal noise (no external asset), blended over the sheet at low opacity. */
  const grain = (id, freq) => `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  const item = (label, val, cls) =>
    `<div class="it${cls ? " " + cls : ""}" data-role="body"><span class="lb">${caps(label)}</span><span class="ld" aria-hidden="true"></span><span class="vl">${caps(val)}</span></div>`;
  const note = (t) => `<p class="nt">${caps(t)}</p>`;
  const RULE = `<div class="rule" aria-hidden="true"></div>`;
  const RULE2 = `<div class="rule dbl" aria-hidden="true"></div>`;

  EXPLORER.register({
    id: "receipt",
    name: "The Receipt",
    axes: {
      desk: [
        { id: "slate", label: "cool slate", hi: "#7d8592", a: "#6c7480", b: "#535a64" },
        { id: "baize", label: "green baize", hi: "#3b6e5b", a: "#2a5243", b: "#1c3a2f" },
        { id: "walnut", label: "walnut", hi: "#7a5a3d", a: "#5f4531", b: "#463223" },
        { id: "oxblood", label: "oxblood leather", hi: "#7d3a3a", a: "#622a2c", b: "#481d20" },
      ],
      stock: [
        { id: "thermal", label: "thermal white", paper: "#f6f4ec", edge: "rgba(92,90,82,0.07)" },
        { id: "canary", label: "canary roll", paper: "#f5ebbb", edge: "rgba(150,120,25,0.14)" },
      ],
      density: [
        { id: "crisp", label: "fresh print head", ink: "#22221f", soft: "#4f4d47", red: "#b3261e" },
        { id: "faded", label: "worn print head", ink: "#3d3b36", soft: "#5d5a53", red: "#a3302a" },
      ],
    },
    css: `
.t-receipt { box-sizing: border-box; isolation: isolate; width: 540px; padding: 56px 0 80px; display: flex; justify-content: center;
  background: radial-gradient(120% 80% at 30% 0%, var(--hi) 0%, var(--a) 45%, var(--b) 100%); font-family: Menlo, 'SF Mono', ui-monospace, monospace; }
.t-receipt * { box-sizing: border-box; margin: 0; padding: 0; }
.t-receipt .wrap { position: relative; transform: rotate(0.5deg); }
.t-receipt .wrap::before, .t-receipt .wrap::after { content: ""; position: absolute; bottom: 14px; width: 46%; height: 30px; z-index: -1; box-shadow: 0 18px 14px rgba(8,10,14,.5); }
.t-receipt .wrap::before { left: 10px; transform: rotate(-3.5deg); }
.t-receipt .wrap::after { right: 10px; transform: rotate(3.5deg); }
.t-receipt .tape { position: relative; width: 452px; padding: 44px 26px 34px; color: var(--ink); isolation: isolate;
  font-size: 17px; line-height: 1.5; letter-spacing: 0.01em; font-variant-numeric: tabular-nums;
  background:
    radial-gradient(110% 100% at 50% 50%, transparent 58%, var(--edge) 100%),
    repeating-linear-gradient(0deg, rgba(0,0,0,0.024) 0 1px, transparent 1px 4px),
    repeating-linear-gradient(90deg, rgba(0,0,0,0.014) 0 1px, transparent 1px 3px),
    var(--paper);
  box-shadow: 0 1px 0 rgba(255,255,255,.35) inset, 0 14px 26px -16px rgba(10,14,20,.55), 0 3px 8px -4px rgba(10,14,20,.4); }
.t-receipt .tape::before, .t-receipt .tape::after { content: ""; position: absolute; left: 0; right: 0; height: 10px; background: var(--paper); }
.t-receipt .tape::before { top: -9px; clip-path: ${TEAR_TOP}; }
.t-receipt .tape::after { bottom: -9px; clip-path: ${TEAR_BOT}; }
.t-receipt .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .14; }
.t-receipt .crease { position: absolute; left: 0; right: 0; top: 38%; height: 16px; pointer-events: none;
  background: linear-gradient(180deg, transparent 0, rgba(0,0,0,.025) 45%, rgba(0,0,0,.05) 50%, rgba(255,255,255,.4) 52%, rgba(255,255,255,.1) 62%, transparent 100%); }
.t-receipt .store { text-align: center; font-size: 56px; line-height: 1; font-weight: 700; letter-spacing: .32em; padding-left: .32em; }
.t-receipt .meta { text-align: center; font-size: 15px; line-height: 1.6; letter-spacing: .06em; margin-top: 16px; }
.t-receipt .rule { margin: 16px 0; overflow: hidden; white-space: nowrap; letter-spacing: 0; line-height: 1; }
.t-receipt .rule::before { content: "------------------------------------------------------------"; }
.t-receipt .rule.dbl::before { content: "============================================================"; }
.t-receipt .deck { text-align: center; font-size: 22px; line-height: 1.35; font-weight: 700; letter-spacing: 0; padding: 4px 4px; }
.t-receipt .sec { letter-spacing: .14em; margin-bottom: 10px; }
.t-receipt .sec.red, .t-receipt .red .vl { color: var(--red); }
.t-receipt .it { display: flex; align-items: flex-end; margin-bottom: 4px; }
.t-receipt .lb { flex: 0 1 auto; min-width: 0; overflow-wrap: break-word; }
.t-receipt .ld { flex: 1 1 auto; min-width: 40px; height: 0; margin: 0 6px 5px; border-bottom: 2px dotted var(--soft); }
.t-receipt .vl { flex: 0 0 auto; white-space: nowrap; font-weight: 700; }
.t-receipt .nt { color: var(--soft); padding-left: 2ch; margin: 0 0 10px; }
.t-receipt .grp + .grp { margin-top: 4px; }
.t-receipt .total { font-size: 20px; font-weight: 700; }
.t-receipt .tender { text-align: center; letter-spacing: .14em; line-height: 1.7; margin-top: 12px; }
.t-receipt .thanks { text-align: center; letter-spacing: .16em; margin: 4px 0 16px; }
.t-receipt .bars { height: 64px; margin: 0 auto 8px; }
.t-receipt .barnum { text-align: center; letter-spacing: .3em; padding-left: .3em; margin-bottom: 14px; font-size: 15px; }
.t-receipt .colo { text-align: center; font-size: 13px; letter-spacing: .06em; color: var(--soft); }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const wd3 = ed.weekday.slice(0, 3).toUpperCase();
      const parts = [];
      if (needs.length)
        parts.push(`<div class="grp"><p class="sec red">AWAITING PAYMENT &mdash; ${needs.length} ITEM${needs.length > 1 ? "S" : ""}</p>${needs.map((d) => item(d.label, d.verb, "red") + (d.note ? note(d.note) : "")).join("")}</div>`);
      if (c.today.length)
        parts.push(`<div class="grp"><p class="sec">TODAY</p>${c.today.map((e) => item(e.label, e.t24 || "EOD") + (e.note ? note(e.note) : "")).join("")}</div>`);
      if (c.overnight.length)
        parts.push(`<div class="grp"><p class="sec">OVERNIGHT &mdash; PREPAID BY GAIA</p>${c.overnight.map((e) => item(e.label, e.tag) + (e.note ? note(e.note) : "")).join("")}</div>`);
      if (c.running.length)
        parts.push(`<div class="grp"><p class="sec">STILL IN PROGRESS &mdash; GAIA</p>${c.running.map((e) => item(e.label, e.tag) + (e.note ? note(e.note) : "")).join("")}</div>`);
      const s = c.stats;
      const totals = s
        ? `${RULE}${item("Done yesterday", s.done)}${s.you && s.gaia ? note(`You ${s.you} / GAIA ${s.gaia}`) : ""}${s.mail ? item("Emails handled", s.mail) : ""}${s.focus ? item("Focus time", s.focus) : ""}${RULE2}<div class="total">${item("Total", `1 ${ed.weekday}`)}</div>`
        : "";
      const count = needs.length + c.today.length + c.overnight.length + c.running.length;
      const bc = barcode(ed.editionNo);
      return `<article class="t-receipt" style="--hi:${skin.desk.hi}; --a:${skin.desk.a}; --b:${skin.desk.b}; --paper:${skin.stock.paper}; --edge:${skin.stock.edge}; --ink:${skin.density.ink}; --soft:${skin.density.soft}; --red:${skin.density.red}">
<div class="wrap"><div class="tape">${grain("rc-g", 0.9)}<i class="crease" aria-hidden="true"></i>
  <h1 class="store">GAIA</h1>
  <p class="meta">DAILY BRIEF &mdash; REGISTER 1<br>${wd3} ${pad2(ed.day)} ${ed.monthShort.toUpperCase()} ${ed.year}&nbsp;&nbsp;${ed.time24}<br>EDITION #${ed.editionNo}<br>SERVED BY: GAIA &middot; TERMINAL 01</p>
  ${RULE}
  <p class="deck">${esc(ed.deck)}</p>
  ${RULE}
  ${parts.join(RULE)}
  ${totals}
  <div class="tender">${count ? `<span>ITEMS: ${count}</span><br>` : ""}<span>AUTH ${ed.editionNo}-${ed.time24.replace(":", "")} &middot; APPROVED</span></div>
  ${RULE}
  <p class="thanks">*** THANK YOU FOR WAKING ***</p>
  <div class="bars" style="width:${bc.w}px; background:${bc.bg}"></div>
  <p class="barnum">ED${ed.editionNo}-${ed.time24.replace(":", "")}-GAIA</p>
  <p class="colo">EDITION No. ${ed.editionNo} &middot; GENERATED ${ed.time24} BY GAIA</p>
</div></div></article>`;
    },
  });
})();
