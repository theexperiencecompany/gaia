"""Compaction middleware: query_json/grep auto-bind on offload.

The bind appends the mining tools to `selected_tool_ids` (append-only reducer)
only when a tool result carries an offload marker, deduped against what's already
selected, and it fires even for tools excluded from compaction (gmail self-offload).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage
from langgraph.types import Command
import pytest

from app.agents.middleware import compaction as compaction_mod
from app.agents.middleware.compaction import WorkspaceCompactionMiddleware
from app.agents.tools.coding import query_json_tool
from app.agents.tools.coding.query_json_tool import query_json
from app.agents.workspace.offload import mark_offload, read_offload, tools_for_offload

pytestmark = pytest.mark.unit


def _persist_request() -> SimpleNamespace:
    return SimpleNamespace(
        tool_call={"name": "search", "id": "1", "args": {}},
        runtime=SimpleNamespace(config={"configurable": {"user_id": "u1", "thread_id": "c1"}}),
    )

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


def test_bind_appends_query_json_grep_when_marker_present() -> None:
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(_marked(), _req([]))
    assert isinstance(r, Command)
    assert r.update["selected_tool_ids"] == ["query_json", "grep"]
    assert r.update["messages"][0].content == "digest"  # the result still flows through


def test_bind_dedups_already_selected() -> None:
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(_marked(), _req(["query_json"]))
    assert isinstance(r, Command)
    assert r.update["selected_tool_ids"] == ["grep"]  # only the missing one


def test_bind_passthrough_when_all_present() -> None:
    msg = _marked()
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(msg, _req(["query_json", "grep"]))
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
    assert r.update["selected_tool_ids"] == ["query_json", "grep"]


def test_bind_ignores_non_str_junk_in_selected_tool_ids() -> None:
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(_marked(), _req([123, None, "query_json"]))
    assert isinstance(r, Command)
    assert r.update["selected_tool_ids"] == ["grep"]  # query_json already there, junk ignored


# --- awrap_tool_call ordering ------------------------------------------------ #


async def test_awrap_excluded_self_offloading_tool_still_binds() -> None:
    # GMAIL_FETCH_MESSAGES is excluded from compaction, yet its lifted marker must
    # still surface query_json/grep — the bind keys on the marker, not on compaction firing.
    mw = WorkspaceCompactionMiddleware(excluded_tools={"GMAIL_FETCH_MESSAGES"})
    req = SimpleNamespace(
        tool_call={"name": "GMAIL_FETCH_MESSAGES", "id": "1"},
        state={"messages": [], "selected_tool_ids": []},
    )

    async def handler(_req):
        return _marked()

    res = await mw.awrap_tool_call(req, handler)
    assert isinstance(res, Command)
    assert res.update["selected_tool_ids"] == ["query_json", "grep"]


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


# --- _persist writes a file query_json can actually mine (the P0 regression) -- #


async def test_persist_writes_raw_jsonl_and_query_json_can_mine_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = [{"from": "github", "subject": "a"}, {"from": "bob", "subject": "b"}]
    content = "\n".join(json.dumps(r) for r in records)
    captured: dict = {}

    async def fake_write(*, user_id, conversation_id, relative_path, content):
        p = tmp_path / "offloaded"
        p.write_text(content)
        captured.update(path=p, rel=relative_path, content=content)
        return p, f"/workspace/sessions/{conversation_id}/{relative_path}"

    monkeypatch.setattr(compaction_mod, "write_session_file", fake_write)
    out = await WorkspaceCompactionMiddleware()._persist(
        ToolMessage(content=content, tool_call_id="1", name="search"), _persist_request(), "large_output"
    )

    assert captured["content"] == content  # RAW jsonl written, not a metadata wrapper
    assert captured["rel"].endswith(".jsonl")
    info = read_offload(out)
    assert info is not None and info["fmt"] == "jsonl"

    # THE POINT: query_json can actually query the file compaction produced.
    with patch.object(query_json_tool, "resolve_user_file", AsyncMock(return_value=captured["path"])):
        q = await query_json.ainvoke(
            {"path": "tool_outputs/x.jsonl",
             "where": [{"field": "from", "op": "contains", "value": "github"}],
             "fields": ["subject"]},
            config={"configurable": {"user_id": "u1", "conversation_id": "c1"}},
        )
    assert json.loads(q) == {"subject": "a"}


async def test_persist_text_output_marks_grep_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = "\n".join(f"log line {i} with error" for i in range(500))
    captured: dict = {}

    async def fake_write(*, user_id, conversation_id, relative_path, content):
        captured.update(rel=relative_path, content=content)
        return tmp_path / "x", f"/workspace/x/{relative_path}"

    monkeypatch.setattr(compaction_mod, "write_session_file", fake_write)
    out = await WorkspaceCompactionMiddleware()._persist(
        ToolMessage(content=content, tool_call_id="1", name="run"), _persist_request(), "large_output"
    )

    assert captured["content"] == content and captured["rel"].endswith(".txt")
    info = read_offload(out)
    assert info is not None and info["fmt"] == "text"
    assert tools_for_offload(info) == ["grep"]  # query_json NOT surfaced for plain text
