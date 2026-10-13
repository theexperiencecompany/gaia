/* ============================================================================
   tpl-poster.js — three "poster" templates for the Daily Brief explorer.
   Ported from hand-built variants: swiss (variant-timetable), dayline
   (variant-dayline), playbill (variant-playbill). Each is one committed
   print tradition, made skinnable via inline CSS custom properties.
   Wrapped in an IIFE so module-local helpers never collide with sibling
   modules that share the page's global script scope.
   ============================================================================ */
(() => {
  /* ---- shared helpers (module-private) ---- */
  const esc = (s) =>
    String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
  const ordinal = (d) => {
    const s = ["th", "st", "nd", "rd"];
    const v = d % 100;
    return d + (s[(v - 20) % 10] || s[v] || s[0]);
  };
  const to12 = (t24) => {
    const [H, M] = t24.split(":").map(Number);
    const ap = H < 12 ? "AM" : "PM";
    let h = H % 12;
    if (h === 0) h = 12;
    return `${h}:${String(M).padStart(2, "0")} ${ap}`;
  };

  // Uppercase advance table (em) for a geometric grotesk, deliberately
  // generous, so a headliner sized from it never overruns its measure.
  const CAP_ADV = {
    A: 0.72,
    B: 0.7,
    C: 0.75,
    D: 0.76,
    E: 0.62,
    F: 0.58,
    G: 0.79,
    H: 0.76,
    I: 0.24,
    J: 0.5,
    K: 0.7,
    L: 0.58,
    M: 0.92,
    N: 0.76,
    O: 0.8,
    P: 0.66,
    Q: 0.8,
    R: 0.7,
    S: 0.62,
    T: 0.64,
    U: 0.74,
    V: 0.72,
    W: 0.98,
    X: 0.7,
    Y: 0.68,
    Z: 0.64,
    " ": 0.4,
  };
  const capWidth = (s) =>
    [...s.toUpperCase()].reduce((w, c) => w + (CAP_ADV[c] ?? 0.72), 0);

  /* ==========================================================================
     1. SWISS  —  Müller-Brockmann timetable poster
     Thesis: the day as an International-Typographic grid — a colossal element
     bleeding the left edge (weekday spine OR stacked time numerals), a hard
     right schedule column of giant tabular figures, and one signal square as
     the day's only voice of colour, floating in deliberate whitespace.
     ========================================================================== */
  const swissCss = `
    .t-swiss {
      --ink: #0a0a0a; --mute: #8a8a8a; --slab: #444;
      position: relative;
      overflow: hidden;
      background: var(--paper);
      color: var(--ink);
      min-height: 1440px;
      padding: clamp(1.75rem, 4vw, 3.5rem);
      box-sizing: border-box;
      font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
      -webkit-font-smoothing: antialiased;
      font-variant-numeric: tabular-nums;
    }
    .t-swiss * { box-sizing: border-box; }

    .t-swiss .sw-spine {
      position: absolute;
      top: 0; bottom: 0;
      left: clamp(0.4rem, 1.4vw, 1.6rem);
      display: flex;
      align-items: center;
      pointer-events: none;
      user-select: none;
    }
    .t-swiss .sw-spine b {
      writing-mode: vertical-rl;
      transform: rotate(180deg);
      font-size: min(var(--spine-size), 15vw);
      font-weight: 700;
      letter-spacing: -0.055em;
      line-height: 0.78;
      color: var(--ink);
      white-space: nowrap;
    }

    .t-swiss .sw-content {
      position: relative;
      display: flex;
      flex-direction: column;
      min-height: 1280px;
      max-width: 62ch;
      margin-left: 0;
    }
    .t-swiss--spine .sw-content { margin-left: clamp(5.5rem, 21vw, 16rem); }

    /* stacked-numerals hero (second composition) */
    .t-swiss .sw-num { margin: 0 0 0.5rem clamp(-1.5rem, -2vw, -0.5rem); }
    .t-swiss .sw-num-fig {
      font-size: clamp(7rem, 19vw, 14rem);
      font-weight: 700;
      line-height: 0.8;
      letter-spacing: -0.05em;
      color: var(--ink);
    }
    .t-swiss .sw-num-cap {
      margin-top: 0.5rem;
      font-size: 0.66rem;
      font-weight: 700;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: var(--mute);
    }

    .t-swiss .sw-stamp {
      display: flex;
      flex-wrap: wrap;
      gap: 0.15rem 1.4rem;
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      padding-bottom: 0.5rem;
    }
    .t-swiss .sw-stamp span { white-space: nowrap; }
    .t-swiss .sw-wd { letter-spacing: 0.2em; }

    .t-swiss .sw-deck {
      font-size: clamp(1rem, 2.4vw, 1.35rem);
      font-style: italic;
      letter-spacing: -0.015em;
      line-height: 1.25;
      max-width: 46ch;
      margin: 0.5rem 0 0;
      padding-bottom: 1.1rem;
      border-bottom: 6px solid var(--ink);
    }

    .t-swiss .sw-board { margin-top: 1.15rem; }
    .t-swiss .sw-sec { margin-top: 1.3rem; }
    .t-swiss .sw-sec:first-child { margin-top: 0.35rem; }
    .t-swiss .sw-lab {
      display: flex;
      align-items: center;
      gap: 0.7rem;
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.24em;
      text-transform: uppercase;
      margin-bottom: 0.35rem;
    }
    .t-swiss .sw-n { color: var(--mute); }
    .t-swiss .sw-sq {
      width: 0.92rem; height: 0.92rem;
      background: var(--signal);
      flex: 0 0 auto;
    }

    .t-swiss .sw-item {
      display: grid;
      grid-template-columns: 5.25rem 1fr;
      gap: 0 1.15rem;
      align-items: baseline;
      padding: 0.5rem 0;
      border-top: 1px solid var(--hair);
    }
    .t-swiss .sw-sec .sw-item:last-child { border-bottom: 1px solid var(--hair); }
    .t-swiss .sw-t {
      font-weight: 700;
      letter-spacing: -0.03em;
      line-height: 1;
      white-space: nowrap;
    }
    .t-swiss .sw-t--timed { font-size: clamp(1.4rem, 3.4vw, 1.85rem); }
    .t-swiss .sw-t--past { font-size: 1rem; color: var(--mute); }
    .t-swiss .sw-t--none { font-size: 1rem; color: #bcbcbc; }
    .t-swiss .sw-d {
      font-size: clamp(0.88rem, 2vw, 1rem);
      line-height: 1.3;
      letter-spacing: -0.005em;
      align-self: center;
    }
    .t-swiss .sw-sub { color: var(--mute); }

    .t-swiss .sw-strip {
      display: grid;
      grid-template-columns: repeat(3, auto);
      gap: 0 clamp(1.5rem, 6vw, 4rem);
      margin-top: auto;
      padding-top: clamp(2.5rem, 6vw, 4.5rem);
    }
    .t-swiss .sw-fig {
      font-size: clamp(2.2rem, 6vw, 3.4rem);
      font-weight: 700;
      letter-spacing: -0.045em;
      line-height: 0.85;
    }
    .t-swiss .sw-slab {
      font-size: 0.6rem;
      font-weight: 700;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--slab);
      margin-top: 0.55rem;
      max-width: 16ch;
    }
    .t-swiss .sw-colophon {
      margin-top: 1.3rem;
      font-size: 0.6rem;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--mute);
    }

    @media (max-width: 820px) {
      .t-swiss .sw-item { grid-template-columns: 4.4rem 1fr; gap: 0 0.85rem; }
      .t-swiss .sw-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1.4rem 1.5rem; }
      .t-swiss .sw-slab { max-width: 18ch; }
    }
    @media (max-width: 540px) {
      .t-swiss .sw-strip { grid-template-columns: minmax(0, 1fr); gap: 1.2rem 0; }
    }
  `;

  function swItem(cls, time, desc, note) {
    const sub = note ? ` <span class="sw-sub">(${esc(note)})</span>` : "";
    return `<div class="sw-item"><div class="sw-t sw-t--${cls}">${time}</div><div class="sw-d">${desc}${sub}</div></div>`;
  }

  EXPLORER.register({
    id: "swiss",
    name: "The Swiss Timetable",
    axes: {
      composition: [
        { id: "spine", label: "weekday spine" },
        { id: "numerals", label: "stacked numerals" },
      ],
      signal: [
        { id: "red", label: "Vignelli red", accent: "#c8102e" },
        { id: "blue", label: "Swiss blue", accent: "#0b5bd3" },
        { id: "black", label: "black only", accent: "#0a0a0a" },
      ],
      ground: [
        {
          id: "paper",
          label: "paper white",
          paper: "#ffffff",
          hair: "#d8d8d8",
        },
        {
          id: "warm",
          label: "warm off-white",
          paper: "#f5f1e8",
          hair: "#ddd6c6",
        },
        {
          id: "cool",
          label: "cool gray-white",
          paper: "#eef0f2",
          hair: "#d3d8dc",
        },
        {
          id: "canary",
          label: "canary field",
          paper: "#f4c020",
          hair: "rgba(20,14,0,0.26)",
          ink: "#141006",
          mute: "#6b5410",
          slab: "#6b5410",
        },
        {
          id: "cobalt",
          label: "cobalt field",
          paper: "#123a72",
          hair: "rgba(255,255,255,0.22)",
          ink: "#ffffff",
          mute: "rgba(255,255,255,0.66)",
          slab: "rgba(255,255,255,0.74)",
          dark: true,
        },
      ],
    },
    css: swissCss,
    render(ed, skin) {
      const wd = ed.weekday.toUpperCase();
      const comp = skin.composition.id;
      const spineSize = Math.min(
        200,
        Math.floor(1250 / (ed.weekday.length * 0.82)),
      );
      const [gh, gm] = ed.time24.split(":");
      const stats = ed.content.stats;

      const today = ed.content.today
        .map((it) =>
          it.t24
            ? swItem("timed", it.t24, esc(it.label), it.note)
            : swItem("none", "&mdash;", esc(it.label), it.note),
        )
        .join("");
      const overnight = ed.content.overnight
        .map((it) => swItem("past", it.t24 || "&mdash;", esc(it.label), it.note))
        .join("");
      const decisions = ed.content.decisions
        .map((d) =>
          swItem(
            "none",
            "&mdash;",
            `<b>${esc(d.verb)}</b> &mdash; ${esc(d.label)}`,
            d.note,
          ),
        )
        .join("");

      const stamp = `<div class="sw-stamp">${
        comp === "numerals" ? `<span class="sw-wd">${wd}</span>` : ""
      }<span>${ed.day} ${esc(ed.month)} ${ed.year}</span><span>Edition N&ordm; ${
        ed.editionNo
      }</span><span>${ed.time24} &middot; GAIA</span></div>`;

      const numHero =
        comp === "numerals"
          ? `<div class="sw-num"><div class="sw-num-fig">${gh}</div><div class="sw-num-fig">${gm}</div><div class="sw-num-cap">Brief generated</div></div>`
          : "";
      const spineHero =
        comp === "spine" ? `<div class="sw-spine"><b>${wd}</b></div>` : "";

      // On a saturated field the type flips to the ground's own ink/mute/slab.
      // The lone red accent survives on cobalt; blue/black would vanish on deep
      // blue, so they resolve to white — a curated pairing, not a raw product.
      const g = skin.ground;
      const signal =
        g.dark && skin.signal.id !== "red" ? "#ffffff" : skin.signal.accent;
      const fieldVars = g.ink
        ? `--ink:${g.ink}; --mute:${g.mute}; --slab:${g.slab}; `
        : "";

      return `<article class="t-swiss t-swiss--${comp}" style="${fieldVars}--paper:${g.paper}; --hair:${g.hair}; --signal:${signal}; --spine-size:${spineSize}px">${spineHero}<div class="sw-content">${numHero}${stamp}<p class="sw-deck">${esc(
        ed.deck,
      )}</p><div class="sw-board"><section class="sw-sec"><div class="sw-lab"><span class="sw-n">01</span><span>What matters today</span></div>${today}</section><section class="sw-sec"><div class="sw-lab"><span class="sw-n">02</span><span>While you slept</span></div>${overnight}</section><section class="sw-sec"><div class="sw-lab"><span class="sw-sq"></span><span>Needs your call</span></div>${decisions}</section></div><div class="sw-strip"><div class="sw-stat"><div class="sw-fig">${stats.done}</div><div class="sw-slab">Done yesterday &middot; you ${stats.you} / GAIA ${stats.gaia}</div></div><div class="sw-stat"><div class="sw-fig">${stats.mail}</div><div class="sw-slab">Emails handled</div></div><div class="sw-stat"><div class="sw-fig">${esc(
        stats.focus,
      )}</div><div class="sw-slab">Focus time today</div></div></div><div class="sw-colophon">Edition N&ordm; ${
        ed.editionNo
      } &middot; Generated ${esc(ed.time)} by GAIA</div></div></article>`;
    },
  });

  /* ==========================================================================
     2. DAYLINE  —  the page IS the day
     Thesis: a single proportional time axis from 02:00 to 24:00, ruled like an
     instrument; events pinned at their true vertical position, overnight work
     dimmed, decisions floating untimed, and a vast empty evening carrying one
     italic line. The axis can sit 30% in or hug the left edge.
     ========================================================================== */
  const DL_PPH = 78; // px per hour — roomy vertical rhythm; full day runs ~1720px
  const DL_START = 2;
  const dlY = (t24) => {
    const [H, M] = t24.split(":").map(Number);
    return Math.round((H + M / 60 - DL_START) * DL_PPH);
  };

  /* Two type roles only — a body face for content and one mono utility for
     every measured mark (times, ruler, labels, figures). The two personality
     moments are the floating decisions and the lone evening line. */
  const daylineCss = `
    .t-dayline {
      --ink: #17181b; --dim: #8b9196; --faint: #c7ccd0;
      --mono: "SF Mono", "Menlo", ui-monospace, monospace;
      --ev-inset: 46px;
      background: var(--paper);
      color: var(--ink);
      display: block;
      width: 100%;
      overflow: hidden;
      -webkit-font-smoothing: antialiased;
      font-family: var(--body);
    }
    .t-dayline .dl-sheet {
      position: relative;
      max-width: 920px;
      margin: 0 auto;
      padding: 60px 44px 0;
      box-sizing: border-box;
    }
    .t-dayline .dl-sheet * { box-sizing: border-box; }

    /* masthead */
    .t-dayline .dl-mast { max-width: 44ch; margin: 0 0 8px; }
    .t-dayline .dl-kicker {
      font-family: var(--mono); font-size: 10px; letter-spacing: 0.24em;
      text-transform: uppercase; color: var(--dim); margin: 0 0 14px;
    }
    .t-dayline .dl-title {
      font-family: var(--body); font-weight: 600; font-size: 26px;
      line-height: 1.05; letter-spacing: -0.01em; margin: 0;
    }
    .t-dayline .dl-dateline {
      font-family: var(--mono); font-size: 11px; letter-spacing: 0.02em;
      color: var(--ink); font-variant-numeric: tabular-nums; margin: 10px 0 0;
    }
    .t-dayline .dl-deck {
      font-family: var(--body); font-style: italic; font-size: 15px;
      line-height: 1.5; color: #4a4d51; margin: 14px 0 0; max-width: 34ch;
    }

    /* the axis — a single ruled instrument line */
    .t-dayline .dl-axiswrap { position: relative; height: 1800px; margin-top: 40px; }
    .t-dayline .dl-axis {
      position: absolute; left: var(--axis); top: 0; bottom: 60px;
      width: 1px; background: var(--ink);
    }

    /* ticks — one 1px length for every hour; the hour label carries the
       major/minor distinction, aligned to its tick and set to the left */
    .t-dayline .dl-tick {
      position: absolute; left: var(--axis); top: calc(var(--t) * 1px); height: 0;
    }
    .t-dayline .dl-tick::before {
      content: ""; position: absolute; right: 0; top: 0;
      width: 8px; height: 1px; background: var(--faint); transform: translateY(-50%);
    }
    .t-dayline .dl-tick--major::before { background: var(--ink); width: 13px; }
    .t-dayline .dl-hour {
      position: absolute; right: 18px; top: 0; transform: translateY(-50%);
      font-family: var(--mono); font-size: 10px; letter-spacing: 0.04em;
      color: var(--faint); font-variant-numeric: tabular-nums; white-space: nowrap;
    }
    .t-dayline .dl-tick--major .dl-hour { color: var(--dim); }

    /* every pinned block shares one strict left edge (--ev-inset) and one
       1px connector back to the axis */
    .t-dayline .dl-clabel {
      position: absolute; left: var(--axis); top: calc(var(--t) * 1px);
      padding-left: var(--ev-inset); font-family: var(--mono); font-size: 10px;
      letter-spacing: 0.22em; text-transform: uppercase; color: var(--dim);
      transform: translateY(-50%);
    }
    .t-dayline .dl-ev {
      position: absolute; left: var(--axis); right: 0; top: calc(var(--t) * 1px);
      padding-left: var(--ev-inset); transform: translateY(-0.7em);
    }
    .t-dayline .dl-ev::before {
      content: ""; position: absolute; left: 0; top: 0.7em;
      width: 28px; height: 1px; background: var(--ink); transform: translateY(-50%);
    }
    .t-dayline .dl-time {
      display: block; font-family: var(--mono); font-size: 12px;
      letter-spacing: 0.04em; color: var(--ink);
      font-variant-numeric: tabular-nums; margin-bottom: 5px;
    }
    .t-dayline .dl-body { font-family: var(--body); font-size: 18px; line-height: 1.45; max-width: 46ch; }
    .t-dayline .dl-note {
      display: block; font-family: var(--body); font-size: 14px;
      line-height: 1.45; color: var(--dim); margin-top: 4px; max-width: 44ch;
    }

    /* overnight — dimmed, faint connector */
    .t-dayline .dl-ev--dim .dl-time, .t-dayline .dl-ev--dim .dl-body { color: var(--dim); }
    .t-dayline .dl-ev--dim .dl-body { font-size: 16px; max-width: 44ch; }
    .t-dayline .dl-ev--dim::before { background: var(--faint); }

    /* brief generated — the one accent mark on the axis, a confident node */
    .t-dayline .dl-ev--gen .dl-time { color: var(--accent); }
    .t-dayline .dl-ev--gen::before { background: var(--accent); height: 2px; width: 34px; }
    .t-dayline .dl-ev--gen::after {
      content: ""; position: absolute; left: 0; top: 0.7em;
      width: 9px; height: 9px; border-radius: 50%; background: var(--accent);
      transform: translate(-50%, -50%);
    }

    /* the lone evening line */
    .t-dayline .dl-evening {
      position: absolute; left: var(--axis); top: calc(var(--t) * 1px);
      padding-left: var(--ev-inset); font-family: var(--body); font-style: italic;
      font-size: 18px; color: #7d8286; max-width: 30ch; transform: translateY(-0.7em);
    }

    /* untimed decisions — float in the left margin when the axis is inset */
    .t-dayline .dl-decide {
      position: absolute; left: 0; width: calc(var(--axis) - 24px);
      top: calc(var(--t) * 1px);
    }
    .t-dayline .dl-decide-mark {
      width: 10px; height: 10px; border-radius: 50%;
      border: 1.5px solid var(--accent); margin-bottom: 10px;
    }
    .t-dayline .dl-decide-label {
      font-family: var(--mono); font-size: 9px; letter-spacing: 0.2em;
      text-transform: uppercase; color: var(--accent); margin-bottom: 8px;
    }
    .t-dayline .dl-decide-verb {
      display: block; font-family: var(--mono); font-size: 10px;
      letter-spacing: 0.08em; text-transform: uppercase; color: #4a4d51; margin-bottom: 3px;
    }
    .t-dayline .dl-decide-body {
      font-family: var(--body); font-size: 16px; line-height: 1.45; color: var(--ink);
    }
    /* hard-left axis: no margin to float in — pin to the right of the axis */
    .t-dayline--edge .dl-decide {
      left: var(--axis); width: auto; right: 0; padding-left: var(--ev-inset);
    }
    .t-dayline--edge .dl-decide-mark { position: absolute; left: -4px; top: 3px; margin: 0; }
    .t-dayline--edge .dl-hour { right: 14px; }

    /* footer figures */
    .t-dayline .dl-base {
      display: flex; flex-wrap: wrap; gap: 6px 28px; align-items: baseline;
      padding: 26px 0 60px; font-family: var(--mono); font-size: 11px;
      letter-spacing: 0.02em; color: #4a4d51; font-variant-numeric: tabular-nums;
    }
    .t-dayline .dl-base b { color: var(--ink); font-weight: 600; }
    .t-dayline .dl-colophon {
      margin-left: auto; color: var(--dim); letter-spacing: 0.08em;
      text-transform: uppercase; font-size: 10px;
    }
  `;

  EXPLORER.register({
    id: "dayline",
    name: "The Day Line",
    axes: {
      accent: [
        { id: "red", label: "deep red", accent: "#bf2d1f" },
        { id: "amber", label: "warm amber", accent: "#a86a00" },
        { id: "ink", label: "ink blue", accent: "#1f4e8c" },
      ],
      face: [
        {
          id: "serif",
          label: "Charter serif",
          body: "Charter, 'Iowan Old Style', Georgia, serif",
        },
        {
          id: "sans",
          label: "system sans",
          body: "system-ui, -apple-system, 'Helvetica Neue', sans-serif",
        },
      ],
      axis: [
        { id: "thirty", label: "axis inset 30%", pos: "30%" },
        { id: "edge", label: "hard left edge", pos: "72px" },
      ],
      ground: [
        { id: "paper", label: "paper white", paper: "#f7f8f9" },
        { id: "warm", label: "soft warm", paper: "#f4f1ea" },
      ],
    },
    css: daylineCss,
    render(ed, skin) {
      const edge = skin.axis.id === "edge";
      const stats = ed.content.stats;
      const gy = dlY(ed.time24);

      let ticks = "";
      for (let h = DL_START; h <= 24; h++) {
        const y = (h - DL_START) * DL_PPH;
        const major = h % 6 === 0;
        ticks += `<div class="dl-tick${major ? " dl-tick--major" : ""}" style="--t:${y}"><span class="dl-hour">${String(
          h,
        ).padStart(2, "0")}</span></div>`;
      }

      // Overnight is a dim pre-dawn *cluster*: pin to true time, but keep a
      // minimum vertical gap so near-coincident entries never overprint.
      const DL_DIM_GAP = 74;
      let dimPrev = -Infinity;
      const overnight = ed.content.overnight
        .filter((it) => it.t24)
        .map((it) => {
          let y = dlY(it.t24);
          if (y < dimPrev + DL_DIM_GAP) y = dimPrev + DL_DIM_GAP;
          dimPrev = y;
          return `<div class="dl-ev dl-ev--dim" style="--t:${y}"><time class="dl-time">${to12(
            it.t24,
          )}</time><div class="dl-body">${esc(it.label)}${
            it.note ? ` &mdash; ${esc(it.note)}` : ""
          }.</div></div>`;
        })
        .join("");

      const timed = ed.content.today
        .filter((it) => it.t24)
        .map(
          (it) =>
            `<div class="dl-ev" style="--t:${dlY(it.t24)}"><time class="dl-time">${esc(
              it.time,
            )}</time><div class="dl-body">${esc(it.label)}.${
              it.note ? `<span class="dl-note">${esc(it.note)}</span>` : ""
            }</div></div>`,
        )
        .join("");

      const decY = [dlY("09:30"), dlY("11:20")];
      const decisions = ed.content.decisions
        .map(
          (d, i) =>
            `<aside class="dl-decide" style="--t:${decY[i] != null ? decY[i] : dlY("09:30") + i * Math.round(DL_PPH * 1.9)}"><div class="dl-decide-mark"></div><div class="dl-decide-label">Needs your call</div><div class="dl-decide-body"><span class="dl-decide-verb">${esc(
              d.verb,
            )}</span>${esc(d.label)}${d.note ? `. ${cap(esc(d.note))}.` : ""}</div></aside>`,
        )
        .join("");

      const ship = ed.content.today.find((it) => !it.t24);
      const shipBlock = ship
        ? `<div class="dl-ev" style="--t:${dlY("17:30")}"><time class="dl-time">Before EOD</time><div class="dl-body">${esc(
            ship.label,
          )}.${ship.note ? `<span class="dl-note">${esc(ship.note)}</span>` : ""}</div></div>`
        : "";

      return `<article class="t-dayline${edge ? " t-dayline--edge" : ""}" style="--paper:${skin.ground.paper}; --accent:${skin.accent.accent}; --body:${skin.face.body}; --axis:${skin.axis.pos}"><div class="dl-sheet"><header class="dl-mast"><div class="dl-kicker">GAIA &middot; Daily Brief</div><h1 class="dl-title">The ${esc(
        ed.weekday,
      )} Brief</h1><div class="dl-dateline">${esc(ed.dateLong)} &middot; Edition No.&nbsp;${
        ed.editionNo
      }</div><p class="dl-deck">${esc(
        ed.deck,
      )}</p></header><div class="dl-axiswrap"><div class="dl-axis"></div>${ticks}<div class="dl-clabel" style="--t:-6">While you slept</div>${overnight}<div class="dl-ev dl-ev--gen" style="--t:${gy}"><time class="dl-time">${to12(
        ed.time24,
      )}</time><div class="dl-body">Brief generated by GAIA.</div></div>${decisions}<div class="dl-clabel" style="--t:${dlY(
        "12:40",
      )}">What matters today</div>${timed}${shipBlock}<div class="dl-evening" style="--t:${dlY(
        "20:00",
      )}">then the evening is yours.</div></div><footer class="dl-base"><div>Done yesterday <b>${
        stats.done
      }</b> &middot; you&nbsp;${stats.you} / GAIA&nbsp;${stats.gaia}</div><div>Emails handled <b>${
        stats.mail
      }</b></div><div>Focus time today <b>${esc(
        stats.focus,
      )}</b></div><div class="dl-colophon">Edition No.&nbsp;${ed.editionNo} &middot; Generated ${esc(
        ed.time,
      )} by GAIA</div></footer></div></article>`;
    },
  });

  /* ==========================================================================
     3. PLAYBILL  —  Hatch Show Print letterpress bill
     Thesis: a 19th-century theatre bill for a single day's performance —
     a double-ruled frame, every line a full-width lockup, condensed heavy caps
     against Baskerville-italic connectives, pointing hands as type furniture,
     and a giant weekday billed as the headliner that never crosses the frame.
     ========================================================================== */
  const playbillCss = `
    .t-playbill {
      --ink: #241c12;
      background: var(--paper);
      color: var(--ink);
      min-height: 1200px;
      overflow: hidden;
      display: flex;
      justify-content: center;
      padding: clamp(22px, 5vw, 64px) clamp(12px, 4vw, 40px);
      box-sizing: border-box;
      font-family: var(--face);
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
      font-variant-numeric: tabular-nums;
    }
    .t-playbill * { box-sizing: border-box; }

    .t-playbill .pb-bill {
      width: 100%;
      max-width: 620px;
      background: var(--paper);
      border: 3px solid var(--ink);
      outline: 1px solid var(--ink);
      outline-offset: 3px;
      padding: clamp(18px, 4.5vw, 44px) clamp(16px, 4.5vw, 46px);
      text-align: center;
      display: flex;
      flex-direction: column;
      align-items: stretch;
      container-type: inline-size;
    }

    .t-playbill .pb-rule {
      border: 0; border-top: 2px solid var(--ink);
      margin: clamp(12px, 2.4vw, 16px) 0; width: 100%;
    }
    .t-playbill .pb-rule.thin { border-top-width: 1px; }
    .t-playbill .pb-rule.thick { border-top-width: 6px; }
    .t-playbill .pb-rule.double {
      border-top: 3px solid var(--ink); border-bottom: 1px solid var(--ink);
      height: 5px; padding: 0;
    }
    .t-playbill .pb-rule.spot { border-top-color: var(--spot); }

    .t-playbill .pb-caps {
      text-transform: uppercase; font-weight: 700; line-height: 0.98; margin: 0;
    }
    .t-playbill .pb-spaced {
      text-transform: uppercase; letter-spacing: 0.34em; font-weight: 600;
      margin: 0.15em 0 0.15em 0.34em;
    }
    .t-playbill .pb-ital {
      font-family: Baskerville, "Iowan Old Style", Georgia, serif;
      font-style: italic; font-weight: 400; letter-spacing: 0;
      text-transform: none; line-height: 1.2; margin: 0;
    }

    .t-playbill .pb-presents { font-size: clamp(11px, 2.9vw, 15px); letter-spacing: 0.3em; }
    .t-playbill .pb-day {
      font-size: var(--day-size);
      letter-spacing: -0.02em; color: var(--spot); margin: 0.02em 0 0.04em;
      -webkit-text-stroke: 0.5px var(--spot); white-space: nowrap;
    }
    .t-playbill .pb-datum { font-size: clamp(13px, 3.4vw, 19px); letter-spacing: 0.16em; }
    .t-playbill .pb-edition { white-space: nowrap; margin-top: 0.25em; }
    .t-playbill .pb-deck {
      font-size: clamp(15px, 4vw, 22px); max-width: 30ch;
      margin: 0 auto; padding: clamp(4px, 1.4vw, 10px) 0;
    }

    .t-playbill .pb-billing { font-size: clamp(11px, 3vw, 15px); letter-spacing: 0.32em; margin-left: 0.32em; }
    .t-playbill .pb-act { padding: clamp(11px, 2.2vw, 14px) 0; }
    .t-playbill .pb-time { font-size: clamp(12px, 3.3vw, 17px); letter-spacing: 0.22em; margin-left: 0.22em; }
    .t-playbill .pb-head { font-size: clamp(30px, 9.6vw, 60px); letter-spacing: -0.005em; margin: 0.05em 0; }
    .t-playbill .pb-with { font-size: clamp(15px, 4vw, 21px); }
    .t-playbill .pb-head.pb-ship { color: var(--spot); }

    .t-playbill .pb-actsep {
      font-size: clamp(13px, 3.4vw, 18px); line-height: 1;
      margin: clamp(8px, 2vw, 11px) 0 clamp(8px, 2vw, 11px) 0.5em; letter-spacing: 0.5em;
    }

    .t-playbill .pb-banner { font-size: clamp(15px, 4.6vw, 26px); letter-spacing: 0.14em; }
    .t-playbill .pb-feat { font-size: clamp(15px, 4.3vw, 23px); letter-spacing: 0.01em; margin: 0.28em 0; }
    .t-playbill .pb-feat small {
      display: block; font-family: Baskerville, "Iowan Old Style", Georgia, serif;
      font-style: italic; font-weight: 400; text-transform: none; letter-spacing: 0;
      font-size: clamp(12px, 1.9vw, 14px); margin-top: 0.15em;
    }

    .t-playbill .pb-callhead { font-size: clamp(14px, 4.2vw, 23px); letter-spacing: 0.12em; color: var(--spot); }
    .t-playbill .pb-decision { font-size: clamp(19px, 5.8vw, 32px); letter-spacing: 0; margin: 0.2em 0; }
    .t-playbill .pb-decision small {
      display: block; font-family: Baskerville, "Iowan Old Style", Georgia, serif;
      font-style: italic; font-weight: 400; text-transform: none; letter-spacing: 0;
      font-size: clamp(12px, 2vw, 15px); margin-top: 0.18em;
    }
    .t-playbill .pb-hand {
      font-family: Georgia, "Times New Roman", serif; font-style: normal;
      display: inline-block; transform: translateY(0.06em); color: var(--spot);
    }

    .t-playbill .pb-figures {
      display: flex; justify-content: center; align-items: baseline; flex-wrap: wrap;
      gap: 0 clamp(10px, 3vw, 22px); font-size: clamp(13px, 3.7vw, 19px);
      letter-spacing: 0.14em; margin: 0 0 0 0.14em; text-transform: uppercase; font-weight: 700;
    }
    .t-playbill .pb-n { color: var(--spot); font-weight: 700; }
    .t-playbill .pb-dot { font-family: Georgia, serif; letter-spacing: 0; opacity: 0.8; font-weight: 400; }

    .t-playbill .pb-imprint {
      font-family: Baskerville, "Iowan Old Style", Georgia, serif;
      font-style: italic; font-size: clamp(12px, 2.9vw, 14px); letter-spacing: 0.02em;
      line-height: 1.4; margin: 0;
    }
    .t-playbill .pb-mark {
      font-style: normal; letter-spacing: 0.3em; text-transform: uppercase;
      font-family: var(--face); font-weight: 700; font-size: 0.92em;
      display: block; margin-bottom: 0.4em;
    }
  `;

  EXPLORER.register({
    id: "playbill",
    name: "The Playbill",
    axes: {
      spot: [
        { id: "red", label: "barn red", spot: "#a8231d" },
        { id: "blue", label: "union blue", spot: "#1c3f77" },
        { id: "black", label: "black only", spot: "#241c12" },
      ],
      display: [
        {
          id: "avenir",
          label: "Avenir Next Condensed",
          face: "'Avenir Next Condensed', 'Futura Condensed', 'Helvetica Neue', sans-serif",
          widthFactor: 0.72,
        },
        {
          id: "futura",
          label: "Futura",
          face: "Futura, 'Avenir Next Condensed', 'Helvetica Neue', sans-serif",
          widthFactor: 1,
        },
      ],
      paper: [
        { id: "cream", label: "playbill cream", paper: "#efe6d0" },
        { id: "canary", label: "canary stock", paper: "#f0c235" },
        { id: "coral", label: "salmon stock", paper: "#f4b79e" },
        { id: "cyan", label: "cyan stock", paper: "#79c4cc" },
      ],
    },
    css: playbillCss,
    render(ed, skin) {
      const wd = ed.weekday.toUpperCase();
      // Size the headliner against the bill's own inner measure: font-size in
      // cqi (relative to the frame's content box) so this weekday fills the
      // measure in this font and can never cross the frame at any width.
      const wordW = capWidth(wd) * skin.display.widthFactor;
      const coeff = (86 / wordW).toFixed(2);
      const daySize = `clamp(40px, ${coeff}cqi, 150px)`;
      const stats = ed.content.stats;

      const acts = ed.content.today
        .map((it) => {
          const timeLine = it.time ? `At ${esc(it.time)}` : "Before Nightfall";
          const shipCls = it.t24 ? "" : " pb-ship";
          const withNote = it.note ? ` &mdash; ${esc(it.note)}` : "";
          return `<div class="pb-act"><p class="pb-caps pb-time">${timeLine}</p><p class="pb-caps pb-head${shipCls}">${esc(
            it.tag,
          )}</p><p class="pb-ital pb-with">${esc(it.label)}${withNote}</p></div>`;
        })
        .join('<p class="pb-actsep">&mdash;&#9758;&mdash;</p>');

      const feats = ed.content.overnight
        .map(
          (it) =>
            `<p class="pb-caps pb-feat">${esc(it.label)}${
              it.note ? `<small>${esc(it.note)}</small>` : ""
            }</p>`,
        )
        .join("");

      const decisions = ed.content.decisions
        .map(
          (d) =>
            `<p class="pb-caps pb-decision"><span class="pb-hand">&#9758;</span> ${esc(
              d.verb,
            )} &mdash; ${esc(d.label)}${d.note ? `<small>${esc(d.note)}</small>` : ""}</p>`,
        )
        .join("");

      return `<article class="t-playbill" style="--paper:${skin.paper.paper}; --spot:${skin.spot.spot}; --face:${skin.display.face}; --day-size:${daySize}"><div class="pb-bill"><p class="pb-caps pb-spaced pb-presents">GAIA Presents &mdash; For One Day Only</p><hr class="pb-rule thin" /><h1 class="pb-caps pb-day">${wd}</h1><hr class="pb-rule spot" /><p class="pb-caps pb-spaced pb-datum">The ${ordinal(
        ed.day,
      )} of ${esc(ed.month)}, ${ed.year}</p><p class="pb-caps pb-spaced pb-datum pb-edition">Edition No. ${
        ed.editionNo
      }</p><hr class="pb-rule spot" /><p class="pb-ital pb-deck">&ldquo;${esc(
        ed.deck,
      )}&rdquo;</p><hr class="pb-rule double" /><p class="pb-caps pb-spaced pb-billing">This Day&rsquo;s Grand Programme</p><hr class="pb-rule thick" />${acts}<hr class="pb-rule thick" /><p class="pb-caps pb-spaced pb-banner">Performed While You Slept</p><hr class="pb-rule thin" />${feats}<hr class="pb-rule spot" /><p class="pb-caps pb-callhead">The Management Awaits Your Decision</p><hr class="pb-rule spot" />${decisions}<hr class="pb-rule double" /><p class="pb-figures"><span><span class="pb-n">${
        stats.done
      }</span> Done Yesterday</span><span class="pb-dot">&mdash;</span><span><span class="pb-n">${
        stats.mail
      }</span> Letters Handled</span><span class="pb-dot">&mdash;</span><span><span class="pb-n">${esc(
        stats.focus,
      )}</span> Held for Focus</span></p><hr class="pb-rule thick" /><p class="pb-imprint"><span class="pb-mark">&#9758; &nbsp; Edition No. ${
        ed.editionNo
      } &nbsp; &#9756;</span>Struck &amp; billed at ${esc(
        ed.time,
      )} by the House of GAIA.<br />Yesterday&rsquo;s labour: ${stats.you} by your hand, ${
        stats.gaia
      } by the House.</p></div></article>`;
    },
  });
})();
