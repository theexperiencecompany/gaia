"""
Google Sheets trigger payload models.

Reference: node_modules/@composio/core/generated/googlesheets.ts
"""

from pydantic import BaseModel, Field


class GoogleSheetsNewRowPayload(BaseModel):
    """Payload for GOOGLESHEETS_NEW_ROWS_TRIGGER."""

    detected_at: str | None = Field(
        None, description="ISO timestamp when row was detected"
    )
    row_data: list[str] | None = Field(None, description="Row data as list of strings")
    row_number: int | None = Field(None, description="Row number (1-indexed)")
    sheet_name: str | None = Field(None, description="Sheet name")
    spreadsheet_id: str | None = Field(None, description="Spreadsheet ID")


class GoogleSheetsNewSheetAddedPayload(BaseModel):
    """Payload for GOOGLESHEETS_NEW_SHEET_ADDED_TRIGGER."""

    detected_at: str | None = Field(None, description="ISO timestamp")
    sheet_name: str | None = Field(None, description="Sheet name")
    spreadsheet_id: str | None = Field(None, description="Spreadsheet ID")
