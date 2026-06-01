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
//   • No external image/asset files — all graphics are pptxgenjs shapes/charts/tables.
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

const FONT = { face: "Segoe UI", heading: "Segoe UI Semibold" };

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
    fontSize: 26, bold: true, color: COLOR.brand, fontFace: FONT.heading, align: "left", valign: "middle",
  });
};

// A header cell for tables: bold white text on a brand fill.
const th = (text) => ({ text, options: { bold: true, color: COLOR.white, fill: { color: COLOR.brand }, align: "left" } });

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
  x: 0.85, y: 2.95, w: 11.5, h: 1.8, fontSize: 46, bold: true, color: COLOR.white, fontFace: FONT.heading, lineSpacingMultiple: 1.02,
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
  s.addText(String(i + 1), { x: PAGE.margin, y, w: 0.62, h: 0.62, fontSize: 22, bold: true, color: COLOR.white, align: "center", valign: "middle", fontFace: FONT.heading });
  s.addText(item, { x: 1.45, y, w: 10.5, h: 0.62, fontSize: 20, color: COLOR.ink, valign: "middle", fontFace: FONT.face });
});

// ===========================================================================
// SLIDE 3 — SECTION DIVIDER (full-bleed color)
// Big section number + label; signals a new part of the deck.
// ===========================================================================
s = pptx.addSlide();
s.background = { color: COLOR.brand };
s.addText("01", { x: 0.85, y: 2.0, w: 4, h: 2, fontSize: 120, bold: true, color: COLOR.accent, fontFace: FONT.heading });
s.addText("Performance", { x: 0.9, y: 4.1, w: 11, h: 1, fontSize: 44, bold: true, color: COLOR.white, fontFace: FONT.heading });
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
  s.addText(heading, { x: x + 0.1, y: 1.75, w: cw - 0.2, h: 0.85, fontSize: 20, bold: true, color: COLOR.white, align: "center", valign: "middle", fontFace: FONT.heading });
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
  s.addText(k.value, { x: x + 0.15, y: 2.7, w: kpiW - 0.3, h: 1.0, fontSize: 40, bold: true, color: COLOR.brand, align: "center", valign: "middle", fontFace: FONT.heading });
  s.addText(k.label, { x: x + 0.15, y: 3.75, w: kpiW - 0.3, h: 0.5, fontSize: 13, color: COLOR.body, align: "center", fontFace: FONT.face });
  s.addText(k.delta, { x: x + 0.15, y: 4.35, w: kpiW - 0.3, h: 0.5, fontSize: 14, bold: true, color: k.up ? COLOR.ok : COLOR.bad, align: "center", fontFace: FONT.face });
});

// ===========================================================================
// SLIDE 7 — NATIVE BAR CHART
// Multi-series clustered bars. `barDir: "col"` makes vertical columns.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "Revenue by Region", "Section 01");
s.addChart(
  pptx.ChartType.bar,
  [
    { name: "Q2 2026", labels: ["NA", "EMEA", "APAC", "LATAM"], values: [0.52, 0.34, 0.21, 0.13] },
    { name: "Q3 2026", labels: ["NA", "EMEA", "APAC", "LATAM"], values: [0.63, 0.41, 0.29, 0.17] },
  ],
  {
    x: PAGE.margin, y: 1.7, w: CONTENT_W, h: 5.0,
    barDir: "col",
    barGapWidthPct: 50,
    chartColors: [COLOR.faint, COLOR.brand],
    showLegend: true, legendPos: "t", legendColor: COLOR.body, legendFontSize: 12,
    showTitle: false,
    showValue: true, dataLabelColor: COLOR.ink, dataLabelFontSize: 9, dataLabelFormatCode: "$0.00\\M",
    catAxisLabelColor: COLOR.body, catAxisLabelFontSize: 12,
    valAxisLabelColor: COLOR.faint, valAxisLabelFontSize: 10, valAxisLabelFormatCode: "$0.0\\M",
    valGridLine: { color: COLOR.line, style: "solid", size: 0.5 },
    catGridLine: { style: "none" },
  },
);

// ===========================================================================
// SLIDE 8 — NATIVE PIE + LINE (two charts on one slide)
// Left: revenue mix (pie with % labels). Right: trailing user growth (line).
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "Mix & Trajectory", "Section 01");
s.addText("Revenue mix by plan", { x: PAGE.margin, y: 1.6, w: 5.9, h: 0.4, fontSize: 14, bold: true, color: COLOR.body, fontFace: FONT.face });
s.addChart(
  pptx.ChartType.pie,
  [{ name: "Revenue mix", labels: ["Enterprise", "Pro", "Team", "Free→paid"], values: [48, 27, 18, 7] }],
  {
    x: PAGE.margin, y: 2.0, w: 5.9, h: 4.6,
    chartColors: [COLOR.brand, COLOR.accent, COLOR.ok, COLOR.faint],
    showLegend: true, legendPos: "b", legendColor: COLOR.body, legendFontSize: 11,
    showValue: false, showPercent: true, dataLabelColor: COLOR.white, dataLabelFontSize: 11, dataLabelPosition: "ctr",
  },
);
s.addText("Active users (trailing 6 mo, k)", { x: 6.95, y: 1.6, w: 5.78, h: 0.4, fontSize: 14, bold: true, color: COLOR.body, fontFace: FONT.face });
s.addChart(
  pptx.ChartType.line,
  [{ name: "Active users", labels: ["Apr", "May", "Jun", "Jul", "Aug", "Sep"], values: [13.4, 14.1, 14.8, 16.0, 17.1, 18.2] }],
  {
    x: 6.95, y: 2.0, w: 5.78, h: 4.6,
    chartColors: [COLOR.brand],
    lineSize: 3, lineSmooth: true,
    showLegend: false, showTitle: false,
    catAxisLabelColor: COLOR.body, catAxisLabelFontSize: 11,
    valAxisLabelColor: COLOR.faint, valAxisLabelFontSize: 10,
    valGridLine: { color: COLOR.line, style: "solid", size: 0.5 },
    lineDataSymbol: "circle", lineDataSymbolSize: 6,
  },
);

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
  s.addText(st.t, { x, y: stY, w: stW, h: 0.7, fontSize: 18, bold: true, color: COLOR.white, align: "center", valign: "middle", fontFace: FONT.heading });
  s.addText(st.d, { x: x + 0.15, y: stY + 0.85, w: stW - 0.3, h: 1.0, fontSize: 13, color: COLOR.body, align: "center", valign: "middle", fontFace: FONT.face });
  s.addText(`Week ${i * 3 + 1}–${i * 3 + 3}`, { x, y: stY + 1.6, w: stW, h: 0.35, fontSize: 11, italic: true, color: COLOR.faint, align: "center", fontFace: FONT.face });
});

// ===========================================================================
// SLIDE 11 — QUOTE (large centered text on tinted backdrop)
// ===========================================================================
s = pptx.addSlide();
s.background = { color: COLOR.panel };
s.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: 0.22, h: PAGE.h, fill: { color: COLOR.accent } });
s.addText("“", { x: 0.7, y: 1.4, w: 3, h: 2, fontSize: 140, bold: true, color: COLOR.line, fontFace: FONT.heading });
s.addText("We didn't just grow the numbers — we grew the trust behind them.", {
  x: 1.6, y: 2.5, w: 10.2, h: 2.2, fontSize: 32, bold: true, italic: true, color: COLOR.ink, align: "center", valign: "middle", fontFace: FONT.heading, lineSpacingMultiple: 1.1,
});
s.addText("— Jordan Lee, VP of Product", { x: 1.6, y: 4.9, w: 10.2, h: 0.5, fontSize: 16, color: COLOR.brand, align: "center", fontFace: FONT.face });

// ===========================================================================
// SLIDE 12 — CLOSING / CONTACT (full-bleed dark, mirrors the title slide)
// ===========================================================================
s = pptx.addSlide();
s.background = { color: COLOR.brandDark };
s.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: PAGE.w, h: 0.9, fill: { color: COLOR.brand } });
s.addShape(pptx.ShapeType.rect, { x: 0, y: 6.6, w: PAGE.w, h: 0.9, fill: { color: COLOR.accent } });
s.addText("Thank you.", { x: 0.9, y: 2.5, w: 11.5, h: 1.2, fontSize: 54, bold: true, color: COLOR.white, fontFace: FONT.heading });
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
