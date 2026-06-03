// REPORT TEMPLATE (docx-js) — comprehensive, multi-section .docx report.
//
// This file is a benchmark-quality reference for building rich Word documents
// with the `docx` npm package (ESM). It is heavily commented so an LLM can
// learn each feature by example, then adapt the values/content for a real task.
//
// Run via: bash scripts/build.sh report.mjs out.docx
// Contract: build a `Document`, then write it to process.argv[2] (fallback
// "out.docx"). Do NOT reference external image/asset files — none exist.
//
// ---------------------------------------------------------------------------
// CROSS-VIEWER CORRECTNESS NOTES (why this template is written the way it is)
// ---------------------------------------------------------------------------
// This report is built to render correctly in NON-Word viewers — macOS Quick
// Look, Preview, and Pages — not just Microsoft Word. Those viewers do NOT run
// Word's "update fields" pass and are stricter about table geometry, so three
// classes of bug that "look fine in Word" must be avoided entirely:
//
//   1. SERIF COVER TITLE. The built-in Word "Title" style (HeadingLevel.TITLE)
//      defaults to a serif/theme font. We never restyled it, so Apple viewers
//      fell back to serif. FIX: the cover title is a PLAIN Paragraph whose
//      TextRun carries an explicit { font } — never HeadingLevel.TITLE.
//
//   2. BROKEN AUTO-TOC. `TableOfContents` emits a Word FIELD CODE that only
//      computes on "update fields". Apple viewers show the un-computed field as
//      a flat list of every paragraph + stray page numbers. FIX: NO field-code
//      TOC anywhere. We render a STATIC "Contents" list as ordinary styled
//      paragraphs — section names only, no page-number fields, no tab leaders.
//
//   3. VERTICAL 1-CHAR-PER-LINE TABLE. If table column widths are too narrow or
//      don't sum to the table width, Apple viewers collapse each column to a
//      single character wide and stack text vertically. FIX: every table sets
//      width 100% and uses explicit WidthType.PERCENTAGE column widths that sum
//      to exactly 100; the table-level `columnWidths` is also given so the
//      geometry is unambiguous to non-Word layout engines.

import {
  Document,
  Packer,
  Paragraph,
  TextRun,
  HeadingLevel,
  AlignmentType,
  LineRuleType,
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

// A safe font applied CONSISTENTLY everywhere — body, headings, table cells,
// AND the cover title. "Calibri" exists on virtually every Windows/Office
// install; "Arial" is the cross-platform fallback (macOS/Linux). Because we
// set this explicitly on every run, no viewer can fall back to a serif face.
const FONT = "Calibri";

// Numbering reference ids configured on the Document and attached to ordered
// paragraphs below. Bullets use the built-in `bullet` shortcut, but ORDERED
// (1. 2. 3.) lists must reference a numbering definition like these.
const NUM_STEPS = "ordered-steps"; // the "How it works" numbered list
const NUM_REFS = "references-list"; // the final References list

// Page width available for content = US Letter (12240 twips) minus 1" margins
// on each side. Used to give tables an explicit absolute column geometry in
// addition to percentages, so non-Word engines never guess column widths.
const CONTENT_WIDTH_TWIP = 12240 - 2 * convertInchesToTwip(1); // 9360 twips

// Split a content-width into integer twip columns from a list of percentages.
// Guarantees the per-column absolute widths sum to the full content width.
const colWidths = (...percents) => {
  const widths = percents.map((p) => Math.round((p / 100) * CONTENT_WIDTH_TWIP));
  // Absorb any rounding drift into the last column so the sum is exact.
  const drift = CONTENT_WIDTH_TWIP - widths.reduce((a, b) => a + b, 0);
  widths[widths.length - 1] += drift;
  return widths;
};

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

// A plain text run on the body colour + font — the default for most prose.
// Every TextRun in the document carries an explicit `font` so that no viewer
// (Word, Pages, Quick Look) can substitute a different face.
const t = (text, opts = {}) => new TextRun({ text, font: FONT, color: COLORS.ink, ...opts });

// ---------------------------------------------------------------------------
// 1) STYLES — document-wide default + named paragraph styles.
// `default.document` sets the base run font/size for EVERYTHING (this is what
// guarantees a consistent sans-serif face across viewers). We also restyle the
// built-in heading1-3 styles so the body headings carry brand colour.
//
// NOTE: we deliberately do NOT use the built-in "Title" style — its default
// font is serif in non-Word viewers. The cover title is rendered explicitly
// (see section 7) instead.
// ---------------------------------------------------------------------------
const styles = {
  default: {
    document: {
      run: { font: FONT, size: 22, color: COLORS.ink }, // 11pt body, sans-serif
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
  // Custom named styles applied to captions and to the static TOC entries.
  paragraphStyles: [
    {
      id: "Caption",
      name: "Caption",
      basedOn: "Normal",
      next: "Normal",
      run: { font: FONT, size: 18, italics: true, color: COLORS.muted }, // 9pt
      paragraph: { spacing: { before: 80, after: 240 }, alignment: AlignmentType.CENTER },
    },
    {
      // Static "Contents" entry — a plain styled paragraph, NOT a TOC field.
      id: "TocEntry",
      name: "Toc Entry",
      basedOn: "Normal",
      next: "Normal",
      run: { font: FONT, size: 22, color: COLORS.ink },
      paragraph: { spacing: { after: 80 }, indent: { left: convertInchesToTwip(0.25) } },
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
          style: {
            paragraph: {
              indent: { left: convertInchesToTwip(0.5), hanging: convertInchesToTwip(0.25) },
            },
          },
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
          style: {
            paragraph: {
              indent: { left: convertInchesToTwip(0.5), hanging: convertInchesToTwip(0.3) },
            },
          },
        },
      ],
    },
  ],
};

// ---------------------------------------------------------------------------
// 3) RUNNING HEADER + FOOTER — appear on every page of the section. The footer
// uses field codes: PageNumber.CURRENT and PageNumber.TOTAL_PAGES render live
// "Page X of Y" values. These are simple, well-supported page-number fields
// (distinct from the problematic TOC field) and render fine in Apple viewers.
// ---------------------------------------------------------------------------
const header = new Header({
  children: [
    new Paragraph({
      alignment: AlignmentType.RIGHT,
      // a thin bottom rule under the header text
      border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: COLORS.muted, space: 4 } },
      children: [new TextRun({ text: "GAIA — Quarterly Operations Report", font: FONT, size: 16, color: COLORS.muted })],
    }),
  ],
});

const footer = new Footer({
  children: [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      border: { top: { style: BorderStyle.SINGLE, size: 4, color: COLORS.muted, space: 4 } },
      children: [
        new TextRun({ text: "Confidential", font: FONT, size: 16, color: COLORS.muted }),
        new TextRun({ text: "    |    Page ", font: FONT, size: 16, color: COLORS.muted }),
        new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: COLORS.muted }),
        new TextRun({ text: " of ", font: FONT, size: 16, color: COLORS.muted }),
        new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: 16, color: COLORS.muted }),
      ],
    }),
  ],
});

// ---------------------------------------------------------------------------
// 4) STYLED DATA TABLE — header row shaded with the brand colour, percentage
// column widths that SUM TO 100, full borders, and zebra-striped body rows.
//
// Column geometry: 40 / 20 / 20 / 20 = 100%. We ALSO pass `columnWidths` (an
// absolute twip array summing to the content width) on the Table so non-Word
// layout engines have an unambiguous grid and never collapse columns to one
// character wide.
// ---------------------------------------------------------------------------
const cellBorder = { style: BorderStyle.SINGLE, size: 2, color: "D1D5DB" };
const allBorders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };

// A header cell: shaded background + white bold text, centered. The width %
// is declared on the cell so each column's share is explicit.
const headCell = (text, widthPct) =>
  new TableCell({
    width: { size: widthPct, type: WidthType.PERCENTAGE },
    shading: { type: ShadingType.CLEAR, fill: COLORS.headerFill, color: "auto" },
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text, font: FONT, bold: true, color: "FFFFFF", size: 20 })],
      }),
    ],
  });

// A body cell: explicit width %, optional zebra shading, optional right-align.
const dataCell = (text, widthPct, { zebra = false, alignRight = false, bold = false } = {}) =>
  new TableCell({
    width: { size: widthPct, type: WidthType.PERCENTAGE },
    shading: zebra ? { type: ShadingType.CLEAR, fill: COLORS.zebra, color: "auto" } : undefined,
    margins: { top: 50, bottom: 50, left: 100, right: 100 },
    children: [
      new Paragraph({
        alignment: alignRight ? AlignmentType.RIGHT : AlignmentType.LEFT,
        children: [new TextRun({ text, font: FONT, size: 20, bold, color: COLORS.ink })],
      }),
    ],
  });

// Column percentages for the data table — MUST sum to 100.
const DATA_COLS = [40, 20, 20, 20];

const metricsRows = [
  ["Active users", "42,180", "+12.4%", "On track"],
  ["Avg. session (min)", "8.7", "+0.9", "Above target"],
  ["Task completion", "91.3%", "+3.1pp", "On track"],
  ["Support tickets", "1,204", "-7.6%", "Improving"],
];

const dataTable = new Table({
  width: { size: 100, type: WidthType.PERCENTAGE },
  columnWidths: colWidths(...DATA_COLS), // absolute twip grid, sums to content width
  borders: allBorders,
  rows: [
    new TableRow({
      tableHeader: true, // repeat this row if the table breaks across pages
      children: [
        headCell("Metric", DATA_COLS[0]),
        headCell("Value", DATA_COLS[1]),
        headCell("Delta (QoQ)", DATA_COLS[2]),
        headCell("Status", DATA_COLS[3]),
      ],
    }),
    ...metricsRows.map(
      (row, i) =>
        new TableRow({
          children: [
            dataCell(row[0], DATA_COLS[0], { zebra: i % 2 === 1 }),
            dataCell(row[1], DATA_COLS[1], { zebra: i % 2 === 1, alignRight: true }),
            dataCell(row[2], DATA_COLS[2], { zebra: i % 2 === 1, alignRight: true }),
            dataCell(row[3], DATA_COLS[3], { zebra: i % 2 === 1 }),
          ],
        }),
    ),
  ],
});

// ---------------------------------------------------------------------------
// 5) METADATA TABLE — a two-column "key: value" grid. Borders are NONE so it
// reads as a clean layout block, BUT the column widths are explicit (30/70)
// and the table has an absolute `columnWidths` grid — this is exactly the
// geometry that, when omitted, made Apple viewers render the values as
// 1-character-per-line vertical text. Wide value column = readable values.
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

// 30% label column, 70% value column — sums to 100.
const SUMMARY_COLS = [30, 70];

const summaryRow = (label, value) =>
  new TableRow({
    children: [
      new TableCell({
        width: { size: SUMMARY_COLS[0], type: WidthType.PERCENTAGE },
        borders: noBorders,
        margins: { top: 30, bottom: 30, right: 100 },
        children: [
          new Paragraph({
            children: [new TextRun({ text: label, font: FONT, bold: true, color: COLORS.muted, size: 20 })],
          }),
        ],
      }),
      new TableCell({
        width: { size: SUMMARY_COLS[1], type: WidthType.PERCENTAGE },
        borders: noBorders,
        margins: { top: 30, bottom: 30 },
        children: [
          new Paragraph({
            children: [new TextRun({ text: value, font: FONT, color: COLORS.ink, size: 20 })],
          }),
        ],
      }),
    ],
  });

const summaryTable = new Table({
  width: { size: 100, type: WidthType.PERCENTAGE },
  columnWidths: colWidths(...SUMMARY_COLS), // explicit 30/70 absolute grid
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
      font: FONT,
      italics: true,
      color: COLORS.ink,
      size: 22,
    }),
  ],
});

// ---------------------------------------------------------------------------
// 7) COVER PAGE — large centered title, subtitle, author, date, generous
// vertical spacing, then a hard page break.
//
// CRITICAL: the title is a PLAIN Paragraph whose TextRun has an explicit
// `font: FONT`. We do NOT use HeadingLevel.TITLE — its built-in style defaults
// to a serif/theme font that we never restyled, which is exactly why the title
// previously rendered serif in macOS Preview/Pages. An explicit run font makes
// the face deterministic in every viewer.
// ---------------------------------------------------------------------------
const today = new Date().toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });

const cover = [
  new Paragraph({ spacing: { before: 2400 } }), // push the title down the page
  new Paragraph({
    alignment: AlignmentType.CENTER,
    // 26pt fits "Quarterly Operations Report" on one line at this width (no
    // wrap). The explicit AT_LEAST line rule (≥34pt) is a safety net so that
    // even if it does wrap, the lines never overlap (a plain AUTO `line` was
    // ignored by some non-Word viewers).
    spacing: { after: 200, line: 680, lineRule: LineRuleType.AT_LEAST },
    children: [new TextRun({ text: "Quarterly Operations Report", font: FONT, bold: true, size: 52, color: COLORS.brandDark })], // 26pt, explicit sans-serif
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 600 },
    children: [new TextRun({ text: "Performance, Insights & Recommendations — Q1 2026", font: FONT, size: 28, color: COLORS.brand })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 60 },
    children: [new TextRun({ text: "Prepared by the Operations Analytics Team", font: FONT, size: 24, color: COLORS.ink })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: today, font: FONT, size: 22, color: COLORS.muted })],
  }),
  // A PageBreak inside a paragraph ends the cover page.
  new Paragraph({ children: [new PageBreak()] }),
];

// ---------------------------------------------------------------------------
// 8) STATIC CONTENTS — NOT a Word TOC field.
//
// We deliberately avoid docx's `TableOfContents` because it emits a field code
// that only computes during Word's "update fields" pass. In macOS Quick Look /
// Preview / Pages that field is never computed, so it renders as a broken flat
// list. Instead we hand-write the section list as ordinary styled paragraphs
// (section names only — no page numbers, no tab leaders, no fields). This is
// 100% static text and renders identically everywhere.
// ---------------------------------------------------------------------------
const TOC_SECTIONS = [
  "1. Executive Summary",
  "2. Key Metrics",
  "3. Methodology",
  "4. Recommendations",
  "References",
];

const toc = [
  new Paragraph({ heading: HeadingLevel.HEADING_1, text: "Contents" }),
  ...TOC_SECTIONS.map(
    (label) =>
      new Paragraph({
        style: "TocEntry",
        children: [new TextRun({ text: label, font: FONT, color: COLORS.ink, size: 22 })],
      }),
  ),
  new Paragraph({ children: [new PageBreak()] }),
];

// ---------------------------------------------------------------------------
// 9) BODY — numbered sections via headings + the building blocks above.
// Section labels here match the static Contents list above.
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
    new TextRun({ text: "highlighted", font: FONT, highlight: "yellow", color: COLORS.ink }),
    t(". Footnote markers use superscript"),
    new TextRun({ text: "1", font: FONT, superScript: true, color: COLORS.ink }),
    t(" and unit notation can use subscript, e.g. CO"),
    new TextRun({ text: "2", font: FONT, subScript: true, color: COLORS.ink }),
    t(" emissions per session."),
  ]),

  // ----- 3. Methodology (NUMBERED list) -----
  new Paragraph({ heading: HeadingLevel.HEADING_1, text: "3. Methodology" }),
  new Paragraph({ heading: HeadingLevel.HEADING_2, text: "3.1 Data pipeline" }),
  body("Metrics are produced by a deterministic four-stage pipeline. Each stage is idempotent and independently auditable:"),
  new Paragraph({ numbering: { reference: NUM_STEPS, level: 0 }, children: [t("Ingest raw events from the application event bus into the staging store.")] }),
  new Paragraph({ numbering: { reference: NUM_STEPS, level: 0 }, children: [t("Deduplicate and sessionize events using a 30-minute inactivity window.")] }),
  new Paragraph({ numbering: { reference: NUM_STEPS, level: 0 }, children: [t("Aggregate sessionized data into daily and quarterly rollups.")] }),
  new Paragraph({ numbering: { reference: NUM_STEPS, level: 0 }, children: [t("Reconcile rollups against the billing system before publishing.")] }),

  // ----- 3.2 Assumptions (BULLETED list, with a nested level) -----
  new Paragraph({ heading: HeadingLevel.HEADING_2, text: "3.2 Assumptions" }),
  body("The figures rest on the following assumptions, listed for transparency:"),
  new Paragraph({ bullet: { level: 0 }, children: [t("Timestamps are normalized to UTC before sessionization.")] }),
  new Paragraph({ bullet: { level: 0 }, children: [t("Internal and test accounts are excluded from all user counts.")] }),
  new Paragraph({ bullet: { level: 1 }, children: [t("Sub-bullet: test accounts are identified by the org allowlist.")] }),
  new Paragraph({ bullet: { level: 0 }, children: [t("Refunded transactions are netted out of revenue metrics.")] }),

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
  new Paragraph({ bullet: { level: 0 }, children: [t("Ship a streamlined three-step first-run experience.")] }),
  new Paragraph({ bullet: { level: 0 }, children: [t("Instrument drop-off at each onboarding step for fast iteration.")] }),
  new Paragraph({ bullet: { level: 0 }, children: [t("Re-run this analysis monthly during the rollout.")] }),

  // ----- References (page break, then numbered citation list) -----
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ heading: HeadingLevel.HEADING_1, text: "References" }),
  new Paragraph({ numbering: { reference: NUM_REFS, level: 0 }, children: [t("Operations Analytics Team. Internal Metrics Warehouse Schema, v4. 2026.")] }),
  new Paragraph({ numbering: { reference: NUM_REFS, level: 0 }, children: [t("Billing Platform. Quarterly Reconciliation Report, Q1 2026.")] }),
  new Paragraph({ numbering: { reference: NUM_REFS, level: 0 }, children: [t("Product Research. Onboarding Friction Study. 2025.")] }),
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
