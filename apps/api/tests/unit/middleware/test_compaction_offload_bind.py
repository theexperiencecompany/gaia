"""Compaction middleware: query_json/grep auto-bind on offload.

The bind appends the mining tools to selected_tool_ids (append-only reducer)
only when a tool result carries an offload marker, deduped against what's already
selected, and it fires even for tools excluded from compaction.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolCall, ToolMessage
from langgraph.types import Command
import pytest

from app.agents.middleware import compaction as compaction_mod
from app.agents.middleware.compaction import WorkspaceCompactionMiddleware
from app.agents.tools.coding import query_json_tool
from app.agents.tools.coding.query_json_tool import query_json
from app.agents.workspace.offload import mark_offload, read_offload, tools_for_offload
from tests.helpers import tool_call_request

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


IDENTITY: dict[str, object] = {"user_id": "u1", "thread_id": "c1"}


def _request(
    selected: list[object] | None = None,
    *,
    name: str = "GMAIL_FETCH_MESSAGES",
    args: dict[str, object] | None = None,
) -> ToolCallRequest:
    call = ToolCall(name=name, args=args or {}, id="1")
    state: dict[str, object] | None = (
        None if selected is None else {"messages": [], "selected_tool_ids": selected}
    )
    return tool_call_request(call, configurable=IDENTITY, state=state)


# --- _bind_offload_tools (direct) -------------------------------------------- #


def test_bind_appends_query_json_grep_when_marker_present() -> None:
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(_marked(), _request([]))
    assert isinstance(r, Command)
    assert r.update["selected_tool_ids"] == ["query_json", "grep"]
    assert r.update["messages"][0].content == "digest"  # the result still flows through


def test_bind_dedups_already_selected() -> None:
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(_marked(), _request(["query_json"]))
    assert isinstance(r, Command)
    assert r.update["selected_tool_ids"] == ["grep"]  # only the missing one


def test_bind_passthrough_when_all_present() -> None:
    msg = _marked()
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(msg, _request(["query_json", "grep"]))
    assert r is msg  # nothing to bind -> plain ToolMessage, no Command


def test_bind_text_fmt_binds_grep_only() -> None:
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(_marked("text"), _request([]))
    assert isinstance(r, Command)
    assert r.update["selected_tool_ids"] == ["grep"]


def test_bind_no_marker_passthrough() -> None:
    msg = ToolMessage(content="x", tool_call_id="2", name="t")
    assert WorkspaceCompactionMiddleware()._bind_offload_tools(msg, _request([])) is msg


def test_bind_handles_none_state() -> None:
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(_marked(), _request())
    assert isinstance(r, Command)
    assert r.update["selected_tool_ids"] == ["query_json", "grep"]


def test_bind_ignores_non_str_junk_in_selected_tool_ids() -> None:
    r = WorkspaceCompactionMiddleware()._bind_offload_tools(
        _marked(), _request([123, None, "query_json"])
    )
    assert isinstance(r, Command)
    assert r.update["selected_tool_ids"] == ["grep"]  # query_json already there, junk ignored


# --- awrap_tool_call ordering ------------------------------------------------ #


async def test_awrap_excluded_tool_carrying_a_marker_still_binds() -> None:
    # The bind keys on the marker, not on compaction firing.
    mw = WorkspaceCompactionMiddleware(excluded_tools={"GMAIL_FETCH_MESSAGES"})

    async def handler(_req: ToolCallRequest) -> ToolMessage:
        return _marked()

    res = await mw.awrap_tool_call(_request([]), handler)
    assert isinstance(res, Command)
    assert res.update["selected_tool_ids"] == ["query_json", "grep"]


async def test_awrap_miners_already_bound_leave_a_plain_message() -> None:
    mw = WorkspaceCompactionMiddleware(excluded_tools={"GMAIL_FETCH_MESSAGES"})
    marked = _marked()

    async def handler(_req: ToolCallRequest) -> ToolMessage | Command[str]:
        return marked

    res = await mw.awrap_tool_call(_request(["query_json", "grep"]), handler)

    assert res is marked


async def test_awrap_a_compacted_command_output_replaces_the_original_message() -> None:
    """With nothing left to bind, the compacted message itself must still land in the Command."""
    mw = WorkspaceCompactionMiddleware()
    original = ToolMessage(content="huge", tool_call_id="1", name="GMAIL_FETCH_MESSAGES")
    compacted = _marked()
    command: Command[str] = Command(update={"messages": [original], "selected_tool_ids": ["read"]})

    async def handler(_req: ToolCallRequest) -> ToolMessage | Command[str]:
        return command

    with patch.object(compaction_mod, "compact_tool_output", AsyncMock(return_value=compacted)):
        res = await mw.awrap_tool_call(_request(["query_json", "grep"]), handler)

    assert res is command
    assert command.update == {"messages": [compacted], "selected_tool_ids": ["read"]}


async def test_awrap_hands_the_tool_its_own_request() -> None:
    mw = WorkspaceCompactionMiddleware()
    req = _request([])
    seen: list[object] = []

    async def handler(request: ToolCallRequest) -> ToolMessage:
        seen.append(request)
        return ToolMessage(content="small", tool_call_id="1", name="GMAIL_FETCH_MESSAGES")

    await mw.awrap_tool_call(req, handler)

    assert seen == [req]


async def test_awrap_without_a_vfs_session_offloads_under_the_thread() -> None:
    mw = WorkspaceCompactionMiddleware()
    compact = AsyncMock(return_value=None)

    async def handler(_req: ToolCallRequest) -> ToolMessage | Command[str]:
        return ToolMessage(content="huge", tool_call_id="1", name="GMAIL_FETCH_MESSAGES")

    with patch.object(compaction_mod, "compact_tool_output", compact):
        await mw.awrap_tool_call(_request([]), handler)

    assert compact.await_args.kwargs["conversation_id"] == "c1"
    assert compact.await_args.kwargs["user_id"] == "u1"


async def test_awrap_command_result_passes_through_untouched() -> None:
    mw = WorkspaceCompactionMiddleware()
    cmd: Command[str] = Command(update={"messages": []})
    req = _request([], name="x")

    async def handler(_req: ToolCallRequest) -> ToolMessage | Command[str]:
        return cmd

    assert await mw.awrap_tool_call(req, handler) is cmd


async def test_awrap_plain_small_output_passes_through() -> None:
    mw = WorkspaceCompactionMiddleware()
    msg = ToolMessage(content="small", tool_call_id="1", name="x")
    req = _request([], name="x")

    async def handler(_req: ToolCallRequest) -> ToolMessage | Command[str]:
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


# --- tools behind the execute proxy are judged as themselves ----------------- #


def _execute_request(tool_name: str) -> ToolCallRequest:
    args: dict[str, object] = {"task_description": "t", "tool_name": tool_name, "data": {}}
    return _request([], name="execute", args=args)


def _composio_result(count: int) -> str:
    """Render a Composio custom-tool result the way execute hands it to the model."""
    messages = [{"id": f"m{i}", "from": f"sender{i}@x.com"} for i in range(count)]
    return json.dumps(
        {"data": {"fetched_count": count, "messages": messages}, "error": None, "successful": True}
    )


async def test_awrap_an_excluded_tool_behind_execute_is_left_alone() -> None:
    mw = WorkspaceCompactionMiddleware(max_output_chars=100, excluded_tools={"NOISY_TOOL"})
    original = ToolMessage(content="x" * 5000, tool_call_id="1", name="execute")

    async def handler(_req: ToolCallRequest) -> ToolMessage | Command[str]:
        return original

    assert await mw.awrap_tool_call(_execute_request("NOISY_TOOL"), handler) is original


async def test_awrap_a_record_limited_tool_behind_execute_is_filed_as_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: dict[str, str] = {}

    async def fake_write(*, user_id, conversation_id, relative_path, content):
        written.update(rel=relative_path, content=content)
        return Path("/host"), f"/workspace/sessions/{conversation_id}/{relative_path}"

    monkeypatch.setattr(compaction_mod, "write_session_file", fake_write)
    mw = WorkspaceCompactionMiddleware(max_output_records={"GMAIL_FETCH_MESSAGES": 50})

    async def handler(_req: ToolCallRequest) -> ToolMessage | Command[str]:
        return ToolMessage(content=_composio_result(60), tool_call_id="1", name="execute")

    res = await mw.awrap_tool_call(_execute_request("GMAIL_FETCH_MESSAGES"), handler)

    assert isinstance(res, Command)
    assert res.update["selected_tool_ids"] == ["query_json", "grep"]
    message = res.update["messages"][0]
    assert message.name == "execute", "the reply must keep the name of the call it answers"
    info = read_offload(message)
    assert info is not None
    assert (info["fmt"], info["producer"]) == ("jsonl", "GMAIL_FETCH_MESSAGES")
    assert written["rel"].startswith("tool_outputs/GMAIL_FETCH_MESSAGES_")
    lines = written["content"].splitlines()
    assert len(lines) == 60 and json.loads(lines[0]) == {"id": "m0", "from": "sender0@x.com"}
    assert '"data.fetched_count": 60' in message.content, "the fields the file drops are lost"


async def test_awrap_a_record_limited_tool_at_its_limit_stays_inline() -> None:
    mw = WorkspaceCompactionMiddleware(max_output_records={"GMAIL_FETCH_MESSAGES": 50})
    original = ToolMessage(content=_composio_result(50), tool_call_id="1", name="execute")

    async def handler(_req: ToolCallRequest) -> ToolMessage | Command[str]:
        return original

    assert await mw.awrap_tool_call(_execute_request("GMAIL_FETCH_MESSAGES"), handler) is original


async def test_awrap_a_record_limited_tool_with_no_records_stays_inline() -> None:
    mw = WorkspaceCompactionMiddleware(max_output_records={"GMAIL_FETCH_MESSAGES": 50})
    original = ToolMessage(content="plain text " * 100, tool_call_id="1", name="execute")

    async def handler(_req: ToolCallRequest) -> ToolMessage | Command[str]:
        return original

    assert await mw.awrap_tool_call(_execute_request("GMAIL_FETCH_MESSAGES"), handler) is original


class _AttributeCall:
    """A tool call handed over as an object, the form some framework versions use."""

    def __init__(self, name: str, args: dict[str, object]) -> None:
        self.name = name
        self.args = args
        self.id = "1"


async def test_awrap_an_attribute_form_execute_call_is_judged_as_its_real_tool() -> None:
    mw = WorkspaceCompactionMiddleware(max_output_chars=100, excluded_tools={"NOISY_TOOL"})
    request = _execute_request("NOISY_TOOL")
    args: dict[str, object] = {"task_description": "t", "tool_name": "NOISY_TOOL", "data": {}}
    object.__setattr__(request, "tool_call", _AttributeCall("execute", args))
    original = ToolMessage(content="x" * 5000, tool_call_id="1", name="execute")

    async def handler(_req: ToolCallRequest) -> ToolMessage | Command[str]:
        return original

    assert await mw.awrap_tool_call(request, handler) is original
