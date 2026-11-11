/* The reading system's rules, measured on a rendered edition (ported from the founder-reviewed
   gallery's tools/reading_check.py). Evaluated in the page with the brief's expectations; returns
   every broken rule as a sentence. */
(expect) => {
  const art = document.querySelector("#root > article");
  const R = (e) => e.getBoundingClientRect();
  const lh = (e) => parseFloat(getComputedStyle(e).lineHeight);
  const fails = [];
  const short = (e) => e.textContent.trim().replace(/\s+/g, " ").slice(0, 40);

  // Ink, not boxes: a text element counts by its glyph lines (padding is space, not content).
  const inkRect = (e) => {
    const texts = [...e.childNodes].filter((n) => n.nodeType === 3 && n.textContent.trim());
    if (!texts.length) return R(e);
    const rg = document.createRange();
    const rs = texts
      .flatMap((n) => {
        rg.selectNodeContents(n);
        return [...rg.getClientRects()];
      })
      .filter((r) => r.width > 0);
    if (!rs.length) return R(e);
    return {
      left: Math.min(...rs.map((r) => r.left)),
      right: Math.max(...rs.map((r) => r.right)),
      top: Math.min(...rs.map((r) => r.top)),
      bottom: Math.max(...rs.map((r) => r.bottom)),
    };
  };
  const isVisible = (e) => {
    const s = getComputedStyle(e);
    const r = R(e);
    return r.width >= 1 && r.height >= 1 && s.visibility !== "hidden" && +s.opacity !== 0;
  };
  const ownText = (e) => [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());

  // Content outside the reading blocks: text, pictures and charts; an ornament (textless svg) is not.
  const leaves = [...art.querySelectorAll("*")]
    .filter((e) => !e.closest(".rs-sec, .rs-lead") && isVisible(e))
    .filter((e) => ownText(e) || ["IMG", "CANVAS"].includes(e.tagName) || (e.tagName === "svg" && e.textContent.trim()))
    .map((e) => inkRect(e));

  // The item gap as the eye sees it: ink to ink between neighbouring items, the widest on the page.
  let gapItem = 0;
  for (const list of art.querySelectorAll(".rs-list")) {
    const its = [...list.children];
    for (let i = 1; i < its.length; i++) {
      const prev = [...its[i - 1].children].map(inkRect);
      const next = inkRect(its[i].querySelector(".rs-title"));
      gapItem = Math.max(gapItem, next.top - Math.max(...prev.map((r) => r.bottom)));
    }
  }

  // Item anatomy: the verb or outcome is the first glyph, set apart from the title; titles hold to 2 lines.
  for (const it of art.querySelectorAll(".rs-item, .rs-lead")) {
    const t = it.querySelector(".rs-title");
    const v = it.querySelector(".rs-verb");
    const lines = Math.round(R(t).height / lh(t));
    if (lines > 2) fails.push(`title wraps ${lines} lines: ${short(t)}`);
    if (!v) {
      fails.push(`no verb or outcome: ${short(t)}`);
      continue;
    }
    const left = Math.min(...[...it.children].filter((c) => !c.matches(".rs-kick")).map((c) => R(c).left));
    if (!(Math.abs(R(v).left - left) < 2 && Math.abs(R(v).top - R(t).top) < lh(t))) fails.push(`verb not first: ${short(t)}`);
    const vs = getComputedStyle(v);
    const apart = vs.color !== getComputedStyle(t).color || vs.fontVariantCaps !== "normal" || vs.textTransform === "uppercase";
    if (!apart) fails.push(`verb not set apart from its title: ${short(t)}`);
  }

  // Sections stand at least twice the item gap clear of the content around them.
  const blocks = [...art.querySelectorAll(".rs-sec, .rs-lead")];
  const extent = (o) => {
    const c = [...o.querySelectorAll(".rs-kick, .rs-h, .rs-title, .rs-detail, .rs-more, .rs-offer")].map(inkRect);
    return { top: Math.min(...c.map((r) => r.top)), bottom: Math.max(...c.map((r) => r.bottom)), left: Math.min(...c.map((r) => r.left)), right: Math.max(...c.map((r) => r.right)) };
  };
  const min = Math.ceil(2 * gapItem);
  for (const s of blocks) {
    const box = extent(s);
    const xs = (r) => r.right > box.left + 2 && r.left < box.right - 2;
    const others = blocks.filter((o) => o !== s && !o.contains(s) && !s.contains(o)).map(extent);
    const above = [...leaves.filter((r) => xs(r) && r.bottom <= box.top + 1), ...others.filter((o) => o.bottom <= box.top + 1)].map((r) => r.bottom);
    const below = [...leaves.filter((r) => xs(r) && r.top >= box.bottom - 1), ...others.filter((o) => o.top >= box.bottom - 1)].map((r) => r.top);
    const name = s.dataset.rs || (s.matches(".rs-lead") ? "lead" : "section");
    if (above.length && box.top - Math.max(...above) < min) fails.push(`${name}: ${Math.round(box.top - Math.max(...above))}px above, under 2x the ${Math.round(gapItem)}px item gap`);
    if (below.length && Math.min(...below) - box.bottom < min) fails.push(`${name}: ${Math.round(Math.min(...below) - box.bottom)}px below, under 2x the ${Math.round(gapItem)}px item gap`);
  }

  // Rows: no empty cell taking width (a label column with no label), labels only in a label column.
  const isRowBox = (p) => p.matches(".rs-item") || [...p.children].some((c) => c.matches(".rs-body, .rs-title"));
  for (const e of art.querySelectorAll(".rs-item *, .rs-item")) {
    const p = e.parentElement;
    if (!/grid|flex/.test(getComputedStyle(p).display) || !isRowBox(p)) continue;
    const st = getComputedStyle(e);
    if (R(e).width < 16 || e.textContent.trim() || e.querySelector("img, svg, canvas, .xb-logo") || e.matches("img, svg, canvas, .xb-logo")) continue;
    if (st.backgroundImage !== "none" || st.backgroundColor !== "rgba(0, 0, 0, 0)" || parseFloat(st.borderTopWidth) || parseFloat(st.borderLeftWidth)) continue;
    fails.push(`empty label cell ${Math.round(R(e).width)}px: ${short(p)}`);
  }
  for (const l of art.querySelectorAll(".rs-label")) if (!l.closest(".rs-labelled")) fails.push(`label outside a label column: ${short(l)}`);
  for (const list of art.querySelectorAll(".rs-labelled")) {
    for (const it of list.children) {
      const l = it.querySelector(":scope > .rs-label");
      if (!l || !l.textContent.trim()) fails.push(`unlabelled row in a label column: ${short(it)}`);
    }
  }

  // Logos: an app item shows its mark after the verb, on the title's cap band; GAIA's items none.
  const cv = document.createElement("canvas").getContext("2d");
  let logos = 0;
  for (const it of art.querySelectorAll(".rs-item, .rs-lead")) {
    const app = it.dataset.app;
    const lg = it.querySelector(".rs-logo");
    const t = it.querySelector(".rs-title");
    if (!app || app === "gaia") {
      if (lg) fails.push(`GAIA item shows a logo: ${short(t)}`);
      continue;
    }
    if (!lg) {
      fails.push(`no ${app} logo: ${short(t)}`);
      continue;
    }
    const lr = R(lg);
    const ls = getComputedStyle(lg);
    const painted = ls.backgroundImage !== "none" || (ls.maskImage && ls.maskImage !== "none") || (ls.webkitMaskImage && ls.webkitMaskImage !== "none");
    if (lr.width < 4 || !painted) {
      fails.push(`${app} logo not painted: ${short(t)}`);
      continue;
    }
    const v = t.querySelector(":scope > .rs-verb");
    if (v && lr.left < R(v).right) fails.push(`${app} logo before its verb: ${short(t)}`);
    const ts = getComputedStyle(t);
    cv.font = `${ts.fontStyle} ${ts.fontWeight} ${ts.fontSize} ${ts.fontFamily}`;
    const cap = cv.measureText("H").actualBoundingBoxAscent;
    const probe = document.createElement("span");
    probe.style.cssText = "display:inline-block;width:0;height:0;vertical-align:baseline";
    lg.after(probe);
    const base = R(probe).bottom;
    probe.remove();
    const off = (lr.top + lr.bottom) / 2 - (base - cap / 2);
    if (Math.abs(off) > 1.5) fails.push(`${app} logo ${off.toFixed(1)}px off the cap band: ${short(t)}`);
    logos++;
  }

  // Done items say what happened: never an action, never an imperative first word.
  for (const it of art.querySelectorAll(".rs-item[data-outcome]")) {
    const word = it.querySelector(".rs-title").textContent.trim().split(/\s+/)[0].toLowerCase();
    if (expect.imperatives.includes(word)) fails.push(`done item opens with an imperative: ${short(it)}`);
  }

  // Type: at most two families (Aeonik, GAIA's brand face, aside; marks and plots are pictures),
  // one family per row and its "+N more", one label per section, a heading that outranks its titles.
  const fam = (e) => getComputedStyle(e).fontFamily.split(",")[0].trim().replace(/^['"]|['"]$/g, "");
  const texty = (e) => !e.closest("svg, .xb-logo") && ownText(e) && R(e).width > 0;
  const families = new Set([art, ...art.querySelectorAll("*")].filter(texty).map(fam).filter((f) => !/^Aeonik/.test(f)));
  if (families.size > 2) fails.push(`${families.size} type families: ${[...families].join(", ")}`);
  // Bold is a real cut, never synthesised: a 600+ weight needs a loaded 600+ face of its family.
  const cuts = [...document.fonts].filter((f) => f.status === "loaded");
  for (const e of art.querySelectorAll(".rs-sec *, .rs-lead *")) {
    if (!texty(e)) continue;
    const cs = getComputedStyle(e);
    const f = fam(e);
    const italic = cs.fontStyle !== "normal" ? "italic" : "normal";
    const own = cuts.filter((c) => c.family.replace(/["']/g, "") === f && c.style === italic);
    if (+cs.fontWeight >= 600 && own.length && !own.some((c) => +c.weight >= 600)) fails.push(`synthesised bold in ${f}: ${short(e)}`);
  }
  for (const s of art.querySelectorAll(".rs-sec")) {
    const name = s.dataset.rs || "section";
    for (const row of s.querySelectorAll(".rs-item")) {
      const fs = new Set([row, ...row.querySelectorAll("*")].filter(texty).map(fam));
      if (fs.size > 1) fails.push(`${name}: a row in ${fs.size} families (${[...fs].join(", ")}): ${short(row)}`);
    }
    const more = s.querySelector(".rs-more");
    const first = s.querySelector(".rs-title");
    if (more && first && fam(more) !== fam(first)) fails.push(`${name}: "+N more" in ${fam(more)}, rows in ${fam(first)}`);
    const list = s.querySelector(".rs-list");
    if (!list) continue;
    const kids = [...s.children];
    const labels = kids.slice(0, kids.indexOf(list)).filter((e) => e.textContent.trim() && !e.matches("svg, img, canvas") && !e.querySelector("svg, img, canvas"));
    if (labels.length !== 1 || !labels[0].matches(".rs-h")) fails.push(`${name}: ${labels.length} labels over the rows (${labels.map(short).join(" / ")})`);
    const h = s.querySelector(".rs-h");
    const hs = getComputedStyle(h);
    const hz = parseFloat(hs.fontSize);
    const hw = +hs.fontWeight;
    for (const t of s.querySelectorAll(".rs-title")) {
      const ts = getComputedStyle(t);
      const tz = parseFloat(ts.fontSize);
      const tw = +ts.fontWeight;
      if (!((hz > tz && hw >= tw) || (hz === tz && hw > tw))) {
        fails.push(`${name}: heading ${hz}px/${hw} does not outrank title ${tz}px/${tw}`);
        break;
      }
    }
    // Layout px, not screen boxes: a tilted paper (memo, boarding pass) skews bounding rects.
    const gap = Math.round(h.nextElementSibling.offsetTop - h.offsetTop - h.offsetHeight);
    if (gap < 12 || gap % 4) fails.push(`${name}: heading-to-row gap ${gap}px (want 12 or more, on 4px)`);
  }

  // Every composed block the family draws is on the page with the facts it must carry.
  const text = (e) => e.innerText.replace(/\s+/g, " ").toLowerCase();
  const has = (e, s) => text(e).includes(String(s).replace(/\s+/g, " ").toLowerCase());
  const byKind = (k) => [...art.querySelectorAll(`[data-block="${k}"]`)];
  for (const [kind, want] of Object.entries(expect.counts)) {
    const got = byKind(kind).length;
    if (got !== want) fails.push(`${want} ${kind} block(s) composed, ${got} drawn`);
  }
  expect.charts.forEach((c, i) => {
    const el = byKind("chart")[i];
    if (!el) return;
    // Plotted marks, and the points' labels on the page (in the plot or in the family's rows).
    const marks = el.querySelectorAll("svg rect, svg path, svg circle, svg line, svg polyline").length;
    if (!marks) fails.push(`chart "${c.title}" plots nothing`);
    const all = el.textContent.replace(/\s+/g, " ").toLowerCase();
    for (const x of [c.x[0], c.x[c.x.length - 1]]) if (!all.includes(x.toLowerCase())) fails.push(`chart "${c.title}" does not label "${x}"`);
    for (const fact of [c.title, c.takeaway, c.range, c.unit].filter(Boolean)) if (!has(el, fact)) fails.push(`chart "${c.title}" does not print "${fact}"`);
    if (c.legend.length > 1) for (const name of c.legend) if (!has(el, name)) fails.push(`chart "${c.title}" has no legend entry "${name}"`);
  });
  expect.quotes.forEach((q, i) => {
    const el = byKind("quote")[i];
    if (el) for (const fact of [q.text, q.author, q.app]) if (!has(el, fact)) fails.push(`quote does not print "${fact}"`);
  });
  expect.progress.forEach((p, i) => {
    const el = byKind("progress")[i];
    if (!el) return;
    if (!has(el, p.statement)) fails.push(`progress does not print its goal "${p.statement}"`);
    // A number may be spelled, as a menu or a playbill spells it.
    for (const n of [p.done, p.total]) if (!n.some((w) => new RegExp(`\\b${w}\\b`, "i").test(text(el)))) fails.push(`progress does not print ${n[0]}`);
  });
  expect.notes.forEach((n, i) => {
    const el = byKind("note")[i];
    if (el && !has(el, n)) fails.push(`note does not print its text`);
  });
  return { fails, gapItem: Math.round(gapItem), logos, families: [...families] };
};
