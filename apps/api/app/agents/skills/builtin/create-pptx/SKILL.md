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
A deck template here is a **Node program** (using `pptxgenjs`) that writes the `.pptx`. You adapt the slides' content, then the build script runs it and validates the output.

## Rendering rules (do NOT break these)
The deck must look right in EVERY viewer, including macOS Keynote / Quick Look — not just PowerPoint:
- **Never use `addChart`.** Native OOXML charts render **blank** in Apple viewers (only the title shows). **Draw charts from shapes** instead — `rect` bars, `line` + small `ellipse` markers for trends, colored `rect` segments for a stacked/share bar. The templates show how.
- **Use a cross-platform font (`"Arial"`).** Fonts like "Segoe UI" trigger a "missing fonts" warning on macOS.
- **No empty slides** — every slide must have visible body content.

**Skill directory:** `/workspace/integrations/docgen/agent/skills/create-pptx` — `templates/`, `reference.md`, and `scripts/` live here; read them by absolute path. Your work goes in `./scratch/`.

## Workflow (every job)
1. **Work in a job dir:** `mkdir -p ./scratch/pptx-<short-name>`.
2. **Adapt the closest template — don't start blank.** `read /workspace/integrations/docgen/agent/skills/create-pptx/templates/deck.mjs` (business review) or `pitch-deck.mjs` (startup pitch), then `write` the edited deck to `./scratch/pptx-<name>/deck.mjs`. Read `/workspace/integrations/docgen/agent/skills/create-pptx/reference.md` for the slide-building blocks.
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
Comprehensive starting points (all charts drawn with shapes, Arial font, ~12 slides) — adapt the closest fit:
- `deck.mjs` — quarterly **business review**: title, agenda, section divider, bullets, 2-column comparison, KPI cards, a drawn bar chart, a drawn line + stacked-share slide, a table, a process/timeline, a quote, and a closing slide.
- `pitch-deck.mjs` — startup **pitch deck**: cover, problem, solution, product cards, market size (drawn), business model, traction (drawn chart + KPIs), competition matrix, go-to-market, team cards, the ask (drawn use-of-funds bar), closing.
