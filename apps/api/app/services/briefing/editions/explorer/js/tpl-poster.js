/* ============================================================================
   tpl-poster.js (round 2) — The Swiss Timetable on a 540 px portrait canvas (export at 3x). Body 17 px or larger.
   Reading order: headline -> needs you -> today -> done overnight -> stats;
   empty sections are omitted.
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
        { id: "helvetica", label: "Helvetica Neue", stack: "'Helvetica Neue', Helvetica, Arial, sans-serif", ratio: 0.6 },
        { id: "aeonik", label: "Aeonik Extended", stack: "'Aeonik Extended', 'Helvetica Neue', sans-serif", ratio: 0.78 },
      ],
    },
    css: `
.t-swiss { position: relative; isolation: isolate; box-sizing: border-box; width: 540px; min-height: 820px; padding: 32px 28px 36px 0; background: var(--field); color: var(--ink);
  font: 400 17px/1.4 'Helvetica Neue', Helvetica, Arial, sans-serif; display: grid; grid-template-columns: 158px 1fr; }
.t-swiss * { box-sizing: border-box; margin: 0; padding: 0; }
.t-swiss .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: soft-light; opacity: .35; z-index: -1; }
.t-swiss .fold { position: absolute; left: 0; right: 0; top: 50%; height: 2px; background: linear-gradient(180deg, rgba(0,0,0,.08), rgba(255,255,255,.18)); pointer-events: none; }
.t-swiss .crop { position: absolute; width: 14px; height: 14px; border: 0 solid var(--soft); opacity: .7; }
.t-swiss .day { position: relative; }
.t-swiss .day span { position: absolute; top: 0; left: 18px; writing-mode: vertical-rl; transform: rotate(180deg); font-family: var(--face); font-weight: 700; line-height: .78; letter-spacing: -.035em; color: var(--day); white-space: nowrap; }
.t-swiss .day b { position: absolute; bottom: 0; left: 18px; writing-mode: vertical-rl; transform: rotate(180deg); font-family: var(--face); font-weight: 700; font-size: 64px; line-height: .78; letter-spacing: -.03em; color: var(--day); font-variant-numeric: tabular-nums; }
.t-swiss .top { display: flex; gap: 16px; font-size: 15px; font-weight: 700; letter-spacing: 0; }
.t-swiss .deck { font-size: 25px; line-height: 1.22; font-weight: 500; letter-spacing: -.01em; margin-top: 14px; padding-bottom: 18px; border-bottom: 6px solid var(--ink); text-wrap: balance; }
.t-swiss section { margin-top: 40px; }
.t-swiss h2 { display: flex; align-items: baseline; gap: 10px; font-family: var(--face); font-size: 21px; font-weight: 700; letter-spacing: -.015em; padding-bottom: 10px; border-bottom: 2px solid var(--ink); }
.t-swiss h2 small { font-size: 21px; font-weight: 400; color: var(--soft); font-variant-numeric: tabular-nums; }
.t-swiss h2 i { width: 16px; height: 16px; background: var(--mark); align-self: center; }
.t-swiss .row { display: grid; grid-template-columns: 84px 1fr; padding: 10px 0; border-bottom: 1px solid var(--hair); align-items: baseline; }
.t-swiss .t { font-family: var(--face); font-size: 24px; font-weight: 700; letter-spacing: -.02em; font-variant-numeric: tabular-nums; line-height: 1; }
.t-swiss .t.sm { font-size: 17px; color: var(--soft); font-weight: 500; letter-spacing: 0; }
.t-swiss .v { text-wrap: pretty; }
.t-swiss .v b { font-weight: 700; }
.t-swiss .v span { color: var(--soft); }
.t-swiss .figs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 34px; }
.t-swiss .figs b { display: block; font-family: var(--face); font-size: 50px; line-height: .95; font-weight: 700; letter-spacing: -.04em; font-variant-numeric: tabular-nums; }
.t-swiss .figs span { display: block; font-size: 15px; font-weight: 700; letter-spacing: 0; margin-top: 6px; line-height: 1.25; }
.t-swiss .colo { margin-top: 24px; font-size: 15px; font-weight: 700; letter-spacing: 0; color: var(--soft); }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const pad = (n) => String(n).padStart(2, "0");
      let n = 0;
      const sec = (title, count, rows, mark) => `<section><h2>${mark ? "<i></i>" : `<small>${pad(++n)}</small>`}${title}<small style="margin-left:auto">${pad(count)}</small></h2>${rows}</section>`;
      const secs = [];
      if (needs.length) secs.push(sec("Needs your call", needs.length, needs.map((d) => `<div class="row" data-role="body"><span class="t sm">${esc(d.verb)}</span><span class="v">${esc(d.label)}${d.note ? ` <span>(${esc(d.note)})</span>` : ""}</span></div>`).join(""), true));
      if (c.today.length) secs.push(sec("What matters today", c.today.length, c.today.map((e) => `<div class="row" data-role="body"><span class="t${e.t24 ? "" : " sm"}">${e.t24 ? esc(e.t24) : "EOD"}</span><span class="v">${esc(e.label)}${e.note ? ` <span>(${esc(e.note)})</span>` : ""}</span></div>`).join("")));
      if (c.overnight.length) secs.push(sec("While you slept", c.overnight.length, c.overnight.map((e) => `<div class="row" data-role="body"><span class="t sm">${esc(e.t24)}</span><span class="v">${esc(e.label)}${e.note ? ` <span>(${esc(e.note)})</span>` : ""}</span></div>`).join("")));
      if (c.running.length) secs.push(sec("Still in progress", c.running.length, c.running.map((e) => `<div class="row" data-role="body"><span class="t sm">${esc(e.t24)}</span><span class="v">${esc(e.label)}${e.note ? ` <span>(${esc(e.note)})</span>` : ""}</span></div>`).join("")));
      const s = c.stats;
      const figs = s ? `<div class="figs"><div><b>${s.done}</b><span>Done yesterday${s.you && s.gaia ? `<br>you ${s.you} / GAIA ${s.gaia}` : ""}</span></div>${s.mail ? `<div><b>${s.mail}</b><span>Emails<br>handled</span></div>` : ""}${s.focus ? `<div><b>${esc(s.focus)}</b><span>Focus time<br>today</span></div>` : ""}</div>` : "";
      const size = Math.min(124, Math.floor(650 / (ed.weekday.length * skin.face.ratio)));
      const crops = [["top:10px;left:10px", "border-top-width:1px;border-left-width:1px"], ["top:10px;right:10px", "border-top-width:1px;border-right-width:1px"], ["bottom:10px;left:10px", "border-bottom-width:1px;border-left-width:1px"], ["bottom:10px;right:10px", "border-bottom-width:1px;border-right-width:1px"]]
        .map(([p, b]) => `<i class="crop" style="${p};${b}"></i>`).join("");
      return `<article class="t-swiss" style="--field:${skin.field.field}; --ink:${skin.field.ink}; --soft:${skin.field.soft}; --hair:${skin.field.hair}; --day:${skin.field.day}; --mark:${skin.marker.mark}; --face:${skin.face.stack}">
${grain("sw-g", 0.9)}<i class="fold" aria-hidden="true"></i>${crops}
<div class="day"><span style="font-size:${size}px">${esc(ed.weekday.toUpperCase())}</span>${needs.length + c.today.length + c.overnight.length + c.running.length >= 5 ? `<b aria-hidden="true">No ${ed.editionNo}</b>` : ""}</div>
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
