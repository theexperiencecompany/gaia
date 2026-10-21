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
  const title = (s) => cap(String(s).toLowerCase());
  const WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];
  const word = (n) => WORDS[n] || String(n);
  const fit = (text, width, ratio, max) => Math.min(max, Math.floor(width / (text.length * ratio)));
  /* Newspaper time style: "1:30 PM" -> "1:30 p.m." */
  const paperTime = (t) => (t ? t.replace(" AM", " a.m.").replace(" PM", " p.m.") : "");
  const sentence = (s) => (/[.!?]$/.test(s) ? s : s + ".");

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
        { id: "didot", label: "Didot", stack: "Didot, 'Bodoni 72', 'Hoefler Text', Georgia, serif", ratio: 0.5 },
        { id: "bodoni", label: "Bodoni 72", stack: "'Bodoni 72', Didot, 'Hoefler Text', Georgia, serif", ratio: 0.5 },
        { id: "hoefler", label: "Hoefler Text", stack: "'Hoefler Text', 'Iowan Old Style', Georgia, serif", ratio: 0.52 },
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
  font: 400 17px/1.5 'Iowan Old Style', 'Hoefler Text', Georgia, serif; -webkit-font-smoothing: antialiased; }
.t-broadsheet * { box-sizing: border-box; margin: 0; padding: 0; }
.t-broadsheet .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .16; }
.t-broadsheet .platefig { margin: 4px 0 18px; }
.t-broadsheet .platebox { position: relative; border: 1px solid var(--rule); }
.t-broadsheet .platebox { overflow: hidden; }
.t-broadsheet .platebox img { display: block; width: 112%; margin-left: -6%; height: 250px; object-fit: cover; object-position: 50% 42%; filter: grayscale(1) contrast(1.2) brightness(1.02) sepia(.15); }
.t-broadsheet .screen { position: absolute; inset: 0; background-image: radial-gradient(circle, rgba(0,0,0,.7) 24%, transparent 30%); background-size: 3.5px 3.5px; mix-blend-mode: multiply; opacity: .35; }
.t-broadsheet .cap { font-size: 14px; line-height: 1.35; color: var(--soft); text-align: center; margin-top: 8px; }
.t-broadsheet .cap span { display: block; font-size: 14px; letter-spacing: 0; margin-top: 2px; }
.t-broadsheet .bk { font-family: Baskerville, 'Hoefler Text', Georgia, serif; }
.t-broadsheet .ears { display: flex; justify-content: space-between; font-size: 14px; line-height: 1.35; letter-spacing: 0; color: var(--soft); }
.t-broadsheet .ears em { display: block; font-style: italic; text-transform: none; letter-spacing: 0; font-size: 14px; }
.t-broadsheet .ears .r { text-align: right; }
.t-broadsheet .plate { font-family: var(--display); font-weight: 700; text-align: center; line-height: .9; letter-spacing: -.01em; white-space: nowrap; margin-top: 8px; }
.t-broadsheet .the { display: block; font-family: Baskerville, 'Hoefler Text', Georgia, serif; font-weight: 400; font-size: 18px; letter-spacing: 0; text-indent: .5em; margin-bottom: 6px; }
.t-broadsheet .dbl { border: 0; border-top: 3px solid var(--rule); border-bottom: 1px solid var(--rule); height: 3px; margin-top: 18px; }
.t-broadsheet .dateline { display: flex; justify-content: center; gap: .6em; font-size: 14px; letter-spacing: 0; color: var(--soft);
  padding: 9px 0 10px; border-bottom: 3px double var(--rule); }
.t-broadsheet .kick { font-size: 14px; letter-spacing: 0; text-align: center; color: var(--soft); padding-bottom: 6px; border-bottom: 1px solid var(--rule); margin-bottom: 14px; }
.t-broadsheet .lead { margin-top: 26px; }
.t-broadsheet .lead h2 { font-family: var(--display); font-weight: 700; font-size: 40px; line-height: 1.04; text-align: center; letter-spacing: -.005em; text-wrap: balance; }
.t-broadsheet .lead .deck { font-style: italic; font-size: 19px; line-height: 1.35; text-align: center; color: var(--soft); margin: 12px auto 0; max-width: 30em; }
.t-broadsheet .short { border: 0; border-top: 1px solid var(--rule); width: 34%; margin: 18px auto 0; }
.t-broadsheet .notice { margin-top: 24px; border: 1px solid var(--rule); border-top: 3px double var(--rule); padding: 12px 16px 14px; }
.t-broadsheet .notice .kick { border-bottom: 0; margin-bottom: 2px; padding-bottom: 0; }
.t-broadsheet .sech { font-family: var(--display); font-weight: 700; text-transform: uppercase; text-align: center; font-size: 23px; letter-spacing: .03em; line-height: 1.05; }
.t-broadsheet .hr { border: 0; border-top: 1px solid var(--rule); width: 46%; margin: 10px auto 14px; }
.t-broadsheet .txt { text-align: justify; hyphens: auto; -webkit-hyphens: auto; }
.t-broadsheet .notice .txt { text-align: left; hyphens: manual; -webkit-hyphens: manual; text-wrap: pretty; }
.t-broadsheet .txt p + p { margin-top: 10px; }
.t-broadsheet .txt.cols { column-count: 2; column-gap: 26px; column-rule: 1px solid var(--hair); text-align: left; hyphens: manual; -webkit-hyphens: manual; text-wrap: pretty; }
.t-broadsheet .platebox.short-plate img { height: 190px; }
.t-broadsheet .txt.cols p { break-inside: avoid; }
.t-broadsheet .cue { font-variant-caps: small-caps; font-weight: 700; letter-spacing: .03em; }
.t-broadsheet .drop::first-letter { font-family: var(--display); font-weight: 700; float: left; font-size: 3.35em; line-height: .78; padding: .05em .08em 0 0; }
.t-broadsheet .story { margin-top: 34px; }
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
.t-broadsheet .imprint { margin-top: 26px; padding-top: 11px; border-top: 3px double var(--rule); text-align: center; font-size: 14px; letter-spacing: 0; color: var(--soft); }
`,
    render(ed, skin) {
      const c = ed.content;
      const needs = c.decisions.slice(0, 3);
      const name = `${ed.weekday} Brief`;
      const size = fit(name, 488, skin.masthead.ratio, 86);
      const orn = `<div class="orn${skin.ornament.id === "rule" ? " plain" : ""}" aria-hidden="true"><i></i><i></i><i></i></div>`;

      const notice = needs.length
        ? `<div class="notice"><div class="kick bk">Awaiting the editor</div><h3 class="sech">Needs your call</h3><hr class="hr"><div class="txt">${needs.map((d) => `<p data-role="body"><span class="cue">${esc(d.verb)}</span> — ${esc(sentence(d.label))}${d.note ? ` ${esc(sentence(cap(d.note)))}` : ""}</p>`).join("")}</div></div>`
        : "";

      let lead = "";
      if (c.today.length) {
        const [first, ...rest] = c.today;
        const lede = `${first.time ? `At ${paperTime(first.time)}` : "Before nightfall"}, ${first.label.charAt(0).toLowerCase()}${first.label.slice(1)}`;
        const firstP = `<p class="${c.today.length >= 2 ? "drop" : ""}" data-role="body">${esc(sentence(lede))}${first.note ? ` ${esc(sentence(cap(first.note)))}` : ""}</p>`;
        const restP = rest.map((e) => `<p data-role="body"><span class="cue">${e.time ? esc(paperTime(e.time)) : "Before nightfall"}</span> — ${esc(sentence(e.label))}${e.note ? ` ${esc(sentence(cap(e.note)))}` : ""}</p>`).join("");
        const a = ed.art;
        const plate = `<figure class="platefig"><div class="platebox${c.today.length < 3 ? " short-plate" : ""}"><img src="${a.src}" alt="${esc(a.title)}, ${esc(a.artist)}, ${a.year}"><i class="screen"></i></div><figcaption class="cap bk"><em>${esc(a.title)}</em>, engraved for this edition after the ${esc(a.medium)}.<span>${esc(a.artist)}, ${a.year} · The Met · Public domain</span></figcaption></figure>`;
        lead = `<div class="story"><div class="kick bk">The day ahead · Lead story</div><h3 class="sech">What matters today</h3><hr class="hr">${plate}<div class="txt${c.today.length >= 3 ? " cols" : ""}">${firstP}${restP}</div></div>`;
      }

      const done = c.overnight.length
        ? `<div class="story"><div class="kick bk">Filed overnight</div><h3 class="sech">While you slept</h3><hr class="hr"><div class="txt${c.overnight.length >= 3 ? " cols" : ""}">${c.overnight.map((e) => `<p data-role="body"><span class="cue">${esc(title(e.tag))}</span> — ${esc(sentence(e.label))}${e.note ? ` ${esc(sentence(cap(e.note)))}` : ""}</p>`).join("")}</div></div>`
        : "";

      const s = c.stats;
      const figs = s
        ? `<div class="figs"><h4 class="bk">The day's figures</h4><table><tr><td class="lab">Done yesterday${s.you && s.gaia ? ` <span class="sub">(you ${s.you} · GAIA ${s.gaia})</span>` : ""}</td><td class="num">${s.done}</td></tr>${s.mail ? `<tr><td class="lab">Emails handled</td><td class="num">${s.mail}</td></tr>` : ""}${s.focus ? `<tr><td class="lab">Focus time today</td><td class="num">${esc(s.focus)}</td></tr>` : ""}</table></div>`
        : "";

      const sections = [notice, lead, done].filter(Boolean);
      return `<article class="t-broadsheet" lang="en" style="--display:${skin.masthead.stack}; --paper:${skin.tone.paper}; --ink:${skin.tone.ink}; --soft:${skin.tone.soft}; --rule:${skin.tone.rule}; --hair:${skin.tone.hair}; --fox:${skin.tone.fox}">
${grain("bs-g", 0.75)}
<div class="ears bk"><div>Edition No. ${ed.editionNo}<em>Compiled by GAIA</em></div><div class="r">Price · Your attention<em>Generated ${esc(ed.time)}</em></div></div>
<h1 class="plate" style="font-size:${size}px"><span class="the">The</span>${esc(name)}</h1>
<hr class="dbl">
<div class="dateline bk"><span>Vol. I</span><span>·</span><span>${esc(ed.weekday)}, ${esc(ed.month)} ${ed.day}, ${ed.year}</span><span>·</span><span>One edition daily</span></div>
<div class="lead"><div class="kick bk">Front page</div><h2>${esc(ed.deck)}</h2><p class="deck bk">${esc(leadDeck(needs.length, c.today.length, c.overnight.length))}</p><hr class="short"></div>
${sections.join(orn)}
${figs}
<div class="imprint bk">Edition No. ${ed.editionNo} · Generated ${esc(ed.time)} by GAIA · Printed for a readership of one</div>
</article>`;
    },
  });
})();
