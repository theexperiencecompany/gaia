/* ================================================================
   tpl-tech.js — two "techy" templates for the Edition Explorer.
   Register: flightplan (a drafted elevation of the day, chalk on
   blue paper) and instrument (Braun/Rams instrument panel as print).
   No terminal-green, no glow, no cyberpunk — real drafting heritage.
   ================================================================ */

/* ---- shared local helpers (module-scoped, deterministic) ---- */
function _two(n) {
  return String(n).padStart(2, "0");
}
function _esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
function _sub(note) {
  return note ? `<span class="sub">${_esc(note)}</span>` : "";
}
/* "13:30" -> 13.5 (decimal hours) */
function _hr(t24) {
  const [h, m] = t24.split(":").map(Number);
  return h + m / 60;
}
/* decimal hours -> "HH:MM" */
function _clock(hr) {
  const h = Math.floor(hr + 1e-6);
  const m = Math.round((hr - h) * 60);
  return `${_two(h)}:${_two(m)}`;
}

/* ================================================================
   1) FLIGHTPLAN — the day drawn as a technical elevation.
   A single thick datum (06:00–24:00). Meetings are dimensioned
   spans that rise off the datum on shelf-leaders. The overnight
   work is a hatched section below grade with keyed callouts. The
   free evening is a long open dimension. The EOD ship is a dashed
   hidden-line box keyed to a Detail A blow-up. One ruled title
   block carries all the metadata. Chalk lines on blue paper — or,
   on the diazo skin, dark ink on near-white stock.
   ================================================================ */
EXPLORER.register({
  id: "flightplan",
  name: "The Blueprint",
  axes: {
    ground: [
      {
        id: "prussian",
        label: "prussian ultramarine",
        paper: "#17398a",
        ink: "#eaf1fb",
        soft: "#bcd0ee",
        rgb: "234,241,251",
      },
      {
        id: "washed",
        label: "cyanotype turquoise",
        paper: "#0e6379",
        ink: "#eef8fb",
        soft: "#bfe1ec",
        rgb: "238,248,251",
      },
      {
        id: "diazo",
        label: "diazo whiteprint",
        paper: "#eef4f6",
        ink: "#06455e",
        soft: "#2d6b80",
        rgb: "6,69,94",
      },
    ],
    face: [
      {
        id: "helv",
        label: "Helvetica lettering",
        stack: "'Helvetica Neue',Helvetica,Arial,sans-serif",
        track: "0.22em",
      },
      {
        id: "aeonik",
        label: "Aeonik Extended",
        stack: "'Aeonik Extended','Helvetica Neue',sans-serif",
        track: "0.14em",
      },
    ],
    grid: [
      {
        id: "grid",
        label: "faint field grid",
        showGrid: true,
        showCrop: false,
      },
      {
        id: "crop",
        label: "corner crop marks",
        showGrid: false,
        showCrop: true,
      },
    ],
    hatch: [
      { id: "diag", label: "diagonal section", cross: false },
      { id: "cross", label: "cross-hatched section", cross: true },
    ],
  },
  css: `
    .t-flightplan{
      position:relative; box-sizing:border-box; width:100%; min-height:1400px; overflow:hidden;
      background:var(--paper,#17398a); color:var(--ink,#eaf1fb);
      font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;
      -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
      font-variant-numeric:tabular-nums lining-nums;
      padding:clamp(38px,4.4vw,70px);
    }
    .t-flightplan *{ box-sizing:border-box; }
    .t-flightplan .obj{ background:var(--ink); }
    .t-flightplan .dim{ background:rgba(var(--rgb),0.66); }

    /* ---- frame + crop marks ---- */
    .t-flightplan .frame{
      position:absolute; inset:20px; border:2px solid rgba(var(--rgb),0.62); pointer-events:none;
    }
    .t-flightplan .frame::after{
      content:""; position:absolute; inset:7px; border:1px solid rgba(var(--rgb),0.22);
    }
    .t-flightplan .crop{ position:absolute; width:34px; height:34px; pointer-events:none; }
    .t-flightplan .crop::before{ content:""; position:absolute; left:0; top:16px; width:34px; height:1.5px; background:rgba(var(--rgb),0.7); }
    .t-flightplan .crop::after{ content:""; position:absolute; top:0; left:16px; width:1.5px; height:34px; background:rgba(var(--rgb),0.7); }
    .t-flightplan .crop.tl{ left:8px; top:8px; } .t-flightplan .crop.tr{ right:8px; top:8px; }
    .t-flightplan .crop.bl{ left:8px; bottom:8px; } .t-flightplan .crop.br{ right:8px; bottom:8px; }

    .t-flightplan .sheet{ position:relative; width:100%; max-width:1080px; margin:0 auto; }

    /* ---- drawing zone ---- */
    .t-flightplan .draw{ position:relative; height:800px; }
    .t-flightplan .grid{
      position:absolute; inset:0; pointer-events:none; opacity:0.9;
      background-image:
        repeating-linear-gradient(to right, rgba(var(--rgb),0.10) 0 1px, transparent 1px 48px),
        repeating-linear-gradient(to bottom, rgba(var(--rgb),0.10) 0 1px, transparent 1px 48px);
      -webkit-mask-image:linear-gradient(#000,#000); mask-image:linear-gradient(#000,#000);
    }
    .t-flightplan .cap{
      position:absolute; left:0; top:6px; font-size:11px; letter-spacing:0; color:var(--soft);
      text-transform:uppercase;
    }
    .t-flightplan .cap b{ color:var(--ink); font-weight:700; letter-spacing:0.01em; }

    /* datum + scale */
    .t-flightplan .datum{ position:absolute; left:0; right:0; top:400px; height:2.5px; background:var(--ink); }
    .t-flightplan .tick{ position:absolute; top:400px; width:1px; background:rgba(var(--rgb),0.5); transform:translateX(-0.5px); }
    .t-flightplan .tick.mn{ height:7px; }
    .t-flightplan .tick.mj{ height:14px; background:rgba(var(--rgb),0.8); }
    .t-flightplan .hnum{ position:absolute; top:410px; transform:translateX(-50%); font-size:11px; color:var(--soft); }

    /* dimension apparatus */
    .t-flightplan .ext{ position:absolute; width:1px; transform:translateX(-0.5px); background:rgba(var(--rgb),0.6); }
    .t-flightplan .dline{ position:absolute; height:1px; background:rgba(var(--rgb),0.66); }
    .t-flightplan .ah{ position:absolute; width:0; height:0; border-style:solid; }
    .t-flightplan .ah.r{ border-width:4px 0 4px 8px; border-color:transparent transparent transparent rgba(var(--rgb),0.9); }
    .t-flightplan .ah.l{ border-width:4px 8px 4px 0; border-color:transparent rgba(var(--rgb),0.9) transparent transparent; }
    .t-flightplan .meas{
      position:absolute; transform:translateX(-50%); white-space:nowrap;
      font-size:12px; font-weight:700; color:var(--ink); letter-spacing:0.01em;
    }
    .t-flightplan .meas .u{ font-weight:400; color:var(--soft); }

    /* shelf leader + label */
    .t-flightplan .lead{ position:absolute; }
    .t-flightplan .lead .diag{ position:absolute; height:1px; background:rgba(var(--rgb),0.66); transform-origin:left center; }
    .t-flightplan .lead .shelf{ position:absolute; height:1px; background:rgba(var(--rgb),0.66); }
    .t-flightplan .lead .txt{ position:absolute; width:210px; }
    .t-flightplan .lead .txt.rt{ text-align:right; }
    .t-flightplan .lead .tt{ font-size:14px; font-weight:700; color:var(--ink); line-height:1.15; }
    .t-flightplan .lead .tb{ font-size:12.5px; color:var(--soft); line-height:1.3; margin-top:2px; }
    .t-flightplan .lead .dot{ position:absolute; width:5px; height:5px; border-radius:50%; background:var(--ink); transform:translate(-2.5px,-2.5px); }

    /* EOD ship: hidden line box + detail ring */
    .t-flightplan .ship{
      position:absolute; border:1.5px dashed rgba(var(--rgb),0.85);
      display:flex; align-items:center; justify-content:center;
    }
    .t-flightplan .ship b{ font-size:11px; font-weight:700; letter-spacing:0.04em; color:var(--ink); }
    .t-flightplan .dring{ position:absolute; border:1px solid rgba(var(--rgb),0.7); border-radius:50%; }
    .t-flightplan .dkey{ position:absolute; width:1px; background:rgba(var(--rgb),0.6); }

    /* Detail A blow-up */
    .t-flightplan .detail{ position:absolute; top:4px; right:2px; width:168px; }
    .t-flightplan .detail .dcirc{
      position:relative; width:168px; height:168px; border-radius:50%;
      border:1.5px solid rgba(var(--rgb),0.8); overflow:hidden;
    }
    .t-flightplan .detail .mbox{
      position:absolute; left:34px; top:56px; width:100px; height:52px;
      border:1.5px dashed rgba(var(--rgb),0.85);
    }
    .t-flightplan .detail .mtx{ position:absolute; left:24px; right:16px; top:112px; }
    .t-flightplan .detail .mtx .a{ font-size:11px; font-weight:700; color:var(--ink); line-height:1.2; }
    .t-flightplan .detail .mtx .b{ font-size:10px; color:var(--soft); margin-top:3px; }
    .t-flightplan .detail .dhd{
      position:absolute; left:-2px; top:-26px; font-size:11px; font-weight:700;
      font-family:var(--disp,'Helvetica Neue',Helvetica,Arial,sans-serif);
      letter-spacing:var(--track,0.22em); text-transform:uppercase; color:var(--ink);
    }
    .t-flightplan .detail .dsc{ position:absolute; right:0; top:-24px; font-size:10px; color:var(--soft); letter-spacing:0.02em; }

    /* overnight section */
    .t-flightplan .seclabel{ position:absolute; font-size:11px; text-transform:uppercase; color:var(--ink); font-weight:700; letter-spacing:0.01em; }
    .t-flightplan .seclabel span{ color:var(--soft); font-weight:400; }
    .t-flightplan .sec{
      position:absolute; border:1px solid rgba(var(--rgb),0.5);
    }
    .t-flightplan .sec.hatch{
      background-image:repeating-linear-gradient(45deg, rgba(var(--rgb),0.34) 0 1px, transparent 1px 9px);
    }
    .t-flightplan .sec.cross{
      background-image:
        repeating-linear-gradient(45deg, rgba(var(--rgb),0.28) 0 1px, transparent 1px 10px),
        repeating-linear-gradient(-45deg, rgba(var(--rgb),0.28) 0 1px, transparent 1px 10px);
    }
    .t-flightplan .cbub{
      position:absolute; width:16px; height:16px; border-radius:50%;
      border:1px solid var(--ink); background:var(--paper);
      display:flex; align-items:center; justify-content:center;
      font-size:9px; font-weight:700; color:var(--ink); transform:translate(-8px,-8px);
    }
    .t-flightplan .cout{ position:absolute; width:284px; }
    .t-flightplan .cout .ct{ display:flex; align-items:baseline; }
    .t-flightplan .cout .cl{ font-size:12.5px; line-height:1.32; color:var(--ink); }
    .t-flightplan .cout .cl b{ font-weight:700; }
    .t-flightplan .cout .sub{ display:block; color:var(--soft); font-size:11.5px; margin-top:1px; }
    .t-flightplan .cleader{ position:absolute; height:1px; background:rgba(var(--rgb),0.55); }

    /* ---- baseband: notes + title block ---- */
    .t-flightplan .base{ display:grid; grid-template-columns:1fr 336px; gap:44px; margin-top:26px; align-items:start; }
    .t-flightplan .nhd{
      font-family:var(--disp,'Helvetica Neue',Helvetica,Arial,sans-serif);
      font-size:11px; letter-spacing:var(--track,0.22em); text-transform:uppercase; color:var(--ink);
      font-weight:700; padding-bottom:9px; border-bottom:2px solid var(--ink); margin-bottom:4px;
    }
    .t-flightplan .note{
      display:grid; grid-template-columns:24px 1fr; gap:0 6px; padding:11px 0;
      border-bottom:1px solid rgba(var(--rgb),0.18); align-items:baseline;
    }
    .t-flightplan .note .k{ font-size:13px; color:var(--soft); font-weight:700; }
    .t-flightplan .note .b{ font-size:14.5px; line-height:1.42; color:var(--ink); }
    .t-flightplan .note .b .v{ font-weight:700; }
    .t-flightplan .note .sub{ color:var(--soft); }
    .t-flightplan .yield{
      margin-top:16px; font-size:12.5px; color:var(--soft); letter-spacing:0.01em;
    }
    .t-flightplan .yield b{ color:var(--ink); font-weight:700; }

    .t-flightplan .tblock{ border:1.5px solid var(--ink); }
    .t-flightplan .tblock .ban{
      font-family:var(--disp,'Helvetica Neue',Helvetica,Arial,sans-serif);
      padding:10px 14px; border-bottom:1.5px solid var(--ink);
      font-size:11px; letter-spacing:var(--track,0.22em); text-transform:uppercase; font-weight:700; color:var(--ink);
    }
    .t-flightplan .tblock .tr{ display:grid; grid-template-columns:104px 1fr; border-bottom:1px solid rgba(var(--rgb),0.4); }
    .t-flightplan .tblock .tr:last-child{ border-bottom:0; }
    .t-flightplan .tblock .tk{
      padding:9px 14px; font-size:9.5px; letter-spacing:0.02em; text-transform:uppercase; color:var(--soft);
      border-right:1px solid rgba(var(--rgb),0.4);
    }
    .t-flightplan .tblock .tv{ padding:9px 14px; font-size:12.5px; font-weight:700; letter-spacing:0.01em; text-transform:uppercase; color:var(--ink); }

    @media (max-width:900px){
      .t-flightplan .base{ grid-template-columns:1fr; gap:26px; }
      .t-flightplan .detail{ width:140px; }
      .t-flightplan .detail .dcirc{ width:140px; height:140px; }
    }
  `,
  render(ed, skin) {
    const c = ed.content;
    const dateCode = `${_two(ed.day)} ${ed.monthShort.toUpperCase()} ${ed.year}`;
    const sheetNo = String(ed.editionNo).padStart(3, "0");

    const H0 = 6,
      H1 = 24,
      SPAN = H1 - H0;
    const L = 6,
      R = 94; // datum runs 6%..94%
    const X = (hr) => L + ((hr - H0) / SPAN) * (R - L);
    const DATUM = 430;

    // hour scale
    let ticks = "";
    for (let h = H0; h <= H1; h++) {
      const x = X(h);
      const mj = h % 3 === 0;
      ticks += `<div class="tick ${mj ? "mj" : "mn"}" style="left:${x.toFixed(3)}%"></div>`;
      if (mj)
        ticks += `<div class="hnum" style="left:${x.toFixed(3)}%">${_two(h)}</div>`;
    }

    // meetings -> dimensioned spans that rise off the datum on shelf leaders
    const timed = c.today.filter((it) => it.t24);
    const DIMY = 360; // meeting dimension line
    const meetings = timed
      .map((it, i) => {
        const s = _hr(it.t24);
        const e = s + 0.5; // 30-minute engagement
        const x1 = X(s),
          x2 = X(e),
          xc = (x1 + x2) / 2;
        const left = i === 0; // first meeting labels left, second right
        // witness lines (datum -> dim line) + tiny dimension line + outward arrows
        const ext = `
          <div class="ext" style="left:${x1.toFixed(3)}%; top:${DIMY}px; height:${DATUM - DIMY}px"></div>
          <div class="ext" style="left:${x2.toFixed(3)}%; top:${DIMY}px; height:${DATUM - DIMY}px"></div>
          <div class="dline" style="left:${x1.toFixed(3)}%; width:${(x2 - x1).toFixed(3)}%; top:${DIMY}px"></div>
          <div class="ah r" style="left:calc(${x1.toFixed(3)}% - 8px); top:${DIMY - 4}px"></div>
          <div class="ah l" style="left:${x2.toFixed(3)}%; top:${DIMY - 4}px"></div>
          <div class="meas" style="left:${xc.toFixed(3)}%; top:${DIMY - 22}px">${it.t24}<span class="u"> &ndash; ${_clock(e)}</span></div>`;
        // shelf leader up-left or up-right, 45deg rise then horizontal shelf
        const rise = 60,
          shelfW = 210;
        const shelfY = DIMY - rise; // 284
        const diag = `<div class="diag" style="left:0; top:0; width:${(rise * 1.4142).toFixed(1)}px; transform:rotate(${left ? 225 : -45}deg)"></div>`;
        const shelf = left
          ? `<div class="shelf" style="right:${rise}px; top:${-rise}px; width:${shelfW}px"></div>`
          : `<div class="shelf" style="left:${rise}px; top:${-rise}px; width:${shelfW}px"></div>`;
        const txt = `<div class="txt ${left ? "rt" : ""}" style="${left ? "right" : "left"}:${rise}px; top:${-rise - 46}px">
            <div class="tt">${_esc(it.label)}</div>
            ${it.note ? `<div class="tb">${_esc(it.note)}</div>` : ""}
          </div>`;
        const lead = `<div class="lead" style="left:${xc.toFixed(3)}%; top:${DIMY}px">
            <div class="dot"></div>${diag}${shelf}${txt}
          </div>`;
        return ext + lead;
      })
      .join("");

    // free evening — a long open dimension below the datum
    const evStart = 17,
      evEnd = 24;
    const ex1 = X(evStart),
      ex2 = X(evEnd),
      exc = (ex1 + ex2) / 2;
    const EVY = 488;
    const evening = `
      <div class="ext" style="left:${ex1.toFixed(3)}%; top:${DATUM}px; height:${EVY - DATUM}px"></div>
      <div class="ext" style="left:${ex2.toFixed(3)}%; top:${DATUM}px; height:${EVY - DATUM}px"></div>
      <div class="dline" style="left:${ex1.toFixed(3)}%; width:${(ex2 - ex1).toFixed(3)}%; top:${EVY}px"></div>
      <div class="ah r" style="left:${ex1.toFixed(3)}%; top:${EVY - 4}px"></div>
      <div class="ah l" style="left:calc(${ex2.toFixed(3)}% - 8px); top:${EVY - 4}px"></div>
      <div class="meas" style="left:${exc.toFixed(3)}%; top:${EVY + 8}px">17:00 &ndash; 24:00 <span class="u">&middot; yours</span></div>`;

    // EOD ship — dashed hidden-line box keyed to Detail A
    const eod = c.today.find((it) => !it.t24);
    let ship = "";
    if (eod) {
      const sx = X(23.4); // near end of day
      ship = `
        <div class="ship" style="left:calc(${sx.toFixed(3)}% - 30px); top:${DATUM - 19}px; width:60px; height:38px"><b>PR</b></div>
        <div class="dring" style="left:calc(${sx.toFixed(3)}% - 44px); top:${DATUM - 44}px; width:88px; height:88px"></div>
        <div class="dkey" style="left:calc(${sx.toFixed(3)}% - 0.5px); top:172px; height:${DATUM - 44 - 172}px"></div>`;
    }
    const detail = eod
      ? `<div class="detail">
          <div class="dhd">Detail A</div><div class="dsc">scale 2:1</div>
          <div class="dcirc">
            <div class="mbox"></div>
            <div class="mtx"><div class="a">Ship approval-flow PR</div><div class="b">CI green 05:40</div></div>
          </div>
        </div>`
      : "";

    // overnight — hatched section below grade, keyed callouts
    const SEC_X = 4,
      SEC_W = 26,
      SEC_Y = 540,
      SEC_H = 182;
    const secClass = skin.hatch.cross ? "cross" : "hatch";
    const bubX = SEC_X + SEC_W - 3; // bubble sits inside the section's right edge
    const outX = SEC_X + SEC_W + 4; // callouts to the right of the section
    const rows = c.overnight.slice(0, 3);
    const rowY = [560, 620, 680];
    const bubbles = rows
      .map(
        (
          it,
          i,
        ) => `<div class="cbub" style="left:${bubX.toFixed(3)}%; top:${rowY[i]}px">${i + 1}</div>
          <div class="cleader" style="left:${bubX.toFixed(3)}%; width:${(outX - bubX + 0.3).toFixed(3)}%; top:${rowY[i]}px"></div>`,
      )
      .join("");
    const callouts = rows
      .map(
        (
          it,
          i,
        ) => `<div class="cout" style="left:${outX}%; top:${rowY[i] - 8}px">
          <div class="ct"><span class="cl"><b>${it.t24 || ""}</b> &middot; ${_esc(it.label)}${_sub(it.note)}</span></div>
        </div>`,
      )
      .join("");
    const overnight = `
      <div class="seclabel" style="left:${SEC_X}%; top:${SEC_Y - 22}px">Overnight <span>&middot; section 02:14&ndash;04:09, while you slept</span></div>
      <div class="sec ${secClass}" style="left:${SEC_X}%; top:${SEC_Y}px; width:${SEC_W}%; height:${SEC_H}px"></div>
      ${bubbles}${callouts}`;

    // corner crop marks
    const crops = skin.grid.showCrop
      ? `<div class="crop tl"></div><div class="crop tr"></div><div class="crop bl"></div><div class="crop br"></div>`
      : "";
    const gridEl = skin.grid.showGrid ? `<div class="grid"></div>` : "";

    // notes: deck + the two decisions
    const notesItems = [
      `<span class="v"></span>${_esc(ed.deck)}`,
      ...c.decisions.map(
        (d) =>
          `<span class="v">${_esc(d.verb)} &mdash; </span>${_esc(d.label)}.${d.note ? ` <span class="sub">${_esc(d.note)}.</span>` : ""}`,
      ),
    ];
    const notes = notesItems
      .map(
        (t, i) =>
          `<div class="note"><span class="k">${_two(i + 1)}</span><span class="b">${t}</span></div>`,
      )
      .join("");

    const s = c.stats;
    const yieldLine = `<b>Yield</b> &mdash; <b>${s.done}</b> done (${s.you} you &middot; ${s.gaia} GAIA) &middot; <b>${s.mail}</b> letters cleared &middot; <b>${_esc(s.focus)}</b> held`;

    return `<article class="t-flightplan" style="--paper:${skin.ground.paper};--ink:${skin.ground.ink};--soft:${skin.ground.soft};--rgb:${skin.ground.rgb};--disp:${skin.face.stack};--track:${skin.face.track}">
      <div class="frame"></div>${crops}
      <div class="sheet">
        <div class="draw">
          ${gridEl}
          <div class="cap"><b>The day &mdash; an elevation.</b> One operating window, 06:00 to 24:00 local.</div>
          <div class="datum obj"></div>
          ${ticks}
          ${meetings}
          ${evening}
          ${ship}
          ${detail}
          ${overnight}
        </div>
        <div class="base">
          <div>
            <div class="nhd">Notes</div>
            ${notes}
            <div class="yield">${yieldLine}</div>
          </div>
          <div class="tblock">
            <div class="ban">GAIA &middot; Daily Operations</div>
            <div class="tr"><div class="tk">Project</div><div class="tv">${_esc(ed.weekday)}</div></div>
            <div class="tr"><div class="tk">Sheet</div><div class="tv">${sheetNo} of 100</div></div>
            <div class="tr"><div class="tk">Scale</div><div class="tv">One day</div></div>
            <div class="tr"><div class="tk">Drawn by</div><div class="tv">GAIA</div></div>
            <div class="tr"><div class="tk">Date</div><div class="tv">${dateCode}</div></div>
          </div>
        </div>
      </div>
    </article>`;
  },
});

/* ================================================================
   2) INSTRUMENT — a Braun/Rams instrument panel as print.
   Deep warm charcoal, light precise labels, the day's times drawn
   as a real horizontal scale (06–24) inside a discreet recessed
   panel with model/serial line, unit markings, and a marker legend.
   One function color, used sparingly.
   ================================================================ */
EXPLORER.register({
  id: "instrument",
  name: "The Instrument",
  axes: {
    func: [
      { id: "yellow", label: "function yellow", color: "#f0a500" },
      { id: "green", label: "signal green", color: "#3d9970" },
      { id: "red", label: "warm red", color: "#d8503a" },
    ],
    face: [
      {
        id: "helv",
        label: "Helvetica Neue",
        stack: "'Helvetica Neue',Helvetica,Arial,sans-serif",
      },
      {
        id: "optima",
        label: "Optima",
        stack: "Optima,'Avenir Next','Helvetica Neue',sans-serif",
      },
    ],
    finish: [
      {
        id: "warm",
        label: "warm charcoal",
        panel: "#26262a",
        panel2: "#2e2e33",
      },
      {
        id: "cool",
        label: "cool graphite",
        panel: "#232629",
        panel2: "#2b2f33",
      },
    ],
    scale: [
      { id: "numbered", label: "ticks with numerals", num: "1" },
      { id: "minimal", label: "minimal ticks", num: "0" },
    ],
  },
  css: `
    .t-instrument{
      position:relative; box-sizing:border-box; width:100%; min-height:1240px;
      overflow:hidden; background:var(--panel,#26262a); color:#e9e9e5;
      font-family:var(--display,'Helvetica Neue',Helvetica,Arial,sans-serif); -webkit-font-smoothing:antialiased;
      font-variant-numeric:tabular-nums lining-nums;
      padding:clamp(32px,4.6vw,74px);
    }
    .t-instrument *{ box-sizing:border-box; }
    .t-instrument .face{ max-width:1040px; margin:0 auto; }

    .t-instrument .top{
      display:flex; justify-content:space-between; align-items:flex-end; gap:20px 28px;
      flex-wrap:wrap; border-bottom:1px solid rgba(255,255,255,0.16); padding-bottom:18px;
    }
    .t-instrument .brand{ font-size:clamp(28px,4.3vw,46px); font-weight:700; letter-spacing:0.01em; line-height:1; }
    .t-instrument .meta{ text-align:right; }
    .t-instrument .model{ font-size:11px; letter-spacing:0.22em; text-transform:uppercase; color:#a2a29d; }
    .t-instrument .serial{ font-size:11px; letter-spacing:0.14em; color:#8f8f8a; margin-top:6px; }
    .t-instrument .deck{
      font-size:clamp(15px,1.9vw,20px); color:#c6c6c0; max-width:54ch;
      margin:22px 0 8px; line-height:1.38;
    }

    .t-instrument .rule{ height:1px; background:rgba(255,255,255,0.12); border:0; margin:20px 0; }

    /* ---- the scale: the day's times as a drawn ruler, recessed ---- */
    .t-instrument .scalewrap{ background:rgba(0,0,0,0.16); padding:22px 26px 18px; }
    .t-instrument .scale-hd{
      display:flex; justify-content:space-between; align-items:baseline; gap:12px;
      font-size:10px; letter-spacing:0.2em; text-transform:uppercase; color:#a2a29d; margin-bottom:6px;
    }
    .t-instrument .scale-hd .unit{ color:#8f8f8a; letter-spacing:0.14em; }
    .t-instrument .scale{ position:relative; height:104px; margin:6px 0 0; }
    .t-instrument .scale .track{ position:absolute; left:0; right:0; top:70px; height:1px; background:rgba(255,255,255,0.34); }
    .t-instrument .scale .tick{ position:absolute; top:70px; width:1px; background:rgba(255,255,255,0.26); transform:translateX(-0.5px); }
    .t-instrument .scale .tick.min{ height:7px; }
    .t-instrument .scale .tick.maj{ height:14px; background:rgba(255,255,255,0.5); }
    .t-instrument .scale .tnum{
      position:absolute; top:88px; transform:translateX(-50%);
      font-size:10px; letter-spacing:0.1em; color:#8f8f8a; opacity:var(--num-op,1);
    }
    .t-instrument .mk{
      position:absolute; top:6px; height:64px; transform:translateX(-50%);
      display:flex; flex-direction:column; align-items:center; width:140px;
    }
    .t-instrument .mk .tm{ font-size:15px; font-weight:700; color:#f0f0ec; line-height:1; }
    .t-instrument .mk .tg{ font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:#a2a29d; margin-top:4px; }
    .t-instrument .mk .stem{ width:1px; flex:1; min-height:14px; background:var(--func,#f0a500); margin-top:7px; }
    .t-instrument .mk .dot{ width:8px; height:8px; border-radius:50%; background:var(--func,#f0a500); margin-top:-4px; }
    .t-instrument .legend{
      display:flex; gap:24px; align-items:center; margin-top:14px;
      font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:#8f8f8a;
    }
    .t-instrument .legend .li{ display:flex; align-items:center; gap:8px; }
    .t-instrument .legend .sw-dot{ width:8px; height:8px; border-radius:50%; background:var(--func,#f0a500); }
    .t-instrument .legend .sw-maj{ width:1px; height:12px; background:rgba(255,255,255,0.55); }
    .t-instrument .legend .sw-min{ width:1px; height:7px; background:rgba(255,255,255,0.32); }

    /* ---- clusters ---- */
    .t-instrument .cluster{ background:var(--panel2,#2e2e33); padding:20px 24px; }
    .t-instrument .cluster + .cluster{ margin-top:16px; }
    .t-instrument .cols{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:16px; }
    .t-instrument .cols .cluster + .cluster{ margin-top:0; }
    .t-instrument .cl-h{
      font-size:10px; letter-spacing:0.24em; text-transform:uppercase; color:#a2a29d;
      margin-bottom:14px; display:flex; justify-content:space-between; gap:12px;
    }

    .t-instrument .row{
      display:grid; grid-template-columns:66px 1fr; gap:0 16px; padding:10px 0;
      border-top:1px solid rgba(255,255,255,0.08); align-items:baseline;
    }
    .t-instrument .row:first-of-type{ border-top:0; padding-top:0; }
    .t-instrument .row .tm{ font-weight:700; color:#dbdbd6; white-space:nowrap; }
    .t-instrument .row .tm.none{ color:#75756f; font-weight:400; }
    .t-instrument .row .lb{ line-height:1.34; color:#e6e6e1; }
    .t-instrument .sub{ display:block; color:#9a9a94; font-size:12px; margin-top:3px; }

    .t-instrument .drow{
      display:grid; grid-template-columns:14px 1fr; gap:0 15px; padding:12px 0;
      border-top:1px solid rgba(255,255,255,0.08); align-items:baseline;
    }
    .t-instrument .drow:first-of-type{ border-top:0; padding-top:0; }
    .t-instrument .drow .dot{ width:10px; height:10px; border-radius:50%; background:var(--func,#f0a500); margin-top:5px; }
    .t-instrument .drow .verb{ font-weight:700; color:#f2f2ee; }
    .t-instrument .drow .lb{ line-height:1.34; color:#e6e6e1; }

    /* ---- readout (stats) ---- */
    .t-instrument .readout{ display:flex; flex-wrap:wrap; gap:24px 44px; align-items:baseline; }
    .t-instrument .gauge .n{ font-size:clamp(26px,3.2vw,36px); font-weight:700; letter-spacing:-0.01em; line-height:1; }
    .t-instrument .gauge .k{ font-size:9px; letter-spacing:0.2em; text-transform:uppercase; color:#a2a29d; margin-top:8px; }

    .t-instrument .foot{
      margin-top:28px; padding-top:16px; border-top:1px solid rgba(255,255,255,0.16);
      font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:#8f8f8a;
      display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap;
    }

    @media (max-width:680px){
      .t-instrument .cols{ grid-template-columns:1fr; }
      .t-instrument .cols .cluster + .cluster{ margin-top:16px; }
      .t-instrument .legend{ flex-wrap:wrap; gap:10px 18px; }
    }
  `,
  render(ed, skin) {
    const c = ed.content;
    const dateCode = `${_two(ed.day)} ${ed.monthShort.toUpperCase()} ${ed.year}`;

    // scale ruler 06 -> 24
    let ticks = "";
    for (let h = 6; h <= 24; h++) {
      const pct = ((h - 6) / 18) * 100;
      const maj = h % 3 === 0;
      ticks += `<div class="tick ${maj ? "maj" : "min"}" style="left:${pct.toFixed(3)}%"></div>`;
      if (maj)
        ticks += `<div class="tnum" style="left:${pct.toFixed(3)}%">${_two(h)}</div>`;
    }
    const marks = c.today
      .filter((it) => it.t24)
      .map((it) => {
        const [hh, mm] = it.t24.split(":").map(Number);
        const hours = hh + mm / 60;
        const pct = Math.min(100, Math.max(0, ((hours - 6) / 18) * 100));
        return `<div class="mk" style="left:${pct.toFixed(3)}%"><div class="tm">${it.t24}</div><div class="tg">${_esc(it.tag)}</div><div class="stem"></div><div class="dot"></div></div>`;
      })
      .join("");

    const todayRows = c.today
      .map((it) => {
        const timed = !!it.t24;
        return `<div class="row"><div class="tm ${timed ? "" : "none"}">${timed ? it.t24 : "EOD"}</div><div class="lb">${_esc(it.label)}${_sub(it.note)}</div></div>`;
      })
      .join("");
    const overRows = c.overnight
      .map(
        (it) =>
          `<div class="row"><div class="tm">${it.t24 || ""}</div><div class="lb">${_esc(it.label)}${_sub(it.note)}</div></div>`,
      )
      .join("");
    const decRows = c.decisions
      .map(
        (d) =>
          `<div class="drow"><div class="dot"></div><div class="lb"><span class="verb">${_esc(d.verb)}</span> &mdash; ${_esc(d.label)}${_sub(d.note)}</div></div>`,
      )
      .join("");

    const s = c.stats;
    const gauge = (n, k) =>
      `<div class="gauge"><div class="n">${_esc(n)}</div><div class="k">${k}</div></div>`;

    return `<article class="t-instrument" style="--func:${skin.func.color};--display:${skin.face.stack};--panel:${skin.finish.panel};--panel2:${skin.finish.panel2};--num-op:${skin.scale.num}">
      <div class="face">
        <header class="top">
          <div class="brand">GAIA</div>
          <div class="meta">
            <div class="model">GAIA RB&#8209;${ed.editionNo} &middot; Daily Briefing Instrument</div>
            <div class="serial">Ser. ${_esc(ed.weekday.slice(0, 3).toUpperCase())} ${dateCode} &middot; issued ${ed.time24}</div>
          </div>
        </header>

        <p class="deck">${_esc(ed.deck)}</p>

        <hr class="rule">

        <div class="scalewrap">
          <div class="scale-hd"><span>Operating Window</span><span class="unit">06:00&ndash;24:00 &middot; 24H local</span></div>
          <div class="scale">
            ${ticks}
            <div class="track"></div>
            ${marks}
          </div>
          <div class="legend">
            <span class="li"><span class="sw-dot"></span>Scheduled</span>
            <span class="li"><span class="sw-maj"></span>3-hour</span>
            <span class="li"><span class="sw-min"></span>1-hour</span>
          </div>
        </div>

        <section class="cluster" style="margin-top:16px">
          <div class="cl-h"><span>Today</span><span>${c.today.length} items</span></div>
          ${todayRows}
        </section>

        <div class="cols">
          <section class="cluster">
            <div class="cl-h"><span>While you slept</span><span>${c.overnight.length}</span></div>
            ${overRows}
          </section>
          <section class="cluster">
            <div class="cl-h"><span>Needs your call</span><span>${c.decisions.length}</span></div>
            ${decRows}
          </section>
        </div>

        <section class="cluster" style="margin-top:16px">
          <div class="cl-h"><span>Yesterday</span><span>readout</span></div>
          <div class="readout">
            ${gauge(s.done, "done")}
            ${gauge(s.you, "by you")}
            ${gauge(s.gaia, "by gaia")}
            ${gauge(s.mail, "mail")}
            ${gauge(s.focus, "focus today")}
          </div>
        </section>

        <div class="foot">
          <span>GAIA Daily Brief &middot; Edition No. ${ed.editionNo}</span>
          <span>Issued ${ed.time24} &middot; ${_esc(ed.weekday)}</span>
        </div>
      </div>
    </article>`;
  },
});
