"""Google Sheets utility functions for API operations.

This module provides helpers for Google Sheets and Drive API interactions:
- Color conversion
- A1 notation parsing
- Sheet ID resolution (via Composio proxy)
- Column header resolution (via Composio proxy)
"""

import re
from typing import Dict, Optional

from shared.py.wide_events import log
from app.services.composio.proxy_client import proxy_request_sync

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
SHEETS_TOOLKIT = "GOOGLESHEETS"


def hex_to_rgb(hex_color: str) -> Dict[str, float]:
    """Convert hex color (#RRGGBB) to Google API RGB format (0-1 floats)."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return {"red": r, "green": g, "blue": b}


def parse_a1_range(range_str: str) -> Dict[str, int]:
    """Parse A1 notation (e.g., 'A1:B10') to row/column indices."""
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


def get_sheet_id_by_name(
    spreadsheet_id: str, sheet_name: str, user_id: str
) -> Optional[int]:
    """Get sheet ID by its name."""
    log.set(spreadsheet_id=spreadsheet_id, sheet_name=sheet_name)
    try:
        data = proxy_request_sync(
            user_id=user_id,
            toolkit=SHEETS_TOOLKIT,
            endpoint=f"{SHEETS_API_BASE}/{spreadsheet_id}",
            method="GET",
            query={"fields": "sheets.properties"},
        )
        for sheet in (data or {}).get("sheets", []):
            if sheet.get("properties", {}).get("title") == sheet_name:
                return sheet["properties"]["sheetId"]
        return None
    except Exception as e:
        log.error(f"Error getting sheet ID: {e}")
        return None


def get_column_index_by_header(
    spreadsheet_id: str,
    sheet_name: str,
    column_name: str,
    user_id: str,
) -> Optional[int]:
    """Get column index by header name (first row)."""
    log.set(
        spreadsheet_id=spreadsheet_id, sheet_name=sheet_name, column_name=column_name
    )
    try:
        data = proxy_request_sync(
            user_id=user_id,
            toolkit=SHEETS_TOOLKIT,
            endpoint=f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{sheet_name}!1:1",
            method="GET",
        )
        header_row = (data or {}).get("values", [[]])[0]
        for idx, header in enumerate(header_row):
            if header.lower() == column_name.lower():
                return idx
        return None
    except Exception as e:
        log.error(f"Error getting column index: {e}")
        return None
