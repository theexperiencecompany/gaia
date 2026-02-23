---
name: googlesheets-charts-graphs
description: Create charts and visualizations in Google Sheets — detect data structure, select chart type, format for clarity, present insights
target: googlesheets_agent
---

# Google Sheets: Charts & Graphs

## When to Activate
User wants to visualize data, create charts, build dashboards, or add graphs to a spreadsheet.

## Step 1: Understand the Data

Before creating any chart, read the data:
```
GOOGLESHEETS_SEARCH_SPREADSHEETS(query="<name>") → spreadsheet_id
GOOGLESHEETS_GET_SHEET_NAMES(spreadsheetId=spreadsheet_id) → sheets list
GOOGLESHEETS_VALUES_GET(spreadsheetId, range="Sheet1!A1:Z5") → peek at structure
```

**Identify:**
- Header row (column names)
- Data types: numeric, categorical, date/time
- Number of columns and rows
- What makes sense as X-axis vs Y-axis

## Step 2: Select Chart Type

| Data Pattern | Best Chart | Why |
|-------------|-----------|-----|
| Categories + values | `BAR` or `COLUMN` | Compare quantities across categories |
| Time series | `LINE` or `AREA` | Show trends over time |
| Parts of whole | `PIE` | Show proportions (≤7 categories) |
| Two numeric variables | `SCATTER` | Show correlation/distribution |
| Multiple metrics over time | `COMBO` | Lines + bars together |
| Distribution | `HISTOGRAM` | Show frequency distribution |
| Hierarchical | `TREEMAP` | Show nested proportions |

**Rules:**
- PIE charts: only for ≤7 categories, need exactly 2 columns (labels + values)
- LINE charts: best when X-axis is temporal
- BAR vs COLUMN: horizontal bars for long category names
- SCATTER: only when both axes are numeric

## Step 3: Determine Data Range

```
GOOGLESHEETS_GET_SPREADSHEET_INFO(spreadsheetId) → get sheet_id (numeric, NOT sheet name)
```

**Range rules:**
- Use A1 notation: `'Sheet1!A1:C20'`
- First column = domain (labels/categories)
- Remaining columns = data series
- Include headers: they become legend labels
- Single contiguous range only (no comma-separated ranges)

## Step 4: Create the Chart

```
GOOGLESHEETS_CREATE_CHART(
  spreadsheet_id="...",
  sheet_id=0,                    # Numeric sheet ID, NOT name
  chart_type="BAR",
  data_range="Sheet1!A1:C10",
  title="Sales by Region",
  x_axis_title="Region",
  y_axis_title="Revenue ($)",
  legend_position="BOTTOM_LEGEND"
)
```

**Chart type options:** BAR, LINE, PIE, COLUMN, AREA, SCATTER, COMBO, STEPPED_AREA, HISTOGRAM, BUBBLE, CANDLESTICK, TREEMAP, WATERFALL, ORG, SCORECARD

## Step 5: Present Insights

Don't just create the chart — tell the user what it shows:
```
Created: "Sales by Region" (Bar Chart)
  Key insights:
  - West region leads with $450K (38% of total)
  - East region grew 22% vs last quarter
  - South region underperforming at $120K
```

## Anti-Patterns
- Creating charts without reading data first
- Using sheet name instead of numeric sheet_id
- PIE chart with 15+ categories (unreadable)
- LINE chart for non-temporal categorical data
- Comma-separated ranges (not supported)
- Creating chart without providing insights
