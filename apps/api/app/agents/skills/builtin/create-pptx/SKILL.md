---
name: create-pptx
title: Create Presentation
description: Generate a PowerPoint (.pptx) slide deck — pitch decks, reviews, summaries. Use when the user wants slides. Built with pptxgenjs (Node) for native, editable slides and charts.
# When NOT to use: a PDF (use create-pdf), a Word doc (use create-docx), or a spreadsheet (use create-spreadsheet).
target: docgen_agent
---

# Create Presentation

## When to use
The deliverable is a `.pptx` slide deck.

## How it works
A deck template here is a **Node program** (using `pptxgenjs`) that writes the `.pptx`. You adapt the slides' content, then the build script runs it and validates the output. Slides and charts are native and editable in PowerPoint/Google Slides.

**Skill directory:** `/workspace/integrations/docgen/agent/skills/create-pptx` — `templates/`, `reference.md`, and `scripts/` live here; read them by absolute path. Your work goes in `./scratch/`.

## Workflow (every job)
1. **Work in a job dir:** `mkdir -p ./scratch/pptx-<short-name>`.
2. **Adapt the template — don't start blank.** `read /workspace/integrations/docgen/agent/skills/create-pptx/templates/deck.mjs`, then `write` the edited deck to `./scratch/pptx-<name>/deck.mjs` (title, bullets, table rows, chart data). Read `/workspace/integrations/docgen/agent/skills/create-pptx/reference.md` for the slide-building blocks.
3. **Build + validate:**
   ```
   bash /workspace/integrations/docgen/agent/skills/create-pptx/scripts/build.sh ./scratch/pptx-<name>/deck.mjs ./scratch/pptx-<name>/out.pptx
   ```
   Prints `OK: <path> (slides=N)` or `ERROR: ...`.
4. **Fix loop:** on `ERROR`, read the message, fix, re-run. Cap at 5 attempts.
5. **Deliver:** `mv ./scratch/pptx-<name>/out.pptx ./artifacts/<final-name>.pptx`, then report the full path. Moving it into `artifacts/` surfaces it to the user.

## Layout discipline (important)
There is no automatic visual check — you place elements by coordinates (inches). To avoid overflow:
- Keep to ~6 bullets per slide, ~6–8 words per bullet.
- Use the template's `x/y/w/h` grid; don't push text past the slide width (13.33in wide on the default widescreen layout).
- One idea per slide. Split dense content across slides.

## Toolchain note
The build script installs `pptxgenjs` on first use; the first deck may take a little longer, then it's fast.

## Never
- Never overload a slide — split it. Never leave the file in `./scratch/`. Never skip build/validate.

## Templates
- `deck.mjs` — title slide, agenda, content (bullets), a table slide, a native chart slide, and a closing slide.
