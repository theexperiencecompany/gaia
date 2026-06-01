---
name: create-pdf
title: Create PDF
description: Generate a polished, printable PDF — reports, letters, invoices, resumes, one-pagers. Use when the user wants a PDF document. Typst is the primary engine; LaTeX (tectonic) is the fallback for niche packages or specific academic/journal templates.
# When NOT to use: editing a Google Doc (use the googledocs skill), or producing an editable Word file (use create-docx).
target: docgen_agent
---

# Create PDF

## When to use
The deliverable is a PDF. For Word use `create-docx`, for slides `create-pptx`, for spreadsheets `create-spreadsheet`.

## Engine decision
- **Default: Typst.** Fast, single-pass, and its errors are short and point at a line — you can fix them quickly. Templates here are `.typ`.
- **Fallback: LaTeX via tectonic.** Switch only when you need a LaTeX-only package, a specific journal/publisher class file, or Typst fails the same way twice. Write a `.tex` file and the build script compiles it with tectonic. See `reference.md` for when each applies.

**Skill directory:** `/workspace/integrations/docgen/agent/skills/create-pdf` — the templates, `reference.md`, and `scripts/` referenced below live here. Read them by absolute path (the `read` tool serves them instantly from memory); your own work goes in `./scratch/` (relative to the session).

## Workflow (every job)
1. **Work in a job dir:** `mkdir -p ./scratch/pdf-<short-name>` and do everything there. Never build in `./artifacts/`.
2. **Adapt a template — do not start blank.** `read /workspace/integrations/docgen/agent/skills/create-pdf/templates/report.typ` (or `letter.typ`, `invoice.typ`, `resume.typ`), then `write` the filled-in version to `./scratch/pdf-<name>/main.typ`. Read `/workspace/integrations/docgen/agent/skills/create-pdf/reference.md` for syntax and the common-error → fix table.
3. **Put data in a file** if there's a lot of it, and reference it from the source, rather than inlining giant blobs.
4. **Build + validate** with the bundled script (absolute path):
   ```
   bash /workspace/integrations/docgen/agent/skills/create-pdf/scripts/build.sh ./scratch/pdf-<name>/main.typ ./scratch/pdf-<name>/out.pdf
   ```
   It compiles, validates the PDF (non-empty, real pages), and prints `OK: <path> (pages=N)` or a short `ERROR: file:line: message`.
5. **Fix loop:** on `ERROR`, read the message, edit the source, re-run. **Cap at 5 attempts.** If Typst keeps failing on the same construct, switch to the LaTeX/tectonic path (write `main.tex`, run the same `build.sh` with the `.tex` file).
6. **Deliver:** once you get `OK`, move the final PDF into artifacts:
   ```
   mv ./scratch/pdf-<name>/out.pdf ./artifacts/<final-name>.pdf
   ```
   Then report the full path (`/workspace/sessions/<conv>/artifacts/<final-name>.pdf`). Moving it into `artifacts/` is what makes it show up for the user (web card, or sent as a file on WhatsApp/etc).

## Toolchain note
The build script provisions Typst + tectonic on first use; the very first PDF may take a little longer while that happens, then it's fast.

## Never
- Never author a layout from scratch when a template fits — adapt one.
- Never leave the deliverable in `./scratch/`. Never skip the build/validate step.
- Never loop past 5 fix attempts on one engine — fall back to LaTeX or report the blocking error.

## Templates
- `report.typ` — multi-section report with title block, headings, a table.
- `letter.typ` — formal/business letter.
- `invoice.typ` — itemized invoice with totals.
- `resume.typ` — single-column resume / CV.
