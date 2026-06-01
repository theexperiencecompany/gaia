---
name: create-docx
title: Create Word Document
description: Generate an editable Microsoft Word (.docx) document — reports, letters, memos, structured docs. Use when the user wants a Word file. Built with docx-js (Node) for high fidelity.
# When NOT to use: a PDF (use create-pdf), a Google Doc (use the googledocs skill), or a spreadsheet (use create-spreadsheet).
target: docgen_agent
---

# Create Word Document

## When to use
The deliverable is an editable `.docx`. For a fixed PDF use `create-pdf`; for Google Docs use the googledocs skill.

## How it works
A `.docx` template here is a **Node program** (using the `docx` library) that, when run, writes the Word file. You adapt the program's content, then the build script runs it and validates the output. You do **not** hand-edit XML.

## Rendering rules (do NOT break these)
The document must render correctly in EVERY viewer, including macOS Quick Look / Preview / Pages — not just Word:
- **No auto Table-of-Contents field.** A `TableOfContents` field only computes in Word after "update fields"; everywhere else it renders as a broken flat list of every paragraph + page number. Use a **static** "Contents" list (styled text, no page-number fields) or omit it.
- **Set fonts explicitly.** Don't rely on `HeadingLevel.TITLE` (renders serif in non-Word viewers) — give the cover title an explicit `TextRun({ font, size, bold })`. Use a safe font (`"Calibri"`/`"Arial"`) consistently.
- **Table column widths must sum correctly** (set the table `width` to 100% and `WidthType.PERCENTAGE` cell widths that add up) — otherwise columns collapse to 1-character-per-line vertical text.

**Skill directory:** `/workspace/integrations/docgen/agent/skills/create-docx` — templates, `reference.md`, and `scripts/` live here; read them by absolute path. Your work goes in `./scratch/`.

## Workflow (every job)
1. **Work in a job dir:** `mkdir -p ./scratch/docx-<short-name>`.
2. **Adapt the template — don't start blank.** `read /workspace/integrations/docgen/agent/skills/create-docx/templates/report.mjs`, then `write` the edited program to `./scratch/docx-<name>/doc.mjs`. Read `/workspace/integrations/docgen/agent/skills/create-docx/reference.md` for the docx-js building blocks.
3. **Build + validate:**
   ```
   bash /workspace/integrations/docgen/agent/skills/create-docx/scripts/build.sh ./scratch/docx-<name>/doc.mjs ./scratch/docx-<name>/out.docx
   ```
   Prints `OK: <path>` on success or `ERROR: ...` (the Node error) on failure.
4. **Fix loop:** on `ERROR`, read the message, fix the program, re-run. Cap at 5 attempts.
5. **Deliver:** `mv ./scratch/docx-<name>/out.docx ./artifacts/<final-name>.docx`, then report the full path. Moving it into `artifacts/` is what surfaces it to the user (web card / sent as a file on WhatsApp etc).

## Toolchain note
The build script installs the `docx` Node library on first use; the first document may take a little longer, then it's fast.

## Never
- Never edit raw OOXML/XML by hand — adapt the Node template.
- Never leave the file in `./scratch/`. Never skip the build/validate step.

## Templates
- `report.mjs` — comprehensive multi-section report: cover (explicit-font title), static Contents, styled headings, justified body, bulleted + numbered lists, a styled data table with correct column widths, a block quote, running header/footer with page numbers, and a references list.
