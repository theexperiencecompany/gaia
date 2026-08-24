"""Unit tests for app/models/composio_schemas/sheets_tools.py."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.sheets_tools import (
    GoogleSheetsGetSheetNamesData,
    GoogleSheetsGetSheetNamesInput,
    GoogleSheetsSearchSpreadsheetsData,
    GoogleSheetsSearchSpreadsheetsInput,
    GoogleSheetsSpreadsheet,
)


class TestGoogleSheetsSearchSpreadsheetsInput:
    def test_defaults(self):
        m = GoogleSheetsSearchSpreadsheetsInput()
        assert m.max_results == 10
        assert m.created_after is None
        assert m.include_trashed is None
        assert m.modified_after is None
        assert m.order_by is None

    def test_valid_full_with_aliases(self):
        m = GoogleSheetsSearchSpreadsheetsInput(
            createdAfter="2024-01-01",
            includeTrashed=True,
            maxResults=25,
            modifiedAfter="2024-02-01",
            orderBy="modifiedTime desc",
        )
        assert m.created_after == "2024-01-01"
        assert m.include_trashed is True
        assert m.max_results == 25
        assert m.modified_after == "2024-02-01"
        assert m.order_by == "modifiedTime desc"

    def test_serializes_with_aliases(self):
        m = GoogleSheetsSearchSpreadsheetsInput(maxResults=5)
        dumped = m.model_dump(by_alias=True)
        assert dumped == {
            "createdAfter": None,
            "includeTrashed": None,
            "maxResults": 5,
            "modifiedAfter": None,
            "orderBy": None,
        }

    def test_field_name_kwargs_are_ignored(self):
        # No populate_by_name: field-name kwargs are silently dropped,
        # so the declared values never land on the model.
        m = GoogleSheetsSearchSpreadsheetsInput(created_after="2024-01-01")
        assert m.created_after is None

    def test_round_trip_model_dump(self):
        m = GoogleSheetsSearchSpreadsheetsInput.model_validate(
            GoogleSheetsSearchSpreadsheetsInput(maxResults=12).model_dump(by_alias=True)
        )
        assert m.max_results == 12

    def test_wrong_type_max_results(self):
        with pytest.raises(ValidationError):
            GoogleSheetsSearchSpreadsheetsInput(maxResults="twenty-five")


class TestGoogleSheetsGetSheetNamesInput:
    def test_valid_minimal(self):
        m = GoogleSheetsGetSheetNamesInput()
        assert m.spreadsheet_id is None

    def test_valid_full(self):
        m = GoogleSheetsGetSheetNamesInput(spreadsheet_id="spr123")
        assert m.spreadsheet_id == "spr123"

    def test_wrong_type(self):
        with pytest.raises(ValidationError):
            GoogleSheetsGetSheetNamesInput(spreadsheet_id=123)


class TestGoogleSheetsSpreadsheet:
    def test_valid_minimal(self):
        m = GoogleSheetsSpreadsheet()
        assert m.id is None
        assert m.owners == []

    def test_valid_full(self):
        m = GoogleSheetsSpreadsheet(
            id="spr123",
            name="Sheet",
            mimeType="application/vnd.google-apps.spreadsheet",
            shared=False,
            owners=[
                {
                    "me": True,
                    "kind": "drive#user",
                    "displayName": "Alice",
                    "emailAddress": "a@b.com",
                }
            ],
        )
        assert m.id == "spr123"
        assert m.owners[0].me is True
        assert m.owners[0].emailAddress == "a@b.com"

    def test_extra_fields_ignored(self):
        m = GoogleSheetsSpreadsheet(id="spr123", unknown="dropped")
        assert not hasattr(m, "unknown")

    def test_wrong_type_owners(self):
        with pytest.raises(ValidationError):
            GoogleSheetsSpreadsheet(owners=["not-a-owner"])


class TestGoogleSheetsSearchSpreadsheetsData:
    def test_defaults(self):
        m = GoogleSheetsSearchSpreadsheetsData()
        assert m.spreadsheets == []

    def test_valid_full(self):
        m = GoogleSheetsSearchSpreadsheetsData(
            spreadsheets=[{"id": "spr1", "name": "A"}, {"id": "spr2", "name": "B"}]
        )
        assert isinstance(m.spreadsheets[0], GoogleSheetsSpreadsheet)
        assert [s.id for s in m.spreadsheets] == ["spr1", "spr2"]

    def test_extra_fields_ignored(self):
        m = GoogleSheetsSearchSpreadsheetsData(spreadsheets=[], extra="dropped")
        assert not hasattr(m, "extra")


class TestGoogleSheetsGetSheetNamesData:
    def test_defaults(self):
        m = GoogleSheetsGetSheetNamesData()
        assert m.sheet_names == []

    def test_valid_full(self):
        m = GoogleSheetsGetSheetNamesData(sheet_names=["Sheet1", "Sheet2"])
        assert m.sheet_names == ["Sheet1", "Sheet2"]

    def test_extra_fields_ignored(self):
        m = GoogleSheetsGetSheetNamesData(sheet_names=[], extra="dropped")
        assert not hasattr(m, "extra")

    def test_wrong_type_sheet_names(self):
        with pytest.raises(ValidationError):
            GoogleSheetsGetSheetNamesData(sheet_names=[1])


# ---------------------------------------------------------------------------
# slack trigger payloads
# ---------------------------------------------------------------------------
