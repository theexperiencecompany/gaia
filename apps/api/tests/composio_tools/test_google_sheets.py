"""
Google Sheets custom tool tests using pytest.

Tests 5 sheets tools:
- CUSTOM_SET_DATA_VALIDATION (modifies sheet)
- CUSTOM_ADD_CONDITIONAL_FORMAT (modifies sheet)
- CUSTOM_CREATE_CHART (modifies sheet)
- CUSTOM_CREATE_PIVOT_TABLE (modifies sheet)
- CUSTOM_SHARE_SPREADSHEET (destructive - manual only)

Usage:
    pytest tests/composio_tools/test_google_sheets_pytest.py -v --user-id USER_ID --spreadsheet-id SHEET_ID

To run all including destructive:
    pytest ... --run-destructive
"""

import pytest

from tests.composio_tools.conftest import execute_tool


def pytest_addoption(parser):
    """Add custom CLI options."""
    try:
        parser.addoption(
            "--spreadsheet-id",
            action="store",
            default=None,
            help="Google Sheets spreadsheet ID to test with",
        )
        parser.addoption(
            "--sheet-name",
            action="store",
            default="Sheet1",
            help="Sheet tab name (default: Sheet1)",
        )
        parser.addoption(
            "--run-destructive",
            action="store_true",
            default=False,
            help="Run destructive tests (share, etc.)",
        )
    except ValueError:
        pass  # Already added


@pytest.fixture(scope="session")
def spreadsheet_id(request) -> str:
    """Get spreadsheet ID from CLI argument."""
    sheet_id = request.config.getoption("--spreadsheet-id")
    if not sheet_id:
        pytest.skip("--spreadsheet-id required for Google Sheets tests")
    return sheet_id


@pytest.fixture(scope="session")
def sheet_name(request) -> str:
    """Get sheet name from CLI argument."""
    return request.config.getoption("--sheet-name") or "Sheet1"


@pytest.fixture(scope="session")
def run_destructive(request) -> bool:
    """Check if destructive tests should run."""
    return request.config.getoption("--run-destructive")


class TestGoogleSheetsModifyOperations:
    """Tests that modify the spreadsheet (but are reversible)."""

    def test_set_data_validation(
        self, composio_client, user_id, spreadsheet_id, sheet_name
    ):
        """Test CUSTOM_SET_DATA_VALIDATION adds dropdown validation."""
        result = execute_tool(
            composio_client,
            "GOOGLESHEETS_CUSTOM_SET_DATA_VALIDATION",
            {
                "spreadsheet_id": spreadsheet_id,
                "sheet_name": sheet_name,
                "range": "E1:E10",
                "validation_type": "dropdown_list",
                "values": ["Option A", "Option B", "Option C"],
                "strict": True,
                "show_dropdown": True,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})
        assert data, "Expected response data"

    def test_add_conditional_format(
        self, composio_client, user_id, spreadsheet_id, sheet_name
    ):
        """Test CUSTOM_ADD_CONDITIONAL_FORMAT adds color scale."""
        result = execute_tool(
            composio_client,
            "GOOGLESHEETS_CUSTOM_ADD_CONDITIONAL_FORMAT",
            {
                "spreadsheet_id": spreadsheet_id,
                "sheet_name": sheet_name,
                "range": "A1:D10",
                "format_type": "color_scale",
                "min_color": "#FF0000",
                "mid_color": "#FFFF00",
                "max_color": "#00FF00",
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})
        assert data, "Expected response data"

    def test_create_chart(self, composio_client, user_id, spreadsheet_id, sheet_name):
        """Test CUSTOM_CREATE_CHART creates a bar chart."""
        result = execute_tool(
            composio_client,
            "GOOGLESHEETS_CUSTOM_CREATE_CHART",
            {
                "spreadsheet_id": spreadsheet_id,
                "sheet_name": sheet_name,
                "data_range": "A1:B10",
                "chart_type": "BAR",
                "title": "Test Chart",
                "anchor_cell": "G1",
                "width": 400,
                "height": 300,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})
        assert data, "Expected response data"

    @pytest.mark.skip(reason="Requires proper columnar headers. Run manually.")
    def test_create_pivot_table(
        self, composio_client, user_id, spreadsheet_id, sheet_name
    ):
        """Test CUSTOM_CREATE_PIVOT_TABLE creates a pivot table.

        NOTE: Requires sheet with headers in row 1 (e.g., Name, Category, Amount).
        """
        result = execute_tool(
            composio_client,
            "GOOGLESHEETS_CUSTOM_CREATE_PIVOT_TABLE",
            {
                "spreadsheet_id": spreadsheet_id,
                "source_sheet_name": sheet_name,
                "destination_sheet_name": sheet_name,
                "destination_cell": "J1",
                "rows": ["Category"],  # Adjust to your column name
                "columns": [],
                "values": [{"column": "Amount", "aggregation": "SUM"}],
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})
        assert data, "Expected response data"


class TestGoogleSheetsDestructiveOperations:
    """Tests that are irreversible - run manually."""

    @pytest.mark.skip(
        reason="Destructive: adds real permissions. Use --run-destructive."
    )
    def test_share_spreadsheet(self, composio_client, user_id, spreadsheet_id):
        """Test CUSTOM_SHARE_SPREADSHEET shares a spreadsheet.

        MANUAL TEST: Adds a real permission to the spreadsheet.
        """
        test_email = "test@example.com"  # Replace with real email

        result = execute_tool(
            composio_client,
            "GOOGLESHEETS_CUSTOM_SHARE_SPREADSHEET",
            {
                "spreadsheet_id": spreadsheet_id,
                "recipients": [
                    {
                        "email": test_email,
                        "role": "reader",
                        "send_notification": False,
                    }
                ],
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})
        assert data, "Expected response data"
