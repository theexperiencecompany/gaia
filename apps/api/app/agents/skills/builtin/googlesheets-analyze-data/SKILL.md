---
name: googlesheets-analyze-data
description: Analyze spreadsheet data intelligently - understand structure, choose right analysis tool (SQL/pivot/chart), apply formatting, present insights.
target: googlesheets_agent
---

# Google Sheets Analyze Data

## When to Use
- User asks to "analyze this spreadsheet" or "summarize the numbers"
- User wants a "pivot table" or "chart"
- User asks to "highlight" or "format" data
- User wants "totals by category" or any aggregation
- User asks to set up "dropdowns" or "validation"

## Tools

### Discovery
- **GOOGLESHEETS_SEARCH_SPREADSHEETS** — Find spreadsheets by name
- **GOOGLESHEETS_GET_SPREADSHEET_INFO** — Get spreadsheet metadata
- **GOOGLESHEETS_GET_SHEET_NAMES** — List sheets within a spreadsheet
- **GOOGLESHEETS_VALUES_GET** — Read cell values and structure
- **GOOGLESHEETS_BATCH_GET** — Read multiple ranges at once

### Analysis
- **GOOGLESHEETS_EXECUTE_SQL** — Run SQL queries against sheet data
  - SELECT, WHERE, GROUP BY, ORDER BY, SUM, AVG, COUNT, etc.

### Visualization
- **GOOGLESHEETS_CUSTOM_CREATE_PIVOT_TABLE** — Summarize data by dimensions
  - rows: Grouping columns (e.g., ["Region", "Product"])
  - values: Aggregations [{column: "Sales", aggregation: "SUM"}]
- **GOOGLESHEETS_CUSTOM_CREATE_CHART** — Create visual charts
  - Types: BAR, LINE, PIE, COLUMN, AREA, SCATTER, COMBO

### Formatting
- **GOOGLESHEETS_CUSTOM_ADD_CONDITIONAL_FORMAT** — Visual rules
  - value_based: >, <, =, contains, between
  - color_scale: Gradient across range
  - custom_formula: Advanced rules
- **GOOGLESHEETS_CUSTOM_SET_DATA_VALIDATION** — Input restrictions
  - dropdown_list: List of allowed values
  - dropdown_range: Values from another range
  - number: Min/max constraints
  - date: Date restrictions
  - custom_formula: Advanced validation

### Sharing
- **GOOGLESHEETS_CUSTOM_SHARE_SPREADSHEET** — Share with users
  - recipients: Email list
  - role: reader, writer, commenter

## Workflow

### Step 1: Understand the Data (CRITICAL)

Before any analysis, read the data:

```
GOOGLESHEETS_SEARCH_SPREADSHEETS(query="sales data")
```
```
GOOGLESHEETS_GET_SHEET_NAMES(spreadsheet_id="...")
```
```
GOOGLESHEETS_VALUES_GET(
    spreadsheet_id="...",
    range="Sheet1!A1:Z5"
)
```

Study the results to understand:
- Column headers and their meaning
- Data types (numbers, dates, text, categories)
- Number of rows (to gauge dataset size)
- Any patterns or anomalies

### Step 2: Choose the Right Analysis Tool

| Need | Tool |
|------|------|
| Simple aggregation (totals, averages) | EXECUTE_SQL |
| Cross-dimensional summary | CUSTOM_CREATE_PIVOT_TABLE |
| Visual patterns and trends | CUSTOM_CREATE_CHART |
| Highlight specific values | CUSTOM_ADD_CONDITIONAL_FORMAT |
| Restrict input options | CUSTOM_SET_DATA_VALIDATION |

### Step 3: Execute Analysis

**SQL Query Example:**
```
GOOGLESHEETS_EXECUTE_SQL(
    spreadsheet_id="...",
    query="SELECT Category, SUM(Amount), AVG(Amount) FROM Sheet1 GROUP BY Category ORDER BY SUM(Amount) DESC"
)
```

**Pivot Table Example:**
```
GOOGLESHEETS_CUSTOM_CREATE_PIVOT_TABLE(
    spreadsheet_id="...",
    source_sheet="Sales",
    rows=["Region", "Product"],
    values=[
        {"column": "Revenue", "aggregation": "SUM"},
        {"column": "Orders", "aggregation": "COUNT"}
    ]
)
```

**Chart Example:**
```
GOOGLESHEETS_CUSTOM_CREATE_CHART(
    spreadsheet_id="...",
    sheet_name="Sales",
    chart_type="BAR",
    title="Revenue by Region"
)
```

### Step 4: Apply Visual Formatting

**Conditional formatting:**
```
GOOGLESHEETS_CUSTOM_ADD_CONDITIONAL_FORMAT(
    spreadsheet_id="...",
    sheet_name="Sales",
    range="D2:D100",
    condition="greater_than",
    condition_values=["1000"],
    background_color="#4CAF50"
)
```

**Data validation (dropdowns):**
```
GOOGLESHEETS_CUSTOM_SET_DATA_VALIDATION(
    spreadsheet_id="...",
    sheet_name="Tracker",
    range="B2:B100",
    validation_type="dropdown_list",
    values=["High", "Medium", "Low"]
)
```

### Step 5: Present Insights

Don't just return raw data — interpret it:
- "Total revenue is $X, with Region Y contributing 45%"
- "The top 3 categories account for 80% of sales"
- "There's a clear upward trend from Q1 to Q3"

Then offer: "Want me to create a chart to visualize this?"

### Step 6: Range Notation Reference

- Basic: `Sheet1!A1:B10`
- Entire column: `Sheet1!A:A`
- Entire row: `Sheet1!1:1`
- Names with spaces: `'My Sheet'!A1:B10`
- Always include sheet name in multi-sheet spreadsheets

## Important Rules
1. **Understand data first** — Always read structure before analyzing
2. **Choose right tool** — SQL for queries, pivot for summaries, charts for visuals
3. **Interpret results** — Present insights, not just raw numbers
4. **Offer visualizations** — After analysis, suggest charts when appropriate
5. **Respect data** — Don't modify source data unless asked; create new sheets for analysis
6. **Destructive actions need consent** — Deleting sheets, clearing ranges, overwriting data
