/* ============================================================================
   tpl-print.js — "the print tradition"
   Two parametric templates for the Daily Brief edition explorer, ported from
   the approved hand-built designs (variant-memo / variant-broadsheet).
   Each source's identity is preserved; every skin-varying
   value is lifted into an inline CSS custom property consumed by static,
   .t-<id>-scoped CSS. Content comes from `ed`; only tradition-voiced headings
   are fixed copy. Pure/deterministic — no Date.now, no Math.random.
   ========================================================================== */

/* ---- shared helpers (local to this module) ---- */
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
// clock face without meridiem: "1:30 PM" -> "1:30"
function clock(t) {
  return t ? String(t).split(" ")[0] : "";
}
// "DONE" -> "Done"
function cap(s) {
  s = String(s || "");
  return s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : "";
}
// day ordinal: 3 -> "3rd"
function ord(n) {
  const v = n % 100;
  const suf = v >= 11 && v <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th";
  return n + suf;
}

/* ============================================================================
   1. THE MEMO — typewritten interoffice memo on paper laid over a desk.
      Axes: ground (paper/desk) × face (typewriter) × stamp (ink) × header wording
      3 × 2 × 3 × 2 = 36 combos.
   ========================================================================== */
EXPLORER.register({
  id: "memo",
  name: "The Memo",
  axes: {
    ground: [
      { id: "buff", label: "buff paper · slate desk",
        paper: "#f4f1e7", paperEdge: "#e9e5d8", desk: "#b9b6ae", deskDark: "#a7a49b",
        ink: "#2c2a26", inkSoft: "#55524b" },
      { id: "manila", label: "manila · walnut desk",
        paper: "#efe6cf", paperEdge: "#e3d8ba", desk: "#8a7a63", deskDark: "#77684f",
        ink: "#2b2519", inkSoft: "#584e3b" },
      { id: "onionskin", label: "onionskin · ink-blotter desk",
        paper: "#f7f6f1", paperEdge: "#ebe9e0", desk: "#5f6b6b", deskDark: "#515c5c",
        ink: "#26302f", inkSoft: "#4b5654" },
    ],
    face: [
      { id: "amtype", label: "American Typewriter",
        stack: '"American Typewriter","Courier New",Courier,monospace' },
      { id: "courier", label: "Courier",
        stack: '"Courier New",Courier,"American Typewriter",monospace' },
    ],
    stamp: [
      { id: "red", label: "faded red stamp", ink: "#a53728" },
      { id: "blue", label: "faded blue stamp", ink: "#3a5c86" },
      { id: "none", label: "no stamp", ink: null },
    ],
    header: [
      { id: "memorandum", label: "MEMORANDUM", word: "MEMORANDUM" },
      { id: "interoffice", label: "INTEROFFICE MEMO", word: "INTEROFFICE MEMO" },
    ],
  },
  css: `
    .t-memo {
      box-sizing: border-box;
      display: flex; justify-content: center; align-items: flex-start;
      width: 100%; margin: 0;
      padding: clamp(18px, 5vw, 64px) clamp(10px, 4vw, 56px);
      background-color: var(--desk);
      background-image: repeating-linear-gradient(90deg, transparent 0 3px, rgba(0,0,0,0.012) 3px 4px);
      font-family: var(--face);
      color: var(--ink);
      overflow: hidden;
      -webkit-font-smoothing: antialiased;
    }
    .t-memo * { box-sizing: border-box; }

    .t-memo__sheet {
      position: relative;
      width: 100%; max-width: 640px;
      background-color: var(--paper);
      border: 1px solid var(--paper-edge);
      padding: clamp(26px, 6vw, 52px) clamp(20px, 5vw, 46px) clamp(30px, 6vw, 50px) clamp(34px, 8vw, 62px);
      box-shadow:
        0 1px 0 rgba(255,255,255,0.35) inset,
        2px 3px 3px rgba(0,0,0,0.10),
        10px 16px 34px rgba(0,0,0,0.22);
      font-variant-numeric: tabular-nums;
    }

    .t-memo__hole {
      position: absolute;
      left: clamp(10px, 3vw, 20px);
      width: 13px; height: 13px; border-radius: 50%;
      background-color: var(--desk-dark);
      box-shadow: inset 1px 1px 2px rgba(0,0,0,0.45), inset -1px -1px 1px rgba(255,255,255,0.15);
    }
    .t-memo__hole--a { top: 24%; }
    .t-memo__hole--b { top: 62%; }

    .t-memo__stamp {
      position: absolute;
      top: clamp(14px, 4vw, 26px); right: clamp(12px, 4vw, 30px);
      transform: rotate(-6deg);
      padding: 5px 9px 4px;
      border: 2px solid var(--stamp);
      color: var(--stamp);
      font-size: 10px; line-height: 1.15; letter-spacing: 0.22em;
      text-align: center; opacity: 0.62; filter: blur(0.25px);
      text-transform: uppercase; max-width: 44%;
    }
    .t-memo__stamp b { font-weight: normal; display: block; letter-spacing: 0.3em; }

    .t-memo__title {
      margin: 0 0 clamp(18px, 4vw, 26px);
      font-weight: normal; font-size: clamp(16px, 4.4vw, 22px);
      letter-spacing: 0.42em; text-indent: 0.42em; text-align: center;
    }

    .t-memo__head {
      display: grid; grid-template-columns: auto 1fr;
      column-gap: clamp(12px, 3vw, 22px); row-gap: 3px;
      margin: 0 0 14px; font-size: clamp(12px, 3vw, 13px); line-height: 1.5;
    }
    .t-memo__head dt { margin: 0; letter-spacing: 0.06em; }
    .t-memo__head dd { margin: 0; color: var(--ink-soft); }

    .t-memo__rule {
      overflow: hidden; white-space: nowrap; color: var(--ink-soft);
      font-size: 13px; line-height: 1; margin: 6px 0 clamp(16px, 4vw, 22px); user-select: none;
    }

    .t-memo__deck {
      margin: 0 0 clamp(22px, 5vw, 30px);
      font-size: clamp(13px, 3.3vw, 15px); line-height: 1.75;
      white-space: pre-wrap; max-width: 60ch;
    }

    .t-memo__h {
      margin: clamp(22px, 5vw, 30px) 0 12px;
      font-size: clamp(12px, 3vw, 13px); font-weight: normal; letter-spacing: 0.14em;
    }
    .t-memo__h span { display: inline-block; border-bottom: 1px solid var(--ink); padding-bottom: 1px; }

    .t-memo__list { margin: 0; padding: 0; list-style: none; }
    .t-memo__item {
      display: grid; grid-template-columns: 1.8em 1fr; column-gap: 4px;
      margin: 0 0 9px; font-size: clamp(12px, 3.2vw, 15px); line-height: 1.7;
    }
    .t-memo__item .n { text-align: left; }
    .t-memo__item .t { white-space: pre-wrap; max-width: 62ch; }
    .t-memo__item .lead { letter-spacing: 0.08em; }

    .t-memo__tally {
      margin: clamp(20px, 5vw, 28px) 0 clamp(20px, 5vw, 26px); padding: 0;
      overflow-x: auto; font-size: clamp(11px, 2.9vw, 13px); line-height: 1.85;
      color: var(--ink); font-variant-numeric: tabular-nums;
      font-family: var(--face); white-space: pre;
    }

    .t-memo__end {
      margin: clamp(18px, 4vw, 24px) 0 10px; text-align: center;
      letter-spacing: 0.3em; text-indent: 0.3em; font-size: 14px; color: var(--ink-soft);
    }
    .t-memo__colophon {
      margin: 0; text-align: center; font-size: 10px; letter-spacing: 0.08em;
      color: var(--ink-soft); line-height: 1.6;
    }
  `,
  render(ed, skin) {
    const g = skin.ground, c = ed.content;
    const style =
      `--paper:${g.paper};--paper-edge:${g.paperEdge};--desk:${g.desk};--desk-dark:${g.deskDark};` +
      `--ink:${g.ink};--ink-soft:${g.inkSoft};--face:${skin.face.stack};` +
      (skin.stamp.ink ? `--stamp:${skin.stamp.ink};` : "");

    const stampEl = skin.stamp.ink
      ? `<div class="t-memo__stamp" aria-label="Received ${esc(ed.time)}">Received<b>${esc(ed.time)}</b></div>`
      : "";

    // numbered typewriter list; typewriter tradition uses "--" not em dash
    const list = (items, leadFn) =>
      `<ol class="t-memo__list">${items.map((it, i) => {
        const t = leadFn(it);
        return `<li class="t-memo__item"><span class="n">${i + 1}.</span><span class="t">${t}</span></li>`;
      }).join("")}</ol>`;

    const todayLine = (it) => {
      const head = it.time ? `${esc(it.time)} -- ` : "";
      const note = it.note ? `  ${esc(it.note)}.` : "";
      return `${head}${esc(it.label)}.${note}`;
    };
    const nightLine = (it) => {
      const note = it.note ? `  ${esc(it.note)}.` : "";
      return `${esc(it.label)}.${note}`;
    };
    const callLine = (it) => {
      const note = it.note ? ` -- ${esc(it.note)}` : "";
      return `<span class="lead">${esc(it.verb.toUpperCase())}:</span>  ${esc(it.label)}${note}.`;
    };

    const s = c.stats;
    const tally =
      `DONE YESTERDAY  . . . . . .  ${s.done}   (YOU ${s.you}, GAIA ${s.gaia})\n` +
      `EMAILS HANDLED  . . . . . .  ${s.mail}\n` +
      `FOCUS TIME TODAY  . . . . .  ${esc(s.focus)}`;

    return `<article class="t-memo" style="${style}">
      <div class="t-memo__sheet">
        <span class="t-memo__hole t-memo__hole--a" aria-hidden="true"></span>
        <span class="t-memo__hole t-memo__hole--b" aria-hidden="true"></span>
        ${stampEl}
        <h2 class="t-memo__title">${esc(skin.header.word)}</h2>
        <dl class="t-memo__head">
          <dt>TO:</dt><dd>You</dd>
          <dt>FROM:</dt><dd>GAIA</dd>
          <dt>DATE:</dt><dd>${esc(ed.dateLong)}</dd>
          <dt>RE:</dt><dd>Your ${esc(ed.weekday)} -- Edition No. ${ed.editionNo}</dd>
        </dl>
        <div class="t-memo__rule" aria-hidden="true">----------------------------------------------------------------------------------------------------</div>
        <p class="t-memo__deck">${esc(ed.deck)}</p>

        <h3 class="t-memo__h"><span>WHAT MATTERS TODAY</span></h3>
        ${list(c.today, todayLine)}

        <h3 class="t-memo__h"><span>WHILE YOU SLEPT</span></h3>
        ${list(c.overnight, nightLine)}

        <h3 class="t-memo__h"><span>NEEDS YOUR CALL</span></h3>
        ${list(c.decisions, callLine)}

        <h3 class="t-memo__h"><span>BY THE NUMBERS</span></h3>
        <pre class="t-memo__tally">${tally}</pre>

        <p class="t-memo__end">###</p>
        <p class="t-memo__colophon">EDITION NO. ${ed.editionNo} -- GENERATED ${esc(ed.time)} BY GAIA</p>
      </div>
    </article>`;
  },
});

/* ============================================================================
   2. THE BROADSHEET — 1900s front page on aged newsprint: masthead + ears,
      dominant lead well with a drop-cap lead paragraph + a ruled subordinate
      rail; the engraved plate is present in every edition, its screen the
      variable axis. Grounds are light paper stocks only — newsprint is paper.
      Axes: masthead face × newsprint stock × plate treatment
      3 × 3 × 2 = 18 combos.
   ========================================================================== */
EXPLORER.register({
  id: "broadsheet",
  name: "The Broadsheet",
  axes: {
    masthead: [
      { id: "didot", label: "Didot", stack: '"Didot","Bodoni 72","Hoefler Text",Georgia,serif' },
      { id: "bodoni", label: "Bodoni 72", stack: '"Bodoni 72","Didot","Hoefler Text",Georgia,serif' },
      { id: "hoefler", label: "Hoefler Text", stack: '"Hoefler Text","Iowan Old Style",Georgia,serif' },
    ],
    tone: [
      { id: "cool", label: "cool grey stock",
        paper: "#e4e1d6", ink: "#191916", inkSoft: "#3b3a32", rule: "#20201a", hair: "rgba(32,32,26,0.42)" },
      { id: "neutral", label: "aged neutral stock",
        paper: "#e7e0cf", ink: "#1a1712", inkSoft: "#3c352b", rule: "#241f18", hair: "rgba(36,31,24,0.42)" },
      { id: "warm", label: "warm foxed stock",
        paper: "#ece2c8", ink: "#211b10", inkSoft: "#463c25", rule: "#2a2213", hair: "rgba(42,34,19,0.42)" },
    ],
    plate: [
      { id: "halftone", label: "halftone screen", treat: "halftone" },
      { id: "duotone", label: "warm duotone", treat: "duotone" },
    ],
  },
  css: `
    .t-broadsheet {
      background-color: var(--paper);
      color: var(--ink);
      font-family: "Iowan Old Style","Hoefler Text",Georgia,"Times New Roman",serif;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
      padding: clamp(22px, 4vw, 56px);
      box-sizing: border-box; width: 100%; overflow-x: hidden;
    }
    .t-broadsheet * { box-sizing: border-box; }
    .t-broadsheet-sheet { max-width: 1180px; margin: 0 auto; }

    .t-broadsheet-earrow { display: grid; grid-template-columns: 1fr auto 1fr; align-items: end; gap: 8px; margin-bottom: 10px; }
    .t-broadsheet-ear {
      font-family: "Baskerville","Hoefler Text",Georgia,serif;
      font-size: clamp(9px, 1.05vw, 11px); line-height: 1.3; letter-spacing: 0.06em;
      text-transform: uppercase; color: var(--ink-soft);
    }
    .t-broadsheet-ear--l { text-align: left; }
    .t-broadsheet-ear--r { text-align: right; }
    .t-broadsheet-ear em { font-style: italic; text-transform: none; letter-spacing: 0; display: block; }

    .t-broadsheet-masthead {
      font-family: var(--display); font-weight: 700; text-align: center;
      line-height: 0.9; letter-spacing: -0.01em; font-size: clamp(34px, 9.4vw, 112px);
      margin: 6px 0 0; padding-bottom: 0.05em; white-space: nowrap;
    }
    .t-broadsheet-the {
      display: block; font-size: 0.26em; font-weight: 400; letter-spacing: 0.42em;
      text-indent: 0.42em; text-transform: uppercase; margin-bottom: 0.16em;
      font-family: "Baskerville","Hoefler Text",Georgia,serif;
    }
    .t-broadsheet-doubrule {
      border: 0; border-top: 3px solid var(--rule); border-bottom: 1px solid var(--rule);
      height: 3px; margin: clamp(22px, 2.6vw, 34px) 0 0;
    }
    .t-broadsheet-dateline {
      display: flex; flex-wrap: wrap; justify-content: center; align-items: baseline; gap: 0.55em;
      font-family: "Baskerville","Hoefler Text",Georgia,serif;
      font-size: clamp(8.5px, 1.02vw, 11px); letter-spacing: 0.16em; text-transform: uppercase;
      color: var(--ink-soft); padding: 10px 0 11px; border-bottom: 3px double var(--rule);
    }
    .t-broadsheet-dot { opacity: 0.55; }

    .t-broadsheet-front { display: grid; grid-template-columns: minmax(0, 1.62fr) minmax(0, 1fr); gap: 0; padding-top: 30px; max-width: 1000px; margin: 0 auto; }
    .t-broadsheet-well { padding-right: 40px; min-width: 0; }
    .t-broadsheet-rail { border-left: 1px solid var(--rule); padding-left: 40px; min-width: 0; }

    .t-broadsheet-kicker {
      font-family: "Baskerville","Hoefler Text",Georgia,serif;
      letter-spacing: 0.22em; text-transform: uppercase; text-align: center; color: var(--ink-soft);
      font-size: 10px; padding-bottom: 5px; margin-bottom: 11px; border-bottom: 1px solid var(--rule);
    }
    .t-broadsheet-head {
      font-family: var(--display); font-weight: 700; text-transform: uppercase; text-align: center;
      line-height: 0.96; letter-spacing: 0.004em; margin: 0;
    }
    .t-broadsheet-head--lead { font-size: clamp(30px, 5vw, 62px); line-height: 0.92; }
    .t-broadsheet-head--sec  { font-size: clamp(16px, 1.6vw, 19px); letter-spacing: 0.02em; }
    .t-broadsheet-deck {
      font-family: "Baskerville","Hoefler Text",Georgia,serif; font-style: italic; font-weight: 400;
      text-align: center; letter-spacing: 0; line-height: 1.34; margin: 9px auto 0; color: var(--ink-soft);
    }
    .t-broadsheet-deck--lead { font-size: clamp(14px, 1.5vw, 17px); max-width: 42ch; }
    .t-broadsheet-hr-lead { border: 0; border-top: 1px solid var(--rule); margin: 16px auto 20px; width: 34%; }
    .t-broadsheet-hr-sec  { border: 0; border-top: 1px solid var(--rule); margin: 9px auto 13px; width: 46%; }

    .t-broadsheet-plate { margin: 4px 0 22px; }
    .t-broadsheet-platebox { position: relative; }
    .t-broadsheet-plate img {
      display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: cover; object-position: 50% 44%;
      border: 1px solid var(--rule);
    }
    .t-broadsheet-plate--halftone img {
      filter: grayscale(1) contrast(1.16) brightness(0.98);
      -webkit-filter: grayscale(1) contrast(1.16) brightness(0.98);
    }
    .t-broadsheet-plate--duotone img {
      filter: grayscale(1) sepia(0.62) saturate(1.6) contrast(1.05) brightness(1.02);
      -webkit-filter: grayscale(1) sepia(0.62) saturate(1.6) contrast(1.05) brightness(1.02);
    }
    .t-broadsheet-screen { position: absolute; inset: 0; pointer-events: none; }
    .t-broadsheet-plate--halftone .t-broadsheet-screen {
      background-image: radial-gradient(circle, rgba(0,0,0,0.65) 22%, transparent 27%);
      background-size: 3px 3px; mix-blend-mode: multiply; opacity: 0.3;
    }
    .t-broadsheet-cap {
      font-family: "Baskerville","Hoefler Text",Georgia,serif; font-size: 10.5px; line-height: 1.28;
      color: var(--ink-soft); text-align: center; margin-top: 9px;
    }
    .t-broadsheet-cap em { font-style: italic; }
    .t-broadsheet-credit {
      display: block; font-style: normal; text-transform: uppercase; letter-spacing: 0.08em;
      font-size: 8.5px; margin-top: 2px;
    }

    .t-broadsheet-leadbody { text-align: justify; hyphens: auto; -webkit-hyphens: auto; }
    .t-broadsheet-railtext { text-align: justify; hyphens: auto; -webkit-hyphens: auto; }

    .t-broadsheet-p { font-size: 15px; line-height: 1.6; margin: 0 0 11px; }
    .t-broadsheet-p:last-child { margin-bottom: 0; }
    .t-broadsheet-p--drop::first-letter {
      font-family: var(--display); font-weight: 700; float: left;
      font-size: 3.1em; line-height: 0.72; padding: 0.06em 0.09em 0 0;
    }
    .t-broadsheet-item { font-size: 15px; line-height: 1.6; margin: 0 0 10px; }
    .t-broadsheet-item:last-child { margin-bottom: 0; }
    .t-broadsheet-cue { font-variant-caps: small-caps; font-weight: 700; letter-spacing: 0.03em; }

    .t-broadsheet-railstory + .t-broadsheet-railstory { margin-top: 24px; }

    .t-broadsheet-figs { border: 1px solid var(--rule); border-top-width: 2px; padding: 7px 9px 8px; margin-top: 24px; }
    .t-broadsheet-figs-h {
      font-family: "Baskerville","Hoefler Text",Georgia,serif; font-size: 9.5px; letter-spacing: 0.2em;
      text-transform: uppercase; text-align: center; padding-bottom: 5px; margin-bottom: 5px;
      border-bottom: 1px solid var(--rule);
    }
    .t-broadsheet-figs table { width: 100%; border-collapse: collapse; font-size: 12px; }
    .t-broadsheet-figs td { padding: 2.5px 0; border-bottom: 1px dotted var(--hair); vertical-align: baseline; }
    .t-broadsheet-figs tr:last-child td { border-bottom: 0; }
    .t-broadsheet-lab { font-variant-caps: small-caps; letter-spacing: 0.02em; }
    .t-broadsheet-num { text-align: right; font-variant-numeric: tabular-nums; font-weight: 700; white-space: nowrap; padding-left: 8px; }
    .t-broadsheet-sub { font-size: 10px; color: var(--ink-soft); font-variant-caps: normal; }

    .t-broadsheet-imprint {
      margin-top: 30px; padding-top: 12px; border-top: 3px double var(--rule); text-align: center;
      font-family: "Baskerville","Hoefler Text",Georgia,serif; font-size: 9.5px; letter-spacing: 0.16em;
      text-transform: uppercase; color: var(--ink-soft); font-variant-numeric: tabular-nums;
    }

    @media (max-width: 820px) {
      .t-broadsheet-front { grid-template-columns: 1fr; }
      .t-broadsheet-well { padding-right: 0; }
      .t-broadsheet-rail { border-left: 0; padding-left: 0; margin-top: 18px; padding-top: 16px; border-top: 3px double var(--rule); }
    }
    @media (max-width: 520px) {
      .t-broadsheet-plate img { aspect-ratio: 3 / 2; }
    }
  `,
  render(ed, skin) {
    const c = ed.content, a = ed.art, s = c.stats;
    const style =
      `--display:${skin.masthead.stack};--paper:${skin.tone.paper};--ink:${skin.tone.ink};` +
      `--ink-soft:${skin.tone.inkSoft};--rule:${skin.tone.rule};--hair:${skin.tone.hair};`;

    const t0 = c.today[0];
    const dropPara =
      `<p class="t-broadsheet-p t-broadsheet-p--drop">${esc(t0.label)}` +
      `${t0.time ? `, at ${esc(t0.time)}` : ""}.` +
      `${t0.note ? ` ${esc(cap(t0.note))}.` : ""}</p>`;

    const restToday = c.today.slice(1).map((it) => {
      const lead = it.time
        ? `<span class="t-broadsheet-time">${esc(it.time)}</span>`
        : `<span class="t-broadsheet-cue">Before Nightfall</span>`;
      const note = it.note ? ` ${esc(cap(it.note))}.` : "";
      return `<p class="t-broadsheet-item">${lead} — ${esc(it.label)}.${note}</p>`;
    }).join("");

    const plateFig = skin.plate.show
      ? `<figure class="t-broadsheet-plate">
           <img src="${a.src}" alt="${esc(a.title)}, ${esc(a.artist)}, ${a.year}, ${esc(a.medium)}">
           <figcaption class="t-broadsheet-cap"><em>${esc(a.title)}</em> — engraved for this edition after the ${esc(a.medium)}.
             <span class="t-broadsheet-credit">${esc(a.artist)}, ${a.year} · The Met · Public Domain</span>
           </figcaption>
         </figure>`
      : "";

    const railItems = (items, cueFn) =>
      items.map((it) => {
        const note = it.note ? ` ${esc(cap(it.note))}.` : "";
        return `<p class="t-broadsheet-item"><span class="t-broadsheet-cue">${esc(cueFn(it))}</span> — ${esc(it.label)}.${note}</p>`;
      }).join("");

    return `<article class="t-broadsheet" style="${style}">
      <div class="t-broadsheet-sheet">
        <div class="t-broadsheet-earrow">
          <div class="t-broadsheet-ear t-broadsheet-ear--l">Edition No. ${ed.editionNo}<em>Compiled by GAIA</em></div>
          <div class="t-broadsheet-ear" aria-hidden="true">&nbsp;</div>
          <div class="t-broadsheet-ear t-broadsheet-ear--r">Price · Your Attention<em>Generated ${esc(ed.time)}</em></div>
        </div>
        <h1 class="t-broadsheet-masthead"><span class="t-broadsheet-the">The</span>${esc(ed.weekday)} Brief</h1>
        <hr class="t-broadsheet-doubrule" />
        <div class="t-broadsheet-dateline">
          <span>Vol. I</span><span class="t-broadsheet-dot">·</span>
          <span>${esc(ed.weekday)}, ${esc(ed.month)} ${ed.day}, ${ed.year}</span><span class="t-broadsheet-dot">·</span>
          <span>One Edition Daily</span>
        </div>

        <div class="t-broadsheet-front">
          <div class="t-broadsheet-well">
            <div class="t-broadsheet-kicker">The Day Ahead · Lead Story</div>
            <h2 class="t-broadsheet-head t-broadsheet-head--lead">What Matters Today</h2>
            <p class="t-broadsheet-deck t-broadsheet-deck--lead">${esc(ed.deck)}</p>
            <hr class="t-broadsheet-hr-lead" />
            ${plateFig}
            <div class="t-broadsheet-leadbody">
              ${dropPara}
              ${restToday}
            </div>
          </div>

          <div class="t-broadsheet-rail">
            <div class="t-broadsheet-railstory">
              <div class="t-broadsheet-kicker">Filed Overnight</div>
              <h3 class="t-broadsheet-head t-broadsheet-head--sec">While You Slept</h3>
              <hr class="t-broadsheet-hr-sec" />
              <div class="t-broadsheet-railtext">${railItems(c.overnight, (it) => cap(it.tag))}</div>
            </div>

            <div class="t-broadsheet-railstory">
              <div class="t-broadsheet-kicker">Awaiting the Editor</div>
              <h3 class="t-broadsheet-head t-broadsheet-head--sec">Needs Your Call</h3>
              <hr class="t-broadsheet-hr-sec" />
              <div class="t-broadsheet-railtext">${railItems(c.decisions, (it) => it.verb)}</div>
            </div>

            <div class="t-broadsheet-figs">
              <div class="t-broadsheet-figs-h">The Day's Figures</div>
              <table>
                <tr><td class="t-broadsheet-lab">Done Yesterday <span class="t-broadsheet-sub">(you ${s.you} · gaia ${s.gaia})</span></td><td class="t-broadsheet-num">${s.done}</td></tr>
                <tr><td class="t-broadsheet-lab">Emails Handled</td><td class="t-broadsheet-num">${s.mail}</td></tr>
                <tr><td class="t-broadsheet-lab">Focus Time Today</td><td class="t-broadsheet-num">${esc(s.focus)}</td></tr>
              </table>
            </div>
          </div>
        </div>

        <div class="t-broadsheet-imprint">Edition No. ${ed.editionNo} · Generated ${esc(ed.time)} by GAIA · Printed for a Readership of One</div>
      </div>
    </article>`;
  },
});

/* ============================================================================
   3. THE ALMANAC — readable farmer's almanac: centered title stack, a row of
      calculations, pilcrow items under small-caps section heads, framed Plate I.
      Axes: face × paper × plate × ornament
      3 × 3 × 2 × 2 = 36 combos.
   ========================================================================== */
EXPLORER.register({
  id: "almanac",
  name: "The Almanac",
  axes: {
    face: [
      { id: "baskerville", label: "Baskerville", stack: 'Baskerville,"Hoefler Text",Georgia,serif' },
      { id: "hoefler", label: "Hoefler Text", stack: '"Hoefler Text",Baskerville,Georgia,serif' },
      { id: "iowan", label: "Iowan Old Style", stack: '"Iowan Old Style","Hoefler Text",Georgia,serif' },
    ],
    paper: [
      { id: "linen", label: "pale linen",
        paper: "#ece6d6", paperLit: "#f4efe1", paperDark: "#ddd5bf", ink: "#20201a", inkSoft: "#4a473b" },
      { id: "oat", label: "warm oat",
        paper: "#e9e1cd", paperLit: "#f1ead9", paperDark: "#dcd2b7", ink: "#1f1c16", inkSoft: "#4a4234" },
      { id: "tallow", label: "aged tallow",
        paper: "#e7dcbf", paperLit: "#efe6cd", paperDark: "#d7c8a1", ink: "#241d10", inkSoft: "#4f4329" },
    ],
    plate: [
      { id: "framed", label: "framed plate", show: true },
      { id: "none", label: "no plate", show: false },
    ],
    ornament: [
      { id: "asterism", label: "asterism ornament", asterism: true },
      { id: "rules", label: "short rules only", asterism: false },
    ],
  },
  css: `
    .t-almanac {
      background-color: var(--paper);
      background-image: radial-gradient(125% 90% at 50% 40%, var(--paper-lit) 0%, var(--paper) 60%, var(--paper-dark) 100%);
      color: var(--ink);
      font-family: var(--face);
      -webkit-font-smoothing: antialiased;
      display: flex; justify-content: center;
      padding: clamp(2rem, 6vw, 5rem) clamp(1.15rem, 5vw, 3rem);
      box-sizing: border-box; width: 100%;
    }
    .t-almanac * { box-sizing: border-box; }
    .t-almanac .sheet { width: 100%; max-width: 39rem; text-align: center; }

    .t-almanac .kicker { font-variant: small-caps; letter-spacing: 0.34em; font-size: 0.7rem; margin: 0 0 1.5rem; color: var(--ink-soft); }
    .t-almanac .title { font-variant: small-caps; letter-spacing: 0.05em; font-weight: 400; line-height: 1.02; font-size: clamp(2.5rem, 9vw, 3.8rem); margin: 0; }
    .t-almanac .being { font-style: italic; font-size: clamp(1.05rem, 3.4vw, 1.28rem); margin: 1rem auto 0; max-width: 32ch; line-height: 1.42; }
    .t-almanac .imprintdate { font-variant: small-caps; letter-spacing: 0.16em; font-size: 0.92rem; margin: 1.1rem 0 0; color: var(--ink-soft); }

    .t-almanac .rule-short { border: 0; border-top: 1px solid var(--ink); width: 4rem; margin: 1.5rem auto; opacity: 0.7; }
    .t-almanac .orn-rule  { border: 0; border-top: 1px solid var(--ink); width: 2.5rem; margin: 1.6rem auto; opacity: 0.6; }
    .t-almanac .ornament { font-size: 1.25rem; letter-spacing: 0.3em; line-height: 1; margin: 1.6rem 0; }

    .t-almanac .deck { font-style: italic; font-size: clamp(1.15rem, 3.8vw, 1.42rem); line-height: 1.5; max-width: 30ch; margin: 0 auto; }

    .t-almanac .calc { margin: 2.4rem auto 0; border-top: 2px solid var(--ink); border-bottom: 2px solid var(--ink); padding: 0.9rem 0.5rem; max-width: 34rem; }
    .t-almanac .calc-head { font-variant: small-caps; letter-spacing: 0.26em; font-size: 0.66rem; color: var(--ink-soft); margin: 0 0 0.8rem; }
    .t-almanac .calc-grid { display: flex; flex-wrap: wrap; justify-content: center; gap: 0.9rem 2rem; }
    .t-almanac .calc-cell { display: flex; flex-direction: column; align-items: center; gap: 0.22rem; min-width: 6rem; }
    .t-almanac .calc-cell .lbl { font-variant: small-caps; letter-spacing: 0.12em; font-size: 0.68rem; color: var(--ink-soft); }
    .t-almanac .calc-cell .fig { font-variant-numeric: tabular-nums; font-size: clamp(1.3rem, 4.5vw, 1.65rem); line-height: 1; }

    .t-almanac .section { margin-top: 2.9rem; text-align: left; }
    .t-almanac .sec-head { font-variant: small-caps; letter-spacing: 0.28em; font-size: 0.82rem; font-weight: 400; color: var(--ink-soft); text-align: center; margin: 0 0 0.35rem; }
    .t-almanac .rule-thin { border: 0; border-top: 1px solid var(--ink); width: 100%; max-width: 30rem; margin: 0 auto 1.25rem; opacity: 0.55; }
    .t-almanac .items { list-style: none; margin: 0 auto; padding: 0; max-width: 60ch; }
    .t-almanac .items li { position: relative; padding-left: 1.5rem; margin: 0 0 1rem; font-size: clamp(1.08rem, 3vw, 1.15rem); line-height: 1.6; hyphens: auto; -webkit-hyphens: auto; }
    .t-almanac .items li:last-child { margin-bottom: 0; }
    .t-almanac .items li .pil { position: absolute; left: 0; top: 0; font-size: 1.1em; color: var(--ink-soft); }
    .t-almanac .items li .num { font-variant-numeric: tabular-nums; font-style: italic; }

    .t-almanac .plate { margin: 3rem auto 0; max-width: 19rem; text-align: center; }
    .t-almanac .plate-frame { border: 1px solid var(--ink); padding: 5px; }
    .t-almanac .plate-frame-inner { border: 1px solid var(--ink); padding: 4px; }
    .t-almanac .plate img { display: block; width: 100%; aspect-ratio: 4 / 3.18; object-fit: cover; filter: grayscale(1) contrast(1.06) brightness(0.98) sepia(0.12); }
    .t-almanac .plate-cap { font-variant: small-caps; letter-spacing: 0.15em; font-size: 0.76rem; margin: 0.8rem 0 0.2rem; }
    .t-almanac .plate-credit { font-variant: small-caps; letter-spacing: 0.1em; font-size: 0.66rem; color: var(--ink-soft); margin: 0; line-height: 1.45; }

    .t-almanac .colophon { margin: 3rem auto 0; max-width: 34ch; text-align: center; }
    .t-almanac .colophon .ornament { margin: 0 0 1.1rem; font-size: 1rem; }
    .t-almanac .colophon .orn-rule { margin: 0 auto 1.1rem; }
    .t-almanac .imprint { font-variant: small-caps; letter-spacing: 0.15em; font-size: 0.68rem; line-height: 1.75; color: var(--ink-soft); margin: 0; }
  `,
  render(ed, skin) {
    const c = ed.content, a = ed.art, s = c.stats;
    const style =
      `--face:${skin.face.stack};--paper:${skin.paper.paper};--paper-lit:${skin.paper.paperLit};` +
      `--paper-dark:${skin.paper.paperDark};--ink:${skin.paper.ink};--ink-soft:${skin.paper.inkSoft};`;

    // asterism U+2042 vs a short centered rule — the sole ornament axis
    const orn = skin.ornament.asterism
      ? `<p class="ornament">⁂</p>`
      : `<hr class="orn-rule" />`;

    const t0 = clock(c.today[0].time), t1 = clock(c.today[1].time);
    const calcCells = [
      { fig: t0 || "—", lbl: "First Engagement" },
      { fig: t1 || "—", lbl: "Second Engagement" },
      { fig: esc(s.focus), lbl: "Focus Hours" },
      { fig: String(s.mail), lbl: "Letters Handled" },
    ].map((x) => `<div class="calc-cell"><span class="fig">${x.fig}</span><span class="lbl">${x.lbl}</span></div>`).join("");

    // pilcrow item; optional leading clock rendered as an italic numeral
    const pil = `<span class="pil">¶</span>`;
    const item = (lead, body) =>
      `<li>${pil}${lead ? `<span class="num">${esc(lead)}</span> — ` : ""}${body}</li>`;

    const todayItems = c.today.map((it) => {
      const note = it.note ? ` ${esc(cap(it.note))}.` : "";
      return item(clock(it.time), `${esc(it.label)}.${note}`);
    }).join("");

    const nightItems = c.overnight.map((it) => {
      const note = it.note ? ` ${esc(cap(it.note))}.` : "";
      return item("", `${esc(it.label)}.${note}`);
    }).join("");

    const callItems = c.decisions.map((it) => {
      const note = it.note ? ` ${esc(cap(it.note))}.` : "";
      return item("", `To ${esc(it.verb.toLowerCase())} — ${esc(it.label)}.${note}`);
    }).join("");

    const plate = skin.plate.show
      ? `<div class="plate">
           <div class="plate-frame"><div class="plate-frame-inner">
             <img src="${a.src}" alt="${esc(a.title)}, ${esc(a.artist)}, ${a.year}, ${esc(a.medium)}">
           </div></div>
           <p class="plate-cap">Plate I. — ${esc(a.title)}</p>
           <p class="plate-credit">${esc(a.artist)}, ${a.year}, ${esc(a.medium)} — The Met, public domain</p>
         </div>`
      : "";

    return `<article class="t-almanac" style="${style}">
      <div class="sheet">
        <p class="kicker">The Almanac</p>
        <h1 class="title">The ${esc(ed.weekday)} Brief</h1>
        <p class="being">Being a Faithful Account of the Day's Business</p>
        <p class="imprintdate">for the ${esc(ord(ed.day))} Day of ${esc(ed.month)}, Anno ${ed.year} — No. ${ed.editionNo}</p>

        <hr class="rule-short" />
        ${orn}

        <p class="deck">${esc(ed.deck)}</p>

        <div class="calc">
          <p class="calc-head">Calculations for the Day</p>
          <div class="calc-grid">${calcCells}</div>
        </div>

        <div class="section">
          <h2 class="sec-head">What Matters To-day</h2>
          <hr class="rule-thin" />
          <ul class="items">${todayItems}</ul>
        </div>

        <div class="section">
          <h2 class="sec-head">Work Performed in the Night</h2>
          <hr class="rule-thin" />
          <ul class="items">${nightItems}</ul>
        </div>

        <div class="section">
          <h2 class="sec-head">Needs Your Call</h2>
          <hr class="rule-thin" />
          <ul class="items">${callItems}</ul>
        </div>

        ${plate}

        <div class="colophon">
          ${orn}
          <p class="imprint">
            Reckoning of the day — ${s.done} tasks accomplished, whereof ${s.you} by your own hand and ${s.gaia} by the machine.<br />
            Printed at ${esc(ed.time)} by GAIA — Edition No. ${ed.editionNo}.
          </p>
        </div>
      </div>
    </article>`;
  },
});
