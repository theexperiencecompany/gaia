"""Google Sheets tools using Composio custom tool infrastructure.

Provider API calls go through Composio's proxy via `proxy_request_sync`.
Drive API is used for sharing; Sheets API for spreadsheet operations.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from collections.abc import Mapping
from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.decorators import with_doc
from app.models.common_models import GatherContextInput
from app.models.google_sheets_models import (
    ChartInput,
    ConditionalFormatInput,
    CreatePivotTableInput,
    DataValidationInput,
    ShareSpreadsheetInput,
)
from app.services.composio.proxy_client import ProxyMethod, proxy_request_sync
from app.templates.docstrings.google_sheets_tool_docs import (
    CUSTOM_ADD_CONDITIONAL_FORMAT_DOC as CONDITIONAL_FORMAT_DOC,
    CUSTOM_CREATE_CHART_DOC as CREATE_CHART_DOC,
    CUSTOM_CREATE_PIVOT_TABLE_DOC as CREATE_PIVOT_DOC,
    CUSTOM_SET_DATA_VALIDATION_DOC as DATA_VALIDATION_DOC,
    CUSTOM_SHARE_SPREADSHEET_DOC as SHARE_DOC,
)
from app.utils.errors import AppError
from app.utils.google_sheets_utils import (
    DRIVE_API_BASE,
    SHEETS_API_BASE,
    SheetsGridRange,
    get_column_index_by_header,
    get_sheet_id_by_name,
    hex_to_rgb,
    parse_a1_anchor,
    parse_a1_range,
)
from app.utils.json_helpers import dict_bag, list_bag, text_opt_bag
from shared.py.wide_events import log

SHEETS_TOOLKIT = "GOOGLESHEETS"

# New conditional-format rules go to the front so they win over existing rules.
NEW_FORMAT_RULE_INDEX = 0

RECENT_SPREADSHEETS_PAGE_SIZE = 20


def _user_id(auth_credentials: dict[str, object]) -> str:
    user_id = auth_credentials.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("Missing user_id in auth_credentials")
    return user_id


def _sheets_proxy(
    user_id: str,
    *,
    endpoint: str,
    method: ProxyMethod,
    body: Mapping[str, object] | None = None,
    query: dict[str, object] | None = None,
) -> dict[str, object]:
    # proxy_request_sync returns object; every call site here treats the
    # Sheets/Drive proxy response as a JSON object, so narrow it once here.
    # proxy_request_sync returns object; every call site here treats the
    # Sheets/Drive proxy response as a JSON object, so narrow it once here —
    # and fail loud instead of masking a non-object payload as an empty dict,
    # which would make every caller report success on nothing.
    response = proxy_request_sync(
        user_id=user_id,
        toolkit=SHEETS_TOOLKIT,
        endpoint=endpoint,
        method=method,
        body=body,
        query=query,
    )
    if response is None:
        # A proxy response without a ``data`` key — callers degrade the missing
        # fields to None (e.g. an absent permission id).
        return {}
    if not isinstance(response, dict):
        raise AppError(
            message=f"Sheets proxy returned a non-object payload ({type(response).__name__})",
            why="the Sheets/Drive proxy response is a JSON object on every supported path",
            fix="inspect the proxied endpoint's response shape",
        )
    return response


def register_google_sheets_custom_tools(composio: Composio[Any, Any]) -> list[str]:  # type: ignore[explicit-any]
    """Register Google Sheets tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="GOOGLESHEETS")
    @with_doc(SHARE_DOC)
    def CUSTOM_SHARE_SPREADSHEET(
        request: ShareSpreadsheetInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Share a Google Spreadsheet with one or more recipients."""
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_sheets", "action": "share_spreadsheet"})
        user_id = _user_id(auth_credentials)

        shared = []
        errors = []

        for recipient in request.recipients:
            try:
                result = _sheets_proxy(
                    user_id,
                    endpoint=f"{DRIVE_API_BASE}/files/{request.spreadsheet_id}/permissions",
                    method="POST",
                    body={
                        "type": "user",
                        "role": recipient.role,
                        "emailAddress": recipient.email,
                    },
                    query={
                        "sendNotificationEmail": str(recipient.send_notification).lower(),
                    },
                )
                shared.append(
                    {
                        "email": recipient.email,
                        "role": recipient.role,
                        "permission_id": (result or {}).get("id"),
                        "notification_sent": recipient.send_notification,
                    }
                )
            except AppError as e:
                log.error(
                    f"{LogTag.TOOL} Error sharing sheet with recipient", error_type=type(e).__name__
                )
                errors.append(
                    {
                        "email": recipient.email,
                        "role": recipient.role,
                        "error": f"Failed: {e.status_code} - {e.message}",
                    }
                )
            except Exception as e:
                log.error(
                    f"{LogTag.TOOL} Error sharing sheet with recipient", error_type=type(e).__name__
                )
                errors.append(
                    {
                        "email": recipient.email,
                        "role": recipient.role,
                        "error": str(e),
                    }
                )

        if shared == [] and errors:
            raise RuntimeError(f"Failed to share spreadsheet: {errors}")

        url = f"https://docs.google.com/spreadsheets/d/{request.spreadsheet_id}/edit"

        return {
            "spreadsheet_id": request.spreadsheet_id,
            "url": url,
            "shared": shared,
            # Without this a partial failure reports only `total_failed`, leaving
            # no way to tell the user which recipient failed or why.
            "errors": errors,
            "total_shared": len(shared),
            "total_failed": len(errors),
        }

    @composio.tools.custom_tool(toolkit="GOOGLESHEETS")
    @with_doc(CREATE_PIVOT_DOC)
    def CUSTOM_CREATE_PIVOT_TABLE(
        request: CreatePivotTableInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Create a pivot table from spreadsheet data."""
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_sheets", "action": "create_pivot_table"})
        user_id = _user_id(auth_credentials)

        source_sheet_id = get_sheet_id_by_name(
            request.spreadsheet_id, request.source_sheet_name, user_id
        )
        dest_sheet_id = get_sheet_id_by_name(
            request.spreadsheet_id, request.destination_sheet_name, user_id
        )

        if source_sheet_id is None:
            raise ValueError(f"Source sheet '{request.source_sheet_name}' not found")
        if dest_sheet_id is None:
            raise ValueError(f"Destination sheet '{request.destination_sheet_name}' not found")

        row_indices = []
        for row_field in request.rows:
            idx = get_column_index_by_header(
                request.spreadsheet_id,
                request.source_sheet_name,
                row_field,
                user_id,
            )
            if idx is None:
                raise ValueError(f"Column '{row_field}' not found in headers")
            row_indices.append(
                {
                    "sourceColumnOffset": idx,
                    "sortOrder": "ASCENDING",
                    "showTotals": True,
                }
            )

        col_indices = []
        for col_field in request.columns:
            idx = get_column_index_by_header(
                request.spreadsheet_id,
                request.source_sheet_name,
                col_field,
                user_id,
            )
            if idx is None:
                raise ValueError(f"Column '{col_field}' not found")
            col_indices.append(
                {
                    "sourceColumnOffset": idx,
                    "sortOrder": "ASCENDING",
                    "showTotals": True,
                }
            )

        value_specs = []
        for val in request.values:
            idx = get_column_index_by_header(
                request.spreadsheet_id,
                request.source_sheet_name,
                val.column,
                user_id,
            )
            if idx is None:
                raise ValueError(f"Value column '{val.column}' not found")
            spec: dict[str, object] = {
                "sourceColumnOffset": idx,
                "summarizeFunction": val.aggregation,
            }
            if val.name:
                spec["name"] = val.name
            value_specs.append(spec)

        source_range: SheetsGridRange = {"sheetId": source_sheet_id}
        if request.source_range:
            range_spec = parse_a1_range(request.source_range)
            source_range.update(range_spec)

        dest_row, dest_col = parse_a1_anchor(request.destination_cell)

        pivot_table: dict[str, object] = {
            "source": source_range,
            "rows": row_indices,
            "values": value_specs,
        }
        if col_indices:
            pivot_table["columns"] = col_indices

        batch_request = {
            "requests": [
                {
                    "updateCells": {
                        "rows": [{"values": [{"pivotTable": pivot_table}]}],
                        "start": {
                            "sheetId": dest_sheet_id,
                            "rowIndex": dest_row,
                            "columnIndex": dest_col,
                        },
                        "fields": "pivotTable",
                    }
                }
            ]
        }

        _sheets_proxy(
            user_id,
            endpoint=f"{SHEETS_API_BASE}/{request.spreadsheet_id}:batchUpdate",
            method="POST",
            body=batch_request,
        )

        url = f"https://docs.google.com/spreadsheets/d/{request.spreadsheet_id}/edit"

        return {
            "spreadsheet_id": request.spreadsheet_id,
            "url": url,
            "pivot_sheet": request.destination_sheet_name,
            "source_range": (
                f"{request.source_sheet_name}!{request.source_range or 'entire sheet'}"
            ),
        }

    @composio.tools.custom_tool(toolkit="GOOGLESHEETS")
    @with_doc(DATA_VALIDATION_DOC)
    def CUSTOM_SET_DATA_VALIDATION(
        request: DataValidationInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Set data validation rules on a range."""
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_sheets", "action": "set_data_validation"})
        user_id = _user_id(auth_credentials)

        sheet_id = get_sheet_id_by_name(request.spreadsheet_id, request.sheet_name, user_id)
        if sheet_id is None:
            raise ValueError(f"Sheet '{request.sheet_name}' not found")

        range_spec = parse_a1_range(request.range)
        range_spec["sheetId"] = sheet_id

        condition: dict[str, object] = {}

        if request.validation_type == "dropdown_list":
            if not request.values:
                raise ValueError("values required for dropdown_list")
            condition = {
                "type": "ONE_OF_LIST",
                "values": [{"userEnteredValue": v} for v in request.values],
            }
        elif request.validation_type == "dropdown_range":
            if not request.source_range:
                raise ValueError("source_range required for dropdown_range")
            condition = {
                "type": "ONE_OF_RANGE",
                "values": [{"userEnteredValue": f"={request.source_range}"}],
            }
        elif request.validation_type == "number":
            if request.min_value is not None and request.max_value is not None:
                condition = {
                    "type": "NUMBER_BETWEEN",
                    "values": [
                        {"userEnteredValue": str(request.min_value)},
                        {"userEnteredValue": str(request.max_value)},
                    ],
                }
            elif request.min_value is not None:
                condition = {
                    "type": "NUMBER_GREATER_THAN_EQ",
                    "values": [{"userEnteredValue": str(request.min_value)}],
                }
            elif request.max_value is not None:
                condition = {
                    "type": "NUMBER_LESS_THAN_EQ",
                    "values": [{"userEnteredValue": str(request.max_value)}],
                }
            else:
                raise ValueError("min_value or max_value required for number validation")
        elif request.validation_type == "date":
            if request.min_value is not None and request.max_value is not None:
                condition = {
                    "type": "DATE_BETWEEN",
                    "values": [
                        {"userEnteredValue": str(request.min_value)},
                        {"userEnteredValue": str(request.max_value)},
                    ],
                }
            elif request.min_value is not None:
                condition = {
                    "type": "DATE_AFTER",
                    "values": [{"userEnteredValue": str(request.min_value)}],
                }
            elif request.max_value is not None:
                condition = {
                    "type": "DATE_BEFORE",
                    "values": [{"userEnteredValue": str(request.max_value)}],
                }
            else:
                raise ValueError("min_value or max_value required for date validation")
        elif request.validation_type == "custom_formula":
            if not request.formula:
                raise ValueError("formula required for custom_formula")
            condition = {
                "type": "CUSTOM_FORMULA",
                "values": [{"userEnteredValue": request.formula}],
            }

        validation_rule: dict[str, object] = {
            "condition": condition,
            "strict": request.strict,
            "showCustomUi": request.show_dropdown,
        }

        if request.input_message:
            validation_rule["inputMessage"] = request.input_message

        batch_request = {
            "requests": [
                {
                    "setDataValidation": {
                        "range": range_spec,
                        "rule": validation_rule,
                    }
                }
            ]
        }

        try:
            _sheets_proxy(
                user_id,
                endpoint=f"{SHEETS_API_BASE}/{request.spreadsheet_id}:batchUpdate",
                method="POST",
                body=batch_request,
            )
        except AppError as e:
            log.error(f"{LogTag.TOOL} Error setting data validation", error_type=type(e).__name__)
            raise RuntimeError(f"Failed to set data validation: {e.message}") from e

        url = f"https://docs.google.com/spreadsheets/d/{request.spreadsheet_id}/edit"

        return {
            "spreadsheet_id": request.spreadsheet_id,
            "url": url,
            "range_applied": f"{request.sheet_name}!{request.range}",
            "validation_type": request.validation_type,
        }

    @composio.tools.custom_tool(toolkit="GOOGLESHEETS")
    @with_doc(CONDITIONAL_FORMAT_DOC)
    def CUSTOM_ADD_CONDITIONAL_FORMAT(
        request: ConditionalFormatInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Add conditional formatting rules to a range."""
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_sheets", "action": "add_conditional_format"})
        user_id = _user_id(auth_credentials)

        sheet_id = get_sheet_id_by_name(request.spreadsheet_id, request.sheet_name, user_id)
        if sheet_id is None:
            raise ValueError(f"Sheet '{request.sheet_name}' not found")

        range_spec = parse_a1_range(request.range)
        range_spec["sheetId"] = sheet_id

        rule: dict[str, object] = {"ranges": [range_spec]}

        if request.format_type == "color_scale":
            # Google requires both endpoints on a gradient rule; sending nulls
            # for a missing colour gets the whole batch rejected.
            if not request.min_color or not request.max_color:
                raise ValueError("min_color and max_color are required for color_scale")

            gradient_rule: dict[str, object] = {
                "minpoint": {"type": "MIN", "color": hex_to_rgb(request.min_color)},
                "maxpoint": {"type": "MAX", "color": hex_to_rgb(request.max_color)},
            }
            if request.mid_color:
                gradient_rule["midpoint"] = {
                    "type": "PERCENTILE",
                    "value": "50",
                    "color": hex_to_rgb(request.mid_color),
                }
            rule["gradientRule"] = gradient_rule

        else:
            bool_condition: dict[str, object] = {}

            if request.format_type == "custom_formula":
                if not request.formula:
                    raise ValueError("formula required for custom_formula")
                bool_condition = {
                    "type": "CUSTOM_FORMULA",
                    "values": [{"userEnteredValue": request.formula}],
                }
            else:
                condition_map = {
                    "greater_than": "NUMBER_GREATER",
                    "less_than": "NUMBER_LESS",
                    "equal_to": "NUMBER_EQ",
                    "not_equal_to": "NUMBER_NOT_EQ",
                    "contains": "TEXT_CONTAINS",
                    "not_contains": "TEXT_NOT_CONTAINS",
                    "between": "NUMBER_BETWEEN",
                    "is_empty": "BLANK",
                    "is_not_empty": "NOT_BLANK",
                }

                if not request.condition:
                    raise ValueError("condition required for value_based")

                bool_condition = {"type": condition_map[request.condition]}

                if request.condition not in ["is_empty", "is_not_empty"]:
                    expected = 2 if request.condition == "between" else 1
                    values = request.condition_values or []
                    if len(values) != expected:
                        raise ValueError(
                            f"'{request.condition}' requires exactly {expected} "
                            f"condition_values, got {len(values)}"
                        )
                    bool_condition["values"] = [{"userEnteredValue": v} for v in values]

            format_spec: dict[str, object] = {}
            if request.background_color:
                format_spec["backgroundColor"] = hex_to_rgb(request.background_color)
            text_format: dict[str, object] = {}
            if request.text_color:
                text_format["foregroundColor"] = hex_to_rgb(request.text_color)
            if request.bold is not None:
                text_format["bold"] = request.bold
            if request.italic is not None:
                text_format["italic"] = request.italic
            if text_format:
                format_spec["textFormat"] = text_format

            # A rule with no format is a no-op Google accepts silently, so the
            # user is told the formatting was applied and then sees nothing.
            if not format_spec:
                raise ValueError(
                    "At least one of background_color, text_color, bold or italic "
                    "is required to format matching cells"
                )

            rule["booleanRule"] = {
                "condition": bool_condition,
                "format": format_spec,
            }

        batch_request = {
            "requests": [
                {
                    "addConditionalFormatRule": {
                        "rule": rule,
                        "index": NEW_FORMAT_RULE_INDEX,
                    }
                }
            ]
        }

        _sheets_proxy(
            user_id,
            endpoint=f"{SHEETS_API_BASE}/{request.spreadsheet_id}:batchUpdate",
            method="POST",
            body=batch_request,
        )

        url = f"https://docs.google.com/spreadsheets/d/{request.spreadsheet_id}/edit"

        return {
            "spreadsheet_id": request.spreadsheet_id,
            "url": url,
            "range_applied": f"{request.sheet_name}!{request.range}",
            "format_type": request.format_type,
            "rule_index": NEW_FORMAT_RULE_INDEX,
        }

    @composio.tools.custom_tool(toolkit="GOOGLESHEETS")
    @with_doc(CREATE_CHART_DOC)
    def CUSTOM_CREATE_CHART(
        request: ChartInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Create a chart from spreadsheet data."""
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_sheets", "action": "create_chart"})
        user_id = _user_id(auth_credentials)

        source_sheet_id = get_sheet_id_by_name(request.spreadsheet_id, request.sheet_name, user_id)
        if source_sheet_id is None:
            raise ValueError(f"Sheet '{request.sheet_name}' not found")

        dest_sheet_name = request.destination_sheet_name or request.sheet_name
        dest_sheet_id = get_sheet_id_by_name(request.spreadsheet_id, dest_sheet_name, user_id)
        if dest_sheet_id is None:
            raise ValueError(f"Destination sheet '{dest_sheet_name}' not found")

        range_spec = parse_a1_range(request.data_range)

        start_col = range_spec.get("startColumnIndex", 0)
        end_col = range_spec.get("endColumnIndex", start_col + 1)
        width = end_col - start_col

        if width > 1:
            domain_range = dict(range_spec)
            domain_range["endColumnIndex"] = start_col + 1
            domain_range["sheetId"] = source_sheet_id

            series_ranges = []
            for i in range(start_col + 1, end_col):
                s_range = dict(range_spec)
                s_range["startColumnIndex"] = i
                s_range["endColumnIndex"] = i + 1
                s_range["sheetId"] = source_sheet_id
                series_ranges.append(s_range)
        else:
            r_spec = dict(range_spec)
            r_spec["sheetId"] = source_sheet_id
            domain_range = r_spec
            series_ranges = [r_spec]

        anchor_row, anchor_col = parse_a1_anchor(request.anchor_cell)

        if request.chart_type == "PIE":
            chart_spec: dict[str, object] = {
                "pieChart": {
                    "legendPosition": request.legend_position,
                    "domain": {
                        "sourceRange": {"sources": [domain_range]},
                    },
                    "series": {
                        "sourceRange": {"sources": [series_ranges[0]]},
                    },
                }
            }
        else:
            series_list = []
            for s_range in series_ranges:
                series_list.append(
                    {
                        "series": {
                            "sourceRange": {"sources": [s_range]},
                        },
                        "targetAxis": "LEFT_AXIS",
                    }
                )

            chart_spec = {
                "basicChart": {
                    "chartType": request.chart_type,
                    "legendPosition": request.legend_position,
                    "domains": [
                        {
                            "domain": {
                                "sourceRange": {"sources": [domain_range]},
                            }
                        }
                    ],
                    "series": series_list,
                    "headerCount": 1,
                }
            }

            if request.x_axis_title or request.y_axis_title:
                basic_chart = dict_bag(chart_spec, "basicChart")
                axis: list[object] = []
                if request.x_axis_title:
                    axis.append(
                        {
                            "position": "BOTTOM_AXIS",
                            "title": request.x_axis_title,
                        }
                    )
                if request.y_axis_title:
                    axis.append(
                        {
                            "position": "LEFT_AXIS",
                            "title": request.y_axis_title,
                        }
                    )
                basic_chart["axis"] = axis

        if request.title:
            chart_spec["title"] = request.title

        chart_request = {
            "chart": {
                "spec": chart_spec,
                "position": {
                    "overlayPosition": {
                        "anchorCell": {
                            "sheetId": dest_sheet_id,
                            "rowIndex": anchor_row,
                            "columnIndex": anchor_col,
                        },
                        "widthPixels": request.width,
                        "heightPixels": request.height,
                    }
                },
            }
        }

        batch_request = {"requests": [{"addChart": chart_request}]}

        try:
            result = _sheets_proxy(
                user_id,
                endpoint=f"{SHEETS_API_BASE}/{request.spreadsheet_id}:batchUpdate",
                method="POST",
                body=batch_request,
            )
        except AppError as e:
            log.error(f"{LogTag.TOOL} Error creating chart", error_type=type(e).__name__)
            raise RuntimeError(f"Failed to create chart: {e.message}") from e

        chart_id: object | None = None
        for reply in list_bag(result or {}, "replies"):
            if not isinstance(reply, dict):
                continue
            add_chart = dict_bag(reply, "addChart")
            if not add_chart:
                continue
            chart_id = dict_bag(add_chart, "chart").get("chartId")
            break

        url = f"https://docs.google.com/spreadsheets/d/{request.spreadsheet_id}/edit"

        return {
            "spreadsheet_id": request.spreadsheet_id,
            "url": url,
            "chart_id": chart_id,
            "chart_type": request.chart_type,
        }

    @composio.tools.custom_tool(toolkit="GOOGLESHEETS")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Google Sheets context snapshot: recently viewed/modified spreadsheets.

        Zero required parameters. Returns user's recently accessed spreadsheets.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_sheets", "action": "gather_context"})
        user_id = _user_id(auth_credentials)

        mime = "application/vnd.google-apps.spreadsheet"
        files: list[dict[str, object]] = []
        try:
            data = _sheets_proxy(
                user_id,
                endpoint=f"{DRIVE_API_BASE}/files",
                method="GET",
                query={
                    "q": f"mimeType='{mime}'",
                    "orderBy": "viewedByMeTime desc",
                    "pageSize": RECENT_SPREADSHEETS_PAGE_SIZE,
                    "fields": "files(id,name,modifiedTime,webViewLink)",
                },
            )
            files = [
                {
                    "id": text_opt_bag(f, "id"),
                    "name": text_opt_bag(f, "name"),
                    "modified": text_opt_bag(f, "modifiedTime"),
                    "url": text_opt_bag(f, "webViewLink"),
                }
                for f in list_bag(data or {}, "files")
                if isinstance(f, dict)
            ]
        except Exception as e:
            log.debug(f"{LogTag.TOOL} Google Sheets fetch failed", error_type=type(e).__name__)

        return {"recent_spreadsheets": files, "spreadsheet_count": len(files)}

    return [
        "GOOGLESHEETS_CUSTOM_SHARE_SPREADSHEET",
        "GOOGLESHEETS_CUSTOM_CREATE_PIVOT_TABLE",
        "GOOGLESHEETS_CUSTOM_SET_DATA_VALIDATION",
        "GOOGLESHEETS_CUSTOM_ADD_CONDITIONAL_FORMAT",
        "GOOGLESHEETS_CUSTOM_CREATE_CHART",
        "GOOGLESHEETS_CUSTOM_GATHER_CONTEXT",
    ]
