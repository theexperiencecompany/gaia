"""Pydantic models for Google Sheets custom tools."""

from typing import Literal

from pydantic import BaseModel, Field


class ShareRecipient(BaseModel):
    """Single recipient for spreadsheet sharing."""

    email: str = Field(..., description="Email address to share with")
    role: Literal["reader", "writer", "commenter"] = Field(
        "writer",
        description="Permission level: 'reader', 'writer', or 'commenter'",
    )
    send_notification: bool = Field(True, description="Whether to send email notification")


class ShareSpreadsheetInput(BaseModel):
    """Input for sharing a Google Spreadsheet with multiple recipients."""

    spreadsheet_id: str = Field(..., description="ID of the spreadsheet to share")
    recipients: list[ShareRecipient] = Field(
        ...,
        description="List of recipients to share with",
        min_length=1,
    )


class PivotValue(BaseModel):
    """Configuration for a value field in a pivot table."""

    column: str = Field(..., description="Column header name to aggregate")
    aggregation: str | None = Field(
        "SUM", description="Aggregation function (SUM, AVERAGE, COUNT, MAX, MIN)"
    )
    name: str | None = Field(None, description="Custom display name for this value (optional)")


class CreatePivotTableInput(BaseModel):
    """Input for creating a pivot table in a spreadsheet."""

    spreadsheet_id: str = Field(..., description="ID of the spreadsheet")
    source_sheet_name: str = Field(..., description="Name of the sheet containing source data")
    source_range: str | None = Field(
        None,
        description="Range within source sheet (e.g., 'A1:E100'). If omitted, uses entire sheet.",
    )
    destination_sheet_name: str = Field(
        ..., description="Name of the sheet where pivot table will be placed"
    )
    destination_cell: str = Field("A1", description="Cell where pivot table starts (e.g., 'A1')")
    rows: list[str] = Field(
        ...,
        description="Column header names to use as row groupings",
        min_length=1,
    )
    columns: list[str] = Field(
        default=[],
        description="Column header names to use as column groupings (optional)",
    )
    values: list[PivotValue] = Field(
        ...,
        description="Value fields with aggregation functions",
        min_length=1,
    )


class DataValidationInput(BaseModel):
    """Input for setting data validation rules on a range."""

    spreadsheet_id: str = Field(..., description="ID of the spreadsheet")
    sheet_name: str = Field(..., description="Name of the sheet")
    range: str = Field(..., description="Range to apply validation (e.g., 'A2:A100')")
    validation_type: Literal[
        "dropdown_list", "dropdown_range", "number", "date", "custom_formula"
    ] = Field(..., description="Type of validation to apply")

    # For dropdown_list: explicit values
    values: list[str] | None = Field(
        None, description="List of allowed values for dropdown_list type"
    )

    # For dropdown_range: reference to another range
    source_range: str | None = Field(
        None,
        description="Source range for dropdown values (e.g., 'Sheet2!A:A') for dropdown_range type",
    )

    # For number/date validation
    min_value: str | None = Field(
        None, description="Minimum allowed value for number/date validation"
    )
    max_value: str | None = Field(
        None, description="Maximum allowed value for number/date validation"
    )

    # For custom_formula
    formula: str | None = Field(
        None, description="Custom formula for validation (e.g., '=LEN(A1)<=50')"
    )

    # Common options
    show_dropdown: bool = Field(
        True, description="Show dropdown arrow in cell (for dropdown types)"
    )
    input_message: str | None = Field(None, description="Help message shown when cell is selected")
    strict: bool = Field(True, description="Reject invalid input if True, warn only if False")


class ConditionalFormatInput(BaseModel):
    """Input for adding conditional formatting rules."""

    spreadsheet_id: str = Field(..., description="ID of the spreadsheet")
    sheet_name: str = Field(..., description="Name of the sheet")
    range: str = Field(..., description="Range to apply formatting (e.g., 'B2:B100')")
    format_type: Literal["value_based", "color_scale", "custom_formula"] = Field(
        ..., description="Type of conditional formatting"
    )

    # For value_based formatting
    condition: (
        Literal[
            "greater_than",
            "less_than",
            "equal_to",
            "not_equal_to",
            "contains",
            "not_contains",
            "between",
            "is_empty",
            "is_not_empty",
        ]
        | None
    ) = Field(None, description="Condition type for value_based formatting")
    condition_values: list[str] | None = Field(
        None,
        description="Values for comparison (1 value for most conditions, 2 for 'between')",
    )

    # Format to apply for value_based and custom_formula
    background_color: str | None = Field(
        None, description="Background color in hex (e.g., '#FF0000' for red)"
    )
    text_color: str | None = Field(
        None, description="Text color in hex (e.g., '#FFFFFF' for white)"
    )
    bold: bool | None = Field(None, description="Make text bold")
    italic: bool | None = Field(None, description="Make text italic")

    # For color_scale gradient
    min_color: str | None = Field(None, description="Color for minimum values in color_scale (hex)")
    mid_color: str | None = Field(
        None, description="Color for middle values in color_scale (hex, optional)"
    )
    max_color: str | None = Field(None, description="Color for maximum values in color_scale (hex)")

    # For custom_formula
    formula: str | None = Field(
        None,
        description="Custom formula that evaluates to TRUE/FALSE (e.g., '=A1>100')",
    )


class ChartInput(BaseModel):
    """Input for creating a chart in a spreadsheet."""

    spreadsheet_id: str = Field(..., description="ID of the spreadsheet")
    sheet_name: str = Field(..., description="Name of the sheet containing source data")
    data_range: str = Field(..., description="Range containing chart data (e.g., 'A1:B10')")
    chart_type: Literal["BAR", "LINE", "PIE", "COLUMN", "AREA", "SCATTER", "COMBO"] = Field(
        ..., description="Type of chart to create"
    )
    title: str | None = Field(None, description="Chart title")
    x_axis_title: str | None = Field(None, description="Title for X axis")
    y_axis_title: str | None = Field(None, description="Title for Y axis")
    destination_sheet_name: str | None = Field(
        None,
        description="Sheet where chart will be placed (defaults to source sheet)",
    )
    anchor_cell: str = Field("E1", description="Cell where top-left of chart anchors (e.g., 'E1')")
    width: int = Field(600, description="Chart width in pixels", ge=100, le=2000)
    height: int = Field(400, description="Chart height in pixels", ge=100, le=2000)
    legend_position: Literal[
        "BOTTOM_LEGEND", "LEFT_LEGEND", "RIGHT_LEGEND", "TOP_LEGEND", "NO_LEGEND"
    ] = Field("BOTTOM_LEGEND", description="Position of chart legend")
