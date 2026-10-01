---
name: create-spreadsheet
title: Create Spreadsheet
description: Generate an Excel (.xlsx) workbook or a CSV file — tables, financial models, data exports, formatted reports with charts. Use when the user wants a spreadsheet or CSV. Built with openpyxl + pandas (Python).
# When NOT to use: a Google Sheet (use the googlesheets skill), a PDF table (use create-pdf), or a Word doc (use create-docx).
target: docgen_agent
---

# Create Spreadsheet

## When to use
The deliverable is `.xlsx` or `.csv`. For Google Sheets use the googlesheets skill.

## Important: values, not live formulas
There is **no spreadsheet recalc engine** in the sandbox. If you write a formula like `=SUM(...)`, Excel shows it as blank until the user opens and recalculates. So:
- **Compute results in Python (pandas/numpy) and write the final values.** This is the default and it always opens correctly.
- Only add a literal `=FORMULA` when the user explicitly wants an editable formula — and when you do, also write the computed value in an adjacent labeled cell so the number is visible immediately.

## How it works
A template here is a **Python program** (openpyxl + pandas) that writes the workbook. You adapt the data and structure, then the build script runs it and validates the file.

**Skill directory:** `/workspace/integrations/docgen/agent/skills/create-spreadsheet` — `templates/`, `reference.md`, and `scripts/` live here; read them by absolute path. Your work goes in `./scratch/`.

## Workflow (.xlsx)
1. **Work in a job dir:** `mkdir -p ./scratch/xlsx-<short-name>`.
2. **Adapt the template — don't start blank.** `read /workspace/integrations/docgen/agent/skills/create-spreadsheet/templates/report.py`, then `write` the edited program to `./scratch/xlsx-<name>/sheet.py`. Read `/workspace/integrations/docgen/agent/skills/create-spreadsheet/reference.md` for openpyxl building blocks and the values rule.
3. **Build + validate:**
   ```
   bash /workspace/integrations/docgen/agent/skills/create-spreadsheet/scripts/build.sh ./scratch/xlsx-<name>/sheet.py ./scratch/xlsx-<name>/out.xlsx
   ```
   Prints `OK: <path> (sheets=N)` or `ERROR: ...`.
4. **Fix loop:** on `ERROR`, read the message, fix, re-run. Cap at 5 attempts.
5. **Deliver:** `mv ./scratch/xlsx-<name>/out.xlsx ./artifacts/<final-name>.xlsx`, then report the full path.

## CSV (no build needed)
CSV is plain text — write it directly with `bash` and deliver:
```
python3 - <<'PY'
import csv
rows = [["name","amount"], ["Acme", 1200], ["Globex", 980]]
with open("./artifacts/<final-name>.csv", "w", newline="") as f:
    csv.writer(f).writerows(rows)
PY
```
No toolchain, no validation step — just confirm the file is in `./artifacts/` and report the path.

## Toolchain note
The build script provisions openpyxl + pandas on first use; the first workbook may take a little longer, then it's fast.

## Never
- Never write `=` formulas as the only representation of a computed number (no recalc → blank cells). Write the value.
- Never leave the file in `./scratch/`. Never skip build/validate for `.xlsx`.

## Templates
- `report.py` — formatted workbook: styled header, data rows, a computed totals row, number formats, column widths, and a bar chart.
