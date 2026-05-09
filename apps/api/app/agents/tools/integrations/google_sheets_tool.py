"""Google Sheets tools using Composio custom tool infrastructure.

Provider API calls go through Composio's proxy via `proxy_request_sync`.
Drive API is used for sharing; Sheets API for spreadsheet operations.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any, Dict, List, Optional

from shared.py.wide_events import log
from app.decorators import with_doc
from app.models.common_models import GatherContextInput
from app.models.google_sheets_models import (
    ChartInput,
    ConditionalFormatInput,
    CreatePivotTableInput,
    DataValidationInput,
    ShareSpreadsheetInput,
)
from app.services.composio.proxy_client import proxy_request_sync
from app.templates.docstrings.google_sheets_tool_docs import (
    CUSTOM_ADD_CONDITIONAL_FORMAT_DOC as CONDITIONAL_FORMAT_DOC,
)
from app.templates.docstrings.google_sheets_tool_docs import (
    CUSTOM_CREATE_CHART_DOC as CREATE_CHART_DOC,
)
from app.templates.docstrings.google_sheets_tool_docs import (
    CUSTOM_CREATE_PIVOT_TABLE_DOC as CREATE_PIVOT_DOC,
)
from app.templates.docstrings.google_sheets_tool_docs import (
    CUSTOM_SET_DATA_VALIDATION_DOC as DATA_VALIDATION_DOC,
)
from app.templates.docstrings.google_sheets_tool_docs import (
    CUSTOM_SHARE_SPREADSHEET_DOC as SHARE_DOC,
)
from app.utils.errors import AppError
from app.utils.google_sheets_utils import (
    DRIVE_API_BASE,
    SHEETS_API_BASE,
    get_column_index_by_header,
    get_sheet_id_by_name,
    hex_to_rgb,
    parse_a1_range,
)
from composio import Composio

SHEETS_TOOLKIT = "GOOGLESHEETS"


def _user_id(auth_credentials: Dict[str, Any]) -> str:
    user_id = auth_credentials.get("user_id")
    if not user_id:
        raise ValueError("Missing user_id in auth_credentials")
    return user_id


def _sheets_proxy(
    user_id: str,
    *,
    endpoint: str,
    method: str,
    body: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, Any]] = None,
) -> Any:
    return proxy_request_sync(
        user_id=user_id,
        toolkit=SHEETS_TOOLKIT,
        endpoint=endpoint,
        method=method,  # type: ignore[arg-type]
        body=body,
        query=query,
    )


def register_google_sheets_custom_tools(composio: Composio) -> List[str]:
    """Register Google Sheets tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="GOOGLESHEETS")
    @with_doc(SHARE_DOC)
    def CUSTOM_SHARE_SPREADSHEET(
        request: ShareSpreadsheetInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Share a Google Spreadsheet with one or more recipients."""
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
                        "sendNotificationEmail": str(
                            recipient.send_notification
                        ).lower(),
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
                log.error(f"Error sharing with {recipient.email}: {e}")
                errors.append(
                    {
                        "email": recipient.email,
                        "role": recipient.role,
                        "error": f"Failed: {e.status_code} - {e.message}",
                    }
                )
            except Exception as e:
                log.error(f"Error sharing with {recipient.email}: {e}")
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
            "total_shared": len(shared),
            "total_failed": len(errors),
        }

    @composio.tools.custom_tool(toolkit="GOOGLESHEETS")
    @with_doc(CREATE_PIVOT_DOC)
    def CUSTOM_CREATE_PIVOT_TABLE(
        request: CreatePivotTableInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a pivot table from spreadsheet data."""
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
            raise ValueError(
                f"Destination sheet '{request.destination_sheet_name}' not found"
            )

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
            spec: Dict[str, Any] = {
                "sourceColumnOffset": idx,
                "summarizeFunction": val.aggregation,
            }
            if val.name:
                spec["name"] = val.name
            value_specs.append(spec)

        source_range: Dict[str, Any] = {"sheetId": source_sheet_id}
        if request.source_range:
            range_spec = parse_a1_range(request.source_range)
            source_range.update(range_spec)

        dest_range = parse_a1_range(request.destination_cell)

        pivot_table: Dict[str, Any] = {
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
                            "rowIndex": dest_range["startRowIndex"],
                            "columnIndex": dest_range["startColumnIndex"],
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
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Set data validation rules on a range."""
        log.set(tool={"integration": "google_sheets", "action": "set_data_validation"})
        user_id = _user_id(auth_credentials)

        sheet_id = get_sheet_id_by_name(
            request.spreadsheet_id, request.sheet_name, user_id
        )
        if sheet_id is None:
            raise ValueError(f"Sheet '{request.sheet_name}' not found")

        range_spec = parse_a1_range(request.range)
        range_spec["sheetId"] = sheet_id

        condition: Dict[str, Any] = {}

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
                raise ValueError(
                    "min_value or max_value required for number validation"
                )
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

        validation_rule: Dict[str, Any] = {
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
            log.error(f"Error setting data validation: {e.message}")
            raise RuntimeError(
                f"Failed to set data validation: {e.message}"
            ) from e

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
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Add conditional formatting rules to a range."""
        log.set(
            tool={"integration": "google_sheets", "action": "add_conditional_format"}
        )
        user_id = _user_id(auth_credentials)

        sheet_id = get_sheet_id_by_name(
            request.spreadsheet_id, request.sheet_name, user_id
        )
        if sheet_id is None:
            raise ValueError(f"Sheet '{request.sheet_name}' not found")

        range_spec = parse_a1_range(request.range)
        range_spec["sheetId"] = sheet_id

        rule: Dict[str, Any] = {"ranges": [range_spec]}

        if request.format_type == "color_scale":
            color_scale: Dict[str, Any] = {}

            if request.min_color:
                color_scale["minpoint"] = {
                    "type": "MIN",
                    "color": hex_to_rgb(request.min_color),
                }
            if request.mid_color:
                color_scale["midpoint"] = {
                    "type": "PERCENTILE",
                    "value": "50",
                    "color": hex_to_rgb(request.mid_color),
                }
            if request.max_color:
                color_scale["maxpoint"] = {
                    "type": "MAX",
                    "color": hex_to_rgb(request.max_color),
                }

            rule["gradientRule"] = {
                "minpoint": color_scale.get("minpoint"),
                "maxpoint": color_scale.get("maxpoint"),
            }
            if "midpoint" in color_scale:
                rule["gradientRule"]["midpoint"] = color_scale["midpoint"]

        else:
            bool_condition: Dict[str, Any] = {}

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

                api_condition = condition_map.get(request.condition)
                if not api_condition:
                    raise ValueError(f"Unknown condition: {request.condition}")

                bool_condition = {"type": api_condition}

                if request.condition not in ["is_empty", "is_not_empty"]:
                    if not request.condition_values:
                        raise ValueError("condition_values required")
                    bool_condition["values"] = [
                        {"userEnteredValue": v} for v in request.condition_values
                    ]

            format_spec: Dict[str, Any] = {}
            if request.background_color:
                format_spec["backgroundColor"] = hex_to_rgb(request.background_color)
            if request.text_color:
                format_spec["textFormat"] = {
                    "foregroundColor": hex_to_rgb(request.text_color)
                }
            if request.bold is not None:
                format_spec.setdefault("textFormat", {})["bold"] = request.bold
            if request.italic is not None:
                format_spec.setdefault("textFormat", {})["italic"] = request.italic

            rule["booleanRule"] = {
                "condition": bool_condition,
                "format": format_spec,
            }

        batch_request = {
            "requests": [
                {
                    "addConditionalFormatRule": {
                        "rule": rule,
                        "index": 0,
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
        }

    @composio.tools.custom_tool(toolkit="GOOGLESHEETS")
    @with_doc(CREATE_CHART_DOC)
    def CUSTOM_CREATE_CHART(
        request: ChartInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a chart from spreadsheet data."""
        log.set(tool={"integration": "google_sheets", "action": "create_chart"})
        user_id = _user_id(auth_credentials)

        source_sheet_id = get_sheet_id_by_name(
            request.spreadsheet_id, request.sheet_name, user_id
        )
        if source_sheet_id is None:
            raise ValueError(f"Sheet '{request.sheet_name}' not found")

        dest_sheet_name = request.destination_sheet_name or request.sheet_name
        dest_sheet_id = get_sheet_id_by_name(
            request.spreadsheet_id, dest_sheet_name, user_id
        )
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

        anchor = parse_a1_range(request.anchor_cell)

        chart_type_map = {
            "BAR": "BAR",
            "COLUMN": "COLUMN",
            "LINE": "LINE",
            "AREA": "AREA",
            "SCATTER": "SCATTER",
            "COMBO": "COMBO",
            "PIE": "PIE",
        }

        api_chart_type = chart_type_map.get(request.chart_type, "BAR")

        if request.chart_type == "PIE":
            chart_spec: Dict[str, Any] = {
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
                    "chartType": api_chart_type,
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
                chart_spec["basicChart"]["axis"] = []
                if request.x_axis_title:
                    chart_spec["basicChart"]["axis"].append(
                        {
                            "position": "BOTTOM_AXIS",
                            "title": request.x_axis_title,
                        }
                    )
                if request.y_axis_title:
                    chart_spec["basicChart"]["axis"].append(
                        {
                            "position": "LEFT_AXIS",
                            "title": request.y_axis_title,
                        }
                    )

        if request.title:
            chart_spec["title"] = request.title

        chart_request = {
            "chart": {
                "spec": chart_spec,
                "position": {
                    "overlayPosition": {
                        "anchorCell": {
                            "sheetId": dest_sheet_id,
                            "rowIndex": anchor["startRowIndex"],
                            "columnIndex": anchor["startColumnIndex"],
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
            log.error(f"Error creating chart: {e.message}")
            raise RuntimeError(f"Failed to create chart: {e.message}") from e

        chart_id = None
        for reply in (result or {}).get("replies", []):
            if "addChart" in reply:
                chart_id = reply["addChart"]["chart"]["chartId"]
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
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Google Sheets context snapshot: recently viewed/modified spreadsheets.

        Zero required parameters. Returns user's recently accessed spreadsheets.
        """
        log.set(tool={"integration": "google_sheets", "action": "gather_context"})
        user_id = _user_id(auth_credentials)

        mime = "application/vnd.google-apps.spreadsheet"
        files: List[Dict[str, Any]] = []
        try:
            data = _sheets_proxy(
                user_id,
                endpoint=f"{DRIVE_API_BASE}/files",
                method="GET",
                query={
                    "q": f"mimeType='{mime}'",
                    "orderBy": "viewedByMeTime desc",
                    "pageSize": 20,
                    "fields": "files(id,name,modifiedTime,webViewLink)",
                },
            )
            files = [
                {
                    "id": f.get("id"),
                    "name": f.get("name"),
                    "modified": f.get("modifiedTime"),
                    "url": f.get("webViewLink"),
                }
                for f in (data or {}).get("files", [])
            ]
        except Exception as e:
            log.debug(f"Google Sheets fetch failed: {e}")

        return {"recent_spreadsheets": files, "spreadsheet_count": len(files)}

    return [
        "GOOGLESHEETS_CUSTOM_SHARE_SPREADSHEET",
        "GOOGLESHEETS_CUSTOM_CREATE_PIVOT_TABLE",
        "GOOGLESHEETS_CUSTOM_SET_DATA_VALIDATION",
        "GOOGLESHEETS_CUSTOM_ADD_CONDITIONAL_FORMAT",
        "GOOGLESHEETS_CUSTOM_CREATE_CHART",
        "GOOGLESHEETS_CUSTOM_GATHER_CONTEXT",
    ]
