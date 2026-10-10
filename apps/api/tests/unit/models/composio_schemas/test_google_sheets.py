"""Unit tests for app/models/composio_schemas/google_sheets.py."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.google_sheets import (
    GoogleSheetsNewRowPayload,
    GoogleSheetsNewSheetAddedPayload,
)


class TestGoogleSheetsNewRowPayload:
    def test_valid_minimal(self):
        m = GoogleSheetsNewRowPayload()
        assert m.row_data is None
        assert m.row_number is None

    def test_valid_full(self):
        m = GoogleSheetsNewRowPayload(
            detected_at="2025-01-01T00:00:00Z",
            row_data=["a", "b", "c"],
            row_number=3,
            sheet_name="Sheet1",
            spreadsheet_id="spr123",
        )
        assert m.row_data == ["a", "b", "c"]
        assert m.row_number == 3
        assert m.spreadsheet_id == "spr123"

    def test_wrong_type_row_data(self):
        with pytest.raises(ValidationError):
            GoogleSheetsNewRowPayload(row_data=[1, 2])

    def test_wrong_type_row_number(self):
        with pytest.raises(ValidationError):
            GoogleSheetsNewRowPayload(row_number="three")


class TestGoogleSheetsNewSheetAddedPayload:
    def test_valid_minimal(self):
        m = GoogleSheetsNewSheetAddedPayload()
        assert m.sheet_name is None
        assert m.spreadsheet_id is None

    def test_valid_full(self):
        m = GoogleSheetsNewSheetAddedPayload(
            detected_at="2025-01-01T00:00:00Z",
            sheet_name="Sheet1",
            spreadsheet_id="spr123",
        )
        assert m.sheet_name == "Sheet1"
        assert m.spreadsheet_id == "spr123"


# ---------------------------------------------------------------------------
# linear trigger payloads
# ---------------------------------------------------------------------------
