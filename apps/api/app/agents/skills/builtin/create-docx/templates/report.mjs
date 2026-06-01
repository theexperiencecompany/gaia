// REPORT TEMPLATE (docx-js) — adapt the content, keep the structure.
// Run via: bash scripts/build.sh report.mjs out.docx
import {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType,
} from "docx";
import { writeFileSync } from "node:fs";

const title = "Quarterly Business Review";
const subtitle = "Q3 2026 · Prepared by GAIA";

// Each row: [metric, q1, q2, q3]
const metrics = [
  ["Metric", "Q1", "Q2", "Q3"],
  ["Revenue", "$1.0M", "$1.2M", "$1.5M"],
  ["Active users", "12.1k", "14.8k", "18.2k"],
  ["Churn", "3.2%", "2.9%", "2.4%"],
];

const cell = (text, bold = false) =>
  new TableCell({ children: [new Paragraph({ children: [new TextRun({ text, bold })] })] });

const doc = new Document({
  sections: [
    {
      properties: {},
      children: [
        new Paragraph({ alignment: AlignmentType.CENTER, heading: HeadingLevel.TITLE, children: [new TextRun(title)] }),
        new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 300 }, children: [new TextRun({ text: subtitle, color: "777777" })] }),

        new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Executive Summary")] }),
        new Paragraph({ spacing: { after: 200 }, children: [new TextRun("Replace this with a short summary of the report's key message and outcome.")] }),

        new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Highlights")] }),
        new Paragraph({ bullet: { level: 0 }, children: [new TextRun("First key result.")] }),
        new Paragraph({ bullet: { level: 0 }, children: [new TextRun("Second key result.")] }),
        new Paragraph({ bullet: { level: 0 }, spacing: { after: 200 }, children: [new TextRun("Third key result.")] }),

        new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Performance")] }),
        new Table({
          width: { size: 100, type: WidthType.PERCENTAGE },
          rows: metrics.map((row, i) =>
            new TableRow({ children: row.map((c) => cell(c, i === 0)) })
          ),
        }),

        new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 300 }, children: [new TextRun("Recommendations")] }),
        new Paragraph({ numbering: undefined, bullet: { level: 0 }, children: [new TextRun("First recommended action.")] }),
        new Paragraph({ bullet: { level: 0 }, children: [new TextRun("Second recommended action.")] }),
      ],
    },
  ],
});

const out = process.argv[2] || "out.docx";
Packer.toBuffer(doc).then((buf) => writeFileSync(out, buf));
