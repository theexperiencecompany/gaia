"""
Google Sheets tool schemas.

Reference: node_modules/@composio/core/generated/googlesheets.ts

Note: All Composio tool responses are wrapped in ToolExecutionResponse with
`data`, `error`, `successful` keys. These models represent the INNER data structure.
"""

from pydantic import BaseModel, ConfigDict, Field


class GoogleSheetsSearchSpreadsheetsInput(BaseModel):
    """Input for GOOGLESHEETS_SEARCH_SPREADSHEETS."""

    created_after: str | None = Field(
        None, description="Created after timestamp", alias="createdAfter"
    )
    include_trashed: bool | None = Field(
        None, description="Include trashed items", alias="includeTrashed"
    )
    max_results: int | None = Field(10, description="Max results", alias="maxResults")
    modified_after: str | None = Field(
        None, description="Modified after timestamp", alias="modifiedAfter"
    )
    order_by: str | None = Field(None, description="Sort order", alias="orderBy")


class GoogleSheetsGetSheetNamesInput(BaseModel):
    """Input for GOOGLESHEETS_GET_SHEET_NAMES."""

    spreadsheet_id: str | None = Field(None, description="Spreadsheet ID")


class GoogleSheetsOwner(BaseModel):
    """Spreadsheet owner info."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    me: bool | None = None
    kind: str | None = None
    displayName: str | None = None
    emailAddress: str | None = None


class GoogleSheetsSpreadsheet(BaseModel):
    """Google Sheets spreadsheet model."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str | None = None
    name: str | None = None
    mimeType: str | None = None
    shared: bool | None = None
    owners: list[GoogleSheetsOwner] = Field(default_factory=list)


class GoogleSheetsSearchSpreadsheetsData(BaseModel):
    """Data inside ToolExecutionResponse.data for GOOGLESHEETS_SEARCH_SPREADSHEETS."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    spreadsheets: list[GoogleSheetsSpreadsheet] = Field(default_factory=list)


class GoogleSheetsGetSheetNamesData(BaseModel):
    """Data inside ToolExecutionResponse.data for GOOGLESHEETS_GET_SHEET_NAMES."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    sheet_names: list[str] = Field(default_factory=list)
