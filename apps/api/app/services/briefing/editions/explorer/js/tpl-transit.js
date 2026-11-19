/* ============================================================================
   tpl-transit.js (round 2) — The Line Guide and The Boarding Pass on a 540 px
   portrait canvas (export at 3x). Body 17 px or larger.
   Reading order: headline -> the brief's blocks in GAIA's order -> figures.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const grain = (id, freq) =>
    `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  const pad2 = (n) => String(n).padStart(2, "0");

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
        { id: "overpass", label: "Overpass", stack: "'Overpass', sans-serif" },
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
.t-metromap .sub { font-size: 14px; color: var(--soft); margin-top: 4px; }
.t-metromap .notice { margin-top: 20px; display: grid; grid-template-columns: auto 1fr; gap: 12px; align-items: baseline; background: var(--panel); padding: 14px 16px; border-radius: 3px; }
.t-metromap .notice b { font-size: 14px; letter-spacing: 0; color: var(--decText); }
.t-metromap .notice p { font-size: 20px; line-height: 1.3; font-weight: 500; }
.t-metromap .route { margin-top: 18px; }
.t-metromap .ln { position: relative; padding-left: calc(var(--x) + 40px); }
.t-metromap .ln::before { content: ""; position: absolute; left: calc(var(--x) - 5px); top: 0; bottom: 0; width: 10px; background: var(--c); }
.t-metromap .ln.dash::before { background: repeating-linear-gradient(var(--c) 0 14px, transparent 14px 22px); }
.t-metromap .ix { display: block; width: 100%; height: 54px; }
.t-metromap { --rs-font: var(--face); --rs-font-h: var(--face); --rs-ink: var(--ink); --rs-muted: var(--soft); --rs-acc: var(--decText); --rs-base: 15px; --rs-kick: var(--decText); }
#root .t-metromap .ln > .rs-sec { padding-block: 22px 18px; }
.t-metromap .term { display: block; width: 100%; height: 40px; }
.t-metromap .route + .route, .t-metromap .mpanel + .route, .t-metromap .notice + .route { margin-top: 18px; }
.t-metromap .notice.mlead { display: block; margin-top: 16px; padding: 18px 16px; }
#root .t-metromap .mlead > .rs-lead { padding-block: 0; }
.t-metromap .notice.mquote { margin-top: 22px; }
.t-metromap .notice .mq { font-size: 18px; line-height: 1.35; font-weight: 500; text-wrap: pretty; }
.t-metromap .notice .msm { font-size: 15px; color: var(--soft); margin-top: 6px; }
.t-metromap .mpanel { margin-top: 22px; border: 1.5px solid var(--ink); border-radius: 4px; padding: 14px 16px; font-size: 15px; }
.t-metromap .mpanel h3 { display: flex; justify-content: space-between; gap: 12px; font-size: 15px; letter-spacing: 0; margin-bottom: 8px; }
.t-metromap .mr { font-weight: 400; color: var(--soft); white-space: nowrap; }
.t-metromap .msay { font-size: 16px; line-height: 1.35; margin-bottom: 10px; text-wrap: pretty; }
.t-metromap .mkey { display: flex; flex-wrap: wrap; gap: 4px 18px; margin-top: 10px; }
.t-metromap .mkey i { display: inline-block; width: 26px; height: 6px; vertical-align: middle; margin-right: 8px; }
.t-metromap .msoft { color: var(--soft); }
.t-metromap .mring { display: inline-block; width: 14px; height: 14px; border-radius: 50%; border: 3.5px solid; vertical-align: -2px; margin-right: 8px; }
.t-metromap .legend { margin-top: 22px; border: 1.5px solid var(--ink); border-radius: 4px; padding: 14px 16px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; font-size: 15px; }
.t-metromap .legend h3 { grid-column: 1 / -1; font-size: 15px; letter-spacing: 0; }
.t-metromap .ride { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 6px; padding-top: 12px; border-top: 1px solid var(--soft); line-height: 1.3; }
.t-metromap .ride b { display: block; font-size: 28px; line-height: 1.05; font-weight: 700; margin-bottom: 2px; }
.t-metromap .legend i { display: inline-block; width: 26px; height: 6px; vertical-align: middle; margin-right: 8px; }
.t-metromap .legend b { font-variant-numeric: tabular-nums; }
.t-metromap .conn { margin-top: 22px; }
.t-metromap .conn h3 { font-size: 15px; letter-spacing: 0; margin-bottom: 8px; }
.t-metromap .conn > div { display: flex; flex-wrap: wrap; gap: 8px; }
.t-metromap .cbox { display: inline-flex; align-items: center; border: 2.5px solid var(--ink); background: #ffffff; border-radius: 4px; padding: 2px 8px; font-size: 14px; font-weight: 700; letter-spacing: 0; color: #1b1c22; }
.t-metromap .cbox .cl { width: 15px; height: 15px; margin-right: 6px; color: #1b1c22; }
`,
    render(ed, skin) {
      const B = EXPLORER.blocks;
      const L = skin.livery;
      const face = skin.face.stack;
      const W = 449; // inside a panel's border and padding
      // Each run of reading blocks is a line down the page: what waits on you rides the dashed
      // decision line, your day the day line, GAIA's work the night line; interchanges join them.
      const DEC = { x: 92, c: L.dec, cls: "dash", name: "Decisions, your call" };
      const DAY = { x: 40, c: L.day, cls: "", name: "Your day ahead" };
      const NIGHT = { x: 92, c: L.night, cls: "", name: "GAIA's work, done" };
      const lineOf = (b) => (b.kind === "calendar" ? DAY : b.items.some((it) => it.verb) ? DEC : NIGHT);
      const ix = (l, next) =>
        `<svg class="ix" viewBox="0 0 484 54" preserveAspectRatio="none" aria-hidden="true"><path d="M${l.x} 0 V12 L${next.x} 42 V54" fill="none" stroke="${l.c}" stroke-width="10" ${l.cls ? 'stroke-dasharray="14 8"' : ""}/><path d="M${next.x} 42 V54" stroke="${next.c}" stroke-width="10"/><circle cx="${(l.x + next.x) / 2}" cy="27" r="12" fill="#ffffff" stroke="var(--ink)" stroke-width="5"/></svg>`;
      const terminus = (l) =>
        `<svg class="term" viewBox="0 0 484 40" preserveAspectRatio="none" aria-hidden="true"><path d="M${l.x} 0 V16" stroke="${l.c}" stroke-width="10" ${l.cls ? 'stroke-dasharray="14 8"' : ""}/><circle cx="${l.x}" cy="24" r="11" fill="var(--ground)" stroke="var(--ink)" stroke-width="5"/></svg>`;
      const seg = (l, body) => `<div class="ln ${l.cls}" style="--x:${l.x}px; --c:${l.c}">${body}</div>`;
      const panel = (kind, title, right, body) =>
        `<div class="mpanel" data-block="${kind}"><h3><span>${title}</span><span class="mr">${right}</span></h3>${body}</div>`;
      const key = (items) => `<p class="mkey">${items.map(([bg, t]) => (bg ? `<span><i style="background:${bg}"></i>${t}</span>` : `<span class="msoft">${t}</span>`)).join("")}</p>`;
      const ST = { font: face, size: 13, ink: "var(--ink)", soft: "var(--soft)", weight: 700 };
      const chartFills = [L.day, L.night, L.dec];
      const unitLine = (c) => esc(c.range ? (c.unit ? `${c.unit} per day` : "per day") : B.facts(c));
      const chart = (c) => {
        let plot;
        if (c.chart === "line") {
          plot = B.line(c, { ...ST, w: W, h: 136, rule: "rgba(0,0,0,.12)", base: "var(--ink)", lines: [{ color: L.night, width: 4 }, { color: L.day, width: 4 }, { color: L.dec, width: 4 }], gutter: 26, dot: 6, right: 22 });
          plot = plot.replace(/<circle ([^>]*?) r="6" fill="[^"]*"\/>/g, `<circle $1 r="6" fill="#ffffff" stroke="var(--ink)" stroke-width="3"/>`);
        } else if (c.chart === "spark") {
          plot = B.spark(c, { ...ST, w: W, h: 56, line: L.night, lineW: 4, dot: 5 });
        } else {
          plot = B.bars(c, { ...ST, w: W, h: 150, rule: "var(--ink)", ruleW: 1.5, fills: c.series.length > 1 ? chartFills : [L.night], gapRatio: 0.4 });
        }
        const lines = c.chart === "line" ? [L.night, L.day, L.dec] : chartFills;
        const names = c.series.length > 1 ? c.series.map((sr, k) => [lines[k % 3], `${esc(sr.name)}, ${esc(sr.total)}`]) : [];
        const title = c.chart === "bar" || c.chart === "stacked_bar" ? `Ridership · ${esc(c.title)}` : esc(c.title);
        return panel("chart", title, esc(c.range || ""), `<p class="msay">${esc(c.takeaway)}</p>${plot}${key([...names, ["", unitLine(c)]])}`);
      };
      // A goal is a line with a station per step: built to where you are, dashed to its terminus.
      const progress = (p) => {
        const n = Math.min(p.total, 12);
        const on = p.total > 12 ? Math.round((p.done / p.total) * n) : p.done;
        const pad = 12, y = 22, step = (W - 2 * pad) / Math.max(n - 1, 1);
        const X = (i) => pad + i * step;
        let g = on > 1 ? `<rect x="${X(0)}" y="${y - 5}" width="${X(on - 1) - X(0)}" height="10" fill="${L.day}"/>` : "";
        if (on < n) g += `<line x1="${on ? X(on - 1) + 10 : X(0)}" y1="${y}" x2="${X(n - 1)}" y2="${y}" stroke="${L.day}" stroke-width="10" stroke-dasharray="14 8"/>`;
        for (let i = 0; i < n; i++) {
          g += i < on
            ? `<rect x="${X(i) - 3}" y="${y + 5}" width="6" height="9" fill="${L.day}"/>`
            : `<circle cx="${X(i)}" cy="${y}" r="8" fill="var(--ground)" stroke="${L.day}" stroke-width="4"/>`;
          if (p.total <= 12) g += B.txt(X(i), y + 30, i + 1, { ...ST, fill: i < on ? "var(--ink)" : "var(--soft)" });
        }
        const plot = `<svg class="xb-plot" width="${W}" height="56" viewBox="0 0 ${W} 56" aria-hidden="true">${g}</svg>`;
        return panel("progress", esc(p.statement), `${p.done} of ${p.total} done`, `${plot}<p class="mkey"><span><i style="background:${L.day}"></i>done, ${p.done}</span><span><b class="mring" style="border-color:${L.day}"></b>open, ${p.total - p.done}</span></p>`);
      };
      const R = {
        lead: (b) => `<div class="notice mlead">${B.lead(b, { kicker: "Interchange", mode: "color" })}</div>`,
        chart,
        progress,
        quote: (q) => `<div class="notice mquote" data-block="quote"><b>Passenger&nbsp;notice</b><div><p class="mq">&ldquo;${esc(q.text)}&rdquo;</p><p class="msm">${esc(q.author)}, ${esc(q.app)}</p></div></div>`,
        note: (n) => `<div class="notice mquote" data-block="note"><b>Service&nbsp;note</b><p class="mq">${esc(n.text)}</p></div>`,
      };
      // Runs of items and calendar become one route; any other block closes it at a terminus.
      const out = [];
      let run = [];
      const flush = () => {
        if (!run.length) return;
        const html = run.map((b, i) => {
          const l = lineOf(b);
          const body = b.kind === "calendar"
            ? B.section(b.events.some((e) => e.day) ? "The week ahead" : "Today", B.events(b, { clock: "t24", allDay: "All day", mode: "color" }))
            : B.section(b.heading, B.items(b, { mode: "color" }));
          const next = run[i + 1];
          return seg(l, body) + (next ? ix(l, lineOf(next)) : terminus(l));
        }).join("");
        out.push(`<div class="route">${html}</div>`);
        run = [];
      };
      for (const b of ed.blocks) {
        if (b.kind === "items" || b.kind === "calendar") run.push(b);
        else {
          flush();
          out.push(R[b.kind](b));
        }
      }
      flush();
      const used = [DEC, DAY, NIGHT].filter((l) => ed.blocks.some((b) => (b.kind === "items" || b.kind === "calendar") && lineOf(b) === l));
      const s = ed.stats;
      const legend = used.length || s
        ? `<div class="legend"><h3>Line guide</h3>${used.map((l) => `<span><i style="background:${l.cls ? `repeating-linear-gradient(90deg, ${l.c} 0 8px, transparent 8px 12px)` : l.c}"></i>${l.name}</span>`).join("")}${s ? `<div class="ride"><span><b>${s.done}</b>done yesterday${s.you && s.gaia ? `<br>you ${s.you} / GAIA ${s.gaia}` : ""}</span>${s.mail ? `<span><b>${s.mail}</b>emails handled</span>` : ""}${s.focus ? `<span><b>${esc(s.focus)}</b>focus time today</span>` : ""}</div>` : ""}</div>`
        : "";
      // The apps the brief read are its connecting services, boxed like station names.
      const conn = ed.sources.length
        ? `<div class="conn" data-block="sources"><h3>Connecting services</h3><div>${ed.sources.map((x) => `<span class="cbox">${B.logo(x.logo, { mode: "color", cls: "cl" })}${esc(x.name)}</span>`).join("")}</div></div>`
        : "";
      return `<article class="t-metromap" style="--ground:${skin.ground.ground}; --ink:${skin.ground.ink}; --soft:${skin.ground.soft}; --panel:${skin.ground.panel}; --day:${L.day}; --night:${L.night}; --dec:${L.dec}; --decText:${L.decText}; --face:${skin.face.stack}">
${grain("mt-g", 0.9)}
<div class="hd"><div class="roundel"><span>${esc(ed.weekday.slice(0, 3).toUpperCase())}</span></div><div><div class="auth">GAIA transit authority</div><h1>The ${esc(ed.weekday)} Brief</h1><p class="sub">Line guide No ${ed.editionNo} · ${esc(ed.dateLong)} · ${esc(ed.time)}</p></div></div>
<div class="notice"><b>Service notice</b><p>${esc(ed.deck)}</p></div>
${EXPLORER.fold(out).join("")}
${legend}${conn}
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
        { id: "midnight", label: "midnight + sunflower", liv: "#0a1d4a", acc: "#f0a500", accOn: "#8c5e00" },
        { id: "sky", label: "sky blue", liv: "#0070b8", acc: "#1590d8", accOn: "#00639f" },
        { id: "signal", label: "signal red", liv: "#c8102e", acc: "#d8213c", accOn: "#ad0d27" },
        { id: "graphite", label: "graphite + champagne", liv: "#1d1e22", acc: "#b99a5c", accOn: "#7a6234" },
      ],
      card: [
        { id: "white", label: "white card", paper: "#fbfaf6", desk: "#c9c6bf" },
        { id: "ivory", label: "ivory card", paper: "#f7f1e2", desk: "#b9b2a3" },
      ],
      code: [
        { id: "linear", label: "linear barcode", symbology: "code128", modulePx: 1 },
        { id: "stacked", label: "stacked PDF417", symbology: "pdf417", modulePx: 2 },
      ],
    },
    css: `
.t-boardingpass { position: relative; box-sizing: border-box; width: 540px; padding: 34px 26px 44px; background: radial-gradient(120% 80% at 30% 0%, color-mix(in srgb, var(--desk) 80%, #ffffff) 0%, var(--desk) 70%); color: #1b1c22; font: 400 17px/1.4 'TeX Gyre Heros', sans-serif; --ink: #1b1c22; }
.t-boardingpass * { box-sizing: border-box; margin: 0; padding: 0; }
.t-boardingpass .pass { position: relative; isolation: isolate; transform: rotate(-.6deg); filter: drop-shadow(0 14px 18px rgba(0,0,0,.28)) drop-shadow(0 2px 3px rgba(0,0,0,.2)); }
.t-boardingpass .body, .t-boardingpass .stub { position: relative; background: var(--paper); overflow: hidden; }
.t-boardingpass .body { border-radius: 14px 14px 0 0; }
.t-boardingpass .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .1; }
.t-boardingpass .guil { position: absolute; left: 0; right: 0; top: 150px; width: 100%; height: 200px; opacity: .5; pointer-events: none; }
.t-boardingpass .top { position: relative; background: var(--liv); color: #ffffff; padding: 18px 22px; display: flex; justify-content: space-between; align-items: center; }
.t-boardingpass .air { font: 700 24px/1 'Aeonik Extended', 'TeX Gyre Heros', sans-serif; letter-spacing: .02em; }
.t-boardingpass .top small { display: block; font-size: 14px; font-weight: 700; letter-spacing: 0; margin-top: 6px; opacity: .9; }
.t-boardingpass .top .r { text-align: right; font-size: 14px; font-weight: 700; letter-spacing: 0; }
.t-boardingpass .top .r b { display: block; font-size: 19px; letter-spacing: .04em; margin-top: 4px; }
.t-boardingpass .sec { position: relative; padding: 18px 22px; }
.t-boardingpass .lbl { display: block; font-size: 15px; font-weight: 700; letter-spacing: 0; color: #5b5c63; }
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
.t-boardingpass .stats { display: grid; grid-template-columns: repeat(var(--n), 1fr); border: 1.5px solid #dcd7cb; border-radius: 6px; margin-top: 4px; }
.t-boardingpass .stats .sub { font-weight: 400; margin-top: 2px; }
.t-boardingpass .stats.one div { display: flex; align-items: baseline; gap: 12px; text-align: left; padding: 10px 16px; }
.t-boardingpass .stats.one .sub { margin: 0 0 0 auto; }
.t-boardingpass .bsrc { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.t-boardingpass .bsrc .lbl { font-weight: 400; max-width: 300px; }
.t-boardingpass .blogos { display: flex; gap: 10px; flex: none; }
.t-boardingpass .blogos .bl { width: 18px; height: 18px; color: #1b1c22; }
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
.t-boardingpass .sh b { font: 700 18px/1 'Aeonik Extended', 'TeX Gyre Heros', sans-serif; }
.t-boardingpass .it > span:last-child { text-wrap: pretty; }
.t-boardingpass { --rs-font: 'TeX Gyre Heros', sans-serif; --rs-ink: #1b1c22; --rs-muted: #5b5c63; --rs-acc: var(--accOn); --rs-kick: var(--accOn); --rs-kick-case: none; --rs-kick-track: 0; --rs-base: 15px; }
.t-boardingpass .bsec { padding-block: 0; }
.t-boardingpass .bsec + .bsec { border-top: 1px solid #ebe7dd; }
#root .t-boardingpass .bsec > .rs-lead { padding-block: 24px 20px; }
.t-boardingpass .bsec[data-block] { padding-block: 22px; }
.t-boardingpass .bpq { margin-top: 6px; font-size: 19px; line-height: 1.35; font-weight: 600; letter-spacing: -.01em; text-wrap: pretty; }
.t-boardingpass .bpq .n { display: block; font-size: 15px; font-weight: 400; letter-spacing: 0; color: #5b5c63; margin-top: 4px; }
.t-boardingpass .bpnote { border-top: 0; padding: 0; }
.t-boardingpass .bstats { padding-top: 4px; }
.t-boardingpass .stub .sh { margin-bottom: 12px; }
.t-boardingpass .bplog { margin-top: 26px; transform: rotate(.4deg); }
.t-boardingpass .bplog .body { border-radius: 14px; padding-bottom: 6px; }
.t-boardingpass .bplog .sec + .sec { border-top: 1px solid #ebe7dd; }
.t-boardingpass .bph { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; }
.t-boardingpass .bph .lbl:first-child { color: #1b1c22; }
.t-boardingpass .bpsay { margin-top: 4px; text-wrap: pretty; }
.t-boardingpass .bpkey { display: flex; gap: 16px; font-size: 15px; color: #5b5c63; margin: 8px 0 12px; }
.t-boardingpass .bpkey i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; }
.t-boardingpass .bpkey span:last-child { margin-left: auto; }
.t-boardingpass .bpprog { margin: 6px 0 10px; }
.t-boardingpass .bpprog b { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; margin-right: 4px; }
.t-boardingpass .code { margin: 16px auto 0; height: 64px; }
.t-boardingpass .code svg { display: block; width: 100%; height: 100%; }
.t-boardingpass .codeno { text-align: center; font: 600 13px/1 'JetBrains Mono', monospace; letter-spacing: .24em; margin-top: 8px; color: #3c3c42; }
`,
    render(ed, skin) {
      const B = EXPLORER.blocks;
      const ink = "#1b1c22", grey = "#5b5c63", hair = "#e3dfd5", box = "#dcd7cb";
      const face = "'TeX Gyre Heros', sans-serif";
      const W = 444; // the card's measure inside its section padding
      const cal = ed.blocks.find((b) => b.kind === "calendar" && !b.events.some((e) => e.day));
      // Departure and arrival are the day's first and last timed starts, the rows shown or not.
      const dep = cal && cal.first ? cal.first : ed.time24;
      const last = cal ? cal.last || "EOD" : "—";
      const arr = last === dep ? "EOD" : last;
      // The pass is never cut: reading blocks ride its body, charts and the goal a flight log card
      // from the same airline lying under it, and a closing group of GAIA's done work the stub.
      const reading = ed.blocks.filter((b) => b.kind !== "chart" && b.kind !== "progress");
      const tail = reading[reading.length - 1];
      const onStub = tail && tail.kind === "items" && tail.items.every((it) => it.outcome) ? tail : null;
      const ST = { font: face, size: 14, weight: 400, valueWeight: 700, ink, soft: grey };
      const head = (l, r) => `<div class="bph"><span class="lbl">${l}</span><span class="lbl">${r}</span></div>`;
      const key = (c, fills) =>
        `<div class="bpkey">${c.series.length > 1 ? c.series.map((sr, k) => `<span><i style="background:${fills[k % fills.length]}"></i>${esc(sr.name)} · ${esc(sr.total)}</span>`).join("") : ""}<span>${esc(c.range ? (c.unit ? `${c.unit} per day` : "per day") : B.facts(c))}</span></div>`;
      const fills = ["var(--liv)", "var(--acc)", grey];
      const R = {
        lead: (b) => `<div class="sec bsec">${B.lead(b, { kicker: "Priority boarding", mode: "color" })}</div>`,
        items: (b) => (b === onStub ? "" : `<div class="sec bsec">${B.section(b.heading, B.items(b, { mode: "color" }))}</div>`),
        calendar: (b) => `<div class="sec bsec">${B.section(b.events.some((e) => e.day) ? "The week ahead" : "Itinerary today", B.events(b, { clock: "t24", allDay: "All day", mode: "color" }))}</div>`,
        quote: (q) => `<div class="sec bsec" data-block="quote"><span class="lbl acc">Message for the passenger</span><p class="bpq">&ldquo;${esc(q.text)}&rdquo;<span class="n">${esc(q.author)}, ${esc(q.app)}</span></p></div>`,
        note: (n) => `<div class="sec bsec" data-block="note"><div class="it bpnote"><span class="lbl acc">Crew note</span><span>${esc(n.text)}</span></div></div>`,
        chart: (c) => {
          const plot = c.chart === "line"
            ? B.line(c, { ...ST, w: W, h: 150, rule: hair, base: box, lines: [{ color: "var(--accOn)", width: 2.5 }, { color: "var(--liv)", width: 2.5 }, { color: grey, width: 2, dash: "4 3" }], dot: 4 })
            : c.chart === "spark"
              ? B.spark(c, { ...ST, w: W, h: 56, line: "var(--accOn)", lineW: 2.5 })
              : B.bars(c, { ...ST, w: W, h: 150, rule: box, ruleW: 1.5, fills: c.series.length > 1 ? fills : ["var(--liv)"], gapRatio: 0.42 });
          const lineFills = ["var(--accOn)", "var(--liv)", grey];
          return `<div class="sec" data-block="chart">${head(esc(c.title), esc(c.range || ""))}<p class="bpsay">${esc(c.takeaway)}</p>${key(c, c.chart === "line" ? lineFills : fills)}${plot}</div>`;
        },
        progress: (p) => `<div class="sec" data-block="progress">${head(esc(p.statement), "")}<p class="bpprog"><b>${p.done}</b> of ${p.total} done</p>${B.cells(p, { w: W, h: 14, gap: 6, on: "var(--acc)", off: hair })}</div>`,
      };
      const body = B.layout({ blocks: reading }, R);
      const log = B.layout({ blocks: ed.blocks.filter((b) => b.kind === "chart" || b.kind === "progress") }, R);
      const s = ed.stats;
      // Only the figures the brief has: several share the box in equal cells, a lone one reads across it.
      const figs = [
        s && { v: s.done, l: "done yesterday", sub: s.you && s.gaia ? `you ${s.you} · GAIA ${s.gaia}` : "" },
        ed.awaiting && { v: ed.awaiting, l: "need you", sub: "" },
        s && s.mail && { v: s.mail, l: "emails handled", sub: "" },
        s && s.focus && { v: esc(s.focus), l: "focus", sub: "" },
      ].filter(Boolean);
      const fig = (f) => `<div><b>${f.v}</b><span class="lbl">${f.l}</span>${f.sub ? `<span class="lbl sub">${f.sub}</span>` : ""}</div>`;
      const stats = figs.length
        ? `<div class="sec bstats"><div class="stats${figs.length === 1 ? " one" : ""}" style="--n:${figs.length}">${figs.map(fig).join("")}</div></div>`
        : "";
      // The apps the brief read operate the flight: a line closing the log card, else the pass body.
      const andList = (xs) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);
      const operated = ed.sources.length
        ? `<div class="sec bsrc" data-block="sources"><span class="lbl">Operated with your ${esc(andList(ed.sources.map((x) => x.name)))}</span><span class="blogos">${ed.sources.map((x) => B.logo(x.logo, { mode: "color", cls: "bl" })).join("")}</span></div>`
        : "";
      const bars = ed.codes[skin.code.symbology];
      const flight = `GA-${String(ed.editionNo).padStart(3, "0")}`;
      const date = `${pad2(ed.day)} ${esc(ed.monthShort.toUpperCase())}`;
      const names = ed.recipient ? ed.recipient.name.toUpperCase().split(/\s+/) : [];
      const pax = names.length > 1 ? `${names[names.length - 1]}/${names[0][0]}` : names.join("");
      const logCard = log.length
        ? `<div class="pass bplog"><div class="body"><div class="top"><div><span class="air">GAIA AIR</span><small>Flight log</small></div><div class="r">${flight}<b>${date}</b></div></div>${log.join("")}${operated}</div></div>`
        : "";
      return `<article class="t-boardingpass" style="--liv:${skin.livery.liv}; --acc:${skin.livery.acc}; --accOn:${skin.livery.accOn}; --paper:${skin.card.paper}; --desk:${skin.card.desk}">
<div class="pass" data-paper>
  <div class="body">${grain("bp2-g", 0.9)}${guilloche(skin.livery.acc + "33")}
    <div class="top"><div><span class="air">GAIA AIR</span><small>Briefing class</small></div><div class="r">Boarding pass<b>${flight}</b></div></div>
    <div class="sec">
      <div class="route"><div><b>${esc(dep)}</b><span class="lbl">Boarding</span></div><div class="path"><i style="left:0"></i><i style="left:calc(50% - 7px)"></i><i style="right:0"></i></div><div class="r"><b>${esc(arr)}</b><span class="lbl">Arrival</span></div></div>
    </div>
    <div class="sec" style="padding-top:0" data-fold><span class="lbl acc">Captain's note</span><p class="deck">${esc(ed.deck)}</p></div>
    <div class="sec" style="padding-top:0"><div class="grid"><div><span class="lbl">Passenger</span><b>${ed.recipient ? esc(ed.recipient.name) : "You"}</b></div><div><span class="lbl">Flight</span><b>${flight}</b></div><div><span class="lbl">Date</span><b>${date}</b></div><div><span class="lbl">Gate</span><b>${esc(ed.weekday.slice(0, 1))}${ed.day}</b></div><div><span class="lbl">Seat</span><b class="acc">${ed.editionNo}A</b></div></div></div>
    ${body.join("")}${stats}${log.length ? "" : operated}
  </div>
  <div class="perf"><i></i><i></i></div>
  <div class="stub"><div class="sec"><i class="hole" aria-hidden="true"></i>
    <div class="sh"><b>GAIA AIR</b><span class="lbl">${flight} · seat ${ed.editionNo}A · ${date}</span></div>
    ${onStub ? B.section(onStub.heading, B.items(onStub, { mode: "color" })) : ""}
    <div class="code" style="width:min(100%, ${bars.width * skin.code.modulePx}px)">${EXPLORER.code(bars, "bars")}</div>
    <p class="codeno">GA${ed.editionNo} ${ed.time24.replace(":", "")}${pax ? ` ${esc(pax)}` : ""}</p>
  </div></div>
</div>${logCard}</article>`;
    },
  });
})();
