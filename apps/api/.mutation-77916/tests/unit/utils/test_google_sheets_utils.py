"""Unit tests for app.utils.google_sheets_utils.

The pure helpers (`hex_to_rgb`, `parse_a1_range`, `parse_a1_anchor`) run with no
mocking at all. The two lookup helpers mock only the real I/O boundary
(`proxy_request_sync`).

Several production bugs were found while writing these tests and fixed at the
root; the tests pinning them down are marked with a "BUG:" comment.
"""

from typing import Any
from unittest.mock import patch

import pytest

from app.utils.errors import AppError
from app.utils.google_sheets_utils import (
    SHEETS_API_BASE,
    get_column_index_by_header,
    get_sheet_id_by_name,
    hex_to_rgb,
    parse_a1_anchor,
    parse_a1_range,
)

MODULE = "app.utils.google_sheets_utils"


# ---------------------------------------------------------------------------
# hex_to_rgb
# ---------------------------------------------------------------------------


class TestHexToRgb:
    def test_pure_red(self) -> None:
        assert hex_to_rgb("#FF0000") == {"red": 1.0, "green": 0.0, "blue": 0.0}

    def test_pure_blue(self) -> None:
        assert hex_to_rgb("#0000FF") == {"red": 0.0, "green": 0.0, "blue": 1.0}

    def test_black_and_white_are_the_scale_endpoints(self) -> None:
        assert hex_to_rgb("#000000") == {"red": 0.0, "green": 0.0, "blue": 0.0}
        assert hex_to_rgb("#FFFFFF") == {"red": 1.0, "green": 1.0, "blue": 1.0}

    def test_leading_hash_is_optional(self) -> None:
        assert hex_to_rgb("00FF00") == hex_to_rgb("#00FF00")

    def test_lowercase_digits_accepted(self) -> None:
        assert hex_to_rgb("#00ff00") == {"red": 0.0, "green": 1.0, "blue": 0.0}

    def test_channels_are_not_transposed(self) -> None:
        # Distinct values per channel: a red/blue swap would still pass an
        # all-equal fixture, so pin each channel to its own byte.
        assert hex_to_rgb("#112233") == {
            "red": 0x11 / 255.0,
            "green": 0x22 / 255.0,
            "blue": 0x33 / 255.0,
        }

    def test_midpoint_byte_scales_to_fraction(self) -> None:
        assert hex_to_rgb("#808080")["red"] == pytest.approx(128 / 255.0)

    # BUG: three-digit shorthand used to crash with "invalid literal for int()
    # with base 16: ''" — an opaque message for a colour the model routinely
    # emits. It is still rejected, but now names the expected format.
    def test_three_digit_shorthand_is_rejected_with_a_readable_message(self) -> None:
        with pytest.raises(ValueError, match=r"Invalid hex color: '#fff' \(expected '#RRGGBB'\)"):
            hex_to_rgb("#fff")

    @pytest.mark.parametrize("bad", ["", "#", "#GGGGGG", "#12345", "#1234567", "red"])
    def test_non_hex_input_is_rejected(self, bad: str) -> None:
        with pytest.raises(ValueError, match="Invalid hex color"):
            hex_to_rgb(bad)


# ---------------------------------------------------------------------------
# parse_a1_range
# ---------------------------------------------------------------------------


class TestParseA1Range:
    def test_simple_range_is_half_open_on_the_end(self) -> None:
        # A1:B10 covers rows 1-10 and columns A-B, so the exclusive end indices
        # are 10 and 2 respectively.
        assert parse_a1_range("A1:B10") == {
            "startRowIndex": 0,
            "endRowIndex": 10,
            "startColumnIndex": 0,
            "endColumnIndex": 2,
        }

    def test_single_cell_spans_exactly_one_row_and_column(self) -> None:
        assert parse_a1_range("C3") == {
            "startRowIndex": 2,
            "endRowIndex": 3,
            "startColumnIndex": 2,
            "endColumnIndex": 3,
        }

    def test_multi_letter_columns_use_base_26(self) -> None:
        # AA is the 27th column (index 26); a naive per-character sum yields 0.
        assert parse_a1_range("AA1")["startColumnIndex"] == 26
        assert parse_a1_range("ZZ1")["startColumnIndex"] == 701

    def test_absolute_markers_are_stripped(self) -> None:
        assert parse_a1_range("$A$1:$B$2") == parse_a1_range("A1:B2")

    def test_lowercase_is_normalized(self) -> None:
        assert parse_a1_range("a1:b10") == parse_a1_range("A1:B10")

    # BUG: the sheet qualifier was not stripped, so parse_cell matched "SHEET1"
    # as a column name and produced startColumnIndex=8826681 — garbage silently
    # sent to Google. Sheet-qualified ranges are ordinary A1 notation and the
    # tools' own responses format ranges this way.
    def test_sheet_qualifier_is_stripped_not_read_as_a_column(self) -> None:
        assert parse_a1_range("Sheet1!A1:B2") == parse_a1_range("A1:B2")

    def test_quoted_sheet_name_with_spaces_is_stripped(self) -> None:
        assert parse_a1_range("'My Sheet'!B2:C3") == parse_a1_range("B2:C3")

    # BUG: whole-column references collapsed onto row 1 (A:C returned the single
    # cell A1), so "highlight column C" silently formatted one cell and reported
    # success. Omitting the row bounds is what Google's GridRange means by
    # "unbounded".
    def test_whole_column_range_leaves_rows_unbounded(self) -> None:
        assert parse_a1_range("A:C") == {"startColumnIndex": 0, "endColumnIndex": 3}

    def test_single_whole_column_leaves_rows_unbounded(self) -> None:
        assert parse_a1_range("B:B") == {"startColumnIndex": 1, "endColumnIndex": 2}

    def test_whole_row_range_leaves_columns_unbounded(self) -> None:
        assert parse_a1_range("1:5") == {"startRowIndex": 0, "endRowIndex": 5}

    def test_open_ended_column_keeps_its_start_row(self) -> None:
        # "A2:A" means "column A from row 2 down", so the start row survives and
        # only the end is unbounded.
        assert parse_a1_range("A2:A") == {
            "startRowIndex": 1,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        }

    # BUG: a reversed range produced endRowIndex < startRowIndex, which Google
    # rejects. Spreadsheets treat B10:A1 as the same block as A1:B10.
    def test_reversed_range_is_normalized(self) -> None:
        assert parse_a1_range("B10:A1") == parse_a1_range("A1:B10")

    def test_row_and_column_are_normalized_independently(self) -> None:
        # Only the rows are inverted here; the columns must be left alone.
        assert parse_a1_range("A10:B1") == parse_a1_range("A1:B10")

    # BUG: unparseable input silently became cell A1 via a `return 0, 0`
    # fallback, so a malformed range formatted the wrong cell and reported
    # success instead of failing.
    @pytest.mark.parametrize("bad", ["", "@@", "Sheet1!", "-", " "])
    def test_unparseable_reference_raises_instead_of_defaulting_to_a1(self, bad: str) -> None:
        with pytest.raises(ValueError, match="Invalid A1 cell reference"):
            parse_a1_range(bad)

    def test_more_than_two_endpoints_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"Invalid A1 range: 'A1:B2:C3'"):
            parse_a1_range("A1:B2:C3")

    def test_error_message_quotes_the_original_input(self) -> None:
        with pytest.raises(ValueError, match=r"'\$A1:B2:C3'"):
            parse_a1_range("$A1:B2:C3")


# ---------------------------------------------------------------------------
# parse_a1_anchor
# ---------------------------------------------------------------------------


class TestParseA1Anchor:
    def test_returns_zero_based_row_then_column(self) -> None:
        # E1 is row 1, column 5 -> (0, 4). Order matters: a (col, row) swap
        # would anchor charts in the wrong place.
        assert parse_a1_anchor("E1") == (0, 4)

    def test_row_and_column_are_not_transposed(self) -> None:
        assert parse_a1_anchor("B5") == (4, 1)

    def test_accepts_a_sheet_qualified_cell(self) -> None:
        assert parse_a1_anchor("Sheet1!C3") == (2, 2)

    def test_range_input_anchors_at_its_top_left_corner(self) -> None:
        assert parse_a1_anchor("C3:F9") == (2, 2)

    @pytest.mark.parametrize("ref", ["A", "3", "A:A", "1:5"])
    def test_open_ended_reference_has_no_anchor_point(self, ref: str) -> None:
        with pytest.raises(ValueError, match="Not a single cell reference"):
            parse_a1_anchor(ref)

    def test_invalid_reference_propagates_the_parse_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid A1 cell reference"):
            parse_a1_anchor("@@")


# ---------------------------------------------------------------------------
# get_sheet_id_by_name
# ---------------------------------------------------------------------------


def _sheets_payload(*titles_and_ids: tuple[str, int]) -> dict[str, Any]:
    return {
        "sheets": [
            {"properties": {"title": title, "sheetId": sheet_id}}
            for title, sheet_id in titles_and_ids
        ]
    }


class TestGetSheetIdByName:
    def test_returns_the_matching_sheet_id(self) -> None:
        with patch(
            f"{MODULE}.proxy_request_sync",
            return_value=_sheets_payload(("Sheet1", 0), ("Data", 12345)),
        ):
            assert get_sheet_id_by_name("sid", "Data", "u1") == 12345

    def test_requests_only_the_sheet_properties_field(self) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={}) as proxy:
            get_sheet_id_by_name("sid", "Data", "u1")

        kwargs = proxy.call_args.kwargs
        assert kwargs["endpoint"] == f"{SHEETS_API_BASE}/sid"
        assert kwargs["method"] == "GET"
        assert kwargs["query"] == {"fields": "sheets.properties"}
        assert kwargs["user_id"] == "u1"

    def test_sheet_zero_is_returned_not_treated_as_missing(self) -> None:
        # Sheet id 0 is falsy; returning None for it would send every chart to
        # the "sheet not found" path for the default first tab.
        with patch(f"{MODULE}.proxy_request_sync", return_value=_sheets_payload(("Sheet1", 0))):
            assert get_sheet_id_by_name("sid", "Sheet1", "u1") == 0

    def test_title_match_is_case_sensitive(self) -> None:
        # Google treats "Data" and "data" as distinct tabs, so a loose match
        # would resolve to the wrong sheet.
        with patch(f"{MODULE}.proxy_request_sync", return_value=_sheets_payload(("Data", 5))):
            assert get_sheet_id_by_name("sid", "data", "u1") is None

    def test_absent_sheet_returns_none(self) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value=_sheets_payload(("Sheet1", 0))):
            assert get_sheet_id_by_name("sid", "Nope", "u1") is None

    @pytest.mark.parametrize("payload", [None, {}, {"sheets": []}])
    def test_empty_payloads_return_none(self, payload: Any) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value=payload):
            assert get_sheet_id_by_name("sid", "Data", "u1") is None

    def test_malformed_sheet_entry_is_skipped(self) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={"sheets": [{}]}):
            assert get_sheet_id_by_name("sid", "Data", "u1") is None

    # BUG: every exception was swallowed into `return None`, and callers turn
    # None into "sheet 'X' not found". An expired Google token therefore told
    # the user their tab was missing. Lookup failure must not masquerade as
    # absence.
    def test_auth_failure_propagates_instead_of_looking_like_a_missing_sheet(self) -> None:
        error = AppError(message="No active GOOGLESHEETS connection", why="w", status_code=403)
        with (
            patch(f"{MODULE}.proxy_request_sync", side_effect=error),
            pytest.raises(AppError) as excinfo,
        ):
            get_sheet_id_by_name("sid", "Data", "u1")

        assert excinfo.value.status_code == 403


# ---------------------------------------------------------------------------
# get_column_index_by_header
# ---------------------------------------------------------------------------


class TestGetColumnIndexByHeader:
    def test_returns_the_zero_based_header_position(self) -> None:
        with patch(
            f"{MODULE}.proxy_request_sync",
            return_value={"values": [["Region", "Product", "Revenue"]]},
        ):
            assert get_column_index_by_header("sid", "Data", "Revenue", "u1") == 2

    def test_first_column_is_index_zero_not_missing(self) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={"values": [["Region"]]}):
            assert get_column_index_by_header("sid", "Data", "Region", "u1") == 0

    def test_header_match_ignores_case(self) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={"values": [["Revenue"]]}):
            assert get_column_index_by_header("sid", "Data", "revenue", "u1") == 0

    def test_reads_only_the_first_row_of_the_named_sheet(self) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={}) as proxy:
            get_column_index_by_header("sid", "Data", "Revenue", "u1")

        kwargs = proxy.call_args.kwargs
        assert kwargs["endpoint"] == f"{SHEETS_API_BASE}/sid/values/Data!1:1"
        assert kwargs["method"] == "GET"

    def test_first_match_wins_for_duplicate_headers(self) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={"values": [["A", "B", "A"]]}):
            assert get_column_index_by_header("sid", "Data", "A", "u1") == 0

    def test_unknown_header_returns_none(self) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={"values": [["Region"]]}):
            assert get_column_index_by_header("sid", "Data", "Missing", "u1") is None

    @pytest.mark.parametrize("payload", [None, {}, {"values": []}, {"values": [[]]}])
    def test_empty_sheet_payloads_return_none(self, payload: Any) -> None:
        # An empty sheet comes back with no `values` key at all; indexing [0] on
        # the default would raise IndexError rather than report "no such column".
        with patch(f"{MODULE}.proxy_request_sync", return_value=payload):
            assert get_column_index_by_header("sid", "Data", "Region", "u1") is None

    def test_numeric_header_cell_does_not_crash_the_scan(self) -> None:
        # Google returns unquoted numbers for numeric headers; `.lower()` on an
        # int would raise AttributeError mid-scan.
        with patch(f"{MODULE}.proxy_request_sync", return_value={"values": [[2024, "Revenue"]]}):
            assert get_column_index_by_header("sid", "Data", "Revenue", "u1") == 1

    # BUG: same swallowed-exception bug as get_sheet_id_by_name — a transport
    # failure reported the column as absent.
    def test_transport_failure_propagates(self) -> None:
        with (
            patch(
                f"{MODULE}.proxy_request_sync",
                side_effect=AppError(message="boom", why="w", status_code=502),
            ),
            pytest.raises(AppError),
        ):
            get_column_index_by_header("sid", "Data", "Region", "u1")
