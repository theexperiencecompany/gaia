"""query_json: the in-process structured JSON/JSONL query engine + tool.

Pure engine tests (filter/project/sort/count/dedupe/group + record parsing) plus
the tool end-to-end with the JuiceFS boundary mocked. It is safe by construction
(no subprocess, no eval, no file access beyond the one workspace file), so these
tests focus on correctness of the six operations.
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.coding import query_json_tool
from app.agents.tools.coding.query_json_tool import (
    _apply_query,
    _format_result,
    _hashable,
    _load_records,
    _match_condition,
    _sort_key,
    query_json,
)
from app.constants.log_tags import LogTag
from app.services.storage import FsOps

CONFIG = {"configurable": {"user_id": "u1", "conversation_id": "c1"}}

RECORDS = [
    {
        "from": "github",
        "subject": "PR merged",
        "isRead": False,
        "threadId": "t1",
        "time": "2026-06-03",
        "labels": ["INBOX", "UNREAD"],
    },
    {
        "from": "bob@co.com",
        "subject": "lunch?",
        "isRead": True,
        "threadId": "t2",
        "time": "2026-06-01",
        "labels": ["INBOX"],
    },
    {
        "from": "github",
        "subject": "issue opened",
        "isRead": True,
        "threadId": "t1",
        "time": "2026-06-02",
        "labels": ["INBOX"],
    },
]


def _jsonl(tmp_path: Path, records=RECORDS) -> Path:
    f = tmp_path / "inbox.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return f


def _mock_resolve(path: Path):
    return patch.object(query_json_tool, "resolve_user_file", AsyncMock(return_value=path))


# --- _match_condition -------------------------------------------------------- #


@pytest.mark.parametrize(
    "cond,expected",
    [
        ({"field": "from", "op": "contains", "value": "GIT"}, True),  # case-insensitive
        ({"field": "from", "op": "contains", "value": "nope"}, False),
        ({"field": "from", "op": "equals", "value": "github"}, True),
        ({"field": "from", "op": "not_equals", "value": "github"}, False),
        ({"field": "isRead", "op": "is_false"}, True),
        ({"field": "isRead", "op": "is_true"}, False),
        ({"field": "subject", "op": "exists"}, True),
        ({"field": "missing", "op": "exists"}, False),
        ({"field": "labels", "op": "in", "value": "UNREAD"}, True),
        ({"field": "labels", "op": "in", "value": "SPAM"}, False),
        ({"field": "time", "op": "gt", "value": "2026-06-01"}, True),
        ({"field": "time", "op": "lt", "value": "2026-06-01"}, False),
    ],
)
def test_match_condition(cond: dict, expected: bool) -> None:
    assert _match_condition(RECORDS[0], cond) is expected


def test_match_condition_type_mismatch_is_false_not_error() -> None:
    # gt across incompatible types must not raise.
    assert _match_condition({"n": "abc"}, {"field": "n", "op": "gt", "value": 5}) is False


def test_match_condition_not_equals_true() -> None:
    # A not_equals that actually differs must return True — the parametrized
    # case above only covers the "same value" side, which cannot distinguish
    # not_equals from a broken fall-through to False.
    assert (
        _match_condition({"from": "github"}, {"field": "from", "op": "not_equals", "value": "bob"})
        is True
    )


def test_match_condition_lt_true() -> None:
    # Same for lt: the parametrized case is always False (no record is
    # earlier than the minimum), so a fall-through to False goes unnoticed.
    assert (
        _match_condition({"time": "2026-06-01"}, {"field": "time", "op": "lt", "value": "2026-06-02"})
        is True
    )


def test_match_condition_gt_lt_are_exclusive() -> None:
    # An equal value is neither greater nor less — pins the strict comparison
    # (> vs >=, < vs <=) at the equality boundary.
    rec = {"n": 5}
    assert _match_condition(rec, {"field": "n", "op": "gt", "value": 5}) is False
    assert _match_condition(rec, {"field": "n", "op": "lt", "value": 5}) is False


def test_match_condition_unknown_op_is_false() -> None:
    # An op outside the known set must fall through to False (the tool
    # validates ops earlier, but _match_condition must not blindly match).
    assert _match_condition({"from": "github"}, {"field": "from", "op": "bogus"}) is False


# --- _apply_query ------------------------------------------------------------ #


def test_filter_and_project() -> None:
    out = _apply_query(
        RECORDS,
        where=[{"field": "from", "op": "contains", "value": "github"}],
        match="all",
        fields=["subject"],
        sort_by=None,
        order="desc",
        limit=50,
        count_only=False,
        unique_by=None,
        group_count_by=None,
    )
    assert out == [{"subject": "PR merged"}, {"subject": "issue opened"}]


def test_match_any_is_or() -> None:
    out = _apply_query(
        RECORDS,
        where=[
            {"field": "from", "op": "equals", "value": "github"},
            {"field": "subject", "op": "contains", "value": "lunch"},
        ],
        match="any",
        fields=["threadId"],
        sort_by=None,
        order="desc",
        limit=50,
        count_only=False,
        unique_by=None,
        group_count_by=None,
    )
    assert len(out) == 3  # 2 github + 1 lunch


def test_count_only() -> None:
    out = _apply_query(
        RECORDS,
        where=[{"field": "isRead", "op": "is_true"}],
        match="all",
        fields=None,
        sort_by=None,
        order="desc",
        limit=50,
        count_only=True,
        unique_by=None,
        group_count_by=None,
    )
    assert out == {"count": 2}


def test_sort_and_limit() -> None:
    out = _apply_query(
        RECORDS,
        where=[],
        match="all",
        fields=["time"],
        sort_by="time",
        order="desc",
        limit=1,
        count_only=False,
        unique_by=None,
        group_count_by=None,
    )
    assert out == [{"time": "2026-06-03"}]


def test_unique_by() -> None:
    out = _apply_query(
        RECORDS,
        where=[],
        match="all",
        fields=["threadId"],
        sort_by=None,
        order="desc",
        limit=50,
        count_only=False,
        unique_by="threadId",
        group_count_by=None,
    )
    assert [r["threadId"] for r in out] == ["t1", "t2"]  # t1 deduped


def test_group_count_by() -> None:
    out = _apply_query(
        RECORDS,
        where=[],
        match="all",
        fields=None,
        sort_by=None,
        order="desc",
        limit=50,
        count_only=False,
        unique_by=None,
        group_count_by="from",
    )
    assert out == [{"value": "github", "count": 2}, {"value": "bob@co.com", "count": 1}]


def test_sort_with_missing_field_does_not_crash() -> None:
    recs = [{"a": 1}, {"b": 2}]  # second lacks the sort key
    out = _apply_query(
        recs,
        where=[],
        match="all",
        fields=None,
        sort_by="a",
        order="asc",
        limit=50,
        count_only=False,
        unique_by=None,
        group_count_by=None,
    )
    assert len(out) == 2  # None-sorted last, no TypeError


# --- _load_records ----------------------------------------------------------- #


def test_load_jsonl(tmp_path: Path) -> None:
    records, dropped, truncated = _load_records(_jsonl(tmp_path))
    assert len(records) == 3 and dropped == 0 and truncated is False


def test_load_json_array(tmp_path: Path) -> None:
    f = tmp_path / "arr.json"
    f.write_text(json.dumps(RECORDS))
    records, dropped, _ = _load_records(f)
    assert len(records) == 3 and dropped == 0


def test_load_skips_malformed_lines(tmp_path: Path) -> None:
    f = tmp_path / "mixed.jsonl"
    f.write_text('{"a":1}\nnot json\n{"b":2}\n42\n')
    records, dropped, _ = _load_records(f)
    assert records == [{"a": 1}, {"b": 2}]
    assert dropped == 2  # "not json" + bare 42


# --- large-file defenses ----------------------------------------------------- #


def test_load_bounded_read_caps_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The whole file must NOT be read into memory — only the byte cap.
    monkeypatch.setattr(query_json_tool, "MAX_QUERY_INPUT_BYTES", 30)
    f = _jsonl(tmp_path, [{"n": i} for i in range(100)])
    records, _, truncated = _load_records(f)
    assert truncated is True
    assert 0 < len(records) < 100  # only the bounded prefix was parsed


def test_load_caps_jsonl_record_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query_json_tool, "MAX_QUERY_RECORDS", 5)
    records, _, truncated = _load_records(_jsonl(tmp_path, [{"n": i} for i in range(50)]))
    assert len(records) == 5 and truncated is True


def test_load_caps_array_record_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query_json_tool, "MAX_QUERY_RECORDS", 5)
    f = tmp_path / "arr.json"
    f.write_text(json.dumps([{"n": i} for i in range(50)]))
    records, _, truncated = _load_records(f)
    assert len(records) == 5 and truncated is True


def test_load_pathological_line_is_dropped_not_raised(tmp_path: Path) -> None:
    f = tmp_path / "bad.jsonl"
    f.write_text('{"a":1}\n{"broken":\n{"b":2}\n')  # incomplete middle line
    records, dropped, _ = _load_records(f)
    assert records == [{"a": 1}, {"b": 2}] and dropped == 1


def test_load_dropped_counts_accumulate_per_line(tmp_path: Path) -> None:
    # dropped must accumulate (dropped = 1 per line, not overwritten each time):
    # two parse errors plus two non-dict lines = 4, not 1.
    f = tmp_path / "bad.jsonl"
    f.write_text('bad one\nbad two\n42\n43\n{"a":1}\n')
    records, dropped, truncated = _load_records(f)
    assert records == [{"a": 1}] and dropped == 4 and truncated is False


def test_load_blank_lines_skipped_not_dropped(tmp_path: Path) -> None:
    # Empty and whitespace-only lines are skipped, not counted as unparseable.
    f = tmp_path / "blank.jsonl"
    f.write_text('{"a":1}\n\n  \n{"b":2}\n')
    records, dropped, truncated = _load_records(f)
    assert records == [{"a": 1}, {"b": 2}] and dropped == 0 and truncated is False


def test_load_invalid_utf8_replaced_not_raised(tmp_path: Path) -> None:
    # A non-UTF-8 byte must be replaced, not raise — the decode uses errors="replace".
    f = tmp_path / "latin.jsonl"
    f.write_bytes(b'{"a":1}\n\xff\n{"b":2}\n')
    records, dropped, truncated = _load_records(f)
    assert records == [{"a": 1}, {"b": 2}] and dropped == 1 and truncated is False


def test_load_array_with_leading_whitespace(tmp_path: Path) -> None:
    # Array detection strips leading whitespace (lstrip, not rstrip).
    f = tmp_path / "arr.json"
    f.write_text('  [{"a":1},{"b":2}]  \n')
    records, dropped, truncated = _load_records(f)
    assert records == [{"a": 1}, {"b": 2}] and dropped == 0 and truncated is False


def test_load_array_keeps_only_dict_records(tmp_path: Path) -> None:
    f = tmp_path / "arr.json"
    f.write_text('[{"a":1},"skip",7,null,{"b":2}]')
    records, dropped, truncated = _load_records(f)
    assert records == [{"a": 1}, {"b": 2}] and dropped == 0 and truncated is False


def test_load_array_at_record_cap_not_truncated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Exactly-at-cap arrays are complete (only *over*-cap counts as truncated).
    monkeypatch.setattr(query_json_tool, "MAX_QUERY_RECORDS", 5)
    f = tmp_path / "arr.json"
    f.write_text(json.dumps([{"n": i} for i in range(5)]))
    records, dropped, truncated = _load_records(f)
    assert len(records) == 5 and dropped == 0 and truncated is False


def test_load_byte_cap_exact_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A file that fits exactly in the byte cap is NOT truncated (only over-cap
    # is) — pins > vs >= on the truncation flag.
    body = '{"a":1}\n'
    monkeypatch.setattr(query_json_tool, "MAX_QUERY_INPUT_BYTES", len(body))
    f = tmp_path / "exact.jsonl"
    f.write_text(body)
    records, dropped, truncated = _load_records(f)
    assert records == [{"a": 1}] and dropped == 0 and truncated is False


def test_load_byte_cap_overflow_signals_truncation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query_json_tool, "MAX_QUERY_INPUT_BYTES", len('{"a":1}\n'))
    f = tmp_path / "over.jsonl"
    f.write_text('{"a":1}\n0')  # exactly cap+1 bytes: one full record + one byte of the next
    records, dropped, truncated = _load_records(f)
    assert records == [{"a": 1}] and dropped == 0 and truncated is True


async def test_tool_reports_truncation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query_json_tool, "MAX_QUERY_RECORDS", 2)
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke({"path": "inbox.jsonl"}, config=CONFIG)
    assert "truncated" in out


# --- tool end-to-end (mount mocked) ------------------------------------------ #


async def test_tool_filter_project(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke(
            {
                "path": "inbox.jsonl",
                "where": [
                    {"field": "from", "op": "contains", "value": "github"},
                    {"field": "isRead", "op": "is_false"},
                ],
                "fields": ["subject"],
            },
            config=CONFIG,
        )
    assert json.loads(out) == {"subject": "PR merged"}  # single match, one JSONL line


async def test_tool_count_only(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke(
            {
                "path": "inbox.jsonl",
                "where": [{"field": "from", "op": "contains", "value": "github"}],
                "count_only": True,
            },
            config=CONFIG,
        )
    assert json.loads(out) == {"count": 2}


async def test_tool_no_matches(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke(
            {
                "path": "inbox.jsonl",
                "where": [{"field": "from", "op": "equals", "value": "nobody"}],
            },
            config=CONFIG,
        )
    assert out == "(no matches)"


async def test_tool_rejects_unknown_op(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke(
            {"path": "inbox.jsonl", "where": [{"field": "from", "op": "regex", "value": "x"}]},
            config=CONFIG,
        )
    assert out == f"Error: unknown filter op(s) ['regex']; allowed: {sorted(query_json_tool._OPS)}"


async def test_tool_rejects_bad_match(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke({"path": "inbox.jsonl", "match": "some"}, config=CONFIG)
    assert out == "Error: match must be 'all' or 'any'"


async def test_tool_root_path_rejected() -> None:
    out = await query_json.ainvoke({"path": "/workspace"}, config=CONFIG)
    assert out.startswith("Error:") and out.strip() != "Error:"


async def test_tool_file_not_found() -> None:
    with patch.object(
        query_json_tool, "resolve_user_file", AsyncMock(side_effect=FileNotFoundError("x"))
    ):
        out = await query_json.ainvoke({"path": "x.jsonl"}, config=CONFIG)
    assert out.startswith("Error: file not found")


# --- correctness-fix regressions (brutal) ------------------------------------ #


def test_group_count_by_list_field_does_not_crash() -> None:
    # Gmail `labels` is a list -> was TypeError: unhashable type: 'list'.
    recs = [{"labels": ["A", "B"]}, {"labels": ["A", "B"]}, {"labels": ["C"]}]
    out = _apply_query(
        recs,
        where=[],
        match="all",
        fields=None,
        sort_by=None,
        order="desc",
        limit=50,
        count_only=False,
        unique_by=None,
        group_count_by="labels",
    )
    assert {"value": ["A", "B"], "count": 2} in out
    assert {"value": ["C"], "count": 1} in out


def test_unique_by_list_field_does_not_crash() -> None:
    recs = [{"t": ["x"]}, {"t": ["x"]}, {"t": ["y"]}]
    out = _apply_query(
        recs,
        where=[],
        match="all",
        fields=None,
        sort_by=None,
        order="desc",
        limit=50,
        count_only=False,
        unique_by="t",
        group_count_by=None,
    )
    assert [r["t"] for r in out] == [["x"], ["y"]]


def test_sort_mixed_types_does_not_crash() -> None:
    # A field that is int in some records and str in others -> was TypeError.
    recs = [{"s": 5}, {"s": "high"}, {"s": None}, {"s": 2}]
    out = _apply_query(
        recs,
        where=[],
        match="all",
        fields=None,
        sort_by="s",
        order="asc",
        limit=50,
        count_only=False,
        unique_by=None,
        group_count_by=None,
    )
    assert [r["s"] for r in out] == [None, 2, 5, "high"]  # type-ranked, no crash


@pytest.mark.parametrize("op", ["is_false", "is_true", "exists"])
def test_missing_field_is_neither_true_nor_false(op: str) -> None:
    # is_false previously matched a record that simply lacked the field.
    assert _match_condition({}, {"field": "read", "op": op}) is False


def test_is_false_matches_explicit_false_only() -> None:
    assert _match_condition({"read": False}, {"field": "read", "op": "is_false"}) is True
    assert _match_condition({"read": True}, {"field": "read", "op": "is_false"}) is False


def test_contains_none_value_no_spurious_match() -> None:
    # value=None must not become the literal 'none' and match text containing 'none'.
    assert (
        _match_condition(
            {"body": "error: none found"}, {"field": "body", "op": "contains", "value": None}
        )
        is False
    )


def test_limit_zero_returns_empty() -> None:
    out = _apply_query(
        [{"a": 1}, {"a": 2}],
        where=[],
        match="all",
        fields=None,
        sort_by=None,
        order="desc",
        limit=0,
        count_only=False,
        unique_by=None,
        group_count_by=None,
    )
    assert out == []


def test_large_array_truncation_signals_truncated_not_all_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A JSON array cut off by the byte cap must signal truncation, not silently
    # reinterpret as JSONL and report every line as 'unparseable'.
    monkeypatch.setattr(query_json_tool, "MAX_QUERY_INPUT_BYTES", 40)
    f = tmp_path / "arr.json"
    f.write_text(json.dumps([{"n": i} for i in range(100)]))
    records, dropped, truncated = _load_records(f)
    assert records == [] and truncated is True and dropped == 0


async def test_tool_group_count_by_labels_end_to_end(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke(
            {"path": "inbox.jsonl", "group_count_by": "labels"}, config=CONFIG
        )
    assert "count" in out and "Error" not in out  # list-valued group key, no crash


# --- _hashable / _sort_key (exact grouping/dedup/sort keys) ------------------- #


def test_hashable_scalars_pass_through() -> None:
    assert _hashable(None) is None
    assert _hashable("x") == "x"
    assert _hashable(5) == 5
    assert _hashable(True) is True


def test_hashable_dict_becomes_sorted_json() -> None:
    # sort_keys=True: dict keys must be stable regardless of insertion order.
    assert _hashable({"b": 1, "a": 2}) == '{"a": 2, "b": 1}'


def test_hashable_non_serializable_value_uses_default_str() -> None:
    assert _hashable({"d": date(2026, 6, 1)}) == '{"d": "2026-06-01"}'


def test_sort_key_ranks_types() -> None:
    assert _sort_key(None) == (0, 0)
    assert _sort_key(False) == (1, False)
    assert _sort_key(3) == (2, 3)
    assert _sort_key("x") == (3, "x")


def test_sort_key_dict_becomes_sorted_json() -> None:
    assert _sort_key({"b": 1, "a": 2}) == (4, '{"a": 2, "b": 1}')


def test_sort_key_non_serializable_value_uses_default_str() -> None:
    assert _sort_key({"d": date(2026, 6, 1)}) == (4, '{"d": "2026-06-01"}')


# --- _format_result (exact output strings) ----------------------------------- #


def test_format_count_only_exact() -> None:
    assert _format_result({"count": 2}, dropped=0, truncated=False) == '{"count": 2}'


def test_format_no_matches_exact() -> None:
    assert _format_result([], dropped=0, truncated=False) == "(no matches)"


def test_format_records_joined_exact() -> None:
    assert _format_result([{"a": 1}, {"b": 2}], dropped=0, truncated=False) == '{"a": 1}\n{"b": 2}'


def test_format_non_serializable_values_use_default_str() -> None:
    assert _format_result([{"d": date(2026, 6, 1)}], dropped=0, truncated=False) == '{"d": "2026-06-01"}'


def test_format_truncation_note_exact() -> None:
    out = _format_result([{"a": 1}], dropped=0, truncated=True)
    assert out == '{"a": 1}\n\n[input truncated (file too large) — results may be incomplete]'


def test_format_dropped_note_exact() -> None:
    out = _format_result([{"a": 1}], dropped=3, truncated=False)
    assert out == '{"a": 1}\n\n[3 unparseable line(s) skipped]'


def test_format_both_notes_exact() -> None:
    out = _format_result([{"a": 1}], dropped=3, truncated=True)
    assert out == (
        '{"a": 1}\n\n'
        "[input truncated (file too large) — results may be incomplete; "
        "3 unparseable line(s) skipped]"
    )


def test_format_output_char_cap_exact_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    # A body exactly at the char cap is returned whole (pins > vs >=).
    record = {"pad": "x" * 4}
    body = json.dumps(record)
    monkeypatch.setattr(query_json_tool, "MAX_FILTER_OUTPUT_CHARS", len(body))
    assert _format_result([record], dropped=0, truncated=False) == body


def test_format_output_char_cap_slices_and_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = 10
    monkeypatch.setattr(query_json_tool, "MAX_FILTER_OUTPUT_CHARS", cap)
    record = {"pad": "x" * 20}
    out = _format_result([record], dropped=0, truncated=False)
    assert out == (
        json.dumps(record)[:cap]
        + "\n\n[output truncated at 10 chars — narrow the filter or lower limit]"
    )


# --- tool wiring: exact seam args and defaults ------------------------------- #


async def test_tool_pins_seam_args(tmp_path: Path) -> None:
    # The tool must call its seams with exact args: canonical_rel gets the raw
    # path + resolved session, the concurrency slot and timer get their keys,
    # resolve_user_file gets the resolved user/rel, and the wide event carries
    # the tool name/action.
    logger = MagicMock()
    sem = MagicMock(return_value=AsyncMock())
    timer = MagicMock(return_value=AsyncMock())
    resolve = AsyncMock(return_value=_jsonl(tmp_path))
    canonical = MagicMock(wraps=query_json_tool.canonical_rel)
    _, rel = query_json_tool.canonical_rel("inbox.jsonl", session_id="c1")
    with (
        patch.object(query_json_tool, "canonical_rel", canonical),
        patch.object(query_json_tool, "loop_bound_semaphore", sem),
        patch.object(query_json_tool, "fs_timer", timer),
        patch.object(query_json_tool, "resolve_user_file", resolve),
        patch.object(query_json_tool, "log", logger),
    ):
        out = await query_json.ainvoke({"path": "inbox.jsonl"}, config=CONFIG)
    canonical.assert_called_once_with("inbox.jsonl", session_id="c1")
    sem.assert_called_once_with("query_json", query_json_tool.MAX_QUERY_CONCURRENCY)
    timer.assert_called_once_with(FsOps.TOOL_QUERY_JSON)
    resolve.assert_awaited_once_with("u1", rel)
    logger.set.assert_called_once_with(tool={"name": "query_json", "action": "query"})
    assert len(out.splitlines()) == 3


async def test_tool_passes_exact_query_args(tmp_path: Path) -> None:
    # _apply_query receives every knob as the caller gave it (and where=None
    # becomes []), with count_only/group_count_by defaults filled in.
    where = [{"field": "from", "op": "contains", "value": "github"}]
    spy = MagicMock(wraps=query_json_tool._apply_query)
    with (
        patch.object(query_json_tool, "_apply_query", spy),
        _mock_resolve(_jsonl(tmp_path)),
    ):
        out = await query_json.ainvoke(
            {
                "path": "inbox.jsonl",
                "where": where,
                "match": "any",
                "fields": ["subject"],
                "sort_by": "time",
                "order": "asc",
                "limit": 2,
                "unique_by": "threadId",
            },
            config=CONFIG,
        )
    assert spy.call_count == 1
    call = spy.call_args
    assert call.args[0] == RECORDS
    assert call.kwargs == {
        "where": where,
        "match": "any",
        "fields": ["subject"],
        "sort_by": "time",
        "order": "asc",
        "limit": 2,
        "count_only": False,
        "unique_by": "threadId",
        "group_count_by": None,
    }
    assert out == '{"subject": "PR merged"}'


async def test_tool_defaults(tmp_path: Path) -> None:
    # match/order/limit/count_only defaults: match is AND, order desc, 50 max,
    # and records (not a count) are returned.
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke(
            {
                "path": "inbox.jsonl",
                "fields": ["time"],
                "where": [
                    {"field": "from", "op": "equals", "value": "github"},
                    {"field": "from", "op": "equals", "value": "bob@co.com"},
                ],
            },
            config=CONFIG,
        )
    assert out == "(no matches)"  # AND of two mutually exclusive conditions

    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke(
            {"path": "inbox.jsonl", "fields": ["time"], "sort_by": "time"}, config=CONFIG
        )
    assert out.splitlines() == [
        '{"time": "2026-06-03"}',
        '{"time": "2026-06-02"}',
        '{"time": "2026-06-01"}',
    ]  # desc, not asc

    with _mock_resolve(_jsonl(tmp_path, [{"n": i} for i in range(60)])):
        out = await query_json.ainvoke({"path": "inbox.jsonl"}, config=CONFIG)
    assert len(out.splitlines()) == 50  # default limit, not 51


async def test_tool_match_any_succeeds(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke(
            {
                "path": "inbox.jsonl",
                "match": "any",
                "where": [{"field": "subject", "op": "contains", "value": "lunch"}],
            },
            config=CONFIG,
        )
    assert json.loads(out) == RECORDS[1]  # 'any' is accepted, not rejected


async def test_tool_file_not_found_exact_message() -> None:
    with (
        patch.object(query_json_tool, "canonical_rel", return_value=("/workspace/scratch/x.jsonl", "x.jsonl")),
        patch.object(query_json_tool, "resolve_user_file", AsyncMock(side_effect=FileNotFoundError("nope"))),
    ):
        out = await query_json.ainvoke({"path": "x.jsonl"}, config=CONFIG)
    assert out == "Error: file not found at /workspace/scratch/x.jsonl"


async def test_tool_runtime_error_exact_message_and_log() -> None:
    logger = MagicMock()
    with (
        patch.object(query_json_tool, "log", logger),
        patch.object(query_json_tool, "canonical_rel", return_value=("/workspace/x.jsonl", "x.jsonl")),
        patch.object(query_json_tool, "resolve_user_file", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        out = await query_json.ainvoke({"path": "x.jsonl"}, config=CONFIG)
    assert out == "Error running query_json: boom"
    logger.error.assert_called_once_with(
        f"{LogTag.SANDBOX} query_json failed", error_type="RuntimeError", exc_info=True
    )


async def test_tool_reports_dropped_lines(tmp_path: Path) -> None:
    f = tmp_path / "bad.jsonl"
    f.write_text('{"a":1}\nnot json\n{"b":2}\n')
    with _mock_resolve(f):
        out = await query_json.ainvoke({"path": "bad.jsonl"}, config=CONFIG)
    assert "1 unparseable line(s) skipped" in out
