"""Unit tests for app.agents.tools.integrations.google_sheets_tool.

Only the true I/O boundary is faked: `proxy_request_sync`, patched in both this
module and `google_sheets_utils`, is routed through a single fake Sheets/Drive
API. Everything else — A1 parsing, sheet/column resolution, request assembly —
runs for real, so the assertions below are against the exact JSON Google would
receive.

Several production bugs were found while writing these tests and fixed at the
root in `google_sheets_tool.py`, `google_sheets_utils.py` and
`google_sheets_models.py`; the tests pinning them down are marked "BUG:".
"""

from typing import Any, cast
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
import pytest

from app.agents.tools.integrations.google_sheets_tool import (
    NEW_FORMAT_RULE_INDEX,
    RECENT_SPREADSHEETS_PAGE_SIZE,
    SHEETS_TOOLKIT,
    _user_id,
    register_google_sheets_custom_tools,
)
from app.models.common_models import GatherContextInput
from app.models.google_sheets_models import (
    ChartInput,
    ConditionalFormatInput,
    CreatePivotTableInput,
    DataValidationInput,
    PivotValue,
    ShareRecipient,
    ShareSpreadsheetInput,
)
from app.utils.errors import AppError
from app.utils.google_sheets_utils import DRIVE_API_BASE, SHEETS_API_BASE

MODULE = "app.agents.tools.integrations.google_sheets_tool"
UTILS = "app.utils.google_sheets_utils"
AUTH: dict[str, Any] = {"user_id": "user-42"}
SPREADSHEET = "sheet-abc"
EXPECTED_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET}/edit"


# ---------------------------------------------------------------------------
# Fake Google API
# ---------------------------------------------------------------------------


class FakeSheetsApi:
    """Routes proxy calls to canned Sheets/Drive responses and records requests."""

    def __init__(self) -> None:
        self.sheets: dict[str, int] = {"Sheet1": 0, "Data": 111, "Report": 222}
        self.headers: list[Any] = ["Region", "Product", "Revenue"]
        self.batch_response: Any = {}
        self.batch_error: Exception | None = None
        self.permission_error: Exception | None = None
        self.failing_recipients: dict[str, Exception] = {}
        self.permission_result: Any = {"id": "perm-1"}
        self.files: Any = []
        self.files_error: Exception | None = None

        self.calls: list[dict[str, Any]] = []
        self.batch_bodies: list[dict[str, Any]] = []
        self.permission_calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        endpoint = kwargs["endpoint"]

        if endpoint.endswith(":batchUpdate"):
            self.batch_bodies.append(kwargs["body"])
            if self.batch_error is not None:
                raise self.batch_error
            return self.batch_response

        if endpoint.endswith("/permissions"):
            self.permission_calls.append(kwargs)
            email = kwargs["body"]["emailAddress"]
            failure = self.failing_recipients.get(email, self.permission_error)
            if failure is not None:
                raise failure
            return self.permission_result

        if endpoint == f"{DRIVE_API_BASE}/files":
            if self.files_error is not None:
                raise self.files_error
            return self.files

        if "/values/" in endpoint:
            return {"values": [self.headers]} if self.headers else {}

        if endpoint.startswith(SHEETS_API_BASE):
            return {
                "sheets": [
                    {"properties": {"title": title, "sheetId": sid}}
                    for title, sid in self.sheets.items()
                ]
            }

        raise AssertionError(f"unexpected endpoint: {endpoint}")

    # -- assertions helpers -------------------------------------------------

    def sole_batch_request(self) -> dict[str, Any]:
        assert len(self.batch_bodies) == 1, self.batch_bodies
        requests = self.batch_bodies[0]["requests"]
        assert len(requests) == 1, requests
        return dict(requests[0])


def _register() -> dict[str, Any]:
    captured: dict[str, Any] = {}
    composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            captured[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    register_google_sheets_custom_tools(composio)
    return captured


@pytest.fixture
def api() -> Any:
    fake = FakeSheetsApi()
    with (
        patch(f"{MODULE}.proxy_request_sync", side_effect=fake),
        patch(f"{UTILS}.proxy_request_sync", side_effect=fake),
    ):
        yield fake


@pytest.fixture
def tools() -> dict[str, Any]:
    return _register()


def _call(tools: dict[str, Any], name: str, request: Any) -> dict[str, Any]:
    result: dict[str, Any] = tools[name](request, MagicMock(), AUTH)
    return result


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registers_every_advertised_tool(self) -> None:
        composio = MagicMock()
        registered: list[str] = []

        def custom_tool(**kwargs: Any) -> Any:
            assert kwargs == {"toolkit": "GOOGLESHEETS"}

            def decorator(fn: Any) -> Any:
                registered.append(fn.__name__)
                return fn

            return decorator

        composio.tools.custom_tool = custom_tool
        names = register_google_sheets_custom_tools(composio)

        # Every returned name must correspond to a function that was actually
        # registered — a name in the list with no tool behind it is a tool the
        # agent can select and never execute.
        assert names == [f"GOOGLESHEETS_{fn}" for fn in registered]

    def test_returns_the_six_tool_names(self) -> None:
        assert register_google_sheets_custom_tools(MagicMock()) == [
            "GOOGLESHEETS_CUSTOM_SHARE_SPREADSHEET",
            "GOOGLESHEETS_CUSTOM_CREATE_PIVOT_TABLE",
            "GOOGLESHEETS_CUSTOM_SET_DATA_VALIDATION",
            "GOOGLESHEETS_CUSTOM_ADD_CONDITIONAL_FORMAT",
            "GOOGLESHEETS_CUSTOM_CREATE_CHART",
            "GOOGLESHEETS_CUSTOM_GATHER_CONTEXT",
        ]

    def test_docstrings_are_replaced_with_the_agent_facing_docs(self, tools: Any) -> None:
        # The model selects tools by docstring; the terse developer docstring
        # would strip the parameter contract.
        doc = tools["CUSTOM_CREATE_CHART"].__doc__
        assert doc is not None
        assert "Parameters:" in doc and "chart_type" in doc


# ---------------------------------------------------------------------------
# _user_id
# ---------------------------------------------------------------------------


class TestUserId:
    def test_returns_the_credential_user_id(self) -> None:
        assert _user_id({"user_id": "abc"}) == "abc"

    @pytest.mark.parametrize(
        "credentials",
        [{}, {"user_id": ""}, {"user_id": None}, {"user_id": 42}, {"userId": "abc"}],
    )
    def test_unusable_credentials_are_rejected(self, credentials: dict[str, Any]) -> None:
        # Falling through with a blank/None user id would send the request as
        # nobody and surface as a confusing 500 deep inside the proxy.
        with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
            _user_id(credentials)


# ---------------------------------------------------------------------------
# CUSTOM_SHARE_SPREADSHEET
# ---------------------------------------------------------------------------


class TestShareSpreadsheet:
    def test_shares_with_a_single_recipient(self, tools: Any, api: Any) -> None:
        result = _call(
            tools,
            "CUSTOM_SHARE_SPREADSHEET",
            ShareSpreadsheetInput(
                spreadsheet_id=SPREADSHEET,
                recipients=[ShareRecipient(email="a@x.com", role="reader")],
            ),
        )

        assert result == {
            "spreadsheet_id": SPREADSHEET,
            "url": EXPECTED_URL,
            "shared": [
                {
                    "email": "a@x.com",
                    "role": "reader",
                    "permission_id": "perm-1",
                    "notification_sent": True,
                }
            ],
            "errors": [],
            "total_shared": 1,
            "total_failed": 0,
        }

    def test_sends_the_drive_permission_request_google_expects(self, tools: Any, api: Any) -> None:
        _call(
            tools,
            "CUSTOM_SHARE_SPREADSHEET",
            ShareSpreadsheetInput(
                spreadsheet_id=SPREADSHEET,
                recipients=[ShareRecipient(email="a@x.com", role="commenter")],
            ),
        )

        call = api.permission_calls[0]
        assert call["endpoint"] == f"{DRIVE_API_BASE}/files/{SPREADSHEET}/permissions"
        assert call["method"] == "POST"
        assert call["toolkit"] == SHEETS_TOOLKIT
        assert call["user_id"] == "user-42"
        assert call["body"] == {
            "type": "user",
            "role": "commenter",
            "emailAddress": "a@x.com",
        }

    @pytest.mark.parametrize(("send_notification", "expected"), [(True, "true"), (False, "false")])
    def test_notification_flag_is_sent_as_a_lowercase_string(
        self, tools: Any, api: Any, send_notification: bool, expected: str
    ) -> None:
        # Drive's query API rejects Python's "True"/"False" capitalisation.
        _call(
            tools,
            "CUSTOM_SHARE_SPREADSHEET",
            ShareSpreadsheetInput(
                spreadsheet_id=SPREADSHEET,
                recipients=[ShareRecipient(email="a@x.com", send_notification=send_notification)],
            ),
        )

        assert api.permission_calls[0]["query"] == {"sendNotificationEmail": expected}

    def test_every_recipient_gets_its_own_request(self, tools: Any, api: Any) -> None:
        result = _call(
            tools,
            "CUSTOM_SHARE_SPREADSHEET",
            ShareSpreadsheetInput(
                spreadsheet_id=SPREADSHEET,
                recipients=[
                    ShareRecipient(email="a@x.com"),
                    ShareRecipient(email="b@x.com"),
                    ShareRecipient(email="c@x.com"),
                ],
            ),
        )

        assert [c["body"]["emailAddress"] for c in api.permission_calls] == [
            "a@x.com",
            "b@x.com",
            "c@x.com",
        ]
        assert result["total_shared"] == 3

    def test_missing_permission_id_is_reported_as_none(self, tools: Any, api: Any) -> None:
        api.permission_result = None
        result = _call(
            tools,
            "CUSTOM_SHARE_SPREADSHEET",
            ShareSpreadsheetInput(
                spreadsheet_id=SPREADSHEET, recipients=[ShareRecipient(email="a@x.com")]
            ),
        )

        assert result["shared"][0]["permission_id"] is None
        assert result["total_shared"] == 1

    # BUG: the per-recipient `errors` list was built and then dropped from the
    # response, so a partial failure reported `total_failed: 1` with no way to
    # tell the user which address failed or why — and the tool's own docs
    # promised an `errors` field.
    def test_partial_failure_reports_which_recipient_failed_and_why(
        self, tools: Any, api: Any
    ) -> None:
        api.failing_recipients = {
            "bad@x.com": AppError(message="Invalid email", why="w", status_code=400)
        }
        result = _call(
            tools,
            "CUSTOM_SHARE_SPREADSHEET",
            ShareSpreadsheetInput(
                spreadsheet_id=SPREADSHEET,
                recipients=[
                    ShareRecipient(email="ok@x.com"),
                    ShareRecipient(email="bad@x.com", role="reader"),
                ],
            ),
        )

        assert result["total_shared"] == 1
        assert result["total_failed"] == 1
        assert result["errors"] == [
            {"email": "bad@x.com", "role": "reader", "error": "Failed: 400 - Invalid email"}
        ]

    def test_app_error_message_and_status_are_both_surfaced(self, tools: Any, api: Any) -> None:
        api.permission_error = AppError(message="Quota exceeded", why="w", status_code=429)
        with pytest.raises(RuntimeError) as excinfo:
            _call(
                tools,
                "CUSTOM_SHARE_SPREADSHEET",
                ShareSpreadsheetInput(
                    spreadsheet_id=SPREADSHEET, recipients=[ShareRecipient(email="a@x.com")]
                ),
            )

        assert "429" in str(excinfo.value)
        assert "Quota exceeded" in str(excinfo.value)

    def test_non_app_error_is_captured_as_its_string(self, tools: Any, api: Any) -> None:
        api.permission_error = TimeoutError("connection reset")
        with pytest.raises(RuntimeError, match="connection reset"):
            _call(
                tools,
                "CUSTOM_SHARE_SPREADSHEET",
                ShareSpreadsheetInput(
                    spreadsheet_id=SPREADSHEET, recipients=[ShareRecipient(email="a@x.com")]
                ),
            )

    def test_total_failure_raises_rather_than_reporting_success(self, tools: Any, api: Any) -> None:
        # A response of "shared with 0 of 2" would otherwise read to the agent
        # as a successful call.
        api.permission_error = AppError(message="nope", why="w", status_code=403)
        with pytest.raises(RuntimeError, match="Failed to share spreadsheet"):
            _call(
                tools,
                "CUSTOM_SHARE_SPREADSHEET",
                ShareSpreadsheetInput(
                    spreadsheet_id=SPREADSHEET,
                    recipients=[
                        ShareRecipient(email="a@x.com"),
                        ShareRecipient(email="b@x.com"),
                    ],
                ),
            )

    def test_at_least_one_recipient_is_required(self) -> None:
        with pytest.raises(ValidationError):
            ShareSpreadsheetInput(spreadsheet_id=SPREADSHEET, recipients=[])

    def test_role_must_be_a_drive_permission_role(self) -> None:
        with pytest.raises(ValidationError):
            ShareRecipient(email="a@x.com", role=cast(Any, "owner"))


# ---------------------------------------------------------------------------
# CUSTOM_CREATE_PIVOT_TABLE
# ---------------------------------------------------------------------------


def _pivot(**overrides: Any) -> CreatePivotTableInput:
    payload: dict[str, Any] = {
        "spreadsheet_id": SPREADSHEET,
        "source_sheet_name": "Data",
        "destination_sheet_name": "Report",
        "rows": ["Region"],
        "values": [PivotValue(column="Revenue")],
    }
    payload.update(overrides)
    return CreatePivotTableInput(**payload)


def _pivot_table(api: FakeSheetsApi) -> dict[str, Any]:
    update = api.sole_batch_request()["updateCells"]
    table: dict[str, Any] = update["rows"][0]["values"][0]["pivotTable"]
    return table


class TestCreatePivotTable:
    def test_builds_the_pivot_table_from_resolved_column_offsets(
        self, tools: Any, api: Any
    ) -> None:
        result = _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", _pivot())

        table = _pivot_table(api)
        assert table["source"] == {"sheetId": 111}
        assert table["rows"] == [
            {"sourceColumnOffset": 0, "sortOrder": "ASCENDING", "showTotals": True}
        ]
        assert table["values"] == [{"sourceColumnOffset": 2, "summarizeFunction": "SUM"}]
        assert result["pivot_sheet"] == "Report"
        assert result["url"] == EXPECTED_URL

    def test_writes_the_pivot_into_the_destination_sheet(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", _pivot(destination_cell="C5"))

        update = api.sole_batch_request()["updateCells"]
        assert update["start"] == {"sheetId": 222, "rowIndex": 4, "columnIndex": 2}
        assert update["fields"] == "pivotTable"

    def test_targets_the_batch_update_endpoint(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", _pivot())

        batch = next(c for c in api.calls if c["endpoint"].endswith(":batchUpdate"))
        assert batch["endpoint"] == f"{SHEETS_API_BASE}/{SPREADSHEET}:batchUpdate"
        assert batch["method"] == "POST"

    def test_column_groupings_are_included_when_requested(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", _pivot(columns=["Product"]))

        assert _pivot_table(api)["columns"] == [
            {"sourceColumnOffset": 1, "sortOrder": "ASCENDING", "showTotals": True}
        ]

    def test_columns_key_is_omitted_when_no_column_groupings(self, tools: Any, api: Any) -> None:
        # An empty `columns` list makes Google render an extra blank grouping.
        assert "columns" not in _pivot_table_after(tools, api, _pivot())

    def test_multiple_row_groupings_keep_their_order(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", _pivot(rows=["Product", "Region"]))

        assert [r["sourceColumnOffset"] for r in _pivot_table(api)["rows"]] == [1, 0]

    def test_custom_value_name_is_forwarded(self, tools: Any, api: Any) -> None:
        _call(
            tools,
            "CUSTOM_CREATE_PIVOT_TABLE",
            _pivot(values=[PivotValue(column="Revenue", aggregation="AVERAGE", name="Avg")]),
        )

        assert _pivot_table(api)["values"] == [
            {"sourceColumnOffset": 2, "summarizeFunction": "AVERAGE", "name": "Avg"}
        ]

    def test_name_key_is_omitted_when_unset(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", _pivot())
        assert "name" not in _pivot_table(api)["values"][0]

    # BUG: `aggregation` was `str | None`, so an explicit null reached Google as
    # `"summarizeFunction": null` and the batch was rejected. It is now a
    # required literal with a SUM default.
    def test_aggregation_cannot_be_null(self) -> None:
        with pytest.raises(ValidationError):
            PivotValue(column="Revenue", aggregation=cast(Any, None))

    def test_aggregation_must_be_a_function_google_accepts(self) -> None:
        with pytest.raises(ValidationError):
            PivotValue(column="Revenue", aggregation=cast(Any, "TOTAL"))

    def test_source_range_narrows_the_pivot_source(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", _pivot(source_range="A1:C50"))

        assert _pivot_table(api)["source"] == {
            "sheetId": 111,
            "startRowIndex": 0,
            "endRowIndex": 50,
            "startColumnIndex": 0,
            "endColumnIndex": 3,
        }

    def test_omitted_source_range_is_labelled_as_the_entire_sheet(
        self, tools: Any, api: Any
    ) -> None:
        result = _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", _pivot())
        assert result["source_range"] == "Data!entire sheet"

    def test_source_range_is_echoed_with_its_sheet(self, tools: Any, api: Any) -> None:
        result = _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", _pivot(source_range="A1:C50"))
        assert result["source_range"] == "Data!A1:C50"

    def test_missing_source_sheet_is_named_in_the_error(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="Source sheet 'Ghost' not found"):
            _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", _pivot(source_sheet_name="Ghost"))

    def test_missing_destination_sheet_is_named_in_the_error(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="Destination sheet 'Ghost' not found"):
            _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", _pivot(destination_sheet_name="Ghost"))

    def test_unknown_row_column_is_rejected_before_any_write(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="Column 'Nope' not found in headers"):
            _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", _pivot(rows=["Nope"]))
        assert api.batch_bodies == []

    def test_unknown_column_grouping_is_rejected(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="Column 'Nope' not found"):
            _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", _pivot(columns=["Nope"]))
        assert api.batch_bodies == []

    def test_unknown_value_column_is_rejected(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="Value column 'Nope' not found"):
            _call(
                tools,
                "CUSTOM_CREATE_PIVOT_TABLE",
                _pivot(values=[PivotValue(column="Nope")]),
            )
        assert api.batch_bodies == []

    def test_rows_and_values_are_both_mandatory(self) -> None:
        with pytest.raises(ValidationError):
            _pivot(rows=[])
        with pytest.raises(ValidationError):
            _pivot(values=[])

    # BUG: destination_cell went through parse_a1_range, which silently turned
    # an open-ended reference like "A" into cell A1. It now fails loudly.
    def test_open_ended_destination_cell_is_rejected(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="Not a single cell reference"):
            _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", _pivot(destination_cell="A"))


def _pivot_table_after(
    tools: dict[str, Any], api: FakeSheetsApi, request: CreatePivotTableInput
) -> dict[str, Any]:
    _call(tools, "CUSTOM_CREATE_PIVOT_TABLE", request)
    return _pivot_table(api)


# ---------------------------------------------------------------------------
# CUSTOM_SET_DATA_VALIDATION
# ---------------------------------------------------------------------------


def _validation(**overrides: Any) -> DataValidationInput:
    payload: dict[str, Any] = {
        "spreadsheet_id": SPREADSHEET,
        "sheet_name": "Data",
        "range": "A2:A100",
        "validation_type": "dropdown_list",
        "values": ["High", "Low"],
    }
    payload.update(overrides)
    return DataValidationInput(**payload)


def _validation_rule(api: FakeSheetsApi) -> dict[str, Any]:
    rule: dict[str, Any] = api.sole_batch_request()["setDataValidation"]["rule"]
    return rule


class TestSetDataValidation:
    def test_dropdown_list_builds_a_one_of_list_condition(self, tools: Any, api: Any) -> None:
        result = _call(tools, "CUSTOM_SET_DATA_VALIDATION", _validation())

        assert _validation_rule(api)["condition"] == {
            "type": "ONE_OF_LIST",
            "values": [{"userEnteredValue": "High"}, {"userEnteredValue": "Low"}],
        }
        assert result == {
            "spreadsheet_id": SPREADSHEET,
            "url": EXPECTED_URL,
            "range_applied": "Data!A2:A100",
            "validation_type": "dropdown_list",
        }

    def test_range_carries_the_resolved_sheet_id(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_SET_DATA_VALIDATION", _validation())

        assert api.sole_batch_request()["setDataValidation"]["range"] == {
            "sheetId": 111,
            "startRowIndex": 1,
            "endRowIndex": 100,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        }

    # BUG: a whole-column range collapsed to cell A1, so "add a dropdown to
    # column B" validated one cell and reported success for the whole column.
    def test_whole_column_range_stays_unbounded(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_SET_DATA_VALIDATION", _validation(range="B:B"))

        assert api.sole_batch_request()["setDataValidation"]["range"] == {
            "sheetId": 111,
            "startColumnIndex": 1,
            "endColumnIndex": 2,
        }

    def test_dropdown_list_requires_values(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="values required for dropdown_list"):
            _call(tools, "CUSTOM_SET_DATA_VALIDATION", _validation(values=None))

    def test_dropdown_range_references_the_source_as_a_formula(self, tools: Any, api: Any) -> None:
        _call(
            tools,
            "CUSTOM_SET_DATA_VALIDATION",
            _validation(validation_type="dropdown_range", source_range="Lists!A:A"),
        )

        assert _validation_rule(api)["condition"] == {
            "type": "ONE_OF_RANGE",
            "values": [{"userEnteredValue": "=Lists!A:A"}],
        }

    def test_dropdown_range_requires_a_source_range(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="source_range required for dropdown_range"):
            _call(
                tools, "CUSTOM_SET_DATA_VALIDATION", _validation(validation_type="dropdown_range")
            )

    @pytest.mark.parametrize(
        ("validation_type", "bounds", "expected_type", "expected_values"),
        [
            ("number", {"min_value": "1", "max_value": "100"}, "NUMBER_BETWEEN", ["1", "100"]),
            ("number", {"min_value": "1"}, "NUMBER_GREATER_THAN_EQ", ["1"]),
            ("number", {"max_value": "100"}, "NUMBER_LESS_THAN_EQ", ["100"]),
            (
                "date",
                {"min_value": "2026-01-01", "max_value": "2026-12-31"},
                "DATE_BETWEEN",
                ["2026-01-01", "2026-12-31"],
            ),
            ("date", {"min_value": "2026-01-01"}, "DATE_AFTER", ["2026-01-01"]),
            ("date", {"max_value": "2026-12-31"}, "DATE_BEFORE", ["2026-12-31"]),
        ],
    )
    def test_bounded_validations_pick_the_matching_condition(
        self,
        tools: Any,
        api: Any,
        validation_type: str,
        bounds: dict[str, str],
        expected_type: str,
        expected_values: list[str],
    ) -> None:
        _call(
            tools,
            "CUSTOM_SET_DATA_VALIDATION",
            _validation(validation_type=validation_type, values=None, **bounds),
        )

        assert _validation_rule(api)["condition"] == {
            "type": expected_type,
            "values": [{"userEnteredValue": v} for v in expected_values],
        }

    @pytest.mark.parametrize("validation_type", ["number", "date"])
    def test_bounded_validation_without_any_bound_is_rejected(
        self, tools: Any, api: Any, validation_type: str
    ) -> None:
        with pytest.raises(
            ValueError, match=f"min_value or max_value required for {validation_type}"
        ):
            _call(
                tools,
                "CUSTOM_SET_DATA_VALIDATION",
                _validation(validation_type=validation_type, values=None),
            )

    def test_custom_formula_condition(self, tools: Any, api: Any) -> None:
        _call(
            tools,
            "CUSTOM_SET_DATA_VALIDATION",
            _validation(validation_type="custom_formula", formula="=LEN(A1)<=50"),
        )

        assert _validation_rule(api)["condition"] == {
            "type": "CUSTOM_FORMULA",
            "values": [{"userEnteredValue": "=LEN(A1)<=50"}],
        }

    def test_custom_formula_requires_a_formula(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="formula required for custom_formula"):
            _call(
                tools, "CUSTOM_SET_DATA_VALIDATION", _validation(validation_type="custom_formula")
            )

    @pytest.mark.parametrize("strict", [True, False])
    @pytest.mark.parametrize("show_dropdown", [True, False])
    def test_strict_and_dropdown_flags_are_forwarded(
        self, tools: Any, api: Any, strict: bool, show_dropdown: bool
    ) -> None:
        # strict=False means "warn"; sending the default True would silently
        # reject the user's data instead.
        _call(
            tools,
            "CUSTOM_SET_DATA_VALIDATION",
            _validation(strict=strict, show_dropdown=show_dropdown),
        )

        rule = _validation_rule(api)
        assert rule["strict"] is strict
        assert rule["showCustomUi"] is show_dropdown

    def test_input_message_is_attached_when_given(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_SET_DATA_VALIDATION", _validation(input_message="Pick one"))
        assert _validation_rule(api)["inputMessage"] == "Pick one"

    def test_input_message_key_is_absent_when_unset(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_SET_DATA_VALIDATION", _validation())
        assert "inputMessage" not in _validation_rule(api)

    def test_missing_sheet_is_rejected_before_any_write(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="Sheet 'Ghost' not found"):
            _call(tools, "CUSTOM_SET_DATA_VALIDATION", _validation(sheet_name="Ghost"))
        assert api.batch_bodies == []

    def test_batch_failure_is_reported_with_the_provider_message(
        self, tools: Any, api: Any
    ) -> None:
        api.batch_error = AppError(message="Invalid range", why="w", status_code=400)
        with pytest.raises(RuntimeError, match="Failed to set data validation: Invalid range"):
            _call(tools, "CUSTOM_SET_DATA_VALIDATION", _validation())

    def test_unknown_validation_type_is_rejected_by_the_schema(self) -> None:
        with pytest.raises(ValidationError):
            _validation(validation_type="colour")


# ---------------------------------------------------------------------------
# CUSTOM_ADD_CONDITIONAL_FORMAT
# ---------------------------------------------------------------------------


def _format(**overrides: Any) -> ConditionalFormatInput:
    payload: dict[str, Any] = {
        "spreadsheet_id": SPREADSHEET,
        "sheet_name": "Data",
        "range": "B2:B100",
        "format_type": "value_based",
        "condition": "greater_than",
        "condition_values": ["100"],
        "background_color": "#FF0000",
    }
    payload.update(overrides)
    return ConditionalFormatInput(**payload)


def _format_rule(api: FakeSheetsApi) -> dict[str, Any]:
    rule: dict[str, Any] = api.sole_batch_request()["addConditionalFormatRule"]["rule"]
    return rule


class TestAddConditionalFormat:
    def test_value_based_rule_carries_condition_and_format(self, tools: Any, api: Any) -> None:
        result = _call(tools, "CUSTOM_ADD_CONDITIONAL_FORMAT", _format())

        assert _format_rule(api)["booleanRule"] == {
            "condition": {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "100"}]},
            "format": {"backgroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}},
        }
        assert result == {
            "spreadsheet_id": SPREADSHEET,
            "url": EXPECTED_URL,
            "range_applied": "Data!B2:B100",
            "format_type": "value_based",
            "rule_index": NEW_FORMAT_RULE_INDEX,
        }

    def test_new_rule_is_inserted_ahead_of_existing_rules(self, tools: Any, api: Any) -> None:
        # Index 0 is what makes the new rule win over rules already on the range.
        _call(tools, "CUSTOM_ADD_CONDITIONAL_FORMAT", _format())
        assert api.sole_batch_request()["addConditionalFormatRule"]["index"] == 0

    def test_rule_range_is_bound_to_the_resolved_sheet(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_ADD_CONDITIONAL_FORMAT", _format())

        assert _format_rule(api)["ranges"] == [
            {
                "sheetId": 111,
                "startRowIndex": 1,
                "endRowIndex": 100,
                "startColumnIndex": 1,
                "endColumnIndex": 2,
            }
        ]

    @pytest.mark.parametrize(
        ("condition", "api_type"),
        [
            ("greater_than", "NUMBER_GREATER"),
            ("less_than", "NUMBER_LESS"),
            ("equal_to", "NUMBER_EQ"),
            ("not_equal_to", "NUMBER_NOT_EQ"),
            ("contains", "TEXT_CONTAINS"),
            ("not_contains", "TEXT_NOT_CONTAINS"),
        ],
    )
    def test_single_value_conditions_map_to_their_api_names(
        self, tools: Any, api: Any, condition: str, api_type: str
    ) -> None:
        _call(tools, "CUSTOM_ADD_CONDITIONAL_FORMAT", _format(condition=condition))

        assert _format_rule(api)["booleanRule"]["condition"] == {
            "type": api_type,
            "values": [{"userEnteredValue": "100"}],
        }

    @pytest.mark.parametrize(
        ("condition", "api_type"), [("is_empty", "BLANK"), ("is_not_empty", "NOT_BLANK")]
    )
    def test_emptiness_conditions_carry_no_values(
        self, tools: Any, api: Any, condition: str, api_type: str
    ) -> None:
        _call(
            tools,
            "CUSTOM_ADD_CONDITIONAL_FORMAT",
            _format(condition=condition, condition_values=None),
        )

        assert _format_rule(api)["booleanRule"]["condition"] == {"type": api_type}

    def test_between_uses_both_bounds(self, tools: Any, api: Any) -> None:
        _call(
            tools,
            "CUSTOM_ADD_CONDITIONAL_FORMAT",
            _format(condition="between", condition_values=["10", "20"]),
        )

        assert _format_rule(api)["booleanRule"]["condition"] == {
            "type": "NUMBER_BETWEEN",
            "values": [{"userEnteredValue": "10"}, {"userEnteredValue": "20"}],
        }

    # BUG: only truthiness of `condition_values` was checked, so "between" with a
    # single bound produced a NUMBER_BETWEEN rule with one value that Google
    # rejects, and extra values for a single-value condition passed silently.
    @pytest.mark.parametrize("values", [["10"], ["10", "20", "30"]])
    def test_between_requires_exactly_two_values(
        self, tools: Any, api: Any, values: list[str]
    ) -> None:
        with pytest.raises(
            ValueError, match=rf"'between' requires exactly 2 condition_values, got {len(values)}"
        ):
            _call(
                tools,
                "CUSTOM_ADD_CONDITIONAL_FORMAT",
                _format(condition="between", condition_values=values),
            )

    def test_single_value_condition_rejects_two_values(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="requires exactly 1 condition_values, got 2"):
            _call(
                tools,
                "CUSTOM_ADD_CONDITIONAL_FORMAT",
                _format(condition_values=["1", "2"]),
            )

    def test_missing_condition_values_are_rejected(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="requires exactly 1 condition_values, got 0"):
            _call(tools, "CUSTOM_ADD_CONDITIONAL_FORMAT", _format(condition_values=None))

    def test_value_based_requires_a_condition(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="condition required for value_based"):
            _call(tools, "CUSTOM_ADD_CONDITIONAL_FORMAT", _format(condition=None))

    def test_unknown_condition_is_rejected_by_the_schema(self) -> None:
        with pytest.raises(ValidationError):
            _format(condition="approximately")

    # BUG: a rule with an empty `format` is a no-op Google accepts, so asking to
    # "highlight cells over 100" without naming a colour reported success and
    # changed nothing on the sheet.
    def test_rule_with_no_formatting_is_rejected(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="At least one of background_color"):
            _call(tools, "CUSTOM_ADD_CONDITIONAL_FORMAT", _format(background_color=None))

    def test_text_colour_becomes_a_foreground_text_format(self, tools: Any, api: Any) -> None:
        _call(
            tools,
            "CUSTOM_ADD_CONDITIONAL_FORMAT",
            _format(background_color=None, text_color="#FFFFFF"),
        )

        assert _format_rule(api)["booleanRule"]["format"] == {
            "textFormat": {"foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}}
        }

    def test_bold_and_italic_merge_into_the_same_text_format(self, tools: Any, api: Any) -> None:
        # Each writes into textFormat; a plain assignment would drop the other.
        _call(
            tools,
            "CUSTOM_ADD_CONDITIONAL_FORMAT",
            _format(background_color=None, text_color="#000000", bold=True, italic=True),
        )

        assert _format_rule(api)["booleanRule"]["format"]["textFormat"] == {
            "foregroundColor": {"red": 0.0, "green": 0.0, "blue": 0.0},
            "bold": True,
            "italic": True,
        }

    @pytest.mark.parametrize("flag", ["bold", "italic"])
    def test_explicit_false_is_forwarded_not_treated_as_unset(
        self, tools: Any, api: Any, flag: str
    ) -> None:
        # bold=False must clear boldness; a truthiness check would drop it.
        _call(
            tools,
            "CUSTOM_ADD_CONDITIONAL_FORMAT",
            _format(background_color=None, **{flag: False}),
        )

        assert _format_rule(api)["booleanRule"]["format"]["textFormat"] == {flag: False}

    def test_background_and_text_colours_coexist(self, tools: Any, api: Any) -> None:
        _call(
            tools,
            "CUSTOM_ADD_CONDITIONAL_FORMAT",
            _format(background_color="#FF0000", text_color="#FFFFFF"),
        )

        fmt = _format_rule(api)["booleanRule"]["format"]
        assert fmt["backgroundColor"] == {"red": 1.0, "green": 0.0, "blue": 0.0}
        assert fmt["textFormat"]["foregroundColor"] == {"red": 1.0, "green": 1.0, "blue": 1.0}

    def test_custom_formula_rule(self, tools: Any, api: Any) -> None:
        _call(
            tools,
            "CUSTOM_ADD_CONDITIONAL_FORMAT",
            _format(format_type="custom_formula", condition=None, formula="=A1>100"),
        )

        assert _format_rule(api)["booleanRule"]["condition"] == {
            "type": "CUSTOM_FORMULA",
            "values": [{"userEnteredValue": "=A1>100"}],
        }

    def test_custom_formula_requires_a_formula(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="formula required for custom_formula"):
            _call(
                tools,
                "CUSTOM_ADD_CONDITIONAL_FORMAT",
                _format(format_type="custom_formula", condition=None),
            )

    def test_colour_scale_builds_a_two_point_gradient(self, tools: Any, api: Any) -> None:
        _call(
            tools,
            "CUSTOM_ADD_CONDITIONAL_FORMAT",
            _format(format_type="color_scale", min_color="#FF0000", max_color="#00FF00"),
        )

        rule = _format_rule(api)
        assert rule["gradientRule"] == {
            "minpoint": {"type": "MIN", "color": {"red": 1.0, "green": 0.0, "blue": 0.0}},
            "maxpoint": {"type": "MAX", "color": {"red": 0.0, "green": 1.0, "blue": 0.0}},
        }
        assert "booleanRule" not in rule

    def test_mid_colour_adds_a_median_percentile_stop(self, tools: Any, api: Any) -> None:
        _call(
            tools,
            "CUSTOM_ADD_CONDITIONAL_FORMAT",
            _format(
                format_type="color_scale",
                min_color="#FF0000",
                mid_color="#FFFF00",
                max_color="#00FF00",
            ),
        )

        assert _format_rule(api)["gradientRule"]["midpoint"] == {
            "type": "PERCENTILE",
            "value": "50",
            "color": {"red": 1.0, "green": 1.0, "blue": 0.0},
        }

    def test_midpoint_is_absent_without_a_mid_colour(self, tools: Any, api: Any) -> None:
        _call(
            tools,
            "CUSTOM_ADD_CONDITIONAL_FORMAT",
            _format(format_type="color_scale", min_color="#FF0000", max_color="#00FF00"),
        )
        assert "midpoint" not in _format_rule(api)["gradientRule"]

    # BUG: a gradient with a missing endpoint was sent as
    # {"minpoint": null, "maxpoint": null}, which Google rejects — the tool built
    # a request it knew was incomplete instead of saying what was missing.
    @pytest.mark.parametrize(
        "colors",
        [{}, {"min_color": "#FF0000"}, {"max_color": "#00FF00"}],
    )
    def test_colour_scale_requires_both_endpoints(
        self, tools: Any, api: Any, colors: dict[str, str]
    ) -> None:
        with pytest.raises(
            ValueError, match="min_color and max_color are required for color_scale"
        ):
            _call(
                tools,
                "CUSTOM_ADD_CONDITIONAL_FORMAT",
                _format(format_type="color_scale", **colors),
            )
        assert api.batch_bodies == []

    def test_invalid_colour_is_rejected_before_the_write(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="Invalid hex color"):
            _call(tools, "CUSTOM_ADD_CONDITIONAL_FORMAT", _format(background_color="#fff"))
        assert api.batch_bodies == []

    def test_missing_sheet_is_rejected_before_any_write(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="Sheet 'Ghost' not found"):
            _call(tools, "CUSTOM_ADD_CONDITIONAL_FORMAT", _format(sheet_name="Ghost"))
        assert api.batch_bodies == []

    def test_batch_failure_propagates(self, tools: Any, api: Any) -> None:
        api.batch_error = AppError(message="Invalid rule", why="w", status_code=400)
        with pytest.raises(AppError):
            _call(tools, "CUSTOM_ADD_CONDITIONAL_FORMAT", _format())


# ---------------------------------------------------------------------------
# CUSTOM_CREATE_CHART
# ---------------------------------------------------------------------------


def _chart(**overrides: Any) -> ChartInput:
    payload: dict[str, Any] = {
        "spreadsheet_id": SPREADSHEET,
        "sheet_name": "Data",
        "data_range": "A1:C10",
        "chart_type": "COLUMN",
    }
    payload.update(overrides)
    return ChartInput(**payload)


def _chart_request(api: FakeSheetsApi) -> dict[str, Any]:
    chart: dict[str, Any] = api.sole_batch_request()["addChart"]["chart"]
    return chart


class TestCreateChart:
    def test_first_column_is_the_domain_and_the_rest_are_series(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart())

        basic = _chart_request(api)["spec"]["basicChart"]
        domain = basic["domains"][0]["domain"]["sourceRange"]["sources"][0]
        assert (domain["startColumnIndex"], domain["endColumnIndex"]) == (0, 1)

        series_bounds = [
            (
                s["series"]["sourceRange"]["sources"][0]["startColumnIndex"],
                s["series"]["sourceRange"]["sources"][0]["endColumnIndex"],
            )
            for s in basic["series"]
        ]
        assert series_bounds == [(1, 2), (2, 3)]

    def test_every_range_is_tagged_with_the_source_sheet(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart())

        basic = _chart_request(api)["spec"]["basicChart"]
        assert basic["domains"][0]["domain"]["sourceRange"]["sources"][0]["sheetId"] == 111
        for s in basic["series"]:
            assert s["series"]["sourceRange"]["sources"][0]["sheetId"] == 111
            assert s["targetAxis"] == "LEFT_AXIS"

    def test_series_keep_the_row_bounds_of_the_data_range(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart(data_range="A5:C10"))

        source = _chart_request(api)["spec"]["basicChart"]["series"][0]["series"]["sourceRange"][
            "sources"
        ][0]
        assert (source["startRowIndex"], source["endRowIndex"]) == (4, 10)

    def test_single_column_range_charts_that_column(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart(data_range="B1:B10"))

        basic = _chart_request(api)["spec"]["basicChart"]
        assert len(basic["series"]) == 1
        source = basic["series"][0]["series"]["sourceRange"]["sources"][0]
        assert (source["startColumnIndex"], source["endColumnIndex"]) == (1, 2)

    # BUG: a whole-column data range collapsed to cell A1, so a chart over
    # "A:C" was built from a single cell.
    def test_whole_column_data_range_keeps_all_three_columns(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart(data_range="A:C"))

        assert len(_chart_request(api)["spec"]["basicChart"]["series"]) == 2

    @pytest.mark.parametrize("chart_type", ["BAR", "COLUMN", "LINE", "AREA", "SCATTER", "COMBO"])
    def test_basic_chart_types_are_passed_through(
        self, tools: Any, api: Any, chart_type: str
    ) -> None:
        # A lookup that silently defaulted to BAR would turn a requested LINE
        # chart into the wrong visual without any error.
        _call(tools, "CUSTOM_CREATE_CHART", _chart(chart_type=chart_type))

        assert _chart_request(api)["spec"]["basicChart"]["chartType"] == chart_type

    def test_unsupported_chart_type_is_rejected_by_the_schema(self) -> None:
        with pytest.raises(ValidationError):
            _chart(chart_type="DONUT")

    def test_basic_chart_treats_the_first_row_as_headers(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart())
        assert _chart_request(api)["spec"]["basicChart"]["headerCount"] == 1

    def test_pie_chart_uses_the_pie_spec_not_a_basic_chart(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart(chart_type="PIE"))

        spec = _chart_request(api)["spec"]
        assert "basicChart" not in spec
        assert spec["pieChart"]["domain"]["sourceRange"]["sources"][0]["endColumnIndex"] == 1
        assert spec["pieChart"]["series"]["sourceRange"]["sources"][0]["startColumnIndex"] == 1

    def test_pie_chart_carries_the_legend_position(self, tools: Any, api: Any) -> None:
        _call(
            tools,
            "CUSTOM_CREATE_CHART",
            _chart(chart_type="PIE", legend_position="NO_LEGEND"),
        )
        assert _chart_request(api)["spec"]["pieChart"]["legendPosition"] == "NO_LEGEND"

    def test_basic_chart_carries_the_legend_position(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart(legend_position="RIGHT_LEGEND"))
        assert _chart_request(api)["spec"]["basicChart"]["legendPosition"] == "RIGHT_LEGEND"

    def test_axis_titles_are_placed_on_the_right_axes(self, tools: Any, api: Any) -> None:
        _call(
            tools,
            "CUSTOM_CREATE_CHART",
            _chart(x_axis_title="Month", y_axis_title="Revenue"),
        )

        assert _chart_request(api)["spec"]["basicChart"]["axis"] == [
            {"position": "BOTTOM_AXIS", "title": "Month"},
            {"position": "LEFT_AXIS", "title": "Revenue"},
        ]

    def test_only_the_supplied_axis_title_is_emitted(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart(y_axis_title="Revenue"))

        assert _chart_request(api)["spec"]["basicChart"]["axis"] == [
            {"position": "LEFT_AXIS", "title": "Revenue"}
        ]

    def test_axis_key_is_absent_without_titles(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart())
        assert "axis" not in _chart_request(api)["spec"]["basicChart"]

    def test_title_sits_on_the_chart_spec(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart(title="Monthly Revenue"))
        assert _chart_request(api)["spec"]["title"] == "Monthly Revenue"

    def test_pie_chart_also_accepts_a_title(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart(chart_type="PIE", title="Split"))
        assert _chart_request(api)["spec"]["title"] == "Split"

    def test_title_key_is_absent_when_unset(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart())
        assert "title" not in _chart_request(api)["spec"]

    def test_chart_is_anchored_at_the_requested_cell(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart(anchor_cell="G5"))

        overlay = _chart_request(api)["position"]["overlayPosition"]
        assert overlay["anchorCell"] == {"sheetId": 111, "rowIndex": 4, "columnIndex": 6}

    def test_default_anchor_is_column_e_row_one(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart())

        anchor = _chart_request(api)["position"]["overlayPosition"]["anchorCell"]
        assert (anchor["rowIndex"], anchor["columnIndex"]) == (0, 4)

    # BUG: the anchor went through parse_a1_range, so an open-ended reference
    # silently became A1 instead of failing.
    def test_open_ended_anchor_is_rejected(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="Not a single cell reference"):
            _call(tools, "CUSTOM_CREATE_CHART", _chart(anchor_cell="E"))

    def test_dimensions_are_forwarded_in_pixels(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart(width=800, height=300))

        overlay = _chart_request(api)["position"]["overlayPosition"]
        assert overlay["widthPixels"] == 800
        assert overlay["heightPixels"] == 300

    def test_default_dimensions_are_used_when_unset(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart())

        overlay = _chart_request(api)["position"]["overlayPosition"]
        assert (overlay["widthPixels"], overlay["heightPixels"]) == (600, 400)

    @pytest.mark.parametrize("dimension", ["width", "height"])
    @pytest.mark.parametrize("value", [99, 2001])
    def test_out_of_range_dimensions_are_rejected(self, dimension: str, value: int) -> None:
        with pytest.raises(ValidationError):
            _chart(**{dimension: value})

    def test_chart_defaults_to_the_source_sheet(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart())

        anchor = _chart_request(api)["position"]["overlayPosition"]["anchorCell"]
        assert anchor["sheetId"] == 111

    def test_chart_can_be_placed_on_another_sheet(self, tools: Any, api: Any) -> None:
        _call(tools, "CUSTOM_CREATE_CHART", _chart(destination_sheet_name="Report"))

        chart = _chart_request(api)
        assert chart["position"]["overlayPosition"]["anchorCell"]["sheetId"] == 222
        # The data still comes from the source sheet.
        assert (
            chart["spec"]["basicChart"]["domains"][0]["domain"]["sourceRange"]["sources"][0][
                "sheetId"
            ]
            == 111
        )

    def test_missing_source_sheet_is_named_in_the_error(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="Sheet 'Ghost' not found"):
            _call(tools, "CUSTOM_CREATE_CHART", _chart(sheet_name="Ghost"))

    def test_missing_destination_sheet_is_named_in_the_error(self, tools: Any, api: Any) -> None:
        with pytest.raises(ValueError, match="Destination sheet 'Ghost' not found"):
            _call(tools, "CUSTOM_CREATE_CHART", _chart(destination_sheet_name="Ghost"))

    def test_chart_id_is_read_from_the_batch_reply(self, tools: Any, api: Any) -> None:
        api.batch_response = {"replies": [{"addChart": {"chart": {"chartId": 987}}}]}
        result = _call(tools, "CUSTOM_CREATE_CHART", _chart())

        assert result == {
            "spreadsheet_id": SPREADSHEET,
            "url": EXPECTED_URL,
            "chart_id": 987,
            "chart_type": "COLUMN",
        }

    def test_unrelated_replies_are_skipped_when_finding_the_chart(
        self, tools: Any, api: Any
    ) -> None:
        api.batch_response = {
            "replies": [{}, {"addSheet": {}}, {"addChart": {"chart": {"chartId": 5}}}]
        }
        assert _call(tools, "CUSTOM_CREATE_CHART", _chart())["chart_id"] == 5

    @pytest.mark.parametrize("response", [None, {}, {"replies": []}, {"replies": [{}]}])
    def test_absent_chart_id_is_reported_as_none(self, tools: Any, api: Any, response: Any) -> None:
        api.batch_response = response
        assert _call(tools, "CUSTOM_CREATE_CHART", _chart())["chart_id"] is None

    def test_batch_failure_is_reported_with_the_provider_message(
        self, tools: Any, api: Any
    ) -> None:
        api.batch_error = AppError(message="Bad chart spec", why="w", status_code=400)
        with pytest.raises(RuntimeError, match="Failed to create chart: Bad chart spec"):
            _call(tools, "CUSTOM_CREATE_CHART", _chart())


# ---------------------------------------------------------------------------
# CUSTOM_GATHER_CONTEXT
# ---------------------------------------------------------------------------


class TestGatherContext:
    def test_maps_drive_files_onto_the_context_shape(self, tools: Any, api: Any) -> None:
        api.files = {
            "files": [
                {
                    "id": "f1",
                    "name": "Budget",
                    "modifiedTime": "2026-01-15T10:00:00Z",
                    "webViewLink": "https://example.com/f1",
                }
            ]
        }
        result = _call(tools, "CUSTOM_GATHER_CONTEXT", GatherContextInput())

        assert result == {
            "recent_spreadsheets": [
                {
                    "id": "f1",
                    "name": "Budget",
                    "modified": "2026-01-15T10:00:00Z",
                    "url": "https://example.com/f1",
                }
            ],
            "spreadsheet_count": 1,
        }

    def test_queries_drive_for_recent_spreadsheets_only(self, tools: Any, api: Any) -> None:
        api.files = {"files": []}
        _call(tools, "CUSTOM_GATHER_CONTEXT", GatherContextInput())

        call = api.calls[0]
        assert call["endpoint"] == f"{DRIVE_API_BASE}/files"
        assert call["method"] == "GET"
        assert call["query"] == {
            "q": "mimeType='application/vnd.google-apps.spreadsheet'",
            "orderBy": "viewedByMeTime desc",
            "pageSize": RECENT_SPREADSHEETS_PAGE_SIZE,
            "fields": "files(id,name,modifiedTime,webViewLink)",
        }

    def test_missing_file_attributes_become_none(self, tools: Any, api: Any) -> None:
        api.files = {"files": [{"id": "f1"}]}
        result = _call(tools, "CUSTOM_GATHER_CONTEXT", GatherContextInput())

        assert result["recent_spreadsheets"] == [
            {"id": "f1", "name": None, "modified": None, "url": None}
        ]

    @pytest.mark.parametrize("payload", [None, {}, {"files": []}])
    def test_empty_drive_payloads_yield_an_empty_snapshot(
        self, tools: Any, api: Any, payload: Any
    ) -> None:
        api.files = payload
        result = _call(tools, "CUSTOM_GATHER_CONTEXT", GatherContextInput())

        assert result == {"recent_spreadsheets": [], "spreadsheet_count": 0}

    def test_count_tracks_the_returned_list(self, tools: Any, api: Any) -> None:
        api.files = {"files": [{"id": "f1"}, {"id": "f2"}, {"id": "f3"}]}
        result = _call(tools, "CUSTOM_GATHER_CONTEXT", GatherContextInput())

        assert result["spreadsheet_count"] == len(result["recent_spreadsheets"]) == 3

    def test_a_disconnected_integration_degrades_to_an_empty_snapshot(
        self, tools: Any, api: Any
    ) -> None:
        # gather_context is a best-effort situational snapshot shared by every
        # integration: it must never break the turn when the account is not
        # connected.
        api.files_error = AppError(message="No active connection", why="w", status_code=403)
        result = _call(tools, "CUSTOM_GATHER_CONTEXT", GatherContextInput())

        assert result == {"recent_spreadsheets": [], "spreadsheet_count": 0}

    def test_unexpected_errors_also_degrade_rather_than_raise(self, tools: Any, api: Any) -> None:
        api.files_error = TimeoutError("drive timeout")
        result = _call(tools, "CUSTOM_GATHER_CONTEXT", GatherContextInput())

        assert result["spreadsheet_count"] == 0

    def test_missing_user_id_still_fails_loudly(self, tools: Any, api: Any) -> None:
        # The credential check runs before the guarded fetch, so a broken call
        # is not hidden by the best-effort handling above.
        with pytest.raises(ValueError, match="Missing user_id"):
            tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), MagicMock(), {})
