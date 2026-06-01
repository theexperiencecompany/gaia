// LETTER TEMPLATE (docx-js) — formal/business letter. Adapt the values + body.
// Run via: bash scripts/build.sh letter.mjs out.docx
import { Document, Packer, Paragraph, TextRun, AlignmentType } from "docx";
import { writeFileSync } from "node:fs";

const sender = {
  name: "Jane Doe",
  line2: "Head of Operations, Acme Corp",
  line3: "123 Market St, San Francisco, CA 94103",
  email: "jane@acme.com",
};
const recipient = { name: "Mr. John Smith", org: "Globex Inc.", address: "500 Industrial Ave, Austin, TX 78701" };
const subject = "Re: Partnership proposal";
const today = new Date().toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });

const p = (text, opts = {}) => new Paragraph({ spacing: { after: 160 }, ...opts, children: [new TextRun(text)] });
const right = (text) => new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun(text)] });

const doc = new Document({
  sections: [
    {
      properties: {},
      children: [
        right(sender.name),
        right(sender.line2),
        right(sender.line3),
        right(sender.email),
        p(""),
        p(today),
        p(recipient.name, { spacing: { after: 0 } }),
        p(recipient.org, { spacing: { after: 0 } }),
        p(recipient.address),
        new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: subject, bold: true })] }),
        p(`Dear ${recipient.name},`),
        p("Replace this with the opening — why you are writing."),
        p("Replace this with the body — the substance, the ask, or the proposal."),
        p("Replace this with the closing and next steps."),
        p("Sincerely,"),
        p(""),
        p(sender.name, { spacing: { after: 0 } }),
        p(sender.line2),
      ],
    },
  ],
});

const out = process.argv[2] || "out.docx";
Packer.toBuffer(doc).then((buf) => writeFileSync(out, buf));
