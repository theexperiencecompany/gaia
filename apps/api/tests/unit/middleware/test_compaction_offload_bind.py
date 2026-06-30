"""Compaction middleware: jq/grep auto-bind on offload.

The bind appends the mining tools to `selected_tool_ids` (append-only reducer)
only when a tool result carries an offload marker, deduped against what's already
selected, and it fires even for tools excluded from compaction (gmail self-offload).
"""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import ToolMessage
from langgraph.types import Command
import pytest

from app.agents.middleware.compaction import WorkspaceCompactionMiddleware
from app.agents.workspace.offload import mark_offload

pytestmark = pytest.mark.unit

INFO = {"path": "/w/x.jsonl", "bytes": 10, "fmt": "jsonl", "producer": "GMAIL_FETCH_MESSAGES", "records": 3}


def _marked(fmt: str = "jsonl") -> ToolMessage:
    return ToolMessage(
        content="digest",
        tool_call_id="1",
        name="GMAIL_FETCH_MESSAGES",
        additional_kwargs=mark_offload({}, {**INFO, "fmt": fmt}),  # type: ignore[arg-type]
    )


def _req(selected: list) -> SimpleNamespace:
    return SimpleNamespace(state={"selected_tool_ids": selected})


# --- _bind_offload_tools (direct) -------------------------------------------- #


def test_bind_appends_jq_grep_when_marker_present() -> None:
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(_marked(), _req([]))
    assert isinstance(r, Command)
    assert r.update["selected_tool_ids"] == ["jq", "grep"]
    assert r.update["messages"][0].content == "digest"  # the result still flows through


def test_bind_dedups_already_selected() -> None:
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(_marked(), _req(["jq"]))
    assert isinstance(r, Command)
    assert r.update["selected_tool_ids"] == ["grep"]  # only the missing one


def test_bind_passthrough_when_all_present() -> None:
    msg = _marked()
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(msg, _req(["jq", "grep"]))
    assert r is msg  # nothing to bind -> plain ToolMessage, no Command


def test_bind_text_fmt_binds_grep_only() -> None:
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(_marked("text"), _req([]))
    assert isinstance(r, Command)
    assert r.update["selected_tool_ids"] == ["grep"]


def test_bind_no_marker_passthrough() -> None:
    msg = ToolMessage(content="x", tool_call_id="2", name="t")
    assert WorkspaceCompactionMiddleware()._bind_offload_tools(msg, _req([])) is msg


def test_bind_handles_none_state() -> None:
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(_marked(), SimpleNamespace(state=None))
    assert isinstance(r, Command)
    assert r.update["selected_tool_ids"] == ["jq", "grep"]


def test_bind_ignores_non_str_junk_in_selected_tool_ids() -> None:
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(_marked(), _req([123, None, "jq"]))
    assert isinstance(r, Command)
    assert r.update["selected_tool_ids"] == ["grep"]  # jq already there, junk ignored


# --- awrap_tool_call ordering ------------------------------------------------ #


async def test_awrap_excluded_self_offloading_tool_still_binds() -> None:
    # GMAIL_FETCH_MESSAGES is excluded from compaction, yet its lifted marker must
    # still surface jq/grep — the bind keys on the marker, not on compaction firing.
    mw = WorkspaceCompactionMiddleware(excluded_tools={"GMAIL_FETCH_MESSAGES"})
    req = SimpleNamespace(
        tool_call={"name": "GMAIL_FETCH_MESSAGES", "id": "1"},
        state={"messages": [], "selected_tool_ids": []},
    )

    async def handler(_req):
        return _marked()

    res = await mw.awrap_tool_call(req, handler)
    assert isinstance(res, Command)
    assert res.update["selected_tool_ids"] == ["jq", "grep"]


async def test_awrap_command_result_passes_through_untouched() -> None:
    mw = WorkspaceCompactionMiddleware()
    cmd = Command(update={"messages": []})
    req = SimpleNamespace(tool_call={"name": "x", "id": "1"}, state={"messages": []})

    async def handler(_req):
        return cmd

    assert await mw.awrap_tool_call(req, handler) is cmd


async def test_awrap_plain_small_output_passes_through() -> None:
    mw = WorkspaceCompactionMiddleware()
    msg = ToolMessage(content="small", tool_call_id="1", name="x")
    req = SimpleNamespace(tool_call={"name": "x", "id": "1"}, state={"messages": [], "selected_tool_ids": []})

    async def handler(_req):
        return msg

    assert await mw.awrap_tool_call(req, handler) is msg
