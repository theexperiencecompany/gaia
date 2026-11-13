"""Google Sheets tools using Composio custom tool infrastructure.

Provider API calls go through Composio's proxy via `proxy_request_sync`.
Drive API is used for sharing; Sheets API for spreadsheet operations.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from composio import Composio
from composio.types import ExecuteRequestFn
from pydantic import BaseModel

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
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.google_drive import (
    GoogleDriveFileList,
    GoogleDrivePermission,
    GoogleDrivePermissionCreate,
)
from app.models.integrations.google_sheets import (
    GoogleSheetsAddChartRequest,
    GoogleSheetsAddConditionalFormatRuleRequest,
    GoogleSheetsBasicChartAxis,
    GoogleSheetsBasicChartDomain,
    GoogleSheetsBasicChartSeries,
    GoogleSheetsBasicChartSpec,
    GoogleSheetsBatchUpdateRequest,
    GoogleSheetsBatchUpdateResponse,
    GoogleSheetsBooleanCondition,
    GoogleSheetsBooleanRule,
    GoogleSheetsCellData,
    GoogleSheetsCellFormat,
    GoogleSheetsChartData,
    GoogleSheetsChartSourceRange,
    GoogleSheetsChartSpec,
    GoogleSheetsConditionalFormatRule,
    GoogleSheetsConditionValue,
    GoogleSheetsDataValidationRule,
    GoogleSheetsEmbeddedChart,
    GoogleSheetsEmbeddedObjectPosition,
    GoogleSheetsGradientRule,
    GoogleSheetsGridCoordinate,
    GoogleSheetsGridRange,
    GoogleSheetsInterpolationPoint,
    GoogleSheetsOverlayPosition,
    GoogleSheetsPieChartSpec,
    GoogleSheetsPivotGroup,
    GoogleSheetsPivotTable,
    GoogleSheetsPivotValue,
    GoogleSheetsRequest,
    GoogleSheetsRowData,
    GoogleSheetsSetDataValidationRequest,
    GoogleSheetsTextFormat,
    GoogleSheetsUpdateCellsRequest,
)
from app.services.composio.proxy_client import ProxyMethod, ProxyRequest, proxy_request_sync
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
    get_column_index_by_header,
    get_sheet_id_by_name,
    hex_to_rgb,
    parse_a1_anchor,
    parse_a1_range,
)
from shared.py.wide_events import log

SHEETS_TOOLKIT = "GOOGLESHEETS"

# New conditional-format rules go to the front so they win over existing rules.
NEW_FORMAT_RULE_INDEX = 0

RECENT_SPREADSHEETS_PAGE_SIZE = 20

# ConditionalFormatInput.condition -> Sheets BooleanCondition type.
_CONDITION_TYPES = {
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


QueryParams = dict[str, str | int]


def _sheets_proxy(
    user_id: str,
    *,
    endpoint: str,
    method: ProxyMethod,
    body: BaseModel | None = None,
    query: QueryParams | None = None,
) -> object:
    """Send one Sheets/Drive request.

    The parsed JSON comes back untyped for the caller to validate into its response model.
    """
    return proxy_request_sync(
        ProxyRequest(
            user_id=user_id,
            toolkit=SHEETS_TOOLKIT,
            endpoint=endpoint,
            method=method,
            body=(
                body.model_dump(  # pragma: no mutate -- dropping mode= is unobservable here and banned by tool-dump-boundary
                    mode="json",  # pragma: no mutate -- JSON-native fields only, so any mode value dumps identically
                    exclude_none=True,
                )
                if body is not None
                else None
            ),
            query=query,
        )
    )


def _batch_update(
    user_id: str, spreadsheet_id: str, request: GoogleSheetsRequest
) -> GoogleSheetsBatchUpdateResponse:
    """Apply one batchUpdate request and parse Google's reply."""
    return GoogleSheetsBatchUpdateResponse.model_validate(
        _sheets_proxy(
            user_id,
            endpoint=f"{SHEETS_API_BASE}/{spreadsheet_id}:batchUpdate",
            method="POST",
            body=GoogleSheetsBatchUpdateRequest(requests=[request]),
        )
        or {}
    )


def _condition(kind: str, *values: str) -> GoogleSheetsBooleanCondition:
    return GoogleSheetsBooleanCondition(
        type=kind, values=[GoogleSheetsConditionValue(userEnteredValue=v) for v in values]
    )


def _validation_condition(request: DataValidationInput) -> GoogleSheetsBooleanCondition:
    """The Sheets condition for a validation request, or ValueError naming what is missing."""
    if request.validation_type == "dropdown_list":
        if not request.values:
            raise ValueError("values required for dropdown_list")
        return _condition("ONE_OF_LIST", *request.values)
    if request.validation_type == "dropdown_range":
        if not request.source_range:
            raise ValueError("source_range required for dropdown_range")
        return _condition("ONE_OF_RANGE", f"={request.source_range}")
    if request.validation_type == "custom_formula":
        if not request.formula:
            raise ValueError("formula required for custom_formula")
        return _condition("CUSTOM_FORMULA", request.formula)

    between, at_least, at_most = (
        ("NUMBER_BETWEEN", "NUMBER_GREATER_THAN_EQ", "NUMBER_LESS_THAN_EQ")
        if request.validation_type == "number"
        else ("DATE_BETWEEN", "DATE_AFTER", "DATE_BEFORE")
    )
    if request.min_value is not None and request.max_value is not None:
        return _condition(between, str(request.min_value), str(request.max_value))
    if request.min_value is not None:
        return _condition(at_least, str(request.min_value))
    if request.max_value is not None:
        return _condition(at_most, str(request.max_value))
    raise ValueError(f"min_value or max_value required for {request.validation_type} validation")


def _chart_data(source: GoogleSheetsGridRange) -> GoogleSheetsChartData:
    return GoogleSheetsChartData(sourceRange=GoogleSheetsChartSourceRange(sources=[source]))


def register_google_sheets_custom_tools(composio: Composio) -> list[str]:
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
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        shared: list[dict[str, object]] = []
        errors: list[dict[str, str]] = []

        for recipient in request.recipients:
            try:
                permission = GoogleDrivePermission.model_validate(
                    _sheets_proxy(
                        user_id,
                        endpoint=f"{DRIVE_API_BASE}/files/{request.spreadsheet_id}/permissions",
                        method="POST",
                        body=GoogleDrivePermissionCreate(
                            type="user", role=recipient.role, emailAddress=recipient.email
                        ),
                        query={
                            "sendNotificationEmail": str(recipient.send_notification).lower(),
                        },
                    )
                    or {}
                )
                shared.append(
                    {
                        "email": recipient.email,
                        "role": recipient.role,
                        "permission_id": permission.id,
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
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

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

        row_indices: list[GoogleSheetsPivotGroup] = []
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
                GoogleSheetsPivotGroup(
                    sourceColumnOffset=idx, sortOrder="ASCENDING", showTotals=True
                )
            )

        col_indices: list[GoogleSheetsPivotGroup] = []
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
                GoogleSheetsPivotGroup(
                    sourceColumnOffset=idx, sortOrder="ASCENDING", showTotals=True
                )
            )

        value_specs: list[GoogleSheetsPivotValue] = []
        for val in request.values:
            idx = get_column_index_by_header(
                request.spreadsheet_id,
                request.source_sheet_name,
                val.column,
                user_id,
            )
            if idx is None:
                raise ValueError(f"Value column '{val.column}' not found")
            value_specs.append(
                GoogleSheetsPivotValue(
                    sourceColumnOffset=idx,
                    summarizeFunction=val.aggregation,
                    name=val.name or None,
                )
            )

        source_range = (
            parse_a1_range(request.source_range).model_copy(update={"sheetId": source_sheet_id})
            if request.source_range
            else GoogleSheetsGridRange(sheetId=source_sheet_id)
        )

        dest_row, dest_col = parse_a1_anchor(request.destination_cell)

        pivot_table = GoogleSheetsPivotTable(
            source=source_range,
            rows=row_indices,
            values=value_specs,
            columns=col_indices or None,
        )

        _batch_update(
            user_id,
            request.spreadsheet_id,
            GoogleSheetsRequest(
                updateCells=GoogleSheetsUpdateCellsRequest(
                    rows=[
                        GoogleSheetsRowData(values=[GoogleSheetsCellData(pivotTable=pivot_table)])
                    ],
                    start=GoogleSheetsGridCoordinate(
                        sheetId=dest_sheet_id, rowIndex=dest_row, columnIndex=dest_col
                    ),
                    fields="pivotTable",
                )
            ),
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
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        sheet_id = get_sheet_id_by_name(request.spreadsheet_id, request.sheet_name, user_id)
        if sheet_id is None:
            raise ValueError(f"Sheet '{request.sheet_name}' not found")

        range_spec = parse_a1_range(request.range)
        range_spec.sheetId = sheet_id

        validation_rule = GoogleSheetsDataValidationRule(
            condition=_validation_condition(request),
            strict=request.strict,
            showCustomUi=request.show_dropdown,
            inputMessage=request.input_message or None,
        )

        try:
            _batch_update(
                user_id,
                request.spreadsheet_id,
                GoogleSheetsRequest(
                    setDataValidation=GoogleSheetsSetDataValidationRequest(
                        range=range_spec, rule=validation_rule
                    )
                ),
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
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        sheet_id = get_sheet_id_by_name(request.spreadsheet_id, request.sheet_name, user_id)
        if sheet_id is None:
            raise ValueError(f"Sheet '{request.sheet_name}' not found")

        range_spec = parse_a1_range(request.range)
        range_spec.sheetId = sheet_id

        rule = GoogleSheetsConditionalFormatRule(ranges=[range_spec])

        if request.format_type == "color_scale":
            # Google requires both endpoints on a gradient rule; sending nulls
            # for a missing colour gets the whole batch rejected.
            if not request.min_color or not request.max_color:
                raise ValueError("min_color and max_color are required for color_scale")

            rule.gradientRule = GoogleSheetsGradientRule(
                minpoint=GoogleSheetsInterpolationPoint(
                    type="MIN", color=hex_to_rgb(request.min_color)
                ),
                maxpoint=GoogleSheetsInterpolationPoint(
                    type="MAX", color=hex_to_rgb(request.max_color)
                ),
                midpoint=(
                    GoogleSheetsInterpolationPoint(
                        type="PERCENTILE", value="50", color=hex_to_rgb(request.mid_color)
                    )
                    if request.mid_color
                    else None
                ),
            )

        else:
            if request.format_type == "custom_formula":
                if not request.formula:
                    raise ValueError("formula required for custom_formula")
                bool_condition = _condition("CUSTOM_FORMULA", request.formula)
            else:
                if not request.condition:
                    raise ValueError("condition required for value_based")

                bool_condition = GoogleSheetsBooleanCondition(
                    type=_CONDITION_TYPES[request.condition]
                )

                if request.condition not in ["is_empty", "is_not_empty"]:
                    expected = 2 if request.condition == "between" else 1
                    values = request.condition_values or []
                    if len(values) != expected:
                        raise ValueError(
                            f"'{request.condition}' requires exactly {expected} "
                            f"condition_values, got {len(values)}"
                        )
                    bool_condition.values = [
                        GoogleSheetsConditionValue(userEnteredValue=v) for v in values
                    ]

            wants_text_format = (
                bool(request.text_color) or request.bold is not None or request.italic is not None
            )
            format_spec = GoogleSheetsCellFormat(
                backgroundColor=(
                    hex_to_rgb(request.background_color) if request.background_color else None
                ),
                textFormat=(
                    GoogleSheetsTextFormat(
                        foregroundColor=(
                            hex_to_rgb(request.text_color) if request.text_color else None
                        ),
                        bold=request.bold,
                        italic=request.italic,
                    )
                    if wants_text_format
                    else None
                ),
            )

            # A rule with no format is a no-op Google accepts silently, so the
            # user is told the formatting was applied and then sees nothing.
            if format_spec.backgroundColor is None and format_spec.textFormat is None:
                raise ValueError(
                    "At least one of background_color, text_color, bold or italic "
                    "is required to format matching cells"
                )

            rule.booleanRule = GoogleSheetsBooleanRule(condition=bool_condition, format=format_spec)

        _batch_update(
            user_id,
            request.spreadsheet_id,
            GoogleSheetsRequest(
                addConditionalFormatRule=GoogleSheetsAddConditionalFormatRuleRequest(
                    rule=rule, index=NEW_FORMAT_RULE_INDEX
                )
            ),
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
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        source_sheet_id = get_sheet_id_by_name(request.spreadsheet_id, request.sheet_name, user_id)
        if source_sheet_id is None:
            raise ValueError(f"Sheet '{request.sheet_name}' not found")

        dest_sheet_name = request.destination_sheet_name or request.sheet_name
        dest_sheet_id = get_sheet_id_by_name(request.spreadsheet_id, dest_sheet_name, user_id)
        if dest_sheet_id is None:
            raise ValueError(f"Destination sheet '{dest_sheet_name}' not found")

        range_spec = parse_a1_range(request.data_range)

        start_col = range_spec.startColumnIndex if range_spec.startColumnIndex is not None else 0
        end_col = (
            range_spec.endColumnIndex
            if range_spec.endColumnIndex is not None
            else start_col + 1  # pragma: no mutate — width stays <= 1, end_col unused
        )
        width = end_col - start_col

        if width > 1:
            domain_range = range_spec.model_copy(
                update={"endColumnIndex": start_col + 1, "sheetId": source_sheet_id}
            )
            series_ranges = [
                range_spec.model_copy(
                    update={
                        "startColumnIndex": i,
                        "endColumnIndex": i + 1,
                        "sheetId": source_sheet_id,
                    }
                )
                for i in range(start_col + 1, end_col)
            ]
        else:
            domain_range = range_spec.model_copy(update={"sheetId": source_sheet_id})
            series_ranges = [domain_range]

        anchor_row, anchor_col = parse_a1_anchor(request.anchor_cell)

        chart_spec = GoogleSheetsChartSpec(title=request.title or None)
        if request.chart_type == "PIE":
            chart_spec.pieChart = GoogleSheetsPieChartSpec(
                legendPosition=request.legend_position,
                domain=_chart_data(domain_range),
                series=_chart_data(series_ranges[0]),
            )
        else:
            axis = [
                GoogleSheetsBasicChartAxis(position=position, title=title)
                for position, title in (
                    ("BOTTOM_AXIS", request.x_axis_title),
                    ("LEFT_AXIS", request.y_axis_title),
                )
                if title
            ]
            chart_spec.basicChart = GoogleSheetsBasicChartSpec(
                chartType=request.chart_type,
                legendPosition=request.legend_position,
                domains=[GoogleSheetsBasicChartDomain(domain=_chart_data(domain_range))],
                series=[
                    GoogleSheetsBasicChartSeries(
                        series=_chart_data(s_range), targetAxis="LEFT_AXIS"
                    )
                    for s_range in series_ranges
                ],
                headerCount=1,
                axis=axis or None,
            )

        chart_request = GoogleSheetsAddChartRequest(
            chart=GoogleSheetsEmbeddedChart(
                spec=chart_spec,
                position=GoogleSheetsEmbeddedObjectPosition(
                    overlayPosition=GoogleSheetsOverlayPosition(
                        anchorCell=GoogleSheetsGridCoordinate(
                            sheetId=dest_sheet_id, rowIndex=anchor_row, columnIndex=anchor_col
                        ),
                        widthPixels=request.width,
                        heightPixels=request.height,
                    )
                ),
            )
        )

        try:
            result = _batch_update(
                user_id, request.spreadsheet_id, GoogleSheetsRequest(addChart=chart_request)
            )
        except AppError as e:
            log.error(f"{LogTag.TOOL} Error creating chart", error_type=type(e).__name__)
            raise RuntimeError(f"Failed to create chart: {e.message}") from e

        chart_id = None
        for reply in result.replies:
            if reply.addChart is not None:
                chart_id = reply.addChart.chart.chartId if reply.addChart.chart else None
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
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        mime = "application/vnd.google-apps.spreadsheet"
        files: list[dict[str, str | None]] = []
        try:
            listing = GoogleDriveFileList.model_validate(
                _sheets_proxy(
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
                or {}
            )
            files = [
                {
                    "id": f.id,
                    "name": f.name,
                    "modified": f.modifiedTime,
                    "url": f.webViewLink,
                }
                for f in listing.files
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
