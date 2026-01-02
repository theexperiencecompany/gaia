"""
Google Sheets custom tool tests using pytest.

Tests 5 sheets tools with self-contained fixtures:
- CUSTOM_SET_DATA_VALIDATION
- CUSTOM_ADD_CONDITIONAL_FORMAT
- CUSTOM_CREATE_CHART
- CUSTOM_CREATE_PIVOT_TABLE (skipped - requires specific headers)
- CUSTOM_SHARE_SPREADSHEET


Creates a temp spreadsheet via Google Drive, runs tests, then deletes it.

Usage:
    python -m tests.composio_tools.run_tests google_sheets
    pytest tests/composio_tools/test_google_sheets.py -v --user-id USER_ID
"""

from datetime import datetime
from typing import Any, Dict, Generator

import pytest

from tests.composio_tools.config_utils import get_integration_config
from tests.composio_tools.conftest import execute_tool


@pytest.fixture(scope="module")
def test_spreadsheet(composio_client, user_id) -> Generator[Dict[str, Any], None, None]:
    """
    Create a test spreadsheet with sample data.

    Creates spreadsheet using Google Drive, adds test data, yields info, then deletes.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title = f"[PYTEST] Test Spreadsheet {timestamp}"

    # Get share email from config if available
    config = get_integration_config("google_sheets")
    share_email = config.get("share_email")

    # Try to create a spreadsheet using GOOGLESHEETS_CREATE_SPREADSHEET
    try:
        create_result = execute_tool(
            composio_client,
            "GOOGLESHEETS_CREATE_GOOGLE_SHEET1",
            {"title": title},
            user_id,
        )
    except Exception as e:
        pytest.skip(
            f"Could not create test spreadsheet (check Google Sheets connection): {e}"
        )

    if not create_result.get("successful"):
        pytest.skip(f"Create spreadsheet failed: {create_result.get('error')}")

    data = create_result.get("data", {})
    # Handle potentially stringified data
    if isinstance(data, str):
        import json

        try:
            data = json.loads(data)
        except Exception:
            pass

    spreadsheet_id = (
        data.get("spreadsheetId") or data.get("id") or data.get("spreadsheet_id")
    )
    sheet_name = data.get("sheet_name", "Sheet1")  # Default sheet name

    if not spreadsheet_id:
        pytest.skip(f"Could not get spreadsheet ID from create response: {data}")

    # Add some test data using GOOGLESHEETS_BATCH_UPDATE
    try:
        execute_tool(
            composio_client,
            "GOOGLESHEETS_BATCH_UPDATE",
            {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sheet_name}!A1:D10",
                "values": [
                    ["Name", "Category", "Value", "Score"],
                    ["Item A", "Type 1", "100", "85"],
                    ["Item B", "Type 2", "200", "90"],
                    ["Item C", "Type 1", "150", "75"],
                    ["Item D", "Type 2", "175", "88"],
                    ["Item E", "Type 1", "125", "92"],
                    ["Item F", "Type 2", "225", "78"],
                    ["Item G", "Type 1", "180", "82"],
                    ["Item H", "Type 2", "195", "95"],
                    ["Item I", "Type 1", "160", "80"],
                ],
            },
            user_id,
        )
    except Exception as e:
        pytest.skip(f"Could not add test data (check Google Sheets connection): {e}")

    spreadsheet_info = {
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": sheet_name,
        "title": title,
        "share_email": share_email,
    }

    yield spreadsheet_info

    pass


class TestGoogleSheetsOperations:
    """Tests for Google Sheets custom tools using temp spreadsheet."""

    def test_set_data_validation(self, composio_client, user_id, test_spreadsheet):
        """Test CUSTOM_SET_DATA_VALIDATION adds dropdown validation."""
        result = execute_tool(
            composio_client,
            "GOOGLESHEETS_CUSTOM_SET_DATA_VALIDATION",
            {
                "spreadsheet_id": test_spreadsheet["spreadsheet_id"],
                "sheet_name": test_spreadsheet["sheet_name"],
                "range": "E1:E10",
                "validation_type": "dropdown_list",
                "values": ["Option A", "Option B", "Option C"],
                "strict": True,
                "show_dropdown": True,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

    def test_add_conditional_format(self, composio_client, user_id, test_spreadsheet):
        """Test CUSTOM_ADD_CONDITIONAL_FORMAT adds color scale."""
        result = execute_tool(
            composio_client,
            "GOOGLESHEETS_CUSTOM_ADD_CONDITIONAL_FORMAT",
            {
                "spreadsheet_id": test_spreadsheet["spreadsheet_id"],
                "sheet_name": test_spreadsheet["sheet_name"],
                "range": "C2:D10",
                "format_type": "color_scale",
                "min_color": "#FF0000",
                "mid_color": "#FFFF00",
                "max_color": "#00FF00",
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

    def test_create_chart(self, composio_client, user_id, test_spreadsheet):
        """Test CUSTOM_CREATE_CHART creates a bar chart."""
        result = execute_tool(
            composio_client,
            "GOOGLESHEETS_CUSTOM_CREATE_CHART",
            {
                "spreadsheet_id": test_spreadsheet["spreadsheet_id"],
                "sheet_name": test_spreadsheet["sheet_name"],
                "data_range": "A1:B10",
                "chart_type": "BAR",
                "title": "Test Chart",
                "anchor_cell": "F1",
                "width": 400,
                "height": 300,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

    def test_create_pivot_table(self, composio_client, user_id, test_spreadsheet):
        """Test CUSTOM_CREATE_PIVOT_TABLE creates a pivot table."""
        from app.models.google_sheets_models import CreatePivotTableInput

        try:
            args = {
                "spreadsheet_id": test_spreadsheet["spreadsheet_id"],
                "source_sheet_name": test_spreadsheet["sheet_name"],
                "source_range": "A1:D10",  # Includes headers
                "rows": ["Category"],
                "columns": ["Name"],
                "values": [{"column": "Value", "aggregation": "SUM"}],
                "destination_sheet_name": "Pivot Table",
                "destination_cell": "A1",
            }
            print(f"DEBUG: Pivot Table Input: {args}")
            # Verify payload strictly against model
            try:
                CreatePivotTableInput(**args)
            except Exception as e:
                pytest.fail(f"Local Validation Failed: {e}")

            result = execute_tool(
                composio_client,
                "GOOGLESHEETS_CUSTOM_CREATE_PIVOT_TABLE",
                args,
                user_id,
            )
        except Exception:
            # Pivot table might fail if "Pivot Table" sheet already exists or similar
            # But in a fresh sheet it should work.
            # Fallback for debugging if it fails
            pytest.fail("Failed to create pivot table")

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})
        if isinstance(data, str):
            import json

            try:
                data = json.loads(data)
            except Exception:
                pass

        if not isinstance(data, dict):
            pytest.fail(f"Response data is not a dict: {data}")

        assert data.get("pivot_sheet") == "Pivot Table"

    def test_share_spreadsheet(self, composio_client, user_id, test_spreadsheet):
        """Test CUSTOM_SHARE_SPREADSHEET (via GOOGLESHEETS_CUSTOM_SHARE_SPREADSHEET)."""
        share_email = test_spreadsheet.get("share_email")
        if not share_email:
            pytest.skip("No share_email configured in config.yaml")

        result = execute_tool(
            composio_client,
            "GOOGLESHEETS_CUSTOM_SHARE_SPREADSHEET",
            {
                "spreadsheet_id": test_spreadsheet["spreadsheet_id"],
                "recipients": [
                    {
                        "email": share_email,
                        "role": "reader",
                        "send_notification": True,
                    }
                ],
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
