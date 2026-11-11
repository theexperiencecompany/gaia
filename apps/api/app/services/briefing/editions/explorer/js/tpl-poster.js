/* ============================================================================
   tpl-poster.js (round 2) — The Swiss Timetable on a 540 px portrait canvas (export at 3x). Body 17 px or larger.
   Reading order: headline -> the brief's blocks as GAIA composed them -> stats.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const grain = (id, freq) =>
    `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;

  /* ==========================================================================
     THE SWISS TIMETABLE — signature moves from the desktop original:
       the weekday set huge and rotated up the left edge; a strict asymmetric
       grid; numbered section heads ("01 What matters today"); big bold
       tabular times; one red square marking what needs you; a row of large
       figures at the foot. Added detail: poster-paper noise on the flat
       field, a quarter-fold crease, crop marks in the margin.
     ======================================================================== */
  EXPLORER.register({
    id: "swiss",
    name: "The Swiss Timetable",
    axes: {
      field: [
        { id: "white", label: "white poster", field: "#f4f3ef", ink: "#111111", soft: "#4a4a4a", hair: "#cfcdc6", day: "#111111" },
        { id: "red", label: "signal red", field: "#bf2419", ink: "#fffaf3", soft: "#fff0ea", hair: "rgba(255,250,243,.35)", day: "#fffaf3" },
        { id: "cobalt", label: "cobalt", field: "#1f3fb8", ink: "#f6f7fb", soft: "#d9def3", hair: "rgba(246,247,251,.32)", day: "#f6f7fb" },
        { id: "black", label: "black", field: "#141414", ink: "#f2f0ea", soft: "#c4c1b8", hair: "rgba(242,240,234,.25)", day: "#f2f0ea" },
      ],
      marker: [
        { id: "red", label: "red marker", mark: "#e3261a" },
        { id: "yellow", label: "yellow marker", mark: "#ffd23f" },
      ],
      face: [
        { id: "heros", label: "TeX Gyre Heros", stack: "'TeX Gyre Heros', sans-serif", ratio: 0.6 },
        { id: "aeonik", label: "Aeonik Extended", stack: "'Aeonik Extended', 'TeX Gyre Heros', sans-serif", ratio: 0.78 },
      ],
    },
    css: `
.t-swiss { position: relative; isolation: isolate; box-sizing: border-box; width: 540px; min-height: 820px; padding: 32px 28px 36px 0; background: var(--field); color: var(--ink);
  font: 400 17px/1.4 'TeX Gyre Heros', sans-serif; display: grid; grid-template-columns: 158px 1fr; }
.t-swiss * { box-sizing: border-box; margin: 0; padding: 0; }
.t-swiss .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: soft-light; opacity: .35; z-index: -1; }
.t-swiss .fold { position: absolute; left: 0; right: 0; top: 50%; height: 2px; background: linear-gradient(180deg, rgba(0,0,0,.08), rgba(255,255,255,.18)); pointer-events: none; }
.t-swiss .crop { position: absolute; width: 14px; height: 14px; border: 0 solid var(--soft); opacity: .7; }
.t-swiss .day { display: flex; flex-direction: column; justify-content: space-between; gap: 24px; padding-left: 18px; }
.t-swiss .day span { writing-mode: vertical-rl; transform: rotate(180deg); font-family: var(--face); font-weight: 700; line-height: .78; letter-spacing: -.035em; color: var(--day); white-space: nowrap; }
.t-swiss .day b { writing-mode: vertical-rl; transform: rotate(180deg); font-family: var(--face); font-weight: 700; font-size: 64px; line-height: .78; letter-spacing: -.03em; color: var(--day); font-variant-numeric: tabular-nums; }
.t-swiss .top { display: flex; gap: 16px; font-size: 15px; font-weight: 700; letter-spacing: 0; }
.t-swiss .deck { font-size: 25px; line-height: 1.22; font-weight: 500; letter-spacing: -.01em; margin-top: 14px; padding-bottom: 18px; border-bottom: 6px solid var(--ink); text-wrap: balance; }
.t-swiss section { margin-top: 40px; }
.t-swiss section:has(> .rs-sec) { margin-top: 20px; }
.t-swiss .lead { margin-top: 0; }
.t-swiss .dh, .t-swiss .rs-h { display: flex; align-items: baseline; gap: 10px; }
.t-swiss .dh { font: 700 23.5px/28px var(--face); letter-spacing: -.015em; }
.t-swiss .dh small, .t-swiss .rs-h small { font-weight: 400; color: var(--soft); font-variant-numeric: tabular-nums; }
.t-swiss .dh small.r, .t-swiss .rs-h small.r { margin-left: auto; }
.t-swiss .dh::after, .t-swiss .rs-h::after { content: ""; position: absolute; left: 0; right: 0; bottom: -8px; border-top: 2px solid var(--ink); }
.t-swiss .dh, .t-swiss .rs-h { position: relative; }
.t-swiss .dh { margin-bottom: 16px; }
.t-swiss .rs-item { padding-bottom: 0; }
.t-swiss .plot { padding-top: 16px; }
.t-swiss .key { display: flex; flex-wrap: wrap; gap: 4px 18px; margin-top: 14px; font-size: 15px; font-weight: 700; }
.t-swiss .key i { display: inline-block; width: 16px; height: 16px; margin-right: 8px; vertical-align: -2px; }
.t-swiss .key i.ln { height: 0; border-top: 3px solid var(--acc); vertical-align: 4px; }
.t-swiss .key i.ln.dash { border-top: 2px dashed var(--ink); }
.t-swiss .say { margin-top: 12px; font-weight: 700; line-height: 1.35; text-wrap: pretty; }
.t-swiss .cap { display: block; margin-top: 6px; font-size: 15px; font-weight: 700; color: var(--soft); }
.t-swiss .q { margin-top: 16px; font-size: 20px; line-height: 1.32; letter-spacing: -.01em; text-wrap: pretty; }
.t-swiss .goal { display: grid; grid-template-columns: 84px 1fr; align-items: center; padding-top: 16px; }
.t-swiss .goal .t { font-size: 24px; font-weight: 700; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
.t-swiss { --rs-font: 'TeX Gyre Heros', sans-serif; --rs-font-h: var(--face); --rs-ink: var(--ink); --rs-muted: var(--soft); --rs-acc: var(--acc); --rs-base: 15px; }
.t-swiss .figs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 34px; }
.t-swiss .figs b { display: block; font-family: var(--face); font-size: 50px; line-height: .95; font-weight: 700; letter-spacing: -.04em; font-variant-numeric: tabular-nums; }
.t-swiss .figs span { display: block; font-size: 15px; font-weight: 700; letter-spacing: 0; margin-top: 6px; line-height: 1.25; }
.t-swiss .colo { margin-top: 24px; font-size: 15px; font-weight: 700; letter-spacing: 0; color: var(--soft); }
`,
    render(ed, skin) {
      const B = EXPLORER.blocks;
      const pad = (n) => String(n).padStart(2, "0");
      const W = 354;
      // The verb's ink: the marker where it reads on the field, else the other marker of the axis.
      const MARKERS = { red: "#e3261a", yellow: "#ffd23f" };
      const acc = skin.field.id === "white" ? MARKERS.red : skin.field.id === "black" ? skin.marker.mark : MARKERS.yellow;
      let n = 0;
      /* Every block is a numbered section on the poster's grid: a numeral, the title, a count at the right. */
      const head = (title, right, cls) => `<div class="${cls}" role="heading" aria-level="3"><small>${pad(++n)}</small>${esc(title)}${right ? `<small class="r">${esc(right)}</small>` : ""}</div>`;
      const reading = (title, right, body) => `<section><div class="rs-sec" role="group">${head(title, right, "rs-h")}${body}</div></section>`;
      const block = (kind, title, right, html) => `<section class="data" data-block="${kind}">${head(title, right, "dh")}${html}</section>`;
      const PLOT = { w: W, font: skin.face.stack.split(",")[0].replace(/'/g, ""), size: 15, weight: 700, valueWeight: 700, ink: "var(--ink)", soft: "var(--soft)", rule: "var(--hair)", base: "var(--ink)", ruleW: 1 };
      const fills = (c) => (c.series.length > 1 ? ["var(--ink)", acc, "var(--soft)"] : [acc]);
      const plot = (c) => {
        if (c.chart === "spark") return B.spark(c, { ...PLOT, h: 64, line: acc, lineW: 3, dot: 4.5 });
        if (c.chart === "line") return B.line(c, { ...PLOT, h: 170, gutter: 28, dot: 4.5, lines: [{ color: acc, width: 3 }, { color: "var(--ink)", width: 2, dash: "6 4" }] });
        return B.bars(c, { ...PLOT, h: 190, rule: "var(--ink)", ruleW: 2, fills: fills(c), gapRatio: 0.3 });
      };
      const key = (c) => {
        if (c.series.length < 2) return "";
        const sw = c.chart === "line" ? (k) => `<i class="ln${k ? " dash" : ""}"></i>` : (k) => `<i style="background:${fills(c)[k]}"></i>`;
        return `<p class="key">${B.legend(c, sw).map((x) => `<span>${x}</span>`).join("")}</p>`;
      };
      const R = {
        lead: (b) => `<section class="lead">${B.lead(b, { kicker: "00" })}</section>`,
        items: (b) => reading(b.heading, pad(b.items.length + b.more), B.items(b)),
        calendar: (b) => reading("Today", pad(b.events.length + b.more), B.events(b, { clock: "t24", allDay: "All day" })),
        chart: (c) => block("chart", c.title, "", `<div class="plot">${plot(c)}</div>${key(c)}<p class="say">${esc(c.takeaway)}</p><p class="cap">${esc(B.facts(c, ", "))}</p>`),
        quote: (q) => block("quote", q.author, q.app, `<p class="q">&ldquo;${esc(q.text)}&rdquo;</p>`),
        progress: (p) => block("progress", p.statement, "", `<div class="goal"><span class="t">${p.done}/${p.total}</span><span>${B.cells(p, { w: W - 84, h: 24, gap: 4, on: acc, offStroke: "var(--ink)" })}<span class="cap">${p.done} of ${p.total} done</span></span></div>`),
        note: (x) => block("note", "Note", "", `<p class="q">${esc(x.text)}</p>`),
      };
      const secs = B.layout(ed, R);
      const rows = ed.blocks.reduce((k, b) => k + (b.kind === "lead" ? 1 : b.kind === "items" ? b.items.length + b.more : b.kind === "calendar" ? b.events.length + b.more : 0), 0);
      const s = ed.stats;
      const figs = s ? `<div class="figs"><div><b>${s.done}</b><span>Done yesterday${s.you && s.gaia ? `<br>you ${s.you} / GAIA ${s.gaia}` : ""}</span></div>${s.mail ? `<div><b>${s.mail}</b><span>Emails<br>handled</span></div>` : ""}${s.focus ? `<div><b>${esc(s.focus)}</b><span>Focus time<br>today</span></div>` : ""}</div>` : "";
      const size = Math.min(124, Math.floor(650 / (ed.weekday.length * skin.face.ratio)));
      const crops = [["top:10px;left:10px", "border-top-width:1px;border-left-width:1px"], ["top:10px;right:10px", "border-top-width:1px;border-right-width:1px"], ["bottom:10px;left:10px", "border-bottom-width:1px;border-left-width:1px"], ["bottom:10px;right:10px", "border-bottom-width:1px;border-right-width:1px"]]
        .map(([p, b]) => `<i class="crop" style="${p};${b}"></i>`).join("");
      return `<article class="t-swiss" style="--field:${skin.field.field}; --ink:${skin.field.ink}; --soft:${skin.field.soft}; --hair:${skin.field.hair}; --day:${skin.field.day}; --mark:${skin.marker.mark}; --acc:${acc}; --face:${skin.face.stack}">
${grain("sw-g", 0.9)}<i class="fold" aria-hidden="true"></i>${crops}
<div class="day"><span style="font-size:${size}px">${esc(ed.weekday.toUpperCase())}</span>${rows >= 5 ? `<b aria-hidden="true">No ${ed.editionNo}</b>` : ""}</div>
<div class="main">
  <div class="top"><span>${ed.day} ${esc(ed.month)} ${ed.year}</span><span>Edition No ${ed.editionNo}</span><span>${esc(ed.time24)} · GAIA</span></div>
  <p class="deck">${esc(ed.deck)}</p>
  ${EXPLORER.fold(secs).join("")}
  ${figs}
  <p class="colo">Edition No ${ed.editionNo} · Generated ${esc(ed.time)} by GAIA</p>
</div></article>`;
    },
  });
})();
