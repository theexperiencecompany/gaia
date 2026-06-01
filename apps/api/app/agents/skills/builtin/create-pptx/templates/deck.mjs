// DECK TEMPLATE (pptxgenjs, ESM) — benchmark-quality reference deck.
//
// Doubles as few-shot material for an LLM: every slide demonstrates a distinct
// pptxgenjs feature with heavy inline commentary. Adapt the CONTENT arrays and
// the PALETTE consts; keep the layout grid and the contract below intact.
//
// CONTRACT
//   • Run:  node deck.mjs out.pptx   (with `pptxgenjs` resolvable)
//   • Writes to process.argv[2] (fallback "out.pptx") via `await pptx.writeFile`.
//   • LAYOUT_WIDE → 13.33in × 7.5in. Keep every element inside those bounds.
//   • No external image/asset files — all graphics are pptxgenjs shapes/text/tables.
//
// CHARTS ARE DRAWN, NOT EMBEDDED. We deliberately avoid pptxgen's native
// `addChart(...)`: Apple viewers (Keynote / Quick Look) do NOT render the
// embedded OOXML chart parts, so those slides come up blank. Every chart here
// is composed from primitive shapes (rect / line / ellipse) plus `addText`
// labels, with all geometry computed in JS from a data array. These render
// identically in PowerPoint, Keynote, Google Slides, and LibreOffice.
import pptxgen from "pptxgenjs";

// ---------------------------------------------------------------------------
// PALETTE & TYPE TOKENS — single source of truth for branding.
// Colors are 6-digit hex strings WITHOUT a leading "#", as pptxgenjs expects.
// ---------------------------------------------------------------------------
const COLOR = {
  brand: "1A4D8F", // primary blue
  brandDark: "0E2E57", // darker blue for dividers / title backdrop
  accent: "F2A93B", // warm amber accent
  ok: "2E9E5B", // positive / up
  bad: "C0392B", // negative / down
  ink: "1F2933", // near-black body text
  body: "475569", // muted body text
  faint: "94A3B8", // captions / footer
  line: "D8DEE9", // hairline borders
  panel: "F4F6FA", // light card fill
  white: "FFFFFF",
};

// Slide geometry (inches) for the widescreen layout.
const PAGE = { w: 13.33, h: 7.5, margin: 0.6 };
const CONTENT_W = PAGE.w - PAGE.margin * 2; // 12.13in usable width

// Cross-platform font. "Arial" exists on macOS, Windows, and Google Slides, so
// no "missing fonts" warning appears in any viewer. Bold weights are requested
// via `bold: true` rather than a separate semibold face (e.g. "Segoe UI
// Semibold"), which does not exist on macOS.
const FONT = { face: "Arial" };

// ---------------------------------------------------------------------------
// PRESENTATION SETUP
// ---------------------------------------------------------------------------
const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "GAIA";
pptx.company = "GAIA";
pptx.subject = "Quarterly Business Review";
pptx.title = "QBR Q3 2026";

// ---------------------------------------------------------------------------
// SLIDE MASTER — consistent branding (footer bar + slide number placeholder).
// Slides built with { masterName: "BRAND" } inherit these static objects.
// `slideNumber` renders the running number; we keep the title as a per-slide
// element (helper below) for full control over wrapping/positioning.
// ---------------------------------------------------------------------------
const MASTER = "BRAND";
pptx.defineSlideMaster({
  title: MASTER,
  background: { color: COLOR.white },
  objects: [
    // thin brand rule under the header region
    { line: { x: PAGE.margin, y: 1.32, w: CONTENT_W, h: 0, line: { color: COLOR.line, width: 1 } } },
    // footer rule + label
    { line: { x: PAGE.margin, y: 7.02, w: CONTENT_W, h: 0, line: { color: COLOR.line, width: 0.75 } } },
    {
      text: {
        text: "GAIA · Quarterly Business Review · Q3 2026",
        options: { x: PAGE.margin, y: 7.06, w: 8.5, h: 0.32, fontSize: 9, color: COLOR.faint, fontFace: FONT.face, align: "left", valign: "middle" },
      },
    },
  ],
  // running slide number, bottom-right corner
  slideNumber: { x: 12.3, y: 7.06, w: 0.6, h: 0.32, fontSize: 9, color: COLOR.faint, fontFace: FONT.face, align: "right" },
});

// ---------------------------------------------------------------------------
// HELPERS — small, composable builders so each slide reads declaratively.
// ---------------------------------------------------------------------------

// Standard slide title + optional kicker (eyebrow) used on every content slide.
const addHeader = (slide, title, kicker) => {
  if (kicker) {
    slide.addText(kicker.toUpperCase(), {
      x: PAGE.margin, y: 0.42, w: CONTENT_W, h: 0.3,
      fontSize: 11, bold: true, color: COLOR.accent, charSpacing: 2, fontFace: FONT.face,
    });
  }
  slide.addText(title, {
    x: PAGE.margin, y: kicker ? 0.68 : 0.5, w: CONTENT_W, h: 0.7,
    fontSize: 26, bold: true, color: COLOR.brand, fontFace: FONT.face, align: "left", valign: "middle",
  });
};

// A header cell for tables: bold white text on a brand fill.
const th = (text) => ({ text, options: { bold: true, color: COLOR.white, fill: { color: COLOR.brand }, align: "left" } });

// Linearly map a data value to a pixel/inch length within a chart's plot area.
// Returns the length (in inches) that `value` represents on an axis of `axisLen`
// inches whose scale runs 0 → `maxValue`.
const scaleLen = (value, maxValue, axisLen) => (value / maxValue) * axisLen;

// ===========================================================================
// SLIDE 1 — BRANDED TITLE
// Full-bleed dark backdrop with layered accent shapes; no master (custom look).
// ===========================================================================
let s = pptx.addSlide();
s.background = { color: COLOR.brandDark };
// large translucent accent bar bottom-left for visual depth
s.addShape(pptx.ShapeType.rect, { x: 0, y: 6.6, w: PAGE.w, h: 0.9, fill: { color: COLOR.brand } });
s.addShape(pptx.ShapeType.rect, { x: 0, y: 2.55, w: 0.18, h: 2.6, fill: { color: COLOR.accent } });
s.addText("QUARTERLY BUSINESS REVIEW", {
  x: 0.9, y: 2.5, w: 11.5, h: 0.4, fontSize: 14, bold: true, color: COLOR.accent, charSpacing: 3, fontFace: FONT.face,
});
s.addText("Growth, Efficiency &\nThe Road to Q4", {
  x: 0.85, y: 2.95, w: 11.5, h: 1.8, fontSize: 46, bold: true, color: COLOR.white, fontFace: FONT.face, lineSpacingMultiple: 1.02,
});
s.addText(
  [
    { text: "Q3 2026", options: { bold: true, color: COLOR.white } },
    { text: "   ·   Prepared by GAIA   ·   Confidential", options: { color: "B9C6DC" } },
  ],
  { x: 0.9, y: 5.0, w: 11.5, h: 0.5, fontSize: 16, fontFace: FONT.face },
);

// ===========================================================================
// SLIDE 2 — AGENDA
// Numbered list rendered as paired shapes (number chip) + label rows.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "Agenda", "What we'll cover");
const agenda = ["Executive highlights", "Performance vs. plan", "Key metrics & KPIs", "Competitive comparison", "Roadmap & next steps"];
agenda.forEach((item, i) => {
  const y = 1.7 + i * 0.95;
  s.addShape(pptx.ShapeType.roundRect, { x: PAGE.margin, y, w: 0.62, h: 0.62, rectRadius: 0.1, fill: { color: COLOR.brand } });
  s.addText(String(i + 1), { x: PAGE.margin, y, w: 0.62, h: 0.62, fontSize: 22, bold: true, color: COLOR.white, align: "center", valign: "middle", fontFace: FONT.face });
  s.addText(item, { x: 1.45, y, w: 10.5, h: 0.62, fontSize: 20, color: COLOR.ink, valign: "middle", fontFace: FONT.face });
});

// ===========================================================================
// SLIDE 3 — SECTION DIVIDER (full-bleed color)
// Big section number + label; signals a new part of the deck.
// ===========================================================================
s = pptx.addSlide();
s.background = { color: COLOR.brand };
s.addText("01", { x: 0.85, y: 2.0, w: 4, h: 2, fontSize: 120, bold: true, color: COLOR.accent, fontFace: FONT.face });
s.addText("Performance", { x: 0.9, y: 4.1, w: 11, h: 1, fontSize: 44, bold: true, color: COLOR.white, fontFace: FONT.face });
s.addText("How the quarter landed against the plan we set in Q2.", { x: 0.95, y: 5.05, w: 10, h: 0.6, fontSize: 18, color: "D6E0F0", fontFace: FONT.face });

// ===========================================================================
// SLIDE 4 — BULLET CONTENT (multi-level bullets via indentLevel)
// Each run is an object; `indentLevel` nests it, `bullet` styles the marker.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "Executive Highlights", "Section 01");
s.addText(
  [
    { text: "Revenue beat plan for the third straight quarter", options: { bullet: { code: "2022" }, bold: true, color: COLOR.ink } },
    { text: "$1.5M total — 25% QoQ growth", options: { bullet: true, indentLevel: 1, color: COLOR.body } },
    { text: "Net revenue retention held above 110%", options: { bullet: true, indentLevel: 1, color: COLOR.body } },
    { text: "Activation and retention both improved", options: { bullet: { code: "2022" }, bold: true, color: COLOR.ink } },
    { text: "Active users climbed to 18.2k (+23%)", options: { bullet: true, indentLevel: 1, color: COLOR.body } },
    { text: "Monthly churn fell to 2.4% from 3.2%", options: { bullet: true, indentLevel: 1, color: COLOR.body } },
    { text: "Shipped three major features ahead of schedule", options: { bullet: { code: "2022" }, bold: true, color: COLOR.ink } },
    { text: "Collaboration mode, audit log, and SSO", options: { bullet: true, indentLevel: 1, color: COLOR.body } },
  ],
  { x: PAGE.margin, y: 1.7, w: CONTENT_W, h: 5.0, fontSize: 18, fontFace: FONT.face, lineSpacingMultiple: 1.25, paraSpaceAfter: 6 },
);

// ===========================================================================
// SLIDE 5 — TWO-COLUMN COMPARISON (two shape "cards" side by side)
// Each card = a roundRect panel + a header band + a bulleted body.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "Build vs. Buy", "Decision");
const card = (x, headColor, heading, points) => {
  const cw = 5.75;
  // panel
  s.addShape(pptx.ShapeType.roundRect, { x, y: 1.75, w: cw, h: 4.9, rectRadius: 0.12, fill: { color: COLOR.panel }, line: { color: COLOR.line, width: 1 } });
  // header band
  s.addShape(pptx.ShapeType.roundRect, { x, y: 1.75, w: cw, h: 0.85, rectRadius: 0.12, fill: { color: headColor } });
  s.addText(heading, { x: x + 0.1, y: 1.75, w: cw - 0.2, h: 0.85, fontSize: 20, bold: true, color: COLOR.white, align: "center", valign: "middle", fontFace: FONT.face });
  // body bullets
  s.addText(
    points.map((p) => ({ text: p.t, options: { bullet: { code: p.ok ? "2713" : "2717" }, color: p.ok ? COLOR.ink : COLOR.bad } })),
    { x: x + 0.35, y: 2.85, w: cw - 0.7, h: 3.6, fontSize: 15, fontFace: FONT.face, lineSpacingMultiple: 1.3, valign: "top", paraSpaceAfter: 8 },
  );
};
card(PAGE.margin, COLOR.brand, "Build in-house", [
  { t: "Full control over roadmap", ok: true },
  { t: "No per-seat vendor fees", ok: true },
  { t: "6–9 months to parity", ok: false },
  { t: "Ongoing maintenance burden", ok: false },
]);
card(PAGE.margin + 5.78 + 0.22, COLOR.accent, "Buy a vendor", [
  { t: "Live in under 30 days", ok: true },
  { t: "Vendor-managed reliability", ok: true },
  { t: "Recurring license cost", ok: false },
  { t: "Limited customization", ok: false },
]);

// ===========================================================================
// SLIDE 6 — KPI / METRICS (3-4 stat cards via roundRect + text)
// Each card stacks: big value, label, and a colored delta line.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "Key Metrics", "At a glance");
const kpis = [
  { value: "$1.5M", label: "Quarterly revenue", delta: "+25% QoQ", up: true },
  { value: "18.2k", label: "Active users", delta: "+23% QoQ", up: true },
  { value: "2.4%", label: "Monthly churn", delta: "-0.8 pts", up: true },
  { value: "73", label: "Net promoter score", delta: "+6 pts", up: true },
];
const kpiW = 2.85;
const kpiGap = (CONTENT_W - kpiW * kpis.length) / (kpis.length - 1);
kpis.forEach((k, i) => {
  const x = PAGE.margin + i * (kpiW + kpiGap);
  s.addShape(pptx.ShapeType.roundRect, { x, y: 2.3, w: kpiW, h: 2.9, rectRadius: 0.14, fill: { color: COLOR.panel }, line: { color: COLOR.line, width: 1 } });
  s.addShape(pptx.ShapeType.rect, { x, y: 2.3, w: kpiW, h: 0.12, fill: { color: COLOR.brand } });
  s.addText(k.value, { x: x + 0.15, y: 2.7, w: kpiW - 0.3, h: 1.0, fontSize: 40, bold: true, color: COLOR.brand, align: "center", valign: "middle", fontFace: FONT.face });
  s.addText(k.label, { x: x + 0.15, y: 3.75, w: kpiW - 0.3, h: 0.5, fontSize: 13, color: COLOR.body, align: "center", fontFace: FONT.face });
  s.addText(k.delta, { x: x + 0.15, y: 4.35, w: kpiW - 0.3, h: 0.5, fontSize: 14, bold: true, color: k.up ? COLOR.ok : COLOR.bad, align: "center", fontFace: FONT.face });
});

// ===========================================================================
// SLIDE 7 — BAR CHART, DRAWN FROM SHAPES (renders in every viewer)
// Clustered vertical columns built entirely from `rect` shapes. We compute
// each bar's height and x-offset in JS from the data array, draw the axes as
// `line` shapes, place gridlines + axis tick labels, and put a value label
// above every bar. No addChart — so Keynote/Quick Look show the full chart.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "Revenue by Region", "Section 01");

// --- chart data: two series, clustered per category ($ millions) ---
const barCats = ["NA", "EMEA", "APAC", "LATAM"];
const barSeries = [
  { name: "Q2 2026", color: COLOR.faint, values: [0.52, 0.34, 0.21, 0.13] },
  { name: "Q3 2026", color: COLOR.brand, values: [0.63, 0.41, 0.29, 0.17] },
];

// --- plot-area geometry (the rectangle the bars live inside) ---
const plot = { x: PAGE.margin + 0.7, y: 2.0, w: CONTENT_W - 0.7, h: 4.2 };
const axisMax = 0.7; // round number above the largest value (0.63)
const yTicks = [0, 0.175, 0.35, 0.525, 0.7]; // 5 gridlines

// horizontal gridlines + left-side value-axis labels
yTicks.forEach((t) => {
  const gy = plot.y + plot.h - scaleLen(t, axisMax, plot.h);
  s.addShape(pptx.ShapeType.line, { x: plot.x, y: gy, w: plot.w, h: 0, line: { color: COLOR.line, width: 0.75 } });
  s.addText(`$${t.toFixed(2)}M`, { x: PAGE.margin - 0.05, y: gy - 0.13, w: 0.7, h: 0.26, fontSize: 9, color: COLOR.faint, align: "right", valign: "middle", fontFace: FONT.face });
});
// solid baseline (value = 0) drawn last so it sits on top of the gridlines
s.addShape(pptx.ShapeType.line, { x: plot.x, y: plot.y + plot.h, w: plot.w, h: 0, line: { color: COLOR.body, width: 1.25 } });

// per-category column group; two bars (one per series) sit inside each group
const groupW = plot.w / barCats.length;
const barW = 0.7; // single bar width
const innerGap = 0.12; // gap between the two clustered bars
barCats.forEach((cat, ci) => {
  const groupCenter = plot.x + groupW * ci + groupW / 2;
  const clusterW = barW * barSeries.length + innerGap;
  const clusterLeft = groupCenter - clusterW / 2;
  barSeries.forEach((series, si) => {
    const v = series.values[ci];
    const barH = scaleLen(v, axisMax, plot.h);
    const bx = clusterLeft + si * (barW + innerGap);
    const by = plot.y + plot.h - barH;
    s.addShape(pptx.ShapeType.rect, { x: bx, y: by, w: barW, h: barH, fill: { color: series.color } });
    // value label sitting just above each bar
    s.addText(`$${v.toFixed(2)}M`, { x: bx - 0.15, y: by - 0.3, w: barW + 0.3, h: 0.26, fontSize: 9, bold: true, color: COLOR.ink, align: "center", fontFace: FONT.face });
  });
  // category (x-axis) label below the baseline
  s.addText(cat, { x: groupCenter - groupW / 2, y: plot.y + plot.h + 0.08, w: groupW, h: 0.3, fontSize: 12, color: COLOR.body, align: "center", fontFace: FONT.face });
});

// hand-built legend (swatch + label per series) along the top of the plot
let legendX = plot.x;
const legendY = 1.62;
barSeries.forEach((series) => {
  s.addShape(pptx.ShapeType.rect, { x: legendX, y: legendY, w: 0.26, h: 0.18, fill: { color: series.color } });
  s.addText(series.name, { x: legendX + 0.33, y: legendY - 0.07, w: 1.6, h: 0.32, fontSize: 11, color: COLOR.body, valign: "middle", fontFace: FONT.face });
  legendX += 1.9;
});

// ===========================================================================
// SLIDE 8 — TREND LINE + 100% STACKED BAR, DRAWN FROM SHAPES
// Left: a horizontal 100%-stacked revenue-mix bar made of colored `rect`
// segments + a legend (deliberately NOT a pie — pies don't render in Apple
// viewers and are hard to label cleanly). Right: a line chart built from `line`
// segments between consecutive points + `ellipse` markers + value labels.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "Mix & Trajectory", "Section 01");

// ---------- LEFT: 100% horizontal stacked bar (revenue mix) ----------
s.addText("Revenue mix by plan", { x: PAGE.margin, y: 1.6, w: 5.9, h: 0.4, fontSize: 14, bold: true, color: COLOR.body, fontFace: FONT.face });
const mix = [
  { label: "Enterprise", pct: 48, color: COLOR.brand },
  { label: "Pro", pct: 27, color: COLOR.accent },
  { label: "Team", pct: 18, color: COLOR.ok },
  { label: "Free→paid", pct: 7, color: COLOR.faint },
];
const stackX = PAGE.margin;
const stackY = 2.25;
const stackW = 5.9;
const stackH = 0.95;
// draw each segment left-to-right, width proportional to its share of 100%
let segX = stackX;
mix.forEach((seg) => {
  const segW = (seg.pct / 100) * stackW;
  s.addShape(pptx.ShapeType.rect, { x: segX, y: stackY, w: segW, h: stackH, fill: { color: seg.color } });
  // in-segment percentage label (only when the segment is wide enough to fit)
  if (segW > 0.7) {
    s.addText(`${seg.pct}%`, { x: segX, y: stackY, w: segW, h: stackH, fontSize: 13, bold: true, color: COLOR.white, align: "center", valign: "middle", fontFace: FONT.face });
  }
  segX += segW;
});
// legend beneath the stacked bar — one swatch + label + share per plan
mix.forEach((seg, i) => {
  const ly = stackY + stackH + 0.45 + i * 0.55;
  s.addShape(pptx.ShapeType.rect, { x: stackX, y: ly, w: 0.3, h: 0.3, fill: { color: seg.color } });
  s.addText(
    [
      { text: `${seg.label}  `, options: { bold: true, color: COLOR.ink } },
      { text: `${seg.pct}%`, options: { color: COLOR.body } },
    ],
    { x: stackX + 0.45, y: ly - 0.04, w: 5.0, h: 0.38, fontSize: 14, valign: "middle", fontFace: FONT.face },
  );
});

// ---------- RIGHT: line chart from line segments + ellipse markers ----------
s.addText("Active users (trailing 6 mo, k)", { x: 6.95, y: 1.6, w: 5.78, h: 0.4, fontSize: 14, bold: true, color: COLOR.body, fontFace: FONT.face });
const lineLabels = ["Apr", "May", "Jun", "Jul", "Aug", "Sep"];
const lineValues = [13.4, 14.1, 14.8, 16.0, 17.1, 18.2];
const lplot = { x: 7.35, y: 2.2, w: 5.35, h: 3.9 };
const lMin = 12; // floor below the smallest value so the line isn't flat at the bottom
const lMax = 19; // ceiling above the largest value
const lTicks = [12, 14, 16, 18];

// gridlines + value-axis labels
lTicks.forEach((t) => {
  const gy = lplot.y + lplot.h - scaleLen(t - lMin, lMax - lMin, lplot.h);
  s.addShape(pptx.ShapeType.line, { x: lplot.x, y: gy, w: lplot.w, h: 0, line: { color: COLOR.line, width: 0.75 } });
  s.addText(String(t), { x: 6.95, y: gy - 0.13, w: 0.34, h: 0.26, fontSize: 9, color: COLOR.faint, align: "right", valign: "middle", fontFace: FONT.face });
});

// convert each data point to an (x, y) coordinate inside the plot area
const stepX = lplot.w / (lineValues.length - 1);
const pts = lineValues.map((v, i) => ({
  x: lplot.x + i * stepX,
  y: lplot.y + lplot.h - scaleLen(v - lMin, lMax - lMin, lplot.h),
}));

// connect consecutive points with `line` shapes (pptxgen draws a line from the
// box's top-left to its bottom-right corner, so w/h are the run/rise and may be
// negative — flipH/flipV handle the sign)
for (let i = 0; i < pts.length - 1; i++) {
  const a = pts[i];
  const b = pts[i + 1];
  s.addShape(pptx.ShapeType.line, {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    w: Math.abs(b.x - a.x),
    h: Math.abs(b.y - a.y),
    line: { color: COLOR.brand, width: 2.5 },
    flipH: b.x < a.x,
    flipV: b.y < a.y,
  });
}
// circular markers + value labels at each point, drawn on top of the line
const markerR = 0.09;
pts.forEach((p, i) => {
  s.addShape(pptx.ShapeType.ellipse, { x: p.x - markerR, y: p.y - markerR, w: markerR * 2, h: markerR * 2, fill: { color: COLOR.white }, line: { color: COLOR.brand, width: 2 } });
  s.addText(lineValues[i].toFixed(1), { x: p.x - 0.4, y: p.y - 0.42, w: 0.8, h: 0.26, fontSize: 9, bold: true, color: COLOR.ink, align: "center", fontFace: FONT.face });
  // month (x-axis) label below the baseline
  s.addText(lineLabels[i], { x: p.x - 0.4, y: lplot.y + lplot.h + 0.08, w: 0.8, h: 0.28, fontSize: 11, color: COLOR.body, align: "center", fontFace: FONT.face });
});
// baseline drawn last
s.addShape(pptx.ShapeType.line, { x: lplot.x, y: lplot.y + lplot.h, w: lplot.w, h: 0, line: { color: COLOR.body, width: 1.25 } });

// ===========================================================================
// SLIDE 9 — TABLE (header styling + borders + per-cell color)
// First row uses `th()` chips; the delta column is colored per sign.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "Quarter-over-Quarter Detail", "Numbers");
const num = (t, color) => ({ text: t, options: { align: "right", color: color || COLOR.ink } });
const rows = [
  [th("Metric"), { ...th("Q1"), options: { ...th("Q1").options, align: "right" } }, { ...th("Q2"), options: { ...th("Q2").options, align: "right" } }, { ...th("Q3"), options: { ...th("Q3").options, align: "right" } }, { ...th("QoQ Δ"), options: { ...th("QoQ Δ").options, align: "right" } }],
  ["Revenue", num("$1.0M"), num("$1.2M"), num("$1.5M"), num("+25%", COLOR.ok)],
  ["Active users", num("12.1k"), num("14.8k"), num("18.2k"), num("+23%", COLOR.ok)],
  ["Gross margin", num("71%"), num("73%"), num("76%"), num("+3 pts", COLOR.ok)],
  ["Monthly churn", num("3.6%"), num("3.2%"), num("2.4%"), num("-0.8 pts", COLOR.ok)],
  ["CAC payback", num("14 mo"), num("12 mo"), num("11 mo"), num("-1 mo", COLOR.ok)],
];
s.addTable(rows, {
  x: PAGE.margin, y: 1.75, w: CONTENT_W,
  colW: [4.13, 2, 2, 2, 2],
  rowH: 0.62,
  fontSize: 15, fontFace: FONT.face, color: COLOR.ink, valign: "middle",
  border: { type: "solid", pt: 0.5, color: COLOR.line },
  align: "left",
  fill: { color: COLOR.white },
  // zebra striping for body rows via alternating row fills is handled by
  // pptxgenjs when you set `fill` per-row; here we keep it clean with borders.
});

// ===========================================================================
// SLIDE 10 — PROCESS / TIMELINE (shapes + connector arrows)
// Four stage chips connected by right-pointing arrow shapes.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "Q4 Execution Plan", "Roadmap");
const stages = [
  { t: "Discovery", d: "Customer interviews", c: COLOR.brand },
  { t: "Build", d: "Ship core feature set", c: COLOR.accent },
  { t: "Beta", d: "10 design partners", c: COLOR.ok },
  { t: "GA", d: "Public launch", c: COLOR.brandDark },
];
const stW = 2.55;
const stGap = 0.62;
const stY = 3.0;
stages.forEach((st, i) => {
  const x = PAGE.margin + i * (stW + stGap);
  // connector arrow between stage i-1 and i
  if (i > 0) {
    s.addShape(pptx.ShapeType.rightArrow, { x: x - stGap - 0.04, y: stY + 0.78, w: stGap + 0.08, h: 0.4, fill: { color: COLOR.faint } });
  }
  s.addShape(pptx.ShapeType.roundRect, { x, y: stY, w: stW, h: 2.0, rectRadius: 0.12, fill: { color: COLOR.white }, line: { color: st.c, width: 1.5 } });
  s.addShape(pptx.ShapeType.roundRect, { x, y: stY, w: stW, h: 0.7, rectRadius: 0.12, fill: { color: st.c } });
  s.addText(st.t, { x, y: stY, w: stW, h: 0.7, fontSize: 18, bold: true, color: COLOR.white, align: "center", valign: "middle", fontFace: FONT.face });
  s.addText(st.d, { x: x + 0.15, y: stY + 0.85, w: stW - 0.3, h: 1.0, fontSize: 13, color: COLOR.body, align: "center", valign: "middle", fontFace: FONT.face });
  s.addText(`Week ${i * 3 + 1}–${i * 3 + 3}`, { x, y: stY + 1.6, w: stW, h: 0.35, fontSize: 11, italic: true, color: COLOR.faint, align: "center", fontFace: FONT.face });
});

// ===========================================================================
// SLIDE 11 — QUOTE (large centered text on tinted backdrop)
// ===========================================================================
s = pptx.addSlide();
s.background = { color: COLOR.panel };
s.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: 0.22, h: PAGE.h, fill: { color: COLOR.accent } });
s.addText("“", { x: 0.7, y: 1.4, w: 3, h: 2, fontSize: 140, bold: true, color: COLOR.line, fontFace: FONT.face });
s.addText("We didn't just grow the numbers — we grew the trust behind them.", {
  x: 1.6, y: 2.5, w: 10.2, h: 2.2, fontSize: 32, bold: true, italic: true, color: COLOR.ink, align: "center", valign: "middle", fontFace: FONT.face, lineSpacingMultiple: 1.1,
});
s.addText("— Jordan Lee, VP of Product", { x: 1.6, y: 4.9, w: 10.2, h: 0.5, fontSize: 16, color: COLOR.brand, align: "center", fontFace: FONT.face });

// ===========================================================================
// SLIDE 12 — CLOSING / CONTACT (full-bleed dark, mirrors the title slide)
// ===========================================================================
s = pptx.addSlide();
s.background = { color: COLOR.brandDark };
s.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: PAGE.w, h: 0.9, fill: { color: COLOR.brand } });
s.addShape(pptx.ShapeType.rect, { x: 0, y: 6.6, w: PAGE.w, h: 0.9, fill: { color: COLOR.accent } });
s.addText("Thank you.", { x: 0.9, y: 2.5, w: 11.5, h: 1.2, fontSize: 54, bold: true, color: COLOR.white, fontFace: FONT.face });
s.addText("Questions, data requests, or a walkthrough — reach out any time.", { x: 0.95, y: 3.8, w: 11.5, h: 0.6, fontSize: 18, color: "C7D3E8", fontFace: FONT.face });
s.addText(
  [
    { text: "qbr@gaia.example", options: { bold: true, color: COLOR.white } },
    { text: "      gaia.example/reports      @gaia", options: { color: "9FB2D4" } },
  ],
  { x: 0.95, y: 4.7, w: 11.5, h: 0.5, fontSize: 16, fontFace: FONT.face },
);

// ---------------------------------------------------------------------------
// WRITE — the only side effect. Path comes from argv[2] (build.sh passes it).
// ---------------------------------------------------------------------------
const out = process.argv[2] || "out.pptx";
await pptx.writeFile({ fileName: out });
