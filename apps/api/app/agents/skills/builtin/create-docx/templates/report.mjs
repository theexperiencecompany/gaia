// REPORT TEMPLATE (docx-js) — comprehensive, multi-section .docx report.
//
// This file is a benchmark-quality reference for building rich Word documents
// with the `docx` npm package (ESM). It is heavily commented so an LLM can
// learn each feature by example, then adapt the values/content for a real task.
//
// Run via: bash scripts/build.sh report.mjs out.docx
// Contract: build a `Document`, then write it to process.argv[2] (fallback
// "out.docx"). Do NOT reference external image/asset files — none exist.

import {
  Document,
  Packer,
  Paragraph,
  TextRun,
  HeadingLevel,
  AlignmentType,
  PageBreak,
  Table,
  TableRow,
  TableCell,
  WidthType,
  BorderStyle,
  ShadingType,
  Header,
  Footer,
  PageNumber,
  TableOfContents,
  LevelFormat,
  convertInchesToTwip,
} from "docx";
import { writeFileSync } from "node:fs";

// ---------------------------------------------------------------------------
// Design tokens — single source of truth for colours/sizes used below.
// docx colours are 6-digit hex WITHOUT a leading "#". Font sizes are in
// half-points (so `size: 24` == 12pt). Spacing/indent values are in twips
// (1 inch = 1440 twips; convertInchesToTwip() does the math for you).
// ---------------------------------------------------------------------------
const COLORS = {
  brand: "2563EB", // primary blue (headings / accents)
  brandDark: "1E3A8A", // darker blue (cover title)
  ink: "1F2937", // near-black body text
  muted: "6B7280", // grey captions / footer
  headerFill: "1E3A8A", // table header row background
  zebra: "F3F4F6", // alternating table row background
  quoteBar: "2563EB", // block-quote left border
};

const FONT = "Calibri"; // a font that exists on virtually every system

// Numbering reference ids configured on the Document and attached to ordered
// paragraphs below. Bullets use the built-in `bullet` shortcut, but ORDERED
// (1. 2. 3.) lists must reference a numbering definition like these.
const NUM_STEPS = "ordered-steps"; // the "How it works" numbered list
const NUM_REFS = "references-list"; // the final References list

// ---------------------------------------------------------------------------
// Small paragraph helpers. Helpers keep the document body readable and avoid
// repeating the same option objects dozens of times (DRY).
// ---------------------------------------------------------------------------

// Justified body paragraph with comfortable line spacing and space-after.
const body = (children) =>
  new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    spacing: { after: 160, line: 276 }, // line: 276 ≈ 1.15x line height
    children: Array.isArray(children) ? children : [new TextRun(children)],
  });

// A plain text run on the body colour — the default for most prose.
const t = (text, opts = {}) => new TextRun({ text, color: COLORS.ink, ...opts });

// ---------------------------------------------------------------------------
// 1) STYLES — document-wide default + named paragraph styles.
// `default` sets base run/paragraph formatting and restyles the built-in
// heading styles so headings (and the TOC built from them) carry brand colour.
// ---------------------------------------------------------------------------
const styles = {
  default: {
    document: {
      run: { font: FONT, size: 22, color: COLORS.ink }, // 11pt body
      paragraph: { spacing: { line: 276 } },
    },
    heading1: {
      run: { font: FONT, size: 32, bold: true, color: COLORS.brand }, // 16pt
      paragraph: { spacing: { before: 320, after: 160 } },
    },
    heading2: {
      run: { font: FONT, size: 26, bold: true, color: COLORS.brandDark }, // 13pt
      paragraph: { spacing: { before: 240, after: 120 } },
    },
    heading3: {
      run: { font: FONT, size: 24, bold: true, color: COLORS.ink }, // 12pt
      paragraph: { spacing: { before: 200, after: 100 } },
    },
  },
  // A custom named style applied to captions under tables.
  paragraphStyles: [
    {
      id: "Caption",
      name: "Caption",
      basedOn: "Normal",
      next: "Normal",
      run: { font: FONT, size: 18, italics: true, color: COLORS.muted }, // 9pt
      paragraph: { spacing: { before: 80, after: 240 }, alignment: AlignmentType.CENTER },
    },
  ],
};

// ---------------------------------------------------------------------------
// 2) NUMBERING — declare ordered-list definitions. Each `reference` is a named
// list; `levels` define how each indent level renders. `%1` is the level-1
// counter. Two independent lists keep their counters from sharing state.
// (Bulleted lists use the `bullet` shortcut and need no config here.)
// ---------------------------------------------------------------------------
const numbering = {
  config: [
    {
      reference: NUM_STEPS,
      levels: [
        {
          level: 0,
          format: LevelFormat.DECIMAL, // 1. 2. 3.
          text: "%1.",
          alignment: AlignmentType.START,
          style: { paragraph: { indent: { left: convertInchesToTwip(0.5), hanging: convertInchesToTwip(0.25) } } },
        },
      ],
    },
    {
      reference: NUM_REFS,
      levels: [
        {
          level: 0,
          format: LevelFormat.DECIMAL,
          text: "[%1]", // [1] [2] [3] — citation style
          alignment: AlignmentType.START,
          style: { paragraph: { indent: { left: convertInchesToTwip(0.5), hanging: convertInchesToTwip(0.3) } } },
        },
      ],
    },
  ],
};

// ---------------------------------------------------------------------------
// 3) RUNNING HEADER + FOOTER — appear on every page of the section. The footer
// uses field codes: PageNumber.CURRENT and PageNumber.TOTAL_PAGES render live
// "Page X of Y" values that Word computes at open/print time.
// ---------------------------------------------------------------------------
const header = new Header({
  children: [
    new Paragraph({
      alignment: AlignmentType.RIGHT,
      // a thin bottom rule under the header text
      border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: COLORS.muted, space: 4 } },
      children: [new TextRun({ text: "GAIA — Quarterly Operations Report", size: 16, color: COLORS.muted })],
    }),
  ],
});

const footer = new Footer({
  children: [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      border: { top: { style: BorderStyle.SINGLE, size: 4, color: COLORS.muted, space: 4 } },
      children: [
        new TextRun({ text: "Confidential", size: 16, color: COLORS.muted }),
        new TextRun({ text: "    |    Page ", size: 16, color: COLORS.muted }),
        new TextRun({ children: [PageNumber.CURRENT], size: 16, color: COLORS.muted }),
        new TextRun({ text: " of ", size: 16, color: COLORS.muted }),
        new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: COLORS.muted }),
      ],
    }),
  ],
});

// ---------------------------------------------------------------------------
// 4) STYLED DATA TABLE — header row shaded with the brand colour, percentage
// column widths, full borders, and zebra-striped body rows for readability.
// ---------------------------------------------------------------------------
const cellBorder = { style: BorderStyle.SINGLE, size: 2, color: "D1D5DB" };
const allBorders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };

// A header cell: shaded background + white bold text, centered.
const headCell = (text, widthPct) =>
  new TableCell({
    width: { size: widthPct, type: WidthType.PERCENTAGE },
    shading: { type: ShadingType.CLEAR, fill: COLORS.headerFill, color: "auto" },
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text, bold: true, color: "FFFFFF", size: 20 })],
      }),
    ],
  });

// A body cell: optional zebra shading, optional right-alignment for numbers.
const dataCell = (text, { zebra = false, alignRight = false, bold = false } = {}) =>
  new TableCell({
    shading: zebra ? { type: ShadingType.CLEAR, fill: COLORS.zebra, color: "auto" } : undefined,
    margins: { top: 50, bottom: 50, left: 100, right: 100 },
    children: [
      new Paragraph({
        alignment: alignRight ? AlignmentType.RIGHT : AlignmentType.LEFT,
        children: [new TextRun({ text, size: 20, bold, color: COLORS.ink })],
      }),
    ],
  });

const metricsRows = [
  ["Active users", "42,180", "+12.4%", "On track"],
  ["Avg. session (min)", "8.7", "+0.9", "Above target"],
  ["Task completion", "91.3%", "+3.1pp", "On track"],
  ["Support tickets", "1,204", "-7.6%", "Improving"],
];

const dataTable = new Table({
  width: { size: 100, type: WidthType.PERCENTAGE },
  borders: allBorders,
  rows: [
    new TableRow({
      tableHeader: true, // repeat this row if the table breaks across pages
      children: [
        headCell("Metric", 40),
        headCell("Value", 20),
        headCell("Delta (QoQ)", 20),
        headCell("Status", 20),
      ],
    }),
    ...metricsRows.map(
      (row, i) =>
        new TableRow({
          children: [
            dataCell(row[0], { zebra: i % 2 === 1 }),
            dataCell(row[1], { zebra: i % 2 === 1, alignRight: true }),
            dataCell(row[2], { zebra: i % 2 === 1, alignRight: true }),
            dataCell(row[3], { zebra: i % 2 === 1 }),
          ],
        }),
    ),
  ],
});

// ---------------------------------------------------------------------------
// 5) LAYOUT / SUMMARY TABLE — a borderless two-column "key: value" grid used
// for metadata. Borders set to NONE so it reads as a clean layout block.
// ---------------------------------------------------------------------------
const noBorder = { style: BorderStyle.NONE, size: 0, color: "auto" };
const noBorders = {
  top: noBorder,
  bottom: noBorder,
  left: noBorder,
  right: noBorder,
  insideHorizontal: noBorder,
  insideVertical: noBorder,
};

const summaryRow = (label, value) =>
  new TableRow({
    children: [
      new TableCell({
        width: { size: 30, type: WidthType.PERCENTAGE },
        borders: noBorders,
        children: [new Paragraph({ children: [new TextRun({ text: label, bold: true, color: COLORS.muted, size: 20 })] })],
      }),
      new TableCell({
        width: { size: 70, type: WidthType.PERCENTAGE },
        borders: noBorders,
        children: [new Paragraph({ children: [new TextRun({ text: value, color: COLORS.ink, size: 20 })] })],
      }),
    ],
  });

const summaryTable = new Table({
  width: { size: 100, type: WidthType.PERCENTAGE },
  borders: noBorders,
  rows: [
    summaryRow("Report ID", "OPS-2026-Q1-0042"),
    summaryRow("Prepared by", "Operations Analytics Team"),
    summaryRow("Reviewed by", "Office of the COO"),
    summaryRow("Classification", "Confidential — Internal"),
  ],
});

// ---------------------------------------------------------------------------
// 6) BLOCK QUOTE — indented, italic, with an accent left border on the
// paragraph. Shows paragraph-level borders + indentation working together.
// ---------------------------------------------------------------------------
const blockQuote = new Paragraph({
  indent: { left: convertInchesToTwip(0.5), right: convertInchesToTwip(0.5) },
  spacing: { before: 160, after: 200 },
  border: { left: { style: BorderStyle.SINGLE, size: 24, color: COLORS.quoteBar, space: 12 } },
  children: [
    new TextRun({
      text: "“The quarter validated our thesis: small, compounding improvements to the onboarding flow move retention more than any single large feature.”",
      italics: true,
      color: COLORS.ink,
      size: 22,
    }),
  ],
});

// ---------------------------------------------------------------------------
// 7) COVER PAGE — large centered title, subtitle, author, date, generous
// vertical spacing, then a hard page break onto the TOC page.
// ---------------------------------------------------------------------------
const today = new Date().toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });

const cover = [
  new Paragraph({ spacing: { before: 2400 } }), // push the title down the page
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 200 },
    children: [new TextRun({ text: "Quarterly Operations Report", bold: true, size: 64, color: COLORS.brandDark })], // 32pt
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 600 },
    children: [new TextRun({ text: "Performance, Insights & Recommendations — Q1 2026", size: 28, color: COLORS.brand })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 60 },
    children: [new TextRun({ text: "Prepared by the Operations Analytics Team", size: 24, color: COLORS.ink })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: today, size: 22, color: COLORS.muted })],
  }),
  // A PageBreak inside a paragraph ends the cover page.
  new Paragraph({ children: [new PageBreak()] }),
];

// ---------------------------------------------------------------------------
// 8) TABLE OF CONTENTS — a real Word TOC field built from heading styles 1-3.
// Word shows an "Update Field" prompt on open; entries populate from the
// HEADING_1..3 paragraphs below. `hyperlink` makes entries clickable.
// ---------------------------------------------------------------------------
const toc = [
  new Paragraph({ heading: HeadingLevel.HEADING_1, text: "Contents" }),
  new TableOfContents("Table of Contents", {
    hyperlink: true,
    headingStyleRange: "1-3", // include H1..H3
  }),
  new Paragraph({ children: [new PageBreak()] }),
];

// ---------------------------------------------------------------------------
// 9) BODY — numbered sections via headings + the building blocks above.
// Heading text is plain so the TOC picks up clean labels.
// ---------------------------------------------------------------------------
const sectionBody = [
  // ----- 1. Executive Summary -----
  new Paragraph({ heading: HeadingLevel.HEADING_1, text: "1. Executive Summary" }),
  body([
    t("This report summarizes operational performance for the first quarter of 2026. Overall, the business "),
    t("exceeded", { bold: true }),
    t(" its retention targets while holding costs flat. Key metrics improved quarter over quarter, and the "),
    t("highest-leverage", { italics: true }),
    t(" opportunity remains onboarding. The following sections detail the data, methodology, and recommendations."),
  ]),
  summaryTable,
  new Paragraph({ style: "Caption", text: "Table 1 — Report metadata." }),

  // ----- 2. Key Metrics -----
  new Paragraph({ heading: HeadingLevel.HEADING_1, text: "2. Key Metrics" }),
  body(
    "The table below reports headline metrics with quarter-over-quarter deltas. Values are de-duplicated across sessions and reconciled against the billing system of record.",
  ),
  dataTable,
  new Paragraph({ style: "Caption", text: "Table 2 — Headline metrics, Q1 2026 (QoQ = quarter over quarter)." }),

  // ----- 2.1 Inline formatting showcase -----
  new Paragraph({ heading: HeadingLevel.HEADING_2, text: "2.1 Reading the figures" }),
  body([
    t("Text can be "),
    t("bold", { bold: true }),
    t(", "),
    t("italic", { italics: true }),
    t(", "),
    t("underlined", { underline: {} }),
    t(", "),
    t("brand-coloured", { color: COLORS.brand }),
    t(", or "),
    new TextRun({ text: "highlighted", highlight: "yellow", color: COLORS.ink }),
    t(". Footnote markers use superscript"),
    new TextRun({ text: "1", superScript: true, color: COLORS.ink }),
    t(" and unit notation can use subscript, e.g. CO"),
    new TextRun({ text: "2", subScript: true, color: COLORS.ink }),
    t(" emissions per session."),
  ]),

  // ----- 3. Methodology (NUMBERED list) -----
  new Paragraph({ heading: HeadingLevel.HEADING_1, text: "3. Methodology" }),
  new Paragraph({ heading: HeadingLevel.HEADING_2, text: "3.1 Data pipeline" }),
  body("Metrics are produced by a deterministic four-stage pipeline. Each stage is idempotent and independently auditable:"),
  new Paragraph({ numbering: { reference: NUM_STEPS, level: 0 }, children: [new TextRun("Ingest raw events from the application event bus into the staging store.")] }),
  new Paragraph({ numbering: { reference: NUM_STEPS, level: 0 }, children: [new TextRun("Deduplicate and sessionize events using a 30-minute inactivity window.")] }),
  new Paragraph({ numbering: { reference: NUM_STEPS, level: 0 }, children: [new TextRun("Aggregate sessionized data into daily and quarterly rollups.")] }),
  new Paragraph({ numbering: { reference: NUM_STEPS, level: 0 }, children: [new TextRun("Reconcile rollups against the billing system before publishing.")] }),

  // ----- 3.2 Assumptions (BULLETED list, with a nested level) -----
  new Paragraph({ heading: HeadingLevel.HEADING_2, text: "3.2 Assumptions" }),
  body("The figures rest on the following assumptions, listed for transparency:"),
  new Paragraph({ bullet: { level: 0 }, children: [new TextRun("Timestamps are normalized to UTC before sessionization.")] }),
  new Paragraph({ bullet: { level: 0 }, children: [new TextRun("Internal and test accounts are excluded from all user counts.")] }),
  new Paragraph({ bullet: { level: 1 }, children: [new TextRun("Sub-bullet: test accounts are identified by the org allowlist.")] }),
  new Paragraph({ bullet: { level: 0 }, children: [new TextRun("Refunded transactions are netted out of revenue metrics.")] }),

  // ----- 3.3 Analyst note (H3 + block quote) -----
  new Paragraph({ heading: HeadingLevel.HEADING_3, text: "3.3 Analyst note" }),
  body("One qualitative observation framed the quarter and is worth quoting directly:"),
  blockQuote,

  // ----- 4. Recommendations -----
  new Paragraph({ heading: HeadingLevel.HEADING_1, text: "4. Recommendations" }),
  body([
    t("We recommend a focused onboarding investment in Q2. Modeling suggests a "),
    t("2–3 percentage-point", { bold: true }),
    t(" retention lift is achievable by reducing first-session friction, with no expected increase in support load."),
  ]),
  new Paragraph({ bullet: { level: 0 }, children: [new TextRun("Ship a streamlined three-step first-run experience.")] }),
  new Paragraph({ bullet: { level: 0 }, children: [new TextRun("Instrument drop-off at each onboarding step for fast iteration.")] }),
  new Paragraph({ bullet: { level: 0 }, children: [new TextRun("Re-run this analysis monthly during the rollout.")] }),

  // ----- References (page break, then numbered citation list) -----
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ heading: HeadingLevel.HEADING_1, text: "References" }),
  new Paragraph({ numbering: { reference: NUM_REFS, level: 0 }, children: [new TextRun("Operations Analytics Team. Internal Metrics Warehouse Schema, v4. 2026.")] }),
  new Paragraph({ numbering: { reference: NUM_REFS, level: 0 }, children: [new TextRun("Billing Platform. Quarterly Reconciliation Report, Q1 2026.")] }),
  new Paragraph({ numbering: { reference: NUM_REFS, level: 0 }, children: [new TextRun("Product Research. Onboarding Friction Study. 2025.")] }),
];

// ---------------------------------------------------------------------------
// ASSEMBLE — one section carries the header/footer + all flowing content.
// `properties.page.margin` sets uniform 1-inch margins around the page.
// ---------------------------------------------------------------------------
const doc = new Document({
  creator: "GAIA",
  title: "Quarterly Operations Report — Q1 2026",
  description: "Comprehensive operations report generated with docx-js.",
  styles,
  numbering,
  sections: [
    {
      properties: {
        page: {
          margin: {
            top: convertInchesToTwip(1),
            bottom: convertInchesToTwip(1),
            left: convertInchesToTwip(1),
            right: convertInchesToTwip(1),
          },
        },
      },
      headers: { default: header },
      footers: { default: footer },
      children: [...cover, ...toc, ...sectionBody],
    },
  ],
});

const out = process.argv[2] || "out.docx";
Packer.toBuffer(doc).then((buf) => writeFileSync(out, buf));
