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
A `.docx` template here is a small **Node program** (using the `docx` library) that, when run, writes the Word file. You adapt the program's content, then the build script runs it and validates the output. You do **not** hand-edit XML.

## Workflow (every job)
1. **Work in a job dir:** `mkdir -p ./scratch/docx-<short-name>`.
2. **Adapt a template — don't start blank.** `read` the closest file in `templates/` (`report.mjs`, `letter.mjs`) and replace its content (headings, paragraphs, table rows) with the real material. Read `reference.md` for the docx-js building blocks.
3. **Build + validate:**
   ```
   bash scripts/build.sh ./scratch/docx-<name>/doc.mjs ./scratch/docx-<name>/out.docx
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
- `report.mjs` — titled report with headings, paragraphs, and a table.
- `letter.mjs` — formal/business letter.
