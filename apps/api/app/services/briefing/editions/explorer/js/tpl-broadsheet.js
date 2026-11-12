/* ============================================================================
   tpl-broadsheet.js (round 2) — the broadsheet front page, re-composed for a
   540 px portrait canvas (export at 3x). Body 17 px Iowan, justified.

   Signature moves kept from the desktop original:
     1. ears flanking a towering Didot nameplate with a spaced "THE"
     2. thick-thin rule, spaced-caps dateline, double-rule underline
     3. kicker over a ruled, centred headline with an italic deck
     4. justified, hyphenated column text with a drop cap; columns separated
        by a hairline column rule (two columns once a story has three items)
     5. small-caps cues ("Approve —", "Draft —"), a boxed figures table with
        dotted rows, and a double-ruled imprint
   Phone re-composition: the deck becomes the lead headline, a boxed
   "Editor's desk" notice carries what needs a call, then the lead story
   (today) and the overnight report, then the figures box.
   ========================================================================== */
(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
  const WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];
  const word = (n) => WORDS[n] || String(n);
  const fit = (text, width, ratio, max) => Math.min(max, Math.floor(width / (text.length * ratio)));

  /* Paper grain: inline SVG fractal noise (no external asset), blended over the sheet at low opacity. */
  const grain = (id, freq) => `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;
  function leadDeck(needs, today, done) {
    const bits = [];
    if (needs) bits.push(`${word(needs).toLowerCase()} call${needs > 1 ? "s" : ""} await${needs > 1 ? "" : "s"} your word`);
    if (today) bits.push(`${word(today).toLowerCase()} engagement${today > 1 ? "s" : ""} on the calendar`);
    if (done) bits.push(`${word(done).toLowerCase()} matter${done > 1 ? "s" : ""} filed overnight`);
    return cap(bits.join("; ")) + ".";
  }

  EXPLORER.register({
    id: "broadsheet",
    name: "The Broadsheet",
    axes: {
      masthead: [
        { id: "caslon", label: "Libre Caslon", stack: "'Broadsheet Caslon', serif", ratio: 0.6 },
      ],
      tone: [
        { id: "warm", label: "warm foxed stock", paper: "#ece2c8", ink: "#211b10", soft: "#463c25", rule: "#2a2213", hair: "rgba(42,34,19,.45)", fox: "rgba(120,86,30,.10)" },
        { id: "neutral", label: "aged neutral stock", paper: "#e7e0cf", ink: "#1a1712", soft: "#3c352b", rule: "#241f18", hair: "rgba(36,31,24,.45)", fox: "rgba(90,70,40,.08)" },
        { id: "salmon", label: "salmon stock", paper: "#f2d9c4", ink: "#1f1712", soft: "#4a362a", rule: "#2a1d15", hair: "rgba(42,29,21,.45)", fox: "rgba(140,70,40,.09)" },
      ],
      ornament: [
        { id: "lozenge", label: "lozenge ornament" },
        { id: "rule", label: "plain rule" },
      ],
    },
    css: `
.t-broadsheet { position: relative; box-sizing: border-box; width: 540px; text-shadow: 0 0 .35px currentColor; padding: 28px 26px 34px; color: var(--ink);
  background:
    radial-gradient(140% 90% at 50% 40%, transparent 55%, var(--fox) 100%),
    repeating-linear-gradient(0deg, rgba(0,0,0,.018) 0 1px, transparent 1px 3px),
    var(--paper);
  font: 400 17px/1.5 'Source Serif 4', serif; -webkit-font-smoothing: antialiased; }
.t-broadsheet * { box-sizing: border-box; margin: 0; padding: 0; }
.t-broadsheet .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .16; }
.t-broadsheet .platefig { margin: 4px 0 18px; }
.t-broadsheet .platebox { position: relative; border: 1px solid var(--rule); }
.t-broadsheet .platebox { overflow: hidden; }
.t-broadsheet .platebox img { display: block; width: 112%; margin-left: -6%; height: 250px; object-fit: cover; object-position: 50% 42%; filter: grayscale(1) contrast(1.2) brightness(1.02) sepia(.15); }
.t-broadsheet .screen { position: absolute; inset: 0; background-image: radial-gradient(circle, rgba(0,0,0,.7) 24%, transparent 30%); background-size: 3.5px 3.5px; mix-blend-mode: multiply; opacity: .35; }
.t-broadsheet .cap { font-size: 14px; line-height: 1.35; color: var(--soft); text-align: center; margin-top: 8px; }
.t-broadsheet .cap span { display: block; font-size: 14px; letter-spacing: 0; margin-top: 2px; }
.t-broadsheet .bk { font-family: 'Broadsheet Caslon', serif; }
.t-broadsheet .ears { display: flex; justify-content: space-between; font-size: 14px; line-height: 1.35; letter-spacing: 0; color: var(--soft); }
.t-broadsheet .ears em { display: block; font-style: italic; text-transform: none; letter-spacing: 0; font-size: 14px; }
.t-broadsheet .ears .r { text-align: right; }
.t-broadsheet .plate { font-family: var(--display); font-weight: 700; text-align: center; line-height: .9; letter-spacing: -.01em; white-space: nowrap; margin-top: 8px; }
.t-broadsheet .the { display: block; font-family: 'Broadsheet Caslon', serif; font-weight: 400; font-size: 18px; letter-spacing: 0; text-indent: .5em; margin-bottom: 6px; }
.t-broadsheet .dbl { border: 0; border-top: 3px solid var(--rule); border-bottom: 1px solid var(--rule); height: 3px; margin-top: 18px; }
.t-broadsheet .dateline { display: flex; justify-content: center; gap: .6em; font-size: 14px; letter-spacing: 0; color: var(--soft);
  padding: 9px 0 10px; border-bottom: 3px double var(--rule); }
.t-broadsheet .kick { font-size: 14px; letter-spacing: 0; text-align: center; color: var(--soft); padding-bottom: 6px; border-bottom: 1px solid var(--rule); margin-bottom: 14px; }
.t-broadsheet .lead { margin-top: 26px; }
.t-broadsheet .lead h2 { font-family: var(--display); font-weight: 700; font-size: 40px; line-height: 1.04; text-align: center; letter-spacing: -.005em; text-wrap: balance; }
.t-broadsheet .lead .deck { font-style: italic; font-size: 19px; line-height: 1.35; text-align: center; color: var(--soft); margin: 12px auto 0; max-width: 30em; }
.t-broadsheet .short { border: 0; border-top: 1px solid var(--rule); width: 34%; margin: 18px auto 0; }
.t-broadsheet .notice { margin-top: 24px; border: 1px solid var(--rule); border-top: 3px double var(--rule); padding: 12px 16px 14px; }
.t-broadsheet .platebox.short-plate img { height: 190px; }
.t-broadsheet .story { margin-top: 34px; padding-top: 14px; border-top: 1px solid var(--rule); }
.t-broadsheet .orn { display: flex; justify-content: center; align-items: center; gap: 10px; margin: 26px 0 0; }
.t-broadsheet .orn i { width: 6px; height: 6px; background: var(--ink); transform: rotate(45deg); }
.t-broadsheet .orn i:nth-child(2) { width: 8px; height: 8px; }
.t-broadsheet .orn.plain i { display: none; }
.t-broadsheet .orn.plain::before { content: ""; width: 34%; border-top: 1px solid var(--rule); }
.t-broadsheet .figs { margin-top: 26px; border: 1px solid var(--rule); border-top-width: 2px; padding: 8px 14px 10px; }
.t-broadsheet .figs h4 { font-weight: 400; font-size: 14px; letter-spacing: 0; text-align: center; padding-bottom: 6px; margin-bottom: 4px; border-bottom: 1px solid var(--rule); }
.t-broadsheet .figs table { width: 100%; border-collapse: collapse; }
.t-broadsheet .figs td { padding: 5px 0; border-bottom: 1px dotted var(--hair); font-size: 17px; }
.t-broadsheet .figs tr:last-child td { border-bottom: 0; }
.t-broadsheet .figs .lab { font-variant-caps: small-caps; letter-spacing: .03em; }
.t-broadsheet .figs .sub { font-size: 14px; color: var(--soft); font-variant-caps: normal; }
.t-broadsheet .figs .num { text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; }
.t-broadsheet .story { padding-top: 6px; }
.t-broadsheet .notice { padding: 0 16px; }
.t-broadsheet .lead-story { border-top-width: 3px; border-top-style: double; }
.t-broadsheet .platefig { margin: 0 0 20px; }
.t-broadsheet .graphic h4 { margin-bottom: 8px; }
.t-broadsheet .dek { font-style: italic; font-size: 17px; line-height: 1.4; margin: 4px 0 10px; text-wrap: pretty; }
.t-broadsheet .key { display: flex; flex-wrap: wrap; gap: 4px 18px; font-size: 14px; color: var(--soft); margin: 0 0 10px; }
.t-broadsheet .key span { display: inline-flex; align-items: center; }
.t-broadsheet .key .sw { display: inline-block; width: 12px; height: 12px; margin-right: 6px; }
.t-broadsheet .key .ht { background-image: radial-gradient(circle, var(--ink) 30%, transparent 32%); background-size: 3.5px 3.5px; }
.t-broadsheet .key .ln { display: inline-block; width: 16px; border-top: 2px solid var(--ink); margin-right: 6px; }
.t-broadsheet .key .ln.dash { border-top: 1.5px dashed var(--ink); }
.t-broadsheet .src { font-size: 14px; color: var(--soft); text-align: right; margin-top: 8px; padding-top: 6px; border-top: 1px solid var(--hair); }
.t-broadsheet .pull { margin: 0 12px; padding: 18px 0 0; font-family: var(--display); font-style: italic; font-variant-ligatures: common-ligatures no-discretionary-ligatures no-historical-ligatures; font-size: 22px; line-height: 1.25; text-align: center; text-wrap: balance; }
.t-broadsheet .pull cite { display: flex; justify-content: center; align-items: center; gap: 6px; font-size: 14px; font-style: italic; color: var(--soft); margin-top: 10px; }
.t-broadsheet .qlogo { width: 13px; height: 13px; color: var(--ink); }
.t-broadsheet .bar { margin: 6px 0 4px; }
.t-broadsheet .desk { border-left: 3px double var(--rule); padding: 2px 0 2px 14px; }
.t-broadsheet .desk .bk { font-variant-caps: small-caps; font-size: 15px; letter-spacing: .04em; color: var(--soft); }
.t-broadsheet .desk .txt { font-style: italic; font-size: 18px; line-height: 1.42; margin-top: 2px; text-wrap: pretty; }
.t-broadsheet { --rs-font: 'Source Serif 4', serif; --rs-font-h: var(--display); --rs-ink: var(--ink); --rs-muted: var(--soft); --rs-acc: var(--ink); --rs-base: 15px; --rs-kick-case: none; --rs-kick-variant: small-caps; --rs-kick-track: .06em; --rs-h-variant: small-caps; --rs-verb-variant: small-caps; }
.t-broadsheet .imprint { margin-top: 26px; padding-top: 11px; border-top: 3px double var(--rule); text-align: center; font-size: 14px; letter-spacing: 0; color: var(--soft); }
.t-broadsheet .wire { margin-top: 10px; }
.t-broadsheet .wire .logos { display: flex; justify-content: center; gap: 12px; margin-bottom: 6px; color: var(--ink); }
.t-broadsheet .wire .xb-logo { width: 15px; height: 15px; }
`,
    render(ed, skin) {
      const B = EXPLORER.blocks;
      const name = `${ed.weekday} Brief`;
      const size = fit(name, 488, skin.masthead.ratio, 86);
      const orn = `<div class="orn${skin.ornament.id === "rule" ? " plain" : ""}" aria-hidden="true"><i></i><i></i><i></i></div>`;
      const W = 458;
      let screens = 0;
      /* The plate's halftone screen, the paper's second tone, as an SVG pattern for a plotted series. */
      const halftone = (svg) => {
        const id = `bs-ht${screens++}`;
        return { id, svg: svg.replace(/(<svg[^>]*>)/, `$1<defs><pattern id="${id}" width="3.5" height="3.5" patternUnits="userSpaceOnUse"><circle cx="1.75" cy="1.75" r="1.05" fill="var(--ink)"/></pattern></defs>`) };
      };
      const PLOT = { w: W, font: "Source Serif 4", size: 14, ink: "var(--ink)", soft: "var(--soft)", rule: "var(--rule)", base: "var(--rule)", ruleW: 1, valueWeight: 700 };
      const plot = (c) => {
        if (c.chart === "spark") return { svg: B.spark(c, { ...PLOT, h: 56, line: "var(--ink)", lineW: 2 }) };
        if (c.chart === "line") return { svg: B.line(c, { ...PLOT, h: 150, rule: "var(--hair)", gutter: 26, lines: [{ color: "var(--ink)", width: 2 }, { color: "var(--ink)", width: 1.5, dash: "4 3" }] }) };
        const id = `bs-ht${screens}`;
        const fills = c.series.length > 1 ? ["var(--ink)", `url(#${id})`, "var(--soft)"] : ["var(--ink)"];
        return halftone(B.bars(c, { ...PLOT, h: 150, fills, gapRatio: 0.42 }));
      };
      const key = (c) => {
        if (c.series.length < 2) return "";
        const sw = c.chart === "line"
          ? (k) => `<i class="ln${k ? " dash" : ""}"></i>`
          : (k) => (k === 1 ? `<i class="sw ht"></i>` : `<i class="sw" style="background:var(--${k ? "soft" : "ink"})"></i>`);
        return B.legend(c, sw).map((x) => `<span>${x}</span>`).join("");
      };
      const sources = (c) => [...new Set(c.series.map((x) => x.app))].join(", ");
      const asks = (b) => b.items.every((it) => it.verb);
      const R = {
        lead: (b) => `<div class="story lead-story">${B.lead(b, { kicker: "Lead story" })}</div>`,
        items: (b) => `<div class="${asks(b) ? "notice" : "story"}">${B.section(b.heading, B.items(b))}</div>`,
        calendar: (b) => {
          const a = ed.art;
          const plate = a
            ? `<figure class="platefig"><div class="platebox${b.events.length < 3 ? " short-plate" : ""}"><img src="${a.src}" alt="${esc(a.title)}, ${esc(a.artist)}, ${a.year}"><i class="screen"></i></div><figcaption class="cap bk"><em>${esc(a.title)}</em>, engraved for this edition after the ${esc(a.medium)}.<span>${esc(a.artist)}, ${a.year} · The Met · Public domain</span></figcaption></figure>`
            : "";
          return `<div class="story">${B.section("Today", B.events(b, { clock: "t12", allDay: "All day" }), { extra: plate })}</div>`;
        },
        chart: (c) => {
          const p = plot(c);
          const facts = B.facts(c, " · ");
          return `<div class="figs graphic" data-block="chart"><h4 class="bk">${esc(c.title)}${facts ? ` · ${esc(facts)}` : ""}</h4><p class="dek">${esc(c.takeaway)}</p>${c.series.length > 1 ? `<p class="key bk">${key(c)}</p>` : ""}${p.svg}<p class="src bk">Source: ${esc(sources(c))}</p></div>`;
        },
        quote: (q) => `<div class="story" data-block="quote"><blockquote class="pull">&ldquo;${esc(q.text)}&rdquo;<cite class="bk">${B.logo(q.logo, { cls: "qlogo" })}${esc(q.author)}, by ${esc(q.app)}</cite></blockquote></div>`,
        progress: (p) => `<div class="figs" data-block="progress"><h4 class="bk">Standing of a goal</h4><table><tr><td class="lab">${esc(p.statement)}</td><td class="num">${p.done} of ${p.total}</td></tr></table><div class="bar">${B.cells(p, { w: W, h: 10, gap: 4, on: "var(--ink)", offStroke: "var(--rule)" })}</div></div>`,
        note: (x) => `<div class="desk" data-block="note"><p class="bk">From GAIA&rsquo;s desk</p><p class="txt">${esc(x.text)}</p></div>`,
      };
      const sections = B.layout(ed, R);
      const count = (pick) => ed.blocks.reduce((n, b) => n + pick(b), 0);
      const placed = (b) => (b.kind === "lead" ? [b.item] : b.kind === "items" ? b.items : []);
      const needs = count((b) => placed(b).filter((it) => it.verb).length);
      const done = count((b) => placed(b).filter((it) => it.outcome).length);
      const today = count((b) => (b.kind === "calendar" ? b.events.length + b.more : 0));
      const s = ed.stats;
      const figs = s
        ? `<div class="figs"><h4 class="bk">The day's figures</h4><table><tr><td class="lab">Done yesterday${s.you && s.gaia ? ` <span class="sub">(you ${s.you} · GAIA ${s.gaia})</span>` : ""}</td><td class="num">${s.done}</td></tr>${s.mail ? `<tr><td class="lab">Emails handled</td><td class="num">${s.mail}</td></tr>` : ""}${s.focus ? `<tr><td class="lab">Focus time today</td><td class="num">${esc(s.focus)}</td></tr>` : ""}</table></div>`
        : "";
      const dek = needs || today || done ? `<p class="deck bk">${esc(leadDeck(needs, today, done))}</p>` : "";
      return `<article class="t-broadsheet" lang="en" style="--display:${skin.masthead.stack}; --paper:${skin.tone.paper}; --ink:${skin.tone.ink}; --soft:${skin.tone.soft}; --rule:${skin.tone.rule}; --hair:${skin.tone.hair}; --fox:${skin.tone.fox}">
${grain("bs-g", 0.75)}
<div class="ears bk"><div>Edition No. ${ed.editionNo}<em>Compiled by GAIA</em></div><div class="r">Price · Your attention<em>Generated ${esc(ed.time)}</em></div></div>
<h1 class="plate" style="font-size:${size}px"><span class="the">The</span>${esc(name)}</h1>
<hr class="dbl">
<div class="dateline bk"><span>Vol. I</span><span>·</span><span>${esc(ed.weekday)}, ${esc(ed.month)} ${ed.day}, ${ed.year}</span><span>·</span><span>One edition daily</span></div>
<div class="lead"><div class="kick bk">Front page</div><h2>${esc(ed.deck)}</h2>${dek}<hr class="short"></div>
${EXPLORER.fold(sections).join(orn)}
${figs}
<div class="imprint bk">Edition No. ${ed.editionNo} · Generated ${esc(ed.time)} by GAIA · Printed for a readership of one${ed.sources.length ? `<div class="wire" data-block="sources"><p class="logos">${ed.sources.map((x) => EXPLORER.blocks.logo(x.logo, { cls: "" })).join("")}</p><p>Reported from your ${esc(EXPLORER.blocks.appList(ed.sources))}</p></div>` : ""}</div>
</article>`;
    },
  });
})();
