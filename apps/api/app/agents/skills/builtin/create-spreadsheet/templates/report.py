"""REPORT TEMPLATE (openpyxl) — adapt the data + columns. Values are computed
in Python and written directly (no live formulas). Keep the structure.

Run via: bash scripts/build.sh report.py out.xlsx
"""

import sys

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill

BRAND = "1A4D8F"

# --- Data (edit this) ---------------------------------------------------------
# Each row: (region, q1, q2, q3)
rows = [
    ("North", 120000, 138000, 151000),
    ("South", 98000, 102000, 119000),
    ("East", 76000, 81000, 88000),
    ("West", 110000, 121000, 134000),
]
headers = ["Region", "Q1", "Q2", "Q3", "Total"]

# --- Build workbook -----------------------------------------------------------
wb = Workbook()
ws = wb.active
ws.title = "Summary"

ws.append(headers)
for c in ws[1]:
    c.font = Font(bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor=BRAND)
    c.alignment = Alignment(horizontal="center")

# Data rows — Total computed in Python (a value, not a formula).
for region, q1, q2, q3 in rows:
    ws.append([region, q1, q2, q3, q1 + q2 + q3])

# Totals row — also computed values.
col_totals = [sum(r[i] for r in rows) for i in range(1, 4)]
grand_total = sum(col_totals)
ws.append(["Total", *col_totals, grand_total])
for c in ws[ws.max_row]:
    c.font = Font(bold=True)

# Number formatting for the numeric columns.
for row in ws.iter_rows(min_row=2, min_col=2, max_col=5):
    for c in row:
        c.number_format = '"$"#,##0'

# Layout
widths = {"A": 14, "B": 12, "C": 12, "D": 12, "E": 14}
for col, w in widths.items():
    ws.column_dimensions[col].width = w
ws.freeze_panes = "A2"

# Bar chart of quarterly totals per region.
chart = BarChart()
chart.title = "Revenue by region"
chart.y_axis.title = "USD"
data = Reference(ws, min_col=2, max_col=4, min_row=1, max_row=1 + len(rows))
cats = Reference(ws, min_col=1, min_row=2, max_row=1 + len(rows))
chart.add_data(data, titles_from_data=True)
chart.set_categories(cats)
chart.height = 8
chart.width = 16
ws.add_chart(chart, "G2")

out = sys.argv[1] if len(sys.argv) > 1 else "out.xlsx"
wb.save(out)
