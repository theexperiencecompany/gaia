"""Layer 2 — read tool _format_text_read: line split + paging contract.

This is shared by the in-memory system-file path and the sandbox-fallback path;
both must number lines identically to the host read_user_file (split on "\\n"
only). The footer/total must be consistent.
"""

from __future__ import annotations

from app.agents.tools.coding.read_tool import _format_text_read


def _numbered_lines(out: str) -> list[str]:
    # The footer (if any) starts with a blank line + "... [showing". Strip it.
    body = out.split("\n\n... [", maxsplit=1)[0]
    return body.split("\n") if body else []


def test_basic_numbering_one_indexed() -> None:
    out = _format_text_read("/workspace/x", "alpha\nbeta\ngamma", 0, 2000, None)
    lines = _numbered_lines(out)
    assert lines[0].endswith("alpha") and lines[0].lstrip().startswith("1")
    assert lines[1].endswith("beta") and lines[1].lstrip().startswith("2")
    assert lines[2].endswith("gamma") and lines[2].lstrip().startswith("3")


def test_trailing_newline_is_not_a_phantom_line() -> None:
    # "a\nb\n" is 2 lines, not 3 — a trailing newline does not start a new line.
    out = _format_text_read("/workspace/x", "a\nb\n", 0, 2000, None)
    assert len(_numbered_lines(out)) == 2


def test_empty_file_is_zero_lines() -> None:
    out = _format_text_read("/workspace/x", "", 0, 2000, None)
    assert _numbered_lines(out) == [] or out == ""


def test_splits_on_newline_only_not_other_unicode_separators() -> None:
    # str.splitlines() would break on \v, \f, \x85, U+2028 — the host path does
    # NOT (it iterates file lines = split on \n). A file with these chars must
    # be ONE line, matching read_user_file, or line numbers diverge.
    text = "a\x0bb\x0cc d"  # no real \n
    out = _format_text_read("/workspace/x", text, 0, 2000, None)
    assert len(_numbered_lines(out)) == 1, "must split on \\n only, not unicode separators"


def test_offset_zero_and_one_both_mean_first_line() -> None:
    a = _format_text_read("/workspace/x", "l1\nl2\nl3", 0, 1, None)
    b = _format_text_read("/workspace/x", "l1\nl2\nl3", 1, 1, None)
    assert _numbered_lines(a)[0].endswith("l1")
    assert _numbered_lines(b)[0].endswith("l1")


def test_paging_footer_reports_total_when_truncated() -> None:
    text = "\n".join(f"line{i}" for i in range(1, 11))  # 10 lines
    out = _format_text_read("/workspace/x", text, 0, 3, None)
    assert "of 10" in out, "footer must report the true total line count"
    assert "offset=4" in out, "footer must point at the next page"


def test_no_footer_when_all_lines_shown() -> None:
    out = _format_text_read("/workspace/x", "a\nb", 0, 2000, None)
    assert "showing lines" not in out


def test_crlf_normalized_to_match_host_universal_newlines() -> None:
    # The host read_user_file opens in TEXT mode → universal newlines translate
    # \r\n to \n. The shared formatter must match, else a CRLF file renders with
    # stray \r via the sandbox/memory paths but clean via the host path.
    out = _format_text_read("/workspace/x", "alpha\r\nbeta\r\ngamma", 0, 2000, None)
    assert "\r" not in out, "CRLF must normalize to \\n to match the host text-mode read"
    assert len(_numbered_lines(out)) == 3


def test_lone_carriage_return_is_a_line_break() -> None:
    # Universal newlines treats a bare \r (old-Mac) as a line break too.
    out = _format_text_read("/workspace/x", "a\rb\rc", 0, 2000, None)
    assert len(_numbered_lines(out)) == 3
    assert "\r" not in out


def test_a_page_of_long_lines_stops_at_the_output_cap_and_offers_the_next_offset() -> None:
    """Regression: 400 JSONL lines of whole emails came back as 1.2M chars (a 386k-token call)."""
    from app.agents.tools.coding import read_tool

    line = "x" * 3_000
    text = "\n".join(f"{index}{line}" for index in range(400))

    out = read_tool._format_text_read("/workspace/mail.jsonl", text, 0, 400, None)

    shown = _numbered_lines(out)
    assert len(out) <= read_tool.MAX_READ_OUTPUT_CHARS + 200
    assert 0 < len(shown) < 400
    assert f"offset={len(shown) + 1}" in out


def test_a_single_line_longer_than_the_cap_is_cut_and_paging_still_advances() -> None:
    from app.agents.tools.coding import read_tool

    text = "y" * (read_tool.MAX_READ_OUTPUT_CHARS * 2) + "\nnext"

    out = read_tool._format_text_read("/workspace/one.jsonl", text, 0, 10, None)

    assert len(out) <= read_tool.MAX_READ_OUTPUT_CHARS + 200
    assert "offset=2" in out
