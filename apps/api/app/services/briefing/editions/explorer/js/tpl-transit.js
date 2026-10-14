/* ============================================================================
   tpl-transit.js (round 2) — The Line Guide and The Boarding Pass on a 540 px
   portrait canvas (export at 3x). Body 17 px or larger.
   Reading order: headline -> needs you -> today -> done overnight -> stats;
   empty sections are omitted.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const grain = (id, freq) =>
    `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  const pad2 = (n) => String(n).padStart(2, "0");
  const title = (s) => s.charAt(0) + s.slice(1).toLowerCase();

  /* ==========================================================================
     THE LINE GUIDE — signature moves from the desktop original:
       a transit roundel with the day code; "GAIA TRANSIT AUTHORITY"; a bold
       title under a coloured rule; thick coloured lines with station ticks;
       boxed station names (white box, line-coloured outline, bold caps);
       interchange rings joining lines; a dashed line for decisions; a
       legend panel; a service-notice bar.
     Phone re-composition: the decision line, day line and GAIA's night line
     run down the page in reading order, joined by interchanges.
     Added detail: enamel-panel sheen, printed-map grain.
     ======================================================================== */
  EXPLORER.register({
    id: "metromap",
    name: "The Line Guide",
    axes: {
      livery: [
        { id: "classic", label: "red / blue / orange", day: "#cf3426", night: "#3a62c4", dec: "#e08a1e", decText: "#8a4d00" },
        { id: "tokyo", label: "green / purple / teal", day: "#237a3b", night: "#7c45b0", dec: "#2bb3c4", decText: "#095e69" },
        { id: "paris", label: "magenta / navy / gold", day: "#c4307a", night: "#2a3f8f", dec: "#d9b33a", decText: "#6e5406" },
        { id: "london", label: "brown / grey / pink", day: "#8a4a1f", night: "#4f5a66", dec: "#e98fb0", decText: "#9a2d58" },
      ],
      ground: [
        { id: "enamel", label: "cream enamel", ground: "#f3efe4", ink: "#1c1c20", soft: "#55555c", panel: "#e7e1d2" },
        { id: "white", label: "white enamel", ground: "#f7f7f5", ink: "#16171b", soft: "#53555c", panel: "#ebebe7" },
      ],
      face: [
        { id: "helvetica", label: "Helvetica Neue", stack: "'Helvetica Neue', Helvetica, Arial, sans-serif" },
        { id: "johnston", label: "Gill-style (Avenir)", stack: "'Avenir Next', 'Helvetica Neue', sans-serif" },
      ],
    },
    css: `
.t-metromap { position: relative; isolation: isolate; box-sizing: border-box; width: 540px; padding: 30px 28px 32px; color: var(--ink); font: 400 17px/1.4 var(--face);
  background: linear-gradient(160deg, rgba(255,255,255,.45), transparent 40%), var(--ground); }
.t-metromap * { box-sizing: border-box; margin: 0; padding: 0; }
.t-metromap .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .12; z-index: -1; }
.t-metromap .hd { display: grid; grid-template-columns: 70px 1fr; gap: 16px; align-items: center; padding-bottom: 16px; border-bottom: 4px solid var(--dec); }
.t-metromap .roundel { position: relative; width: 70px; height: 70px; border-radius: 50%; border: 12px solid var(--dec); }
.t-metromap .roundel span { position: absolute; left: -14px; right: -14px; top: 50%; transform: translateY(-50%); background: var(--night); color: #ffffff; text-align: center; font-size: 13px; font-weight: 700; letter-spacing: .1em; padding: 3px 0; }
.t-metromap .auth { font-size: 14px; font-weight: 700; letter-spacing: 0; color: var(--soft); }
.t-metromap h1 { font-size: 34px; line-height: 1.05; font-weight: 700; letter-spacing: -.015em; margin-top: 4px; }
.t-metromap .sub { font-size: 13px; color: var(--soft); margin-top: 4px; }
.t-metromap .notice { margin-top: 20px; display: grid; grid-template-columns: auto 1fr; gap: 12px; align-items: baseline; background: var(--panel); padding: 14px 16px; border-radius: 3px; }
.t-metromap .notice b { font-size: 14px; letter-spacing: 0; color: var(--decText); }
.t-metromap .notice p { font-size: 20px; line-height: 1.3; font-weight: 500; }
.t-metromap .route { margin-top: 18px; }
.t-metromap .ln { position: relative; padding-left: calc(var(--x) + 40px); }
.t-metromap .ln::before { content: ""; position: absolute; left: calc(var(--x) - 5px); top: 0; bottom: 0; width: 10px; background: var(--c); }
.t-metromap .ln.dash::before { background: repeating-linear-gradient(var(--c) 0 14px, transparent 14px 22px); }
.t-metromap .chip { display: inline-block; margin: 6px 0 4px; padding: 3px 10px; border-radius: 3px; background: var(--c); color: var(--on, #ffffff); font-size: 14px; font-weight: 700; letter-spacing: 0; }
.t-metromap .st { position: relative; padding: 10px 0 12px; }
.t-metromap .st::before { content: ""; position: absolute; left: -35px; top: 18px; width: 16px; height: 7px; background: var(--c); }
.t-metromap .box { display: inline-block; border: 2.5px solid var(--c); background: #ffffff; border-radius: 4px; padding: 2px 8px; font-size: 14px; font-weight: 700; letter-spacing: 0; }
.t-metromap .box time { color: var(--soft); margin-right: 6px; font-variant-numeric: tabular-nums; }
.t-metromap .st p { margin-top: 6px; font-size: 18px; line-height: 1.32; }
.t-metromap .st small { display: block; font-size: 15px; color: var(--soft); margin-top: 2px; }
.t-metromap .ix { display: block; width: 100%; height: 54px; }
.t-metromap .legend { margin-top: 22px; border: 1.5px solid var(--ink); border-radius: 4px; padding: 12px 14px; display: grid; grid-template-columns: 1fr 1fr; gap: 6px 16px; font-size: 13px; }
.t-metromap .legend h3 { grid-column: 1 / -1; font-size: 14px; letter-spacing: 0; }
.t-metromap .legend i { display: inline-block; width: 26px; height: 6px; vertical-align: middle; margin-right: 8px; }
.t-metromap .legend b { font-variant-numeric: tabular-nums; }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const L = skin.livery;
      const lines = [];
      if (needs.length) lines.push({ x: 92, c: L.dec, on: "#1c1c20", cls: "dash", name: `Decision line · ${needs.length} for you`, rows: needs.map((d) => `<div class="st" data-role="body"><span class="box">${esc(d.verb)}</span><p>${esc(d.label)}${d.note ? `<small>${esc(d.note)}</small>` : ""}</p></div>`) });
      if (c.today.length) lines.push({ x: 40, c: L.day, cls: "", name: "Day line · today", rows: c.today.map((e) => `<div class="st" data-role="body"><span class="box"><time>${e.t24 ? esc(e.t24) : "EOD"}</time>${esc(title(e.tag))}</span><p>${esc(e.label)}${e.note ? `<small>${esc(e.note)}</small>` : ""}</p></div>`) });
      if (c.overnight.length) lines.push({ x: 92, c: L.night, cls: "", name: "GAIA night line · done", rows: c.overnight.map((e) => `<div class="st" data-role="body"><span class="box"><time>${esc(e.t24)}</time>${esc(title(e.tag))}</span><p>${esc(e.label)}${e.note ? `<small>${esc(e.note)}</small>` : ""}</p></div>`) });
      const route = lines
        .map((l, i) => {
          const block = `<div class="ln ${l.cls}" style="--x:${l.x}px; --c:${l.c}${l.on ? `; --on:${l.on}` : ""}"><span class="chip">${esc(l.name)}</span>${l.rows.join("")}</div>`;
          const next = lines[i + 1];
          if (!next) return block;
          const ix = `<svg class="ix" viewBox="0 0 484 54" preserveAspectRatio="none" aria-hidden="true"><path d="M${l.x} 0 V12 L${next.x} 42 V54" fill="none" stroke="${l.c}" stroke-width="10" ${l.cls ? 'stroke-dasharray="14 8"' : ""}/><path d="M${next.x} 42 V54" stroke="${next.c}" stroke-width="10"/><circle cx="${(l.x + next.x) / 2}" cy="27" r="12" fill="#ffffff" stroke="var(--ink)" stroke-width="5"/></svg>`;
          return block + ix;
        })
        .join("");
      const s = c.stats;
      const legend = `<div class="legend"><h3>Line guide</h3>${needs.length ? `<span><i style="background:repeating-linear-gradient(90deg, ${L.dec} 0 8px, transparent 8px 12px)"></i>Decisions, your call</span>` : ""}${c.today.length ? `<span><i style="background:${L.day}"></i>Your day ahead</span>` : ""}${c.overnight.length ? `<span><i style="background:${L.night}"></i>GAIA, ran overnight</span>` : ""}${s ? `<span>Done yesterday <b>${s.done}</b>${s.you && s.gaia ? ` (you ${s.you}, GAIA ${s.gaia})` : ""}</span>${s.mail ? `<span>Emails handled <b>${s.mail}</b></span>` : ""}${s.focus ? `<span>Focus time today <b>${esc(s.focus)}</b></span>` : ""}` : ""}</div>`;
      return `<article class="t-metromap" style="--ground:${skin.ground.ground}; --ink:${skin.ground.ink}; --soft:${skin.ground.soft}; --panel:${skin.ground.panel}; --day:${L.day}; --night:${L.night}; --dec:${L.dec}; --decText:${L.decText}; --face:${skin.face.stack}">
${grain("mt-g", 0.9)}
<div class="hd"><div class="roundel"><span>${esc(ed.weekday.slice(0, 3).toUpperCase())}</span></div><div><div class="auth">GAIA transit authority</div><h1>The ${esc(ed.weekday)} Brief</h1><p class="sub">Line guide No ${ed.editionNo} · ${esc(ed.dateLong)} · ${esc(ed.time)}</p></div></div>
<div class="notice"><b>Service notice</b><p>${esc(ed.deck)}</p></div>
<div class="route">${route}</div>
${legend}
</article>`;
    },
  });

  /* ==========================================================================
     THE BOARDING PASS — signature moves from the desktop original:
       a navy airline header (GAIA AIR, briefing class, boarding pass number);
       a route line of rings and dots from first departure to arrival; a
       passenger / flight / date / seat grid in tiny caps labels; itinerary
       rows labelled BOARDING / CONNECTION / CARGO; a stats box row; a
       perforated stub with services completed in transit and a barcode.
     Added detail: crimped perforation with semicircle notches, a punched
     hole, a faint security guilloche, a serrated stub edge, a stacked
     PDF417-style code, a gate cell.
     ======================================================================== */
  function barcode(seed, rows, width) {
    let v = Math.imul(seed, 2654435761) >>> 0;
    const out = [];
    for (let r = 0; r < rows; r++) {
      const stops = [];
      let x = 0;
      while (x < width) {
        v = (Math.imul(v, 1103515245) + 12345) >>> 0;
        const w = 1 + (v % 4);
        const gap = 1 + ((v >> 5) % 3);
        stops.push(`var(--ink) ${x}px ${x + w}px, transparent ${x + w}px ${x + w + gap}px`);
        x += w + gap;
      }
      out.push(`linear-gradient(90deg, ${stops.join(", ")})`);
    }
    return out;
  }
  /* Security guilloche: interleaved sine ribbons, drawn once as an SVG. */
  function guilloche(col) {
    const paths = [];
    for (let k = 0; k < 8; k++) {
      let d = "";
      for (let x = 0; x <= 500; x += 6) {
        const y = 60 + Math.sin(x / 26 + k * 0.8) * 26 + Math.sin(x / 61 + k) * 10;
        d += `${x ? "L" : "M"}${x} ${y.toFixed(1)} `;
      }
      paths.push(`<path d="${d}" fill="none" stroke="${col}" stroke-width=".6"/>`);
    }
    return `<svg class="guil" viewBox="0 0 500 120" preserveAspectRatio="none" aria-hidden="true">${paths.join("")}</svg>`;
  }
  EXPLORER.register({
    id: "boardingpass",
    name: "The Boarding Pass",
    axes: {
      livery: [
        { id: "navy", label: "navy + amber", liv: "#13234a", acc: "#b7741a", accOn: "#9a5f0e" },
        { id: "oxblood", label: "oxblood + gold", liv: "#5e1a26", acc: "#b58a2a", accOn: "#8a6510" },
        { id: "jade", label: "jade + coral", liv: "#0c4a3e", acc: "#d0603f", accOn: "#a8441f" },
        { id: "plum", label: "plum + teal", liv: "#3d1f4f", acc: "#1d8a8a", accOn: "#146b6b" },
      ],
      card: [
        { id: "white", label: "white card", paper: "#fbfaf6", desk: "#c9c6bf" },
        { id: "ivory", label: "ivory card", paper: "#f7f1e2", desk: "#b9b2a3" },
      ],
      code: [
        { id: "linear", label: "linear barcode", rows: 1 },
        { id: "stacked", label: "stacked PDF417", rows: 6 },
      ],
    },
    css: `
.t-boardingpass { position: relative; box-sizing: border-box; width: 540px; padding: 34px 26px 44px; background: radial-gradient(120% 80% at 30% 0%, color-mix(in srgb, var(--desk) 80%, #ffffff) 0%, var(--desk) 70%); color: #1b1c22; font: 400 17px/1.4 'Helvetica Neue', Helvetica, Arial, sans-serif; --ink: #1b1c22; }
.t-boardingpass * { box-sizing: border-box; margin: 0; padding: 0; }
.t-boardingpass .pass { position: relative; isolation: isolate; transform: rotate(-.6deg); filter: drop-shadow(0 14px 18px rgba(0,0,0,.28)) drop-shadow(0 2px 3px rgba(0,0,0,.2)); }
.t-boardingpass .body, .t-boardingpass .stub { position: relative; background: var(--paper); overflow: hidden; }
.t-boardingpass .body { border-radius: 14px 14px 0 0; }
.t-boardingpass .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .1; }
.t-boardingpass .guil { position: absolute; left: 0; right: 0; top: 150px; width: 100%; height: 200px; opacity: .5; pointer-events: none; }
.t-boardingpass .top { position: relative; background: var(--liv); color: #ffffff; padding: 18px 22px; display: flex; justify-content: space-between; align-items: center; }
.t-boardingpass .air { font: 700 24px/1 'Aeonik Extended', 'Helvetica Neue', sans-serif; letter-spacing: .02em; }
.t-boardingpass .top small { display: block; font-size: 14px; font-weight: 700; letter-spacing: 0; margin-top: 6px; opacity: .9; }
.t-boardingpass .top .r { text-align: right; font-size: 14px; font-weight: 700; letter-spacing: 0; }
.t-boardingpass .top .r b { display: block; font-size: 19px; letter-spacing: .04em; margin-top: 4px; }
.t-boardingpass .sec { position: relative; padding: 18px 22px; }
.t-boardingpass .lbl { display: block; font-size: 14px; font-weight: 700; letter-spacing: 0; color: #5b5c63; }
.t-boardingpass .lbl.acc { color: var(--accOn); }
.t-boardingpass .route { display: grid; grid-template-columns: auto 1fr auto; gap: 12px; align-items: center; }
.t-boardingpass .route b { display: block; font-size: 44px; line-height: 1; font-weight: 700; letter-spacing: -.03em; font-variant-numeric: tabular-nums; }
.t-boardingpass .route .r { text-align: right; }
.t-boardingpass .path { position: relative; height: 14px; }
.t-boardingpass .path::before { content: ""; position: absolute; left: 7px; right: 7px; top: 6px; border-top: 2px dotted var(--acc); }
.t-boardingpass .path i { position: absolute; top: 0; width: 14px; height: 14px; border-radius: 50%; border: 2.5px solid var(--acc); background: var(--paper); }
.t-boardingpass .deck { font-size: 22px; line-height: 1.3; font-weight: 600; margin-top: 6px; letter-spacing: -.01em; }
.t-boardingpass .grid { display: grid; grid-template-columns: 1.6fr 1fr 1fr .7fr .7fr; gap: 10px; padding-top: 14px; border-top: 1px solid #e3dfd5; }
.t-boardingpass .grid b { display: block; font-size: 16px; font-weight: 700; margin-top: 2px; }
.t-boardingpass .grid b.acc { color: var(--accOn); }
.t-boardingpass .it { display: grid; grid-template-columns: 112px 1fr; padding: 9px 0; border-top: 1px solid #ebe7dd; }
.t-boardingpass .it:first-of-type { border-top: 0; }
.t-boardingpass .it .n { display: block; font-size: 15px; color: #5b5c63; }
.t-boardingpass .it .tm { font-weight: 700; font-variant-numeric: tabular-nums; margin-right: 6px; }
.t-boardingpass .stats { display: grid; grid-template-columns: repeat(3, 1fr); border: 1.5px solid #dcd7cb; border-radius: 6px; margin-top: 4px; }
.t-boardingpass .stats div { padding: 10px 12px; text-align: center; }
.t-boardingpass .stats div + div { border-left: 1.5px solid #dcd7cb; }
.t-boardingpass .stats b { display: block; font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; }
.t-boardingpass .perf { position: relative; height: 28px; background: var(--paper); }
.t-boardingpass .perf::before { content: ""; position: absolute; left: 20px; right: 20px; top: 13px; border-top: 2px dashed #bdb7a9; }
.t-boardingpass .perf i { position: absolute; top: 0; width: 28px; height: 28px; border-radius: 50%; background: var(--desk); }
.t-boardingpass .perf i:first-child { left: -14px; } .t-boardingpass .perf i:last-child { right: -14px; }
.t-boardingpass .stub { border-radius: 0 0 6px 6px; padding-bottom: 6px; }
.t-boardingpass .stub::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 6px; background: linear-gradient(135deg, var(--desk) 50%, transparent 50%) 0 0 / 10px 6px repeat-x, linear-gradient(225deg, var(--desk) 50%, transparent 50%) 0 0 / 10px 6px repeat-x; }
.t-boardingpass .hole { position: absolute; right: 26px; top: 20px; width: 18px; height: 18px; border-radius: 50%; background: var(--desk); box-shadow: inset 0 2px 3px rgba(0,0,0,.35); }
.t-boardingpass .sh { display: flex; justify-content: space-between; align-items: baseline; padding-right: 40px; margin-bottom: 8px; }
.t-boardingpass .sh b { font: 700 18px/1 'Aeonik Extended', 'Helvetica Neue', sans-serif; }
.t-boardingpass .svc { display: grid; grid-template-columns: 58px 1fr; padding: 4px 0; font-size: 17px; }
.t-boardingpass .svc span:first-child { font-weight: 700; font-variant-numeric: tabular-nums; }
.t-boardingpass .svc .n { color: #5b5c63; }
.t-boardingpass .code { display: grid; gap: 2px; margin: 16px auto 0; width: 360px; }
.t-boardingpass .code div { height: var(--bh); }
.t-boardingpass .codeno { text-align: center; font: 600 12px/1 Menlo, monospace; letter-spacing: .24em; margin-top: 8px; color: #3c3c42; }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const timed = c.today.filter((e) => e.t24);
      const dep = timed.length ? timed[0].t24 : ed.time24;
      const arr = c.today.length ? c.today[c.today.length - 1].t24 || "EOD" : "—";
      const conf = needs.length ? `<div class="sec" style="padding-top:4px"><span class="lbl acc">Awaiting your confirmation · ${needs.length}</span>${needs.map((d, i) => `<div class="it" data-role="body"><span class="lbl">Connection ${i + 1}<br><b class="lbl acc">${esc(d.verb)}</b></span><span>${esc(d.label)}${d.note ? `<span class="n">${esc(d.note)}</span>` : ""}</span></div>`).join("")}</div>` : "";
      const role = (i, e) => (!e.t24 ? "Cargo" : i === 0 ? "Boarding" : "Connection");
      const itin = c.today.length ? `<div class="sec" style="padding-top:4px"><span class="lbl">Itinerary · today</span>${c.today.map((e, i) => `<div class="it" data-role="body"><span class="lbl acc">${role(i, e)}</span><span><span class="tm">${e.t24 ? esc(e.t24) : "EOD"}</span>${esc(e.label)}${e.note ? `<span class="n">${esc(e.note)}</span>` : ""}</span></div>`).join("")}</div>` : "";
      const s = c.stats;
      const stats = s ? `<div class="sec" style="padding-top:0"><div class="stats"><div><b>${s.done}</b><span class="lbl">done</span></div>${s.mail ? `<div><b>${s.mail}</b><span class="lbl">mail cleared</span></div>` : ""}${s.focus ? `<div><b>${esc(s.focus)}</b><span class="lbl">focus</span></div>` : ""}</div></div>` : "";
      const svc = c.overnight.length ? `<span class="lbl">Services completed in transit</span>${c.overnight.map((e) => `<div class="svc" data-role="body"><span>${esc(e.t24)}</span><span>${esc(e.label)}${e.note ? ` <span class="n">— ${esc(e.note)}</span>` : ""}</span></div>`).join("")}` : "";
      const bars = barcode(ed.editionNo, skin.code.rows, 360);
      const bh = skin.code.rows === 1 ? "64px" : "9px";
      const flight = `GA-${String(ed.editionNo).padStart(3, "0")}`;
      return `<article class="t-boardingpass" style="--liv:${skin.livery.liv}; --acc:${skin.livery.acc}; --accOn:${skin.livery.accOn}; --paper:${skin.card.paper}; --desk:${skin.card.desk}; --bh:${bh}">
<div class="pass">
  <div class="body">${grain("bp2-g", 0.9)}${guilloche(skin.livery.acc + "33")}
    <div class="top"><div><span class="air">GAIA AIR</span><small>Briefing class</small></div><div class="r">Boarding pass<b>${flight}</b></div></div>
    <div class="sec">
      <div class="route"><div><b>${esc(dep)}</b><span class="lbl">Boarding</span></div><div class="path"><i style="left:0"></i><i style="left:calc(50% - 7px)"></i><i style="right:0"></i></div><div class="r"><b>${esc(arr)}</b><span class="lbl">Arrival</span></div></div>
    </div>
    <div class="sec" style="padding-top:0"><span class="lbl acc">Captain's note</span><p class="deck">${esc(ed.deck)}</p></div>
    <div class="sec" style="padding-top:0"><div class="grid"><div><span class="lbl">Passenger</span><b>${ed.recipient ? esc(ed.recipient.name) : "You"}</b></div><div><span class="lbl">Flight</span><b>${flight}</b></div><div><span class="lbl">Date</span><b>${pad2(ed.day)} ${esc(ed.monthShort.toUpperCase())}</b></div><div><span class="lbl">Gate</span><b>${esc(ed.weekday.slice(0, 1))}${ed.day}</b></div><div><span class="lbl">Seat</span><b class="acc">${ed.editionNo}A</b></div></div></div>
    ${conf}${itin}${stats}
  </div>
  <div class="perf"><i></i><i></i></div>
  <div class="stub"><div class="sec"><i class="hole" aria-hidden="true"></i>
    <div class="sh"><b>GAIA AIR</b><span class="lbl">${flight} · seat ${ed.editionNo}A · ${pad2(ed.day)} ${esc(ed.monthShort.toUpperCase())}</span></div>
    ${svc}
    <div class="code">${bars.map((g) => `<div style="background:${g}"></div>`).join("")}</div>
    <p class="codeno">GA${ed.editionNo} ${ed.time24.replace(":", "")} RANDERIYA/A</p>
  </div></div>
</div></article>`;
    },
  });
})();
