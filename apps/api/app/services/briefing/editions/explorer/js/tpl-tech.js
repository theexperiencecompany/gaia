/* ============================================================================
   tpl-tech.js (round 2) — The Blueprint and The Instrument on a 540 px
   portrait canvas (export at 3x). Body 17 px or larger.
   Reading order: headline -> needs you -> today -> done overnight -> stats;
   empty sections are omitted.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const grain = (id, freq) =>
    `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  const hours = (t24) => {
    const [h, m] = t24.split(":").map(Number);
    return h + m / 60;
  };
  const pad2 = (n) => String(n).padStart(2, "0");
  /* Position on the 06:00-24:00 operating window, 0..1; untimed deadlines sit at 18:00. */
  const pos = (e) => ((e.t24 ? hours(e.t24) : 18) - 6) / 18;
  /* Stagger callouts that would collide into alternating levels. */
  function levels(items, minGap) {
    let last = -1;
    let lvl = 0;
    return items.map((e) => {
      const p = pos(e);
      lvl = p - last < minGap ? (lvl + 1) % 2 : 0;
      last = p;
      return lvl;
    });
  }

  /* ==========================================================================
     THE BLUEPRINT — signature moves from the desktop original:
       cyanotype ground with a drafting grid and a ruled border; "DETAIL A"
       sheet label; the day drawn as an elevation along a dimensioned
       06-24 axis with leader lines and arrowed spans; a dimension marking
       the free evening; a detail circle around the deadline; the overnight
       as a hatched section with numbered balloons; numbered NOTES; a title
       block (project, sheet, scale, drawn by, date) with the yield.
     Added detail: revision triangles on what needs you, fold creases from
     a sheet stored folded, diazo edge fade.
     ======================================================================== */
  EXPLORER.register({
    id: "flightplan",
    name: "The Blueprint",
    axes: {
      stock: [
        { id: "cyanotype", label: "cyanotype", stock: "#1b3f9a", ink: "#eef3fc", soft: "#c3d1ef", line: "rgba(238,243,252,.6)", grid: "rgba(238,243,252,.075)", warn: "#ffd28a" },
        { id: "prussian", label: "prussian blue", stock: "#163a63", ink: "#edf4fa", soft: "#bfd0e2", line: "rgba(237,244,250,.6)", grid: "rgba(237,244,250,.07)", warn: "#ffcf8f" },
        { id: "vandyke", label: "vandyke brown", stock: "#4a2e1f", ink: "#f5ebdd", soft: "#dcc9b2", line: "rgba(245,235,221,.55)", grid: "rgba(245,235,221,.07)", warn: "#ffc98a" },
        { id: "diazo", label: "diazo whiteprint", stock: "#f1efe6", ink: "#1f3487", soft: "#3d4f99", line: "rgba(31,52,135,.55)", grid: "rgba(31,52,135,.08)", warn: "#a8321c" },
      ],
      face: [
        { id: "helvetica", label: "Helvetica Neue", stack: "'Helvetica Neue', Helvetica, Arial, sans-serif" },
        { id: "condensed", label: "Avenir Condensed", stack: "'Avenir Next Condensed', 'Helvetica Neue', sans-serif" },
      ],
      folds: [
        { id: "folded", label: "folded sheet" },
        { id: "flat", label: "flat sheet" },
      ],
    },
    css: `
.t-flightplan { position: relative; isolation: isolate; box-sizing: border-box; width: 540px; padding: 18px; color: var(--ink); font: 400 17px/1.45 var(--face);
  background: radial-gradient(120% 100% at 50% 40%, transparent 60%, rgba(0,0,0,.16) 100%),
    linear-gradient(var(--grid) 1px, transparent 1px) 0 0 / 18px 18px, linear-gradient(90deg, var(--grid) 1px, transparent 1px) 0 0 / 18px 18px, var(--stock); }
.t-flightplan * { box-sizing: border-box; margin: 0; padding: 0; }
.t-flightplan .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: soft-light; opacity: .4; z-index: -1; }
.t-flightplan .fold { position: absolute; pointer-events: none; }
.t-flightplan .fold.h { left: 0; right: 0; top: 50%; height: 3px; background: linear-gradient(180deg, rgba(0,0,0,.14), rgba(255,255,255,.12)); }
.t-flightplan .fold.v { top: 0; bottom: 0; left: 50%; width: 3px; background: linear-gradient(90deg, rgba(0,0,0,.12), rgba(255,255,255,.1)); }
.t-flightplan .sheet { position: relative; border: 1.5px solid var(--line); outline: 1px solid var(--line); outline-offset: 4px; padding: 20px 20px 18px; }
.t-flightplan .lbl { font-size: 15px; font-weight: 700; letter-spacing: 0; }
.t-flightplan .strip { display: flex; justify-content: space-between; color: var(--soft); }
.t-flightplan h1 { font-size: 27px; line-height: 1.2; font-weight: 600; margin-top: 14px; }
.t-flightplan h2 { display: flex; justify-content: space-between; padding-bottom: 6px; border-bottom: 1px solid var(--line); margin: 36px 0 12px; }
.t-flightplan .rev { display: grid; grid-template-columns: 34px 1fr; padding: 6px 0; }
.t-flightplan .tri { width: 24px; height: 22px; color: var(--warn); }
.t-flightplan .rev b { color: var(--warn); font-weight: 700; }
.t-flightplan .soft { color: var(--soft); }
.t-flightplan svg.elev { display: block; width: 100%; height: auto; overflow: visible; }
.t-flightplan svg.elev text { font-family: inherit; fill: currentColor; }
.t-flightplan .sched { display: grid; grid-template-columns: 30px 64px 1fr; padding: 6px 0; align-items: baseline; }
.t-flightplan .ball { display: inline-grid; place-items: center; width: 22px; height: 22px; border: 1.3px solid currentColor; border-radius: 50%; font-size: 13px; font-weight: 700; }
.t-flightplan .t { font-weight: 700; font-variant-numeric: tabular-nums; }
.t-flightplan .section { display: grid; grid-template-columns: 36px 1fr; gap: 14px; }
.t-flightplan .sched > span:last-child, .t-flightplan .ov > span:last-child, .t-flightplan .rev > span { text-wrap: pretty; }
.t-flightplan .hatch { border: 1.3px solid var(--line); background: repeating-linear-gradient(45deg, var(--line) 0 1px, transparent 1px 9px); }
.t-flightplan .ov { display: grid; grid-template-columns: 30px 56px 1fr; padding: 5px 0; align-items: baseline; }
.t-flightplan .tb { margin-top: 26px; display: grid; grid-template-columns: 1fr 1fr; border: 1.5px solid var(--line); }
.t-flightplan .tb div { padding: 7px 10px; border-top: 1px solid var(--line); }
.t-flightplan .tb div:nth-child(-n+2) { border-top: 0; }
.t-flightplan .tb div:nth-child(even) { border-left: 1px solid var(--line); }
.t-flightplan .tb .wide { grid-column: 1 / -1; border-left: 0 !important; }
.t-flightplan .tb span { display: block; font-size: 14px; font-weight: 700; letter-spacing: 0; color: var(--soft); }
.t-flightplan .tb b { display: block; font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
.t-flightplan .tb .nw { white-space: nowrap; }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const W = 500;
      const X = (p) => 10 + p * (W - 20);
      const parts = [];
      const tri = (n) => `<svg class="tri" viewBox="0 0 24 22" aria-hidden="true"><path d="M12 1.5 L23 20.5 H1 Z" fill="none" stroke="currentColor" stroke-width="1.6"/><text x="12" y="17" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">${n}</text></svg>`;
      if (needs.length) parts.push(`<h2 class="lbl"><span>Revisions · needs your call</span><span>${pad2(needs.length)}</span></h2>${needs.map((d, i) => `<div class="rev" data-role="body">${tri(i + 1)}<span><b>${esc(d.verb)}</b> — ${esc(d.label)}${d.note ? ` <span class="soft">(${esc(d.note)})</span>` : ""}</span></div>`).join("")}`);
      if (c.today.length) {
        const lv = levels(c.today, 0.1);
        const ticks = [6, 9, 12, 15, 18, 21, 24].map((h) => `<line x1="${X((h - 6) / 18)}" y1="112" x2="${X((h - 6) / 18)}" y2="122" stroke="currentColor" stroke-width="1"/><text x="${X((h - 6) / 18)}" y="140" text-anchor="middle" font-size="13" font-weight="700">${pad2(h)}</text>`).join("");
        const marks = c.today.map((e, i) => {
          const x = X(pos(e));
          const y = lv[i] ? 30 : 62;
          if (!e.t24) return `<circle cx="${x}" cy="112" r="20" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="3 3"/><line x1="${x}" y1="92" x2="${x}" y2="${y + 11}" stroke="currentColor" stroke-width=".8"/><circle cx="${x}" cy="${y}" r="11" fill="var(--stock)" stroke="currentColor" stroke-width="1.3"/><text x="${x}" y="${y + 4}" text-anchor="middle" font-size="12" font-weight="700">${i + 1}</text>`;
          const x2 = X(Math.min(1, pos(e) + 0.5 / 18)); // a 30-minute span
          return `<line x1="${x}" y1="${y + 11}" x2="${x}" y2="112" stroke="currentColor" stroke-width=".8"/><line x1="${x}" y1="104" x2="${x2}" y2="104" stroke="currentColor" stroke-width="1"/><path d="M${x} 104 l5 -3 v6 z M${x2} 104 l-5 -3 v6 z" fill="currentColor"/><circle cx="${x}" cy="${y}" r="11" fill="var(--stock)" stroke="currentColor" stroke-width="1.3"/><text x="${x}" y="${y + 4}" text-anchor="middle" font-size="12" font-weight="700">${i + 1}</text>`;
        }).join("");
        const lastT = Math.max(...c.today.map((e) => (e.t24 ? hours(e.t24) + 0.5 : 18)), 0);
        const freeH = Math.ceil(lastT + 0.5);
        const free = lastT && freeH < 22 ? `<line x1="${X((freeH - 6) / 18)}" y1="160" x2="${X(1)}" y2="160" stroke="currentColor" stroke-width="1"/><path d="M${X((freeH - 6) / 18)} 160 l6 -3 v6 z M${X(1)} 160 l-6 -3 v6 z" fill="currentColor"/><text x="${(X((freeH - 6) / 18) + X(1)) / 2}" y="178" text-anchor="middle" font-size="13" font-weight="700">${pad2(freeH)}:00 – 24:00 · YOURS</text>` : "";
        const svg = `<svg class="elev" viewBox="0 0 ${W} 186" aria-hidden="true"><line x1="${X(0)}" y1="117" x2="${X(1)}" y2="117" stroke="currentColor" stroke-width="1.6"/>${ticks}${marks}${free}</svg>`;
        parts.push(`<h2 class="lbl"><span>Elevation · the day, 06–24</span><span>Scale 1:1</span></h2>${svg}${c.today.map((e, i) => `<div class="sched" data-role="body"><span class="ball">${i + 1}</span><span class="t">${e.t24 ? esc(e.t24) : "EOD"}</span><span>${esc(e.label)}${e.note ? ` <span class="soft">(${esc(e.note)})</span>` : ""}</span></div>`).join("")}`);
      }
      if (c.overnight.length)
        parts.push(`<h2 class="lbl"><span>Section 00–06 · while you slept</span><span>${pad2(c.overnight.length)}</span></h2><div class="section"><div class="hatch" aria-hidden="true"></div><div>${c.overnight.map((e, i) => `<div class="ov" data-role="body"><span class="ball">${String.fromCharCode(65 + i)}</span><span class="t">${esc(e.t24)}</span><span>${esc(e.label)}${e.note ? ` <span class="soft">(${esc(e.note)})</span>` : ""}</span></div>`).join("")}</div></div>`);
      if (c.running.length)
        parts.push(`<h2 class="lbl"><span>Section now · still in progress</span><span>${pad2(c.running.length)}</span></h2><div class="section"><div class="hatch" aria-hidden="true"></div><div>${c.running.map((e, i) => `<div class="ov" data-role="body"><span class="ball">${String.fromCharCode(65 + c.overnight.length + i)}</span><span class="t">${esc(e.t24)}</span><span>${esc(e.label)}${e.note ? ` <span class="soft">(${esc(e.note)})</span>` : ""}</span></div>`).join("")}</div></div>`);
      const s = c.stats;
      const tb = `<div class="tb"><div><span>Project</span><b>${esc(ed.weekday)}</b></div><div><span>Sheet</span><b>${String(ed.editionNo).padStart(3, "0")}</b></div><div><span>Drawn by</span><b>GAIA · ${esc(ed.time24)}</b></div><div><span>Date</span><b>${pad2(ed.day)} ${esc(ed.monthShort.toUpperCase())} ${ed.year}</b></div>${s ? `<div class="wide"><span>Yield</span><b><span class="nw">${s.done} done${s.you && s.gaia ? ` (${s.you} you · ${s.gaia} GAIA)` : ""}</span>${s.mail ? ` · <span class="nw">${s.mail} emails cleared</span>` : ""}${s.focus ? ` · <span class="nw">${esc(s.focus)} focus held</span>` : ""}</b></div>` : ""}</div>`;
      const folds = skin.folds.id === "folded" ? `<i class="fold h"></i><i class="fold v"></i>` : "";
      return `<article class="t-flightplan" style="--stock:${skin.stock.stock}; --ink:${skin.stock.ink}; --soft:${skin.stock.soft}; --line:${skin.stock.line}; --grid:${skin.stock.grid}; --warn:${skin.stock.warn}; --face:${skin.face.stack}">
${grain("bp-g", 0.85)}${folds}
<div class="sheet">
  <div class="strip lbl"><span>Detail A · the day — an elevation</span><span>No. ${ed.editionNo}</span></div>
  <h1>${esc(ed.deck)}</h1>
  ${parts.join("")}
  ${tb}
</div></article>`;
    },
  });

  /* ==========================================================================
     THE INSTRUMENT — signature moves from the desktop original:
       a dark equipment panel; GAIA wordmark with a serial strip; recessed
       modules with engraved labels; the operating-window gauge with labelled
       amber pins on a 06-24 scale; amber annunciator dots on decisions; a
       YESTERDAY readout of big numerals.
     Added detail: corner screws on every module, brushed-metal grain,
     engraved-label highlights, glowing LEDs, a NOW needle.
     ======================================================================== */
  EXPLORER.register({
    id: "instrument",
    name: "The Instrument",
    axes: {
      signal: [
        { id: "amber", label: "amber", sig: "#f5b324" },
        { id: "green", label: "avionics green", sig: "#4fd17f" },
        { id: "orange", label: "signal orange", sig: "#ff7a2a" },
        { id: "red", label: "alarm red", sig: "#ff5b4b" },
      ],
      panel: [
        { id: "graphite", label: "graphite", panel: "#1d1e21", well: "#141517", plate: "#26282c", ink: "#eceae4", soft: "#a9a8a2", hair: "#36383d" },
        { id: "olive", label: "olive drab", panel: "#23271e", well: "#161911", plate: "#2d3226", ink: "#ecebe2", soft: "#adb0a0", hair: "#3d4334" },
      ],
      face: [
        { id: "helvetica", label: "Helvetica Neue", stack: "'Helvetica Neue', Helvetica, Arial, sans-serif" },
        { id: "din", label: "Avenir Condensed", stack: "'Avenir Next Condensed', 'Helvetica Neue', sans-serif" },
      ],
    },
    css: `
.t-instrument { position: relative; isolation: isolate; box-sizing: border-box; width: 540px; padding: 28px 22px 28px; background: var(--panel); color: var(--ink); font: 400 17px/1.45 var(--face); }
.t-instrument * { box-sizing: border-box; margin: 0; padding: 0; }
.t-instrument .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: soft-light; opacity: .45; z-index: -1; }
.t-instrument .brush { position: absolute; inset: 0; z-index: -1; background: repeating-linear-gradient(90deg, rgba(255,255,255,.012) 0 1px, transparent 1px 3px); }
.t-instrument .lbl { font-size: 15px; font-weight: 700; letter-spacing: 0; color: var(--soft); text-shadow: 0 1px 0 rgba(255,255,255,.06), 0 -1px 0 rgba(0,0,0,.6); }
.t-instrument .top { display: flex; justify-content: space-between; align-items: flex-end; padding-bottom: 14px; border-bottom: 1px solid var(--hair); }
.t-instrument .brand { font: 700 34px/1 'Aeonik Extended', var(--face); letter-spacing: .01em; }
.t-instrument .serial { text-align: right; line-height: 1.6; }
.t-instrument .deck { font-size: 24px; line-height: 1.3; margin-top: 18px; padding-bottom: 18px; border-bottom: 1px solid var(--hair); }
.t-instrument .mod { position: relative; margin-top: 22px; background: var(--plate); border-radius: 6px; padding: 16px 18px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.05), inset 0 -1px 0 rgba(0,0,0,.4), 0 1px 0 rgba(255,255,255,.03); }
.t-instrument .screw { position: absolute; width: 8px; height: 8px; border-radius: 50%; background: radial-gradient(circle at 35% 35%, #6d6f74, #2a2b2e 70%); box-shadow: 0 1px 0 rgba(255,255,255,.06); }
.t-instrument .screw::after { content: ""; position: absolute; left: 1px; right: 1px; top: 3.5px; height: 1px; background: rgba(0,0,0,.6); transform: rotate(var(--r)); }
.t-instrument .head { display: flex; justify-content: space-between; margin-bottom: 10px; }
.t-instrument .row { display: grid; grid-template-columns: 60px 1fr; padding: 8px 0; border-top: 1px solid var(--hair); }
.t-instrument .row:first-of-type { border-top: 0; }
.t-instrument .t { font-weight: 700; font-variant-numeric: tabular-nums; }
.t-instrument .n { display: block; font-size: 15px; color: var(--soft); }
.t-instrument .ann { display: grid; grid-template-columns: 96px 1fr; column-gap: 14px; align-items: start; padding: 8px 0; }
.t-instrument .lamp { display: grid; place-items: center; height: 30px; border-radius: 3px; background: var(--sig); color: #16130c; font-size: 15px; font-weight: 800; letter-spacing: 0;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.45), inset 0 -2px 0 rgba(0,0,0,.2), 0 0 12px color-mix(in srgb, var(--sig) 45%, transparent); }
.t-instrument .gauge { position: relative; height: 112px; margin: 6px 0 10px; background: var(--well); border-radius: 4px; box-shadow: inset 0 2px 6px rgba(0,0,0,.6); }
.t-instrument .gauge svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.t-instrument .gauge text { font-family: inherit; }
.t-instrument .read { display: grid; grid-template-columns: 1.3fr 1fr 1fr; gap: 6px; margin-top: 10px; }
.t-instrument .read div { background: var(--well); border-radius: 4px; padding: 10px 8px; box-shadow: inset 0 2px 5px rgba(0,0,0,.55); }
.t-instrument .read .sub { display: block; margin-top: 2px; font-size: 15px; color: var(--soft); }
.t-instrument .read b { display: block; font-size: 34px; line-height: 1; font-weight: 700; color: var(--sig); font-variant-numeric: tabular-nums; text-shadow: 0 0 10px color-mix(in srgb, var(--sig) 40%, transparent); }
.t-instrument .read .lbl { display: block; margin-top: 6px; }
.t-instrument .foot { display: flex; justify-content: space-between; margin-top: 18px; padding-top: 12px; border-top: 1px solid var(--hair); }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const screws = [["8px", "8px", "20deg"], ["8px", null, "70deg"], [null, "8px", "-35deg"], [null, null, "5deg"]]
        .map(([t, l, r]) => `<i class="screw" style="${t ? `top:${t}` : "bottom:8px"};${l ? `left:${l}` : "right:8px"};--r:${r}"></i>`).join("");
      const mod = (title, count, body) => `<div class="mod">${screws}<div class="head"><span class="lbl">${title}</span><span class="lbl">${count}</span></div>${body}</div>`;
      const mods = [];
      if (needs.length) mods.push(mod("Annunciator · needs your call", `${needs.length} lit`, needs.map((d) => `<div class="ann" data-role="body"><span class="lamp">${esc(d.verb)}</span><span>${esc(d.label)}${d.note ? `<span class="n">${esc(d.note)}</span>` : ""}</span></div>`).join("")));
      if (c.today.length) {
        const W = 456;
        const X = (p) => 14 + p * (W - 28);
        const lv = levels(c.today, 0.12);
        const ticks = Array.from({ length: 19 }, (_, i) => i + 6).map((h) => `<line x1="${X((h - 6) / 18)}" y1="${h % 3 ? 82 : 76}" x2="${X((h - 6) / 18)}" y2="90" stroke="var(--soft)" stroke-width="1"/>${h % 3 === 0 ? `<text x="${X((h - 6) / 18)}" y="106" text-anchor="middle" font-size="13" fill="var(--soft)">${pad2(h)}</text>` : ""}`).join("");
        const pins = c.today.map((e, i) => {
          const x = X(pos(e));
          const y = lv[i] ? 14 : 34;
          return `<line x1="${x}" y1="${y + 6}" x2="${x}" y2="84" stroke="var(--sig)" stroke-width="1"/><circle cx="${x}" cy="84" r="4" fill="var(--sig)"/><text x="${x}" y="${y}" text-anchor="middle" font-size="13" font-weight="700" fill="var(--ink)">${e.t24 ? esc(e.t24) : "EOD"}</text>`;
        }).join("");
        const now = X((hours(ed.time24) - 6) / 18);
        const gauge = `<div class="gauge"><svg viewBox="0 0 ${W} 112" preserveAspectRatio="none" aria-hidden="true">${ticks}<line x1="${now}" y1="20" x2="${now}" y2="92" stroke="var(--ink)" stroke-width="2"/><text x="${now + 5}" y="16" font-size="13" font-weight="800" fill="var(--sig)">NOW</text>${pins}</svg></div>`;
        mods.push(mod("Operating window · 06–24 local", `${c.today.length} scheduled`, gauge + c.today.map((e) => `<div class="row" data-role="body"><span class="t">${e.t24 ? esc(e.t24) : "EOD"}</span><span>${esc(e.label)}${e.note ? `<span class="n">${esc(e.note)}</span>` : ""}</span></div>`).join("")));
      }
      if (c.overnight.length) mods.push(mod("Overnight log · while you slept", `${c.overnight.length} entr${c.overnight.length === 1 ? "y" : "ies"}`, c.overnight.map((e) => `<div class="row" data-role="body"><span class="t">${esc(e.t24)}</span><span>${esc(e.label)}${e.note ? `<span class="n">${esc(e.note)}</span>` : ""}</span></div>`).join("")));
      if (c.running.length) mods.push(mod("In progress · still running", `${c.running.length} entr${c.running.length === 1 ? "y" : "ies"}`, c.running.map((e) => `<div class="row" data-role="body"><span class="t">${esc(e.t24)}</span><span>${esc(e.label)}${e.note ? `<span class="n">${esc(e.note)}</span>` : ""}</span></div>`).join("")));
      const s = c.stats;
      if (s) mods.push(mod("Yesterday · readout", "", `<div class="read"><div><b>${s.done}</b><span class="lbl">done</span>${s.you && s.gaia ? `<span class="sub">you ${s.you} · GAIA ${s.gaia}</span>` : ""}</div>${s.mail ? `<div><b>${s.mail}</b><span class="lbl">emails</span></div>` : ""}${s.focus ? `<div><b>${esc(s.focus)}</b><span class="lbl">focus today</span></div>` : ""}</div>`));
      return `<article class="t-instrument" style="--sig:${skin.signal.sig}; --panel:${skin.panel.panel}; --well:${skin.panel.well}; --plate:${skin.panel.plate}; --ink:${skin.panel.ink}; --soft:${skin.panel.soft}; --hair:${skin.panel.hair}; --face:${skin.face.stack}">
<i class="brush" aria-hidden="true"></i>${grain("in-g", 0.9)}
<div class="top"><span class="brand">GAIA</span><span class="serial lbl">GAIA RB-${ed.editionNo} · Daily briefing instrument<br>Serial ${esc(ed.weekday.slice(0, 3))} ${ed.day} ${esc(ed.monthShort)} ${ed.year} · issued ${esc(ed.time24)}</span></div>
<p class="deck">${esc(ed.deck)}</p>
${mods.join("")}
<div class="foot"><span class="lbl">GAIA daily brief · edition No. ${ed.editionNo}</span><span class="lbl">Issued ${esc(ed.time24)}</span></div>
</article>`;
    },
  });
})();
