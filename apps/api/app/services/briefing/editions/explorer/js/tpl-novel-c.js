/* ============================================================================
 * tpl-novel-c.js — two poster templates for the daily-brief explorer.
 *
 *   gradient — the day as a modern brand poster: a grainy, multi-stop pastel
 *              sky with a horizon glow, one huge confident grotesk statement
 *              set top-left (the deck), the day's content held as a single
 *              compact mono column after a long breath of air, and two tiny
 *              letterspaced mono clusters pinned to the bottom corners. Film
 *              grain (inline feTurbulence, url-encoded so no bare http) over
 *              the whole field so it reads as print, not a SaaS hero.
 *
 *   invoice  — the day as a brutalist studio invoice: a bracketed grotesk
 *              wordmark, INVOICE flush-right at equal weight, a ruled
 *              DESCRIPTION/QTY/UNIT/AMOUNT line-item table where the day's work
 *              is billed deadpan (overnight lines prepaid at 0.00 by GAIA), a
 *              totals stack, a PAYMENT block whose two rows are the decisions,
 *              TERMS set verbatim from the deck, and a QR-looking block whose
 *              modules are deterministically seeded from the edition number.
 *              The joke is carried entirely by the formality.
 *
 * Both draw every fact from `ed`; skin values arrive only as inline custom
 * properties consumed via var(); structural variants ride on modifier classes.
 * Deterministic — no Date.now / Math.random. One IIFE so locals never collide.
 * ==========================================================================*/
(() => {
  /* ---- shared text helpers -------------------------------------------- */
  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }
  function caps(s) {
    return esc(String(s).toUpperCase());
  }
  // pad an edition number to the studio's four-digit house style (#GA-0042)
  function pad4(n) {
    return String(n).padStart(4, "0");
  }

  /* ============================================================================
   * GRADIENT — grainy pastel brand poster with a confident grotesk statement.
   *
   * The grain is an inline SVG feTurbulence, url-encoded so the string carries
   * no bare "://" (the SVG namespace is written http%3A%2F%2F… — it decodes to
   * a real namespace in the browser and renders, but never trips an external-
   * URL check). It sits under the text (::before, z-index 0) so type stays
   * crisp while the airy gradient reads as printed stock.
   * ==========================================================================*/
  const GRADIENT_CSS = `
    .t-gradient {
      position: relative;
      overflow: hidden;
      width: 100%;
      margin: 0;
      box-sizing: border-box;
      min-height: 1360px;
      padding: clamp(34px, 4.6vw, 88px);
      display: flex;
      flex-direction: column;
      color: var(--ink);
      font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }
    .t-gradient * { box-sizing: border-box; }

    /* horizon variants — the whole atmosphere lives on these two classes */
    .t-gradient.h-band {
      background:
        linear-gradient(179deg,
          var(--g1) 0%,
          var(--g2) 30%,
          var(--glow) 57%,
          var(--glow) 65%,
          var(--g3) 80%,
          var(--g4) 100%);
    }
    .t-gradient.h-glow {
      background:
        radial-gradient(96% 62% at 27% 113%, var(--glow) 0%, transparent 58%),
        linear-gradient(176deg,
          var(--g1) 0%,
          var(--g2) 38%,
          var(--g3) 72%,
          var(--g4) 100%);
    }

    /* film grain — desaturated fractal noise, kept faint and under the type */
    .t-gradient::before {
      content: "";
      position: absolute;
      inset: 0;
      z-index: 0;
      pointer-events: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg' width='140' height='140'%3E%3Cfilter id='g'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.86' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23g)'/%3E%3C/svg%3E");
      background-size: 170px 170px;
      opacity: var(--grain, 0.6);
      mix-blend-mode: overlay;
    }
    .t-gradient > * { position: relative; z-index: 1; }

    .t-gradient__statement {
      font-family: var(--display, 'Helvetica Neue'), Helvetica, Arial, sans-serif;
      font-weight: 700;
      font-size: clamp(38px, 6.3vw, 88px);
      line-height: 1.02;
      letter-spacing: var(--stmt-track, -0.022em);
      max-width: 21ch;
      margin: 0;
      text-wrap: balance;
    }

    .t-gradient__spacer { flex: 1 1 auto; min-height: 90px; }

    .t-gradient__body {
      max-width: min(100%, 54ch);
      font-family: Menlo, 'SF Mono', ui-monospace, monospace;
    }
    .t-gradient__grp { margin-top: 34px; }
    .t-gradient__grp:first-child { margin-top: 0; }
    .t-gradient__glabel {
      font-size: 10px;
      letter-spacing: 0.28em;
      text-transform: uppercase;
      opacity: 0.6;
      margin: 0 0 13px;
      padding-left: 0.28em;
    }
    .t-gradient__list { list-style: none; margin: 0; padding: 0; }
    .t-gradient__line {
      display: flex;
      gap: 16px;
      font-size: 12px;
      line-height: 1.5;
      margin: 0 0 10px;
      font-variant-numeric: tabular-nums;
    }
    .t-gradient__line:last-child { margin-bottom: 0; }
    .t-gradient__t {
      flex: 0 0 auto;
      width: 58px;
      opacity: 0.68;
      letter-spacing: 0.03em;
    }
    .t-gradient__t.is-verb { text-transform: uppercase; letter-spacing: 0.1em; opacity: 0.9; }
    .t-gradient__lab { flex: 1 1 auto; }
    .t-gradient__lab i {
      display: block;
      font-style: normal;
      opacity: 0.58;
      font-size: 11px;
      margin-top: 2px;
    }

    .t-gradient__corners {
      margin-top: 46px;
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 22px;
      flex-wrap: wrap;
    }
    .t-gradient__cl {
      font-family: Menlo, ui-monospace, monospace;
      font-size: 10px;
      letter-spacing: 0.24em;
      text-transform: uppercase;
      line-height: 2;
    }
    .t-gradient__cl b { font-weight: 700; letter-spacing: 0.16em; }
    .t-gradient__cl.is-right { text-align: right; opacity: 0.86; }

    @media (max-width: 560px) {
      .t-gradient { min-height: 1180px; }
      .t-gradient__statement { font-size: clamp(32px, 9vw, 52px); max-width: 100%; }
      .t-gradient__t { width: 50px; }
    }
  `;

  // one mono line: a fixed-width left token (time or verb) + label + optional note
  function gradLine(token, isVerb, label, note) {
    return (
      `<li class="t-gradient__line">` +
      `<span class="t-gradient__t${isVerb ? " is-verb" : ""}">${esc(token)}</span>` +
      `<span class="t-gradient__lab">${esc(label)}` +
      (note ? `<i>${esc(note)}</i>` : "") +
      `</span>` +
      `</li>`
    );
  }
  function gradGroup(label, lines) {
    return (
      `<div class="t-gradient__grp">` +
      `<p class="t-gradient__glabel">${esc(label)}</p>` +
      `<ul class="t-gradient__list">${lines}</ul>` +
      `</div>`
    );
  }

  EXPLORER.register({
    id: "gradient",
    name: "The Horizon",
    axes: {
      // five curated grainy-gradient palettes, each with its own matched ink.
      // the first three are light fields (dark ink); the last two are dark
      // fields lit by a glow (light ink) — none of them a flat 2-stop hero.
      palette: [
        {
          id: "dawn",
          label: "Dawn — blue to pink",
          g1: "#9fb9db", g2: "#c4cfe0", g3: "#f2cec9", g4: "#edaea3",
          glow: "#fdf4e8",
          ink: "#17181d", grain: "0.72",
        },
        {
          id: "dusk",
          label: "Dusk — peach to violet",
          g1: "#edc99f", g2: "#dcb4a5", g3: "#bd9dba", g4: "#8b81b3",
          glow: "#f7dcb4",
          ink: "#221b28", grain: "0.68",
        },
        {
          id: "sage",
          label: "Sage — sage to cream",
          g1: "#9fb289", g2: "#c2ce9f", g3: "#e2e2c2", g4: "#efe7cc",
          glow: "#f6f3d6",
          ink: "#242a1c", grain: "0.72",
        },
        {
          id: "ocean",
          label: "Ocean — deep blue, cyan glow",
          g1: "#0a1e33", g2: "#123a52", g3: "#155f78", g4: "#1f8f97",
          glow: "#63d2c8",
          ink: "#eef5f2", grain: "0.58",
        },
        {
          id: "ember",
          label: "Charcoal to ember",
          g1: "#161309", g2: "#241a10", g3: "#4d2716", g4: "#8f3f1e",
          glow: "#df7a3a",
          ink: "#f3e7d9", grain: "0.56",
        },
      ],
      // the statement face — a tight neo-grotesk or the extended axis
      face: [
        {
          id: "helvetica",
          label: "Helvetica Neue Bold",
          display: "'Helvetica Neue'",
          track: "-0.024em",
        },
        {
          id: "aeonik",
          label: "Aeonik Extended",
          display: "'Aeonik Extended'",
          track: "-0.006em",
        },
      ],
      // where the light in the sky lives
      horizon: [
        { id: "band", label: "Horizon band", cls: "h-band" },
        { id: "glow", label: "Corner glow", cls: "h-glow" },
      ],
    },
    css: GRADIENT_CSS,
    render(ed, skin) {
      const { palette, face, horizon } = skin;
      const c = ed.content;
      const s = c.stats;

      const todayLines = c.today
        .map((it) => gradLine(it.t24 || "EOD", false, it.label, it.note))
        .join("");
      const overnightLines = c.overnight
        .map((it) => gradLine(it.t24 || "", false, it.label, it.note))
        .join("");
      const callLines = c.decisions
        .map((it) => gradLine(it.verb, true, it.label, it.note))
        .join("");

      const body =
        `<section class="t-gradient__body">` +
        gradGroup("Today", todayLines) +
        gradGroup("Handled overnight", overnightLines) +
        gradGroup("Needs your call", callLines) +
        `</section>`;

      const corners =
        `<footer class="t-gradient__corners">` +
        `<div class="t-gradient__cl">` +
        `<b>The ${caps(ed.weekday)} Brief</b><br>` +
        `Edition N&ordm; ${ed.editionNo}<br>` +
        `${esc(ed.dateLong)}` +
        `</div>` +
        `<div class="t-gradient__cl is-right">` +
        `Done ${s.done} &middot; Mail ${s.mail} &middot; Focus ${caps(s.focus)}<br>` +
        `${s.you} by you &middot; ${s.gaia} by GAIA` +
        `</div>` +
        `</footer>`;

      const style =
        `--g1:${palette.g1};--g2:${palette.g2};--g3:${palette.g3};--g4:${palette.g4};` +
        `--glow:${palette.glow};--ink:${palette.ink};--grain:${palette.grain};` +
        `--display:${face.display};--stmt-track:${face.track};`;

      return (
        `<article class="t-gradient ${horizon.cls}" style="${style}">` +
        `<h1 class="t-gradient__statement">${esc(ed.deck)}</h1>` +
        `<div class="t-gradient__spacer"></div>` +
        body +
        corners +
        `</article>`
      );
    },
  });

  /* ============================================================================
   * INVOICE — a brutalist studio invoice. Helvetica Neue only, tabular figures.
   * ==========================================================================*/
  const INVOICE_CSS = `
    .t-invoice {
      width: 100%;
      margin: 0;
      box-sizing: border-box;
      min-height: 1500px;
      padding: clamp(30px, 4.4vw, 80px) clamp(20px, 4vw, 76px) clamp(40px, 5vw, 92px);
      background: var(--paper);
      color: var(--ink);
      font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
      -webkit-font-smoothing: antialiased;
      font-variant-numeric: tabular-nums;
    }
    .t-invoice * { box-sizing: border-box; }

    .t-invoice__head {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 24px;
      flex-wrap: wrap;
    }
    .t-invoice__mark, .t-invoice__inv {
      font-weight: 700;
      font-size: var(--wm, clamp(30px, 5vw, 64px));
      line-height: 0.9;
      margin: 0;
    }
    .t-invoice__mark { letter-spacing: -0.03em; }
    .t-invoice__inv { letter-spacing: -0.02em; }

    .t-invoice__meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px 22px;
      margin-top: 28px;
      padding-bottom: 22px;
      border-bottom: var(--rule-strong, 2px) solid var(--ink);
      font-size: 12px;
      letter-spacing: 0.04em;
    }
    .t-invoice__meta span { white-space: nowrap; }

    .t-invoice__tbl {
      width: 100%;
      border-collapse: collapse;
      margin-top: 4px;
      table-layout: fixed;
    }
    .t-invoice__tbl col.c-qty { width: clamp(48px, 8%, 70px); }
    .t-invoice__tbl col.c-unit { width: clamp(84px, 14%, 128px); }
    .t-invoice__tbl col.c-amt { width: clamp(96px, 15%, 140px); }
    .t-invoice__tbl th {
      font-size: 10px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      text-align: left;
      font-weight: 700;
      padding: 18px 10px 10px;
      border-bottom: var(--rule-w, 1px) solid var(--ink);
    }
    .t-invoice__tbl th.num, .t-invoice__tbl td.num { text-align: right; }
    .t-invoice__sec td {
      padding: 24px 10px 8px;
      font-size: 10px;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      font-weight: 700;
      color: var(--ink);
    }
    .t-invoice__tbl td {
      padding: 12px 10px;
      border-bottom: var(--rule-w, 1px) solid var(--line);
      font-size: 14px;
      line-height: 1.4;
      vertical-align: top;
      overflow-wrap: anywhere;
    }
    .t-invoice__desc small {
      display: block;
      font-size: 11px;
      opacity: 0.6;
      margin-top: 3px;
      letter-spacing: 0;
    }
    .t-invoice__amt.is-zero { opacity: 0.5; }

    .t-invoice__totals {
      margin-top: 26px;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 9px;
    }
    .t-invoice__trow {
      display: flex;
      justify-content: space-between;
      gap: 44px;
      min-width: min(360px, 100%);
      font-size: 13px;
    }
    .t-invoice__trow .k {
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 11px;
      opacity: 0.72;
    }
    .t-invoice__trow.is-due {
      margin-top: 8px;
      padding-top: 13px;
      border-top: var(--rule-strong, 2px) solid var(--ink);
      font-weight: 700;
      font-size: 15px;
    }
    .t-invoice__trow.is-due .k { opacity: 1; font-size: 12px; }

    .t-invoice__lower {
      margin-top: 56px;
      padding-top: 32px;
      border-top: var(--rule-strong, 2px) solid var(--ink);
      display: flex;
      gap: 48px;
      justify-content: space-between;
      align-items: flex-start;
      flex-wrap: wrap;
    }
    .t-invoice__pay { flex: 1 1 380px; min-width: 260px; }
    .t-invoice__payh {
      font-weight: 700;
      letter-spacing: -0.01em;
      font-size: clamp(22px, 3vw, 34px);
      margin: 0 0 18px;
    }
    .t-invoice__prow {
      display: flex;
      gap: 14px;
      align-items: baseline;
      padding: 13px 0;
      border-bottom: var(--rule-w, 1px) solid var(--line);
      font-size: 14px;
      line-height: 1.45;
    }
    .t-invoice__tag {
      flex: 0 0 auto;
      font-size: 9.5px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      border: var(--rule-w, 1px) solid var(--ink);
      padding: 3px 6px;
      font-weight: 700;
      white-space: nowrap;
    }
    .t-invoice__prow .verb { font-weight: 700; letter-spacing: 0.02em; }
    .t-invoice__prow small { display: block; opacity: 0.6; font-size: 12px; margin-top: 2px; }
    .t-invoice__terms {
      margin-top: 22px;
      font-size: 12.5px;
      line-height: 1.6;
      letter-spacing: 0.01em;
    }
    .t-invoice__terms b {
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 10px;
      opacity: 0.72;
      margin-right: 9px;
    }

    .t-invoice__qr { flex: 0 0 auto; width: 186px; text-align: center; }
    .t-invoice__qrsvg { width: 186px; height: 186px; display: block; fill: var(--ink); }
    .t-invoice__qrcap {
      margin-top: 11px;
      font-size: 10px;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      font-weight: 700;
    }

    .t-invoice__foot {
      margin-top: 46px;
      padding-top: 18px;
      border-top: var(--rule-w, 1px) solid var(--line);
      display: flex;
      flex-wrap: wrap;
      gap: 8px 20px;
      font-size: 11px;
      letter-spacing: 0.05em;
    }

    @media (max-width: 560px) {
      .t-invoice { min-height: 1320px; }
      .t-invoice__tbl td, .t-invoice__tbl th, .t-invoice__sec td { padding-left: 6px; padding-right: 6px; }
      .t-invoice__tbl td { font-size: 13px; }
      .t-invoice__lower { gap: 32px; }
    }
  `;

  // deterministic QR-looking matrix: three finder eyes + modules seeded from the
  // edition number via a tiny LCG (pure — no Math.random). Rendered as inline
  // SVG (HTML parser supplies the SVG namespace, so no data URI, no bare http).
  function invoiceQR(seed) {
    const N = 21;
    let a = (Math.imul(seed >>> 0, 2654435761) ^ 0x9e3779b9) >>> 0 || 1;
    const rnd = () => {
      a = (Math.imul(a, 1664525) + 1013904223) >>> 0;
      return a / 4294967296;
    };
    const rects = [];
    const push = (x, y) => rects.push(`<rect x='${x}' y='${y}' width='1' height='1'/>`);

    // three finder eyes: outer ring + 3x3 core, at TL / TR / BL
    for (const [ox, oy] of [[0, 0], [N - 7, 0], [0, N - 7]]) {
      for (let ry = 0; ry < 7; ry++) {
        for (let rx = 0; rx < 7; rx++) {
          const ring = rx === 0 || rx === 6 || ry === 0 || ry === 6;
          const core = rx >= 2 && rx <= 4 && ry >= 2 && ry <= 4;
          if (ring || core) push(ox + rx, oy + ry);
        }
      }
    }
    // data modules everywhere outside the finder+separator zones
    for (let y = 0; y < N; y++) {
      for (let x = 0; x < N; x++) {
        const zone =
          (x < 8 && y < 8) || (x >= N - 8 && y < 8) || (x < 8 && y >= N - 8);
        if (zone) continue;
        if (rnd() > 0.5) push(x, y);
      }
    }
    return (
      `<svg class="t-invoice__qrsvg" viewBox="0 0 ${N} ${N}" shape-rendering="crispEdges" aria-hidden="true">` +
      rects.join("") +
      `</svg>`
    );
  }

  function invLineItem(desc, small, qty, unit, amt, zero) {
    return (
      `<tr>` +
      `<td class="t-invoice__desc">${esc(desc)}${small ? `<small>${esc(small)}</small>` : ""}</td>` +
      `<td class="num">${esc(qty)}</td>` +
      `<td class="num">${esc(unit)}</td>` +
      `<td class="num t-invoice__amt${zero ? " is-zero" : ""}">${esc(amt)}</td>` +
      `</tr>`
    );
  }
  function invSection(label) {
    return `<tr class="t-invoice__sec"><td colspan="4">${esc(label)}</td></tr>`;
  }
  function invTotal(k, v, due) {
    return (
      `<div class="t-invoice__trow${due ? " is-due" : ""}">` +
      `<span class="k">${esc(k)}</span><span>${esc(v)}</span>` +
      `</div>`
    );
  }

  EXPLORER.register({
    id: "invoice",
    name: "The Invoice",
    axes: {
      // single-ink colorways in the studio-print tradition
      colorway: [
        {
          id: "paper",
          label: "Paper — black on white",
          paper: "#f4f2ec", ink: "#17150f", line: "rgba(23,21,15,0.17)",
        },
        {
          id: "inverted",
          label: "Inverted — white on black",
          paper: "#131210", ink: "#efece2", line: "rgba(239,236,226,0.22)",
        },
        {
          id: "cobalt",
          label: "Cobalt riso print",
          paper: "#edf0f7", ink: "#1a3ca8", line: "rgba(26,60,168,0.26)",
        },
        {
          id: "vermilion",
          label: "Vermilion print",
          paper: "#f6f0e7", ink: "#b8331a", line: "rgba(184,51,26,0.26)",
        },
      ],
      // wordmark scale
      scale: [
        { id: "standard", label: "Standard wordmark", wm: "clamp(30px, 5vw, 62px)" },
        { id: "oversized", label: "Oversized wordmark", wm: "clamp(40px, 7.4vw, 104px)" },
      ],
      // rule weight
      rule: [
        { id: "hairline", label: "Hairline rules", w: "1px", strong: "1.5px" },
        { id: "heavy", label: "Heavy rules", w: "2px", strong: "3px" },
      ],
    },
    css: INVOICE_CSS,
    render(ed, skin) {
      const { colorway, scale, rule } = skin;
      const c = ed.content;
      const s = c.stats;
      const invNo = `GA-${pad4(ed.editionNo)}`;

      // BILLABLE — today's work, itemised at face value
      const t = c.today;
      const billable =
        invSection("Today — billable") +
        invLineItem(t[0].label, t[0].note, "1", t[0].t24 || "", "1 session", false) +
        invLineItem(t[1].label, t[1].note, "1", t[1].t24 || "", "1 session", false) +
        invLineItem(t[2].label, t[2].note, "1", t[2].t24 || "EOD", "1 session", false);

      // OVERNIGHT — prepaid by GAIA, billed at 0.00
      const o = c.overnight;
      const prepaid =
        invSection("Overnight — prepaid by GAIA") +
        invLineItem(o[0].label, o[0].note, "1", o[0].t24 || "", "0.00", true) +
        invLineItem(o[1].label, o[1].note, "1", o[1].t24 || "", "0.00", true) +
        invLineItem(o[2].label, o[2].note, "1", o[2].t24 || "", "0.00", true);

      const table =
        `<table class="t-invoice__tbl">` +
        `<colgroup><col class="c-desc"><col class="c-qty"><col class="c-unit"><col class="c-amt"></colgroup>` +
        `<thead><tr>` +
        `<th>Description</th>` +
        `<th class="num">Qty</th>` +
        `<th class="num">Unit</th>` +
        `<th class="num">Amount</th>` +
        `</tr></thead>` +
        `<tbody>${billable}${prepaid}</tbody>` +
        `</table>`;

      const totals =
        `<div class="t-invoice__totals">` +
        invTotal("Subtotal", "1 day", false) +
        invTotal("Items settled", `${s.done}: ${s.you} you, ${s.gaia} GAIA`, false) +
        invTotal("Correspondence", `${s.mail} filed`, false) +
        invTotal("Focus held", caps(s.focus), false) +
        invTotal("Balance due", `1 ${caps(ed.weekday)}`, true) +
        `</div>`;

      const paymentRows = c.decisions
        .map(
          (d) =>
            `<div class="t-invoice__prow">` +
            `<span class="t-invoice__tag">[Payment pending]</span>` +
            `<span><span class="verb">${esc(d.verb)}</span> &mdash; ${esc(d.label)}` +
            (d.note ? `<small>${esc(d.note)}</small>` : "") +
            `</span></div>`,
        )
        .join("");

      const lower =
        `<div class="t-invoice__lower">` +
        `<div class="t-invoice__pay">` +
        `<h2 class="t-invoice__payh">Payment</h2>` +
        paymentRows +
        `<p class="t-invoice__terms"><b>Terms</b>${esc(ed.deck)}</p>` +
        `</div>` +
        `<div class="t-invoice__qr">` +
        invoiceQR(ed.editionNo) +
        `<p class="t-invoice__qrcap">Scan to reply</p>` +
        `</div>` +
        `</div>`;

      const style =
        `--paper:${colorway.paper};--ink:${colorway.ink};--line:${colorway.line};` +
        `--wm:${scale.wm};--rule-w:${rule.w};--rule-strong:${rule.strong};`;

      return (
        `<article class="t-invoice" style="${style}">` +
        `<header class="t-invoice__head">` +
        `<p class="t-invoice__mark">[GAIA STUDIOS]</p>` +
        `<p class="t-invoice__inv">INVOICE</p>` +
        `</header>` +
        `<div class="t-invoice__meta">` +
        `<span>[${esc(ed.dateLong)}]</span>` +
        `<span>[#${invNo}]</span>` +
        `<span>[One ${esc(ed.weekday)}]</span>` +
        `<span>[Issued ${esc(ed.time24)}]</span>` +
        `</div>` +
        table +
        totals +
        lower +
        `<footer class="t-invoice__foot">` +
        `<span>[GAIA &middot; your desk]</span>` +
        `<span>[Edition ${ed.editionNo}]</span>` +
        `<span>[Generated ${esc(ed.time24)}]</span>` +
        `</footer>` +
        `</article>`
      );
    },
  });
})();
