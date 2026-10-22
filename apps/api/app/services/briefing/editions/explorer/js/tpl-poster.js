/* ============================================================================
   tpl-poster.js (round 2) — The Swiss Timetable and The Day Line on a 540 px portrait canvas (export at 3x). Body 17 px or larger.
   Reading order: headline -> needs you -> today -> done overnight -> stats;
   empty sections are omitted.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
    const grain = (id, freq) =>
    `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  const hourOf = (t24) => Number(t24.split(":")[0]);

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
  ${secs.join("")}
  ${figs}
  <p class="colo">Edition No ${ed.editionNo} · Generated ${esc(ed.time)} by GAIA</p>
</div></article>`;
    },
  });

  /* ==========================================================================
     THE DAY LINE — signature moves from the desktop original:
       a vertical hour axis with ticked, numbered hours; each item hung off
       the axis at its hour with a mono time and a serif label; a red NOW
       marker; decisions as red-circled margin notes; "then the evening is
       yours." written into the empty evening. Phone re-composition: the axis
       runs NOW -> midnight (needs pinned to NOW), then the 00-06 night
       segment GAIA worked through. Added detail: a faint graph-paper grid.
     ======================================================================== */
  EXPLORER.register({
    id: "dayline",
    name: "The Day Line",
    axes: {
      paper: [
        { id: "cool", label: "cool white", paper: "#f6f7f9", ink: "#1c1d22", soft: "#5a5d66", grid: "rgba(40,60,110,.06)", axis: "#2a2c33" },
        { id: "warm", label: "warm paper", paper: "#f8f3e8", ink: "#211d17", soft: "#5f574a", grid: "rgba(120,90,40,.07)", axis: "#2e2921" },
        { id: "sage", label: "sage paper", paper: "#eef2ea", ink: "#1a221c", soft: "#4f5b52", grid: "rgba(40,90,50,.07)", axis: "#26302a" },
        { id: "night", label: "night", paper: "#15171c", ink: "#eceae4", soft: "#adaba4", grid: "rgba(255,255,255,.05)", axis: "#cfccc4" },
      ],
      accent: [
        { id: "red", label: "red NOW", acc: "#d1351f", accText: "#b52a17", accNight: "#ff7a62" },
        { id: "blue", label: "blue NOW", acc: "#2f5bd8", accText: "#2449b8", accNight: "#87a6ff" },
      ],
      face: [
        { id: "charter", label: "Charter", serif: "Charter, Georgia, serif" },
        { id: "iowan", label: "Iowan Old Style", serif: "'Iowan Old Style', Georgia, serif" },
      ],
    },
    css: `
.t-dayline { position: relative; box-sizing: border-box; width: 540px; padding: 36px 32px 36px; color: var(--ink); font: 400 18px/1.45 var(--serif);
  background: linear-gradient(var(--grid) 1px, transparent 1px) 0 0 / 18px 18px, linear-gradient(90deg, var(--grid) 1px, transparent 1px) 0 0 / 18px 18px, var(--paper); }
.t-dayline * { box-sizing: border-box; margin: 0; padding: 0; }
.t-dayline .mono { font-family: Menlo, 'SF Mono', monospace; }
.t-dayline .eyebrow { font-size: 14px; letter-spacing: 0; color: var(--soft); }
.t-dayline h1 { font-size: 34px; line-height: 1.1; font-weight: 700; margin-top: 8px; letter-spacing: -.01em; }
.t-dayline .meta { font-size: 14px; color: var(--soft); margin-top: 6px; }
.t-dayline .deck { font-style: italic; font-size: 24px; line-height: 1.35; margin-top: 18px; text-wrap: balance; }
.t-dayline .axis { position: relative; margin-top: 30px; padding-left: 64px; }
.t-dayline .axis::before { content: ""; position: absolute; left: 44px; top: 0; bottom: 0; width: 1.5px; background: var(--axis); }
.t-dayline .hr { position: relative; min-height: 20px; }
.t-dayline .hr .tk { position: absolute; left: -24px; top: 7px; width: 10px; border-top: 1px solid var(--axis); }
.t-dayline .hr .lb { position: absolute; left: -64px; top: -1px; width: 32px; text-align: right; font-size: 13px; color: var(--soft); }
.t-dayline .ev { padding: 4px 0 12px; }
.t-dayline .ev .tm { font-size: 15px; color: var(--soft); letter-spacing: 0; }
.t-dayline .ev .lab { font-size: 19px; line-height: 1.35; text-wrap: pretty; }
.t-dayline .ev .nt { font-size: 15px; color: var(--soft); }
.t-dayline .now .tk { border-top: 2px solid var(--acc); width: 26px; left: -34px; }
.t-dayline .now .dot { position: absolute; left: -26px; top: 2px; width: 12px; height: 12px; border-radius: 50%; background: var(--acc); box-shadow: 0 0 0 4px color-mix(in srgb, var(--acc) 22%, transparent); }
.t-dayline .now .lb { color: var(--accText); font-weight: 700; }
.t-dayline .notes { display: grid; gap: 10px; padding: 0 0 16px; }
.t-dayline .notes .tm.now-t { font-style: italic; font-size: 21px; color: var(--accText); font-weight: 700; letter-spacing: 0; }
.t-dayline .note { display: grid; grid-template-columns: 26px 1fr; }
.t-dayline .note i { font-style: italic; font-weight: 700; font-size: 19px; line-height: 1.4; color: var(--accText); }
.t-dayline .note b { font-style: italic; color: var(--accText); margin-right: 6px; }
.t-dayline .evening { font-style: italic; font-size: 19px; color: var(--soft); padding: 2px 0 10px; }
.t-dayline .night { margin-top: 40px; }
.t-dayline .night h2 { font-style: italic; font-weight: 400; font-size: 22px; line-height: 1.3; }
.t-dayline .night h2 span { font-family: Menlo, monospace; font-style: normal; font-size: 15px; color: var(--soft); margin-left: 8px; }
.t-dayline .night .axis { margin-top: 14px; }
.t-dayline .night .axis::before { background: repeating-linear-gradient(var(--axis) 0 4px, transparent 4px 8px); }
.t-dayline .stats { margin-top: 30px; padding-top: 14px; border-top: 1px solid var(--axis); display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; font-size: 15px; line-height: 1.3; color: var(--soft); }
.t-dayline .stats b { display: block; color: var(--ink); font-size: 26px; line-height: 1.1; margin-bottom: 4px; font-variant-numeric: tabular-nums; }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const nowH = hourOf(ed.time24);
      const byHour = {};
      for (const e of c.today) {
        const h = e.t24 ? hourOf(e.t24) : 18;
        (byHour[h] = byHour[h] || []).push(e);
      }
      const lastH = Math.max(-1, ...Object.keys(byHour).map(Number));
      const ev = (tm, e) => `<div class="ev" data-role="body"><div class="tm mono">${tm}</div><div class="lab">${esc(e.label)}${/[.!?]$/.test(e.label) ? "" : "."}</div>${e.note ? `<div class="nt">${esc(e.note)}</div>` : ""}</div>`;
      const hourRow = (h, inner, cls) => `<div class="hr${cls ? " " + cls : ""}"><i class="tk"></i><span class="lb mono">${h % 3 === 0 ? String(h).padStart(2, "0") : ""}</span>${inner}</div>`;
      const rows = [];
      const notes = needs.length
        ? `<div class="notes"><div class="tm now-t">Now, ${esc(ed.time)} — needs your call</div>${needs.map((d, i) => `<div class="note" data-role="body"><i>${i + 1}</i><span><b>${esc(d.verb)}</b>${esc(d.label)}${d.note ? `. <span class="nt">${esc(cap(d.note))}.</span>` : "."}</span></div>`).join("")}</div>`
        : `<div class="notes"><div class="tm now-t">Now, ${esc(ed.time)}</div></div>`;
      rows.push(`<div class="hr now"><i class="tk"></i><i class="dot"></i><span class="lb mono">${String(nowH).padStart(2, "0")}</span>${notes}</div>`);
      for (let h = nowH + 1; h <= 24; h++) {
        const items = byHour[h] || [];
        let inner = items.map((e) => ev(e.time ? esc(e.time) : "Before EOD", e)).join("");
        if (!inner && h === Math.max(lastH + 2, 19)) inner = `<p class="evening">then the evening is yours.</p>`;
        rows.push(hourRow(h, inner));
      }
      const night = c.overnight.length
        ? `<div class="night"><h2>Earlier, while you slept<span>00–06</span></h2><div class="axis">${(() => {
            const nb = {};
            for (const e of c.overnight) {
              const h = e.t24 ? hourOf(e.t24) : Math.max(0, nowH - 1);
              (nb[h] = nb[h] || []).push(e);
            }
            const out = [];
            for (let h = 0; h < nowH; h++) out.push(hourRow(h, (nb[h] || []).map((e) => ev(esc(e.t24), e)).join("")));
            return out.join("");
          })()}</div></div>`
        : "";
      const running = c.running.length
        ? `<div class="night"><h2>Still in progress<span>now</span></h2><div class="axis">${hourRow(nowH, c.running.map((e) => ev(e.t24 ? esc(e.t24) : "Running", e)).join(""))}</div></div>`
        : "";
      const s = c.stats;
      const stats = s ? `<div class="stats mono"><span><b>${s.done}</b>done yesterday${s.you && s.gaia ? `<br>you ${s.you} / GAIA ${s.gaia}` : ""}</span>${s.mail ? `<span><b>${s.mail}</b>emails handled</span>` : ""}${s.focus ? `<span><b>${esc(s.focus)}</b>focus time today</span>` : ""}</div>` : "";
      const dark = skin.paper.id === "night";
      return `<article class="t-dayline" style="--paper:${skin.paper.paper}; --ink:${skin.paper.ink}; --soft:${skin.paper.soft}; --grid:${skin.paper.grid}; --axis:${skin.paper.axis}; --acc:${skin.accent.acc}; --accText:${dark ? skin.accent.accNight : skin.accent.accText}; --serif:${skin.face.serif}">
<div class="eyebrow mono">GAIA · Daily brief · The day line</div>
<h1>The ${esc(ed.weekday)} Brief</h1>
<p class="meta mono">${esc(ed.dateLong)} · Edition No. ${ed.editionNo}</p>
<p class="deck">${esc(ed.deck)}</p>
<div class="axis">${rows.join("")}</div>
${night}
${running}
${stats}
</article>`;
    },
  });
})();
