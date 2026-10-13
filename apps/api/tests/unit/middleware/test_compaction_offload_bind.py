"""Compaction middleware: query_json/grep auto-bind on offload.

The bind appends the mining tools to selected_tool_ids (append-only reducer)
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

INFO = {
    "path": "/w/x.jsonl",
    "bytes": 10,
    "fmt": "jsonl",
    "producer": "GMAIL_FETCH_MESSAGES",
    "records": 3,
}


def _marked(fmt: str = "jsonl") -> ToolMessage:
    return ToolMessage(
        content="digest",
        tool_call_id="1",
        name="GMAIL_FETCH_MESSAGES",
        additional_kwargs=mark_offload({}, {**INFO, "fmt": fmt}),  # type: ignore[typeddict-item]  # loose dict expanded into a TypedDict parameter
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
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(
        _marked(), _req([123, None, "query_json"])
    )
    assert isinstance(r, Command)
    assert r.update["selected_tool_ids"] == ["grep"]  # query_json already there, junk ignored


# --- awrap_tool_call ordering ------------------------------------------------ #


async def test_awrap_excluded_self_offloading_tool_still_binds() -> None:
    # GMAIL_FETCH_MESSAGES is excluded from compaction, yet its lifted marker must
    # still surface query_json/grep — the bind keys on the marker, not on compaction firing.
    mw = WorkspaceCompactionMiddleware(excluded_tools={"GMAIL_FETCH_MESSAGES"})
    req = SimpleNamespace(
        tool_call={"name": "GMAIL_FETCH_MESSAGES", "id": "1", "args": {}},
        runtime=SimpleNamespace(config={"configurable": {"user_id": "u1", "thread_id": "c1"}}),
        state={"messages": [], "selected_tool_ids": []},
    )

    async def handler(_req):
        return _marked()

    res = await mw.awrap_tool_call(req, handler)
    assert isinstance(res, Command)
    assert res.update["selected_tool_ids"] == ["query_json", "grep"]


def _gmail_request(selected: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        tool_call={"name": "GMAIL_FETCH_MESSAGES", "id": "1", "args": {}},
        runtime=SimpleNamespace(config={"configurable": {"user_id": "u1", "thread_id": "c1"}}),
        state={"messages": [], "selected_tool_ids": selected},
    )


async def test_awrap_miners_already_bound_leave_a_plain_message() -> None:
    mw = WorkspaceCompactionMiddleware(excluded_tools={"GMAIL_FETCH_MESSAGES"})
    marked = _marked()

    async def handler(_req):
        return marked

    res = await mw.awrap_tool_call(_gmail_request(["query_json", "grep"]), handler)

    assert res is marked


async def test_awrap_a_compacted_command_output_replaces_the_original_message() -> None:
    """With nothing left to bind, the compacted message itself must still land in the Command."""
    mw = WorkspaceCompactionMiddleware()
    original = ToolMessage(content="huge", tool_call_id="1", name="GMAIL_FETCH_MESSAGES")
    compacted = _marked()
    command = Command(update={"messages": [original], "selected_tool_ids": ["read"]})

    async def handler(_req):
        return command

    with patch.object(compaction_mod, "compact_tool_output", AsyncMock(return_value=compacted)):
        res = await mw.awrap_tool_call(_gmail_request(["query_json", "grep"]), handler)

    assert res is command
    assert res.update == {"messages": [compacted], "selected_tool_ids": ["read"]}


async def test_awrap_hands_the_tool_its_own_request() -> None:
    mw = WorkspaceCompactionMiddleware()
    req = _gmail_request([])
    seen: list[object] = []

    async def handler(request):
        seen.append(request)
        return ToolMessage(content="small", tool_call_id="1", name="GMAIL_FETCH_MESSAGES")

    await mw.awrap_tool_call(req, handler)

    assert seen == [req]


async def test_awrap_without_a_vfs_session_offloads_under_the_thread() -> None:
    mw = WorkspaceCompactionMiddleware()
    compact = AsyncMock(return_value=None)

    async def handler(_req):
        return ToolMessage(content="huge", tool_call_id="1", name="GMAIL_FETCH_MESSAGES")

    with patch.object(compaction_mod, "compact_tool_output", compact):
        await mw.awrap_tool_call(_gmail_request([]), handler)

    assert compact.await_args.kwargs["conversation_id"] == "c1"
    assert compact.await_args.kwargs["user_id"] == "u1"


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
    req = SimpleNamespace(
        tool_call={"name": "x", "id": "1", "args": {}},
        runtime=SimpleNamespace(config={"configurable": {"user_id": "u1", "thread_id": "c1"}}),
        state={"messages": [], "selected_tool_ids": []},
    )

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
    fmt, sandbox_path = await compaction_mod._write_raw_output(
        content_str=content,
        tool_name="search",
        user_id="u1",
        conversation_id="c1",
    )
    out = compaction_mod._stub_spill_message(
        content_str=content,
        fmt=fmt,
        sandbox_path=sandbox_path,
        tool_name="search",
        tool_call_id="1",
        reason="large_output",
        status="success",
        existing_additional_kwargs={},
    )

    assert captured["content"] == content  # RAW jsonl written, not a metadata wrapper
    assert captured["rel"].endswith(".jsonl")
    info = read_offload(out)
    assert info is not None and info["fmt"] == "jsonl"

    # THE POINT: query_json can actually query the file compaction produced.
    with patch.object(
        query_json_tool, "resolve_user_file", AsyncMock(return_value=captured["path"])
    ):
        q = await query_json.ainvoke(
            {
                "path": "tool_outputs/x.jsonl",
                "where": [{"field": "from", "op": "contains", "value": "github"}],
                "fields": ["subject"],
            },
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
    fmt, sandbox_path = await compaction_mod._write_raw_output(
        content_str=content,
        tool_name="run",
        user_id="u1",
        conversation_id="c1",
    )
    out = compaction_mod._stub_spill_message(
        content_str=content,
        fmt=fmt,
        sandbox_path=sandbox_path,
        tool_name="run",
        tool_call_id="1",
        reason="large_output",
        status="success",
        existing_additional_kwargs={},
    )

    assert captured["content"] == content and captured["rel"].endswith(".txt")
    info = read_offload(out)
    assert info is not None and info["fmt"] == "text"
    assert tools_for_offload(info) == ["grep"]  # query_json NOT surfaced for plain text
