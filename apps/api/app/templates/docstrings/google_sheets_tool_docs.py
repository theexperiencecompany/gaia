"""Docstrings for Google Sheets custom tools."""

CUSTOM_SHARE_SPREADSHEET_DOC = """
Share a Google Spreadsheet with one or more recipients in a single operation.

Use this tool when the user wants to:
- Share a spreadsheet with multiple people at once
- Collaborate on a spreadsheet with colleagues
- Grant different access levels (reader, writer, commenter)
- Share with a team or group of people

Parameters:
- spreadsheet_id (str): The unique identifier of the spreadsheet to share
- recipients (list): List of recipients, each containing:
  - email (str): Email address of the person to share with
  - role (str): Permission level - "reader", "writer", or "commenter" (default: "writer")
  - send_notification (bool): Whether to send email notification (default: True)

Returns:
- success: Whether all shares were successful
- spreadsheet_id: Unique identifier of the shared spreadsheet
- url: Direct link to the spreadsheet
- shared: List of successfully shared recipients with permission IDs
- errors: List of any failed shares with error details
- total_shared: Count of successful shares
- total_failed: Count of failed shares

Example usage:
- "Share my budget spreadsheet with john@example.com and jane@example.com as writers"
- "Give read access to this spreadsheet to the finance team"
- "Share the data with alice@company.com as reader and bob@company.com as commenter"
"""

CUSTOM_CREATE_PIVOT_TABLE_DOC = """
Create a pivot table from spreadsheet data with a simplified interface.

Use this tool when the user wants to:
- Summarize large datasets with groupings
- Create cross-tabulation reports
- Calculate aggregates (sum, count, average) by category
- Build dynamic reports from raw data

Parameters:
- spreadsheet_id (str): ID of the spreadsheet
- source_sheet_name (str): Name of the sheet containing source data
- source_range (str, optional): Range within source sheet (e.g., 'A1:E100'). Omit for entire sheet.
- destination_sheet_name (str): Sheet where pivot table will be placed
- destination_cell (str): Cell where pivot starts (default: 'A1')
- rows (list): Column header names to use as row groupings
- columns (list): Column header names for column groupings (optional)
- values (list): Value fields with aggregation, each containing:
  - column (str): Column header name to aggregate
  - aggregation (str): Function - "SUM", "COUNT", "AVERAGE", "MAX", "MIN", "COUNTA"
  - name (str, optional): Custom display name

Returns:
- success: Whether the pivot table was created
- spreadsheet_id: Spreadsheet identifier
- url: Direct link to the spreadsheet
- pivot_sheet: Sheet containing the pivot table
- source_range: Source data range used

Example usage:
- "Create a pivot table showing total sales by region and product category"
- "Summarize the expenses data by department with monthly columns"
- "Make a pivot table from Sheet1 data grouped by Status showing count of items"
"""

CUSTOM_SET_DATA_VALIDATION_DOC = """
Add data validation rules to cells, including dropdown lists.

Use this tool when the user wants to:
- Create dropdown menus in cells
- Restrict input to specific values
- Validate numbers within a range
- Enforce date constraints
- Apply custom formula validation

Parameters:
- spreadsheet_id (str): ID of the spreadsheet
- sheet_name (str): Name of the sheet
- range (str): Range to apply validation (e.g., 'A2:A100')
- validation_type (str): Type of validation:
  - "dropdown_list": Fixed list of allowed values
  - "dropdown_range": Dropdown from another range
  - "number": Number within min/max range
  - "date": Date within min/max range
  - "custom_formula": Custom formula validation
- values (list): Allowed values for dropdown_list type
- source_range (str): Source range for dropdown_range (e.g., 'Sheet2!A:A')
- min_value, max_value: Bounds for number/date validation
- formula (str): Custom formula for custom_formula type
- show_dropdown (bool): Show dropdown arrow (default: True)
- input_message (str): Help message when cell selected
- strict (bool): Reject invalid input (default: True)

Returns:
- success: Whether validation was applied
- spreadsheet_id: Spreadsheet identifier
- url: Direct link to the spreadsheet
- range_applied: Range where validation was set
- validation_type: Type of validation applied

Example usage:
- "Add a dropdown with options High, Medium, Low to column B"
- "Make column A only accept numbers between 1 and 100"
- "Create a dropdown in D2:D50 that uses values from the Categories sheet"
"""

CUSTOM_ADD_CONDITIONAL_FORMAT_DOC = """
Apply conditional formatting rules to highlight cells based on values.

Use this tool when the user wants to:
- Highlight cells above/below thresholds
- Apply color gradients to data ranges
- Format cells containing specific text
- Use custom formulas for conditional styling
- Visually differentiate data patterns

Parameters:
- spreadsheet_id (str): ID of the spreadsheet
- sheet_name (str): Name of the sheet
- range (str): Range to format (e.g., 'B2:B100')
- format_type (str): Type of formatting:
  - "value_based": Format based on cell value conditions
  - "color_scale": Gradient coloring (min to max)
  - "custom_formula": Formula-based formatting
- condition (str): For value_based - "greater_than", "less_than", "equal_to", 
  "not_equal_to", "contains", "not_contains", "between", "is_empty", "is_not_empty"
- condition_values (list): Values for comparison
- background_color (str): Background color in hex (e.g., '#FF0000')
- text_color (str): Text color in hex
- bold (bool): Make text bold
- italic (bool): Make text italic
- min_color, mid_color, max_color (str): Colors for color_scale gradient
- formula (str): Custom formula for custom_formula type

Returns:
- success: Whether formatting was applied
- spreadsheet_id: Spreadsheet identifier
- url: Direct link to the spreadsheet
- range_applied: Range where formatting was set
- rule_index: Index of the created rule

Example usage:
- "Highlight cells in column C red if value is greater than 100"
- "Apply a green-yellow-red color scale to the Sales column"
- "Make cells bold if they contain the word 'Urgent'"
- "Format rows where status is 'Complete' with green background"
"""

CUSTOM_CREATE_CHART_DOC = """
Create a chart from spreadsheet data with visual customization.

Use this tool when the user wants to:
- Visualize data as charts or graphs
- Create bar, line, pie, or other chart types
- Add charts to their spreadsheet
- Build data dashboards

Parameters:
- spreadsheet_id (str): ID of the spreadsheet
- sheet_name (str): Name of sheet with source data
- data_range (str): Range containing chart data (e.g., 'A1:B10')
- chart_type (str): Type of chart - "BAR", "LINE", "PIE", "COLUMN", "AREA", "SCATTER", "COMBO"
- title (str, optional): Chart title
- x_axis_title (str, optional): X axis label
- y_axis_title (str, optional): Y axis label
- destination_sheet_name (str, optional): Sheet for chart (defaults to source)
- anchor_cell (str): Cell for chart position (default: 'E1')
- width (int): Chart width in pixels (default: 600)
- height (int): Chart height in pixels (default: 400)
- legend_position (str): Legend position - "BOTTOM_LEGEND", "LEFT_LEGEND", 
  "RIGHT_LEGEND", "TOP_LEGEND", "NO_LEGEND"

Returns:
- success: Whether the chart was created
- spreadsheet_id: Spreadsheet identifier
- url: Direct link to the spreadsheet
- chart_id: ID of the created chart
- chart_type: Type of chart created

Example usage:
- "Create a bar chart from the sales data in A1:B12"
- "Make a pie chart showing expense distribution"
- "Add a line chart with title 'Monthly Revenue' from the data"
- "Create a column chart comparing Q1 vs Q2 sales"
"""
