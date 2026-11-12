/* ============================================================================
   tpl-brand.js (round 2) — GAIA · Band and Playfair Frontispiece on a 540 px
   portrait canvas (export at 3x). Body 17 px or larger.
   Reading order: headline -> the brief's blocks as GAIA composed them -> stats.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const grain = (id, freq) =>
    `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  const WORDS = ["None", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"];
  // A count spelled as the page spells it: one to nine in words, the rest in figures.
  const spell = (n) => (n > 0 && n < WORDS.length ? WORDS[n] : String(n));
  const ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"];

  /* ==========================================================================
     GAIA · BAND — signature moves from the desktop original:
       the bands wallpaper as a tall header carrying a huge GAIA wordmark;
       a near-black field; numbered section heads with an accent numeral
       ("01 Today") and a count; time / label rows with an em-dash note and a
       tiny lowercase tag; a three-up figure row in the accent colour.
     Added detail: a soft light-leak where the bands meet the field, film
     grain on the dark field, a hairline grid under the figures.
     ======================================================================== */
  EXPLORER.register({
    id: "band",
    name: "GAIA · Band",
    axes: {
      hue: [
        { id: "azure", label: "azure (brand)", filter: "none", acc: "#4fb8ff" },
        { id: "jade", label: "jade", filter: "hue-rotate(-55deg) saturate(1.1)", acc: "#3ddc9a" },
        { id: "amber", label: "amber", filter: "hue-rotate(-160deg) saturate(1.25)", acc: "#ffbf3c" },
        { id: "coral", label: "coral", filter: "hue-rotate(165deg) saturate(1.2)", acc: "#ff8a6b" },
        { id: "violet", label: "violet", filter: "hue-rotate(68deg) saturate(1.1)", acc: "#b694ff" },
        { id: "pink", label: "pink", filter: "hue-rotate(118deg) saturate(1.15)", acc: "#ff7fc4" },
        { id: "red", label: "red", filter: "hue-rotate(145deg) saturate(1.35)", acc: "#ff6363" },
        { id: "teal", label: "teal", filter: "hue-rotate(-28deg) saturate(1.05)", acc: "#3fd8d0" },
        { id: "lime", label: "lime", filter: "hue-rotate(-128deg) saturate(1.15)", acc: "#c6e85c" },
      ],
      header: [
        { id: "tall", label: "tall band", h: "300px" },
        { id: "short", label: "short band", h: "220px" },
      ],
      field: [
        { id: "black", label: "near black", field: "#0d0e11", hair: "#25272d" },
        { id: "ink", label: "ink blue-black", field: "#0c1018", hair: "#222a38" },
      ],
    },
    css: `
.t-band { position: relative; isolation: isolate; box-sizing: border-box; width: 540px; background: var(--field); color: #f2f2f4; font: 400 17px/1.45 'TeX Gyre Heros', sans-serif; padding-bottom: 30px; }
.t-band * { box-sizing: border-box; margin: 0; padding: 0; }
.t-band .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: soft-light; opacity: .5; z-index: -1; }
.t-band .hd::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 1px; background: var(--acc); opacity: .55; box-shadow: 0 0 14px 2px var(--acc); }
.t-band .hd { position: relative; height: var(--h); overflow: hidden; }
.t-band .hd img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; object-position: 50% 70%; filter: var(--filter); }
.t-band .hd .k { position: absolute; left: 28px; top: 28px; font-size: 14px; font-weight: 600; color: #ffffff; letter-spacing: .02em; z-index: 1; }
.t-band .hd .mark { position: absolute; left: 24px; top: 50px; font: 700 104px/1 'Aeonik Extended', 'TeX Gyre Heros', sans-serif; color: #ffffff; letter-spacing: -.01em; z-index: 1; }
.t-band .hd .date { position: absolute; left: 28px; top: 166px; font-size: 15px; color: #ffffff; z-index: 1; }
.t-band .body { padding: 30px 28px 0; }
.t-band .deck { font-size: 27px; line-height: 1.28; letter-spacing: -.01em; font-weight: 500; padding-bottom: 26px; border-bottom: 1px solid var(--hair); }
.t-band section { padding: 30px 0 18px; }
.t-band section.rs { padding: 10px 0 8px; }
.t-band section + section { border-top: 1px solid var(--hair); }
.t-band h2 { font: 700 23.5px/28px 'Aeonik Extended', 'TeX Gyre Heros', sans-serif; letter-spacing: -.01em; }
.t-band .sub { font-size: 15px; color: #a3a5ad; margin-top: 6px; }
.t-band .sub b { color: var(--acc); font-weight: 700; }
.t-band .key { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 18px; font-size: 14px; font-weight: 700; color: #a3a5ad; margin-top: 12px; }
.t-band .key i { display: inline-block; width: 10px; height: 10px; margin-right: 7px; vertical-align: 0; }
.t-band .key i.ln { width: 16px; height: 0; border-top: 2.5px solid var(--acc); vertical-align: 3px; }
.t-band .key i.ln.dash { border-top: 2px dashed #f2f2f4; }
.t-band .plot { margin-top: 16px; }
.t-band .say { margin-top: 14px; font-size: 17px; line-height: 1.45; color: #d6d7dc; }
.t-band .q { font-size: 19px; line-height: 1.42; letter-spacing: -.005em; color: #f2f2f4; text-wrap: pretty; }
.t-band .tag { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 700; color: #8d9098; margin-top: 10px; }
.t-band .qlogo { width: 16px; height: 16px; }
.t-band { --rs-font: 'TeX Gyre Heros', sans-serif; --rs-font-h: 'Aeonik Extended', 'TeX Gyre Heros', sans-serif; --rs-ink: #f2f2f4; --rs-muted: #a3a5ad; --rs-acc: var(--acc); --rs-base: 15px; }
.t-band .figs { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); margin-top: 30px; border-top: 1px solid var(--hair); border-bottom: 1px solid var(--hair); }
.t-band .figs div { padding: 16px 14px; }
.t-band .figs div + div { border-left: 1px solid var(--hair); }
.t-band .figs b { display: block; font: 700 40px/1 'Aeonik Extended', 'TeX Gyre Heros', sans-serif; color: var(--acc); font-variant-numeric: tabular-nums; }
.t-band .figs span { display: block; font-size: 15px; font-weight: 600; margin-top: 8px; }
.t-band .figs small { display: block; font-size: 14px; color: #9fa1a8; }
.t-band .foot { margin-top: 18px; font-size: 14px; color: #8d9098; }
.t-band .src { margin-top: 8px; line-height: 1.5; }
.t-band .src .logos { display: flex; gap: 10px; margin-bottom: 8px; color: #c4c6cc; }
.t-band .src .xb-logo { width: 16px; height: 16px; }
`,
    render(ed, skin) {
      const B = EXPLORER.blocks;
      const INK = "#f2f2f4";
      const W = 484;
      const O = { mode: "color" };
      /* A data block is a band section of its own: an Aeonik head, a grey sub line, the picture. */
      const block = (kind, html) => `<section class="data" data-block="${kind}">${html}</section>`;
      const reading = (html) => `<section class="rs">${html}</section>`;
      const fills = (c) => (c.series.length > 1 ? [INK, "var(--acc)", "#8d9098"] : ["var(--acc)"]);
      const plot = (c) => {
        const st = { w: W, font: "TeX Gyre Heros", size: 14, weight: 700, valueWeight: 700, ink: INK, soft: "#8d9098", rule: "var(--hair)", ruleW: 1, base: "#3a3d45" };
        if (c.chart === "spark") return B.spark(c, { ...st, h: 60, line: "var(--acc)", lineW: 2.5, dot: 4 });
        if (c.chart === "line") return B.line(c, { ...st, h: 156, gutter: 30, dot: 4, lines: [{ color: "var(--acc)", width: 2.5 }, { color: INK, width: 2, dash: "5 4" }] });
        return B.bars(c, { ...st, h: 172, fills: fills(c), gapRatio: 0.42 });
      };
      const key = (c) => {
        if (c.series.length < 2) return "";
        const sw = c.chart === "line" ? (k) => `<i class="ln${k ? " dash" : ""}"></i>` : (k) => `<i style="background:${fills(c)[k]}"></i>`;
        return `<p class="key">${B.legend(c, sw).map((x) => `<span>${x}</span>`).join("")}</p>`;
      };
      const R = {
        lead: (b) => reading(B.lead(b, { ...O, kicker: "Top of the stack" })),
        items: (b) => reading(B.section(b.heading, B.items(b, O))),
        calendar: (b) => reading(B.section("Today", B.events(b, { ...O, clock: "t12", allDay: "All day" }))),
        chart: (c) => block("chart", `<h2>${esc(c.title)}</h2><p class="sub">${esc(B.facts(c, ", "))}</p>${key(c)}<div class="plot">${plot(c)}</div><p class="say">${esc(c.takeaway)}</p>`),
        quote: (q) => block("quote", `<p class="q">&ldquo;${esc(q.text)}&rdquo;</p><p class="tag">${B.logo(q.logo, { ...O, cls: "qlogo" })}${esc(q.author)} in ${esc(q.app)}</p>`),
        progress: (p) => block("progress", `<h2>${esc(p.statement)}</h2><p class="sub"><b>${spell(p.done)}</b> of ${spell(p.total).toLowerCase()} done</p><div class="plot">${B.cells(p, { w: W, h: 14, gap: 6, on: "var(--acc)", off: "var(--hair)" })}</div>`),
        note: (n) => block("note", `<p class="q">${esc(n.text)}</p>`),
      };
      const secs = B.layout(ed, R);
      const s = ed.stats;
      const figs = s ? `<div class="figs"><div><b>${s.done}</b><span>Completed</span>${s.you && s.gaia ? `<small>you ${s.you} · GAIA ${s.gaia}</small>` : ""}</div>${s.mail ? `<div><b>${s.mail}</b><span>Emails handled</span></div>` : ""}${s.focus ? `<div><b>${esc(s.focus)}</b><span>Focus today</span></div>` : ""}</div>` : "";
      return `<article class="t-band" style="--filter:${skin.hue.filter}; --acc:${skin.hue.acc}; --h:${skin.header.h}; --field:${skin.field.field}; --hair:${skin.field.hair}">
${grain("bd-g", 0.9)}
<div class="hd"><img src="${ed.assets.BAND}" alt=""><span class="k">Daily brief · No. ${ed.editionNo}</span><span class="mark">GAIA</span><span class="date">${esc(ed.dateLong)} · ${esc(ed.time)}</span></div>
<div class="body">
  <p class="deck">${esc(ed.deck)}</p>
  ${EXPLORER.fold(secs).join("")}
  ${figs}
  <p class="foot">Edition No. ${ed.editionNo} · Generated ${esc(ed.time)} by GAIA</p>
  ${ed.sources.length ? `<p class="foot src" data-block="sources"><span class="logos">${ed.sources.map((s) => EXPLORER.blocks.logo(s.logo, { mode: "color", cls: "" })).join("")}</span>Made from your ${esc(EXPLORER.blocks.appList(ed.sources))}</p>` : ""}
</div></article>`;
    },
  });

  /* ==========================================================================
     PLAYFAIR FRONTISPIECE — signature moves from the desktop original:
       a ruled folio line ("VOL. I · No 42 · FRIDAY, 3 JULY 2026") with a
       gilt numero; the title in towering Playfair italic over a tone-on-tone
       edition numeral; an italic deck; roman-numeral sections with
       small-caps labels and a spelled-out count; time / label rows with an
       italic note and a small-caps tag; a centred figures row.
     Added detail: laid-paper chain lines, gilt hairlines, a blind-embossed
     edition numeral.
     ======================================================================== */
  EXPLORER.register({
    id: "playfair",
    name: "Playfair Frontispiece",
    axes: {
      ground: [
        { id: "ivory", label: "ivory paper", ground: "#f6f1e6", ink: "#1d1a15", soft: "#5c5446", gilt: "#76560f", mark: "rgba(29,26,21,.06)", hair: "#d8cfbd" },
        { id: "emerald", label: "emerald cloth", ground: "#0f3b2c", ink: "#f4eddc", soft: "#c9d3c4", gilt: "#dcb86e", mark: "rgba(244,237,220,.06)", hair: "#2c5a48" },
        { id: "burgundy", label: "burgundy cloth", ground: "#561423", ink: "#f8ece6", soft: "#e2c4c3", gilt: "#e6bd77", mark: "rgba(248,236,230,.06)", hair: "#743042" },
        { id: "navy", label: "navy cloth", ground: "#15223f", ink: "#eef0f6", soft: "#c3c9da", gilt: "#dcbd77", mark: "rgba(238,240,246,.06)", hair: "#2e3d60" },
      ],
      numeral: [
        { id: "roman", label: "roman section numerals" },
        { id: "arabic", label: "arabic section numerals" },
      ],
      watermark: [
        { id: "on", label: "edition watermark" },
        { id: "off", label: "no watermark" },
      ],
    },
    css: `
.t-playfair { position: relative; isolation: isolate; overflow: hidden; box-sizing: border-box; width: 540px; padding: 34px 34px 36px; color: var(--ink);
  background: repeating-linear-gradient(90deg, var(--mark) 0 1px, transparent 1px 26px), var(--ground); font: 400 17px/1.5 'Literata', serif; }
.t-playfair * { box-sizing: border-box; margin: 0; padding: 0; }
.t-playfair .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .12; z-index: -1; }
.t-playfair .wm { position: absolute; top: 20px; left: 50%; transform: translateX(-38%); font: 700 250px/1 'Playfair Display', serif; color: var(--mark); letter-spacing: -.04em; z-index: -1;
  text-shadow: 1px 1px 0 rgba(255,255,255,.18), -1px -1px 0 rgba(0,0,0,.05); }
.t-playfair .folio { display: flex; align-items: center; gap: 12px; font-size: 14px; letter-spacing: 0; color: var(--soft); }
.t-playfair .folio::before, .t-playfair .folio::after { content: ""; flex: 1; border-top: 1px solid var(--gilt); }
.t-playfair .folio b { color: var(--gilt); font-weight: 400; }
.t-playfair h1 { font: italic 500 80px/.92 'Playfair Display', serif; text-align: center; margin-top: 26px; letter-spacing: -.01em; }
.t-playfair .rule { border-top: 1px solid var(--ink); margin: 24px 0 18px; }
.t-playfair .deck { font: italic 500 25px/1.32 'Playfair Display', serif; text-align: center; padding: 0 12px; }
.t-playfair section { margin-top: 36px; }
.t-playfair section.rs { margin-top: 18px; }
.t-playfair .lead { margin-top: 30px; border-top: 1px solid var(--gilt); }
.t-playfair .rs-h b, .t-playfair .dh b { font: normal 700 .9em/1 'Playfair Display', serif; color: var(--gilt); margin-right: .45em; }
.t-playfair .rs-h::after { content: ""; display: block; margin-top: 10px; border-top: 1px solid var(--ink); }
.t-playfair .dh { font: italic 500 24.5px/32px 'Playfair Display', serif; padding-bottom: 10px; border-bottom: 1px solid var(--ink); }
.t-playfair .sub { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 18px; font-size: 15px; color: var(--soft); margin-top: 10px; }
.t-playfair .sub > i { margin-right: auto; }
.t-playfair .sub span i { display: inline-block; width: 10px; height: 10px; margin-right: 7px; }
.t-playfair .sub span i.ln { width: 16px; height: 0; border-top: 2px solid var(--gilt); vertical-align: 3px; }
.t-playfair .sub span i.ln.dash { border-top: 1.5px dashed var(--ink); }
.t-playfair .plot { margin-top: 14px; }
.t-playfair .plot.cells { margin-top: 18px; }
.t-playfair .say { margin-top: 12px; font-style: italic; color: var(--ink); text-wrap: pretty; }
.t-playfair .epi { margin: 0 18px; padding: 18px 0; border-top: 1px solid var(--gilt); border-bottom: 1px solid var(--gilt); text-align: center; }
.t-playfair .epi p { font: italic 500 22px/1.35 'Playfair Display', serif; text-wrap: balance; }
.t-playfair .epi cite { display: flex; justify-content: center; align-items: center; gap: 8px; margin-top: 10px; font-style: italic; font-size: 15px; color: var(--soft); }
.t-playfair .qlogo { width: 14px; height: 14px; color: var(--gilt); }
.t-playfair .nb { font-style: italic; text-align: center; padding: 0 24px; text-wrap: balance; }
.t-playfair { --rs-font: 'Literata', serif; --rs-font-h: 'Playfair Display', serif; --rs-ink: var(--ink); --rs-muted: var(--soft); --rs-acc: var(--gilt); --rs-logo-ink: var(--gilt); --rs-base: 15px; --rs-h-style: italic; --rs-kick-case: none; --rs-kick-variant: small-caps; --rs-kick-track: .06em; }
.t-playfair .figs { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); text-align: center; margin-top: 34px; padding: 18px 0; border-top: 1px solid var(--ink); border-bottom: 1px solid var(--ink); }
.t-playfair .figs b { display: block; font: 700 42px/1 'Playfair Display', serif; font-variant-numeric: lining-nums; }
.t-playfair .figs span { display: block; font-style: italic; font-size: 16px; margin-top: 8px; color: var(--soft); }
.t-playfair .col { margin-top: 22px; text-align: center; font-size: 14px; letter-spacing: 0; color: var(--soft); }
.t-playfair .src { margin-top: 18px; }
.t-playfair .src .col { margin-top: 8px; text-wrap: balance; }
.t-playfair .src .logos { display: flex; justify-content: center; gap: 12px; color: var(--gilt); }
.t-playfair .src .xb-logo { width: 15px; height: 15px; }
`,
    render(ed, skin) {
      const B = EXPLORER.blocks;
      const W = 472;
      let n = 0;
      const num = () => (skin.numeral.id === "roman" ? ROMAN[n++] : String(++n));
      /* Every section continues the book's numbering: a numeral, an italic title, set as one heading. */
      const head = (title, cls) => `<div class="${cls}" role="heading" aria-level="3"><b>${num()}</b>${esc(title)}</div>`;
      const reading = (title, body) => `<section class="rs"><div class="rs-sec" role="group">${head(title, "rs-h")}${body}</div></section>`;
      const block = (kind, title, html) => `<section class="data" data-block="${kind}">${title ? head(title, "dh") : ""}${html}</section>`;
      const PLOT = { w: W, font: "Literata", size: 15, ink: "var(--ink)", soft: "var(--soft)", rule: "var(--hair)", base: "var(--ink)", valueWeight: 400 };
      const fills = (c) => (c.series.length > 1 ? ["var(--ink)", "var(--gilt)", "var(--soft)"] : ["var(--gilt)"]);
      const plot = (c) => {
        if (c.chart === "spark") return B.spark(c, { ...PLOT, h: 58, line: "var(--gilt)", lineW: 2, dot: 3.5 });
        if (c.chart === "line") return B.line(c, { ...PLOT, h: 152, gutter: 30, dot: 3.5, lines: [{ color: "var(--gilt)", width: 2 }, { color: "var(--ink)", width: 1.5, dash: "4 3" }] });
        return B.bars(c, { ...PLOT, h: 170, rule: "var(--ink)", fills: fills(c), gapRatio: 0.46 });
      };
      const key = (c) => {
        if (c.series.length < 2) return "";
        const sw = c.chart === "line" ? (k) => `<i class="ln${k ? " dash" : ""}"></i>` : (k) => `<i style="background:${fills(c)[k]}"></i>`;
        return B.legend(c, sw).map((x) => `<span>${x}</span>`).join("");
      };
      const R = {
        lead: (b) => `<section class="lead">${B.lead(b, { kicker: "Foreword" })}</section>`,
        items: (b) => reading(b.heading, B.items(b)),
        calendar: (b) => reading("The day ahead", B.events(b, { clock: "t12", allDay: "All day" })),
        chart: (c) => block("chart", c.title, `<p class="sub"><i>${esc(B.facts(c, ", "))}</i>${key(c)}</p><div class="plot">${plot(c)}</div><p class="say">${esc(c.takeaway)}</p>`),
        quote: (q) => block("quote", "", `<blockquote class="epi"><p>&ldquo;${esc(q.text)}&rdquo;</p><cite>${B.logo(q.logo, { cls: "qlogo" })}${esc(q.author)}, in ${esc(q.app)}</cite></blockquote>`),
        progress: (p) => block("progress", p.statement, `<div class="plot cells">${B.cells(p, { w: W, h: 12, gap: 6, on: "var(--gilt)", offStroke: "var(--soft)" })}</div><p class="sub"><i>${spell(p.done)} of ${spell(p.total).toLowerCase()} done</i></p>`),
        note: (x) => block("note", "", `<p class="nb">${esc(x.text)}</p>`),
      };
      const secs = B.layout(ed, R);
      const s = ed.stats;
      const figs = s ? `<div class="figs"><div><b>${s.done}</b><span>completed</span></div>${s.mail ? `<div><b>${s.mail}</b><span>emails handled</span></div>` : ""}${s.focus ? `<div><b>${esc(s.focus)}</b><span>focus today</span></div>` : ""}</div>` : "";
      const t1 = `The ${ed.weekday}`;
      const size = Math.min(80, Math.floor(470 / (t1.length * 0.46)));
      return `<article class="t-playfair" style="--ground:${skin.ground.ground}; --ink:${skin.ground.ink}; --soft:${skin.ground.soft}; --gilt:${skin.ground.gilt}; --mark:${skin.ground.mark}; --hair:${skin.ground.hair}">
${grain("pf-g", 0.8)}${skin.watermark.id === "on" ? `<div class="wm" aria-hidden="true">${ed.editionNo}</div>` : ""}
<div class="folio"><span>Vol. I</span><b>No ${ed.editionNo}</b><span>${esc(ed.weekday)}, ${ed.day} ${esc(ed.month)} ${ed.year}</span></div>
<h1><span style="font-size:${size}px">${esc(t1)}</span><br>Brief</h1>
<div class="rule"></div>
<p class="deck">${esc(ed.deck)}</p>
${EXPLORER.fold(secs).join("")}
${figs}
<p class="col">Edition No ${ed.editionNo} · set by GAIA at ${esc(ed.time)}${s && s.you && s.gaia ? ` · yesterday ${s.you} by you, ${s.gaia} by GAIA` : ""}</p>
${ed.sources.length ? `<div class="src" data-block="sources"><p class="logos">${ed.sources.map((x) => EXPLORER.blocks.logo(x.logo, { cls: "" })).join("")}</p><p class="col">Made from your ${esc(EXPLORER.blocks.appList(ed.sources))}</p></div>` : ""}
</article>`;
    },
  });
})();
