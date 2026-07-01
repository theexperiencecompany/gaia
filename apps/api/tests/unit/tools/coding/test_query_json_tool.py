"""query_json: the in-process structured JSON/JSONL query engine + tool.

Pure engine tests (filter/project/sort/count/dedupe/group + record parsing) plus
the tool end-to-end with the JuiceFS boundary mocked. It is safe by construction
(no subprocess, no eval, no file access beyond the one workspace file), so these
tests focus on correctness of the six operations.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.coding import query_json_tool
from app.agents.tools.coding.query_json_tool import (
    _apply_query,
    _load_records,
    _match_condition,
    query_json,
)

pytestmark = pytest.mark.unit

CONFIG = {"configurable": {"user_id": "u1", "conversation_id": "c1"}}

RECORDS = [
    {"from": "github", "subject": "PR merged", "isRead": False, "threadId": "t1", "time": "2026-06-03", "labels": ["INBOX", "UNREAD"]},
    {"from": "bob@co.com", "subject": "lunch?", "isRead": True, "threadId": "t2", "time": "2026-06-01", "labels": ["INBOX"]},
    {"from": "github", "subject": "issue opened", "isRead": True, "threadId": "t1", "time": "2026-06-02", "labels": ["INBOX"]},
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


# --- _apply_query ------------------------------------------------------------ #


def test_filter_and_project() -> None:
    out = _apply_query(
        RECORDS,
        where=[{"field": "from", "op": "contains", "value": "github"}],
        match="all", fields=["subject"], sort_by=None, order="desc", limit=50,
        count_only=False, unique_by=None, group_count_by=None,
    )
    assert out == [{"subject": "PR merged"}, {"subject": "issue opened"}]


def test_match_any_is_or() -> None:
    out = _apply_query(
        RECORDS,
        where=[{"field": "from", "op": "equals", "value": "github"},
               {"field": "subject", "op": "contains", "value": "lunch"}],
        match="any", fields=["threadId"], sort_by=None, order="desc", limit=50,
        count_only=False, unique_by=None, group_count_by=None,
    )
    assert len(out) == 3  # 2 github + 1 lunch


def test_count_only() -> None:
    out = _apply_query(
        RECORDS, where=[{"field": "isRead", "op": "is_true"}], match="all",
        fields=None, sort_by=None, order="desc", limit=50,
        count_only=True, unique_by=None, group_count_by=None,
    )
    assert out == {"count": 2}


def test_sort_and_limit() -> None:
    out = _apply_query(
        RECORDS, where=[], match="all", fields=["time"], sort_by="time", order="desc",
        limit=1, count_only=False, unique_by=None, group_count_by=None,
    )
    assert out == [{"time": "2026-06-03"}]


def test_unique_by() -> None:
    out = _apply_query(
        RECORDS, where=[], match="all", fields=["threadId"], sort_by=None, order="desc",
        limit=50, count_only=False, unique_by="threadId", group_count_by=None,
    )
    assert [r["threadId"] for r in out] == ["t1", "t2"]  # t1 deduped


def test_group_count_by() -> None:
    out = _apply_query(
        RECORDS, where=[], match="all", fields=None, sort_by=None, order="desc",
        limit=50, count_only=False, unique_by=None, group_count_by="from",
    )
    assert out == [{"value": "github", "count": 2}, {"value": "bob@co.com", "count": 1}]


def test_sort_with_missing_field_does_not_crash() -> None:
    recs = [{"a": 1}, {"b": 2}]  # second lacks the sort key
    out = _apply_query(
        recs, where=[], match="all", fields=None, sort_by="a", order="asc",
        limit=50, count_only=False, unique_by=None, group_count_by=None,
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


async def test_tool_reports_truncation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query_json_tool, "MAX_QUERY_RECORDS", 2)
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke({"path": "inbox.jsonl"}, config=CONFIG)
    assert "truncated" in out


# --- tool end-to-end (mount mocked) ------------------------------------------ #


async def test_tool_filter_project(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke(
            {"path": "inbox.jsonl",
             "where": [{"field": "from", "op": "contains", "value": "github"},
                       {"field": "isRead", "op": "is_false"}],
             "fields": ["subject"]},
            config=CONFIG,
        )
    assert json.loads(out) == {"subject": "PR merged"}  # single match, one JSONL line


async def test_tool_count_only(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke(
            {"path": "inbox.jsonl", "where": [{"field": "from", "op": "contains", "value": "github"}],
             "count_only": True},
            config=CONFIG,
        )
    assert json.loads(out) == {"count": 2}


async def test_tool_no_matches(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke(
            {"path": "inbox.jsonl", "where": [{"field": "from", "op": "equals", "value": "nobody"}]},
            config=CONFIG,
        )
    assert out == "(no matches)"


async def test_tool_rejects_unknown_op(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke(
            {"path": "inbox.jsonl", "where": [{"field": "from", "op": "regex", "value": "x"}]},
            config=CONFIG,
        )
    assert "unknown filter op" in out


async def test_tool_rejects_bad_match(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await query_json.ainvoke({"path": "inbox.jsonl", "match": "some"}, config=CONFIG)
    assert "match must be" in out


async def test_tool_root_path_rejected() -> None:
    out = await query_json.ainvoke({"path": "/workspace"}, config=CONFIG)
    assert out.startswith("Error:") and out.strip() != "Error:"


async def test_tool_file_not_found() -> None:
    with patch.object(query_json_tool, "resolve_user_file", AsyncMock(side_effect=FileNotFoundError("x"))):
        out = await query_json.ainvoke({"path": "x.jsonl"}, config=CONFIG)
    assert out.startswith("Error: file not found")


# --- correctness-fix regressions (brutal) ------------------------------------ #


def test_group_count_by_list_field_does_not_crash() -> None:
    # Gmail `labels` is a list -> was TypeError: unhashable type: 'list'.
    recs = [{"labels": ["A", "B"]}, {"labels": ["A", "B"]}, {"labels": ["C"]}]
    out = _apply_query(recs, where=[], match="all", fields=None, sort_by=None, order="desc",
                       limit=50, count_only=False, unique_by=None, group_count_by="labels")
    assert {"value": ["A", "B"], "count": 2} in out
    assert {"value": ["C"], "count": 1} in out


def test_unique_by_list_field_does_not_crash() -> None:
    recs = [{"t": ["x"]}, {"t": ["x"]}, {"t": ["y"]}]
    out = _apply_query(recs, where=[], match="all", fields=None, sort_by=None, order="desc",
                       limit=50, count_only=False, unique_by="t", group_count_by=None)
    assert [r["t"] for r in out] == [["x"], ["y"]]


def test_sort_mixed_types_does_not_crash() -> None:
    # A field that is int in some records and str in others -> was TypeError.
    recs = [{"s": 5}, {"s": "high"}, {"s": None}, {"s": 2}]
    out = _apply_query(recs, where=[], match="all", fields=None, sort_by="s", order="asc",
                       limit=50, count_only=False, unique_by=None, group_count_by=None)
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
    assert _match_condition({"body": "error: none found"},
                            {"field": "body", "op": "contains", "value": None}) is False


def test_limit_zero_returns_empty() -> None:
    out = _apply_query([{"a": 1}, {"a": 2}], where=[], match="all", fields=None, sort_by=None,
                       order="desc", limit=0, count_only=False, unique_by=None, group_count_by=None)
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
        out = await query_json.ainvoke({"path": "inbox.jsonl", "group_count_by": "labels"}, config=CONFIG)
    assert "count" in out and "Error" not in out  # list-valued group key, no crash
