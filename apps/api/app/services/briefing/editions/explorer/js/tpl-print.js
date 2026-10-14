/* ============================================================================
   tpl-print.js (round 2) — The Memo and The Almanac on a 540 px portrait
   canvas (export at 3x). Body text 17 px or larger.
   Reading order: headline -> needs you -> today -> done overnight -> stats;
   empty sections are omitted.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
  const sentence = (s) => (/[.!?]$/.test(s) ? s : s + ".");
  const ord = (n) => {
    const v = n % 100;
    return n + (v >= 11 && v <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th");
  };
  /* Paper grain: inline SVG fractal noise, multiplied over the sheet at low opacity. */
  const grain = (id, freq) =>
    `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  /* Rubber-stamp ink: a noise mask knocks small voids out of the impression. */
  const inkMask = (id) =>
    `<svg width="0" height="0" style="position:absolute" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="2" seed="4" result="n"/><feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -1.5 1.55" result="m"/><feComposite in="SourceGraphic" in2="m" operator="in"/></filter></svg>`;

  /* ==========================================================================
     THE MEMO — signature moves from the desktop original:
       a typed sheet laid on a desk with a real shadow; two punch holes;
       MEMORANDUM spaced caps; a TO / FROM / DATE / RE header on a tab stop;
       a dashed typed rule; underlined section heads; numbered typed lists;
       a RECEIVED rubber stamp with the time; dot-leader numbers; "# # #".
     Added detail: a steel paper clip, uneven typewriter ink, a faint carbon
     ghost of the header, worn stamp ink.
     ======================================================================== */
  EXPLORER.register({
    id: "memo",
    name: "The Memo",
    axes: {
      desk: [
        { id: "putty", label: "putty desk", desk: "#b9b3a8", deskB: "#a49d91" },
        { id: "oxblood", label: "oxblood leather", desk: "#6d2a31", deskB: "#541e25" },
        { id: "cobalt", label: "cobalt blotter", desk: "#2c4b94", deskB: "#213a75" },
        { id: "green", label: "green blotter", desk: "#2f5a40", deskB: "#234631" },
      ],
      paper: [
        { id: "bond", label: "bond white", paper: "#f6f3e9", rule: "#b8b1a2" },
        { id: "canary", label: "canary second sheet", paper: "#f5e9b4", rule: "#c9b773" },
      ],
      face: [
        { id: "amtype", label: "American Typewriter", stack: "'American Typewriter', 'Courier New', monospace", size: "17px" },
        { id: "courier", label: "Courier", stack: "'Courier New', Courier, monospace", size: "18px" },
      ],
      stamp: [
        { id: "red", label: "red stamp", ink: "#b02a22" },
        { id: "violet", label: "violet stamp", ink: "#5a3a9a" },
      ],
    },
    css: `
.t-memo { box-sizing: border-box; width: 540px; padding: 40px 24px 48px; background: radial-gradient(120% 80% at 30% 0%, var(--desk) 0%, var(--deskB) 100%); }
.t-memo * { box-sizing: border-box; margin: 0; padding: 0; }
.t-memo .sheet { position: relative; isolation: isolate; background: var(--paper); color: #24221d; font: 400 var(--size)/1.55 var(--face);
  padding: 48px 34px 40px 52px; transform: rotate(-.4deg);
  text-shadow: 0 0 .5px rgba(36,34,29,.55);
  box-shadow: 0 1px 1px rgba(0,0,0,.18), 0 18px 30px -14px rgba(0,0,0,.5); }
.t-memo .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .13; z-index: -1; }
.t-memo .hole { position: absolute; left: 18px; width: 15px; height: 15px; border-radius: 50%; background: var(--deskB);
  box-shadow: inset 0 2px 3px rgba(0,0,0,.55), 0 1px 0 rgba(255,255,255,.5); }
.t-memo .clip { position: absolute; top: -16px; left: 70px; width: 26px; height: 74px; }
.t-memo .title { text-align: center; font-size: 24px; letter-spacing: .5em; padding-left: .5em; }
.t-memo .stamp { position: absolute; top: 96px; right: 26px; transform: rotate(8deg); color: var(--ink); border: 2.5px solid var(--ink); border-radius: 3px;
  padding: 4px 10px 5px; text-align: center; font: 700 15px/1.2 'Courier New', monospace; letter-spacing: .14em; text-shadow: none; opacity: .92; filter: url(#mm-ink); }
.t-memo .stamp b { display: block; font-size: 19px; }
.t-memo .head { position: relative; display: grid; grid-template-columns: 76px 1fr; row-gap: 2px; margin-top: 30px; }
.t-memo .head.ghost { position: absolute; top: 0; left: 0; right: 0; margin: 0; color: #2b3f7a; opacity: .09; transform: translate(2px, 3px); text-shadow: none; }
.t-memo .typed-rule { margin: 20px 0 22px; overflow: hidden; white-space: nowrap; letter-spacing: 0; }
.t-memo .typed-rule::before { content: "- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -"; }
.t-memo .deck { font-size: 22px; line-height: 1.4; }
.t-memo section { margin-top: 38px; }
.t-memo h3 { font-weight: 400; letter-spacing: 0; text-decoration: underline; text-underline-offset: 5px; margin-bottom: 12px; }
.t-memo h3.act { color: var(--ink); }
.t-memo ol { list-style: none; display: grid; gap: 8px; }
.t-memo li { display: grid; grid-template-columns: 32px 1fr; }
.t-memo .verb { color: var(--ink); }
.t-memo .num { display: grid; gap: 4px; font-variant-numeric: tabular-nums; }
.t-memo .num div { display: flex; align-items: baseline; gap: 8px; }
.t-memo .num i { flex: 1; border-bottom: 2px dotted #6d685c; transform: translateY(-5px); }
.t-memo .end { text-align: center; margin-top: 34px; letter-spacing: .4em; }
.t-memo .colo { text-align: center; font-size: 13px; letter-spacing: .08em; margin-top: 6px; color: #4f4b42; }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const numbered = (rows) => {
        let k = 0;
        return `<ol>${rows.map((r) => `<li data-role="body"><span>${++k}.</span><span>${r}</span></li>`).join("")}</ol>`;
      };
      const sections = [];
      if (needs.length) sections.push(`<section><h3 class="act">Needs your call</h3>${numbered(needs.map((d) => `<span class="verb">${esc(d.verb)}:</span> ${esc(d.label)}${d.note ? ` -- ${esc(d.note)}.` : "."}`))}</section>`);
      if (c.today.length) sections.push(`<section><h3>What matters today</h3>${numbered(c.today.map((e) => `${e.time ? `${esc(e.time)} -- ` : ""}${esc(sentence(e.label))}${e.note ? `  ${esc(sentence(cap(e.note)))}` : ""}`))}</section>`);
      if (c.overnight.length) sections.push(`<section><h3>While you slept</h3>${numbered(c.overnight.map((e) => `${esc(sentence(e.label))}${e.note ? `  ${esc(sentence(cap(e.note)))}` : ""}`))}</section>`);
      const s = c.stats;
      if (s) {
        const split = [s.you ? `you ${s.you}` : "", s.gaia ? `GAIA ${s.gaia}` : ""].filter(Boolean).join(", ");
        sections.push(`<section><h3>By the numbers</h3><div class="num">${s.done ? `<div>Done yesterday<i></i>${s.done}${split ? ` (${split})` : ""}</div>` : ""}${s.mail ? `<div>Emails handled<i></i>${s.mail}</div>` : ""}${s.focus ? `<div>Focus time today<i></i>${esc(s.focus)}</div>` : ""}</div></section>`);
      }
      const head = `<span>TO:</span><span>${ed.recipient ? esc(ed.recipient.first) : "You"}</span><span>FROM:</span><span>GAIA</span><span>DATE:</span><span>${esc(ed.dateLong)}</span><span>RE:</span><span>Your ${esc(ed.weekday)} -- Edition No. ${ed.editionNo}</span>`;
      const clip = `<svg class="clip" viewBox="0 0 26 74" aria-hidden="true"><path d="M8 66 V12 a5 5 0 0 1 10 0 V58 a8 8 0 0 1 -16 0 V18" fill="none" stroke="#8d939b" stroke-width="2.4" stroke-linecap="round"/><path d="M8 66 V12 a5 5 0 0 1 10 0" fill="none" stroke="#e9edf1" stroke-width=".8" stroke-linecap="round" transform="translate(-.6 -.4)"/></svg>`;
      return `<article class="t-memo" style="--desk:${skin.desk.desk}; --deskB:${skin.desk.deskB}; --paper:${skin.paper.paper}; --rule:${skin.paper.rule}; --face:${skin.face.stack}; --size:${skin.face.size}; --ink:${skin.stamp.ink}">
${inkMask("mm-ink")}
<div class="sheet">${grain("mm-g", 0.85)}
  <i class="hole" style="top:30%"></i><i class="hole" style="top:70%"></i>${clip}
  <div class="title">MEMORANDUM</div>
  <div class="stamp">RECEIVED<b>${esc(ed.time)}</b></div>
  <div class="head"><div class="head ghost" aria-hidden="true">${head}</div>${head}</div>
  <div class="typed-rule" aria-hidden="true"></div>
  <p class="deck">${esc(ed.deck)}</p>
  ${sections.join("")}
  <p class="end">###</p>
  <p class="colo">EDITION NO. ${ed.editionNo} -- TYPED ${esc(ed.time)} BY GAIA</p>
</div></article>`;
    },
  });

  /* ==========================================================================
     THE ALMANAC — signature moves from the desktop original:
       a centred small-caps title page ("Being a faithful account of the
       day's business", "for the 3rd Day of July, Anno 2026"); fleuron
       ornaments; a double-ruled "Calculations for the Day" table; small-caps
       section heads over hairlines; pilcrow-led paragraphs; a framed
       engraved plate of the painting; a "Reckoning of the day" colophon.
     Added detail: letterpress impression, foxing spots, a deckled edge.
     ======================================================================== */
  const fleuron = `<svg class="fleu" viewBox="0 0 40 24" aria-hidden="true"><circle cx="20" cy="6" r="3.4"/><circle cx="13" cy="17" r="3.4"/><circle cx="27" cy="17" r="3.4"/></svg>`;
  EXPLORER.register({
    id: "almanac",
    name: "The Almanac",
    axes: {
      paper: [
        { id: "tallow", label: "aged tallow", paper: "#efe5c9", hair: "#bcaa80", fox: "rgba(140,96,40,.16)" },
        { id: "linen", label: "linen", paper: "#f3eee2", hair: "#c3b89e", fox: "rgba(120,90,50,.12)" },
        { id: "sage", label: "sage wrapper", paper: "#dfe6d0", hair: "#a6b48f", fox: "rgba(90,90,40,.14)" },
      ],
      rubric: [
        { id: "ink", label: "black only", rub: "#2a241a" },
        { id: "vermilion", label: "vermilion rubric", rub: "#9e2e1b" },
      ],
      face: [
        { id: "hoefler", label: "Hoefler Text", stack: "'Hoefler Text', Baskerville, Georgia, serif" },
        { id: "baskerville", label: "Baskerville", stack: "Baskerville, 'Hoefler Text', Georgia, serif" },
      ],
      plate: [
        { id: "engraving", label: "engraved plate" },
        { id: "none", label: "no plate" },
      ],
    },
    css: `
.t-almanac { position: relative; isolation: isolate; box-sizing: border-box; width: 540px; padding: 44px 40px 48px; color: #2a241a;
  background: radial-gradient(130% 90% at 50% 45%, transparent 55%, var(--fox) 100%), var(--paper);
  font: 400 18px/1.55 var(--face); text-shadow: 0 .4px 0 rgba(42,36,26,.35); }
.t-almanac * { box-sizing: border-box; margin: 0; padding: 0; }
.t-almanac .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .16; z-index: -1; }
.t-almanac .spot { position: absolute; border-radius: 50%; background: var(--fox); filter: blur(1.5px); z-index: -1; }
.t-almanac .c { text-align: center; }
.t-almanac .sc { font-variant-caps: small-caps; letter-spacing: .03em; }
.t-almanac .eyebrow { font-size: 16px; color: var(--rub); }
.t-almanac h1 { font-weight: 400; font-variant-caps: small-caps; font-size: 44px; line-height: 1.05; letter-spacing: .02em; margin-top: 10px; }
.t-almanac .sub { font-style: italic; font-size: 19px; margin-top: 10px; }
.t-almanac .for { font-size: 17px; margin-top: 10px; }
.t-almanac .fleu { display: block; width: 30px; height: 18px; margin: 20px auto; fill: var(--rub); }
.t-almanac .deck { font-style: italic; font-size: 23px; line-height: 1.38; text-align: center; padding: 0 8px; }
.t-almanac section { margin-top: 44px; }
.t-almanac h2 { font-weight: 400; text-align: center; font-size: 17px; padding-bottom: 6px; border-bottom: 1px solid var(--hair); margin: 0 18px 14px; }
.t-almanac .p { display: grid; grid-template-columns: 22px 1fr; padding: 5px 0; }
.t-almanac .p .pil { color: var(--rub); }
.t-almanac .p em { font-style: italic; }
.t-almanac .calc { margin-top: 30px; border-top: 3px double #2a241a; border-bottom: 3px double #2a241a; padding: 8px 0 10px; }
.t-almanac .calc h2 { border: 0; margin: 0 0 4px; padding: 0; font-size: 15px; }
.t-almanac .calc .row { display: grid; grid-template-columns: repeat(3, 1fr); text-align: center; }
.t-almanac .calc b { display: block; font-weight: 400; font-size: 30px; line-height: 1.1; font-variant-numeric: lining-nums tabular-nums; }
.t-almanac .calc span { font-size: 15px; }
.t-almanac figure { margin: 34px auto 0; width: 300px; }
.t-almanac .frame { padding: 6px; border: 3px double #2a241a; }
.t-almanac .frame img { display: block; width: 100%; height: 200px; object-fit: cover; filter: grayscale(1) contrast(1.35) brightness(.98) sepia(.2); }
.t-almanac figcaption { text-align: center; font-size: 15px; margin-top: 8px; line-height: 1.4; }
.t-almanac .reck { margin-top: 30px; text-align: center; font-size: 15px; line-height: 1.55; }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const p = (lead, body) => `<div class="p" data-role="body"><span class="pil">¶</span><span>${lead ? `<em>${lead}</em> — ` : ""}${body}</span></div>`;
      const secs = [];
      if (needs.length) secs.push(`<section><h2 class="sc">Matters for your judgement</h2>${needs.map((d) => p(`To ${esc(d.verb.toLowerCase())}`, `${esc(sentence(d.label))}${d.note ? ` ${esc(sentence(cap(d.note)))}` : ""}`)).join("")}</section>`);
      if (c.today.length) secs.push(`<section><h2 class="sc">What matters to-day</h2>${c.today.map((e) => p(e.time ? esc(e.time.replace(/ (AM|PM)/, "")) : "", `${esc(sentence(e.label))}${e.note ? ` ${esc(sentence(cap(e.note)))}` : ""}`)).join("")}</section>`);
      if (c.overnight.length) secs.push(`<section><h2 class="sc">Work performed in the night</h2>${c.overnight.map((e) => p("", `${esc(sentence(e.label))}${e.note ? ` ${esc(sentence(cap(e.note)))}` : ""}`)).join("")}</section>`);
      const s = c.stats;
      const calc = s ? `<div class="calc"><h2 class="sc">Calculations for the day</h2><div class="row">${s.done ? `<div><b>${s.done}</b><span class="sc">tasks done</span></div>` : ""}${s.mail ? `<div><b>${s.mail}</b><span class="sc">letters</span></div>` : ""}${s.focus ? `<div><b>${esc(s.focus)}</b><span class="sc">focus hours</span></div>` : ""}</div></div>` : "";
      const a = ed.art;
      const plate = skin.plate.id === "engraving" ? `<figure><div class="frame"><img src="${a.src}" alt="${esc(a.title)}, ${esc(a.artist)}"></div><figcaption><span class="sc">Plate I. — ${esc(a.title)}</span><br><i>${esc(a.artist)}, ${a.year}, ${esc(a.medium)}</i></figcaption></figure>` : "";
      return `<article class="t-almanac" style="--paper:${skin.paper.paper}; --hair:${skin.paper.hair}; --fox:${skin.paper.fox}; --rub:${skin.rubric.rub}; --face:${skin.face.stack}">
${grain("al-g", 0.7)}<i class="spot" style="top:12%; left:8%; width:9px; height:7px"></i><i class="spot" style="top:58%; right:6%; width:12px; height:10px"></i><i class="spot" style="bottom:9%; left:20%; width:6px; height:6px"></i>
<div class="c"><div class="eyebrow sc">The Almanac</div><h1>The ${esc(ed.weekday)} Brief</h1><p class="sub">Being a faithful account of the day's business</p><p class="for sc">for the ${ord(ed.day)} day of ${esc(ed.month)}, anno ${ed.year} — No. ${ed.editionNo}</p></div>
${fleuron}
<p class="deck">${esc(ed.deck)}</p>
${secs.join("")}
${calc}
${plate}
${fleuron}
<p class="reck sc">Reckoning of the day${s ? ` — ${s.done} tasks accomplished${s.you && s.gaia ? `, whereof ${s.you} by your own hand and ${s.gaia} by the machine` : ""}` : ""}. Printed at ${esc(ed.time)} by GAIA.</p>
</article>`;
    },
  });
})();
