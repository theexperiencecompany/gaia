/* ============================================================================
 * tpl-novel-b.js — two paper-object templates for the daily-brief explorer.
 *
 *   librarycard — the day as a vintage library checkout card lying on a desk:
 *                 letterpress masthead, a thin-ruled DATE|ITEM|DUE borrow table,
 *                 CSS-only rubber stamps (JUL 3 dates, DONE/DRAFT/MOVED returns),
 *                 empty due cells where the two decisions await a signature.
 *
 *   menu        — the day as a Michelin tasting menu: centred, hairline-ruled,
 *                 courses instead of meetings, mise en place for the overnight
 *                 work, one accent-touched decision block, a digestif to close.
 *
 * Both draw every fact from `ed`; skin values arrive only as inline custom
 * properties consumed via var(). Deterministic — no Date.now / Math.random.
 * Wrapped in one IIFE so local helpers never collide with sibling modules.
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

  /* Deterministic small rotations for the rubber stamps — a fixed ring of
     angles walked by row index, so every render of an edition is identical. */
  const STAMP_ROT = [-3.6, 2.4, -1.8, 3.2, -2.7, 1.6, -3.1, 2.1, -1.4, 2.9];
  function rot(i) {
    return STAMP_ROT[i % STAMP_ROT.length];
  }

  /* ============================================================================
   * LIBRARYCARD — an oversized checkout card on a flat desk.
   * ==========================================================================*/
  const LIBRARYCARD_CSS = `
    .t-librarycard {
      width: 100%;
      margin: 0;
      box-sizing: border-box;
      padding: clamp(30px, 5vw, 86px) clamp(16px, 4vw, 60px) clamp(40px, 6vw, 96px);
      display: flex;
      justify-content: center;
      align-items: flex-start;
      background:
        radial-gradient(130% 90% at 50% -10%, #6c6a63 0%, #5b594f 46%, #494740 100%);
      font-family: 'American Typewriter', 'Courier New', Courier, monospace;
      -webkit-font-smoothing: antialiased;
    }
    .t-librarycard * { box-sizing: border-box; }

    /* the pocket the card is tucked into (skin: in-pocket adds .is-pocketed) */
    .t-librarycard__slot {
      position: relative;
      width: 760px;
      max-width: 100%;
    }

    /* the card itself: aged stock, faint paper grain, a hair of rotation */
    .t-librarycard__card {
      position: relative;
      z-index: 1;
      color: var(--ink);
      background:
        repeating-linear-gradient(0deg, rgba(60,45,20,0.020) 0, rgba(60,45,20,0.020) 1px, transparent 1px, transparent 5px),
        repeating-linear-gradient(90deg, rgba(60,45,20,0.013) 0, rgba(60,45,20,0.013) 1px, transparent 1px, transparent 4px),
        radial-gradient(120% 120% at 50% 0%, var(--stock) 0%, var(--stock2) 100%);
      padding: clamp(28px, 3.6vw, 56px) clamp(24px, 3.4vw, 52px) var(--card-pad-b, clamp(30px, 4vw, 56px));
      transform: rotate(-0.5deg);
      box-shadow:
        0 1px 0 rgba(255,255,255,0.35) inset,
        0 14px 30px -20px rgba(14,12,8,0.55),
        0 3px 9px -5px rgba(14,12,8,0.4);
    }
    .t-librarycard__slot.is-pocketed .t-librarycard__card { --card-pad-b: 150px; }

    /* ---- printed furniture (compact serif) ---- */
    .t-librarycard__ex {
      font-family: Charter, Georgia, 'Times New Roman', serif;
      font-size: 12px;
      letter-spacing: 0.26em;
      text-transform: uppercase;
      color: var(--ink-soft);
      margin: 0 0 14px;
      padding-left: 0.26em;
    }
    .t-librarycard__masthead {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 18px;
      border-bottom: 3px double var(--ink-soft);
      padding-bottom: 14px;
      margin-bottom: 4px;
    }
    .t-librarycard__title {
      font-family: Charter, Georgia, 'Times New Roman', serif;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.015em;
      line-height: 0.98;
      font-size: clamp(30px, 4.7vw, 56px);
      margin: 0;
      color: var(--ink);
      /* worn letterpress: a whisper of ink spread, nothing more */
      text-shadow: 0 0.5px 0 rgba(0,0,0,0.10);
    }
    .t-librarycard__cardno {
      font-family: Charter, Georgia, 'Times New Roman', serif;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.10em;
      font-size: clamp(12px, 1.3vw, 15px);
      line-height: 1.25;
      text-align: right;
      color: var(--ink-soft);
      white-space: nowrap;
      flex: 0 0 auto;
    }
    .t-librarycard__cardno b {
      display: block;
      font-size: clamp(17px, 1.9vw, 22px);
      letter-spacing: 0.16em;
      color: var(--ink);
    }

    /* ---- the borrow table ---- */
    .t-librarycard__tbl {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      margin-top: 20px;
      font-variant-numeric: tabular-nums;
    }
    .t-librarycard__tbl col.c-date { width: clamp(84px, 15%, 128px); }
    .t-librarycard__tbl col.c-due  { width: clamp(78px, 13%, 116px); }
    .t-librarycard__tbl th {
      font-family: Charter, Georgia, 'Times New Roman', serif;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.2em;
      font-size: 11px;
      color: var(--ink-soft);
      text-align: left;
      padding: 0 12px 8px;
      border-bottom: 1.5px solid var(--ink-soft);
    }
    .t-librarycard__tbl th.h-due { text-align: right; }
    .t-librarycard__tbl td {
      padding: 13px 12px;
      border-bottom: 1px solid var(--rule);
      vertical-align: top;
    }
    .t-librarycard__tbl tr:last-child td { border-bottom: 1.5px solid var(--ink-soft); }

    .t-librarycard__caprow td {
      border-bottom: none;
      padding: 20px 12px 4px;
    }
    .t-librarycard__cap {
      font-family: Charter, Georgia, 'Times New Roman', serif;
      text-transform: uppercase;
      letter-spacing: 0.22em;
      font-size: 11px;
      color: var(--ink-soft);
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .t-librarycard__cap::after {
      content: "";
      flex: 1 1 auto;
      height: 0;
      border-bottom: 1px solid var(--rule);
    }

    .t-librarycard__item {
      font-size: 15px;
      line-height: 1.4;
      color: var(--ink);
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    .t-librarycard__verb {
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      font-size: 12.5px;
      margin-right: 2px;
    }
    .t-librarycard__note {
      display: block;
      margin-top: 4px;
      font-size: 11.5px;
      line-height: 1.4;
      color: var(--ink-soft);
    }
    .t-librarycard__due {
      text-align: right;
      font-size: 14px;
      color: var(--ink);
      white-space: nowrap;
    }
    .t-librarycard__due.is-eod { letter-spacing: 0.08em; }
    /* the ask: an empty due cell, only a faint waiting line */
    .t-librarycard__due.is-blank::after {
      content: "";
      display: inline-block;
      width: 100%;
      max-width: 70px;
      border-bottom: 1px solid var(--ink-soft);
      opacity: 0.55;
      vertical-align: middle;
    }

    /* ---- CSS-only rubber stamps (no images) ---- */
    .t-librarycard__stamp {
      display: inline-block;
      font-family: 'American Typewriter', 'Courier New', Courier, monospace;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--stamp);
      border: 2px solid var(--stamp);
      opacity: 0.72;
      transform: rotate(var(--rot, 0deg));
      /* faint, uneven ink: the stamp never seats perfectly flat */
      mix-blend-mode: multiply;
    }
    .t-librarycard__stamp.s-date {
      font-size: 12px;
      padding: 3px 6px 2px;
      border-radius: 2px;
      line-height: 1;
    }
    .t-librarycard__stamp.s-return {
      font-size: 12.5px;
      padding: 4px 9px 3px;
      border-width: 2.5px;
      border-radius: 3px;
      line-height: 1;
    }

    /* ---- foot: signature, tally, deck, colophon ---- */
    .t-librarycard__foot { margin-top: 30px; }
    .t-librarycard__sign {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 24px;
      flex-wrap: wrap;
    }
    .t-librarycard__signline { flex: 1 1 220px; min-width: 180px; }
    .t-librarycard__signrule {
      border-bottom: 1.5px solid var(--ink);
      height: 26px;
    }
    .t-librarycard__signwho {
      font-size: 12.5px;
      letter-spacing: 0.06em;
      color: var(--ink);
      margin-top: 6px;
    }
    .t-librarycard__signwho b { letter-spacing: 0.1em; }
    .t-librarycard__signcap {
      font-family: Charter, Georgia, 'Times New Roman', serif;
      text-transform: uppercase;
      letter-spacing: 0.2em;
      font-size: 10px;
      color: var(--ink-soft);
      text-align: right;
    }

    .t-librarycard__tally {
      margin-top: 22px;
      padding-top: 14px;
      border-top: 1px solid var(--rule);
      font-size: 12.5px;
      line-height: 1.6;
      color: var(--ink);
      font-variant-numeric: tabular-nums;
    }
    .t-librarycard__tally .k {
      font-family: Charter, Georgia, 'Times New Roman', serif;
      text-transform: uppercase;
      letter-spacing: 0.2em;
      font-size: 10px;
      color: var(--ink-soft);
      display: block;
      margin-bottom: 4px;
    }
    .t-librarycard__deck {
      margin-top: 16px;
      font-size: 12.5px;
      line-height: 1.55;
      color: var(--ink-soft);
    }
    .t-librarycard__colophon {
      margin-top: 14px;
      font-family: Charter, Georgia, 'Times New Roman', serif;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 10px;
      color: var(--ink-soft);
    }

    /* ---- the manila pocket the card is tucked into ---- */
    .t-librarycard__pocket {
      position: absolute;
      left: -14px;
      right: -14px;
      bottom: -18px;
      height: 176px;
      z-index: 2;
      background:
        repeating-linear-gradient(0deg, rgba(70,52,20,0.03) 0, rgba(70,52,20,0.03) 1px, transparent 1px, transparent 5px),
        linear-gradient(180deg, var(--pocket) 0%, var(--pocket-lo) 100%);
      /* diagonal-cut top edge, the classic library book pocket */
      clip-path: polygon(0 34px, 42% 34px, 58% 0, 100% 0, 100% 100%, 0 100%);
      box-shadow:
        0 -1px 0 rgba(255,255,255,0.25) inset,
        0 16px 26px -20px rgba(14,12,8,0.5);
    }
    .t-librarycard__pocket span {
      position: absolute;
      left: 0; right: 0;
      bottom: 26px;
      text-align: center;
      font-family: Charter, Georgia, 'Times New Roman', serif;
      text-transform: uppercase;
      letter-spacing: 0.28em;
      font-size: 11px;
      color: var(--pocket-ink);
      padding-left: 0.28em;
    }
    .t-librarycard__pocket span small {
      display: block;
      margin-top: 5px;
      letter-spacing: 0.16em;
      font-size: 9px;
      opacity: 0.8;
    }

    @media (max-width: 560px) {
      .t-librarycard__masthead { flex-direction: column; align-items: flex-start; gap: 8px; }
      .t-librarycard__cardno { text-align: left; }
      .t-librarycard__tbl td, .t-librarycard__tbl th { padding-left: 8px; padding-right: 8px; }
      .t-librarycard__item { font-size: 14px; }
    }
  `;

  function lcStamp(cls, text, i) {
    return (
      `<span class="t-librarycard__stamp ${cls}" style="--rot:${rot(i)}deg">` +
      caps(text) +
      `</span>`
    );
  }
  function lcRow(dateStamp, itemHtml, dueHtml, i) {
    return (
      `<tr>` +
      `<td>${dateStamp}</td>` +
      `<td class="t-librarycard__item">${itemHtml}</td>` +
      `<td class="t-librarycard__due ${dueHtml.cls}">${dueHtml.body}</td>` +
      `</tr>`
    );
  }
  // caption text is a trusted static literal (may carry an entity); CSS uppercases it
  function lcCap(text) {
    return (
      `<tr class="t-librarycard__caprow"><td colspan="3">` +
      `<span class="t-librarycard__cap">${text}</span>` +
      `</td></tr>`
    );
  }

  EXPLORER.register({
    id: "librarycard",
    name: 'The Library Card',
    axes: {
      stock: [
        { id: "manila", label: "Manila", stock: "#e9dcbe", stock2: "#ddcca4" },
        { id: "cream", label: "Cream", stock: "#f3ecda", stock2: "#e9dfc6" },
        { id: "sage", label: 'Pale sage', stock: "#e0e5d4", stock2: "#d3dac1" },
      ],
      ink: [
        {
          id: "red",
          label: "Faded red stamp",
          stamp: "#b0402f",
        },
        {
          id: "blue",
          label: "Faded blue stamp",
          stamp: "#3c5b7c",
        },
        {
          id: "black",
          label: "Near-black stamp",
          stamp: "#2c2a24",
        },
      ],
      pocket: [
        { id: "in", label: "Tucked in pocket", pocketed: true },
        { id: "bare", label: 'Bare card', pocketed: false },
      ],
      ruling: [
        {
          id: "bluegray",
          label: "Blue-gray ruling",
          rule: "rgba(96,112,132,0.42)",
        },
        {
          id: "sepia",
          label: "Warm sepia ruling",
          rule: "rgba(150,116,74,0.46)",
        },
      ],
    },
    css: LIBRARYCARD_CSS,
    render(ed, skin) {
      const { stock, ink, pocket, ruling } = skin;
      const c = ed.content;
      const s = c.stats;
      const dateText = `${ed.monthShort} ${ed.day}`; // JUL 3

      let ri = 0; // running row index → stamp rotation ring
      const dateStamp = () => lcStamp("s-date", dateText, ri);

      const todayRows = c.today
        .map((it) => {
          const item =
            esc(it.label) +
            (it.note
              ? `<span class="t-librarycard__note">${esc(it.note)}</span>`
              : "");
          const t = it.t24 || "EOD";
          const due = { cls: it.t24 ? "" : "is-eod", body: esc(t) };
          const row = lcRow(dateStamp(), item, due, ri);
          ri++;
          return row;
        })
        .join("");

      const overnightRows = c.overnight
        .map((it) => {
          const item =
            esc(it.label) +
            (it.note
              ? `<span class="t-librarycard__note">${esc(it.note)}</span>`
              : "");
          const due = { cls: "", body: lcStamp("s-return", it.tag, ri) };
          const row = lcRow(dateStamp(), item, due, ri);
          ri++;
          return row;
        })
        .join("");

      const decisionRows = c.decisions
        .map((it) => {
          const item =
            `<span class="t-librarycard__verb">${caps(it.verb)}</span>` +
            esc(it.label) +
            (it.note
              ? `<span class="t-librarycard__note">${esc(it.note)}</span>`
              : "");
          const due = { cls: "is-blank", body: "" };
          const row = lcRow(dateStamp(), item, due, ri);
          ri++;
          return row;
        })
        .join("");

      const table =
        `<table class="t-librarycard__tbl">` +
        `<colgroup><col class="c-date"><col class="c-item"><col class="c-due"></colgroup>` +
        `<thead><tr><th>Date</th><th>Item</th><th class="h-due">Due</th></tr></thead>` +
        `<tbody>` +
        lcCap("Checked out &mdash; today") +
        todayRows +
        lcCap("Returned overnight by GAIA") +
        overnightRows +
        lcCap("Awaiting your signature") +
        decisionRows +
        `</tbody></table>`;

      const foot =
        `<div class="t-librarycard__foot">` +
        `<div class="t-librarycard__sign">` +
        `<div class="t-librarycard__signline">` +
        `<div class="t-librarycard__signrule"></div>` +
        `<div class="t-librarycard__signwho">Prepared by <b>GAIA</b> &mdash; librarian on duty</div>` +
        `</div>` +
        `<div class="t-librarycard__signcap">Issued ${esc(ed.time24)}<br>${caps(ed.weekday)}</div>` +
        `</div>` +
        `<div class="t-librarycard__tally">` +
        `<span class="k">This card&rsquo;s record</span>` +
        `Items returned ${s.done} &mdash; ${s.you} by your hand, ${s.gaia} by GAIA` +
        ` &middot; Correspondence filed ${s.mail} &middot; Focus held ${esc(s.focus)}` +
        `</div>` +
        `<p class="t-librarycard__deck">${esc(ed.deck)}</p>` +
        `<p class="t-librarycard__colophon">GAIA Circulation Desk &middot; Card N&ordm; ${ed.editionNo} &middot; ${esc(ed.dateLong)}</p>` +
        `</div>`;

      const pocketEl = pocket.pocketed
        ? `<div class="t-librarycard__pocket"><span>Return to GAIA Circulation<small>Date due as stamped &middot; card n&ordm; ${ed.editionNo}</small></span></div>`
        : "";

      const style =
        `--stock:${stock.stock};--stock2:${stock.stock2};` +
        `--ink:#2b2820;--ink-soft:#6d6555;` +
        `--rule:${ruling.rule};--stamp:${ink.stamp};` +
        `--pocket:#d9c69c;--pocket-lo:#cbb384;--pocket-ink:#6a5432;`;

      return (
        `<article class="t-librarycard" style="${style}">` +
        `<div class="t-librarycard__slot ${pocket.pocketed ? "is-pocketed" : ""}">` +
        `<div class="t-librarycard__card">` +
        `<p class="t-librarycard__ex">Ex Libris &middot; GAIA Circulation</p>` +
        `<div class="t-librarycard__masthead">` +
        `<h1 class="t-librarycard__title">The ${esc(ed.weekday)}<br>Brief</h1>` +
        `<div class="t-librarycard__cardno">Card<b>N&ordm; ${ed.editionNo}</b></div>` +
        `</div>` +
        table +
        foot +
        `</div>` +
        pocketEl +
        `</div>` +
        `</article>`
      );
    },
  });

  /* ============================================================================
   * MENU — the day as a Michelin tasting menu. Centred, hairline restraint.
   * ==========================================================================*/
  const MENU_CSS = `
    .t-menu {
      width: 100%;
      margin: 0;
      box-sizing: border-box;
      padding: clamp(40px, 6vw, 104px) clamp(18px, 5vw, 72px) clamp(48px, 7vw, 112px);
      display: flex;
      justify-content: center;
      align-items: flex-start;
      color: var(--ink);
      background:
        var(--laid, none),
        var(--paper);
      font-family: 'Iowan Old Style', 'Palatino Linotype', Palatino, Georgia, serif;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }
    .t-menu * { box-sizing: border-box; }

    .t-menu__frame {
      width: 600px;
      max-width: 100%;
      text-align: center;
      border: var(--frame-border, none);
      padding: var(--frame-pad, 0);
    }

    .t-menu__marque {
      font-family: var(--display), Georgia, serif;
      font-weight: 500;
      letter-spacing: 0.52em;
      font-size: clamp(15px, 1.8vw, 20px);
      text-transform: uppercase;
      margin: 0 0 18px;
      padding-left: 0.52em;
      color: var(--ink);
    }
    .t-menu__dujour {
      font-style: italic;
      font-size: clamp(16px, 1.9vw, 21px);
      color: var(--ink);
      margin: 0 0 12px;
    }
    .t-menu__date {
      text-transform: uppercase;
      letter-spacing: 0.24em;
      font-size: 11px;
      color: var(--ink-soft);
      margin: 0;
      padding-left: 0.24em;
      font-variant-numeric: tabular-nums;
    }
    .t-menu__epigraph {
      font-style: italic;
      font-size: 13.5px;
      line-height: 1.6;
      color: var(--ink-soft);
      max-width: 40ch;
      margin: 16px auto 0;
    }

    .t-menu__rule {
      height: 0;
      width: 46px;
      margin: 30px auto;
      border-top: 1px solid var(--ink-soft);
    }
    .t-menu__rule.is-wide { width: 100%; }

    .t-menu__course { margin: 30px 0; }
    .t-menu__label {
      text-transform: uppercase;
      letter-spacing: 0.32em;
      font-size: 11px;
      color: var(--ink-soft);
      margin: 0 0 12px;
      padding-left: 0.32em;
    }
    .t-menu__label .em { color: var(--accent); margin: 0 0.5em; }
    .t-menu__dish {
      font-family: var(--display), Georgia, serif;
      font-weight: 500;
      font-size: clamp(23px, 3vw, 31px);
      line-height: 1.18;
      color: var(--ink);
      margin: 0;
      overflow-wrap: break-word;
    }
    .t-menu__time {
      text-transform: uppercase;
      letter-spacing: 0.22em;
      font-size: 11px;
      color: var(--ink-soft);
      margin: 10px 0 0;
      padding-left: 0.22em;
    }
    .t-menu__desc {
      font-style: italic;
      font-size: 14.5px;
      line-height: 1.6;
      color: var(--ink-soft);
      max-width: 42ch;
      margin: 12px auto 0;
    }

    .t-menu__section { margin: 8px 0; }
    .t-menu__sechead {
      font-style: italic;
      font-size: clamp(15px, 1.8vw, 18px);
      color: var(--ink);
      margin: 0 0 16px;
    }
    .t-menu__mise {
      list-style: none;
      padding: 0;
      margin: 0;
    }
    .t-menu__mise li {
      font-size: 13.5px;
      line-height: 1.5;
      color: var(--ink-soft);
      margin: 0 0 9px;
      max-width: 46ch;
      margin-left: auto;
      margin-right: auto;
    }

    .t-menu__decisions .t-menu__sechead::before,
    .t-menu__decisions .t-menu__sechead::after {
      content: "";
      display: block;
      width: 30px;
      margin: 0 auto;
      border-top: 1px solid var(--accent);
    }
    .t-menu__decisions .t-menu__sechead::before { margin-bottom: 14px; }
    .t-menu__decisions .t-menu__sechead::after { margin-top: 14px; }
    .t-menu__decision {
      font-size: 15px;
      line-height: 1.55;
      color: var(--ink);
      margin: 0 auto 12px;
      max-width: 44ch;
    }
    .t-menu__decision .verb {
      font-style: italic;
      color: var(--accent);
    }
    .t-menu__decision small {
      display: block;
      font-size: 12px;
      color: var(--ink-soft);
      margin-top: 3px;
    }

    .t-menu__digestif {
      font-style: italic;
      font-size: clamp(16px, 2vw, 20px);
      color: var(--ink);
      margin: 36px 0 0;
    }

    .t-menu__stats {
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 10.5px;
      color: var(--ink-soft);
      margin: 30px 0 0;
      line-height: 1.7;
      font-variant-numeric: tabular-nums;
    }
    .t-menu__colophon {
      text-transform: uppercase;
      letter-spacing: 0.2em;
      font-size: 9px;
      color: var(--ink-soft);
      margin: 14px 0 0;
      padding-left: 0.2em;
    }

    @media (max-width: 560px) {
      .t-menu__frame { padding: var(--frame-pad-sm, 0); }
    }
  `;

  function menuCourse(label, dish, time, desc) {
    return (
      `<div class="t-menu__course">` +
      `<p class="t-menu__label"><span class="em">&mdash;</span>${esc(label)}<span class="em">&mdash;</span></p>` +
      `<h2 class="t-menu__dish">${esc(dish)}</h2>` +
      (time ? `<p class="t-menu__time">${esc(time)}</p>` : "") +
      (desc ? `<p class="t-menu__desc">${esc(desc)}</p>` : "") +
      `</div>`
    );
  }

  EXPLORER.register({
    id: "menu",
    name: 'The Tasting Menu',
    axes: {
      paper: [
        { id: "ivory", label: "Ivory", paper: "#f7f2e6", laid: "none" },
        { id: "white", label: 'Bright white', paper: "#fcfbf7", laid: "none" },
        {
          id: "ecru",
          label: 'Ecru laid',
          paper: "#efe6d3",
          laid: "repeating-linear-gradient(90deg, rgba(120,96,54,0.05) 0, rgba(120,96,54,0.05) 1px, transparent 1px, transparent 7px)",
        },
      ],
      face: [
        {
          id: "playfair",
          label: 'Playfair Display',
          display: "'Playfair Display'",
        },
        {
          id: "didot",
          label: "Didot",
          display: "Didot, 'Bodoni 72', 'Hoefler Text'",
        },
        {
          id: "baskerville",
          label: "Baskerville",
          display: "Baskerville, 'Baskerville Old Face', 'Hoefler Text'",
        },
      ],
      accent: [
        { id: "gold", label: 'Aged gold', accent: "#9c7b3b" },
        { id: "oxblood", label: "Oxblood", accent: "#7c2f2c" },
        { id: "none", label: 'No accent', accent: "#26221b" },
      ],
      frame: [
        { id: "framed", label: 'Hairline frame', framed: true },
        { id: "frameless", label: "Frameless", framed: false },
      ],
    },
    css: MENU_CSS,
    render(ed, skin) {
      const { paper, face, accent, frame } = skin;
      const c = ed.content;
      const s = c.stats;

      const marque = "G A I A";
      const dateLine = `${caps(ed.weekday)} &middot; ${ed.day} ${caps(ed.month)} ${ed.year} &middot; Service N&ordm; ${ed.editionNo}`;

      const courses =
        menuCourse("First", c.today[0].label, c.today[0].t24, c.today[0].note) +
        menuCourse("Second", c.today[1].label, c.today[1].t24, c.today[1].note) +
        menuCourse('To finish', c.today[2].label, c.today[2].t24, c.today[2].note);

      // mise en place — the overnight work, re-voiced small
      const miseLines = [
        `${esc(c.overnight[0].label)}${c.overnight[0].note ? ` &mdash; ${esc(c.overnight[0].note)}` : ""}`,
        `${esc(c.overnight[1].label)}${c.overnight[1].note ? ` &mdash; ${esc(c.overnight[1].note)}` : ""}`,
        `${esc(c.overnight[2].label)}${c.overnight[2].note ? `; ${esc(c.overnight[2].note)}` : ""}`,
      ];
      const mise =
        `<div class="t-menu__section">` +
        `<p class="t-menu__sechead">prepared overnight</p>` +
        `<ul class="t-menu__mise">` +
        miseLines.map((l) => `<li>${l}</li>`).join("") +
        `</ul></div>`;

      const decisions =
        `<div class="t-menu__section t-menu__decisions">` +
        `<p class="t-menu__sechead">awaiting the table&rsquo;s decision</p>` +
        c.decisions
          .map(
            (d) =>
              `<p class="t-menu__decision"><span class="verb">to ${esc(d.verb.toLowerCase())}</span> &mdash; ${esc(d.label)}${d.note ? `<small>${esc(d.note)}</small>` : ""}</p>`,
          )
          .join("") +
        `</div>`;

      const stats =
        `couverts ${s.done} &mdash; ${s.you} by your hand, ${s.gaia} by the kitchen` +
        ` &middot; correspondence ${s.mail} &middot; ${esc(s.focus)
          .replace(".5h", "&frac12; hours")
          .replace(/(\d+)h$/, "$1 hours")} held`;

      const frameBorder = frame.framed
        ? "--frame-border:1px solid var(--ink-soft);--frame-pad:clamp(40px,5vw,72px);--frame-pad-sm:28px 18px;"
        : "";

      const style =
        `--paper:${paper.paper};--laid:${paper.laid};` +
        `--ink:#26221b;--ink-soft:#7a7060;` +
        `--display:${face.display};--accent:${accent.accent};` +
        frameBorder;

      return (
        `<article class="t-menu" style="${style}">` +
        `<div class="t-menu__frame">` +
        `<p class="t-menu__marque">${marque}</p>` +
        `<p class="t-menu__dujour">menu du jour</p>` +
        `<p class="t-menu__date">${dateLine}</p>` +
        `<p class="t-menu__epigraph">${esc(ed.deck)}</p>` +
        `<div class="t-menu__rule"></div>` +
        courses +
        `<div class="t-menu__rule is-wide"></div>` +
        mise +
        `<div class="t-menu__rule"></div>` +
        decisions +
        `<p class="t-menu__digestif">digestif &mdash; the evening is yours.</p>` +
        `<p class="t-menu__stats">${stats}</p>` +
        `<p class="t-menu__colophon">GAIA &middot; service n&ordm; ${ed.editionNo} &middot; seated ${esc(ed.time24)}</p>` +
        `</div>` +
        `</article>`
      );
    },
  });
})();
