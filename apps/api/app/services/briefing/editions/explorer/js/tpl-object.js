/* ============================================================================
 * tpl-object.js — "object" family template for the daily-brief explorer.
 * One physical object sitting on a desk: a thermal receipt tape. Ports the
 * approved design (variant-receipt.html) — identity preserved, skin values
 * hoisted to CSS custom properties, all body content GENERATED from ed.content
 * arrays. Wrapped in an IIFE so local helpers never collide with sibling files.
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

  /* ---- torn-edge geometry --------------------------------------------
     A thermal tape is torn, not cut. Generate a fine sawtooth clip-path for
     each strip: many shallow teeth, with the top and bottom edges given
     different tooth counts + depth bands so the two tears never mirror each
     other. Deterministic (frac of a sin) — no Math.random, stable output. */
  function frac(x) {
    return x - Math.floor(x);
  }
  function tornTeeth(n, edge) {
    const flush = edge === "top" ? 100 : 0;
    const seed = edge === "top" ? 12.9898 : 78.233;
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const x = +((i / n) * 100).toFixed(2);
      if (i % 2 === 0) {
        pts.push(`${x}% ${flush}%`);
      } else {
        const j = frac(Math.sin(i * seed) * 43758.5453);
        // shorter teeth than the source cut = finer tear; top band ≠ bottom band
        const peak = edge === "top" ? 33 + j * 15 : 55 + j * 15;
        pts.push(`${x}% ${peak.toFixed(1)}%`);
      }
    }
    pts.push(edge === "top" ? "100% 100%" : "100% 0%");
    return "polygon(" + pts.join(", ") + ")";
  }
  const TEAR_TOP = tornTeeth(44, "top");
  const TEAR_BOT = tornTeeth(50, "bottom");

  /* ============================================================================
   * RECEIPT — a single ~340px thermal tape lying on a flat desk.
   * ==========================================================================*/
  const RECEIPT_CSS = `
    .t-receipt {
      min-height: 1200px;
      width: 100%;
      margin: 0;
      padding: 72px 16px 96px;
      box-sizing: border-box;
      display: flex;
      justify-content: center;
      align-items: flex-start;
      background: radial-gradient(120% 80% at 30% 0%, var(--desk-hi) 0%, var(--desk-a) 42%, var(--desk-b) 100%);
      font-family: Menlo, "SF Mono", ui-monospace, monospace;
      -webkit-font-smoothing: antialiased;
    }
    .t-receipt * { box-sizing: border-box; }

    /* the tape: a physical object on the desk.
       background layers, top→bottom: edge yellowing/vignette (skin-driven),
       fine horizontal thermal banding, faint vertical grain, then paper. All
       texture sits at 1.4–2.2% — invisible at thumbnail scale, felt at full. */
    .t-receipt__tape {
      position: relative;
      width: 340px;
      max-width: 100%;
      color: var(--ink);
      padding: 30px 26px 26px;
      transform: rotate(0.4deg);
      background:
        radial-gradient(100% 100% at 50% 50%, transparent 60%, var(--edge, transparent) 100%),
        repeating-linear-gradient(0deg, rgba(0,0,0,0.022) 0, rgba(0,0,0,0.022) 1px, transparent 1px, transparent 4px),
        repeating-linear-gradient(90deg, rgba(0,0,0,0.014) 0, rgba(0,0,0,0.014) 1px, transparent 1px, transparent 3px),
        var(--paper);
      box-shadow:
        0 1px 0 rgba(255,255,255,0.32) inset,
        0 9px 20px -14px rgba(12,16,22,0.42),
        0 2px 6px -3px rgba(12,16,22,0.34);
      font-size: 11px;
      line-height: 1.5;
      letter-spacing: 0.02em;
      font-variant-numeric: tabular-nums;
    }
    /* torn top + bottom edges via fine zig-zag clip on pseudo strips */
    .t-receipt__tape::before,
    .t-receipt__tape::after {
      content: "";
      position: absolute;
      left: 0; right: 0;
      height: 8px;
      background: var(--paper);
    }
    .t-receipt__tape::before { top: -7px; clip-path: ${TEAR_TOP}; }
    .t-receipt__tape::after { bottom: -7px; clip-path: ${TEAR_BOT}; }
    .t-receipt__paper { position: relative; }

    .t-receipt__store {
      text-align: center;
      font-size: 22px;
      line-height: 1;
      letter-spacing: 0.34em;
      margin: 0 0 12px;
      padding-left: 0.34em;
    }
    .t-receipt__meta {
      text-align: center;
      font-size: 11px;
      line-height: 1.7;
      letter-spacing: 0.06em;
      margin: 0;
    }
    .t-receipt__greet {
      margin: 12px 0 0;
      text-align: center;
      color: var(--ink-soft);
      letter-spacing: 0.01em;
    }

    .t-receipt__rule {
      margin: 12px 0;
      overflow: hidden;
      white-space: nowrap;
      color: var(--ink);
      letter-spacing: 0;
      -webkit-user-select: none;
      user-select: none;
    }
    .t-receipt__rule::before { content: "--------------------------------------------------"; }
    .t-receipt__rule--double::before { content: "=================================================="; }

    .t-receipt__sec { letter-spacing: 0.14em; margin: 0 0 8px; }

    /* line items: label ....... value — label always prints in full (wraps,
       never truncates); dotted leader flexes; value right-aligns to one edge */
    .t-receipt__item {
      display: flex;
      align-items: flex-end;
      gap: 0;
      margin: 0 0 5px;
    }
    .t-receipt__label {
      flex: 0 1 auto;
      min-width: 0;
      white-space: normal;
      overflow-wrap: break-word;
    }
    .t-receipt__leader {
      flex: 1 1 auto;
      min-width: 12px;
      height: 0;
      margin: 0 5px 3px;
      border-bottom: 2px dotted var(--ink-soft);
    }
    .t-receipt__val {
      flex: 0 0 auto;
      text-align: right;
      white-space: nowrap;
    }
    .t-receipt__note {
      margin: -2px 0 7px;
      padding-left: 2px;
      color: var(--ink-soft);
    }
    .t-receipt__group { margin: 0 0 12px; }

    /* card-authorization slip: real receipt tender info, deadpan */
    .t-receipt__tender {
      text-align: center;
      letter-spacing: 0.14em;
      padding-left: 0.14em;
      line-height: 1.75;
      margin: 8px 0 0;
      color: var(--ink);
      font-variant-numeric: tabular-nums;
    }
    .t-receipt__tender span { display: block; }

    .t-receipt__thanks {
      text-align: center;
      letter-spacing: 0.18em;
      margin: 4px 0 14px;
    }
    /* CSS barcode: irregular vertical stripes, no libraries */
    .t-receipt__barcode {
      height: 52px;
      margin: 0 auto 6px;
      width: 220px;
      max-width: 100%;
      background-image: repeating-linear-gradient(90deg,
        var(--ink) 0, var(--ink) 2px, transparent 2px, transparent 4px,
        var(--ink) 4px, var(--ink) 5px, transparent 5px, transparent 8px,
        var(--ink) 8px, var(--ink) 11px, transparent 11px, transparent 12px,
        var(--ink) 12px, var(--ink) 13px, transparent 13px, transparent 16px,
        var(--ink) 16px, var(--ink) 19px, transparent 19px, transparent 21px,
        var(--ink) 21px, var(--ink) 22px, transparent 22px, transparent 25px);
    }
    .t-receipt__barnum {
      text-align: center;
      letter-spacing: 0.32em;
      padding-left: 0.32em;
      margin: 0 0 12px;
    }
    .t-receipt__colophon {
      text-align: center;
      font-size: 9px;
      letter-spacing: 0.06em;
      color: var(--ink-soft);
      line-height: 1.6;
      margin: 0;
    }
    @media (max-width: 380px) {
      .t-receipt { padding: 48px 12px 64px; }
      .t-receipt__tape { width: 300px; padding: 28px 20px 24px; }
    }
  `;

  function rItem(label, val) {
    return (
      `<div class="t-receipt__item">` +
      `<span class="t-receipt__label">${caps(label)}</span>` +
      `<span class="t-receipt__leader" aria-hidden="true"></span>` +
      `<span class="t-receipt__val">${caps(val)}</span>` +
      `</div>`
    );
  }
  function rNote(txt) {
    return `<p class="t-receipt__note">&nbsp;&nbsp;${caps(txt)}</p>`;
  }
  function rGroup(sec, body) {
    return (
      `<div class="t-receipt__group">` +
      (sec ? `<p class="t-receipt__sec">${sec}</p>` : "") +
      body +
      `</div>`
    );
  }
  const rRule = `<div class="t-receipt__rule" aria-hidden="true"></div>`;
  const rRuleD = `<div class="t-receipt__rule t-receipt__rule--double" aria-hidden="true"></div>`;

  EXPLORER.register({
    id: "receipt",
    name: "The Receipt",
    axes: {
      stock: [
        {
          id: "thermal",
          label: "Thermal white",
          paper: "#f6f4ec",
          edge: "rgba(92,90,82,0.05)",
        },
        {
          id: "canary",
          label: "Canary yellow",
          paper: "#f4e9b6",
          edge: "rgba(150,120,25,0.12)",
        },
      ],
      desk: [
        {
          id: "slate",
          label: "Cool slate",
          deskHi: "#79808b",
          deskA: "#6f7680",
          deskB: "#5b626c",
        },
        {
          id: "putty",
          label: "Warm putty",
          deskHi: "#b7ac97",
          deskA: "#a89c85",
          deskB: "#928873",
        },
        {
          id: "baize",
          label: "Green baize",
          deskHi: "#356453",
          deskA: "#284c3e",
          deskB: "#1d382d",
        },
        {
          id: "walnut",
          label: "Walnut brown",
          deskHi: "#6f5238",
          deskA: "#5a4230",
          deskB: "#453022",
        },
      ],
      density: [
        {
          id: "crisp",
          label: "Crisp near-black",
          ink: "#22221f",
          inkSoft: "#54524b",
        },
        {
          id: "faded",
          label: "Slightly faded",
          ink: "#4b4942",
          inkSoft: "#7a786f",
        },
      ],
      plate: [
        {
          id: "brief",
          label: "GAIA — Daily Brief",
          store: "G A I A",
          tagline: "DAILY BRIEF &mdash; REGISTER 1",
        },
        {
          id: "register",
          label: "GAIA Register Nº 1",
          store: "G A I A",
          tagline: "GAIA REGISTER N&ordm; 1",
        },
      ],
    },
    css: RECEIPT_CSS,
    render(ed, skin) {
      const { stock, desk, density, plate } = skin;
      const c = ed.content;
      const wd3 = ed.weekday.slice(0, 3).toUpperCase();
      const mon3 = ed.monthShort.toUpperCase();
      const itemCount =
        c.today.length + c.overnight.length + c.decisions.length;

      const meta =
        `${plate.tagline}<br>` +
        `${wd3} ${pad2(ed.day)} ${mon3} ${ed.year}&nbsp;&nbsp;${ed.time24}<br>` +
        `EDITION #${ed.editionNo}<br>` +
        `SERVED BY: GAIA &middot; TERMINAL 01`;

      const today = c.today
        .map(
          (it) =>
            rItem(it.label, it.t24 || "EOD") + (it.note ? rNote(it.note) : ""),
        )
        .join("");
      const overnight = c.overnight
        .map((it) => rItem(it.label, it.tag) + (it.note ? rNote(it.note) : ""))
        .join("");
      const decisions = c.decisions
        .map((it) => rItem(it.label, it.verb) + (it.note ? rNote(it.note) : ""))
        .join("");
      const stats = c.stats;
      const statBody =
        rItem("Done yesterday", stats.done) +
        rNote(`You ${stats.you} / GAIA ${stats.gaia}`) +
        rItem("Emails handled", stats.mail) +
        rItem("Focus time", stats.focus);

      const style =
        `--paper:${stock.paper};--edge:${stock.edge};--ink:${density.ink};--ink-soft:${density.inkSoft};` +
        `--desk-hi:${desk.deskHi};--desk-a:${desk.deskA};--desk-b:${desk.deskB};`;

      return (
        `<article class="t-receipt" style="${style}">` +
        `<div class="t-receipt__tape"><div class="t-receipt__paper">` +
        `<h1 class="t-receipt__store">${plate.store}</h1>` +
        `<p class="t-receipt__meta">${meta}</p>` +
        rRule +
        `<p class="t-receipt__greet">${esc(ed.deck)}</p>` +
        rRule +
        rGroup("TODAY", today) +
        rRule +
        rGroup("OVERNIGHT &mdash; PREPAID BY GAIA", overnight) +
        rRule +
        rGroup(
          `AWAITING PAYMENT &mdash; ${c.decisions.length} ITEMS`,
          decisions,
        ) +
        rRule +
        rGroup("", statBody) +
        rRuleD +
        rItem("TOTAL", `1 ${ed.weekday}`) +
        `<div class="t-receipt__tender">` +
        `<span>ITEMS: ${itemCount}</span>` +
        `<span>AUTH ${ed.editionNo}-0602 &middot; APPROVED</span>` +
        `</div>` +
        rRule +
        `<p class="t-receipt__thanks">*** THANK YOU FOR WAKING ***</p>` +
        `<div class="t-receipt__barcode" aria-hidden="true"></div>` +
        `<p class="t-receipt__barnum">ED${ed.editionNo}-${ed.time24.replace(":", "")}-GAIA</p>` +
        `<p class="t-receipt__colophon">EDITION No. ${ed.editionNo} &middot; GENERATED ${ed.time24} BY GAIA</p>` +
        `</div></div>` +
        `</article>`
      );
    },
  });
})();
