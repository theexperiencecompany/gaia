/* ===========================================================================
   tpl-brand.js — three brand-forward editions for The Daily Brief explorer.
     band     — GAIA's own product-brand editorial, recolored band wallpaper
     playfair — Playfair Display frontispiece, fashion-magazine restraint
     postal   — an airmail envelope + letter, par avion
   All content from `ed`; skin values arrive as inline custom properties.
   =========================================================================== */

/* ---- shared helpers (module-local) ---------------------------------------- */
function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
function todayWhen(it) {
  return it.time || "EOD";
}
function clockAMPM(t24) {
  // "13:30" -> "1:30 PM" — used where a 12h clock reads better than 24h.
  if (!t24) return "";
  const [h, m] = t24.split(":").map(Number);
  const ap = h < 12 ? "AM" : "PM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${String(m).padStart(2, "0")} ${ap}`;
}
/* postalCancel — an authentic cancellation: a double-ring circular datestamp
   (city curved around the top arc via textPath, GAIA POST along the bottom,
   date + time centred) with wavy killer bars fanning out of one side. Rough
   ink from a self-contained turbulence displacement filter. Deterministic. */
function postalCancel(ed, skin) {
  const uid = skin.city.id;
  const cx = 92;
  const cy = 84;
  const markMonth = ed.month.slice(0, 3).toUpperCase();
  const date = `${ed.day} ${markMonth}`;
  // wavy killer bars fan out to the right of the datestamp, sweeping over the stamp
  const wave = (y) => {
    let d = `M 168 ${y}`;
    let up = true;
    for (let px = 168; px < 392; px += 44) {
      const nx = Math.min(px + 44, 392);
      const mx = (px + nx) / 2;
      d += ` Q ${mx} ${y + (up ? -6 : 6)} ${nx} ${y}`;
      up = !up;
    }
    return d;
  };
  const bars = [50, 72, 94, 116]
    .map(
      (y) =>
        `<path d="${wave(y)}" fill="none" stroke="currentColor" stroke-width="5.2" stroke-linecap="round"/>`,
    )
    .join("");
  return `<svg viewBox="0 0 400 168" role="presentation">
    <defs>
      <path id="ca-top-${uid}" d="M 30 61.4 A 66 66 0 0 1 154 61.4"/>
      <path id="ca-bot-${uid}" d="M 30 106.6 A 66 66 0 0 0 154 106.6"/>
      <filter id="ca-rough-${uid}" x="-8%" y="-8%" width="116%" height="116%">
        <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="1" seed="6" result="n"/>
        <feDisplacementMap in="SourceGraphic" in2="n" scale="1.1"/>
      </filter>
    </defs>
    <g filter="url(#ca-rough-${uid})" fill="currentColor">
      ${bars}
      <circle cx="${cx}" cy="${cy}" r="76" fill="none" stroke="currentColor" stroke-width="2.8"/>
      <circle cx="${cx}" cy="${cy}" r="62" fill="none" stroke="currentColor" stroke-width="1.4"/>
      <text text-anchor="middle" font-size="10.5" letter-spacing="2" font-weight="bold">
        <textPath href="#ca-top-${uid}" startOffset="50%">${esc(skin.city.city)}</textPath>
      </text>
      <text text-anchor="middle" font-size="7.5" letter-spacing="1.6">
        <textPath href="#ca-bot-${uid}" startOffset="50%">GAIA POST</textPath>
      </text>
      <text x="${cx}" y="80" text-anchor="middle" font-size="18" font-weight="bold" letter-spacing="0.5">${esc(date)}</text>
      <text x="${cx}" y="95" text-anchor="middle" font-size="10" letter-spacing="1.6">${ed.year}</text>
      <text x="${cx}" y="108" text-anchor="middle" font-size="11.5" letter-spacing="1">${esc(ed.time24)}</text>
    </g>
  </svg>`;
}

/* ===========================================================================
   1. band — GAIA's own daily-brief masthead over the bands wallpaper.
   =========================================================================== */
EXPLORER.register({
  id: "band",
  name: "GAIA · Band",
  axes: {
    // The hue axis carries a matched accent — the band and the accent move together.
    hue: [
      {
        id: "azure",
        label: "Azure → blue",
        rot: "0deg",
        sat: "1.06",
        accent: "#5aa0ff",
      },
      {
        id: "violet",
        label: "Violet → purple",
        rot: "48deg",
        sat: "1.12",
        accent: "#a98bff",
      },
      {
        id: "jade",
        label: "Jade → green",
        rot: "258deg",
        sat: "1.22",
        accent: "#3fd089",
      },
      {
        id: "amber",
        label: "Amber → yellow",
        rot: "190deg",
        sat: "1.34",
        accent: "#e8b23e",
      },
      {
        id: "magenta",
        label: "Magenta → pink",
        rot: "90deg",
        sat: "1.16",
        accent: "#ff6ba6",
      },
    ],
    mast: [
      { id: "over", label: "Overlaid on band" },
      { id: "below", label: "Below band" },
    ],
    height: [
      { id: "tall", label: "Tall hero", h: "440px" },
      { id: "slim", label: "Slim strip", h: "188px" },
    ],
  },
  css: `
    .t-band {
      /* Dark zinc world, fixed — the brand's native ground. */
      --bg: #0a0a0d; --fg: #ededf1; --mut: #8a8a94;
      --line: rgba(255,255,255,0.12); --faint: rgba(255,255,255,0.05);
      box-sizing: border-box;
      width: 100%;
      min-height: 1280px;
      margin: 0;
      background: var(--bg);
      color: var(--fg);
      font-family: "Helvetica Neue", system-ui, -apple-system, Arial, sans-serif;
      -webkit-font-smoothing: antialiased;
      overflow: hidden;
    }
    .t-band * { box-sizing: border-box; }

    .t-band__hero { position: relative; width: 100%; height: var(--band-h); overflow: hidden; }
    /* the wallpaper band renders crisp: hard top/bottom edges against the flat dark ground */
    .t-band__band {
      position: absolute; inset: 0;
      background-size: cover;
      background-position: center 78%;
      filter: hue-rotate(var(--hue)) saturate(var(--sat));
    }

    .t-band__mast { position: relative; z-index: 2; display: flex; flex-direction: column; gap: clamp(8px, 1.4vw, 14px); }
    .t-band[data-mast="over"] .t-band__mast {
      position: absolute; left: clamp(22px, 4.4vw, 60px); top: clamp(24px, 3.6vw, 48px);
      right: clamp(22px, 4.4vw, 60px); color: #f5f6fb;
    }
    .t-band[data-mast="below"] .t-band__mast {
      margin: clamp(30px, 4.4vw, 56px) 0 clamp(26px, 3.6vw, 44px);
    }
    .t-band__kicker {
      font-size: clamp(12px, 1.35vw, 15px); font-weight: 600; letter-spacing: 0;
      color: inherit; opacity: 0.86; font-variant-numeric: tabular-nums;
    }
    .t-band[data-mast="below"] .t-band__kicker { color: var(--mut); opacity: 1; }
    .t-band__wordmark {
      margin: 0; font-family: "Aeonik Extended", "Helvetica Neue", system-ui, sans-serif;
      font-weight: 700; font-size: clamp(52px, 9.5vw, 132px); line-height: 0.9;
      letter-spacing: -0.01em; text-transform: uppercase;
    }
    .t-band__date {
      font-size: clamp(13px, 1.4vw, 16px); letter-spacing: 0; opacity: 0.9;
      font-variant-numeric: tabular-nums;
    }
    .t-band[data-mast="below"] .t-band__date { color: var(--mut); opacity: 1; }

    .t-band__body {
      max-width: 1180px; margin: 0 auto;
      padding: clamp(30px, 4.4vw, 60px) clamp(22px, 4.4vw, 60px) clamp(48px, 6vw, 84px);
    }
    .t-band[data-mast="over"] .t-band__body { padding-top: clamp(40px, 5vw, 72px); }

    .t-band__deck {
      margin: 0 0 clamp(40px, 5vw, 68px); max-width: 34ch;
      font-size: clamp(22px, 3vw, 34px); line-height: 1.28; letter-spacing: -0.01em;
      font-weight: 400; color: var(--fg);
    }

    .t-band__sections { display: grid; grid-template-columns: 1fr; gap: clamp(30px, 4vw, 52px); }
    .t-band__sec { border-top: 1px solid var(--line); padding-top: clamp(14px, 1.8vw, 22px); }
    /* section heading: sentence case, medium, normal tracking — the accent lives in the numeral */
    .t-band__label {
      display: flex; align-items: baseline; gap: clamp(10px, 1.4vw, 16px);
      margin: 0 0 clamp(12px, 1.6vw, 20px);
      font-size: clamp(17px, 1.9vw, 22px); font-weight: 600; letter-spacing: -0.01em;
      color: var(--fg);
    }
    .t-band__label .num {
      font-family: "Aeonik Extended", "Helvetica Neue", system-ui, sans-serif; font-weight: 700;
      font-size: 0.72em; color: var(--accent); font-variant-numeric: tabular-nums;
    }
    .t-band__label .ct { margin-left: auto; font-size: 0.62em; font-weight: 400; color: var(--mut); font-variant-numeric: tabular-nums; }

    .t-band__row {
      display: grid; grid-template-columns: clamp(72px, 9vw, 116px) 1fr;
      gap: clamp(12px, 2vw, 28px);
      padding: clamp(12px, 1.6vw, 18px) 0;
      border-top: 1px solid var(--faint);
    }
    .t-band__row:first-of-type { border-top: 0; }
    .t-band__when {
      font-size: clamp(13px, 1.5vw, 16px); font-weight: 600; letter-spacing: 0.01em;
      font-variant-numeric: tabular-nums; color: var(--fg); padding-top: 2px;
    }
    .t-band__when.verb { font-size: clamp(13px, 1.5vw, 16px); font-weight: 600; letter-spacing: 0; color: var(--mut); }
    .t-band__lead { font-size: clamp(15px, 1.75vw, 19px); line-height: 1.42; letter-spacing: -0.005em; }
    .t-band__note { color: var(--mut); }
    .t-band__tag {
      margin-top: 6px; font-size: clamp(11px, 1.15vw, 12.5px); letter-spacing: 0;
      text-transform: lowercase; color: var(--mut); font-weight: 500;
    }

    .t-band__stats {
      display: flex; flex-wrap: wrap; gap: 0; margin: clamp(40px, 5vw, 68px) 0 clamp(30px, 4vw, 48px);
      border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
    }
    .t-band__stat {
      flex: 1 1 150px; padding: clamp(18px, 2.2vw, 26px) clamp(16px, 2vw, 26px);
      border-left: 1px solid var(--faint);
    }
    .t-band__stat:first-child { border-left: 0; }
    .t-band__num {
      font-family: "Aeonik Extended", "Helvetica Neue", system-ui, sans-serif; font-weight: 700;
      font-size: clamp(30px, 4vw, 48px); line-height: 1; letter-spacing: -0.02em;
      color: var(--accent); font-variant-numeric: tabular-nums;
    }
    .t-band__slabel {
      margin-top: 12px; font-size: clamp(13px, 1.3vw, 15px); letter-spacing: 0;
      color: var(--fg); font-weight: 600;
    }
    .t-band__ssub { margin-top: 4px; font-size: clamp(12px, 1.15vw, 13px); color: var(--mut); font-variant-numeric: tabular-nums; }

    .t-band__colophon {
      font-size: clamp(12px, 1.2vw, 13px); letter-spacing: 0;
      color: var(--mut); font-weight: 400; font-variant-numeric: tabular-nums;
    }

    @media (max-width: 680px) {
      .t-band__row { grid-template-columns: 1fr; gap: 4px; }
      .t-band__stat { flex-basis: 50%; }
    }
  `,
  render(ed, skin) {
    const c = ed.content;
    const over = skin.mast.id === "over";

    const row = (when, whenClass, label, note, tag) => `
      <div class="t-band__row">
        <div class="t-band__when${whenClass ? " " + whenClass : ""}">${esc(when)}</div>
        <div class="t-band__what">
          <div class="t-band__lead">${esc(label)}${note ? ` <span class="t-band__note">— ${esc(note)}</span>` : ""}</div>
          ${tag ? `<div class="t-band__tag">${esc(tag)}</div>` : ""}
        </div>
      </div>`;

    const sec = (num, label, count, rows) => `
      <section class="t-band__sec">
        <h2 class="t-band__label"><span class="num">${num}</span><span>${esc(label)}</span><span class="ct">${count}</span></h2>
        ${rows}
      </section>`;

    const mast = `
      <header class="t-band__mast">
        <div class="t-band__kicker">Daily brief · No. ${ed.editionNo}</div>
        <h1 class="t-band__wordmark">GAIA</h1>
        <div class="t-band__date">${esc(ed.weekday)}, ${ed.day} ${esc(ed.month)} ${ed.year} · ${esc(ed.time)}</div>
      </header>`;

    const style = `--band-h:${skin.height.h};--hue:${skin.hue.rot};--sat:${skin.hue.sat};--accent:${skin.hue.accent}`;

    return `<article class="t-band" data-mast="${skin.mast.id}" style="${style}">
      <div class="t-band__hero">
        <div class="t-band__band" style="background-image:url('${ed.assets.BAND}')"></div>
        ${over ? mast : ""}
      </div>
      <div class="t-band__body">
        ${over ? "" : mast}
        <p class="t-band__deck">${esc(ed.deck)}</p>
        <div class="t-band__sections">
          ${sec("01", "Today", c.today.length, c.today.map((it) => row(todayWhen(it), null, it.label, it.note, it.tag)).join(""))}
          ${sec("02", "While you slept", c.overnight.length, c.overnight.map((it) => row(clockAMPM(it.t24), null, it.label, it.note, it.tag)).join(""))}
          ${sec("03", "Needs your call", c.decisions.length, c.decisions.map((it) => row(it.verb, "verb", it.label, it.note, null)).join(""))}
        </div>
        <div class="t-band__stats">
          <div class="t-band__stat">
            <div class="t-band__num">${c.stats.done}</div>
            <div class="t-band__slabel">Completed</div>
            <div class="t-band__ssub">You ${c.stats.you} · GAIA ${c.stats.gaia}</div>
          </div>
          <div class="t-band__stat">
            <div class="t-band__num">${c.stats.mail}</div>
            <div class="t-band__slabel">Email handled</div>
          </div>
          <div class="t-band__stat">
            <div class="t-band__num">${esc(c.stats.focus)}</div>
            <div class="t-band__slabel">Focus today</div>
          </div>
        </div>
        <div class="t-band__colophon">Edition No. ${ed.editionNo} · Generated ${esc(ed.time)} by GAIA</div>
      </div>
    </article>`;
  },
});

/* ===========================================================================
   2. playfair — a Playfair Display frontispiece. Ivory, ink, one accent.
   =========================================================================== */
EXPLORER.register({
  id: "playfair",
  name: "Playfair Frontispiece",
  axes: {
    // Ground carries a curated gilt accent tuned to its own contrast, so the
    // accent can never clash — it is a property of the ground, not a free axis.
    // One light frontispiece (ivory) + three jewel tones in the luxury tradition.
    ground: [
      {
        id: "ivory",
        label: "Ivory",
        paper: "#f7f3ea",
        ink: "#1b1916",
        mut: "#726c61",
        line: "rgba(27,25,22,0.22)",
        faint: "rgba(27,25,22,0.12)",
        accent: "#9a7b2d",
        ghost: "0.05",
      },
      {
        id: "emerald",
        label: "Emerald",
        paper: "#0e3a2b",
        ink: "#eee7d6",
        mut: "#94a89d",
        line: "rgba(238,231,214,0.24)",
        faint: "rgba(238,231,214,0.12)",
        accent: "#c9a552",
        ghost: "0.06",
      },
      {
        id: "burgundy",
        label: "Burgundy",
        paper: "#3d1420",
        ink: "#ecdcc0",
        mut: "#bd9d88",
        line: "rgba(236,220,192,0.24)",
        faint: "rgba(236,220,192,0.12)",
        accent: "#cba24c",
        ghost: "0.06",
      },
      {
        id: "navy",
        label: "Midnight navy",
        paper: "#101f3a",
        ink: "#ece4d2",
        mut: "#96a2b6",
        line: "rgba(236,228,210,0.24)",
        faint: "rgba(236,228,210,0.12)",
        accent: "#caa64e",
        ghost: "0.06",
      },
    ],
    mast: [
      { id: "italic", label: "Italic", style: "italic", weight: "500" },
      { id: "roman", label: "Roman", style: "normal", weight: "700" },
    ],
    // The single gilt touch (the edition numeral), on or off — the colour itself
    // is the ground's curated accent, so every pairing is safe by construction.
    accent: [
      { id: "gilt", label: "Gilt", on: true },
      { id: "plain", label: "Unadorned", on: false },
    ],
    rule: [
      { id: "hair", label: "Hairline", a: "1px", b: "0px" },
      { id: "duo", label: "Thick-thin", a: "3px", b: "1px" },
    ],
  },
  css: `
    .t-playfair {
      box-sizing: border-box;
      width: 100%;
      min-height: 1360px;
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: "Iowan Old Style", "Palatino", "Charter", Georgia, serif;
      -webkit-font-smoothing: antialiased;
      overflow: hidden;
    }
    .t-playfair * { box-sizing: border-box; }
    .t-playfair__wrap {
      max-width: 940px; margin: 0 auto;
      padding: clamp(48px, 7vw, 108px) clamp(28px, 6vw, 96px) clamp(56px, 7vw, 96px);
    }

    .t-playfair__top {
      display: flex; align-items: center; justify-content: center; gap: 14px;
      margin: 0 0 clamp(30px, 4vw, 52px);
      font-size: clamp(10px, 1.2vw, 12px); letter-spacing: 0.42em; text-transform: uppercase;
      color: var(--mut); font-variant-numeric: tabular-nums;
    }
    .t-playfair__top .em { color: var(--accent); }
    .t-playfair__top .hr { flex: 1 1 auto; height: 0; border-top: 1px solid var(--line); }

    /* the one theatrical move: an enormous ghosted edition numeral straddling the masthead */
    .t-playfair__hero { position: relative; }
    .t-playfair__ghost {
      position: absolute; left: 50%; top: 50%; transform: translate(-50%, -52%);
      z-index: 0; pointer-events: none; user-select: none; white-space: nowrap;
      font-family: "Playfair Display", Georgia, serif; font-weight: 700;
      font-size: clamp(240px, 41vw, 560px); line-height: 0.8; letter-spacing: -0.03em;
      color: var(--ink); opacity: var(--ghost); font-variant-numeric: lining-nums;
    }
    .t-playfair__mast {
      position: relative; z-index: 1;
      margin: 0; text-align: center;
      font-family: "Playfair Display", Georgia, serif;
      font-style: var(--mast-style); font-weight: var(--mast-weight);
      font-size: clamp(56px, 11vw, 146px); line-height: 0.98; letter-spacing: -0.01em;
    }
    .t-playfair__rule { margin: clamp(22px, 3vw, 40px) 0 clamp(10px, 1.4vw, 16px); border-top: var(--rule-a) solid var(--ink); }
    .t-playfair__rule::after { content: ""; display: block; margin-top: 4px; border-top: var(--rule-b) solid var(--ink); }

    .t-playfair__deck {
      margin: 0 auto clamp(46px, 6vw, 80px); max-width: 30ch; text-align: center;
      font-family: "Playfair Display", Georgia, serif; font-style: italic; font-weight: 500;
      font-size: clamp(21px, 3vw, 32px); line-height: 1.34;
    }

    .t-playfair__sec { margin: 0 0 clamp(40px, 5vw, 64px); }
    .t-playfair__sechead {
      display: flex; align-items: baseline; gap: 16px;
      margin: 0 0 clamp(14px, 1.8vw, 22px); padding-bottom: clamp(8px, 1vw, 12px);
      border-bottom: 1px solid var(--line);
    }
    .t-playfair__numeral {
      font-family: "Playfair Display", Georgia, serif; font-weight: 700;
      font-size: clamp(20px, 2.4vw, 28px); line-height: 1; letter-spacing: 0.02em;
    }
    .t-playfair__seclabel {
      font-size: clamp(11px, 1.2vw, 13px); letter-spacing: 0.32em; text-transform: uppercase;
      color: var(--mut);
    }
    .t-playfair__count { margin-left: auto; font-size: clamp(11px, 1.2vw, 13px); letter-spacing: 0.2em; color: var(--mut); font-variant-numeric: tabular-nums; }

    .t-playfair__item {
      display: grid; grid-template-columns: clamp(84px, 10vw, 128px) 1fr; gap: clamp(14px, 2.4vw, 32px);
      padding: clamp(12px, 1.6vw, 18px) 0; border-top: 1px solid var(--faint);
    }
    .t-playfair__item:first-of-type { border-top: 0; }
    .t-playfair__when {
      font-family: "Playfair Display", Georgia, serif; font-weight: 500;
      font-size: clamp(15px, 1.8vw, 19px); font-variant-numeric: tabular-nums lining-nums; padding-top: 1px;
    }
    .t-playfair__when.verb {
      font-family: "Iowan Old Style", Palatino, Georgia, serif; font-size: clamp(10px, 1.1vw, 12px);
      letter-spacing: 0.22em; text-transform: uppercase; color: var(--mut); font-weight: 400;
    }
    .t-playfair__text { font-size: clamp(15px, 1.75vw, 19px); line-height: 1.5; }
    .t-playfair__note { color: var(--mut); font-style: italic; }
    .t-playfair__minitag { display: block; margin-top: 6px; font-size: 10px; letter-spacing: 0.24em; text-transform: uppercase; color: var(--mut); }

    .t-playfair__stats {
      display: flex; flex-wrap: wrap; justify-content: space-between; gap: clamp(20px, 3vw, 40px);
      margin: clamp(46px, 6vw, 78px) 0 clamp(30px, 4vw, 46px);
      padding: clamp(22px, 3vw, 34px) 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
    }
    .t-playfair__stat { text-align: center; flex: 1 1 120px; }
    .t-playfair__snum {
      font-family: "Playfair Display", Georgia, serif; font-weight: 700;
      font-size: clamp(34px, 4.6vw, 56px); line-height: 1; font-variant-numeric: tabular-nums lining-nums;
    }
    .t-playfair__slabel { margin-top: 12px; font-size: clamp(10px, 1.1vw, 12px); letter-spacing: 0.26em; text-transform: uppercase; color: var(--mut); }
    .t-playfair__ssub { margin-top: 3px; font-size: clamp(10px, 1.1vw, 12px); color: var(--mut); font-style: italic; }

    .t-playfair__colophon {
      text-align: center; font-size: clamp(10px, 1.1vw, 12px); letter-spacing: 0.28em;
      text-transform: uppercase; color: var(--mut); font-variant-numeric: tabular-nums;
    }

    @media (max-width: 640px) {
      .t-playfair__item { grid-template-columns: 1fr; gap: 4px; }
      .t-playfair__stat { flex-basis: 40%; }
    }
  `,
  render(ed, skin) {
    const c = ed.content;
    const numerals = ["I", "II", "III"];

    const item = (when, whenClass, text, note, tag) => `
      <div class="t-playfair__item">
        <div class="t-playfair__when${whenClass ? " " + whenClass : ""}">${esc(when)}</div>
        <div class="t-playfair__text">
          ${esc(text)}${note ? ` <span class="t-playfair__note">— ${esc(note)}</span>` : ""}
          ${tag ? `<span class="t-playfair__minitag">${esc(tag)}</span>` : ""}
        </div>
      </div>`;

    const sec = (i, label, count, items) => `
      <section class="t-playfair__sec">
        <div class="t-playfair__sechead">
          <span class="t-playfair__numeral">${numerals[i]}</span>
          <span class="t-playfair__seclabel">${esc(label)}</span>
          <span class="t-playfair__count">${count}</span>
        </div>
        ${items}
      </section>`;

    const style =
      `--paper:${skin.ground.paper};--ink:${skin.ground.ink};--mut:${skin.ground.mut};` +
      `--line:${skin.ground.line};--faint:${skin.ground.faint};--ghost:${skin.ground.ghost};` +
      `--mast-style:${skin.mast.style};--mast-weight:${skin.mast.weight};` +
      `--accent:${skin.accent.on ? skin.ground.accent : skin.ground.ink};--rule-a:${skin.rule.a};--rule-b:${skin.rule.b}`;

    return `<article class="t-playfair" style="${style}">
      <div class="t-playfair__wrap">
        <div class="t-playfair__top">
          <span class="hr"></span>
          <span>Vol. I</span>
          <span class="em">№ ${ed.editionNo}</span>
          <span>${esc(ed.dateLong)}</span>
          <span class="hr"></span>
        </div>
        <div class="t-playfair__hero">
          <div class="t-playfair__ghost" aria-hidden="true">${ed.editionNo}</div>
          <h1 class="t-playfair__mast">The ${esc(ed.weekday)} Brief</h1>
        </div>
        <div class="t-playfair__rule"></div>
        <p class="t-playfair__deck">${esc(ed.deck)}</p>

        ${sec(0, "The day ahead", c.today.length, c.today.map((it) => item(todayWhen(it), null, it.label, it.note, it.tag)).join(""))}
        ${sec(1, "While you slept", c.overnight.length, c.overnight.map((it) => item(clockAMPM(it.t24), null, it.label, it.note, it.tag)).join(""))}
        ${sec(2, "For your decision", c.decisions.length, c.decisions.map((it) => item(it.verb, "verb", it.label, it.note, null)).join(""))}

        <div class="t-playfair__stats">
          <div class="t-playfair__stat">
            <div class="t-playfair__snum">${c.stats.done}</div>
            <div class="t-playfair__slabel">Completed</div>
            <div class="t-playfair__ssub">you ${c.stats.you}, gaia ${c.stats.gaia}</div>
          </div>
          <div class="t-playfair__stat">
            <div class="t-playfair__snum">${c.stats.mail}</div>
            <div class="t-playfair__slabel">Email handled</div>
          </div>
          <div class="t-playfair__stat">
            <div class="t-playfair__snum">${esc(c.stats.focus)}</div>
            <div class="t-playfair__slabel">Focus today</div>
          </div>
        </div>
        <div class="t-playfair__colophon">Edition № ${ed.editionNo} · Set by GAIA at ${esc(ed.time)}</div>
      </div>
    </article>`;
  },
});

/* ===========================================================================
   3. postal — an airmail envelope on a desk, with the brief as a letter.
   =========================================================================== */
EXPLORER.register({
  id: "postal",
  name: "Air Mail",
  axes: {
    // Each city carries an iconic public-domain artwork that reads clearly at stamp
    // size, localized air-mail etiquette, a plausible denomination + engraved-frame
    // colour, and ONE curated non-circular extra mark (customs label / express box).
    city: [
      {
        id: "tokyo",
        label: "Tokyo · Great Wave",
        src: "STAMP_TOKYO",
        city: "TOKYO",
        air: "航空便",
        airSub: "Par Avion",
        denom: "¥110",
        frame: "#9c3b34",
        extra: { kind: "customs", code: "CN 22", sub: "税関 · Customs" },
      },
      {
        id: "london",
        label: "London · Whistler nocturne",
        src: "STAMP_LONDON",
        city: "LONDON",
        air: "By Air Mail",
        airSub: "Par Avion",
        denom: "£1.25",
        frame: "#2f5233",
        extra: { kind: "express", text: "Express" },
      },
      {
        id: "newyork",
        label: "New York · harbour view",
        src: "STAMP_NEWYORK",
        city: "NEW YORK",
        air: "By Air Mail",
        airSub: "Par Avion",
        denom: "$1.50",
        frame: "#26467a",
        extra: { kind: "express", text: "Express Mail" },
      },
      {
        id: "paris",
        label: "Paris · Moulin Rouge",
        src: "STAMP_PARIS",
        city: "PARIS",
        air: "Par Avion",
        airSub: "By Air Mail",
        denom: "€1,20",
        frame: "#8c2f4a",
        extra: { kind: "customs", code: "CN 22", sub: "Douane · Customs" },
      },
      {
        id: "rome",
        label: "Rome · Piranesi Colosseum",
        src: "STAMP_ROME",
        city: "ROMA",
        air: "Via Aerea",
        airSub: "Par Avion",
        denom: "€1,25",
        frame: "#2f6b46",
        extra: { kind: "express", text: "Espresso" },
      },
      {
        id: "venice",
        label: "Venice · Grand Canal",
        src: "STAMP_VENICE",
        city: "VENEZIA",
        air: "Via Aerea",
        airSub: "Par Avion",
        denom: "€1,15",
        frame: "#7a2f2f",
        extra: { kind: "customs", code: "CN 22", sub: "Dogana · Customs" },
      },
    ],
    paper: [
      {
        id: "manila",
        label: "Kraft manila",
        env: "#d9c79d",
        ink: "#3b3222",
        tint: "rgba(120,96,40,0.08)",
      },
      {
        id: "laid",
        label: "Cream laid",
        env: "#efe6d1",
        ink: "#332f27",
        tint: "rgba(90,70,30,0.05)",
      },
      {
        id: "airmail",
        label: "Airmail white",
        env: "#f6f4ec",
        ink: "#2b2a26",
        tint: "rgba(40,60,120,0.04)",
      },
    ],
    ink: [
      { id: "black", label: "Black", c: "#2a2721" },
      { id: "red", label: "Faded red", c: "#a2392e" },
    ],
  },
  css: `
    .t-postal {
      box-sizing: border-box;
      width: 100%;
      min-height: 1560px;
      margin: 0;
      padding: clamp(40px, 5vw, 92px) clamp(20px, 4vw, 70px) clamp(60px, 7vw, 110px);
      background-color: #23262a;
      background-image:
        radial-gradient(120% 90% at 50% 0%, rgba(255,255,255,0.05), rgba(0,0,0,0) 60%),
        repeating-linear-gradient(94deg, rgba(0,0,0,0.10) 0 2px, rgba(255,255,255,0.012) 2px 5px);
      font-family: "American Typewriter", "Courier New", Courier, monospace;
      overflow: hidden;
    }
    .t-postal * { box-sizing: border-box; }
    .t-postal__scene { max-width: 1000px; margin: 0 auto; }

    /* ---------- envelope ---------- */
    .t-postal__env {
      position: relative; width: 100%;
      padding: 13px; transform: rotate(-0.5deg);
      background:
        repeating-linear-gradient(-52deg,
          #c33a30 0 11px, #f4f1e8 11px 21px,
          #2f5c9e 21px 32px, #f4f1e8 32px 42px);
      box-shadow: 0 2px 2px rgba(0,0,0,0.22), 0 26px 46px rgba(0,0,0,0.4);
    }
    .t-postal__face {
      position: relative; width: 100%; height: clamp(400px, 46vw, 560px);
      background-color: var(--env);
      background-image: linear-gradient(var(--tint), var(--tint));
      color: var(--env-ink);
      overflow: hidden;
    }
    .t-postal__face::after {
      /* the envelope flap seam */
      content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 46%;
      background: linear-gradient(180deg, rgba(0,0,0,0) 0%, var(--tint) 100%);
      border-top: 1px solid rgba(0,0,0,0.08);
      clip-path: polygon(0 100%, 50% 0, 100% 100%);
      opacity: 0.5; pointer-events: none;
    }

    .t-postal__return {
      position: absolute; top: clamp(20px, 3vw, 34px); left: clamp(22px, 3.4vw, 40px);
      font-size: clamp(10px, 1.15vw, 12px); line-height: 1.5; letter-spacing: 0.04em;
      text-transform: uppercase; opacity: 0.85;
    }
    .t-postal__avion {
      position: absolute; top: clamp(84px, 10vw, 116px); left: clamp(22px, 3.4vw, 40px);
      border: 1.5px solid #2f5c9e; color: #2f5c9e;
      padding: 3px 9px; font-size: clamp(9px, 1vw, 11px); letter-spacing: 0.24em;
      text-transform: uppercase; transform: rotate(-0.5deg);
    }
    .t-postal__avion b { display: block; color: #c33a30; letter-spacing: 0.2em; font-weight: normal; font-size: 0.85em; }

    .t-postal__addr {
      position: absolute; left: clamp(24px, 8vw, 132px); top: 54%; transform: translateY(-40%);
      font-size: clamp(13px, 1.7vw, 18px); line-height: 1.85; letter-spacing: 0.05em;
    }
    .t-postal__addr .lab { font-size: 0.7em; letter-spacing: 0.2em; opacity: 0.6; }
    .t-postal__addr .to { font-size: 1.24em; letter-spacing: 0.08em; }
    .t-postal__addr .re { text-transform: uppercase; }
    .t-postal__addr .meta { font-size: 0.78em; opacity: 0.72; letter-spacing: 0.12em; margin-top: 4px; font-variant-numeric: tabular-nums; }
    .t-postal__addr .under { display: inline-block; min-width: 8em; border-bottom: 1px solid currentColor; opacity: 0.4; margin-top: 10px; }

    /* ---------- postage stamp: engraved vignette, perforated edge ---------- */
    .t-postal__stamp {
      position: absolute; top: clamp(20px, 2.6vw, 30px); right: clamp(20px, 2.8vw, 34px);
      width: clamp(150px, 17.5vw, 196px); aspect-ratio: 7 / 5; padding: 6px;
      transform: rotate(1.6deg);
      background: #fbfaf4;
      filter: drop-shadow(0 1px 1.5px rgba(0,0,0,0.32));
      /* even round-notch perforations: hole centres pinned to the paper edge, then
         a solid inner panel unions in so only the margin ring keeps the teeth. */
      -webkit-mask:
        radial-gradient(circle 4px at 6.5px 6.5px, #0000 72%, #000 74%) -6.5px -6.5px / 13px 13px,
        linear-gradient(#000 0 0) 50% / calc(100% - 12px) calc(100% - 12px) no-repeat;
      -webkit-mask-composite: source-over;
      mask:
        radial-gradient(circle 4px at 6.5px 6.5px, #0000 72%, #000 74%) -6.5px -6.5px / 13px 13px,
        linear-gradient(#000 0 0) 50% / calc(100% - 12px) calc(100% - 12px) no-repeat;
      mask-composite: add;
    }
    .t-postal__stamp-panel {
      position: relative; width: 100%; height: 100%; overflow: hidden;
      background-size: cover; background-position: center;
      filter: saturate(0.94) contrast(1.03);
    }
    /* fine engraved-style double keyline inset from the panel edge */
    .t-postal__stamp-frame {
      position: absolute; inset: 4px; z-index: 1; pointer-events: none;
      border: 1px solid var(--frame);
      box-shadow: inset 0 0 0 1px rgba(251,250,244,0.6);
    }
    /* country / service line printed on the top engraved panel */
    .t-postal__stamp-country {
      position: absolute; top: 0; left: 0; right: 0; z-index: 2;
      background: var(--frame); color: #fbfaf4;
      font-family: "American Typewriter", "Courier New", monospace; font-weight: bold;
      font-size: clamp(6px, 0.8vw, 8.5px); letter-spacing: 0.09em; text-transform: uppercase;
      text-align: center; padding: 3px 6px; white-space: nowrap;
      overflow: hidden; text-overflow: ellipsis;
    }
    /* denomination cartouche, one corner */
    .t-postal__stamp-denom {
      position: absolute; right: 0; bottom: 0; z-index: 2;
      background: var(--frame); color: #fbfaf4;
      font-family: "Playfair Display", Georgia, serif; font-weight: 700;
      font-size: clamp(12px, 1.5vw, 17px); line-height: 1;
      padding: 3px 7px 4px; letter-spacing: 0.01em;
      font-variant-numeric: lining-nums; white-space: nowrap;
    }

    /* ---------- one curated extra mark, varies by country ---------- */
    .t-postal__extra {
      position: absolute; left: clamp(20px, 3.2vw, 40px); bottom: clamp(22px, 3vw, 40px); z-index: 3;
    }
    .t-postal__cn22 {
      transform: rotate(-2deg); background: #dde6d0; border: 1px solid #5f7048; color: #3f4d30;
      padding: 5px 10px 6px; min-width: clamp(108px, 13vw, 138px);
      font-family: "American Typewriter", "Courier New", monospace;
      box-shadow: 0 1px 1px rgba(0,0,0,0.16);
    }
    .t-postal__cn22 .code { font-size: clamp(12px, 1.5vw, 15px); letter-spacing: 0.14em; font-weight: bold; }
    .t-postal__cn22 .sub { font-size: clamp(8px, 0.95vw, 10px); letter-spacing: 0.05em; margin-top: 1px; opacity: 0.9; }
    .t-postal__express {
      transform: rotate(-3deg); background: #f7f2ea; border: 2px solid #b23020; color: #b23020;
      padding: 4px 13px; font-family: "American Typewriter", "Courier New", monospace;
      font-size: clamp(13px, 1.7vw, 18px); letter-spacing: 0.16em; font-weight: bold;
      text-transform: uppercase; box-shadow: 0 1px 1px rgba(0,0,0,0.18);
    }

    /* ---------- cancellation: circular datestamp + wavy killer bars ---------- */
    .t-postal__cancel {
      position: absolute; top: clamp(34px, 4vw, 58px); right: clamp(18px, 3vw, 44px);
      width: clamp(320px, 41vw, 484px); z-index: 4;
      transform: rotate(-6deg); color: var(--mark-ink);
      opacity: 0.82; pointer-events: none;
    }
    .t-postal__cancel svg { display: block; width: 100%; height: auto; }
    .t-postal__cancel text { font-family: "American Typewriter", "Courier New", monospace; }

    /* ---------- the letter ---------- */
    .t-postal__letter {
      position: relative; z-index: 2; width: 92%; margin: -46px auto 0;
      transform: rotate(0.4deg);
      background: #fbf9f1; color: #2a2822;
      padding: clamp(28px, 3.4vw, 48px) clamp(26px, 3.6vw, 52px) clamp(34px, 4vw, 54px);
      box-shadow: 0 2px 2px rgba(0,0,0,0.16), 0 22px 40px rgba(0,0,0,0.34);
      font-family: "Iowan Old Style", Charter, Georgia, serif;
    }
    .t-postal__lhead {
      display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 8px;
      padding-bottom: clamp(12px, 1.6vw, 18px); margin-bottom: clamp(16px, 2vw, 24px);
      border-bottom: 1px solid rgba(0,0,0,0.18);
    }
    .t-postal__lbrand { font-family: "American Typewriter", monospace; font-size: clamp(12px, 1.4vw, 15px); letter-spacing: 0.22em; text-transform: uppercase; }
    .t-postal__lmeta { font-family: "American Typewriter", monospace; font-size: clamp(10px, 1.15vw, 12px); letter-spacing: 0.1em; color: #6a6458; font-variant-numeric: tabular-nums; }
    .t-postal__ldeck { margin: 0 0 clamp(22px, 3vw, 34px); font-size: clamp(15px, 1.9vw, 21px); line-height: 1.4; font-style: italic; max-width: 40ch; }

    .t-postal__cols { display: grid; grid-template-columns: 1fr 1fr; gap: clamp(22px, 3vw, 44px); }
    .t-postal__block { break-inside: avoid; }
    .t-postal__block + .t-postal__block { margin-top: clamp(20px, 2.4vw, 30px); }
    .t-postal__blabel {
      margin: 0 0 clamp(9px, 1.2vw, 14px); padding-bottom: 5px;
      font-family: "American Typewriter", monospace; font-size: clamp(10px, 1.1vw, 12px);
      letter-spacing: 0.2em; text-transform: uppercase; color: #55503f;
      border-bottom: 1px solid rgba(0,0,0,0.12);
    }
    .t-postal__li { display: grid; grid-template-columns: clamp(52px, 6vw, 74px) 1fr; gap: 10px; padding: 6px 0; font-size: clamp(12px, 1.4vw, 14.5px); line-height: 1.42; }
    .t-postal__li .w { font-family: "American Typewriter", monospace; font-size: 0.86em; letter-spacing: 0.04em; color: #55503f; font-variant-numeric: tabular-nums; padding-top: 1px; }
    .t-postal__li .w.verb { text-transform: uppercase; letter-spacing: 0.12em; font-size: 0.76em; }
    .t-postal__li .nt { color: #7a745f; font-style: italic; }
    .t-postal__li .tg { display: block; margin-top: 3px; font-family: "American Typewriter", monospace; font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase; color: #8a836c; }

    .t-postal__stats {
      display: flex; flex-wrap: wrap; gap: clamp(14px, 2vw, 30px); margin-top: clamp(10px, 1.4vw, 16px);
      padding-top: clamp(10px, 1.4vw, 14px); border-top: 1px solid rgba(0,0,0,0.12);
      font-family: "American Typewriter", monospace; font-variant-numeric: tabular-nums;
    }
    .t-postal__stats .s { font-size: clamp(11px, 1.3vw, 13px); letter-spacing: 0.04em; }
    .t-postal__stats .s b { font-weight: normal; font-size: 1.5em; }
    .t-postal__lfoot {
      margin-top: clamp(22px, 3vw, 34px); padding-top: clamp(12px, 1.6vw, 16px);
      border-top: 1px solid rgba(0,0,0,0.18);
      font-family: "American Typewriter", monospace; font-size: clamp(10px, 1.1vw, 12px);
      letter-spacing: 0.1em; color: #6a6458; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;
    }

    @media (max-width: 720px) {
      .t-postal__cols { grid-template-columns: 1fr; }
      .t-postal__cancel { right: clamp(8px, 3vw, 40px); }
    }
  `,
  render(ed, skin) {
    const c = ed.content;
    const stampArt = ed.assets[skin.city.src];
    const cancel = postalCancel(ed, skin);

    const li = (when, whenClass, text, note, tag) => `
      <div class="t-postal__li">
        <span class="w${whenClass ? " " + whenClass : ""}">${esc(when)}</span>
        <span class="tx">${esc(text)}${note ? ` <span class="nt">— ${esc(note)}</span>` : ""}${tag ? `<span class="tg">${esc(tag)}</span>` : ""}</span>
      </div>`;

    const x = skin.city.extra;
    const extra =
      x.kind === "customs"
        ? `<div class="t-postal__cn22"><div class="code">${esc(x.code)}</div><div class="sub">${esc(x.sub)}</div></div>`
        : `<div class="t-postal__express">${esc(x.text)}</div>`;

    const style =
      `--env:${skin.paper.env};--env-ink:${skin.paper.ink};--tint:${skin.paper.tint};` +
      `--mark-ink:${skin.ink.c};--frame:${skin.city.frame}`;

    return `<article class="t-postal" style="${style}">
      <div class="t-postal__scene">
        <div class="t-postal__env">
          <div class="t-postal__face">
            <div class="t-postal__return">GAIA Post · Personal Desk<br>Daily Brief Service</div>
            <div class="t-postal__avion">${esc(skin.city.air)}<b>${esc(skin.city.airSub)}</b></div>

            <div class="t-postal__addr">
              <div class="lab">TO</div>
              <div class="to">YOU</div>
              <div class="re">Re: Your ${esc(ed.weekday)}</div>
              <div class="meta">Edition No. ${ed.editionNo} · ${esc(ed.dateLong)}</div>
              <div class="under"></div>
            </div>

            <div class="t-postal__stamp">
              <div class="t-postal__stamp-panel" style="background-image:url('${stampArt}')">
                <div class="t-postal__stamp-frame"></div>
                <div class="t-postal__stamp-country">GAIA Post · ${esc(skin.city.city)}</div>
                <div class="t-postal__stamp-denom">${esc(skin.city.denom)}</div>
              </div>
            </div>

            <div class="t-postal__extra">${extra}</div>

            <div class="t-postal__cancel">${cancel}</div>
          </div>
        </div>

        <div class="t-postal__letter">
          <div class="t-postal__lhead">
            <div class="t-postal__lbrand">GAIA — Daily Brief</div>
            <div class="t-postal__lmeta">${esc(ed.dateLong)} · No. ${ed.editionNo} · ${esc(ed.time)}</div>
          </div>
          <p class="t-postal__ldeck">${esc(ed.deck)}</p>

          <div class="t-postal__cols">
            <div class="t-postal__block">
              <h3 class="t-postal__blabel">Today</h3>
              ${c.today.map((it) => li(todayWhen(it), null, it.label, it.note, it.tag)).join("")}
              <div class="t-postal__block">
                <h3 class="t-postal__blabel">Needs your call</h3>
                ${c.decisions.map((it) => li(it.verb, "verb", it.label, it.note, null)).join("")}
              </div>
            </div>
            <div class="t-postal__block">
              <h3 class="t-postal__blabel">While you slept</h3>
              ${c.overnight.map((it) => li(clockAMPM(it.t24), null, it.label, it.note, it.tag)).join("")}
              <div class="t-postal__stats">
                <span class="s"><b>${c.stats.done}</b> done <span class="nt">(you ${c.stats.you}, gaia ${c.stats.gaia})</span></span>
                <span class="s"><b>${c.stats.mail}</b> mail</span>
                <span class="s"><b>${esc(c.stats.focus)}</b> focus</span>
              </div>
            </div>
          </div>

          <div class="t-postal__lfoot">
            <span>Posted ${esc(ed.time)} · GAIA Post</span>
            <span>Edition No. ${ed.editionNo}</span>
          </div>
        </div>
      </div>
    </article>`;
  },
});
