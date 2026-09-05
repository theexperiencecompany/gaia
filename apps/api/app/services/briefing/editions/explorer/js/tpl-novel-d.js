/* ============================================================================
 * tpl-novel-d.js — "exhibition" template for the daily-brief explorer.
 *
 *   exhibition — a museum exhibition poster in which the ARTWORK is the whole
 *                event. A full-bleed crop of the day's painting fills ~70–80%
 *                of the poster; the exhibition title (the edition, "The
 *                <weekday> Brief") does museum-poster work in one of two type
 *                schools; a slim wall-caption credit, a "one day only" date
 *                line and a quiet PROGRAMME footer carry the day's facts
 *                without ever competing with the picture.
 *
 * Text-over-art legibility WITHOUT scrims is solved swap-safely, i.e. without
 * depending on where this particular painting happens to be dark:
 *   - placement "over"  → the title is knocked over the picture with
 *       mix-blend-mode:difference. Difference inverts the title against
 *       whatever pixels sit behind it, so it self-contrasts on light sky and
 *       dark cypress alike — it depends on nothing about the image. Duotone
 *       treatments push the picture toward two tones, which only sharpens it.
 *   - placement "band" → the title sits reversed out of an opaque Stedelijk
 *       type band. A solid block, not a scrim: it never dims the art.
 *
 * The three treatments (full colour / warm duotone / cool duotone) are the
 * ONLY image-colour-dependent thing in the file, exactly as required for a
 * pool of paintings that rotates daily. Duotone is done entirely with layered
 * background-blend-mode (saturation → grayscale, lighten → shadow tone,
 * darken → highlight tone) so it works on any source image.
 *
 * One IIFE so local helpers never collide with sibling modules. Skin values
 * arrive ONLY as inline custom properties on the <article>; every selector is
 * scoped to .t-exhibition. Deterministic: no Date.now / Math.random.
 * ==========================================================================*/
(() => {
  /* ---- text helpers ---------------------------------------------------- */
  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }
  function caps(s) {
    return esc(String(s).toUpperCase());
  }

  /* ---- artwork background ---------------------------------------------
     Build the layered `background-image` / `background-blend-mode` for a
     treatment. Colour is the plain picture; the duotones map luminance onto a
     two-tone ramp entirely in compositing, stack top→bottom:
       shadow tone   (screen)     → lifts the blacks to the dark tone
       highlight tone (multiply)  → scales the whites down to the light tone
       mid grey      (saturation) → strips the picture's own colour first
       the picture   (normal)
     multiply-then-screen interpolates the mid-tones, so the whole tonal range
     lands on the ramp (not just the pure black/white extremes). Every layer is
     sized/positioned by the shared --art-size / --art-pos, but the gradient
     layers are solids so only the picture layer is really cropped. Swap-safe:
     the two duotone hexes are imposed, never sampled. */
  function artStyle(src, treat, crop) {
    const url = `url('${src}')`;
    const pos = crop.pos;
    if (treat.duo) {
      const shadow = `linear-gradient(${treat.shadow},${treat.shadow})`;
      const hi = `linear-gradient(${treat.hi},${treat.hi})`;
      const g = "linear-gradient(#808080,#808080)";
      return (
        `--art-image:${shadow},${hi},${g},${url};` +
        `--art-size:auto,auto,auto,${crop.zoom};` +
        `--art-pos:${pos};` +
        `--art-blend:screen,multiply,saturation,normal;` +
        `--art-filter:contrast(1.04);`
      );
    }
    return (
      `--art-image:${url};` +
      `--art-size:${crop.zoom};` +
      `--art-pos:${pos};` +
      `--art-blend:normal;` +
      `--art-filter:saturate(1.06) contrast(1.02);`
    );
  }

  /* ---- programme rows -------------------------------------------------- */
  function progItem(timeText, label, note, tag) {
    return (
      `<li class="t-exhibition__ev">` +
      `<span class="t-exhibition__ev-time">${timeText}</span>` +
      `<span class="t-exhibition__ev-body">` +
      `<span class="t-exhibition__ev-label">${esc(label)}</span>` +
      (note ? `<span class="t-exhibition__ev-note">${esc(note)}</span>` : "") +
      `<span class="t-exhibition__ev-tag">${caps(tag)}</span>` +
      `</span></li>`
    );
  }
  function decItem(verb, label, note) {
    return (
      `<li class="t-exhibition__ev t-exhibition__ev--dec">` +
      `<span class="t-exhibition__ev-time">${esc(verb)}</span>` +
      `<span class="t-exhibition__ev-body">` +
      `<span class="t-exhibition__ev-label">${esc(label)}</span>` +
      (note ? `<span class="t-exhibition__ev-note">${esc(note)}</span>` : "") +
      `</span></li>`
    );
  }
  function col(head, body) {
    return (
      `<section class="t-exhibition__col">` +
      `<h3 class="t-exhibition__col-h">${head}</h3>` +
      `<ul class="t-exhibition__list">${body}</ul>` +
      `</section>`
    );
  }

  const CSS = `
    .t-exhibition {
      width: 100%;
      margin: 0;
      box-sizing: border-box;
      background: var(--paper);
      color: var(--ink);
      font-family: "Helvetica Neue", Helvetica, Arial, system-ui, sans-serif;
      -webkit-font-smoothing: antialiased;
      overflow: hidden;
    }
    .t-exhibition * { box-sizing: border-box; }

    /* ---- the picture: full-bleed, cropped by the skin ------------------ */
    .t-exhibition__stage {
      position: relative;
      isolation: isolate;
      width: 100%;
      overflow: hidden;
    }
    .t-exhibition.place-over .t-exhibition__stage { aspect-ratio: 118 / 100; }
    .t-exhibition.place-band .t-exhibition__stage { aspect-ratio: 118 / 84; }

    .t-exhibition__art {
      position: absolute;
      inset: 0;
      z-index: 0;
      background-image: var(--art-image);
      background-size: var(--art-size);
      background-position: var(--art-pos);
      background-blend-mode: var(--art-blend);
      background-repeat: no-repeat;
      filter: var(--art-filter);
    }

    /* ---- title knocked over the picture (placement: over) -------------- */
    .t-exhibition__over {
      position: absolute;
      left: 0; right: 0; bottom: 0;
      z-index: 2;
      padding: 0 clamp(20px, 4vw, 60px) clamp(26px, 4.4vw, 64px);
      mix-blend-mode: difference;
      color: #ffffff;
    }

    .t-exhibition__kicker {
      margin: 0 0 clamp(10px, 1.4vw, 18px);
      font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-weight: 700;
      font-size: clamp(11px, 1.05vw, 14px);
      letter-spacing: 0.34em;
      text-transform: uppercase;
    }

    .t-exhibition__title {
      margin: 0;
      font-family: var(--title-face);
      font-weight: var(--title-weight);
      font-style: var(--title-style, normal);
      font-size: clamp(52px, 9.4vw, 124px);
      line-height: var(--title-leading);
      letter-spacing: var(--title-tracking);
      text-transform: uppercase;
    }
    .t-exhibition__title span { display: block; }

    /* ---- title in an opaque Stedelijk band (placement: band) ----------- */
    .t-exhibition__band {
      position: relative;
      z-index: 1;
      background: var(--band-bg);
      color: var(--band-ink);
      padding: clamp(22px, 3vw, 44px) clamp(20px, 4vw, 60px) clamp(26px, 3.4vw, 48px);
    }
    .t-exhibition__band .t-exhibition__kicker { color: var(--band-ink); opacity: 0.72; }
    .t-exhibition__band .t-exhibition__title { color: var(--band-ink); }

    /* ---- wall caption: the credit, set like a gallery label ------------ */
    .t-exhibition__caption {
      display: flex;
      flex-wrap: wrap;
      gap: 6px 18px;
      align-items: baseline;
      padding: clamp(14px, 1.7vw, 22px) clamp(20px, 4vw, 60px) 0;
      font-family: "SF Mono", Menlo, ui-monospace, monospace;
      font-size: clamp(10px, 0.92vw, 12px);
      letter-spacing: 0.04em;
      color: var(--ink-soft);
      font-variant-numeric: tabular-nums;
    }
    .t-exhibition__caption b { color: var(--ink); font-weight: 600; }
    .t-exhibition__caption .t-exhibition__dot { color: var(--ink-soft); }

    /* ---- gallery note (the deck) --------------------------------------- */
    .t-exhibition__note {
      margin: clamp(20px, 2.6vw, 34px) 0 0;
      padding: 0 clamp(20px, 4vw, 60px);
      max-width: 46ch;
      font-family: var(--title-face);
      font-style: italic;
      font-weight: 400;
      font-size: clamp(17px, 1.7vw, 23px);
      line-height: 1.35;
      color: var(--ink);
    }

    /* ---- programme footer ---------------------------------------------- */
    .t-exhibition__programme {
      padding: clamp(24px, 3vw, 40px) clamp(20px, 4vw, 60px) clamp(26px, 3.2vw, 44px);
    }
    .t-exhibition__prog-h {
      margin: 0 0 clamp(16px, 1.8vw, 22px);
      padding-bottom: clamp(9px, 1.1vw, 13px);
      border-bottom: 1.5px solid var(--ink);
      font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-weight: 700;
      font-size: clamp(11px, 1vw, 13px);
      letter-spacing: 0.3em;
      text-transform: uppercase;
    }
    .t-exhibition__cols {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: clamp(20px, 2.6vw, 40px);
    }
    .t-exhibition__col-h {
      margin: 0 0 12px;
      font-family: "SF Mono", Menlo, ui-monospace, monospace;
      font-weight: 600;
      font-size: 11px;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--ink-soft);
    }
    .t-exhibition__list { margin: 0; padding: 0; list-style: none; }
    .t-exhibition__ev {
      display: flex;
      gap: 12px;
      padding: 9px 0;
      border-top: 1px solid var(--rule);
    }
    .t-exhibition__ev:first-child { border-top: 0; padding-top: 0; }
    .t-exhibition__ev-time {
      flex: 0 0 auto;
      min-width: 52px;
      font-family: "SF Mono", Menlo, ui-monospace, monospace;
      font-size: 12px;
      letter-spacing: 0.02em;
      color: var(--ink);
      font-variant-numeric: tabular-nums;
    }
    .t-exhibition__ev--dec .t-exhibition__ev-time {
      color: var(--accent);
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.1em;
    }
    .t-exhibition__ev-body { display: block; }
    .t-exhibition__ev-label {
      display: block;
      font-size: 13px;
      line-height: 1.35;
      color: var(--ink);
    }
    .t-exhibition__ev--dec .t-exhibition__ev-label { font-weight: 600; }
    .t-exhibition__ev-note {
      display: block;
      margin-top: 2px;
      font-size: 11.5px;
      line-height: 1.35;
      color: var(--ink-soft);
    }
    .t-exhibition__ev-tag {
      display: inline-block;
      margin-top: 4px;
      font-family: "SF Mono", Menlo, ui-monospace, monospace;
      font-size: 9.5px;
      letter-spacing: 0.16em;
      color: var(--ink-soft);
    }

    .t-exhibition__stats {
      margin-top: clamp(20px, 2.4vw, 32px);
      padding-top: clamp(12px, 1.4vw, 18px);
      border-top: 1.5px solid var(--ink);
      font-family: "SF Mono", Menlo, ui-monospace, monospace;
      font-size: clamp(10px, 0.92vw, 12px);
      letter-spacing: 0.05em;
      color: var(--ink-soft);
      font-variant-numeric: tabular-nums;
    }
    .t-exhibition__stats b { color: var(--ink); font-weight: 600; }

    @media (max-width: 720px) {
      .t-exhibition__cols { grid-template-columns: 1fr; gap: clamp(18px, 4vw, 28px); }
    }
  `;

  const CROPS = [
    { id: "sky", label: "Sky & hills", pos: "50% 2%", zoom: "168%" },
    { id: "field", label: "Wheat field", pos: "46% 99%", zoom: "168%" },
    { id: "cypress", label: "The cypress", pos: "82% 46%", zoom: "182%" },
  ];

  const TREATMENTS = [
    { id: "color", label: "Full colour", duo: false },
    {
      id: "warm",
      label: "Warm duotone",
      duo: true,
      shadow: "#2a1608",
      hi: "#f3e2bd",
    },
    {
      id: "cool",
      label: "Cool duotone",
      duo: true,
      shadow: "#0d1a2e",
      hi: "#dbe6f2",
    },
  ];

  /* A neutral graphite duotone. Type knocked over the picture only reads
     crisply when the picture is tonal, so the full-colour treatment is shown
     tonally (graphite) in over-the-picture mode — a white difference-knockout
     over a two-tone image self-contrasts cleanly, whereas over full chroma it
     muddies into the paint's own hues. Full chroma is reserved for the plate
     layouts, where the title sits on its own opaque ground. */
  const GRAPHITE = { duo: true, shadow: "#1a1712", hi: "#efeae0" };

  /* Type schools as two museum traditions. The elegant high-contrast face
     (Didot/Bodoni) and the bold Swiss face (Helvetica) are genuinely
     different poster languages. */
  const DIDOT = {
    face: "Didot, 'Bodoni 72', 'Hoefler Text', Georgia, serif",
    weight: "400",
    style: "normal",
    leading: "0.98",
    tracking: "0.015em",
  };
  const HELVETICA = {
    face: "'Helvetica Neue', Helvetica, Arial, sans-serif",
    weight: "700",
    style: "normal",
    leading: "0.9",
    tracking: "-0.02em",
  };

  /* school × placement is a CURATED axis, not a free product. No scrim-free
     technique keeps thin, high-contrast type legible knocked over spatially-
     varying paint, so the elegant school always sets its title on the opaque
     Stedelijk plate. Only the heavy Swiss face rides the picture, knocked out
     with mix-blend-mode:difference — which self-contrasts against a tonal
     backdrop, swap-safe — and over-the-picture forces the art tonal (see
     GRAPHITE) so the knockout stays crisp. Every pairing is verified legible
     on every crop and treatment. */
  const TYPESETS = [
    {
      id: "didot-band",
      label: "Didot on the plate",
      placement: "band",
      type: DIDOT,
    },
    {
      id: "helvetica-band",
      label: "Helvetica on the plate",
      placement: "band",
      type: HELVETICA,
    },
    {
      id: "helvetica-over",
      label: "Helvetica over the picture",
      placement: "over",
      type: HELVETICA,
    },
  ];

  EXPLORER.register({
    id: "exhibition",
    name: "The Exhibition",
    axes: {
      crop: CROPS,
      treatment: TREATMENTS,
      typeset: TYPESETS,
    },
    css: CSS,
    render(ed, skin) {
      const { crop, treatment, typeset } = skin;
      const placement = typeset.placement;
      const type = typeset.type;
      const c = ed.content;
      const art = ed.art;

      /* palette — neutral gallery paper/ink + one restrained accent. Fixed,
         not sampled from the artwork. */
      const paper = "#f4f1ea";
      const ink = "#171512";
      const inkSoft = "#6f6a61";
      const rule = "#d8d2c6";
      const accent = "#b3402c";
      const bandBg = ink;
      const bandInk = paper;

      const titleLines = ["The", ed.weekday, "Brief"]
        .map((w) => `<span>${esc(w)}</span>`)
        .join("");
      const title = `<h1 class="t-exhibition__title">${titleLines}</h1>`;
      /* The kicker only rides the opaque plate, where small type is safe. In
         over-the-picture mode the image carries the big title alone and the
         date lives in the crisp wall caption below. */
      const kicker = `<p class="t-exhibition__kicker">One day only &middot; ${caps(ed.dateLong)}</p>`;

      const caption =
        `<div class="t-exhibition__caption">` +
        (placement === "over"
          ? `<b>One day only</b><span>${caps(ed.dateLong)}</span><span class="t-exhibition__dot">/</span>`
          : "") +
        `<b>${esc(art.artist)}</b>` +
        `<span>${esc(art.title)}, ${art.year}</span>` +
        `<span class="t-exhibition__dot">/</span>` +
        `<span>${esc(art.medium)}</span>` +
        `<span class="t-exhibition__dot">/</span>` +
        `<span>Edition N&ordm; ${ed.editionNo}</span>` +
        `</div>`;

      const today = c.today
        .map((it) => progItem(it.time || "EOD", it.label, it.note, it.tag))
        .join("");
      const overnight = c.overnight
        .map((it) => progItem(it.t24 || "", it.label, it.note, it.tag))
        .join("");
      const decisions = c.decisions
        .map((it) => decItem(it.verb, it.label, it.note))
        .join("");

      const s = c.stats;
      const stats =
        `<p class="t-exhibition__stats">` +
        `Yesterday <b>${s.done}</b> shipped &middot; you <b>${s.you}</b> / GAIA <b>${s.gaia}</b> &middot; ` +
        `<b>${s.mail}</b> emails handled &middot; <b>${s.focus}</b> of focus &middot; ` +
        `brief generated ${esc(ed.time)}` +
        `</p>`;

      const programme =
        `<div class="t-exhibition__programme">` +
        `<h2 class="t-exhibition__prog-h">Programme for the day</h2>` +
        `<div class="t-exhibition__cols">` +
        col("Today", today) +
        col("Overnight, while you slept", overnight) +
        col("Awaiting your decision", decisions) +
        `</div>` +
        stats +
        `</div>`;

      const style =
        `--paper:${paper};--ink:${ink};--ink-soft:${inkSoft};--rule:${rule};--accent:${accent};` +
        `--band-bg:${bandBg};--band-ink:${bandInk};` +
        `--title-face:${type.face};--title-weight:${type.weight};--title-style:${type.style};` +
        `--title-leading:${type.leading};--title-tracking:${type.tracking};` +
        artStyle(
          art.src,
          placement === "over" && !treatment.duo ? GRAPHITE : treatment,
          crop,
        );

      const stage =
        `<div class="t-exhibition__stage">` +
        `<div class="t-exhibition__art"></div>` +
        (placement === "over"
          ? `<div class="t-exhibition__over">${title}</div>`
          : "") +
        `</div>`;

      const band =
        placement === "band"
          ? `<div class="t-exhibition__band">${kicker}${title}</div>`
          : "";

      return (
        `<article class="t-exhibition place-${placement}" style="${style}">` +
        stage +
        band +
        caption +
        `<p class="t-exhibition__note">${esc(ed.deck)}</p>` +
        programme +
        `</article>`
      );
    },
  });
})();
