// DECK TEMPLATE (pptxgenjs) — adapt the content arrays, keep the layout grid.
// Run via: bash scripts/build.sh deck.mjs out.pptx
import pptxgen from "pptxgenjs";

const BRAND = "1A4D8F";
const GRAY = "555555";

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE"; // 13.33in x 7.5in
pptx.author = "GAIA";

// Reusable slide-title helper
const addTitle = (slide, text) =>
  slide.addText(text, { x: 0.6, y: 0.4, w: 12.1, h: 0.9, fontSize: 28, bold: true, color: BRAND });

// 1) Title slide
let s = pptx.addSlide();
s.background = { color: BRAND };
s.addText("Quarterly Business Review", { x: 0.8, y: 2.7, w: 11.7, h: 1.2, fontSize: 40, bold: true, color: "FFFFFF" });
s.addText("Q3 2026 · Prepared by GAIA", { x: 0.8, y: 3.9, w: 11.7, h: 0.6, fontSize: 18, color: "DDE6F2" });

// 2) Agenda
s = pptx.addSlide();
addTitle(s, "Agenda");
s.addText(
  ["Highlights", "Performance", "Key metrics", "Recommendations", "Next steps"].map((t) => ({ text: t, options: { bullet: true } })),
  { x: 0.8, y: 1.6, w: 11.5, h: 5, fontSize: 22, color: "333333", lineSpacingMultiple: 1.4 }
);

// 3) Content (bullets)
s = pptx.addSlide();
addTitle(s, "Highlights");
s.addText(
  [
    { text: "Revenue grew 25% quarter over quarter", options: { bullet: true } },
    { text: "Active users up to 18.2k", options: { bullet: true } },
    { text: "Churn down to 2.4%", options: { bullet: true } },
    { text: "Shipped 3 major features", options: { bullet: true } },
  ],
  { x: 0.8, y: 1.6, w: 11.5, h: 5, fontSize: 20, color: "333333", lineSpacingMultiple: 1.4 }
);

// 4) Table
s = pptx.addSlide();
addTitle(s, "Key Metrics");
const headerCell = (t) => ({ text: t, options: { bold: true, color: "FFFFFF", fill: { color: BRAND } } });
s.addTable(
  [
    [headerCell("Metric"), headerCell("Q1"), headerCell("Q2"), headerCell("Q3")],
    ["Revenue", "$1.0M", "$1.2M", "$1.5M"],
    ["Active users", "12.1k", "14.8k", "18.2k"],
    ["Churn", "3.2%", "2.9%", "2.4%"],
  ],
  { x: 0.8, y: 1.7, w: 11.5, fontSize: 16, border: { pt: 0.5, color: "CCCCCC" }, align: "left" }
);

// 5) Chart
s = pptx.addSlide();
addTitle(s, "Revenue Trend");
s.addChart(
  pptx.ChartType.bar,
  [{ name: "Revenue ($M)", labels: ["Q1", "Q2", "Q3"], values: [1.0, 1.2, 1.5] }],
  { x: 0.8, y: 1.6, w: 11.5, h: 5, showLegend: true, legendPos: "b", chartColors: [BRAND] }
);

// 6) Closing
s = pptx.addSlide();
s.background = { color: BRAND };
s.addText("Thank you", { x: 0.8, y: 3.0, w: 11.7, h: 1.2, fontSize: 40, bold: true, color: "FFFFFF" });
s.addText("Questions? gaia@example.com", { x: 0.8, y: 4.2, w: 11.7, h: 0.6, fontSize: 18, color: "DDE6F2" });

const out = process.argv[2] || "out.pptx";
await pptx.writeFile({ fileName: out });
