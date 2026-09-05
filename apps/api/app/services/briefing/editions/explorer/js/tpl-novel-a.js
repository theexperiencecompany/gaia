/* ============================================================================
 * tpl-novel-a.js — the "ticket" template for the daily-brief explorer.
 *
 *   boardingpass — an airline boarding pass + tear-off stub on a flat desk.
 *
 * Lives in one IIFE so local helpers never collide with sibling modules.
 * Skin values arrive ONLY as inline CSS custom properties on the <article>;
 * every selector is scoped to .t-boardingpass. Deterministic: no Date.now /
 * Math.random. Content is generated from ed fields.
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
  function pad2(n) {
    return String(n).padStart(2, "0");
  }
  function pad3(n) {
    return String(n).padStart(3, "0");
  }

  /* ==========================================================================
   * TEMPLATE 1 — metromap
   * The day drawn as a three-line transit map. The YOU line (your meetings and
   * the ship) is the bright trunk; the GAIA line (overnight work) runs dim below
   * it — those trains already ran; the DECISIONS line is a dashed spur of two
   * hollow "proposed" stations. Where GAIA's draft awaits your review, the two
   * lines meet at a double-ring interchange. Beck grammar: 0/45/90° only,
   * paper-filled station shapes with line-coloured strokes, bold-caps terminus
   * boxes. Everything lives in one SVG viewBox so text can never overflow — the
   * whole diagram simply scales with the canvas.
   * ==========================================================================*/
  const METROMAP_CSS = `
    .t-metromap {
      min-height: 1240px;
      width: 100%;
      margin: 0;
      padding: 64px clamp(22px,4vw,72px) 68px;
      box-sizing: border-box;
      background: var(--paper);
      color: var(--ink);
      font-family: "Helvetica Neue", Helvetica, Arial, system-ui, sans-serif;
      -webkit-font-smoothing: antialiased;
    }
    .t-metromap * { box-sizing: border-box; }

    .t-metromap__mast { display: flex; align-items: center; gap: 22px; flex-wrap: wrap; }
    .t-metromap__roundel { flex: 0 0 auto; display: block; }
    .t-metromap__titles { min-width: 0; }
    .t-metromap__eyebrow {
      font-size: 12px; letter-spacing: 0.34em; text-transform: uppercase;
      color: var(--ink-soft); margin: 0 0 7px; font-weight: 700;
    }
    .t-metromap__title {
      font-family: "Aeonik Extended", "Helvetica Neue", sans-serif;
      font-weight: 700; font-size: clamp(30px,4.6vw,52px); line-height: 0.98;
      margin: 0; letter-spacing: -0.012em;
    }
    .t-metromap__sub {
      font-size: clamp(13px,1.5vw,16px); letter-spacing: 0.01em;
      color: var(--ink-soft); margin: 9px 0 0; font-variant-numeric: tabular-nums;
    }
    .t-metromap__rule { height: 3px; background: var(--accent); border: 0; margin: 20px 0 4px; }

    .t-metromap__map { display: block; width: 100%; height: auto; overflow: visible; }

    .t-metromap__notice {
      display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 16px;
      margin: 10px 0 0; padding: 15px 20px; background: var(--notice-bg);
      border-left: 5px solid var(--accent);
    }
    .t-metromap__notice-tag {
      font-size: 12px; letter-spacing: 0.26em; text-transform: uppercase;
      color: var(--accent); font-weight: 700; white-space: nowrap;
    }
    .t-metromap__notice-body {
      font-size: clamp(14px,1.7vw,18px); line-height: 1.5; color: var(--ink); min-width: 0;
    }

    /* --- svg lines --- */
    .t-metromap .mm-you-line {
      fill: none; stroke: var(--you); stroke-width: 14;
      stroke-linejoin: round; stroke-linecap: round;
    }
    .t-metromap .mm-gaia-line {
      fill: none; stroke: var(--gaia); stroke-width: 14;
      stroke-linejoin: round; stroke-linecap: round; opacity: 0.55;
    }
    .t-metromap .mm-dec-line {
      fill: none; stroke: var(--accent); stroke-width: 11;
      stroke-linejoin: round; stroke-linecap: butt; stroke-dasharray: 18 13;
    }

    /* --- terminus caps + name boxes --- */
    .t-metromap .mm-conn { stroke-width: 6; }
    .t-metromap .mm-conn.you { stroke: var(--you); }
    .t-metromap .mm-conn.gaia { stroke: var(--gaia); opacity: 0.55; }
    .t-metromap .mm-cap { stroke: var(--paper); stroke-width: 3; }
    .t-metromap .mm-cap.you { fill: var(--you); }
    .t-metromap .mm-cap.gaia { fill: var(--gaia); }
    .t-metromap .mm-box { fill: var(--paper); stroke-width: 3; }
    .t-metromap .mm-box.you { stroke: var(--you); }
    .t-metromap .mm-box.gaia { stroke: var(--gaia); }
    .t-metromap .mm-boxname {
      fill: var(--ink); font-weight: 700; font-size: 20px; letter-spacing: 0.045em;
      text-anchor: middle; text-transform: uppercase;
    }
    .t-metromap .mm-time {
      fill: var(--ink-soft); font-size: 17px; font-weight: 700; text-anchor: middle;
      font-variant-numeric: tabular-nums; letter-spacing: 0.02em;
    }

    /* --- ordinary stops --- */
    .t-metromap .mm-tick { stroke: var(--ink); stroke-width: 5; }
    .t-metromap .mm-name { fill: var(--ink); font-size: 19px; font-weight: 600; text-anchor: middle; }
    .t-metromap .mm-note { fill: var(--ink-soft); font-size: 15.5px; text-anchor: middle; }

    /* --- interchange + hollow decision stations --- */
    .t-metromap .mm-ring { fill: var(--paper); stroke: var(--ink); stroke-width: 5; }
    .t-metromap .mm-tie { stroke: var(--ink); stroke-width: 9; }
    .t-metromap .mm-hollow { fill: var(--paper); stroke: var(--accent); stroke-width: 5; }
    .t-metromap .mm-decv {
      fill: var(--accent); font-size: 16px; font-weight: 700; text-anchor: middle;
      text-transform: uppercase; letter-spacing: 0.06em;
    }
    .t-metromap .mm-ixtime {
      fill: var(--ink-soft); font-size: 16px; font-weight: 700; text-anchor: start;
      font-variant-numeric: tabular-nums; letter-spacing: 0.02em;
    }
    .t-metromap .mm-ixname { fill: var(--ink); font-size: 19px; font-weight: 700; text-anchor: start; }
    .t-metromap .mm-ixnote { fill: var(--ink-soft); font-size: 15px; text-anchor: start; }

    /* --- legend --- */
    .t-metromap .mm-legbox { fill: none; stroke: var(--ink-soft); stroke-width: 1.5; opacity: 0.45; }
    .t-metromap .mm-legtitle {
      fill: var(--ink-soft); font-size: 12px; font-weight: 700;
      letter-spacing: 0.2em; text-anchor: start;
    }
    .t-metromap .mm-legtext { fill: var(--ink); font-size: 15px; text-anchor: start; }
    .t-metromap .mm-leg-you { stroke: var(--you); stroke-width: 9; stroke-linecap: round; }
    .t-metromap .mm-leg-gaia { stroke: var(--gaia); stroke-width: 9; stroke-linecap: round; opacity: 0.55; }
    .t-metromap .mm-leg-dec { stroke: var(--accent); stroke-width: 8; stroke-dasharray: 12 8; }
  `;

  // -- svg builders -------------------------------------------------------
  function mmTermBox(x, ty, place, time, name, note, full, cls) {
    const cw = 12.6;
    const w = Math.max(104, name.length * cw + 32);
    const h = 42;
    const gap = 20;
    let bTop, cy2, timeY, noteEl = "";
    if (place === "above") {
      bTop = ty - gap - h;
      cy2 = ty - gap;
      timeY = bTop - 12;
      if (full && note) noteEl = `<text class="mm-note" x="${x}" y="${ty + 33}">${esc(note)}</text>`;
    } else {
      bTop = ty + gap;
      cy2 = ty + gap;
      timeY = bTop + h + 24;
      if (full && note) noteEl = `<text class="mm-note" x="${x}" y="${bTop + h + 44}">${esc(note)}</text>`;
    }
    return (
      `<line class="mm-conn ${cls}" x1="${x}" y1="${ty}" x2="${x}" y2="${cy2}"/>` +
      `<circle class="mm-cap ${cls}" cx="${x}" cy="${ty}" r="9"/>` +
      `<rect class="mm-box ${cls}" x="${(x - w / 2).toFixed(1)}" y="${bTop}" width="${w.toFixed(1)}" height="${h}" rx="7"/>` +
      `<text class="mm-boxname" x="${x}" y="${bTop + h / 2 + 7}">${caps(name)}</text>` +
      `<text class="mm-time" x="${x}" y="${timeY}">${esc(time)}</text>` +
      noteEl
    );
  }

  function mmStop(x, ty, time, name, note, full) {
    // ordinary station: perpendicular tick, labels stacked below the trunk
    return (
      `<line class="mm-tick" x1="${x}" y1="${ty - 13}" x2="${x}" y2="${ty + 13}"/>` +
      `<text class="mm-time" x="${x}" y="${ty + 40}">${esc(time)}</text>` +
      `<text class="mm-name" x="${x}" y="${ty + 62}">${esc(name)}</text>` +
      (full && note ? `<text class="mm-note" x="${x}" y="${ty + 82}">${esc(note)}</text>` : "")
    );
  }

  function mmHollow(x, y, name, note, full) {
    // "proposed service" station: open circle, labels above the dashed spur
    return (
      `<circle class="mm-hollow" cx="${x}" cy="${y}" r="13"/>` +
      `<text class="mm-name" x="${x}" y="${y - 44}">${esc(name)}</text>` +
      (full && note ? `<text class="mm-note" x="${x}" y="${y - 25}">${esc(note)}</text>` : "")
    );
  }

  EXPLORER.register({
    id: "metromap",
    name: "The Line Guide",
    axes: {
      livery: [
        { id: "london", label: "London — ox-red & blue", you: "#D0442F", gaia: "#3E6FD0", accent: "#DB8E27" },
        { id: "tokyo", label: "Tokyo — teal & rose", you: "#12ADA6", gaia: "#E4589A", accent: "#E7A63E" },
        { id: "paris", label: "Paris — jade & gold", you: "#1E9E74", gaia: "#C99B34", accent: "#B24A63" },
        { id: "nyc", label: "New York — blue & amber", you: "#2E6BE0", gaia: "#D6A31E", accent: "#F0741E" },
      ],
      ground: [
        {
          id: "day",
          label: "Day service (white)",
          paper: "#f2f0e7", ink: "#1a1b1e", inkSoft: "#676a70",
          noticeBg: "rgba(20,20,22,0.05)",
        },
        {
          id: "night",
          label: "Night service (navy)",
          paper: "#101a30", ink: "#eef1f7", inkSoft: "#98a1b4",
          noticeBg: "rgba(255,255,255,0.06)",
        },
      ],
      notes: [
        { id: "full", label: "Full station notes" },
        { id: "terse", label: "Terse (names only)" },
      ],
    },
    css: METROMAP_CSS,
    render(ed, skin) {
      const { livery, ground, notes } = skin;
      const full = notes.id === "full";
      const c = ed.content;
      const wdAbbr = ed.weekday.slice(0, 3).toUpperCase();

      // trunks
      const YOU_Y = 340, GAIA_Y = 600;
      const X_REV = 165, X_IX = 450, X_SYNC = 735, X_SHIP = 1030;
      const G_DONE = 165, G_MOVE = 690;
      const D_A = 855, D_B = 1015, D_Y = 250; // decisions hollow stations (well spaced along the spur)

      const you = c.today; // [review, sync, ship]
      const ov = c.overnight; // [done(02:14), draft(03:41), moved(04:09)]
      const dec = c.decisions; // [approve, decide]

      const lines =
        `<polyline class="mm-you-line" points="${X_REV},${YOU_Y} ${X_SHIP},${YOU_Y}"/>` +
        `<polyline class="mm-gaia-line" points="${G_DONE},${GAIA_Y} ${G_MOVE},${GAIA_Y}"/>` +
        `<polyline class="mm-dec-line" points="${X_SYNC},${YOU_Y} ${X_SYNC + (YOU_Y - D_Y)},${D_Y} ${D_B},${D_Y}"/>`;

      // interchange: two rings joined by a neutral tie bar (GAIA hands to YOU)
      const interchange =
        `<line class="mm-tie" x1="${X_IX}" y1="${YOU_Y}" x2="${X_IX}" y2="${GAIA_Y}"/>` +
        `<circle class="mm-ring" cx="${X_IX}" cy="${YOU_Y}" r="17"/>` +
        `<circle class="mm-ring" cx="${X_IX}" cy="${GAIA_Y}" r="17"/>` +
        `<text class="mm-ixtime" x="${X_IX + 30}" y="${(YOU_Y + GAIA_Y) / 2 - 20}">${esc(ov[1].t24 || "")}</text>` +
        `<text class="mm-ixname" x="${X_IX + 30}" y="${(YOU_Y + GAIA_Y) / 2 + 3}">${esc(ov[1].label)}</text>` +
        (full && ov[1].note
          ? `<text class="mm-ixnote" x="${X_IX + 30}" y="${(YOU_Y + GAIA_Y) / 2 + 24}">${esc(ov[1].note)}</text>`
          : "");

      const stations =
        // YOU termini
        mmTermBox(X_REV, YOU_Y, "above", you[0].t24 || "", you[0].label, you[0].note, full, "you") +
        mmTermBox(X_SHIP, YOU_Y, "above", "EOD", you[2].label, you[2].note, full, "you") +
        // YOU mid: investor sync
        mmStop(X_SYNC, YOU_Y, you[1].t24 || "", you[1].label, you[1].note, full) +
        // GAIA termini
        mmTermBox(G_DONE, GAIA_Y, "below", ov[0].t24 || "", ov[0].label, ov[0].note, full, "gaia") +
        mmTermBox(G_MOVE, GAIA_Y, "below", ov[2].t24 || "", ov[2].label, ov[2].note, full, "gaia") +
        // decisions
        mmHollow(D_A, D_Y, dec[0].label, dec[0].note, full) +
        mmHollow(D_B, D_Y, dec[1].label, dec[1].note, full);

      const legend =
        `<g>` +
        `<rect class="mm-legbox" x="808" y="630" width="340" height="150" rx="8"/>` +
        `<text class="mm-legtitle" x="826" y="656">LINE GUIDE</text>` +
        `<line class="mm-leg-you" x1="826" y1="682" x2="868" y2="682"/>` +
        `<text class="mm-legtext" x="882" y="687">Your day ahead</text>` +
        `<line class="mm-leg-gaia" x1="826" y1="710" x2="868" y2="710"/>` +
        `<text class="mm-legtext" x="882" y="715">GAIA — ran overnight</text>` +
        `<line class="mm-leg-dec" x1="826" y1="738" x2="868" y2="738"/>` +
        `<text class="mm-legtext" x="882" y="743">Decisions — your call</text>` +
        `<circle class="mm-ring" cx="833" cy="766" r="8"/><circle class="mm-ring" cx="861" cy="766" r="8"/>` +
        `<line class="mm-tie" x1="833" y1="766" x2="861" y2="766" stroke-width="5"/>` +
        `<text class="mm-legtext" x="882" y="771">Interchange — handoff</text>` +
        `</g>`;

      const svg =
        `<svg class="t-metromap__map" viewBox="0 0 1180 800" preserveAspectRatio="xMidYMid meet" ` +
        `role="img" aria-label="Transit-map guide to ${esc(ed.weekday)}'s brief">` +
        lines + interchange + stations + legend +
        `</svg>`;

      const roundel =
        `<svg class="t-metromap__roundel" width="84" height="84" viewBox="0 0 84 84" aria-hidden="true">` +
        `<circle cx="42" cy="42" r="32" fill="none" stroke="var(--accent)" stroke-width="9"/>` +
        `<rect x="6" y="34" width="72" height="16" fill="var(--accent)"/>` +
        `<text x="42" y="46" text-anchor="middle" font-family="Helvetica Neue, sans-serif" ` +
        `font-weight="700" font-size="12" letter-spacing="1" fill="#ffffff">${esc(wdAbbr)}</text>` +
        `</svg>`;

      const style =
        `--you:${livery.you};--gaia:${livery.gaia};--accent:${livery.accent};` +
        `--paper:${ground.paper};--ink:${ground.ink};--ink-soft:${ground.inkSoft};--notice-bg:${ground.noticeBg};`;

      return (
        `<article class="t-metromap" style="${style}">` +
        `<header class="t-metromap__mast">${roundel}` +
        `<div class="t-metromap__titles">` +
        `<p class="t-metromap__eyebrow">GAIA Transit Authority</p>` +
        `<h1 class="t-metromap__title">The ${esc(ed.weekday)} Brief</h1>` +
        `<p class="t-metromap__sub">Line Guide N&ordm; ${ed.editionNo} &middot; ${esc(ed.dateLong)}</p>` +
        `</div></header>` +
        `<hr class="t-metromap__rule">` +
        svg +
        `<div class="t-metromap__notice">` +
        `<span class="t-metromap__notice-tag">Service notice</span>` +
        `<span class="t-metromap__notice-body">${esc(ed.deck)}</span>` +
        `</div>` +
        `</article>`
      );
    },
  });

  /* ==========================================================================
   * TEMPLATE 2 — boardingpass
   * The day as an airline boarding pass lying on a flat desk. The main coupon
   * carries the scheduled "flights" (your meetings) and the cargo (the PR); the
   * tear-off stub carries what still needs confirming (the two decisions) plus a
   * fine-print manifest of services GAIA completed in transit overnight. Ticket
   * stock: flat paper tone with faint horizontal banding, no colour gradients.
   * The livery paints only the header band + accent rules.
   * ==========================================================================*/
  const BOARDINGPASS_CSS = `
    .t-boardingpass {
      min-height: 1240px; width: 100%; margin: 0; padding: 0; box-sizing: border-box;
      background: var(--desk); color: var(--ink);
      font-family: "Helvetica Neue", Helvetica, Arial, system-ui, sans-serif;
      -webkit-font-smoothing: antialiased;
    }
    .t-boardingpass * { box-sizing: border-box; }

    .t-boardingpass__desk {
      min-height: 1240px; padding: clamp(52px,7vw,120px) clamp(16px,4vw,72px);
      display: flex; justify-content: center; align-items: flex-start;
    }
    .t-boardingpass__pass {
      width: 940px; max-width: 100%; display: flex; position: relative;
      background: var(--paper);
      box-shadow:
        0 1px 0 rgba(255,255,255,0.5) inset,
        0 28px 52px -32px rgba(15,18,24,0.55),
        0 6px 16px -10px rgba(15,18,24,0.4);
    }
    .t-boardingpass__pass::after {
      content: ""; position: absolute; inset: 0; pointer-events: none;
      background: repeating-linear-gradient(0deg,
        rgba(0,0,0,0.016) 0, rgba(0,0,0,0.016) 1px, transparent 1px, transparent 6px);
      mix-blend-mode: multiply;
    }
    .t-boardingpass__pass--right { flex-direction: row; }
    .t-boardingpass__pass--bottom { flex-direction: column; width: 660px; }

    /* --- perforation + punched notches --- */
    .t-boardingpass__perf { position: relative; flex: 0 0 auto; z-index: 2; }
    .t-boardingpass__pass--right .t-boardingpass__perf {
      width: 2px; align-self: stretch;
      background: repeating-linear-gradient(180deg, var(--ink-soft) 0 7px, transparent 7px 14px);
    }
    .t-boardingpass__pass--bottom .t-boardingpass__perf {
      height: 2px; width: 100%;
      background: repeating-linear-gradient(90deg, var(--ink-soft) 0 7px, transparent 7px 14px);
    }
    .t-boardingpass__perf::before, .t-boardingpass__perf::after {
      content: ""; position: absolute; width: 20px; height: 20px;
      border-radius: 50%; background: var(--desk);
    }
    .t-boardingpass__pass--right .t-boardingpass__perf::before { top: -10px; left: -9px; }
    .t-boardingpass__pass--right .t-boardingpass__perf::after { bottom: -10px; left: -9px; }
    .t-boardingpass__pass--bottom .t-boardingpass__perf::before { left: -10px; top: -9px; }
    .t-boardingpass__pass--bottom .t-boardingpass__perf::after { right: -10px; top: -9px; }

    /* --- main coupon --- */
    .t-boardingpass__body { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; }
    .t-boardingpass__band {
      background: var(--band); color: var(--band-ink);
      padding: 18px clamp(20px,3.4vw,34px);
      display: flex; justify-content: space-between; align-items: baseline; gap: 16px; flex-wrap: wrap;
    }
    .t-boardingpass__air {
      font-family: "Aeonik Extended", "Helvetica Neue", sans-serif; font-weight: 700;
      font-size: clamp(22px,3vw,30px); letter-spacing: 0.02em; margin: 0; line-height: 1;
    }
    .t-boardingpass__air span {
      display: block; font-family: "Helvetica Neue", sans-serif; font-weight: 400;
      font-size: 10.5px; letter-spacing: 0.32em; opacity: 0.82; margin-top: 6px;
    }
    .t-boardingpass__pnr { text-align: right; font-size: 11px; letter-spacing: 0.22em; line-height: 1.9; white-space: nowrap; }
    .t-boardingpass__pnr b { font-size: 16px; letter-spacing: 0.12em; font-variant-numeric: tabular-nums; }
    .t-boardingpass__accent-rule { height: 3px; background: var(--accent); }

    .t-boardingpass__inner { padding: clamp(20px,3.2vw,32px); display: flex; flex-direction: column; gap: 22px; }

    /* route */
    .t-boardingpass__route { position: relative; padding-top: 4px; }
    .t-boardingpass__rail {
      position: absolute; top: 11px; left: 8%; right: 8%; height: 2px;
      background: repeating-linear-gradient(90deg, var(--ink-soft) 0 5px, transparent 5px 11px);
    }
    .t-boardingpass__stops { position: relative; display: flex; }
    .t-boardingpass__stop { flex: 1 1 0; min-width: 0; text-align: center; padding: 0 4px; }
    .t-boardingpass__stop:first-child { text-align: left; }
    .t-boardingpass__stop:last-child { text-align: right; }
    .t-boardingpass__node {
      width: 16px; height: 16px; border-radius: 50%; background: var(--paper);
      border: 3px solid var(--accent); margin: 0 auto 14px;
    }
    .t-boardingpass__stop:first-child .t-boardingpass__node { margin-left: 0; }
    .t-boardingpass__stop:last-child .t-boardingpass__node { margin-right: 0; }
    .t-boardingpass__stop-t {
      font-size: clamp(22px,3.2vw,32px); font-weight: 700; line-height: 1;
      font-variant-numeric: tabular-nums; letter-spacing: -0.01em;
    }
    .t-boardingpass__stop-l {
      font-size: 11px; letter-spacing: 0.13em; text-transform: uppercase;
      color: var(--ink-soft); margin-top: 8px; line-height: 1.4;
    }

    /* fields */
    .t-boardingpass__fields {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(110px,1fr)); gap: 15px 18px;
      border-top: 1px solid var(--hair); border-bottom: 1px solid var(--hair); padding: 18px 0;
    }
    .t-boardingpass__f-l { font-size: 10px; letter-spacing: 0.18em; text-transform: uppercase; color: var(--ink-soft); }
    .t-boardingpass__f-v {
      font-size: 16px; font-weight: 700; margin-top: 4px;
      font-variant-numeric: tabular-nums; letter-spacing: 0.01em; overflow-wrap: break-word;
    }
    .t-boardingpass__f-v.seat { color: var(--accent); }

    /* segments */
    .t-boardingpass__segs { display: flex; flex-direction: column; gap: 14px; }
    .t-boardingpass__seg { display: flex; gap: 16px; align-items: baseline; }
    .t-boardingpass__seg-k {
      flex: 0 0 auto; width: 96px; font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;
      color: var(--accent); font-weight: 700; padding-top: 2px;
    }
    .t-boardingpass__seg-b { min-width: 0; }
    .t-boardingpass__seg-t { font-size: 15.5px; font-weight: 600; line-height: 1.4; }
    .t-boardingpass__seg-t b { font-variant-numeric: tabular-nums; }
    .t-boardingpass__seg-n { font-size: 13px; color: var(--ink-soft); margin-top: 2px; }

    /* fare box */
    .t-boardingpass__fare { display: flex; border: 1px solid var(--hair); }
    .t-boardingpass__fare-c { flex: 1 1 0; text-align: center; padding: 15px 8px; border-right: 1px solid var(--hair); min-width: 0; }
    .t-boardingpass__fare-c:last-child { border-right: 0; }
    .t-boardingpass__fare-v { font-size: 23px; font-weight: 700; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }
    .t-boardingpass__fare-l { font-size: 9.5px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--ink-soft); margin-top: 5px; }

    .t-boardingpass__foot {
      margin-top: auto; padding: 13px clamp(20px,3.2vw,32px);
      border-top: 1px dashed var(--hair); font-size: 11px; letter-spacing: 0.05em;
      color: var(--ink-soft); line-height: 1.5;
    }
    .t-boardingpass__foot b { letter-spacing: 0.16em; text-transform: uppercase; color: var(--ink); }

    /* --- stub --- */
    .t-boardingpass__stub { flex: 0 0 auto; padding: clamp(18px,2.6vw,26px); display: flex; flex-direction: column; gap: 16px; }
    .t-boardingpass__pass--right .t-boardingpass__stub { width: 266px; }
    .t-boardingpass__pass--bottom .t-boardingpass__stub { width: 100%; }
    .t-boardingpass__stub-head { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
    .t-boardingpass__stub-air { font-family: "Aeonik Extended", "Helvetica Neue", sans-serif; font-weight: 700; font-size: 16px; letter-spacing: 0.04em; }
    .t-boardingpass__stub-fl { font-size: 13px; font-weight: 700; letter-spacing: 0.1em; font-variant-numeric: tabular-nums; }
    .t-boardingpass__stub-cols { display: flex; flex-direction: column; gap: 16px; }
    .t-boardingpass__pass--bottom .t-boardingpass__stub-cols { flex-direction: row; flex-wrap: wrap; }
    .t-boardingpass__pass--bottom .t-boardingpass__stub-col { flex: 1 1 220px; min-width: 0; }
    .t-boardingpass__await {
      font-size: 12px; letter-spacing: 0.18em; text-transform: uppercase; color: var(--accent);
      font-weight: 700; border-top: 1px solid var(--hair); padding-top: 13px; margin-bottom: 12px;
    }
    .t-boardingpass__conn { margin-bottom: 11px; }
    .t-boardingpass__conn-k { font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--ink-soft); }
    .t-boardingpass__conn-t { font-size: 14px; font-weight: 600; line-height: 1.35; margin-top: 2px; }
    .t-boardingpass__conn-n { font-size: 12px; color: var(--ink-soft); margin-top: 1px; font-variant-numeric: tabular-nums; }
    .t-boardingpass__transit { font-size: 11px; color: var(--ink-soft); line-height: 1.6; font-variant-numeric: tabular-nums; }
    .t-boardingpass__transit b {
      display: block; text-transform: uppercase; letter-spacing: 0.14em;
      color: var(--ink); font-size: 9.5px; margin-bottom: 6px;
    }
    .t-boardingpass__transit p { margin: 0 0 5px; }
    .t-boardingpass__code { margin-top: 4px; }
    .t-boardingpass__barcode {
      height: 66px; width: 100%;
      background-image: repeating-linear-gradient(90deg,
        var(--ink) 0, var(--ink) 2px, transparent 2px, transparent 4px,
        var(--ink) 4px, var(--ink) 5px, transparent 5px, transparent 8px,
        var(--ink) 8px, var(--ink) 11px, transparent 11px, transparent 12px,
        var(--ink) 12px, var(--ink) 13px, transparent 13px, transparent 16px,
        var(--ink) 16px, var(--ink) 19px, transparent 19px, transparent 21px,
        var(--ink) 21px, var(--ink) 22px, transparent 22px, transparent 25px);
    }
    .t-boardingpass__barnum {
      font-family: Menlo, "SF Mono", ui-monospace, monospace; font-size: 10px;
      letter-spacing: 0.16em; text-align: center; margin: 7px 0 0; color: var(--ink);
      font-variant-numeric: tabular-nums;
    }

    /* narrow reflow: both stub positions fall to a stacked coupon + horizontal tear */
    @media (max-width: 680px) {
      .t-boardingpass__pass--right { flex-direction: column; width: 660px; }
      .t-boardingpass__pass--right .t-boardingpass__perf {
        width: 100%; height: 2px;
        background: repeating-linear-gradient(90deg, var(--ink-soft) 0 7px, transparent 7px 14px);
      }
      .t-boardingpass__pass--right .t-boardingpass__perf::before { left: -10px; top: -9px; }
      .t-boardingpass__pass--right .t-boardingpass__perf::after { right: -10px; top: -9px; bottom: auto; left: auto; }
      .t-boardingpass__pass--right .t-boardingpass__stub { width: 100%; }
      .t-boardingpass__pass--right .t-boardingpass__stub-cols { flex-direction: row; flex-wrap: wrap; }
      .t-boardingpass__pass--right .t-boardingpass__stub-col { flex: 1 1 220px; min-width: 0; }
    }
  `;

  function bpSeg(k, time, text, note) {
    return (
      `<div class="t-boardingpass__seg">` +
      `<div class="t-boardingpass__seg-k">${esc(k)}</div>` +
      `<div class="t-boardingpass__seg-b">` +
      `<div class="t-boardingpass__seg-t">${time ? `<b>${esc(time)}</b> &middot; ` : ""}${esc(text)}</div>` +
      (note ? `<div class="t-boardingpass__seg-n">${esc(note)}</div>` : "") +
      `</div></div>`
    );
  }
  function bpField(label, value, cls) {
    return (
      `<div><div class="t-boardingpass__f-l">${esc(label)}</div>` +
      `<div class="t-boardingpass__f-v${cls ? " " + cls : ""}">${esc(value)}</div></div>`
    );
  }
  function bpConn(k, text, note) {
    return (
      `<div class="t-boardingpass__conn">` +
      `<div class="t-boardingpass__conn-k">${esc(k)}</div>` +
      `<div class="t-boardingpass__conn-t">${esc(text)}</div>` +
      (note ? `<div class="t-boardingpass__conn-n">${esc(note)}</div>` : "") +
      `</div>`
    );
  }

  EXPLORER.register({
    id: "boardingpass",
    name: "The Boarding Pass",
    axes: {
      livery: [
        { id: "midnight", label: "Midnight blue & gold", band: "#14263f", bandInk: "#EFE7CF", accent: "#B0873A" },
        { id: "evergreen", label: "Evergreen & cream", band: "#163a2b", bandInk: "#E8E0CB", accent: "#7E6C38" },
        { id: "oxblood", label: "Oxblood & ivory", band: "#4a1c20", bandInk: "#EFE2D6", accent: "#9E4A3C" },
        { id: "slate", label: "Slate & signal orange", band: "#2c333c", bandInk: "#EDF0F3", accent: "#D0672B" },
      ],
      stock: [
        {
          id: "white",
          label: "Bright white stock",
          paper: "#fbfaf7", ink: "#221f1b", inkSoft: "#6f6b64",
          hair: "rgba(20,18,14,0.14)", desk: "#c8c6bf",
        },
        {
          id: "ivory",
          label: "Warm ivory stock",
          paper: "#f3ecd9", ink: "#2a241b", inkSoft: "#7a7161",
          hair: "rgba(40,30,15,0.16)", desk: "#c7bda6",
        },
      ],
      stub: [
        { id: "right", label: "Stub on the right" },
        { id: "bottom", label: "Stub along the foot" },
      ],
    },
    css: BOARDINGPASS_CSS,
    render(ed, skin) {
      const { livery, stock, stub } = skin;
      const c = ed.content;
      const wdAbbr = ed.weekday.slice(0, 3).toUpperCase();
      const monAbbr = ed.monthShort.toUpperCase();
      const flight = "GA-" + pad3(ed.editionNo);
      const seat = ed.editionNo + "A";
      const dateBody = `${wdAbbr} ${pad2(ed.day)} ${monAbbr} ${ed.year}`;
      const dateStub = `${caps(ed.weekday)} ${pad2(ed.day)} ${monAbbr}`;

      const t = c.today; // review / sync / ship
      const ov = c.overnight;
      const dec = c.decisions;
      const st = c.stats;

      const band =
        `<div class="t-boardingpass__band">` +
        `<h1 class="t-boardingpass__air">GAIA AIR<span>BRIEFING CLASS</span></h1>` +
        `<div class="t-boardingpass__pnr">BOARDING PASS<br><b>${esc(flight)}</b></div>` +
        `</div><div class="t-boardingpass__accent-rule"></div>`;

      const route =
        `<div class="t-boardingpass__route"><div class="t-boardingpass__rail"></div>` +
        `<div class="t-boardingpass__stops">` +
        `<div class="t-boardingpass__stop"><div class="t-boardingpass__node"></div>` +
        `<div class="t-boardingpass__stop-t">${esc(t[0].t24 || "")}</div>` +
        `<div class="t-boardingpass__stop-l">Boarding<br>${esc(t[0].label)}</div></div>` +
        `<div class="t-boardingpass__stop"><div class="t-boardingpass__node"></div>` +
        `<div class="t-boardingpass__stop-t">${esc(t[1].t24 || "")}</div>` +
        `<div class="t-boardingpass__stop-l">Connection<br>${esc(t[1].label)}</div></div>` +
        `<div class="t-boardingpass__stop"><div class="t-boardingpass__node"></div>` +
        `<div class="t-boardingpass__stop-t">EOD</div>` +
        `<div class="t-boardingpass__stop-l">Arrival<br>${esc(t[2].label)}</div></div>` +
        `</div></div>`;

      const fields =
        `<div class="t-boardingpass__fields">` +
        bpField("Passenger", "YOU") +
        bpField("Flight", flight) +
        bpField("Date", dateBody) +
        bpField("Seat", seat, "seat") +
        bpField("Boarding", t[0].t24 || "") +
        bpField("Class", "FOCUS") +
        `</div>`;

      const segs =
        `<div class="t-boardingpass__segs">` +
        bpSeg("Boarding", t[0].t24, t[0].label, t[0].note) +
        bpSeg("Connection", t[1].t24, t[1].label, t[1].note) +
        bpSeg("Cargo", null, t[2].label, t[2].note) +
        `</div>`;

      const fare =
        `<div class="t-boardingpass__fare">` +
        `<div class="t-boardingpass__fare-c"><div class="t-boardingpass__fare-v">${st.done}</div><div class="t-boardingpass__fare-l">Done</div></div>` +
        `<div class="t-boardingpass__fare-c"><div class="t-boardingpass__fare-v">${st.mail}</div><div class="t-boardingpass__fare-l">Mail cleared</div></div>` +
        `<div class="t-boardingpass__fare-c"><div class="t-boardingpass__fare-v">${esc(st.focus).toUpperCase()}</div><div class="t-boardingpass__fare-l">Focus</div></div>` +
        `</div>`;

      const foot =
        `<div class="t-boardingpass__foot"><b>Fare conditions</b> &nbsp; ${esc(ed.deck)}</div>`;

      const body =
        `<section class="t-boardingpass__body">` +
        band +
        `<div class="t-boardingpass__inner">${route}${fields}${segs}${fare}</div>` +
        foot +
        `</section>`;

      const stubEl =
        `<aside class="t-boardingpass__stub">` +
        `<div class="t-boardingpass__stub-head">` +
        `<span class="t-boardingpass__stub-air">GAIA AIR</span>` +
        `<span class="t-boardingpass__stub-fl">${esc(flight)}</span></div>` +
        `<div class="t-boardingpass__stub-cols">` +
        `<div class="t-boardingpass__stub-col">` +
        `<div class="t-boardingpass__await">Awaiting confirmation</div>` +
        bpConn("Connection 1", dec[0].verb + " — " + dec[0].label, dec[0].note) +
        bpConn("Connection 2", dec[1].verb + " — " + dec[1].label, dec[1].note) +
        `</div>` +
        `<div class="t-boardingpass__stub-col">` +
        `<div class="t-boardingpass__transit"><b>Services completed in transit</b>` +
        `<p>${esc(ov[0].t24 || "")} &middot; ${esc(ov[0].label)}</p>` +
        `<p>${esc(ov[1].t24 || "")} &middot; ${esc(ov[1].label)}</p>` +
        `<p>${esc(ov[2].t24 || "")} &middot; ${esc(ov[2].label)}</p>` +
        `</div>` +
        `<div class="t-boardingpass__f-l" style="margin-top:12px">Passenger / Seat / Date</div>` +
        `<div class="t-boardingpass__conn-t">YOU</div>` +
        `<div class="t-boardingpass__conn-n">${esc(seat)} &middot; ${esc(dateStub)}</div>` +
        `</div></div>` +
        `<div class="t-boardingpass__code"><div class="t-boardingpass__barcode"></div>` +
        `<p class="t-boardingpass__barnum">GA${pad3(ed.editionNo)}&nbsp;&nbsp;${esc(ed.time24.replace(":", ""))}&nbsp;&nbsp;YOU</p></div>` +
        `</aside>`;

      const perf = `<div class="t-boardingpass__perf" aria-hidden="true"></div>`;

      const style =
        `--band:${livery.band};--band-ink:${livery.bandInk};--accent:${livery.accent};` +
        `--paper:${stock.paper};--ink:${stock.ink};--ink-soft:${stock.inkSoft};--hair:${stock.hair};--desk:${stock.desk};`;

      return (
        `<article class="t-boardingpass" style="${style}">` +
        `<div class="t-boardingpass__desk">` +
        `<div class="t-boardingpass__pass t-boardingpass__pass--${stub.id}">` +
        body + perf + stubEl +
        `</div></div></article>`
      );
    },
  });
})();
