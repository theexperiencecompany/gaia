"""Google Sheets tools using Composio custom tool infrastructure.

These tools provide Google Sheets functionality using the access_token from Composio's
auth_credentials. Uses Google Drive API for sharing and Sheets API for spreadsheet operations.
"""

from typing import Any, Dict, List, Optional

import httpx
from app.config.loggers import chat_logger as logger
from app.decorators import with_doc
from app.models.google_sheets_models import (
    ChartInput,
    ConditionalFormatInput,
    CreatePivotTableInput,
    DataValidationInput,
    ShareSpreadsheetInput,
)
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
from composio import Composio

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=60)


def _get_access_token(auth_credentials: Dict[str, Any]) -> str:
    """Extract access token from auth_credentials."""
    token = auth_credentials.get("access_token")
    if not token:
        raise ValueError("Missing access_token in auth_credentials")
    return token


def _auth_headers(access_token: str) -> Dict[str, str]:
    """Return Bearer token header for Google APIs."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _hex_to_rgb(hex_color: str) -> Dict[str, float]:
    """Convert hex color (#RRGGBB) to Google API RGB format (0-1 floats)."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return {"red": r, "green": g, "blue": b}


def _parse_a1_range(range_str: str) -> Dict[str, int]:
    """Parse A1 notation (e.g., 'A1:B10') to row/column indices."""
    import re

    # Handle ranges like "A1:B10" or single cells like "A1"
    parts = range_str.replace("$", "").upper().split(":")
    start = parts[0]
    end = parts[1] if len(parts) > 1 else parts[0]

    def parse_cell(cell: str) -> tuple:
        match = re.match(r"([A-Z]+)(\d+)", cell)
        if not match:
            return 0, 0
        col_str, row_str = match.groups()
        col = (
            sum(
                (ord(c) - ord("A") + 1) * (26**i)
                for i, c in enumerate(reversed(col_str))
            )
            - 1
        )
        row = int(row_str) - 1
        return row, col

    start_row, start_col = parse_cell(start)
    end_row, end_col = parse_cell(end)

    return {
        "startRowIndex": start_row,
        "endRowIndex": end_row + 1,
        "startColumnIndex": start_col,
        "endColumnIndex": end_col + 1,
    }


def _get_sheet_id_by_name(
    spreadsheet_id: str, sheet_name: str, headers: Dict[str, str]
) -> Optional[int]:
    """Get sheet ID by its name."""
    try:
        resp = _http_client.get(
            f"{SHEETS_API_BASE}/{spreadsheet_id}",
            headers=headers,
            params={"fields": "sheets.properties"},
        )
        resp.raise_for_status()
        data = resp.json()
        for sheet in data.get("sheets", []):
            if sheet.get("properties", {}).get("title") == sheet_name:
                return sheet["properties"]["sheetId"]
        return None
    except Exception as e:
        logger.error(f"Error getting sheet ID: {e}")
        return None


def _get_column_index_by_header(
    spreadsheet_id: str,
    sheet_name: str,
    column_name: str,
    headers: Dict[str, str],
) -> Optional[int]:
    """Get column index by header name (first row)."""
    try:
        resp = _http_client.get(
            f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{sheet_name}!1:1",
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        header_row = data.get("values", [[]])[0]
        for idx, header in enumerate(header_row):
            if header.lower() == column_name.lower():
                return idx
        return None
    except Exception as e:
        logger.error(f"Error getting column index: {e}")
        return None


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
        access_token = _get_access_token(auth_credentials)
        headers = _auth_headers(access_token)

        shared = []
        errors = []

        for recipient in request.recipients:
            permission = {
                "type": "user",
                "role": recipient.role,
                "emailAddress": recipient.email,
            }

            url = f"{DRIVE_API_BASE}/files/{request.spreadsheet_id}/permissions"
            params = {"sendNotificationEmail": str(recipient.send_notification).lower()}

            try:
                resp = _http_client.post(
                    url, headers=headers, json=permission, params=params
                )
                resp.raise_for_status()
                result = resp.json()
                shared.append(
                    {
                        "email": recipient.email,
                        "role": recipient.role,
                        "permission_id": result.get("id"),
                        "notification_sent": recipient.send_notification,
                    }
                )
            except httpx.HTTPStatusError as e:
                logger.error(f"Error sharing with {recipient.email}: {e}")
                errors.append(
                    {
                        "email": recipient.email,
                        "role": recipient.role,
                        "error": f"Failed: {e.response.status_code} - {e.response.text}",
                    }
                )
            except Exception as e:
                logger.error(f"Error sharing with {recipient.email}: {e}")
                errors.append(
                    {
                        "email": recipient.email,
                        "role": recipient.role,
                        "error": str(e),
                    }
                )

        url = f"https://docs.google.com/spreadsheets/d/{request.spreadsheet_id}/edit"

        return {
            "success": len(errors) == 0,
            "spreadsheet_id": request.spreadsheet_id,
            "url": url,
            "shared": shared,
            "errors": errors if errors else None,
            "total_shared": len(shared),
            "total_failed": len(errors),
        }

    # ========================================================================
    # CUSTOM_CREATE_PIVOT_TABLE
    # ========================================================================
    @composio.tools.custom_tool(toolkit="GOOGLESHEETS")
    @with_doc(CREATE_PIVOT_DOC)
    def CUSTOM_CREATE_PIVOT_TABLE(
        request: CreatePivotTableInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a pivot table from spreadsheet data."""
        access_token = _get_access_token(auth_credentials)
        headers = _auth_headers(access_token)

        try:
            # Get source and destination sheet IDs
            source_sheet_id = _get_sheet_id_by_name(
                request.spreadsheet_id, request.source_sheet_name, headers
            )
            dest_sheet_id = _get_sheet_id_by_name(
                request.spreadsheet_id, request.destination_sheet_name, headers
            )

            if source_sheet_id is None:
                return {
                    "success": False,
                    "error": f"Source sheet '{request.source_sheet_name}' not found",
                }
            if dest_sheet_id is None:
                return {
                    "success": False,
                    "error": f"Destination sheet '{request.destination_sheet_name}' not found",
                }

            # Get column indices for row/column/value fields
            row_indices = []
            for row_field in request.rows:
                idx = _get_column_index_by_header(
                    request.spreadsheet_id,
                    request.source_sheet_name,
                    row_field,
                    headers,
                )
                if idx is None:
                    return {
                        "success": False,
                        "error": f"Column '{row_field}' not found in headers",
                    }
                row_indices.append(
                    {
                        "sourceColumnOffset": idx,
                        "sortOrder": "ASCENDING",
                        "showTotals": True,
                    }
                )

            col_indices = []
            for col_field in request.columns:
                idx = _get_column_index_by_header(
                    request.spreadsheet_id,
                    request.source_sheet_name,
                    col_field,
                    headers,
                )
                if idx is None:
                    return {
                        "success": False,
                        "error": f"Column '{col_field}' not found",
                    }
                col_indices.append(
                    {
                        "sourceColumnOffset": idx,
                        "sortOrder": "ASCENDING",
                        "showTotals": True,
                    }
                )

            value_specs = []
            for val in request.values:
                idx = _get_column_index_by_header(
                    request.spreadsheet_id,
                    request.source_sheet_name,
                    val.column,
                    headers,
                )
                if idx is None:
                    return {
                        "success": False,
                        "error": f"Value column '{val.column}' not found",
                    }
                spec: Dict[str, Any] = {
                    "sourceColumnOffset": idx,
                    "summarizeFunction": val.aggregation,
                }
                if val.name:
                    spec["name"] = val.name
                value_specs.append(spec)

            # Build source range
            source_range = {"sheetId": source_sheet_id}
            if request.source_range:
                range_spec = _parse_a1_range(request.source_range)
                source_range.update(range_spec)

            # Parse destination cell
            dest_range = _parse_a1_range(request.destination_cell)

            # Build pivot table request
            pivot_table = {
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

            resp = _http_client.post(
                f"{SHEETS_API_BASE}/{request.spreadsheet_id}:batchUpdate",
                headers=headers,
                json=batch_request,
            )
            resp.raise_for_status()

            url = (
                f"https://docs.google.com/spreadsheets/d/{request.spreadsheet_id}/edit"
            )

            return {
                "success": True,
                "spreadsheet_id": request.spreadsheet_id,
                "url": url,
                "pivot_sheet": request.destination_sheet_name,
                "source_range": f"{request.source_sheet_name}!{request.source_range or 'entire sheet'}",
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Error creating pivot table: {e}")
            return {
                "success": False,
                "error": f"API error: {e.response.status_code} - {e.response.text}",
            }
        except Exception as e:
            logger.error(f"Error creating pivot table: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="GOOGLESHEETS")
    @with_doc(DATA_VALIDATION_DOC)
    def CUSTOM_SET_DATA_VALIDATION(
        request: DataValidationInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Set data validation rules on a range."""
        access_token = _get_access_token(auth_credentials)
        headers = _auth_headers(access_token)

        try:
            sheet_id = _get_sheet_id_by_name(
                request.spreadsheet_id, request.sheet_name, headers
            )
            if sheet_id is None:
                return {
                    "success": False,
                    "error": f"Sheet '{request.sheet_name}' not found",
                }

            range_spec = _parse_a1_range(request.range)
            range_spec["sheetId"] = sheet_id

            # Build condition based on validation type
            condition: Dict[str, Any] = {}

            if request.validation_type == "dropdown_list":
                if not request.values:
                    return {
                        "success": False,
                        "error": "values required for dropdown_list",
                    }
                condition = {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": v} for v in request.values],
                }
            elif request.validation_type == "dropdown_range":
                if not request.source_range:
                    return {
                        "success": False,
                        "error": "source_range required for dropdown_range",
                    }
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
                    return {
                        "success": False,
                        "error": "min_value or max_value required for number validation",
                    }
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
                    return {
                        "success": False,
                        "error": "min_value or max_value required for date validation",
                    }
            elif request.validation_type == "custom_formula":
                if not request.formula:
                    return {
                        "success": False,
                        "error": "formula required for custom_formula",
                    }
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

            resp = _http_client.post(
                f"{SHEETS_API_BASE}/{request.spreadsheet_id}:batchUpdate",
                headers=headers,
                json=batch_request,
            )
            resp.raise_for_status()

            url = (
                f"https://docs.google.com/spreadsheets/d/{request.spreadsheet_id}/edit"
            )

            return {
                "success": True,
                "spreadsheet_id": request.spreadsheet_id,
                "url": url,
                "range_applied": f"{request.sheet_name}!{request.range}",
                "validation_type": request.validation_type,
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Error setting data validation: {e}")
            return {
                "success": False,
                "error": f"API error: {e.response.status_code} - {e.response.text}",
            }
        except Exception as e:
            logger.error(f"Error setting data validation: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="GOOGLESHEETS")
    @with_doc(CONDITIONAL_FORMAT_DOC)
    def CUSTOM_ADD_CONDITIONAL_FORMAT(
        request: ConditionalFormatInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Add conditional formatting rules to a range."""
        access_token = _get_access_token(auth_credentials)
        headers = _auth_headers(access_token)

        try:
            sheet_id = _get_sheet_id_by_name(
                request.spreadsheet_id, request.sheet_name, headers
            )
            if sheet_id is None:
                return {
                    "success": False,
                    "error": f"Sheet '{request.sheet_name}' not found",
                }

            range_spec = _parse_a1_range(request.range)
            range_spec["sheetId"] = sheet_id

            rule: Dict[str, Any] = {"ranges": [range_spec]}

            if request.format_type == "color_scale":
                # Build gradient rule
                color_scale: Dict[str, Any] = {}

                if request.min_color:
                    color_scale["minpoint"] = {
                        "type": "MIN",
                        "color": _hex_to_rgb(request.min_color),
                    }
                if request.mid_color:
                    color_scale["midpoint"] = {
                        "type": "PERCENTILE",
                        "value": "50",
                        "color": _hex_to_rgb(request.mid_color),
                    }
                if request.max_color:
                    color_scale["maxpoint"] = {
                        "type": "MAX",
                        "color": _hex_to_rgb(request.max_color),
                    }

                rule["gradientRule"] = {
                    "minpoint": color_scale.get("minpoint"),
                    "maxpoint": color_scale.get("maxpoint"),
                }
                if "midpoint" in color_scale:
                    rule["gradientRule"]["midpoint"] = color_scale["midpoint"]

            else:
                # Boolean rule (value_based or custom_formula)
                bool_condition: Dict[str, Any] = {}

                if request.format_type == "custom_formula":
                    if not request.formula:
                        return {
                            "success": False,
                            "error": "formula required for custom_formula",
                        }
                    bool_condition = {
                        "type": "CUSTOM_FORMULA",
                        "values": [{"userEnteredValue": request.formula}],
                    }
                else:  # value_based
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
                        return {
                            "success": False,
                            "error": "condition required for value_based",
                        }

                    api_condition = condition_map.get(request.condition)
                    if not api_condition:
                        return {
                            "success": False,
                            "error": f"Unknown condition: {request.condition}",
                        }

                    bool_condition = {"type": api_condition}

                    if request.condition not in ["is_empty", "is_not_empty"]:
                        if not request.condition_values:
                            return {
                                "success": False,
                                "error": "condition_values required",
                            }
                        bool_condition["values"] = [
                            {"userEnteredValue": v} for v in request.condition_values
                        ]

                # Build format
                format_spec: Dict[str, Any] = {}
                if request.background_color:
                    format_spec["backgroundColor"] = _hex_to_rgb(
                        request.background_color
                    )
                if request.text_color:
                    format_spec["textFormat"] = {
                        "foregroundColor": _hex_to_rgb(request.text_color)
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

            resp = _http_client.post(
                f"{SHEETS_API_BASE}/{request.spreadsheet_id}:batchUpdate",
                headers=headers,
                json=batch_request,
            )
            resp.raise_for_status()

            url = (
                f"https://docs.google.com/spreadsheets/d/{request.spreadsheet_id}/edit"
            )

            return {
                "success": True,
                "spreadsheet_id": request.spreadsheet_id,
                "url": url,
                "range_applied": f"{request.sheet_name}!{request.range}",
                "format_type": request.format_type,
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Error adding conditional format: {e}")
            return {
                "success": False,
                "error": f"API error: {e.response.status_code} - {e.response.text}",
            }
        except Exception as e:
            logger.error(f"Error adding conditional format: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="GOOGLESHEETS")
    @with_doc(CREATE_CHART_DOC)
    def CUSTOM_CREATE_CHART(
        request: ChartInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a chart from spreadsheet data."""
        access_token = _get_access_token(auth_credentials)
        headers = _auth_headers(access_token)

        try:
            source_sheet_id = _get_sheet_id_by_name(
                request.spreadsheet_id, request.sheet_name, headers
            )
            if source_sheet_id is None:
                return {
                    "success": False,
                    "error": f"Sheet '{request.sheet_name}' not found",
                }

            dest_sheet_name = request.destination_sheet_name or request.sheet_name
            dest_sheet_id = _get_sheet_id_by_name(
                request.spreadsheet_id, dest_sheet_name, headers
            )
            if dest_sheet_id is None:
                return {
                    "success": False,
                    "error": f"Destination sheet '{dest_sheet_name}' not found",
                }

            # Parse data range
            data_range = _parse_a1_range(request.data_range)
            data_range["sheetId"] = source_sheet_id

            # Parse anchor cell
            anchor = _parse_a1_range(request.anchor_cell)

            # Map chart types
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

            # Build chart spec
            if request.chart_type == "PIE":
                # Pie charts use different structure
                chart_spec: Dict[str, Any] = {
                    "pieChart": {
                        "legendPosition": request.legend_position,
                        "domain": {
                            "sourceRange": {"sources": [data_range]},
                        },
                        "series": {
                            "sourceRange": {"sources": [data_range]},
                        },
                    }
                }
            else:
                # Basic chart structure for bar, line, column, etc.
                chart_spec = {
                    "basicChart": {
                        "chartType": api_chart_type,
                        "legendPosition": request.legend_position,
                        "domains": [
                            {
                                "domain": {
                                    "sourceRange": {"sources": [data_range]},
                                }
                            }
                        ],
                        "series": [
                            {
                                "series": {
                                    "sourceRange": {"sources": [data_range]},
                                },
                                "targetAxis": "LEFT_AXIS",
                            }
                        ],
                        "headerCount": 1,
                    }
                }

                # Add axis titles
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

            # Add title
            if request.title:
                chart_spec["title"] = request.title

            # Build full chart request
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

            resp = _http_client.post(
                f"{SHEETS_API_BASE}/{request.spreadsheet_id}:batchUpdate",
                headers=headers,
                json=batch_request,
            )
            resp.raise_for_status()

            result = resp.json()
            chart_id = None
            for reply in result.get("replies", []):
                if "addChart" in reply:
                    chart_id = reply["addChart"]["chart"]["chartId"]
                    break

            url = (
                f"https://docs.google.com/spreadsheets/d/{request.spreadsheet_id}/edit"
            )

            return {
                "success": True,
                "spreadsheet_id": request.spreadsheet_id,
                "url": url,
                "chart_id": chart_id,
                "chart_type": request.chart_type,
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Error creating chart: {e}")
            return {
                "success": False,
                "error": f"API error: {e.response.status_code} - {e.response.text}",
            }
        except Exception as e:
            logger.error(f"Error creating chart: {e}")
            return {"success": False, "error": str(e)}

    return [
        "GOOGLESHEETS_CUSTOM_SHARE_SPREADSHEET",
        "GOOGLESHEETS_CUSTOM_CREATE_PIVOT_TABLE",
        "GOOGLESHEETS_CUSTOM_SET_DATA_VALIDATION",
        "GOOGLESHEETS_CUSTOM_ADD_CONDITIONAL_FORMAT",
        "GOOGLESHEETS_CUSTOM_CREATE_CHART",
    ]
