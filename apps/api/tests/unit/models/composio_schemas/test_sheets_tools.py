"""Unit tests for the Composio Google Sheets tools schemas (sheets_tools.py)."""

from app.models.composio_schemas.sheets_tools import GoogleSheetsSearchSpreadsheetsInput


class TestGoogleSheetsSearchSpreadsheetsInput:
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
