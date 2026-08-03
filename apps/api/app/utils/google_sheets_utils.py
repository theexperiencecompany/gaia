"""Google Sheets utility functions for API operations.

This module provides helpers for Google Sheets and Drive API interactions:
- Color conversion
- A1 notation parsing
- Sheet ID resolution (via Composio proxy)
- Column header resolution (via Composio proxy)
"""

import re
from typing import NotRequired, TypedDict, cast

from app.services.composio.proxy_client import proxy_request_sync
from shared.py.wide_events import log


class SheetsColor(TypedDict):
    """A Google Sheets API ``Color`` — channels as 0-1 floats."""

    red: float
    green: float
    blue: float


class SheetsGridRange(TypedDict):
    """A Google Sheets API ``GridRange``.

    Every key is ``NotRequired``: an A1 reference may leave rows or columns open
    ('A:C'), and Sheets reads an absent bound as unbounded — omitting it is what
    keeps a column range from collapsing onto row 1. ``parse_a1_range`` never
    sets ``sheetId`` (A1 notation carries a sheet *name*); callers resolve the id
    and add it to the range they build.
    """

    sheetId: NotRequired[int]
    startRowIndex: NotRequired[int]
    endRowIndex: NotRequired[int]
    startColumnIndex: NotRequired[int]
    endColumnIndex: NotRequired[int]


DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
SHEETS_TOOLKIT = "GOOGLESHEETS"


_HEX_COLOR_RE = re.compile(r"^[0-9A-Fa-f]{6}$")


def hex_to_rgb(hex_color: str) -> SheetsColor:
    """Convert hex color (#RRGGBB) to Google API RGB format (0-1 floats)."""
    digits = hex_color.lstrip("#")
    if not _HEX_COLOR_RE.match(digits):
        raise ValueError(f"Invalid hex color: '{hex_color}' (expected '#RRGGBB')")
    return {
        "red": int(digits[0:2], 16) / 255.0,
        "green": int(digits[2:4], 16) / 255.0,
        "blue": int(digits[4:6], 16) / 255.0,
    }


_CELL_REF_RE = re.compile(r"^([A-Z]+)?(\d+)?$")


def _parse_cell(cell: str) -> tuple[int | None, int | None]:
    """Split one A1 cell reference into zero-based (row, column) indices.

    Either coordinate is `None` for an open-ended reference: 'A' names a whole
    column (no row) and '2' names a whole row (no column).
    """
    match = _CELL_REF_RE.match(cell)
    if not match or not any(match.groups()):
        raise ValueError(f"Invalid A1 cell reference: '{cell}'")
    col_str, row_str = match.groups()
    col = (
        None
        if col_str is None
        else sum((ord(c) - ord("A") + 1) * (26**i) for i, c in enumerate(reversed(col_str))) - 1
    )
    row = None if row_str is None else int(row_str) - 1
    return row, col


def parse_a1_range(range_str: str) -> SheetsGridRange:
    """Parse A1 notation (e.g. 'A1:B10', 'Sheet1!A:C') into a Google GridRange.

    Bounds that the reference leaves open are omitted rather than defaulted, so
    'A:C' becomes an unbounded-row column range instead of collapsing onto row 1.
    Raises `ValueError` on input that is not A1 notation — a malformed range must
    not be silently reinterpreted as cell A1.
    """
    # A sheet qualifier is part of A1 notation ("Sheet1!A1:B2") and callers pass
    # it through; leaving it in makes the cell regex read "SHEET1" as a column.
    ref = range_str.replace("$", "").upper().rsplit("!", 1)[-1]

    parts = ref.split(":")
    if len(parts) > 2:
        raise ValueError(f"Invalid A1 range: '{range_str}'")

    start_row, start_col = _parse_cell(parts[0])
    end_row, end_col = _parse_cell(parts[-1])

    # Spreadsheets treat 'B10:A1' as the same block as 'A1:B10'; normalize so we
    # never hand Google a range whose end precedes its start.
    if start_row is not None and end_row is not None and start_row > end_row:
        start_row, end_row = end_row, start_row
    if start_col is not None and end_col is not None and start_col > end_col:
        start_col, end_col = end_col, start_col

    grid: SheetsGridRange = {}
    if start_row is not None:
        grid["startRowIndex"] = start_row
    if end_row is not None:
        grid["endRowIndex"] = end_row + 1
    if start_col is not None:
        grid["startColumnIndex"] = start_col
    if end_col is not None:
        grid["endColumnIndex"] = end_col + 1
    return grid


def parse_a1_anchor(cell_ref: str) -> tuple[int, int]:
    """Parse a single A1 cell reference into zero-based (row, column) indices.

    Both coordinates are required: callers anchor a chart or pivot table at one
    specific cell, so an open-ended reference like 'A' has no defined position.
    """
    grid = parse_a1_range(cell_ref)
    if "startRowIndex" not in grid or "startColumnIndex" not in grid:
        raise ValueError(f"Not a single cell reference: '{cell_ref}' (expected e.g. 'A1')")
    return grid["startRowIndex"], grid["startColumnIndex"]


def get_sheet_id_by_name(spreadsheet_id: str, sheet_name: str, user_id: str) -> int | None:
    """Get sheet ID by its name, or None when the spreadsheet has no such sheet.

    Transport and auth failures propagate: callers turn `None` into "sheet not
    found", so swallowing them would report a missing tab for an expired token.
    """
    log.set(spreadsheet_id=spreadsheet_id, sheet_name=sheet_name)
    data = proxy_request_sync(
        user_id=user_id,
        toolkit=SHEETS_TOOLKIT,
        endpoint=f"{SHEETS_API_BASE}/{spreadsheet_id}",
        method="GET",
        query={"fields": "sheets.properties"},
    )
    for sheet in (data or {}).get("sheets", []):
        if sheet.get("properties", {}).get("title") == sheet_name:
            return cast(int, sheet["properties"]["sheetId"])
    return None


def get_column_index_by_header(
    spreadsheet_id: str,
    sheet_name: str,
    column_name: str,
    user_id: str,
) -> int | None:
    """Get column index by header name (first row), or None when no header matches.

    Transport and auth failures propagate for the same reason as
    `get_sheet_id_by_name`: `None` means "no such column", not "lookup failed".
    """
    log.set(spreadsheet_id=spreadsheet_id, sheet_name=sheet_name, column_name=column_name)
    data = proxy_request_sync(
        user_id=user_id,
        toolkit=SHEETS_TOOLKIT,
        endpoint=f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{sheet_name}!1:1",
        method="GET",
    )
    # An empty sheet comes back with no `values` at all, not an empty first row.
    rows = (data or {}).get("values") or [[]]
    for idx, header in enumerate(rows[0]):
        if str(header).lower() == column_name.lower():
            return idx
    return None
