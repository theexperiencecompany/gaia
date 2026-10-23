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

  /* Every texture, tilt and noise seed is drawn from the edition's date, so one day always prints the same envelope. */
  function rngFor(ed) {
    let h = 2166136261;
    for (const ch of `${ed.year}-${ed.monthShort}-${ed.day}`) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
    return () => {
      h = (h + 0x6d2b79f5) | 0;
      let t = Math.imul(h ^ (h >>> 15), 1 | h);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const seedOf = (rng) => 1 + Math.floor(rng() * 900);
  const lerp = (rng, a, b) => (a + (b - a) * rng()).toFixed(2);

  /* The envelope sheet: kraft fibres in three directions, tonal mottling, a printed chevron border with uneven ink,
     the back flaps embossed through the face under a raking light, and scuffed, grimy edges. */
  function paper(rng) {
    const W = 496;
    const H = 444;
    const b = 12;
    const s = () => seedOf(rng);
    const fibres = (id, angle, color, opacity) =>
      `<g transform="rotate(${angle} ${W / 2} ${H / 2})" opacity="${opacity}"><rect x="-160" y="-160" width="${W + 320}" height="${H + 320}" fill="${color}" filter="url(#${id})"/></g>`;
    const fibreFilter = (id, freq, cut) =>
      `<filter id="${id}" filterUnits="userSpaceOnUse" x="-160" y="-160" width="${W + 320}" height="${H + 320}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" seed="${s()}"/><feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  ${cut[0]} 0 0 0 ${cut[1]}"/><feComposite in="SourceGraphic" operator="in"/></filter>`;
    const region = `filterUnits="userSpaceOnUse" x="0" y="0" width="${W}" height="${H}" color-interpolation-filters="sRGB"`;
    return `<svg class="paper" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><defs>
<pattern id="ap-chev" width="46" height="46" patternUnits="userSpaceOnUse" patternTransform="rotate(-40)"><rect width="13" height="46" fill="#b2372c"/><rect x="23" width="13" height="46" fill="#25498a"/></pattern>
<filter id="ap-print" ${region}><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="${s()}" result="n"/><feDisplacementMap in="SourceGraphic" in2="n" scale="1" xChannelSelector="R" yChannelSelector="G" result="d"/><feTurbulence type="fractalNoise" baseFrequency=".035 .06" numOctaves="3" seed="${s()}" result="p"/><feColorMatrix in="p" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -.9 0 0 0 1.4" result="pm"/><feComposite in="d" in2="pm" operator="in"/></filter>
<filter id="ap-mott" ${region}><feTurbulence type="fractalNoise" baseFrequency=".0045 .007" numOctaves="4" seed="${s()}"/><feColorMatrix type="matrix" values="0 0 0 0 .32  0 0 0 0 .19  0 0 0 0 .06  1.5 0 0 0 -.6"/></filter>
${fibreFilter("ap-fd", ".07 .9", [12, -8.6])}${fibreFilter("ap-fl", ".07 .9", [12, -8.7])}
<filter id="ap-grain" ${region}><feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="3" seed="${s()}"/><feColorMatrix type="matrix" values="0 0 0 0 .2  0 0 0 0 .13  0 0 0 0 .05  -1.2 0 0 0 .78"/></filter>
<filter id="ap-relief" ${region}><feGaussianBlur in="SourceAlpha" stdDeviation="1.8" result="h0"/><feTurbulence type="fractalNoise" baseFrequency=".6" numOctaves="3" seed="${s()}" result="t"/><feColorMatrix in="t" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  .07 0 0 0 0" result="ta"/><feComposite in="h0" in2="ta" operator="arithmetic" k2="1" k3="1" result="h"/><feDiffuseLighting in="h" surfaceScale="2.4" diffuseConstant="1" lighting-color="#b5b5b5"><feDistantLight azimuth="225" elevation="45"/></feDiffuseLighting></filter>
<filter id="ap-wear" ${region}><feMorphology in="SourceAlpha" operator="erode" radius="4" result="in"/><feGaussianBlur in="in" stdDeviation="2.5" result="inb"/><feComposite in="SourceAlpha" in2="inb" operator="arithmetic" k2="1" k3="-1" result="band"/><feTurbulence type="fractalNoise" baseFrequency=".18 .3" numOctaves="3" seed="${s()}" result="sn"/><feColorMatrix in="sn" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  8 0 0 0 -4.7" result="spots"/><feComposite in="spots" in2="band" operator="arithmetic" k1="1.6" result="scuff"/><feFlood flood-color="#fbf3df"/><feComposite in2="scuff" operator="in" result="light"/><feGaussianBlur in="band" stdDeviation="3" result="bb"/><feFlood flood-color="#2b1a08" flood-opacity=".16"/><feComposite in2="bb" operator="in" result="grime"/><feMerge><feMergeNode in="grime"/><feMergeNode in="light"/></feMerge></filter>
</defs>
<rect width="${W}" height="${H}" fill="var(--env)"/>
<rect width="${W}" height="${H}" fill="var(--tint)"/>
<rect width="${W}" height="${H}" filter="url(#ap-mott)" opacity=".4"/>
<path fill="url(#ap-chev)" fill-rule="evenodd" filter="url(#ap-print)" d="M0 0H${W}V${H}H0Z M${b} ${b}V${H - b}H${W - b}V${b}Z"/>
${fibres("ap-fd", lerp(rng, 10, 40), "#4a2e10", 0.13)}${fibres("ap-fd", lerp(rng, -60, -30), "#4a2e10", 0.1)}${fibres("ap-fl", lerp(rng, 70, 100), "#fff4d6", 0.2)}${fibres("ap-fl", lerp(rng, -20, 5), "#fff4d6", 0.16)}
<rect width="${W}" height="${H}" filter="url(#ap-grain)" style="mix-blend-mode:multiply" opacity=".22"/>
<g filter="url(#ap-relief)" style="mix-blend-mode:overlay" opacity=".7">
<path fill-opacity=".34" d="M0 2 C70 70 160 170 214 226 Q 222 236 214 246 C160 302 70 380 0 442Z M${W} 2 C${W - 70} 70 ${W - 160} 170 ${W - 214} 226 Q ${W - 222} 236 ${W - 214} 246 C${W - 160} 302 ${W - 70} 380 ${W} 442Z"/>
<path fill-opacity=".42" d="M0 ${H} C110 352 182 270 236 250 Q 248 246 260 250 C314 270 386 352 ${W} ${H}Z"/>
<path fill-opacity=".2" d="M0 0 C96 66 196 170 240 198 Q 248 202 256 198 C300 170 400 66 ${W} 0Z"/>
</g>
<rect width="${W}" height="${H}" filter="url(#ap-wear)"/>
</svg>`;
  }

  /* The blue etiquette: die-cut perforated label paper, a one-colour plate printed a hair off-register, the double rule,
     plane and lettering knocked out to the paper, ink that thins at a rubbed corner. */
  function etiquette(city, rng) {
    const W = 204;
    const top = city.air ? 14 : 0;
    const H = 62 + top;
    const dx = lerp(rng, -0.9, 0.9);
    const dy = lerp(rng, -0.7, 0.5);
    const holes = [];
    for (let x = 3; x < W; x += 5.6) holes.push(`<circle cx="${x.toFixed(1)}" cy="0" r="1.7"/><circle cx="${x.toFixed(1)}" cy="${H}" r="1.7"/>`);
    for (let y = 3; y < H; y += 5.6) holes.push(`<circle cx="0" cy="${y.toFixed(1)}" r="1.7"/><circle cx="${W}" cy="${y.toFixed(1)}" r="1.7"/>`);
    const plane = `<path transform="translate(25 ${top + 31}) rotate(-24) scale(.95)" d="M16 0C16 -1.4 14 -2.1 11 -2.1L-12 -1.6C-15 -1.4 -16 -.6 -16 0C-16 .6 -15 1.4 -12 1.6L11 2.1C14 2.1 16 1.4 16 0Z M3 -1.9L-4.5 -13.5H-1.6L8.5 -1.9Z M3 1.9L-4.5 13.5H-1.6L8.5 1.9Z M-10.5 -1.5L-15 -6.8H-12.8L-7.6 -1.5Z M-10.5 1.5L-15 6.8H-12.8L-7.6 1.5Z"/>`;
    return `<svg class="etq" viewBox="0 0 ${W} ${H}" aria-hidden="true"><defs>
<mask id="ap-die" maskUnits="userSpaceOnUse" x="0" y="0" width="${W}" height="${H}"><rect width="${W}" height="${H}" fill="#fff"/><g fill="#000">${holes.join("")}</g></mask>
<radialGradient id="ap-rubg" cx="${W - 3}" cy="${H - 2}" r="30" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#000"/><stop offset=".35" stop-color="#000" stop-opacity=".7"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>
<mask id="ap-knock" maskUnits="userSpaceOnUse" x="-4" y="-4" width="${W + 8}" height="${H + 8}"><rect x="-4" y="-4" width="${W + 8}" height="${H + 8}" fill="#fff"/>
<g fill="none" stroke="#000"><rect x="6.5" y="6.5" width="${W - 13}" height="${H - 13}" stroke-width="1.15"/><rect x="9.3" y="9.3" width="${W - 18.6}" height="${H - 18.6}" stroke-width=".5"/><path d="M45 ${top + 13}V${H - 13}" stroke-width=".5"/></g>
<g fill="#000">${plane}
${city.air ? `<text x="${(W + 45) / 2}" y="24" text-anchor="middle" font-size="11.5" font-weight="600" style="font-family:'Hiragino Sans','Noto Sans CJK JP','Kohinoor Devanagari','Noto Sans Devanagari','Helvetica Neue',sans-serif">${esc(city.air)}</text>` : ""}
<text x="${(W + 45) / 2}" y="${top + 34}" text-anchor="middle" font-size="22" font-weight="700" letter-spacing=".9" style="font-family:'Playfair Display',Georgia,serif">PAR AVION</text>
<text x="${(W + 45) / 2}" y="${top + 49}" text-anchor="middle" font-size="8.6" font-weight="600" letter-spacing="2.1" style="font-family:'Aeonik Extended','Helvetica Neue',sans-serif">BY AIR MAIL</text></g>
<rect x="-4" y="-4" width="${W + 8}" height="${H + 8}" fill="url(#ap-rubg)" filter="url(#ap-rubn)"/></mask>
<filter id="ap-rubn" x="0" y="0" width="1" height="1"><feTurbulence type="fractalNoise" baseFrequency=".35" numOctaves="2" seed="${seedOf(rng)}" result="n"/><feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 2.2 -.7" result="na"/><feComposite in="SourceGraphic" in2="na" operator="in"/></filter>
<filter id="ap-plate" x="-2%" y="-4%" width="104%" height="108%" color-interpolation-filters="sRGB"><feTurbulence type="fractalNoise" baseFrequency="1.4" numOctaves="2" seed="${seedOf(rng)}" result="n"/><feDisplacementMap in="SourceGraphic" in2="n" scale=".7" xChannelSelector="R" yChannelSelector="G" result="d"/><feTurbulence type="fractalNoise" baseFrequency=".3 .5" numOctaves="2" seed="${seedOf(rng)}" result="p"/><feColorMatrix in="p" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -.5 0 0 0 1.2" result="pm"/><feComposite in="d" in2="pm" operator="in"/></filter>
<filter id="ap-lgrain" x="0" y="0" width="1" height="1"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="${seedOf(rng)}"/><feColorMatrix type="matrix" values="0 0 0 0 .3  0 0 0 0 .26  0 0 0 0 .2  -1 0 0 0 .62"/></filter>
</defs>
<g mask="url(#ap-die)"><rect width="${W}" height="${H}" fill="#f6f2e7"/>
<g transform="translate(${dx} ${dy})"><rect x="3" y="3" width="${W - 6}" height="${H - 6}" fill="#1d4796" mask="url(#ap-knock)" filter="url(#ap-plate)"/></g>
<rect width="${W}" height="${H}" filter="url(#ap-lgrain)" opacity=".7"/></g></svg>`;
  }

  /* A small engraved definitive beside the city stamp: perforated margin, a line-engraved frame and a guilloche
     rosette behind the denomination, printed in one deep ink. */
  function definitive(rng) {
    const W = 64;
    const H = 78;
    const holes = [];
    for (let x = 2.6; x < W; x += 4.4) holes.push(`<circle cx="${x.toFixed(1)}" cy="0" r="1.45"/><circle cx="${x.toFixed(1)}" cy="${H}" r="1.45"/>`);
    for (let y = 2.6; y < H; y += 4.4) holes.push(`<circle cx="0" cy="${y.toFixed(1)}" r="1.45"/><circle cx="${W}" cy="${y.toFixed(1)}" r="1.45"/>`);
    const rosette = [];
    for (let k = 0; k < 18; k++) rosette.push(`<ellipse cx="32" cy="41" rx="19" ry="7.2" transform="rotate(${k * 10} 32 41)"/>`);
    const hatch = [];
    for (let y = 9; y < 70; y += 1.6) hatch.push(`M8 ${y.toFixed(1)}H56`);
    return `<svg class="defin" viewBox="0 0 ${W} ${H}" aria-hidden="true"><defs>
<mask id="ap-dperf" maskUnits="userSpaceOnUse" x="0" y="0" width="${W}" height="${H}"><rect width="${W}" height="${H}" fill="#fff"/><g fill="#000">${holes.join("")}</g></mask>
<clipPath id="ap-dwin"><rect x="8" y="9" width="48" height="60"/></clipPath>
<filter id="ap-dink" x="0" y="0" width="1" height="1"><feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="2" seed="${seedOf(rng)}" result="n"/><feDisplacementMap in="SourceGraphic" in2="n" scale=".45" xChannelSelector="R" yChannelSelector="G"/></filter>
</defs>
<g mask="url(#ap-dperf)"><rect width="${W}" height="${H}" fill="#f7f3e8"/>
<g filter="url(#ap-dink)" fill="none" stroke="var(--defin)">
<g clip-path="url(#ap-dwin)" stroke-width=".32" opacity=".55"><path d="${hatch.join("")}"/></g>
<rect x="8" y="9" width="48" height="60" stroke-width="1.3"/>
<rect x="5.6" y="6.6" width="52.8" height="64.8" stroke-width=".45"/>
<rect x="12" y="13" width="40" height="11" fill="var(--defin)" stroke="none"/>
<rect x="12" y="58" width="40" height="7" fill="var(--defin)" stroke="none"/>
<g stroke-width=".35"><ellipse cx="32" cy="41" rx="16" ry="14" fill="#f7f3e8"/>${rosette.join("")}</g>
<circle cx="32" cy="41" r="9.6" fill="#f7f3e8" stroke-width=".7"/>
</g>
<g fill="var(--defin)" style="font-family:'Playfair Display',Georgia,serif"><text x="32" y="46.2" text-anchor="middle" font-size="14.5" font-weight="700">25</text></g>
<g fill="#f7f3e8" style="font-family:'Aeonik Extended','Helvetica Neue',sans-serif" font-weight="600" text-anchor="middle"><text x="32" y="21.2" font-size="6.4" letter-spacing="1.4">GAIA</text><text x="32" y="63.4" font-size="4.6" letter-spacing="1.1">AIR MAIL</text></g>
</g></svg>`;
  }

  /* A hand-struck duplex cancellation set beside the stamp: a double-ring datestamp (city on the upper arc,
     GAIA POST on the lower, the date in a ruled band) and a killer of wavy lines on the envelope. The ink pools at
     the edges, thins where the rubber met the paper unevenly, breaks into dry streaks, and leans heavier on one side. */
  function postmark(ed, city, rng) {
    const cx = 232;
    const cy = 64;
    const name = city.city;
    const size = name.length > 13 ? 9 : name.length > 10 ? 10 : 11.5;
    const waves = [0, 1, 2, 3, 4, 5, 6]
      .map((i) => {
        const y = 31 + i * 11;
        let d = `M40 ${y} q6.5 -3.4 13 0`;
        for (let k = 0; k < 8; k++) d += " t13 0";
        return `<path d="${d}"/>`;
      })
      .join("");
    const star = (x) => `<path transform="translate(${x} ${cy}) scale(2.7)" d="M0 -1 L.24 -.32 L.95 -.31 L.38 .12 L.59 .81 L0 .4 L-.59 .81 L-.38 .12 L-.95 -.31 L-.24 -.32Z"/>`;
    const font = `font-family="'Aeonik Extended','Helvetica Neue',Arial,sans-serif" font-weight="600"`;
    const angle = lerp(rng, 0, 1) < 0.5 ? lerp(rng, -150, -100) : lerp(rng, 20, 70);
    const mark = `<g fill="none" stroke="currentColor" stroke-width="2.9" stroke-linecap="round">${waves}</g>
<circle cx="${cx}" cy="${cy}" r="57" fill="none" stroke="currentColor" stroke-width="2.6"/>
<circle cx="${cx}" cy="${cy}" r="38" fill="none" stroke="currentColor" stroke-width="1.3"/>
<g ${font}>
<text font-size="${size}" letter-spacing="${size < 11 ? 0.8 : 2.2}" text-anchor="middle"><textPath href="#ap-arc-t" startOffset="50%">${esc(name)}</textPath></text>
<text font-size="10.5" letter-spacing="2.4" text-anchor="middle"><textPath href="#ap-arc-b" startOffset="50%">GAIA POST</textPath></text>
<text x="${cx}" y="${cy + 5.2}" text-anchor="middle" font-size="13.5" font-weight="700" letter-spacing=".5">${ed.day} ${esc(ed.monthShort.toUpperCase())} ${String(ed.year).slice(2)}</text>
<text x="${cx}" y="${cy - 16}" text-anchor="middle" font-size="10" letter-spacing="1.2">${esc(ed.time24)}</text>
<text x="${cx}" y="${cy + 26}" text-anchor="middle" font-size="10" letter-spacing="1.6">${ed.time24 < "12:00" ? "AM" : "PM"}</text></g>
<path d="M${cx - 36} ${cy - 9.5}H${cx + 36}M${cx - 36} ${cy + 10}H${cx + 36}" stroke="currentColor" stroke-width="1.1"/>
${star(cx - 47.5)}${star(cx + 47.5)}`;
    return `<svg viewBox="0 0 300 128" aria-hidden="true"><defs>
<path id="ap-arc-t" d="M ${cx - 42.5} ${cy} A 42.5 42.5 0 0 1 ${cx + 42.5} ${cy}"/>
<path id="ap-arc-b" d="M ${cx - 51.8} ${cy} A 51.8 51.8 0 0 0 ${cx + 51.8} ${cy}"/>
<linearGradient id="ap-press" gradientUnits="userSpaceOnUse" x1="150" y1="64" x2="${(150 + 160 * Math.cos((angle * Math.PI) / 180)).toFixed(1)}" y2="${(64 + 160 * Math.sin((angle * Math.PI) / 180)).toFixed(1)}"><stop offset="0" stop-color="#fff" stop-opacity=".62"/><stop offset="1" stop-color="#fff"/></linearGradient>
<mask id="ap-pressm" maskUnits="userSpaceOnUse" x="0" y="0" width="300" height="128"><rect width="300" height="128" fill="url(#ap-press)"/></mask>
<filter id="ap-ink" filterUnits="userSpaceOnUse" x="0" y="0" width="300" height="128" color-interpolation-filters="sRGB">
<feTurbulence type="fractalNoise" baseFrequency="1.1" numOctaves="2" seed="${seedOf(rng)}" result="e"/>
<feDisplacementMap in="SourceGraphic" in2="e" scale="1.5" xChannelSelector="R" yChannelSelector="G" result="rough"/>
<feMorphology in="rough" operator="erode" radius=".75" result="core"/>
<feComposite in="rough" in2="core" operator="out" result="rim"/>
<feColorMatrix in="core" type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 .72 0" result="soft"/>
<feMerge result="body"><feMergeNode in="soft"/><feMergeNode in="rim"/></feMerge>
<feTurbulence type="fractalNoise" baseFrequency=".05 .8" numOctaves="3" seed="${seedOf(rng)}" result="st"/>
<feColorMatrix in="st" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -6 0 0 0 4.6" result="gap"/>
<feComponentTransfer in="gap" result="dry"><feFuncA type="linear" slope=".72" intercept=".28"/></feComponentTransfer>
<feTurbulence type="fractalNoise" baseFrequency=".04" numOctaves="2" seed="${seedOf(rng)}" result="pr"/>
<feColorMatrix in="pr" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -2.2 0 0 0 2.05" result="press"/>
<feComposite in="dry" in2="press" operator="arithmetic" k1="1" result="ink"/>
<feComposite in="body" in2="ink" operator="in"/></filter></defs>
<g fill="currentColor" mask="url(#ap-pressm)"><g filter="url(#ap-ink)">${mark}</g></g></svg>`;
  }

  /* Letter grain: inline SVG fractal noise (no external asset), blended over the sheet at low opacity. */
  const grain = (id, freq) => `<svg class="grain" aria-hidden="true"><filter id="${id}"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`;

  EXPLORER.register({
    id: "postal",
    name: "Air Mail",
    axes: {
      /* Every hosted city stamp, supplied by the host page as EXPLORER.cities ({id, label, key, city, air}). */
      city: EXPLORER.cities,
      paper: [
        { id: "honey", label: "honey kraft", env: "#efd7a4", ink: "#3a2a12", tint: "rgba(170,110,30,.08)" },
        { id: "laid", label: "ivory laid", env: "#f6ecd6", ink: "#33291c", tint: "rgba(150,110,50,.06)" },
        { id: "airmail", label: "airmail blue", env: "#dce8f5", ink: "#1f2c44", tint: "rgba(40,70,140,.06)" },
      ],
      ink: [
        { id: "black", label: "black postmark", mark: "#26231e", ribbon: "#a3352a", defin: "#86282a" },
      ],
    },
    css: `
.t-postal { box-sizing: border-box; width: 540px; padding: 40px 22px 56px; overflow: hidden; color: #2a2822;
  background-color: #23262a;
  background-image: radial-gradient(120% 80% at 50% 0%, rgba(255,255,255,.06), transparent 60%),
    repeating-linear-gradient(94deg, rgba(0,0,0,.12) 0 2px, rgba(255,255,255,.014) 2px 5px); }
.t-postal * { box-sizing: border-box; margin: 0; padding: 0; }
.t-postal .tw { font-family: 'American Typewriter', 'Courier New', monospace; }
.t-postal .env { position: relative; padding: 12px; transform: rotate(-1deg); background-color: var(--env);
  box-shadow: 0 1px 1px rgba(0,0,0,.3), 0 3px 6px rgba(0,0,0,.18), 0 26px 44px rgba(0,0,0,.45); }
.t-postal .paper { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.t-postal .face { position: relative; height: 420px; overflow: hidden; color: var(--envInk); }
.t-postal .grain { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; mix-blend-mode: multiply; opacity: .09; }
.t-postal .ret { position: absolute; top: 20px; left: 22px; display: grid; grid-template-columns: 26px auto; column-gap: 9px; align-items: center; font-size: 13px; line-height: 1.35; }
.t-postal .ret img { width: 26px; height: auto; opacity: .85; mix-blend-mode: multiply; }
.t-postal .etq { position: absolute; top: 184px; left: 22px; width: 176px; height: auto; transform: rotate(-2deg); transform-origin: 0 0;
  filter: drop-shadow(0 .5px .4px rgba(40,25,5,.45)) drop-shadow(0 1.5px 2px rgba(40,25,5,.16)); }
.t-postal .stamp { position: absolute; top: 18px; right: 20px; width: 152px; transform: rotate(1.4deg);
  filter: drop-shadow(0 .5px .5px rgba(30,18,4,.5)) drop-shadow(0 2px 2.5px rgba(30,18,4,.22)) drop-shadow(0 7px 9px rgba(30,18,4,.12)); }
.t-postal .defin { position: absolute; top: 21px; right: 178px; width: 60px; height: auto; transform: rotate(-.8deg);
  filter: drop-shadow(0 .5px .4px rgba(30,18,4,.5)) drop-shadow(0 1.5px 2px rgba(30,18,4,.2)); }
.t-postal .pm { position: absolute; top: 66px; left: 8px; width: 250px; height: 107px; transform: rotate(-3deg); color: var(--mark); mix-blend-mode: multiply; }
.t-postal .pm svg { display: block; width: 100%; height: 100%; }
.t-postal .addr { position: absolute; left: 150px; right: 24px; top: 276px; z-index: 3; line-height: 1.5; }
.t-postal .addr .lab { position: absolute; right: 100%; margin-right: 14px; top: 7px; font-size: 15px; font-style: italic; opacity: .8; }
.t-postal .addr .to { font-size: 25px; line-height: 1.2; text-wrap: balance; }
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
      const rng = rngFor(ed);
      const li = (w, wCls, text, note, tag) => `<div class="li" data-role="body"><span class="w tw${wCls ? " " + wCls : ""}">${esc(w)}</span><span>${esc(text)}${note ? ` <span class="nt">— ${esc(note)}</span>` : ""}${tag ? `<span class="tg tw">${esc(tag)}</span>` : ""}</span></div>`;
      const blocks = [];
      if (needs.length) blocks.push(`<div class="blk"><h3 class="blabel red">Waiting on your reply</h3>${needs.map((d) => li(d.verb, "verb", d.label, d.note)).join("")}</div>`);
      if (c.today.length) blocks.push(`<div class="blk"><h3 class="blabel">Your day</h3>${c.today.map((e) => li(e.time || "EOD", "", e.label, e.note)).join("")}</div>`);
      if (c.overnight.length) blocks.push(`<div class="blk"><h3 class="blabel">Done while you slept</h3>${c.overnight.map((e) => li(clock(e.t24), "", e.label, e.note)).join("")}</div>`);
      if (c.running.length) blocks.push(`<div class="blk"><h3 class="blabel">Still in progress</h3>${c.running.map((e) => li(clock(e.t24), "", e.label, e.note)).join("")}</div>`);
      const s = c.stats;
      const ps = s ? `<p class="ps" data-role="body"><span class="w tw">P.S.</span><span>Yesterday we closed <b>${s.done}</b> things${s.you && s.gaia ? ` (you ${s.you}, me ${s.gaia})` : ""}${s.mail ? ` and handled <b>${s.mail}</b> emails` : ""}.${s.focus ? ` You have <b>${esc(s.focus)}</b> of focus ahead.` : ""}</span></p>` : "";
      return `<article class="t-postal" style="--env:${skin.paper.env}; --envInk:${skin.paper.ink}; --tint:${skin.paper.tint}; --mark:${skin.ink.mark}; --defin:${skin.ink.defin}; --ribbon:${skin.ink.ribbon}">
<div class="env">${paper(rng)}<div class="face tw">
  <div class="ret"><img src="${ed.assets.TEC_MARK}" alt="The Experience Company"><span>GAIA Post<br>The Experience Company</span></div>
  ${definitive(rng)}
  <img class="stamp" src="${ed.assets[city.key]}" alt="${esc(city.label)} stamp">
  <div class="pm">${postmark(ed, city, rng)}</div>
  ${etiquette(city, rng)}
  <div class="addr"><div class="lab">To</div><div class="to">${ed.recipient ? esc(ed.recipient.name) : "You"}</div><div class="re">Re: your ${esc(ed.weekday)}</div><div class="meta">Edition No. ${ed.editionNo} · ${ed.day} ${esc(ed.month)} ${ed.year}</div><div class="under"></div></div>
</div></div>
<div class="letter" data-fold>${grain("pa-l", 0.9)}
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
