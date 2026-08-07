/* ============================================================================
 * tpl-novel-e.js — one data-rich template for the daily-brief explorer.
 *
 *   weekly — "The Week": a Sunday-review editorial spread, the daily brief's
 *            grown-up sibling. The week's shape is drawn as the hero data
 *            object — seven Mon–Sun day-columns as a pure-CSS bar chart
 *            (you vs GAIA, ink + accent, weekend dimmed, one quiet gridline,
 *            hairline baseline, tabular numerals) — then an editorial grid:
 *            the numbers, shipped this week, handled quietly, still yours to
 *            call, the week ahead. Density is the point; hierarchy stays
 *            three-level obvious; sections part on hairlines and space.
 *
 * IMPORTANT: the weekly aggregates live in a DEMO fixture (`weekFixture`).
 * The daily `ed` object carries no weekly rollups, so this module declares
 * plausible, clearly-structured demo values — week number and date range are
 * derived from `ed` (weekNo = ceil(editionNo/7); the 7 days ending on ed's
 * date), the two open decisions and the week-ahead preview are re-voiced from
 * `ed.content`, and the totals / per-day counts / prose are fixed demo data.
 *
 * Deterministic — no Date.now / Math.random. Skin values arrive only as inline
 * custom properties consumed via var(). Wrapped in one IIFE so local helpers
 * never collide with sibling modules.
 * ==========================================================================*/
(() => {
  /* ---- text helpers ---------------------------------------------------- */
  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  const MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
  ];
  function monShort(name) {
    return name.slice(0, 3);
  }

  /* ---- chart geometry (fixed, deterministic) --------------------------- */
  // Per-day activity, Mon→Sun. YOU sums to 17, GAIA to 25 → 42 tasks done,
  // matching the totals below. Tuesday is the week's peak, Friday is you-heavy
  // (you shipped the big one) — this is the shape the deck names.
  const DAY_INITIALS = ["M", "T", "W", "T", "F", "S", "S"];
  const YOU = [3, 4, 2, 3, 4, 1, 0];
  const GAIA = [4, 6, 3, 3, 2, 4, 3];
  const WEEKEND = [false, false, false, false, false, true, true];

  const PLOT_H = 220; // px, the plot area height
  const BAR_SPAN = 176; // px the tallest bar fills — leaves headroom for labels
  const STACK_MAX = 10; // max stacked total (Tue: 4+6)
  const PAIR_MAX = 6; // max single value (Tue GAIA)
  const U_STACK = BAR_SPAN / STACK_MAX; // px per unit, stacked
  const U_PAIR = BAR_SPAN / PAIR_MAX; // px per unit, paired
  const GRID_Y = 88; // px from baseline — value 5 stacked / 3 paired, both land here

  function px(n) {
    return `${n.toFixed(1)}px`;
  }

  /* ---- demo weekly fixture, derived from ed where it can be ------------ */
  function weekFixture(ed) {
    const weekNo = Math.ceil(ed.editionNo / 7);
    const mi = MONTHS.indexOf(ed.month);
    const end = new Date(ed.year, mi, ed.day);
    const start = new Date(ed.year, mi, ed.day - 6);
    const sameYear = start.getFullYear() === end.getFullYear();
    const range =
      `${start.getDate()} ${monShort(MONTHS[start.getMonth()])}` +
      (sameYear ? "" : ` ${start.getFullYear()}`) +
      ` &ndash; ${end.getDate()} ${monShort(MONTHS[end.getMonth()])} ${end.getFullYear()}`;

    return {
      weekNo,
      range,
      deck: "A heavy Tuesday, a clean Friday. You shipped the big one.",
      stats: [
        {
          fig: "42",
          label: "tasks done",
          sub: "17 by you &middot; 25 by GAIA",
        },
        { fig: "217", label: "emails handled", sub: "inbox kept at zero" },
        {
          fig: "31.5",
          label: "focus hours",
          sub: "across five deep-work blocks",
        },
        {
          fig: "9",
          label: "meetings",
          sub: "three you ran &middot; six GAIA prepped",
        },
      ],
      shipped: [
        "Redesigned the dashboard and shipped it to production",
        "Closed the investor round &mdash; term sheet signed with Mehul",
        "Rewrote onboarding; activation up twelve points",
        "Cleared the Q2 bug backlog down to zero",
        "Stood up this weekly review and sent the first edition",
      ],
      quiet: [
        "Archived 340 newsletters and held the inbox at zero all week",
        "Rescheduled six conflicting meetings before you noticed them",
        "Drafted fourteen replies; sent the nine routine ones for you",
        "Filed and tagged every receipt for the quarter",
      ],
      // the two open decisions carry over from the daily brief, verbatim
      decisions: ed.content.decisions,
      decisionsMade: 5,
      decisionsPending: 2,
      // the week ahead re-voices the daily's "today" items as next week's plan
      ahead: [
        { day: "Mon", label: ed.content.today[0].label },
        { day: "Wed", label: ed.content.today[1].label },
        { day: "Fri", label: ed.content.today[2].label },
      ],
    };
  }

  /* ---- the chart ------------------------------------------------------- */
  function chartColumns(stacked) {
    let cols = "";
    for (let i = 0; i < 7; i++) {
      const you = YOU[i];
      const gaia = GAIA[i];
      const total = you + gaia;
      const wk = WEEKEND[i] ? " is-weekend" : "";
      let bars;
      if (stacked) {
        // you (ink) on top, GAIA (accent) at the base
        bars =
          `<div class="t-weekly__stack">` +
          `<div class="t-weekly__seg is-you" style="height:${px(you * U_STACK)}"></div>` +
          `<div class="t-weekly__seg is-gaia" style="height:${px(gaia * U_STACK)}"></div>` +
          `</div>`;
      } else {
        bars =
          `<div class="t-weekly__pair">` +
          `<div class="t-weekly__tb is-you" style="height:${px(you * U_PAIR)}"></div>` +
          `<div class="t-weekly__tb is-gaia" style="height:${px(gaia * U_PAIR)}"></div>` +
          `</div>`;
      }
      cols +=
        `<div class="t-weekly__col${wk}">` +
        `<div class="t-weekly__plot">` +
        `<div class="t-weekly__val">${total}</div>` +
        bars +
        `</div>` +
        `<div class="t-weekly__init">${DAY_INITIALS[i]}</div>` +
        `</div>`;
    }
    return cols;
  }

  const WEEKLY_CSS = `
    .t-weekly {
      width: 100%;
      margin: 0;
      box-sizing: border-box;
      padding: clamp(36px, 5vw, 76px) clamp(18px, 5vw, 84px) clamp(44px, 6vw, 88px);
      background: var(--paper);
      color: var(--ink);
      font-family: 'Helvetica Neue', Helvetica, system-ui, Arial, sans-serif;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
      font-variant-numeric: tabular-nums;
    }
    .t-weekly * { box-sizing: border-box; }
    .t-weekly__inner { width: 100%; max-width: 1012px; margin: 0 auto; }

    /* ---- masthead ---- */
    .t-weekly__kicker {
      text-transform: uppercase;
      letter-spacing: 0.34em;
      font-size: 11px;
      font-weight: 600;
      color: var(--ink-soft);
      margin: 0 0 18px;
      padding-left: 0.34em;
    }
    .t-weekly__head {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 24px;
      flex-wrap: wrap;
      border-bottom: 2px solid var(--ink);
      padding-bottom: 16px;
    }
    .t-weekly__title {
      font-family: var(--display), Georgia, serif;
      font-weight: 700;
      line-height: 0.92;
      letter-spacing: -0.01em;
      font-size: clamp(46px, 8vw, 94px);
      margin: 0;
    }
    .t-weekly__meta {
      text-align: right;
      flex: 0 0 auto;
      padding-bottom: 4px;
    }
    .t-weekly__no {
      font-family: var(--display), Georgia, serif;
      font-weight: 700;
      font-size: clamp(22px, 3vw, 32px);
      line-height: 1;
      margin: 0 0 6px;
    }
    .t-weekly__range {
      font-size: 13px;
      letter-spacing: 0.02em;
      color: var(--ink-soft);
      white-space: nowrap;
    }
    .t-weekly__deck {
      font-family: var(--display), Georgia, serif;
      font-style: italic;
      font-weight: 500;
      font-size: clamp(20px, 2.8vw, 30px);
      line-height: 1.28;
      margin: 22px 0 0;
      max-width: 24ch;
      color: var(--ink);
    }

    /* ---- section scaffolding ---- */
    .t-weekly__section { margin-top: clamp(34px, 4.2vw, 52px); }
    .t-weekly__h {
      font-family: var(--display), Georgia, serif;
      font-weight: 700;
      font-size: clamp(18px, 2vw, 23px);
      line-height: 1.1;
      margin: 0 0 20px;
      padding-top: 15px;
      border-top: 1px solid var(--ink);
    }
    .t-weekly__h .t-weekly__hnote {
      display: block;
      font-family: 'Helvetica Neue', Helvetica, system-ui, sans-serif;
      font-weight: 400;
      font-size: 12.5px;
      letter-spacing: 0;
      color: var(--ink-soft);
      margin-top: 5px;
    }

    /* ---- chart ---- */
    .t-weekly__legend {
      display: flex;
      gap: 20px;
      margin: 0 0 16px;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--ink-soft);
    }
    .t-weekly__legend span { display: inline-flex; align-items: center; gap: 7px; }
    .t-weekly__sw { width: 11px; height: 11px; display: inline-block; }
    .t-weekly__sw.is-you { background: var(--ink); }
    .t-weekly__sw.is-gaia { background: var(--accent); }

    .t-weekly__chart {
      position: relative;
      padding-top: 6px;
    }
    .t-weekly__grid {
      display: grid;
      grid-template-columns: repeat(7, 1fr);
      align-items: end;
      gap: clamp(4px, 1.2vw, 16px);
    }
    .t-weekly__col { text-align: center; }
    .t-weekly__plot {
      position: relative;
      height: ${PLOT_H}px;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      align-items: center;
    }
    /* one quiet reference gridline + a firm baseline, chart discipline */
    .t-weekly__plot::before {
      content: "";
      position: absolute;
      left: 0; right: 0;
      bottom: ${GRID_Y}px;
      border-top: 1px solid var(--rule);
    }
    .t-weekly__plot::after {
      content: "";
      position: absolute;
      left: 0; right: 0;
      bottom: 0;
      border-top: 1.5px solid var(--ink);
    }
    .t-weekly__val {
      position: relative;
      z-index: 1;
      font-size: 12px;
      font-weight: 600;
      color: var(--ink-soft);
      margin-bottom: 6px;
    }
    .t-weekly__stack {
      position: relative;
      z-index: 1;
      width: clamp(18px, 4.2vw, 42px);
      display: flex;
      flex-direction: column;
    }
    .t-weekly__seg.is-you { background: var(--ink); }
    .t-weekly__seg.is-gaia { background: var(--accent); }
    .t-weekly__pair {
      position: relative;
      z-index: 1;
      display: flex;
      align-items: flex-end;
      justify-content: center;
      gap: clamp(3px, 0.9vw, 6px);
    }
    .t-weekly__tb {
      width: clamp(8px, 1.9vw, 17px);
    }
    .t-weekly__tb.is-you { background: var(--ink); }
    .t-weekly__tb.is-gaia { background: var(--accent); }
    .t-weekly__col.is-weekend .t-weekly__seg,
    .t-weekly__col.is-weekend .t-weekly__tb { opacity: 0.42; }
    .t-weekly__col.is-weekend .t-weekly__init,
    .t-weekly__col.is-weekend .t-weekly__val { color: var(--ink-faint); }
    .t-weekly__init {
      margin-top: 10px;
      font-size: 12px;
      letter-spacing: 0.06em;
      color: var(--ink-soft);
    }

    /* ---- the numbers ---- */
    .t-weekly__nums {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: clamp(16px, 2.4vw, 34px);
    }
    .t-weekly__stat { min-width: 0; }
    .t-weekly__fig {
      font-family: var(--display), Georgia, serif;
      font-weight: 700;
      font-size: clamp(38px, 5.4vw, 62px);
      line-height: 0.94;
      letter-spacing: -0.015em;
    }
    .t-weekly__statlabel {
      font-size: 14px;
      color: var(--ink);
      margin-top: 10px;
    }
    .t-weekly__statsub {
      font-size: 11.5px;
      color: var(--ink-soft);
      margin-top: 3px;
      line-height: 1.4;
    }

    /* ---- editorial two-column grids ---- */
    .t-weekly__grid2 {
      display: grid;
      grid-template-columns: 1.15fr 1fr;
      gap: clamp(28px, 4vw, 60px);
    }

    .t-weekly__ship {
      list-style: none;
      counter-reset: ship;
      padding: 0;
      margin: 0;
    }
    .t-weekly__ship li {
      counter-increment: ship;
      position: relative;
      padding: 0 0 15px 42px;
      margin: 0 0 15px;
      border-bottom: 1px solid var(--rule);
      font-size: 15.5px;
      line-height: 1.4;
    }
    .t-weekly__ship li:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
    .t-weekly__ship li::before {
      content: counter(ship);
      position: absolute;
      left: 0;
      top: -2px;
      font-family: var(--display), Georgia, serif;
      font-weight: 700;
      font-size: 22px;
      color: var(--ink-soft);
      line-height: 1;
    }

    .t-weekly__quiet {
      list-style: none;
      padding: 0;
      margin: 0;
    }
    .t-weekly__quiet li {
      font-size: 13.5px;
      line-height: 1.5;
      color: var(--ink-soft);
      padding-bottom: 12px;
      margin-bottom: 12px;
      border-bottom: 1px solid var(--rule);
    }
    .t-weekly__quiet li:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }

    /* ---- decisions — the single accent moment ---- */
    .t-weekly__decision {
      padding: 2px 0 2px 18px;
      border-left: 3px solid var(--accent);
      margin-bottom: 20px;
    }
    .t-weekly__decision:last-child { margin-bottom: 0; }
    .t-weekly__verb {
      font-weight: 700;
      color: var(--accent);
      letter-spacing: 0.01em;
    }
    .t-weekly__dlabel { font-size: 16px; line-height: 1.4; }
    .t-weekly__dnote {
      display: block;
      font-size: 12.5px;
      color: var(--ink-soft);
      margin-top: 4px;
    }

    /* ---- the week ahead ---- */
    .t-weekly__ahead { display: grid; gap: 0; }
    .t-weekly__aheaditem {
      display: flex;
      gap: 18px;
      align-items: baseline;
      padding: 13px 0;
      border-bottom: 1px solid var(--rule);
    }
    .t-weekly__aheaditem:first-child { padding-top: 0; }
    .t-weekly__aheaditem:last-child { border-bottom: none; padding-bottom: 0; }
    .t-weekly__aday {
      flex: 0 0 auto;
      width: 3.4em;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 11px;
      font-weight: 600;
      color: var(--ink-soft);
      padding-top: 2px;
    }
    .t-weekly__atext { font-size: 15px; line-height: 1.4; }

    /* ---- colophon ---- */
    .t-weekly__colophon {
      margin-top: clamp(36px, 4.4vw, 56px);
      padding-top: 15px;
      border-top: 1.5px solid var(--ink);
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 10px;
      color: var(--ink-soft);
      line-height: 1.7;
    }

    @media (max-width: 720px) {
      .t-weekly__nums { grid-template-columns: repeat(2, 1fr); row-gap: 26px; }
      .t-weekly__grid2 { grid-template-columns: 1fr; gap: 34px; }
    }
    @media (max-width: 560px) {
      .t-weekly__head { align-items: flex-start; }
      .t-weekly__meta { text-align: left; }
      .t-weekly__range { white-space: normal; }
      .t-weekly__deck { max-width: none; }
    }
  `;

  EXPLORER.register({
    id: "weekly",
    name: "The Week (weekly review)",
    axes: {
      ground: [
        {
          id: "paper",
          label: "Paper white",
          paper: "#fdfcfa",
          ink: "#1a1a17",
          soft: "#6f6d66",
          faint: "#b3b1a9",
          rule: "#e2e0d8",
        },
        {
          id: "ivory",
          label: "Warm ivory",
          paper: "#f5f0e4",
          ink: "#26221a",
          soft: "#7a7264",
          faint: "#b8ad99",
          rule: "#e0d8c6",
        },
        {
          id: "ink",
          label: "Deep ink (inverted)",
          paper: "#16161a",
          ink: "#ece9e1",
          soft: "#9a978e",
          faint: "#5d5a55",
          rule: "#33333a",
        },
        {
          // The rich colored ground — deep forest green on champagne ink, the
          // weekend-supplement register (FT / Economist money-pages energy).
          // The accent axis is re-curated FOR this ground via a per-ground
          // `accents` map: the default accent hexes muddy or vanish against
          // deep green (the "field green" accent would sit green-on-green), so
          // each accent id resolves here to a champagne-jewel hue vetted to
          // sing — a teal, a chartreuse, a warm gold. Other grounds are
          // untouched and keep the shared accent axis.
          id: "green",
          label: "Editorial green (rich)",
          paper: "#173428",
          ink: "#efe9d8",
          soft: "#9fae9e",
          faint: "#5c6f61",
          rule: "#2b4a3a",
          accents: { blue: "#56b0cc", green: "#a6cd6b", amber: "#d8a44f" },
        },
      ],
      face: [
        {
          id: "playfair",
          label: "Playfair Display",
          display: "'Playfair Display'",
        },
        {
          id: "didot",
          label: "Didot",
          display: "Didot, 'Bodoni 72', 'Hoefler Text'",
        },
      ],
      accent: [
        { id: "blue", label: "Ink blue", accent: "#3a78c2" },
        { id: "green", label: "Field green", accent: "#4a9163" },
        { id: "amber", label: "Amber", accent: "#c08a3a" },
      ],
      chart: [
        { id: "stacked", label: "Stacked bars", stacked: true },
        { id: "paired", label: "Paired thin bars", stacked: false },
      ],
    },
    css: WEEKLY_CSS,
    render(ed, skin) {
      const { ground, face, accent, chart } = skin;
      const w = weekFixture(ed);

      const stats = w.stats
        .map(
          (s) =>
            `<div class="t-weekly__stat">` +
            `<div class="t-weekly__fig">${s.fig}</div>` +
            `<div class="t-weekly__statlabel">${s.label}</div>` +
            `<div class="t-weekly__statsub">${s.sub}</div>` +
            `</div>`,
        )
        .join("");

      const shipped =
        `<ol class="t-weekly__ship">` +
        w.shipped.map((t) => `<li>${t}</li>`).join("") +
        `</ol>`;

      const quiet =
        `<ul class="t-weekly__quiet">` +
        w.quiet.map((t) => `<li>${t}</li>`).join("") +
        `</ul>`;

      const decisions = w.decisions
        .map(
          (d) =>
            `<div class="t-weekly__decision">` +
            `<div class="t-weekly__dlabel"><span class="t-weekly__verb">${esc(d.verb)}</span> &mdash; ${esc(d.label)}` +
            (d.note
              ? `<span class="t-weekly__dnote">${esc(d.note)}</span>`
              : "") +
            `</div></div>`,
        )
        .join("");

      const ahead =
        `<div class="t-weekly__ahead">` +
        w.ahead
          .map(
            (a) =>
              `<div class="t-weekly__aheaditem">` +
              `<span class="t-weekly__aday">${esc(a.day)}</span>` +
              `<span class="t-weekly__atext">${esc(a.label)}</span>` +
              `</div>`,
          )
          .join("") +
        `</div>`;

      // A ground may re-curate the accent axis for itself via an `accents`
      // map keyed by accent id (see the editorial-green ground, where the
      // shared blue/green/amber would muddy against deep forest). Grounds
      // without a map fall back to the shared accent value.
      const accentColor =
        (ground.accents && ground.accents[accent.id]) || accent.accent;

      const style =
        `--paper:${ground.paper};--ink:${ground.ink};` +
        `--ink-soft:${ground.soft};--ink-faint:${ground.faint};--rule:${ground.rule};` +
        `--display:${face.display};--accent:${accentColor};`;

      return (
        `<article class="t-weekly" style="${style}">` +
        `<div class="t-weekly__inner">` +
        // masthead
        `<p class="t-weekly__kicker">GAIA &middot; weekly review</p>` +
        `<div class="t-weekly__head">` +
        `<h1 class="t-weekly__title">The Week</h1>` +
        `<div class="t-weekly__meta">` +
        `<p class="t-weekly__no">N&ordm; ${w.weekNo}</p>` +
        `<p class="t-weekly__range">${w.range}</p>` +
        `</div>` +
        `</div>` +
        `<p class="t-weekly__deck">${esc(w.deck)}</p>` +
        // hero chart
        `<section class="t-weekly__section">` +
        `<h2 class="t-weekly__h">The shape of the week` +
        `<span class="t-weekly__hnote">Tasks handled each day, yours and GAIA's</span></h2>` +
        `<div class="t-weekly__legend">` +
        `<span><i class="t-weekly__sw is-you"></i>You</span>` +
        `<span><i class="t-weekly__sw is-gaia"></i>GAIA</span>` +
        `</div>` +
        `<div class="t-weekly__chart"><div class="t-weekly__grid">` +
        chartColumns(chart.stacked) +
        `</div></div>` +
        `</section>` +
        // the numbers
        `<section class="t-weekly__section">` +
        `<h2 class="t-weekly__h">The numbers</h2>` +
        `<div class="t-weekly__nums">${stats}</div>` +
        `</section>` +
        // shipped + handled quietly
        `<section class="t-weekly__section"><div class="t-weekly__grid2">` +
        `<div><h2 class="t-weekly__h">Shipped this week</h2>${shipped}</div>` +
        `<div><h2 class="t-weekly__h">Handled quietly` +
        `<span class="t-weekly__hnote">Done by GAIA, no nudge needed</span></h2>${quiet}</div>` +
        `</div></section>` +
        // decisions + week ahead
        `<section class="t-weekly__section"><div class="t-weekly__grid2">` +
        `<div><h2 class="t-weekly__h">Still yours to call` +
        `<span class="t-weekly__hnote">${w.decisionsMade} decisions made &middot; ${w.decisionsPending} carried into next week</span></h2>${decisions}</div>` +
        `<div><h2 class="t-weekly__h">The week ahead</h2>${ahead}</div>` +
        `</div></section>` +
        // colophon
        `<p class="t-weekly__colophon">Weekly review &middot; compiled Sunday 18:00 by GAIA` +
        `<br>Week N&ordm; ${w.weekNo} &middot; ${w.range} &middot; from daily edition N&ordm; ${ed.editionNo}</p>` +
        `</div>` +
        `</article>`
      );
    },
  });
})();
