"""Structured offload marker helpers — round-trip, lift, tolerance.

Pure unit tests (no I/O). Cover the read-side validators whose contracts must
agree: read_offload only guarantees `path`, so tools_for_offload must tolerate a
missing/unknown `fmt` (F1), and read_offload must never raise on a non-dict
additional_kwargs (F2).
"""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import ToolMessage
import pytest

from app.agents.workspace.offload import (
    OFFLOAD_RESULT_KEY,
    mark_offload,
    pop_offload_descriptor,
    read_offload,
    tools_for_offload,
)
from app.constants.offload import GREP_TOOL_NAME, JQ_TOOL_NAME, OFFLOAD_KEY

pytestmark = pytest.mark.unit

INFO = {"path": "/w/x.jsonl", "bytes": 10, "fmt": "jsonl", "producer": "p", "records": 3}


def _msg(additional_kwargs: dict) -> ToolMessage:
    return ToolMessage(content="d", tool_call_id="1", name="t", additional_kwargs=additional_kwargs)


# --- mark_offload / read_offload --------------------------------------------- #


def test_mark_offload_is_non_mutating_and_round_trips() -> None:
    base = {"existing": 1}
    out = mark_offload(base, INFO)  # type: ignore[arg-type]
    assert base == {"existing": 1}  # input untouched
    assert out[OFFLOAD_KEY] == INFO and out["existing"] == 1
    assert read_offload(_msg(out)) == INFO


def test_read_offload_absent_marker_is_none() -> None:
    assert read_offload(_msg({"other": 1})) is None


def test_read_offload_marker_without_path_is_none() -> None:
    assert read_offload(_msg({OFFLOAD_KEY: {"fmt": "jsonl"}})) is None


def test_read_offload_path_not_str_is_none() -> None:
    assert read_offload(_msg({OFFLOAD_KEY: {"path": 123}})) is None


def test_read_offload_non_dict_additional_kwargs_returns_none() -> None:
    # F2: must not raise AttributeError when additional_kwargs isn't a dict.
    assert read_offload(SimpleNamespace(additional_kwargs="not-a-dict")) is None  # type: ignore[arg-type]
    assert read_offload(SimpleNamespace(additional_kwargs=None)) is None  # type: ignore[arg-type]
    assert read_offload(SimpleNamespace()) is None  # type: ignore[arg-type]


# --- pop_offload_descriptor -------------------------------------------------- #


def test_pop_descriptor_strips_key_and_keeps_real_fields() -> None:
    result = {"total_messages": 5, "inline_preview": [1, 2], OFFLOAD_RESULT_KEY: INFO}
    info = pop_offload_descriptor(result)
    assert info == INFO
    assert OFFLOAD_RESULT_KEY not in result  # popped so it can't leak into content
    assert OFFLOAD_RESULT_KEY not in str(result)
    assert result == {"total_messages": 5, "inline_preview": [1, 2]}  # real fields survive


@pytest.mark.parametrize(
    "descriptor",
    [{"fmt": "jsonl"}, {"path": 5}, "not-a-dict", None, [1, 2]],
)
def test_pop_descriptor_malformed_returns_none_but_still_pops(descriptor: object) -> None:
    result = {"a": 1, OFFLOAD_RESULT_KEY: descriptor}
    assert pop_offload_descriptor(result) is None
    assert OFFLOAD_RESULT_KEY not in result  # always removed, even when invalid


@pytest.mark.parametrize("result", [[1, 2], "str", None, 42, {"a": 1}])
def test_pop_descriptor_no_key_or_non_dict_is_none(result: object) -> None:
    assert pop_offload_descriptor(result) is None


# --- tools_for_offload ------------------------------------------------------- #


@pytest.mark.parametrize("fmt", ["json", "jsonl"])
def test_tools_for_offload_structured_gets_jq_and_grep(fmt: str) -> None:
    assert tools_for_offload({**INFO, "fmt": fmt}) == [JQ_TOOL_NAME, GREP_TOOL_NAME]  # type: ignore[arg-type]


def test_tools_for_offload_text_gets_grep_only() -> None:
    assert tools_for_offload({**INFO, "fmt": "text"}) == [GREP_TOOL_NAME]  # type: ignore[arg-type]


@pytest.mark.parametrize("fmt", ["csv", "", "JSON", "yaml"])
def test_tools_for_offload_unknown_fmt_gets_grep(fmt: str) -> None:
    assert tools_for_offload({**INFO, "fmt": fmt}) == [GREP_TOOL_NAME]  # type: ignore[arg-type]


def test_tools_for_offload_missing_fmt_defaults_to_grep() -> None:
    # F1: a marker that only satisfied read_offload's `path` check must not KeyError.
    assert tools_for_offload({"path": "/w/x", "bytes": 1, "producer": "p", "records": None}) == [  # type: ignore[arg-type]
        GREP_TOOL_NAME
    ]
