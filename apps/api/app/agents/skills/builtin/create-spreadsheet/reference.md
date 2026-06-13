# openpyxl / pandas reference

`read` this when adapting `report.py`. The template is a Python program that writes the workbook to the path passed as `sys.argv[1]`.

## The values rule (read first)
No recalc engine exists. Compute in Python and write the **value**:
```python
total = sum(amounts)          # compute in Python
ws["B10"] = total             # write the value, NOT "=SUM(B2:B9)"
```
If the user wants an editable formula too, write both: the value in one cell and, separately, the formula in a clearly labeled "editable" cell.

## openpyxl skeleton
```python
import sys
from openpyxl import Workbook
wb = Workbook()
ws = wb.active
ws.title = "Summary"
ws.append(["Name", "Amount"])      # header row
ws.append(["Acme", 1200])
wb.save(sys.argv[1])
```

## Building blocks
- **Write a cell:** `ws["A1"] = "Hi"` or `ws.cell(row=1, column=1, value="Hi")`.
- **Append a row:** `ws.append([a, b, c])`.
- **Header styling:**
  ```python
  from openpyxl.styles import Font, PatternFill, Alignment
  for c in ws[1]:
      c.font = Font(bold=True, color="FFFFFF")
      c.fill = PatternFill("solid", fgColor="1A4D8F")
      c.alignment = Alignment(horizontal="center")
  ```
- **Number format:** `ws["B2"].number_format = '#,##0.00'` (currency: `'"$"#,##0.00'`; percent: `'0.0%'`).
- **Column width:** `ws.column_dimensions["A"].width = 24`.
- **Freeze header:** `ws.freeze_panes = "A2"`.
- **Multiple sheets:** `ws2 = wb.create_sheet("Detail")`.
- **Bar chart:**
  ```python
  from openpyxl.chart import BarChart, Reference
  chart = BarChart(); chart.title = "Revenue"
  data = Reference(ws, min_col=2, min_row=1, max_row=ws.max_row)
  cats = Reference(ws, min_col=1, min_row=2, max_row=ws.max_row)
  chart.add_data(data, titles_from_data=True); chart.set_categories(cats)
  ws.add_chart(chart, "E2")
  ```

## pandas (for tabular data)
```python
import pandas as pd
df = pd.DataFrame(records)          # records = list of dicts
df.to_excel(sys.argv[1], index=False, sheet_name="Data")
```
Use pandas for bulk data; switch to openpyxl when you need formatting/charts. To do both, write with pandas via an `ExcelWriter(engine="openpyxl")` then style `writer.sheets[...]`.

## Common error → fix
| Error contains | Cause | Fix |
| --- | --- | --- |
| `No module named openpyxl` / `pandas` | toolchain not installed | re-run the build script |
| cells show blank in Excel | wrote `=FORMULA` with no recalc | write the computed value instead |
| `IllegalCharacterError` | control chars in a string | strip non-printable characters before writing |
| chart not showing | bad `Reference` range | check min/max row/col match your data |
