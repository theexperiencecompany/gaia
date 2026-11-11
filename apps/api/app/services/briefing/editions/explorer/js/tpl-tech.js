/* ============================================================================
   tpl-tech.js (round 2) — The Blueprint and The Instrument on a 540 px
   portrait canvas (export at 3x). Body 17 px or larger.
   Reading order: headline -> the brief's blocks in GAIA's order -> figures.
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
  /* A timed event's position on the 06:00-24:00 operating window, 0..1. */
  const pos = (e) => (hours(e.t24) - 6) / 18;
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
        { id: "prussian", label: "prussian blue", stock: "#0b335e", ink: "#eaf3f8", soft: "#b6cfde", line: "rgba(234,243,248,.62)", grid: "rgba(234,243,248,.075)", warn: "#ffc97e" },
        { id: "diazo", label: "diazo whiteprint", stock: "#f1efe6", ink: "#1f3487", soft: "#3d4f99", line: "rgba(31,52,135,.55)", grid: "rgba(31,52,135,.08)", warn: "#a8321c" },
      ],
      face: [
        { id: "barlow", label: "Barlow Condensed", stack: "'Barlow Condensed', sans-serif" },
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
.t-flightplan .soft { color: var(--soft); }
.t-flightplan svg.elev { display: block; width: 100%; height: auto; overflow: visible; }
.t-flightplan svg.elev text { font-family: inherit; fill: currentColor; }
.t-flightplan .ball { display: inline-grid; place-items: center; width: 22px; height: 22px; border: 1.3px solid currentColor; border-radius: 50%; font-size: 13px; font-weight: 700; }
.t-flightplan { --rs-font: var(--face); --rs-font-h: var(--face); --rs-ink: var(--ink); --rs-muted: var(--soft); --rs-acc: var(--warn); --rs-base: 16px; --rs-kick-track: 0; }
.t-flightplan h1 { margin-bottom: 24px; }
.t-flightplan .rs-h + svg.elev { margin: 4px 0 16px; }
.t-flightplan .fdet { margin: 36px 0 24px; }
.t-flightplan .fdet h2 { margin-top: 0; }
.t-flightplan .fdet .xb-plot { margin-top: 6px; }
.t-flightplan .fsay { margin-bottom: 10px; text-wrap: pretty; }
.t-flightplan .flegend { display: flex; flex-wrap: wrap; gap: 6px 18px; align-items: baseline; margin-top: 10px; font-size: 15px; }
.t-flightplan .fkey { display: inline-flex; align-items: center; gap: 8px; font-weight: 700; }
.t-flightplan .fsw { display: block; flex: none; }
.t-flightplan .fnotes { list-style: none; }
.t-flightplan .fq { font-size: 20px; line-height: 1.3; font-weight: 600; text-wrap: pretty; }
.t-flightplan .fnotes li { display: grid; grid-template-columns: 34px 1fr; padding: 5px 0; align-items: baseline; text-wrap: pretty; }
.t-flightplan .fnotes .ball { transform: translateY(-1px); }
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
      const B = EXPLORER.blocks;
      const W = 446; // the sheet's drawing width inside its border and padding
      const face = skin.face.stack;
      const ink = "var(--ink)";
      const h2 = (l, r = "") => `<h2 class="lbl"><span>${l}</span><span>${r}</span></h2>`;
      const lc = (t) => esc(t.charAt(0).toLowerCase() + t.slice(1));
      const HATCH = (id) => `<pattern id="${id}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="1.2" height="6" fill="${ink}"/></pattern>`;
      const fills = ["var(--ink)", "url(#fp-h)", "none"];
      const sw = (k) => `<svg class="fsw" width="22" height="12" viewBox="0 0 22 12" aria-hidden="true"><defs>${HATCH(`fp-s${k}`)}</defs><rect x=".65" y=".65" width="20.7" height="10.7" fill="${k === 1 ? `url(#fp-s${k})` : fills[k % 3]}" stroke="${ink}" stroke-width="1.3"/></svg>`;
      // Lettered details: the lead is Detail A, every drawing after it takes the next letter.
      let letter = "B".charCodeAt(0);
      const detail = () => `Detail ${String.fromCharCode(letter++)}`;
      // Bars drafted in outline: your share solid, GAIA's hatched like the base's overnight section.
      const bars = (c) => {
        const n = c.x.length;
        const h = 150, top = 22, bottom = 26, ph = h - top - bottom;
        const sums = B.totals(c);
        const max = Math.max(...sums);
        const slot = W / n, bw = Math.round(slot * 0.56);
        let g = "";
        c.x.forEach((lab, i) => {
          const x = Math.round(i * slot + (slot - bw) / 2) + 0.65;
          let y = top + ph;
          c.series.forEach((sr, k) => {
            const hh = (sr.values[i] / max) * ph;
            if (hh) g += `<rect x="${x}" y="${(y - hh).toFixed(2)}" width="${bw - 1.3}" height="${hh.toFixed(2)}" fill="${fills[k % 3]}" stroke="${ink}" stroke-width="1.3"/>`;
            y -= hh;
          });
          g += B.txt(x + bw / 2, y - 7, B.fmt(sums[i]), { font: face, size: 13, weight: 700, fill: ink });
          g += B.txt(x + bw / 2, h - 6, lab, { font: face, size: 13, weight: 700, fill: "var(--soft)" });
        });
        g += `<rect x="0" y="${top + ph}" width="${W}" height="1.6" fill="${ink}"/>`;
        return `<svg class="xb-plot" width="${W}" height="${h}" viewBox="0 0 ${W} ${h}" aria-hidden="true"><defs>${HATCH("fp-h")}</defs>${g}</svg>`;
      };
      const PLOT = { font: face, size: 13, weight: 700, ink, soft: "var(--soft)", rule: "var(--line)", base: ink, dot: 4, gutter: 26 };
      const plot = (c) =>
        c.chart === "line"
          ? B.line(c, { ...PLOT, w: W, h: 140, lines: [{ color: ink, width: 1.8 }, { color: ink, width: 1.8, dash: "5 4" }, { color: "var(--warn)", width: 1.8 }] })
          : c.chart === "spark"
            ? B.spark(c, { ...PLOT, w: W, h: 56, line: ink, lineW: 1.8 })
            : bars(c);
      const lineKey = (k) => `<svg class="fsw" width="22" height="12" viewBox="0 0 22 12" aria-hidden="true"><line x1="1" y1="6" x2="21" y2="6" stroke="${k === 2 ? "var(--warn)" : ink}" stroke-width="1.8" ${k === 1 ? 'stroke-dasharray="5 4"' : ""}/></svg>`;
      const key = (c) => {
        const swatch = c.chart === "line" || c.chart === "spark" ? lineKey : sw;
        const names = c.series.length > 1 ? c.series.map((sr, k) => `<span class="fkey">${swatch(k)}${esc(sr.name)}, ${esc(sr.total)}</span>`).join("") : "";
        // The range heads the detail; the legend says what one unit is.
        const unit = c.range ? (c.unit ? `${c.unit} per day` : "per day") : B.facts(c);
        return `<p class="flegend">${names}<span class="soft">${esc(unit)}</span></p>`;
      };
      // The elevation: the day drawn along a dimensioned 06-24 axis, each event a leader to its time.
      const elevation = (all) => {
        const events = all.filter((e) => e.t24);
        const EW = 446;
        const X = (p) => 10 + p * (EW - 20);
        const lv = levels(events, 0.1);
        const ticks = [6, 9, 12, 15, 18, 21, 24].map((h) => `<line x1="${X((h - 6) / 18)}" y1="112" x2="${X((h - 6) / 18)}" y2="122" stroke="currentColor" stroke-width="1"/><text x="${X((h - 6) / 18)}" y="140" text-anchor="middle" font-size="13" font-weight="700">${pad2(h)}</text>`).join("");
        const marks = events.map((e, i) => {
          const x = X(pos(e));
          const y = lv[i] ? 30 : 62;
          const tag = `<rect x="${x - 21}" y="${y - 11}" width="42" height="20" fill="var(--stock)" stroke="currentColor" stroke-width="1.3"/><text x="${x}" y="${y + 4}" text-anchor="middle" font-size="12" font-weight="700">${esc(e.t24)}</text>`;
          const x2 = X(Math.min(1, pos(e) + 0.5 / 18)); // a 30-minute span
          return `<line x1="${x}" y1="${y + 9}" x2="${x}" y2="112" stroke="currentColor" stroke-width=".8"/><line x1="${x}" y1="104" x2="${x2}" y2="104" stroke="currentColor" stroke-width="1"/><path d="M${x} 104 l5 -3 v6 z M${x2} 104 l-5 -3 v6 z" fill="currentColor"/>${tag}`;
        }).join("");
        const lastT = Math.max(...events.map((e) => hours(e.t24) + 0.5));
        const freeH = Math.ceil(lastT + 0.5);
        const free = lastT && freeH < 22 ? `<line x1="${X((freeH - 6) / 18)}" y1="160" x2="${X(1)}" y2="160" stroke="currentColor" stroke-width="1"/><path d="M${X((freeH - 6) / 18)} 160 l6 -3 v6 z M${X(1)} 160 l-6 -3 v6 z" fill="currentColor"/><text x="${(X((freeH - 6) / 18) + X(1)) / 2}" y="178" text-anchor="middle" font-size="13" font-weight="700">${pad2(freeH)}:00 – 24:00 · YOURS</text>` : "";
        return `<svg class="elev" viewBox="0 0 ${EW} 186" aria-hidden="true"><line x1="${X(0)}" y1="117" x2="${X(1)}" y2="117" stroke="currentColor" stroke-width="1.6"/>${ticks}${marks}${free}</svg>`;
      };
      const R = {
        lead: (b) => B.lead(b, { kicker: "Detail A" }),
        items: (b) => B.section(b.heading, B.items(b)),
        calendar: (b) => B.section(b.events.some((e) => e.day) ? "The week ahead" : "Today", B.events(b, { clock: "t24", allDay: "All day" }), { extra: b.events.some((e) => e.day) || !b.events.some((e) => e.t24) ? "" : elevation(b.events) }),
        chart: (c) => `<div class="fdet" data-block="chart">${h2(`${detail()} · ${lc(c.title)}`, esc(c.range || ""))}<p class="fsay">${esc(c.takeaway)}</p>${plot(c)}${key(c)}</div>`,
        progress: (p) => {
          const n = Math.min(p.total, 12);
          const gap = 8, cw = (W - gap * (n - 1)) / n;
          const on = p.total > 12 ? Math.round((p.done / p.total) * n) : p.done;
          let cells = "";
          for (let i = 0; i < n; i++) cells += `<rect x="${(i * (cw + gap) + 0.65).toFixed(2)}" y=".65" width="${(cw - 1.3).toFixed(2)}" height="24.7" fill="${i < on ? ink : "none"}" stroke="${ink}" stroke-width="1.3" ${i < on ? "" : 'stroke-dasharray="4 3"'}/>`;
          const open = `<svg class="fsw" width="22" height="12" viewBox="0 0 22 12" aria-hidden="true"><rect x=".65" y=".65" width="20.7" height="10.7" fill="none" stroke="${ink}" stroke-width="1.3" stroke-dasharray="4 3"/></svg>`;
          return `<div class="fdet" data-block="progress">${h2(`${detail()} · ${lc(p.statement)}`, `${p.done} of ${p.total}`)}<svg class="xb-plot" width="${W}" height="26" viewBox="0 0 ${W} 26" aria-hidden="true">${cells}</svg><p class="flegend"><span class="fkey">${sw(0)}done, ${p.done}</span><span class="fkey">${open}open, ${p.total - p.done}</span></p></div>`;
        },
        quote: (q) => `<div class="fdet" data-block="quote">${h2(`${detail()} · in ${esc(q.author)}'s words`, esc(q.app))}<p class="fq">&ldquo;${esc(q.text)}&rdquo;</p></div>`,
        note: (n) => `<div class="fdet" data-block="note">${h2("Notes")}<ol class="fnotes"><li><span class="ball">1</span><span>${esc(n.text)}</span></li></ol></div>`,
      };
      const parts = B.layout(ed, R);
      const s = ed.stats;
      const tb = `<div class="tb"><div><span>Project</span><b>${esc(ed.weekday)}</b></div><div><span>Sheet</span><b>${String(ed.editionNo).padStart(3, "0")}</b></div><div><span>Drawn by</span><b>GAIA · ${esc(ed.time24)}</b></div><div><span>Date</span><b>${pad2(ed.day)} ${esc(ed.monthShort.toUpperCase())} ${ed.year}</b></div>${s ? `<div class="wide"><span>Yield</span><b><span class="nw">${s.done} done${s.you && s.gaia ? ` (${s.you} you · ${s.gaia} GAIA)` : ""}</span>${s.mail ? ` · <span class="nw">${s.mail} emails cleared</span>` : ""}${s.focus ? ` · <span class="nw">${esc(s.focus)} focus held</span>` : ""}</b></div>` : ""}</div>`;
      const folds = skin.folds.id === "folded" ? `<i class="fold h"></i><i class="fold v"></i>` : "";
      return `<article class="t-flightplan" style="--stock:${skin.stock.stock}; --ink:${skin.stock.ink}; --soft:${skin.stock.soft}; --line:${skin.stock.line}; --grid:${skin.stock.grid}; --warn:${skin.stock.warn}; --face:${skin.face.stack}">
${grain("bp-g", 0.85)}${folds}
<div class="sheet">
  <div class="strip lbl"><span>Detail A · the day — an elevation</span><span>No. ${ed.editionNo}</span></div>
  <h1>${esc(ed.deck)}</h1>
  ${EXPLORER.fold(parts).join("")}
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
      ],
      face: [
        { id: "sofia", label: "Sofia Sans Condensed", stack: "'Sofia Sans Condensed', sans-serif" },
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
.t-instrument .gauge { position: relative; height: 112px; margin: 6px 0 10px; background: var(--well); border-radius: 4px; box-shadow: inset 0 2px 6px rgba(0,0,0,.6); }
.t-instrument .gauge svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.t-instrument .gauge text { font-family: inherit; }
.t-instrument .read { display: grid; grid-template-columns: 1.3fr 1fr 1fr; gap: 6px; margin-top: 10px; }
.t-instrument .read div { background: var(--well); border-radius: 4px; padding: 10px 8px; box-shadow: inset 0 2px 5px rgba(0,0,0,.55); }
.t-instrument .read .sub { display: block; margin-top: 2px; font-size: 15px; color: var(--soft); }
.t-instrument .read b { display: block; font-size: 34px; line-height: 1; font-weight: 700; color: var(--sig); font-variant-numeric: tabular-nums; text-shadow: 0 0 10px color-mix(in srgb, var(--sig) 40%, transparent); }
.t-instrument .read .lbl { display: block; margin-top: 6px; }
.t-instrument { --rs-font: var(--face); --rs-font-h: var(--face); --rs-ink: var(--ink); --rs-muted: var(--soft); --rs-acc: var(--sig); --rs-base: 16px; }
/* A module is its own frame: the reading block inside it keeps no outer air. */
#root .t-instrument .mod > .rs-sec, #root .t-instrument .mod > .rs-lead { padding-block: 0; }
.t-instrument .rs-h + .gauge { margin: 0 0 16px; }
.t-instrument .isay { margin-bottom: 10px; text-wrap: pretty; }
.t-instrument .iwell { background: var(--well); border-radius: 4px; padding: 12px 12px 10px; box-shadow: inset 0 2px 6px rgba(0,0,0,.6); }
.t-instrument .ileds { padding: 12px; }
.t-instrument .iunit { display: block; margin-top: 6px; }
.t-instrument .ilegend { display: flex; flex-wrap: wrap; gap: 4px 18px; margin-top: 10px; font-size: 15px; }
.t-instrument .ilegend i { display: inline-block; width: 12px; height: 12px; border-radius: 2px; margin-right: 7px; vertical-align: -1px; }
.t-instrument .isoft { color: var(--soft); }
.t-instrument .irx { grid-template-columns: 60px 1fr; text-wrap: pretty; }
.t-instrument .foot { display: flex; justify-content: space-between; margin-top: 18px; padding-top: 12px; border-top: 1px solid var(--hair); }
`,
    render(ed, skin) {
      const B = EXPLORER.blocks;
      const face = skin.face.stack;
      const W = 424; // a module's well, inside the plate's and the well's padding
      const screws = [["8px", "8px", "20deg"], ["8px", null, "70deg"], [null, "8px", "-35deg"], [null, null, "5deg"]]
        .map(([t, l, r]) => `<i class="screw" style="${t ? `top:${t}` : "bottom:8px"};${l ? `left:${l}` : "right:8px"};--r:${r}"></i>`).join("");
      // A screwed-in module; a reading module's one label is its section heading, a display's is engraved.
      const mod = (body, { title = "", count = "", kind = "" } = {}) =>
        `<div class="mod"${kind ? ` data-block="${kind}"` : ""}>${screws}${title ? `<div class="head"><span class="lbl">${title}</span><span class="lbl">${count}</span></div>` : ""}${body}</div>`;
      const ST = { font: face, size: 13, ink: "var(--ink)", soft: "var(--soft)", valueWeight: 700 };
      const legend = (c, fills) =>
        `<p class="ilegend">${c.series.length > 1 ? c.series.map((sr, k) => `<span><i style="background:${fills[k % fills.length]}"></i>${esc(sr.name)} ${esc(sr.total)}</span>`).join("") : ""}<span class="isoft">${esc(c.range ? (c.unit ? `${c.unit} per day` : "per day") : B.facts(c))}</span></p>`;
      const plot = (c) => {
        if (c.chart === "line") return B.line(c, { ...ST, w: W, h: 130, rule: "var(--hair)", base: "var(--soft)", lines: [{ color: "var(--sig)", width: 2 }, { color: "var(--ink)", width: 2 }, { color: "var(--soft)", width: 2, dash: "4 3" }], gutter: 26, dot: 4 });
        if (c.chart === "spark") return B.spark(c, { ...ST, w: W, h: 52, line: "var(--sig)", lineW: 2 });
        return B.bars(c, { ...ST, w: W, h: 150, rule: "var(--soft)", fills: c.series.length > 1 ? ["var(--ink)", "var(--sig)", "var(--soft)"] : ["var(--sig)"], weight: 400, gapRatio: 0.42 });
      };
      // The operating window: today's events pinned on a 06-24 scale, a NOW needle at the issue time.
      const gauge = (all) => {
        const events = all.filter((e) => e.t24);
        const GW = 456;
        const X = (p) => 14 + p * (GW - 28);
        const lv = levels(events, 0.12);
        const ticks = Array.from({ length: 19 }, (_, i) => i + 6).map((h) => `<line x1="${X((h - 6) / 18)}" y1="${h % 3 ? 82 : 76}" x2="${X((h - 6) / 18)}" y2="90" stroke="var(--soft)" stroke-width="1"/>${h % 3 === 0 ? `<text x="${X((h - 6) / 18)}" y="106" text-anchor="middle" font-size="13" fill="var(--soft)">${pad2(h)}</text>` : ""}`).join("");
        const pins = events.map((e, i) => {
          const x = X(pos(e));
          const y = lv[i] ? 14 : 34;
          return `<line x1="${x}" y1="${y + 6}" x2="${x}" y2="84" stroke="var(--sig)" stroke-width="1"/><circle cx="${x}" cy="84" r="4" fill="var(--sig)"/><text x="${x}" y="${y}" text-anchor="middle" font-size="13" font-weight="700" fill="var(--ink)">${esc(e.t24)}</text>`;
        }).join("");
        const now = X((hours(ed.time24) - 6) / 18);
        return `<div class="gauge"><svg viewBox="0 0 ${GW} 112" preserveAspectRatio="none" aria-hidden="true">${ticks}<line x1="${now}" y1="20" x2="${now}" y2="92" stroke="var(--ink)" stroke-width="2"/><text x="${now + 5}" y="16" font-size="13" font-weight="800" fill="var(--sig)">NOW</text>${pins}</svg></div>`;
      };
      const R = {
        lead: (b) => mod(B.lead(b, { kicker: "Master caution" })),
        items: (b) => mod(B.section(b.heading, B.items(b))),
        calendar: (b) => {
          const week = b.events.some((e) => e.day);
          return mod(B.section(week ? "The week ahead" : "Today", B.events(b, { clock: "t24", allDay: "All day" }), { extra: week || !b.events.some((e) => e.t24) ? "" : gauge(b.events) }));
        },
        chart: (c) => mod(`<p class="isay">${esc(c.takeaway)}</p><div class="iwell">${plot(c)}</div>${legend(c, c.series.length > 1 ? ["var(--ink)", "var(--sig)", "var(--soft)"] : ["var(--sig)"])}`, { title: esc(c.title), count: esc(c.range || ""), kind: "chart" }),
        progress: (p) => mod(`<p class="isay">${esc(p.statement)}</p><div class="iwell ileds">${B.cells(p, { w: W, h: 18, gap: 6, on: "var(--sig)", off: "var(--hair)" })}</div><span class="lbl iunit">${p.total - p.done} open</span>`, { title: "Goal · progress", count: `${p.done} of ${p.total} done`, kind: "progress" }),
        quote: (q) => mod(`<div class="row irx"><span class="t">Rx</span><span>&ldquo;${esc(q.text)}&rdquo;<span class="n">${esc(q.author)} · ${esc(q.app)}</span></span></div>`, { title: "Incoming · in their words", kind: "quote" }),
        note: (n) => mod(`<div class="row irx"><span class="t">GAIA</span><span>${esc(n.text)}</span></div>`, { title: "Advisory", kind: "note" }),
      };
      const mods = B.layout(ed, R);
      const s = ed.stats;
      if (s) mods.push(mod(`<div class="read"><div><b>${s.done}</b><span class="lbl">done</span>${s.you && s.gaia ? `<span class="sub">you ${s.you} · GAIA ${s.gaia}</span>` : ""}</div>${s.mail ? `<div><b>${s.mail}</b><span class="lbl">emails</span></div>` : ""}${s.focus ? `<div><b>${esc(s.focus)}</b><span class="lbl">focus today</span></div>` : ""}</div>`, { title: "Yesterday · readout" }));
      return `<article class="t-instrument" style="--sig:${skin.signal.sig}; --panel:${skin.panel.panel}; --well:${skin.panel.well}; --plate:${skin.panel.plate}; --ink:${skin.panel.ink}; --soft:${skin.panel.soft}; --hair:${skin.panel.hair}; --face:${skin.face.stack}">
<i class="brush" aria-hidden="true"></i>${grain("in-g", 0.9)}
<div class="top"><span class="brand">GAIA</span><span class="serial lbl">GAIA RB-${ed.editionNo} · Daily briefing instrument<br>Serial ${esc(ed.weekday.slice(0, 3))} ${ed.day} ${esc(ed.monthShort)} ${ed.year} · issued ${esc(ed.time24)}</span></div>
<p class="deck">${esc(ed.deck)}</p>
${EXPLORER.fold(mods).join("")}
<div class="foot"><span class="lbl">GAIA daily brief · edition No. ${ed.editionNo}</span><span class="lbl">Issued ${esc(ed.time24)}</span></div>
</article>`;
    },
  });
})();
