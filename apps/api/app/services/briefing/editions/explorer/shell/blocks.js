/* The plumbing every edition draws its blocks with (ours, not vendored; ported from the
   founder-reviewed gallery's v2.js and reading.js): the reading system's item anatomy, app marks
   and crisp SVG plots. It decides nothing about where a block goes or how it looks: each family
   frames every block in its own idiom, sets the --rs-* tokens and passes its own faces and inks.

   Item anatomy: an ask opens with its verb, a done item with its outcome (the muted ink, never an
   imperative); then the app's mark, the title, at most one detail. A label column exists only
   where every row has one (calendar times). */
EXPLORER.blocks = (() => {
  const esc = (s) =>
    String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  // Whole numbers print bare, the rest to one decimal, as explorer_blocks.py prints values.
  const fmt = (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1));

  /* An app's mark: "ink" paints its alpha in currentColor, "color" shows it as shipped. A mono mark
     (one colour by brand rule) always prints in ink. */
  function logo(key, { mode = "ink", cls = "rs-logo" } = {}) {
    if (!key) return "";
    const m = EXPLORER.logoKinds[key] === "mono" ? "ink" : mode;
    return `<i class="xb-logo xb-${m} ${cls}" data-logo="${esc(key)}" role="img" aria-hidden="true"></i>`;
  }

  function opener(it) {
    return it.outcome
      ? `<span class="rs-verb rs-outcome">${esc(it.outcome)}</span>`
      : `<span class="rs-verb">${esc(it.verb)}</span>`;
  }

  const detail = (text) => (text ? `<div class="rs-detail">${esc(text)}</div>` : "");
  const more = (n) => (n > 0 ? `<div class="rs-more">+${n} more in the full brief</div>` : "");

  /* One item row. o.mode is the family's logo mode. */
  function item(it, o = {}) {
    const kind = it.outcome ? `data-outcome="${esc(it.outcome)}"` : `data-action="${esc(it.verb)}"`;
    return `<div class="rs-item" role="listitem" data-role="body" data-app="${esc(it.logo || "gaia")}" ${kind}><div class="rs-title">${opener(it)} ${logo(it.logo, o)}${esc(it.title)}</div>${detail(it.detail)}</div>`;
  }

  const list = (rows, labelled = false) => `<div class="rs-list${labelled ? " rs-labelled" : ""}" role="list">${rows.join("")}</div>`;

  /* A calendar row's label is what it is anchored to in time: its day, its start on the family's
     clock (o.clock "t12" | "t24"), or o.allDay. */
  const eventLabel = (e, o) => e.day || e[o.clock || "t24"] || o.allDay || "All day";

  function events(cal, o = {}) {
    const rows = cal.events.map(
      (e) =>
        `<div class="rs-item" role="listitem" data-role="body" data-app="${esc(e.logo)}" data-action="attend"><span class="rs-verb rs-label">${esc(eventLabel(e, o))}</span><div class="rs-body"><div class="rs-title">${logo(e.logo, o)}${esc(e.title)}</div>${detail(e.detail)}</div></div>`,
    );
    return list(rows, true) + more(cal.more);
  }

  /* A group of items under its one label, the heading. extra goes between heading and rows. */
  function section(heading, body, { key = "", extra = "" } = {}) {
    return `<div class="rs-sec" role="group" data-rs="${esc(key)}"><div class="rs-h" role="heading" aria-level="3">${esc(heading)}</div>${extra}${body}</div>`;
  }

  const items = (b, o = {}) => list(b.items.map((it) => item(it, o))) + more(b.more);

  /* The lead, one size up: the family's kicker, verb and title, the detail, then GAIA's offer. */
  function lead(b, o = {}) {
    const it = b.item;
    const kick = o.kicker ? `<div class="rs-kick">${esc(o.kicker)}</div>` : "";
    return `<div class="rs-lead" data-role="body" data-app="${esc(it.logo || "gaia")}" data-action="${esc(it.verb)}">${kick}<div class="rs-title rs-lead-title">${opener(it)} ${logo(it.logo, o)}${esc(it.title)}</div>${detail(it.detail)}${b.offer ? `<div class="rs-offer">${esc(b.offer)}</div>` : ""}</div>`;
  }

  /* Draw ed.blocks in reading order with the family's renderer for each kind. */
  const layout = (ed, R) => ed.blocks.map((b) => R[b.kind](b)).filter(Boolean);

  /* Plots. Every plot is an SVG whose user units are CSS px (viewBox == width x height), so text
     and strokes land on the export's device pixels. The family supplies its own font, sizes and
     inks; titles, takeaways, units, ranges and legends are the family's HTML. */
  const svg = (w, h, inner, cls = "") =>
    `<svg class="xb-plot ${cls}" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-hidden="true">${inner}</svg>`;
  const txt = (x, y, s, st, anchor = "middle", extra = "") =>
    `<text x="${x}" y="${y}" text-anchor="${anchor}" font-family="${esc(st.font)}" font-size="${st.size}" font-weight="${st.weight || 400}" fill="${st.fill}" letter-spacing="${st.track || 0}" ${extra}>${esc(s)}</text>`;
  // Snap a CSS length to the device pixel grid so every edge lands on whole device pixels.
  const DPR = window.devicePixelRatio || 1;
  const snap = (v) => Math.round(v * DPR) / DPR;
  const rect = (x, y, w, h, fill, extra = "") =>
    `<rect x="${snap(x)}" y="${snap(y)}" width="${snap(Math.max(w, 0))}" height="${snap(Math.max(h, 0))}" fill="${fill}" shape-rendering="crispEdges" ${extra}/>`;
  const up = (st, s) => (st.upper ? String(s).toUpperCase() : s);

  // 0 to the first round step above max, in three or four steps of 1, 2, 2.5 or 5 x 10^n
  // (2.5 keeps a peak of 61 on a 0-75 axis instead of 0-100).
  function niceTicks(max) {
    if (max <= 0) return [0, 1];
    const raw = max / 3;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
    const out = [];
    for (let t = 0; t < max + step; t += step) out.push(+t.toFixed(6));
    return out;
  }

  const totals = (chart) => chart.x.map((_, i) => chart.series.reduce((a, s) => a + s.values[i], 0));

  /* Vertical bars, one per x, its series stacked bottom-up (a plain bar is one series). Each bar
     prints its total above it, its x label below. st: {w, h, font, size, ink, soft, rule,
     fills:[...per series], gapRatio, upper, valueWeight, baseline, ruleW, labels:"full"|"initial"} */
  function bars(chart, st) {
    const n = chart.x.length;
    const sums = totals(chart);
    const max = Math.max(...sums, 1e-9);
    const top = Math.ceil(st.size * 1.5);
    const bottom = Math.ceil(st.size * 1.7);
    const plotH = st.h - top - bottom;
    const slot = st.w / n;
    const bw = slot * (1 - (st.gapRatio ?? 0.38));
    let out = "";
    chart.x.forEach((lab, i) => {
      const x = i * slot + (slot - bw) / 2;
      let y = top + plotH;
      chart.series.forEach((s, k) => {
        const h = (s.values[i] / max) * plotH;
        out += rect(x, y - h, bw, h, st.fills[k % st.fills.length]);
        y -= h;
      });
      out += txt(x + bw / 2, y - st.size * 0.45, fmt(sums[i]), { ...st, fill: st.ink, weight: st.valueWeight || st.weight });
      const label = st.labels === "initial" ? lab.slice(0, 1) : lab;
      out += txt(x + bw / 2, top + plotH + st.size * 1.35, up(st, label), { ...st, fill: st.soft });
    });
    if (st.baseline !== false) out += rect(0, top + plotH, st.w, st.ruleW || 1, st.rule);
    return svg(st.w, st.h, out, "xb-bars");
  }

  /* Lines over shared x, on value gridlines that carry their values; each line's last point is
     marked and labelled. st: {w, h, font, size, ink, soft, rule, base, lines:[{color, width, dash}],
     dot, upper, gutter, right, valueWeight, ruleW} */
  function line(chart, st) {
    const n = chart.x.length;
    const all = chart.series.flatMap((s) => s.values);
    const ticks = niceTicks(Math.max(...all));
    const lo = ticks[0];
    const hi = ticks[ticks.length - 1];
    const gutter = st.gutter ?? Math.ceil(st.size * 1.9);
    const top = Math.ceil(st.size * 1.2);
    const bottom = Math.ceil(st.size * 1.9);
    const right = st.right ?? Math.ceil(st.size * 1.6);
    const pw = st.w - gutter - right;
    const ph = st.h - top - bottom;
    const X = (i) => gutter + (n === 1 ? pw / 2 : (i / (n - 1)) * pw);
    const Y = (v) => top + ph - ((v - lo) / (hi - lo)) * ph;
    let out = "";
    for (const tk of ticks) {
      const y = Y(tk);
      out += rect(gutter, y, pw, st.ruleW || 1, tk === lo ? st.base || st.rule : st.rule);
      out += txt(gutter - st.size * 0.5, y + st.size * 0.35, fmt(tk), { ...st, fill: st.soft }, "end");
    }
    chart.series.forEach((s, k) => {
      const ln = st.lines[k % st.lines.length];
      const d = s.values.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(2)} ${Y(v).toFixed(2)}`).join(" ");
      const dash = ln.dash ? ` stroke-dasharray="${ln.dash}"` : "";
      out += `<path d="${d}" fill="none" stroke="${ln.color}" stroke-width="${ln.width || 2}" stroke-linejoin="round" stroke-linecap="round"${dash}/>`;
      const li = n - 1;
      out += `<circle cx="${X(li).toFixed(2)}" cy="${Y(s.values[li]).toFixed(2)}" r="${st.dot || 3.5}" fill="${ln.color}"/>`;
      out += txt(X(li), Y(s.values[li]) - st.size * 0.75, s.shown[li], { ...st, fill: st.ink, weight: st.valueWeight || st.weight });
    });
    const marks = n <= 8 ? chart.x.map((_, i) => i) : [0, Math.floor((n - 1) / 2), n - 1];
    for (const i of marks) {
      const edge = n > 8 && (i === 0 || i === n - 1);
      const anchor = edge ? (i === 0 ? "start" : "end") : "middle";
      const x = edge ? X(i) + (i === 0 ? -2 : 2) : X(i);
      out += rect(X(i), top + ph, 1, 4, st.base || st.rule);
      out += txt(x, st.h - st.size * 0.3, up(st, chart.x[i]), { ...st, fill: st.soft }, anchor);
    }
    return svg(st.w, st.h, out, "xb-line");
  }

  /* A spark: one series, no grid; its first and last values labelled at the ends, its peak marked.
     st: {w, h, font, size, ink, soft, line, lineW, dot} */
  function spark(chart, st) {
    const s = chart.series[0];
    const v = s.values;
    const n = v.length;
    const lo = Math.min(...v);
    const hi = Math.max(...v);
    const pad = st.size * 0.6;
    const lw = st.labelW ?? Math.ceil(st.size * 2.4);
    const pw = st.w - 2 * lw;
    const X = (i) => lw + (i / (n - 1)) * pw;
    const Y = (y) => pad + (st.h - 2 * pad) * (hi === lo ? 0.5 : 1 - (y - lo) / (hi - lo));
    const d = v.map((y, i) => `${i ? "L" : "M"}${X(i).toFixed(2)} ${Y(y).toFixed(2)}`).join(" ");
    let out = `<path d="${d}" fill="none" stroke="${st.line}" stroke-width="${st.lineW || 2}" stroke-linejoin="round" stroke-linecap="round"/>`;
    out += `<circle cx="${X(n - 1).toFixed(2)}" cy="${Y(v[n - 1]).toFixed(2)}" r="${st.dot || 3}" fill="${st.line}"/>`;
    out += txt(lw - st.size * 0.4, Y(v[0]) + st.size * 0.35, s.shown[0], { ...st, fill: st.soft }, "end");
    out += txt(X(n - 1) + st.size * 0.5, Y(v[n - 1]) + st.size * 0.35, s.shown[n - 1], { ...st, fill: st.ink, weight: st.valueWeight || st.weight }, "start");
    return svg(st.w, st.h, out, "xb-spark");
  }

  /* Discrete progress: one cell per unit of the goal, filled up to what is done. Past maxCells the
     goal is one bar filled in proportion. st: {w, h, gap, on, off, offStroke, maxCells} */
  function cells(p, st) {
    const n = p.total;
    if (n > (st.maxCells ?? 12)) {
      const w = (p.done / n) * st.w;
      const off = st.offStroke
        ? `<rect x="0.5" y="0.5" width="${st.w - 1}" height="${st.h - 1}" fill="none" stroke="${st.offStroke}" stroke-width="1" shape-rendering="crispEdges"/>`
        : rect(0, 0, st.w, st.h, st.off);
      return svg(st.w, st.h, off + rect(0, 0, w, st.h, st.on), "xb-cells");
    }
    const gap = st.gap ?? 4;
    const cw = (st.w - gap * (n - 1)) / n;
    let out = "";
    for (let i = 0; i < n; i++) {
      const x = i * (cw + gap);
      out += i < p.done
        ? rect(x, 0, cw, st.h, st.on)
        : st.offStroke
          ? `<rect x="${(x + 0.5).toFixed(2)}" y="0.5" width="${(cw - 1).toFixed(2)}" height="${st.h - 1}" fill="none" stroke="${st.offStroke}" stroke-width="1" shape-rendering="crispEdges"/>`
          : rect(x, 0, cw, st.h, st.off);
    }
    return svg(st.w, st.h, out, "xb-cells");
  }

  /* The chart drawn by its kind; a family that plots its own form for a kind overrides it. */
  const plot = (chart, st) => ({ bar: bars, stacked_bar: bars, line, spark })[chart.chart](chart, st);

  /* What a chart's legend says: each series' name and total, with the family's swatch. */
  const legend = (chart, swatch) => chart.series.map((s, k) => `${swatch(k)}${esc(s.name)} ${esc(s.total)}`);

  /* The facts line under a chart's title: its range and unit, as "Mon 3 – Sun 9 Nov · tasks". */
  const facts = (chart, sep = " · ") => [chart.range, chart.unit].filter(Boolean).join(sep);

  return { esc, fmt, snap, logo, item, items, events, section, lead, list, more, detail, layout, plot, bars, line, spark, cells, legend, facts, svg, txt, rect, niceTicks, totals };
})();
