/* ============================================================================
   tpl-brand.js (round 2) — GAIA · Band and Playfair Frontispiece on a 540 px
   portrait canvas (export at 3x). Body 17 px or larger.
   Reading order: headline -> needs you -> today -> done overnight -> stats;
   empty sections are omitted.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const grain = (id, freq) =>
    `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  const clock = (t24) => {
    if (!t24) return "";
    const [h, m] = t24.split(":").map(Number);
    return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
  };
  const WORDS = ["None", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"];
  const ROMAN = ["I", "II", "III", "IV"];

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
.t-band { position: relative; isolation: isolate; box-sizing: border-box; width: 540px; background: var(--field); color: #f2f2f4; font: 400 17px/1.45 system-ui, -apple-system, 'Helvetica Neue', sans-serif; padding-bottom: 30px; }
.t-band * { box-sizing: border-box; margin: 0; padding: 0; }
.t-band .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: soft-light; opacity: .5; z-index: -1; }
.t-band .hd::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 1px; background: var(--acc); opacity: .55; box-shadow: 0 0 14px 2px var(--acc); }
.t-band .hd { position: relative; height: var(--h); overflow: hidden; }
.t-band .hd img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; object-position: 50% 70%; filter: var(--filter); }
.t-band .hd .k { position: absolute; left: 28px; top: 28px; font-size: 14px; font-weight: 600; color: #ffffff; letter-spacing: .02em; z-index: 1; }
.t-band .hd .mark { position: absolute; left: 24px; top: 50px; font: 700 104px/1 'Aeonik Extended', system-ui, sans-serif; color: #ffffff; letter-spacing: -.01em; z-index: 1; }
.t-band .hd .date { position: absolute; left: 28px; top: 166px; font-size: 15px; color: #ffffff; z-index: 1; }
.t-band .body { padding: 30px 28px 0; }
.t-band .deck { font-size: 27px; line-height: 1.28; letter-spacing: -.01em; font-weight: 500; padding-bottom: 26px; border-bottom: 1px solid var(--hair); }
.t-band section { padding: 34px 0 10px; }
.t-band section + section { border-top: 1px solid var(--hair); }
.t-band h2 { font: 600 25px/1.2 'Aeonik Extended', system-ui, sans-serif; letter-spacing: -.01em; margin-bottom: 16px; }
.t-band h2 b { color: var(--acc); font-weight: 600; }
.t-band .row { display: grid; grid-template-columns: 92px 1fr; padding: 8px 0; line-height: 1.5; }
.t-band .t { font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums; padding-top: 2px; }
.t-band .t.verb { color: var(--acc); }
.t-band .n { color: #a3a5ad; }
.t-band .row > span:last-child { text-wrap: pretty; }
.t-band .tag { display: block; font-size: 14px; font-weight: 500; color: #8d9098; margin-top: 2px; }
.t-band .figs { display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 30px; border-top: 1px solid var(--hair); border-bottom: 1px solid var(--hair); }
.t-band .figs div { padding: 16px 14px; }
.t-band .figs div + div { border-left: 1px solid var(--hair); }
.t-band .figs b { display: block; font: 700 40px/1 'Aeonik Extended', system-ui, sans-serif; color: var(--acc); font-variant-numeric: tabular-nums; }
.t-band .figs span { display: block; font-size: 15px; font-weight: 600; margin-top: 8px; }
.t-band .figs small { display: block; font-size: 14px; color: #9fa1a8; }
.t-band .foot { margin-top: 18px; font-size: 14px; color: #8d9098; }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      /* Section heads read as sentences with the count spelled out in the accent: "Three things need your call". */
      const sec = (head, rows) => `<section><h2>${head}</h2>${rows}</section>`;
      const count = (n, one, many) => `<b>${WORDS[n] || n}</b> ${n === 1 ? one : many}`;
      const row = (t, cls, label, note, tag) => `<div class="row" data-role="body"><span class="t${cls ? " " + cls : ""}">${esc(t)}${tag ? `<span class="tag">${esc(tag.toLowerCase())}</span>` : ""}</span><span>${esc(label)}${note ? ` <span class="n">— ${esc(note)}</span>` : ""}</span></div>`;
      const secs = [];
      if (needs.length) secs.push(sec(`${count(needs.length, "thing needs", "things need")} your call`, needs.map((d) => row(d.verb, "verb", d.label, d.note)).join("")));
      if (c.today.length) secs.push(sec(`${count(c.today.length, "thing", "things")} on today`, c.today.map((e) => row(e.time || "EOD", "", e.label, e.note, e.tag)).join("")));
      if (c.overnight.length) secs.push(sec(`${count(c.overnight.length, "thing", "things")} done while you slept`, c.overnight.map((e) => row(clock(e.t24), "", e.label, e.note, e.tag)).join("")));
      const s = c.stats;
      const figs = s ? `<div class="figs"><div><b>${s.done}</b><span>Completed</span>${s.you && s.gaia ? `<small>you ${s.you} · GAIA ${s.gaia}</small>` : ""}</div>${s.mail ? `<div><b>${s.mail}</b><span>Emails handled</span></div>` : ""}${s.focus ? `<div><b>${esc(s.focus)}</b><span>Focus today</span></div>` : ""}</div>` : "";
      return `<article class="t-band" style="--filter:${skin.hue.filter}; --acc:${skin.hue.acc}; --h:${skin.header.h}; --field:${skin.field.field}; --hair:${skin.field.hair}">
${grain("bd-g", 0.9)}
<div class="hd"><img src="${ed.assets.BAND}" alt=""><span class="k">Daily brief · No. ${ed.editionNo}</span><span class="mark">GAIA</span><span class="date">${esc(ed.dateLong)} · ${esc(ed.time)}</span></div>
<div class="body">
  <p class="deck">${esc(ed.deck)}</p>
  ${secs.join("")}
  ${figs}
  <p class="foot">Edition No. ${ed.editionNo} · Generated ${esc(ed.time)} by GAIA</p>
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
  background: repeating-linear-gradient(90deg, var(--mark) 0 1px, transparent 1px 26px), var(--ground); font: 400 17px/1.5 Charter, Georgia, serif; }
.t-playfair * { box-sizing: border-box; margin: 0; padding: 0; }
.t-playfair .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .12; z-index: -1; }
.t-playfair .wm { position: absolute; top: 20px; left: 50%; transform: translateX(-38%); font: 700 250px/1 'Playfair Display', Georgia, serif; color: var(--mark); letter-spacing: -.04em; z-index: -1;
  text-shadow: 1px 1px 0 rgba(255,255,255,.18), -1px -1px 0 rgba(0,0,0,.05); }
.t-playfair .folio { display: flex; align-items: center; gap: 12px; font-size: 14px; letter-spacing: 0; color: var(--soft); }
.t-playfair .folio::before, .t-playfair .folio::after { content: ""; flex: 1; border-top: 1px solid var(--gilt); }
.t-playfair .folio b { color: var(--gilt); font-weight: 400; }
.t-playfair h1 { font: italic 500 80px/.92 'Playfair Display', Georgia, serif; text-align: center; margin-top: 26px; letter-spacing: -.01em; }
.t-playfair .rule { border-top: 1px solid var(--ink); margin: 24px 0 18px; }
.t-playfair .deck { font: italic 500 25px/1.32 'Playfair Display', Georgia, serif; text-align: center; padding: 0 12px; }
.t-playfair section { margin-top: 46px; }
.t-playfair h2 { display: flex; align-items: baseline; gap: 12px; padding-bottom: 10px; border-bottom: 1px solid var(--ink); margin-bottom: 12px; }
.t-playfair h2 b { font: 700 26px/1 'Playfair Display', Georgia, serif; }
.t-playfair h2 span { font: italic 500 23px/1.2 'Playfair Display', Georgia, serif; }
.t-playfair h2 em { margin-left: auto; font-size: 15px; color: var(--soft); }
.t-playfair .r { display: grid; grid-template-columns: 92px 1fr; padding: 9px 0; line-height: 1.5; }
.t-playfair .r .k { font-size: 16px; font-variant-numeric: lining-nums tabular-nums; padding-top: 1px; }
.t-playfair .r .k.verb { font-style: italic; color: var(--gilt); }
.t-playfair .r i { color: var(--soft); }
.t-playfair .r > span:last-child { text-wrap: pretty; }
.t-playfair .r .tag { display: block; font-style: italic; font-size: 15px; color: var(--soft); margin-top: 2px; }
.t-playfair .figs { display: grid; grid-template-columns: repeat(3, 1fr); text-align: center; margin-top: 34px; padding: 18px 0; border-top: 1px solid var(--ink); border-bottom: 1px solid var(--ink); }
.t-playfair .figs b { display: block; font: 700 42px/1 'Playfair Display', Georgia, serif; font-variant-numeric: lining-nums; }
.t-playfair .figs span { display: block; font-style: italic; font-size: 16px; margin-top: 8px; color: var(--soft); }
.t-playfair .col { margin-top: 22px; text-align: center; font-size: 14px; letter-spacing: 0; color: var(--soft); }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      let n = 0;
      const num = () => (skin.numeral.id === "roman" ? ROMAN[n++] : String(++n));
      const sec = (title, count, rows) => `<section><h2><b>${num()}</b><span>${title}</span><em>${WORDS[count] || count}</em></h2>${rows}</section>`;
      const r = (k, cls, label, note, tag) => `<div class="r" data-role="body"><span class="k${cls ? " " + cls : ""}">${esc(k)}${tag ? `<span class="tag">${esc(tag.toLowerCase())}</span>` : ""}</span><span>${esc(label)}${note ? ` <i>— ${esc(note)}</i>` : ""}</span></div>`;
      const secs = [];
      if (needs.length) secs.push(sec("For your decision", needs.length, needs.map((d) => r(d.verb, "verb", d.label, d.note)).join("")));
      if (c.today.length) secs.push(sec("The day ahead", c.today.length, c.today.map((e) => r(e.time || "EOD", "", e.label, e.note, e.tag)).join("")));
      if (c.overnight.length) secs.push(sec("While you slept", c.overnight.length, c.overnight.map((e) => r(clock(e.t24), "", e.label, e.note, e.tag)).join("")));
      const s = c.stats;
      const figs = s ? `<div class="figs"><div><b>${s.done}</b><span>completed</span></div>${s.mail ? `<div><b>${s.mail}</b><span>emails handled</span></div>` : ""}${s.focus ? `<div><b>${esc(s.focus)}</b><span>focus today</span></div>` : ""}</div>` : "";
      const t1 = `The ${ed.weekday}`;
      const size = Math.min(80, Math.floor(470 / (t1.length * 0.46)));
      return `<article class="t-playfair" style="--ground:${skin.ground.ground}; --ink:${skin.ground.ink}; --soft:${skin.ground.soft}; --gilt:${skin.ground.gilt}; --mark:${skin.ground.mark}; --hair:${skin.ground.hair}">
${grain("pf-g", 0.8)}${skin.watermark.id === "on" ? `<div class="wm" aria-hidden="true">${ed.editionNo}</div>` : ""}
<div class="folio"><span>Vol. I</span><b>No ${ed.editionNo}</b><span>${esc(ed.weekday)}, ${ed.day} ${esc(ed.month)} ${ed.year}</span></div>
<h1><span style="font-size:${size}px">${esc(t1)}</span><br>Brief</h1>
<div class="rule"></div>
<p class="deck">${esc(ed.deck)}</p>
${secs.join("")}
${figs}
<p class="col">Edition No ${ed.editionNo} · set by GAIA at ${esc(ed.time)}${s && s.you && s.gaia ? ` · yesterday ${s.you} by you, ${s.gaia} by GAIA` : ""}</p>
</article>`;
    },
  });
})();
