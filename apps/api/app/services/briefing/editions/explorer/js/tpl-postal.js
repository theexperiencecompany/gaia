/* ============================================================================
   tpl-postal.js (round 2) — Air Mail, re-composed for a 540 px portrait
   canvas (export at 3x). Body 18 px Iowan.

   Signature moves kept from the desktop original:
     1. an airmail envelope on a dark desk: diagonal red/blue chevron border,
        kraft or cream face with the flap seam, a slight tilt, real shadow
     2. the stamp (the GPT city stamp art, perforations included), large and
        unobstructed, with a fine circular date postmark set beside it
     3. typewritten return address under The Experience Company wordmark, the bilingual PAR AVION box, the address
        block with its underline, and a blue PAR AVION / BY AIR MAIL etiquette label
     4. the insert letter overlapping the envelope: tilted, shadowed, laid
        paper, typewriter letterhead, italic deck, typewriter marginalia
   Added for the phone: "Dear Aryan," and a pen signature, the stats as the
   P.S., and needs set first in the letter with red-ribbon verbs.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const clock = (t24) => {
    if (!t24) return "";
    const [h, m] = t24.split(":").map(Number);
    return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
  };

  /* A duplex cancellation set beside the stamp, never over it: a circular datestamp
     (city on the upper arc, GAIA POST and the edition on the lower arc, the date in a
     ruled band) and a killer of bars broken around the office number. The ink is laid
     twice, the second impression faint and slightly off-register, and a noise mask
     thins the ink where the rubber met the paper unevenly. */
  function postmark(ed, city) {
    const uid = city.id;
    const cx = 196;
    const cy = 66;
    const killer = [0, 1, 2, 3, 4, 5]
      .map((i) => {
        const y = 41 + i * 10;
        const broken = i === 2 || i === 3;
        return broken
          ? `<rect x="14" y="${y}" width="40" height="4.6" rx="2.3"/><rect x="98" y="${y}" width="36" height="4.6" rx="2.3"/>`
          : `<rect x="14" y="${y}" width="120" height="4.6" rx="2.3"/>`;
      })
      .join("");
    const mark = `${killer}<text x="76" y="71" text-anchor="middle" font-size="17" font-weight="700">${ed.editionNo}</text>
<circle cx="${cx}" cy="${cy}" r="58" fill="none" stroke="currentColor" stroke-width="2.6"/>
<circle cx="${cx}" cy="${cy}" r="40" fill="none" stroke="currentColor" stroke-width="1.1"/>
<text font-size="12.5" font-weight="700" letter-spacing="2.6" text-anchor="middle"><textPath href="#pm-t-${uid}" startOffset="50%">${esc(city.city)}</textPath></text>
<text font-size="12" letter-spacing="2.2" text-anchor="middle"><textPath href="#pm-b-${uid}" startOffset="50%">GAIA POST</textPath></text>
<line x1="${cx - 38}" y1="${cy - 9}" x2="${cx + 38}" y2="${cy - 9}" stroke="currentColor" stroke-width="1"/>
<line x1="${cx - 38}" y1="${cy + 11}" x2="${cx + 38}" y2="${cy + 11}" stroke="currentColor" stroke-width="1"/>
<text x="${cx}" y="${cy + 6}" text-anchor="middle" font-size="15" font-weight="700" letter-spacing=".6">${ed.day} ${esc(ed.monthShort.toUpperCase())} ${String(ed.year).slice(2)}</text>
<text x="${cx}" y="${cy - 16}" text-anchor="middle" font-size="12" letter-spacing="1">${esc(ed.time24)}</text>
<text x="${cx}" y="${cy + 27}" text-anchor="middle" font-size="12" letter-spacing="1">${ed.time24 < "12:00" ? "AM" : "PM"}</text>`;
    return `<svg viewBox="0 0 260 132" aria-hidden="true">
<defs>
<path id="pm-t-${uid}" d="M ${cx - 45} ${cy} A 45 45 0 0 1 ${cx + 45} ${cy}"/>
<path id="pm-b-${uid}" d="M ${cx - 53} ${cy} A 53 53 0 0 0 ${cx + 53} ${cy}"/>
<filter id="pm-ink-${uid}" x="-5%" y="-5%" width="110%" height="110%">
<feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="11" result="edge"/>
<feDisplacementMap in="SourceGraphic" in2="edge" scale="1.3" result="rough"/>
<feTurbulence type="fractalNoise" baseFrequency=".055 .09" numOctaves="2" seed="3" result="press"/>
<feColorMatrix in="press" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -1.6 1.75" result="pressMask"/>
<feComposite in="rough" in2="pressMask" operator="in"/>
</filter></defs>
<g fill="currentColor" opacity=".2" transform="translate(1.6 1.1)">${mark}</g>
<g fill="currentColor" filter="url(#pm-ink-${uid})">${mark}</g></svg>`;
  }

  /* Paper grain: inline SVG fractal noise (no external asset), blended over the sheet at low opacity. */
  const grain = (id, freq) => `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  /* The back-flap seams that show through a thin envelope: two embossed diagonals meeting under the address. */
  const SEAM = `<svg class="seam" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><path d="M0 100 L50 52 L100 100" fill="none" stroke="rgba(0,0,0,.13)" stroke-width=".35" vector-effect="non-scaling-stroke"/><path d="M0 99 L50 51 L100 99" fill="none" stroke="rgba(255,255,255,.35)" stroke-width=".35" vector-effect="non-scaling-stroke" transform="translate(0 1.2)"/></svg>`;
  const CITIES = [
    { id: "tokyo", label: "Tokyo", key: "CITY_TOKYO", city: "TOKYO", air: "航空便" },
    { id: "paris", label: "Paris", key: "CITY_PARIS", city: "PARIS", air: "" },
    { id: "london", label: "London", key: "CITY_LONDON", city: "LONDON", air: "" },
    { id: "newyork", label: "New York", key: "CITY_NEWYORK", city: "NEW YORK", air: "" },
    { id: "mumbai", label: "Mumbai", key: "CITY_MUMBAI", city: "MUMBAI", air: "हवाई डाक" },
    { id: "istanbul", label: "Istanbul", key: "CITY_ISTANBUL", city: "ISTANBUL", air: "Uçak İle" },
  ];

  EXPLORER.register({
    id: "postal",
    name: "Air Mail",
    axes: {
      city: CITIES,
      paper: [
        { id: "honey", label: "honey kraft", env: "#efd7a4", ink: "#3a2a12", tint: "rgba(170,110,30,.08)" },
        { id: "laid", label: "ivory laid", env: "#f6ecd6", ink: "#33291c", tint: "rgba(150,110,50,.06)" },
        { id: "airmail", label: "airmail blue", env: "#dce8f5", ink: "#1f2c44", tint: "rgba(40,70,140,.06)" },
      ],
      ink: [
        { id: "black", label: "black postmark", mark: "#2a2721", ribbon: "#a3352a" },
        { id: "red", label: "red postmark", mark: "#9c3329", ribbon: "#a3352a" },
      ],
    },
    css: `
.t-postal { box-sizing: border-box; width: 540px; padding: 40px 22px 56px; overflow: hidden; color: #2a2822;
  background-color: #23262a;
  background-image: radial-gradient(120% 80% at 50% 0%, rgba(255,255,255,.06), transparent 60%),
    repeating-linear-gradient(94deg, rgba(0,0,0,.12) 0 2px, rgba(255,255,255,.014) 2px 5px); }
.t-postal * { box-sizing: border-box; margin: 0; padding: 0; }
.t-postal .tw { font-family: 'American Typewriter', 'Courier New', monospace; }
.t-postal .env { position: relative; padding: 12px; transform: rotate(-1deg);
  background: repeating-linear-gradient(-52deg, #c33a30 0 12px, #f4f1e8 12px 22px, #2f5c9e 22px 34px, #f4f1e8 34px 44px);
  box-shadow: 0 2px 2px rgba(0,0,0,.25), 0 26px 44px rgba(0,0,0,.45); }
.t-postal .face { position: relative; height: 420px; overflow: hidden; color: var(--envInk); background-color: var(--env);
  background-image: linear-gradient(var(--tint), var(--tint)), repeating-linear-gradient(90deg, rgba(0,0,0,.025) 0 1px, transparent 1px 4px); }
.t-postal .seam { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.t-postal .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .16; }
.t-postal .letter .grain { opacity: .09; }
.t-postal .thumb { position: absolute; right: 54px; bottom: 54px; width: 64px; height: 82px; border-radius: 50%; transform: rotate(-24deg); pointer-events: none; opacity: .22;
  background: repeating-radial-gradient(ellipse at 50% 60%, rgba(60,45,25,.55) 0 1px, transparent 1px 3.2px);
  -webkit-mask: radial-gradient(ellipse at 50% 55%, #000 30%, transparent 70%); mask: radial-gradient(ellipse at 50% 55%, #000 30%, transparent 70%); }
.t-postal .ret { position: absolute; top: 22px; left: 24px; display: grid; grid-template-columns: 34px auto; column-gap: 10px; align-items: center; font-size: 14px; line-height: 1.35; }
.t-postal .ret img { width: 34px; height: auto; opacity: .9; mix-blend-mode: multiply; }
.t-postal .avion { position: absolute; top: 80px; left: 24px; padding: 3px; background: #1d4b9a; transform: rotate(-1.2deg); box-shadow: 0 1px 1px rgba(0,0,0,.22);
  -webkit-mask: radial-gradient(circle 1.6px at 3px 3px, #0000 95%, #000) -3px -3px / 6px 6px, linear-gradient(#000 0 0) 50% / calc(100% - 4px) calc(100% - 4px) no-repeat;
  mask: radial-gradient(circle 1.6px at 3px 3px, #0000 95%, #000) -3px -3px / 6px 6px, linear-gradient(#000 0 0) 50% / calc(100% - 4px) calc(100% - 4px) no-repeat; mask-composite: add; }
.t-postal .avion div { border: 1.5px solid #f4f1e8; padding: 6px 14px 7px; color: #ffffff; text-align: center; font-family: Futura, 'Avenir Next', sans-serif; }
.t-postal .avion .loc { display: block; font-size: 13px; line-height: 1.2; margin-bottom: 2px; }
.t-postal .avion b { display: block; font-size: 19px; line-height: 1.1; font-weight: 700; letter-spacing: .06em; }
.t-postal .avion small { display: block; font-size: 13px; line-height: 1.3; letter-spacing: .1em; }
.t-postal .stamp { position: absolute; top: 18px; right: 20px; width: 160px; transform: rotate(1.6deg); filter: drop-shadow(0 1px 1.5px rgba(0,0,0,.3)) drop-shadow(0 4px 6px rgba(0,0,0,.12)); }
.t-postal .pm { position: absolute; top: 140px; right: 184px; width: 250px; height: 127px; transform: rotate(-4deg); color: var(--mark); opacity: .86; }
.t-postal .pm svg { display: block; width: 100%; height: 100%; }
.t-postal .pm text { font-family: 'American Typewriter', 'Courier New', monospace; }
.t-postal .addr { position: absolute; left: 44px; top: 270px; z-index: 3; line-height: 1.6; }
.t-postal .addr .lab { font-size: 15px; font-style: italic; }
.t-postal .addr .to { font-size: 28px; line-height: 1.2; }
.t-postal .addr .re { font-size: 18px; }
.t-postal .addr .meta { font-size: 15px; }
.t-postal .addr .under { width: 150px; border-bottom: 1px solid currentColor; opacity: .4; margin-top: 8px; }
.t-postal .letter { position: relative; z-index: 2; width: 94%; margin: -40px auto 0; transform: rotate(.6deg); padding: 36px 34px 40px;
  background-color: #fbf9f1; background-image: repeating-linear-gradient(90deg, rgba(90,70,30,.035) 0 1px, transparent 1px 7px), radial-gradient(130% 100% at 50% 30%, transparent 60%, rgba(120,100,60,.08) 100%);
  box-shadow: 0 2px 2px rgba(0,0,0,.18), 0 24px 40px rgba(0,0,0,.4); font: 400 18px/1.55 'Iowan Old Style', Charter, Georgia, serif; }
.t-postal .lhead { display: flex; justify-content: space-between; align-items: baseline; padding-bottom: 14px; border-bottom: 1px solid rgba(0,0,0,.18); }
.t-postal .lbrand { font-size: 15px; letter-spacing: 0; }
.t-postal .lmeta { font-size: 14px; letter-spacing: .04em; color: #5f594d; font-variant-numeric: tabular-nums; }
.t-postal .dated { margin-top: 18px; text-align: right; font-size: 15px; letter-spacing: .02em; color: #5f594d; }
.t-postal .dear { margin-top: 10px; font-style: italic; font-size: 19px; }
.t-postal .deck { margin-top: 8px; font-size: 29px; line-height: 1.25; font-style: italic; letter-spacing: -.005em; text-wrap: balance; }
.t-postal .blk { margin-top: 36px; }
.t-postal .blabel { font: italic 600 21px/1.2 'Iowan Old Style', Charter, Georgia, serif; color: #2a2822; margin-bottom: 10px; }
.t-postal .blabel.red { color: var(--ribbon); }
.t-postal .li { display: grid; grid-template-columns: 84px 1fr; column-gap: 12px; padding: 6px 0; font-size: 17px; line-height: 1.5; }
.t-postal .li > span:last-child { text-wrap: pretty; }
.t-postal .li .w { font-size: 15px; letter-spacing: 0; color: #4a4437; font-variant-numeric: tabular-nums; padding-top: 3px; }
.t-postal .li .w.verb { color: var(--ribbon); font: italic 600 17px/1.5 'Iowan Old Style', Charter, Georgia, serif; padding-top: 0; }
.t-postal .li .nt { color: #5a5345; font-style: italic; }
.t-postal .li .tg { display: block; margin-top: 2px; font-size: 14px; letter-spacing: 0; color: #8a836c; }
.t-postal .ps { display: grid; grid-template-columns: 84px 1fr; column-gap: 12px; margin-top: 36px; font-size: 17px; line-height: 1.55; text-wrap: pretty; }
.t-postal .ps .w { font-size: 15px; padding-top: 2px; }
.t-postal .ps b { font-family: 'American Typewriter', 'Courier New', monospace; font-weight: normal; font-size: 19px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.t-postal .sign { margin-top: 22px; font-size: 18px; font-style: italic; }
.t-postal .sig { display: inline-block; margin-top: 4px; font: italic 500 36px/1 'Playfair Display', Georgia, serif; color: #233f7d; transform: rotate(-4deg); }
.t-postal .lfoot { margin-top: 26px; padding-top: 12px; border-top: 1px solid rgba(0,0,0,.18); display: flex; justify-content: space-between; font-size: 13px; letter-spacing: .06em; color: #5f594d; }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const city = skin.city;
      const li = (w, wCls, text, note, tag) => `<div class="li" data-role="body"><span class="w tw${wCls ? " " + wCls : ""}">${esc(w)}</span><span>${esc(text)}${note ? ` <span class="nt">— ${esc(note)}</span>` : ""}${tag ? `<span class="tg tw">${esc(tag)}</span>` : ""}</span></div>`;
      const blocks = [];
      if (needs.length) blocks.push(`<div class="blk"><h3 class="blabel red">Waiting on your reply</h3>${needs.map((d) => li(d.verb, "verb", d.label, d.note)).join("")}</div>`);
      if (c.today.length) blocks.push(`<div class="blk"><h3 class="blabel">Your day</h3>${c.today.map((e) => li(e.time || "EOD", "", e.label, e.note)).join("")}</div>`);
      if (c.overnight.length) blocks.push(`<div class="blk"><h3 class="blabel">Done while you slept</h3>${c.overnight.map((e) => li(clock(e.t24), "", e.label, e.note)).join("")}</div>`);
      if (c.running.length) blocks.push(`<div class="blk"><h3 class="blabel">Still in progress</h3>${c.running.map((e) => li(clock(e.t24), "", e.label, e.note)).join("")}</div>`);
      const s = c.stats;
      const ps = s ? `<p class="ps" data-role="body"><span class="w tw">P.S.</span><span>Yesterday we closed <b>${s.done}</b> things${s.you && s.gaia ? ` (you ${s.you}, me ${s.gaia})` : ""}${s.mail ? ` and handled <b>${s.mail}</b> emails` : ""}.${s.focus ? ` You have <b>${esc(s.focus)}</b> of focus ahead.` : ""}</span></p>` : "";
      return `<article class="t-postal" style="--env:${skin.paper.env}; --envInk:${skin.paper.ink}; --tint:${skin.paper.tint}; --mark:${skin.ink.mark}; --ribbon:${skin.ink.ribbon}">
<div class="env"><div class="face tw">${SEAM}${grain("pa-g", 0.8)}<i class="thumb" aria-hidden="true"></i>
  <div class="ret"><img src="${ed.assets.TEC_MARK}" alt="The Experience Company"><span>GAIA Post<br>The Experience Company</span></div>
  <div class="avion"><div>${city.air ? `<span class="loc">${esc(city.air)}</span>` : ""}<b>PAR AVION</b><small>BY AIR MAIL</small></div></div>
  <img class="stamp" src="${ed.assets[city.key]}" alt="${esc(city.label)} stamp">
  <div class="pm">${postmark(ed, city)}</div>
  <div class="addr"><div class="lab">To</div><div class="to">${ed.recipient ? esc(ed.recipient.name) : "You"}</div><div class="re">Re: your ${esc(ed.weekday)}</div><div class="meta">Edition No. ${ed.editionNo} · ${ed.day} ${esc(ed.month)} ${ed.year}</div><div class="under"></div></div>
</div></div>
<div class="letter">${grain("pa-l", 0.9)}
  <div class="lhead tw"><span class="lbrand">GAIA — Daily brief</span><span class="lmeta">No. ${ed.editionNo} · ${esc(ed.time)}</span></div>
  <p class="dated tw">${esc(city.label)}, ${esc(ed.dateLong)}</p>
  <p class="dear">${ed.recipient ? `Dear ${esc(ed.recipient.first)},` : "Good morning,"}</p>
  <p class="deck">${esc(ed.deck)}</p>
  ${blocks.join("")}
  ${ps}
  <p class="sign">Yours, always on watch,<br><span class="sig">GAIA</span></p>
  <div class="lfoot tw"><span>Posted ${esc(ed.time)} · GAIA Post</span><span>Edition No. ${ed.editionNo}</span></div>
</div></article>`;
    },
  });
})();
