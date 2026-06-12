# docx-js reference

`read` this when adapting a `.docx` template. The template is a Node ES module that builds a `Document` and writes it to the path passed as `process.argv[2]`.

## Skeleton
```js
import { Document, Packer, Paragraph, TextRun, HeadingLevel } from "docx";
import { writeFileSync } from "node:fs";

const doc = new Document({
  sections: [{ properties: {}, children: [ /* paragraphs, tables ... */ ] }],
});

const out = process.argv[2] || "out.docx";
Packer.toBuffer(doc).then((buf) => writeFileSync(out, buf));
```

## Building blocks
- **Paragraph / text:** `new Paragraph({ children: [ new TextRun({ text: "Hello", bold: true }) ] })`.
- **Heading:** `new Paragraph({ text: "Title", heading: HeadingLevel.HEADING_1 })` (also `HEADING_2`, `TITLE`).
- **Alignment:** `new Paragraph({ alignment: AlignmentType.CENTER, children: [...] })` (import `AlignmentType`).
- **Spacing:** `new Paragraph({ spacing: { after: 200 }, children: [...] })` (twips; 200 ≈ 10pt).
- **Bullet list:** `new Paragraph({ text: "item", bullet: { level: 0 } })`.
- **Numbered list:** configure `numbering` on the `Document`, then `numbering: { reference: "my-list", level: 0 }` on the paragraph.
- **Line break:** `new TextRun({ text: "...", break: 1 })`.
- **Table:**
  ```js
  import { Table, TableRow, TableCell, WidthType } from "docx";
  new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    rows: [
      new TableRow({ children: [
        new TableCell({ children: [ new Paragraph("A") ] }),
        new TableCell({ children: [ new Paragraph("B") ] }),
      ]}),
    ],
  });
  ```
- **Page break:** `new Paragraph({ children: [ new PageBreak() ] })` (import `PageBreak`).

## Common error → fix
| Error contains | Cause | Fix |
| --- | --- | --- |
| `Cannot find module 'docx'` | toolchain not yet installed | re-run the build script (it installs `docx`) |
| `X is not a constructor` / `is not exported` | imported a name that doesn't exist | check the import against the blocks above |
| `children must be an array` | passed a string where children expected | wrap content in `new Paragraph(...)` / arrays |
| writes nothing / 0 bytes | forgot to `await`/resolve `Packer.toBuffer` | keep the `.then(buf => writeFileSync(...))` |

docx-js produces valid OOXML by construction — if it runs without error and writes a non-empty file, the document opens in Word.
