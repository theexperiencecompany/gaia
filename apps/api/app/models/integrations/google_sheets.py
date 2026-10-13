"""Google Sheets API v4 payloads the Sheets tool sends and reads.

Request models mirror the spreadsheets.batchUpdate request union one level
at a time and are dumped with exclude_none=True at the send site, so an
unset optional key is omitted exactly as the hand-built dicts omitted it.
Reference: https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/request
"""

from pydantic import BaseModel, ConfigDict, Field


class GoogleSheetsColor(BaseModel):
    """A Sheets ``Color`` — channels as 0-1 floats."""

    red: float
    green: float
    blue: float


class GoogleSheetsGridRange(BaseModel):
    """A Sheets ``GridRange``.

    Every bound is optional: an A1 reference may leave rows or columns open
    ('A:C'), and Sheets reads an absent bound as unbounded — omitting it is what
    keeps a column range from collapsing onto row 1. ``parse_a1_range`` never
    sets ``sheetId`` (A1 notation carries a sheet *name*); callers resolve the id.
    """

    sheetId: int | None = None
    startRowIndex: int | None = None
    endRowIndex: int | None = None
    startColumnIndex: int | None = None
    endColumnIndex: int | None = None


class GoogleSheetsGridCoordinate(BaseModel):
    """A Sheets ``GridCoordinate`` — one cell on one sheet."""

    sheetId: int
    rowIndex: int
    columnIndex: int


class GoogleSheetsConditionValue(BaseModel):
    """A ``ConditionValue`` given as a user-entered string."""

    userEnteredValue: str


class GoogleSheetsBooleanCondition(BaseModel):
    """A ``BooleanCondition``; ``values`` is absent for BLANK / NOT_BLANK."""

    type: str
    values: list[GoogleSheetsConditionValue] | None = None


class GoogleSheetsPivotGroup(BaseModel):
    """A ``PivotGroup`` (row or column grouping)."""

    sourceColumnOffset: int
    sortOrder: str
    showTotals: bool


class GoogleSheetsPivotValue(BaseModel):
    """A ``PivotValue`` aggregation."""

    sourceColumnOffset: int
    summarizeFunction: str
    name: str | None = None


class GoogleSheetsPivotTable(BaseModel):
    """A ``PivotTable``; ``columns`` is omitted when there are no column groupings."""

    source: GoogleSheetsGridRange
    rows: list[GoogleSheetsPivotGroup]
    values: list[GoogleSheetsPivotValue]
    columns: list[GoogleSheetsPivotGroup] | None = None


class GoogleSheetsCellData(BaseModel):
    """The one ``CellData`` shape GAIA writes: a pivot table."""

    pivotTable: GoogleSheetsPivotTable


class GoogleSheetsRowData(BaseModel):
    """A ``RowData``."""

    values: list[GoogleSheetsCellData]


class GoogleSheetsUpdateCellsRequest(BaseModel):
    """An ``UpdateCellsRequest``."""

    rows: list[GoogleSheetsRowData]
    start: GoogleSheetsGridCoordinate
    fields: str


class GoogleSheetsDataValidationRule(BaseModel):
    """A ``DataValidationRule``."""

    condition: GoogleSheetsBooleanCondition
    strict: bool
    showCustomUi: bool
    inputMessage: str | None = None


class GoogleSheetsSetDataValidationRequest(BaseModel):
    """A ``SetDataValidationRequest``."""

    range: GoogleSheetsGridRange
    rule: GoogleSheetsDataValidationRule


class GoogleSheetsTextFormat(BaseModel):
    """A ``TextFormat``; only the keys the user asked for are sent."""

    foregroundColor: GoogleSheetsColor | None = None
    bold: bool | None = None
    italic: bool | None = None


class GoogleSheetsCellFormat(BaseModel):
    """A ``CellFormat``."""

    backgroundColor: GoogleSheetsColor | None = None
    textFormat: GoogleSheetsTextFormat | None = None


class GoogleSheetsBooleanRule(BaseModel):
    """A ``BooleanRule``."""

    condition: GoogleSheetsBooleanCondition
    format: GoogleSheetsCellFormat


class GoogleSheetsInterpolationPoint(BaseModel):
    """An ``InterpolationPoint``; ``value`` is only meaningful for PERCENTILE/NUMBER."""

    type: str
    color: GoogleSheetsColor
    value: str | None = None


class GoogleSheetsGradientRule(BaseModel):
    """A ``GradientRule``; ``midpoint`` is optional."""

    minpoint: GoogleSheetsInterpolationPoint
    maxpoint: GoogleSheetsInterpolationPoint
    midpoint: GoogleSheetsInterpolationPoint | None = None


class GoogleSheetsConditionalFormatRule(BaseModel):
    """A ``ConditionalFormatRule`` — exactly one of ``booleanRule`` / ``gradientRule``."""

    ranges: list[GoogleSheetsGridRange]
    booleanRule: GoogleSheetsBooleanRule | None = None
    gradientRule: GoogleSheetsGradientRule | None = None


class GoogleSheetsAddConditionalFormatRuleRequest(BaseModel):
    """An ``AddConditionalFormatRuleRequest``."""

    rule: GoogleSheetsConditionalFormatRule
    index: int


class GoogleSheetsChartSourceRange(BaseModel):
    """A ``ChartSourceRange``."""

    sources: list[GoogleSheetsGridRange]


class GoogleSheetsChartData(BaseModel):
    """A ``ChartData`` backed by a source range."""

    sourceRange: GoogleSheetsChartSourceRange


class GoogleSheetsBasicChartDomain(BaseModel):
    """A ``BasicChartDomain``."""

    domain: GoogleSheetsChartData


class GoogleSheetsBasicChartSeries(BaseModel):
    """A ``BasicChartSeries``."""

    series: GoogleSheetsChartData
    targetAxis: str


class GoogleSheetsBasicChartAxis(BaseModel):
    """A ``BasicChartAxis``."""

    position: str
    title: str


class GoogleSheetsBasicChartSpec(BaseModel):
    """A ``BasicChartSpec``; ``axis`` is omitted when no axis title was given."""

    chartType: str
    legendPosition: str
    domains: list[GoogleSheetsBasicChartDomain]
    series: list[GoogleSheetsBasicChartSeries]
    headerCount: int
    axis: list[GoogleSheetsBasicChartAxis] | None = None


class GoogleSheetsPieChartSpec(BaseModel):
    """A ``PieChartSpec``."""

    legendPosition: str
    domain: GoogleSheetsChartData
    series: GoogleSheetsChartData


class GoogleSheetsChartSpec(BaseModel):
    """A ``ChartSpec`` — exactly one of ``basicChart`` / ``pieChart``."""

    basicChart: GoogleSheetsBasicChartSpec | None = None
    pieChart: GoogleSheetsPieChartSpec | None = None
    title: str | None = None


class GoogleSheetsOverlayPosition(BaseModel):
    """An ``OverlayPosition``."""

    anchorCell: GoogleSheetsGridCoordinate
    widthPixels: int
    heightPixels: int


class GoogleSheetsEmbeddedObjectPosition(BaseModel):
    """An ``EmbeddedObjectPosition`` anchored on a cell."""

    overlayPosition: GoogleSheetsOverlayPosition


class GoogleSheetsEmbeddedChart(BaseModel):
    """An ``EmbeddedChart`` to add."""

    spec: GoogleSheetsChartSpec
    position: GoogleSheetsEmbeddedObjectPosition


class GoogleSheetsAddChartRequest(BaseModel):
    """An ``AddChartRequest``."""

    chart: GoogleSheetsEmbeddedChart


class GoogleSheetsRequest(BaseModel):
    """One ``Request`` of a batch update — exactly one kind is set."""

    updateCells: GoogleSheetsUpdateCellsRequest | None = None
    setDataValidation: GoogleSheetsSetDataValidationRequest | None = None
    addConditionalFormatRule: GoogleSheetsAddConditionalFormatRuleRequest | None = None
    addChart: GoogleSheetsAddChartRequest | None = None


class GoogleSheetsBatchUpdateRequest(BaseModel):
    """Body of ``POST /v4/spreadsheets/{id}:batchUpdate``."""

    requests: list[GoogleSheetsRequest]


class GoogleSheetsEmbeddedChartReply(BaseModel):
    """The ``EmbeddedChart`` Sheets returns for an added chart — only ``chartId`` is read."""

    model_config = ConfigDict(extra="ignore")

    chartId: int | None = None


class GoogleSheetsAddChartReply(BaseModel):
    """An ``AddChartResponse``."""

    model_config = ConfigDict(extra="ignore")

    chart: GoogleSheetsEmbeddedChartReply | None = None


class GoogleSheetsReply(BaseModel):
    """One ``Response`` of a batch update; ``addChart`` is set only for that request kind."""

    model_config = ConfigDict(extra="ignore")

    addChart: GoogleSheetsAddChartReply | None = None


class GoogleSheetsBatchUpdateResponse(BaseModel):
    """``BatchUpdateSpreadsheetResponse`` — ``replies`` is absent when nothing answered."""

    model_config = ConfigDict(extra="ignore")

    replies: list[GoogleSheetsReply] = Field(default_factory=list)


class GoogleSheetsSheetProperties(BaseModel):
    """``SheetProperties`` under the ``sheets.properties`` projection."""

    model_config = ConfigDict(extra="ignore")

    sheetId: int | None = None
    title: str | None = None


class GoogleSheetsSheet(BaseModel):
    """One ``Sheet`` of a spreadsheet; a malformed entry has no ``properties``."""

    model_config = ConfigDict(extra="ignore")

    properties: GoogleSheetsSheetProperties | None = None


class GoogleSheetsSpreadsheet(BaseModel):
    """``GET /v4/spreadsheets/{id}?fields=sheets.properties``."""

    model_config = ConfigDict(extra="ignore")

    sheets: list[GoogleSheetsSheet] = Field(default_factory=list)


class GoogleSheetsValueRange(BaseModel):
    """``GET /v4/spreadsheets/{id}/values/{range}``.

    ``values`` is absent on an empty sheet, and a cell is any JSON scalar — a
    numeric header comes back as a number, not a string.
    """

    model_config = ConfigDict(extra="ignore")

    values: list[list[str | int | float | bool | None]] | None = None
