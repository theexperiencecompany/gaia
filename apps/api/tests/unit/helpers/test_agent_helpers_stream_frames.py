"""Exact SSE frame contracts for the streaming helpers in ``agent_helpers``.

The wire-level tests next door (``test_agent_helpers_tool_call_silence.py`` and
friends) prove the guards hold end to end through a real graph, but they can only
assert coarsely: they see a stream of frames, not the payload each helper built.
Every key name, every lookup key, every fallback default and every buffering
decision inside those helpers is invisible to them, so a frame that ships the
right text under the wrong key, or drops ``tool_arguments``, reads as a pass.

These tests feed the helpers synthetic stream events directly and assert the
emitted frames as whole strings and the mutated run state as whole dicts, so the
key names and defaults are pinned rather than sampled.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from app.agents.core.background.session import RunKind, create_session, teardown_session
from app.helpers.agent_helpers import (
    _buffer_mcp_app,
    _buffer_subagent_mcp_app,
    _emit_mcp_app_event,
    _model_fallback_frame,
    _parse_stream_event,
    _settle_message_boundary,
    _stream_custom,
    _stream_messages,
    _stream_tool_call_frames,
    _stream_tool_message_frames,
    _stream_updates,
    _StreamAccumulators,
    execute_graph_streaming,
)

HELPERS = "app.helpers.agent_helpers"


def _sse(payload: dict[str, Any]) -> str:
    """The exact bytes ``format_sse_data`` produces for this payload."""
    return f"data: {json.dumps(payload)}\n\n"


async def _drain(frames: AsyncGenerator[str, None]) -> list[str]:
    return [frame async for frame in frames]


# ── _model_fallback_frame ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_fallback_frame_names_the_backup_model() -> None:
    msg = AIMessage(
        content="",
        response_metadata={"gaia_fell_back": True, "gaia_fallback_model": "openai/gpt-5-mini"},
    )

    assert _model_fallback_frame(msg) == _sse({"model_fallback": {"model": "openai/gpt-5-mini"}})


def test_model_fallback_frame_without_a_model_name_ships_an_empty_string() -> None:
    msg = AIMessage(content="", response_metadata={"gaia_fell_back": True})

    assert _model_fallback_frame(msg) == _sse({"model_fallback": {"model": ""}})


def test_model_fallback_frame_is_none_when_the_run_did_not_fall_back() -> None:
    msg = AIMessage(content="", response_metadata={"gaia_fell_back": False})

    assert _model_fallback_frame(msg) is None


def test_model_fallback_frame_is_none_without_response_metadata() -> None:
    assert _model_fallback_frame(SimpleNamespace()) is None


# ── _settle_message_boundary / _parse_stream_event ───────────────────


def test_settle_message_boundary_reports_no_boundary_and_no_discard() -> None:
    held: dict[str, str] = {}

    assert _settle_message_boundary([HumanMessage(content="hi")], True, "so far", held, set()) == (
        "so far",
        None,
        False,
    )


def test_parse_stream_event_reads_both_tuple_shapes() -> None:
    assert _parse_stream_event((("ns",), "custom", {"a": 1})) == ("custom", {"a": 1})
    assert _parse_stream_event(("custom", {"a": 1})) == ("custom", {"a": 1})
    assert _parse_stream_event(("custom",)) is None


# ── _buffer_mcp_app ──────────────────────────────────────────────────


def _mcp_tool_entry() -> dict[str, Any]:
    return {
        "tool_name": "tool_calls_data",
        "tool_category": "custom_mcp",
        "mcp_server_url": "https://mcp.example.com/mcp",
        "mcp_ui": {"resource_uri": "ui://get-time/app.html", "csp": "default-src 'self'"},
        "timestamp": "2026-08-27T00:00:00Z",
        "data": {
            "tool_call_id": "call_1",
            "tool_name": "get_time",
            "inputs": {"tz": "UTC"},
        },
    }


def test_buffer_mcp_app_records_every_field_of_the_pending_app() -> None:
    pending: dict[str, dict[str, Any]] = {}

    _buffer_mcp_app(_mcp_tool_entry(), pending)

    assert pending == {
        "call_1": {
            "tool_category": "custom_mcp",
            "tool_name": "get_time",
            "server_url": "https://mcp.example.com/mcp",
            "mcp_ui": {"resource_uri": "ui://get-time/app.html", "csp": "default-src 'self'"},
            "timestamp": "2026-08-27T00:00:00Z",
            "tool_arguments": {"tz": "UTC"},
        }
    }


def test_buffer_mcp_app_falls_back_to_empty_values_for_absent_fields() -> None:
    pending: dict[str, dict[str, Any]] = {}

    _buffer_mcp_app(
        {
            "tool_name": "tool_calls_data",
            "mcp_ui": {"resource_uri": "ui://x"},
            "data": {"tool_call_id": "call_1"},
        },
        pending,
    )

    assert pending == {
        "call_1": {
            "tool_category": "",
            "tool_name": "",
            "server_url": "",
            "mcp_ui": {"resource_uri": "ui://x"},
            "timestamp": None,
            "tool_arguments": {},
        }
    }


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(
            {
                "tool_name": "mcp_app",
                "mcp_ui": {"resource_uri": "ui://x"},
                "data": {"tool_call_id": "call_1"},
            },
            id="not-a-tool_calls_data-entry",
        ),
        pytest.param(
            {"tool_name": "tool_calls_data", "data": {"tool_call_id": "call_1"}},
            id="no-mcp_ui",
        ),
        pytest.param(
            {
                "tool_name": "tool_calls_data",
                "mcp_ui": {"csp": "default-src 'self'"},
                "data": {"tool_call_id": "call_1"},
            },
            id="mcp_ui-without-resource_uri",
        ),
        pytest.param(
            {
                "tool_name": "tool_calls_data",
                "mcp_ui": {"resource_uri": "ui://x"},
                "data": {"tool_name": "get_time"},
            },
            id="no-tool_call_id",
        ),
    ],
)
def test_buffer_mcp_app_buffers_nothing_for(entry: dict[str, Any]) -> None:
    pending: dict[str, dict[str, Any]] = {}

    _buffer_mcp_app(entry, pending)  # type: ignore[arg-type]  # a scripted fake stands in for the compiled graph

    assert pending == {}


# ── _buffer_subagent_mcp_app ─────────────────────────────────────────


def test_buffer_subagent_mcp_app_records_every_field_of_the_pending_app() -> None:
    pending: dict[str, dict[str, Any]] = {}

    _buffer_subagent_mcp_app({"tool_data": _mcp_tool_entry()}, pending)

    assert pending == {
        "call_1": {
            "tool_category": "custom_mcp",
            "tool_name": "get_time",
            "server_url": "https://mcp.example.com/mcp",
            "mcp_ui": {"resource_uri": "ui://get-time/app.html", "csp": "default-src 'self'"},
            "timestamp": "2026-08-27T00:00:00Z",
            "tool_arguments": {"tz": "UTC"},
        }
    }


def test_buffer_subagent_mcp_app_falls_back_to_empty_values_for_absent_fields() -> None:
    pending: dict[str, dict[str, Any]] = {}

    _buffer_subagent_mcp_app(
        {
            "tool_data": {
                "tool_name": "tool_calls_data",
                "mcp_ui": {"resource_uri": "ui://x"},
                "data": {"tool_call_id": "call_1"},
            }
        },
        pending,
    )

    assert pending == {
        "call_1": {
            "tool_category": "",
            "tool_name": "",
            "server_url": "",
            "mcp_ui": {"resource_uri": "ui://x"},
            "timestamp": None,
            "tool_arguments": {},
        }
    }


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("just a progress string", id="payload-is-not-a-dict"),
        pytest.param({"progress": "working"}, id="payload-carries-no-tool_data"),
        pytest.param({"tool_data": "not a dict"}, id="tool_data-is-not-a-dict"),
        pytest.param(
            {
                "tool_data": {
                    "tool_name": "mcp_app",
                    "mcp_ui": {"resource_uri": "ui://x"},
                    "data": {"tool_call_id": "call_1"},
                }
            },
            id="not-a-tool_calls_data-entry",
        ),
        pytest.param(
            {"tool_data": {"tool_name": "tool_calls_data", "data": {"tool_call_id": "call_1"}}},
            id="no-mcp_ui",
        ),
        pytest.param(
            {
                "tool_data": {
                    "tool_name": "tool_calls_data",
                    "mcp_ui": {"csp": "default-src 'self'"},
                    "data": {"tool_call_id": "call_1"},
                }
            },
            id="mcp_ui-without-resource_uri",
        ),
        pytest.param(
            {
                "tool_data": {
                    "tool_name": "tool_calls_data",
                    "mcp_ui": {"resource_uri": "ui://x"},
                }
            },
            id="no-data-object",
        ),
        pytest.param(
            {
                "tool_data": {
                    "tool_name": "tool_calls_data",
                    "mcp_ui": {"resource_uri": "ui://x"},
                    "data": {"tool_name": "get_time"},
                }
            },
            id="no-tool_call_id",
        ),
    ],
)
def test_buffer_subagent_mcp_app_buffers_nothing_for(payload: Any) -> None:
    pending: dict[str, dict[str, Any]] = {}

    _buffer_subagent_mcp_app(payload, pending)

    assert pending == {}


# ── _stream_tool_call_frames ─────────────────────────────────────────


class _RecordingFormatter:
    """Stands in for ``format_tool_call_entry``, recording the exact call it got."""

    def __init__(self, entries: list[dict[str, Any] | None]) -> None:
        self._entries = list(entries)
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def __call__(
        self,
        tool_call: Any,
        *,
        icon_url: str | None = None,
        integration_id: str | None = None,
        integration_name: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        self.calls.append(
            (
                (tool_call,),
                {
                    "icon_url": icon_url,
                    "integration_id": integration_id,
                    "integration_name": integration_name,
                    "user_id": user_id,
                },
            )
        )
        return self._entries.pop(0)


def _tc(tc_id: str | None, name: str = "search_web", args: Any = None) -> dict[str, Any]:
    call: dict[str, Any] = {"id": tc_id, "name": name}
    if args is not None:
        call["args"] = args
    return call


@pytest.mark.asyncio
async def test_tool_call_frames_emit_one_entry_per_new_call_in_order() -> None:
    formatter = _RecordingFormatter([{"tool_name": "a"}, {"tool_name": "b"}])
    emitted: set[str] = set()
    pending: dict[str, dict[str, Any]] = {}
    msg = SimpleNamespace(tool_calls=[_tc("call_1"), _tc("call_2", name="fetch_page")])

    with patch(f"{HELPERS}.format_tool_call_entry", formatter):
        frames = await _drain(_stream_tool_call_frames(msg, emitted, pending, "user-1"))

    assert frames == [
        _sse({"tool_data": {"tool_name": "a"}}),
        _sse({"tool_data": {"tool_name": "b"}}),
    ]
    assert emitted == {"call_1", "call_2"}
    assert pending == {}
    assert formatter.calls[0] == (
        (_tc("call_1"),),
        {
            "icon_url": None,
            "integration_id": None,
            "integration_name": None,
            "user_id": "user-1",
        },
    )


@pytest.mark.asyncio
async def test_tool_call_frames_resolve_handoff_display_metadata() -> None:
    formatter = _RecordingFormatter([{"tool_name": "handoff_card"}])
    handoff_metadata = {
        "icon_url": "https://cdn/gh.png",
        "integration_id": "github",
        "integration_name": "GitHub",
    }
    msg = SimpleNamespace(tool_calls=[_tc("call_1", name="handoff", args={"subagent_id": "gh-1"})])

    with (
        patch(f"{HELPERS}.format_tool_call_entry", formatter),
        patch(
            f"{HELPERS}.get_handoff_metadata", AsyncMock(return_value=handoff_metadata)
        ) as lookup,
    ):
        frames = await _drain(_stream_tool_call_frames(msg, set(), {}, "user-1"))

    assert frames == [_sse({"tool_data": {"tool_name": "handoff_card"}})]
    lookup.assert_awaited_once_with("gh-1")
    assert formatter.calls == [
        (
            (_tc("call_1", name="handoff", args={"subagent_id": "gh-1"}),),
            {
                "icon_url": "https://cdn/gh.png",
                "integration_id": "github",
                "integration_name": "GitHub",
                "user_id": "user-1",
            },
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_call",
    [
        pytest.param(
            _tc("call_1", name="search_web", args={"subagent_id": "gh-1"}), id="not-a-handoff"
        ),
        pytest.param(_tc("call_1", name="handoff"), id="handoff-without-args"),
        pytest.param(_tc("call_1", name="handoff", args={}), id="handoff-with-empty-args"),
    ],
)
async def test_tool_call_frames_look_up_no_handoff_metadata_for(tool_call: dict[str, Any]) -> None:
    formatter = _RecordingFormatter([{"tool_name": "card"}])

    with (
        patch(f"{HELPERS}.format_tool_call_entry", formatter),
        patch(f"{HELPERS}.get_handoff_metadata", AsyncMock()) as lookup,
    ):
        frames = await _drain(
            _stream_tool_call_frames(SimpleNamespace(tool_calls=[tool_call]), set(), {}, "user-1")
        )

    assert frames == [_sse({"tool_data": {"tool_name": "card"}})]
    lookup.assert_not_awaited()
    assert formatter.calls[0][1] == {
        "icon_url": None,
        "integration_id": None,
        "integration_name": None,
        "user_id": "user-1",
    }


@pytest.mark.asyncio
async def test_tool_call_frames_skip_already_emitted_calls_without_stopping() -> None:
    formatter = _RecordingFormatter([{"tool_name": "b"}])
    emitted = {"call_1"}
    msg = SimpleNamespace(tool_calls=[_tc("call_1"), _tc("call_2")])

    with patch(f"{HELPERS}.format_tool_call_entry", formatter):
        frames = await _drain(_stream_tool_call_frames(msg, emitted, {}, None))

    assert frames == [_sse({"tool_data": {"tool_name": "b"}})]
    assert emitted == {"call_1", "call_2"}


@pytest.mark.asyncio
async def test_tool_call_frames_skip_a_call_with_no_id() -> None:
    formatter = _RecordingFormatter([{"tool_name": "a"}])
    emitted: set[str] = set()

    with patch(f"{HELPERS}.format_tool_call_entry", formatter):
        frames = await _drain(
            _stream_tool_call_frames(SimpleNamespace(tool_calls=[_tc(None)]), emitted, {}, None)
        )

    assert frames == []
    assert emitted == set()
    assert formatter.calls == []


@pytest.mark.asyncio
async def test_tool_call_frames_emit_nothing_for_a_message_with_no_tool_calls_attribute() -> None:
    formatter = _RecordingFormatter([])

    with patch(f"{HELPERS}.format_tool_call_entry", formatter):
        frames = await _drain(_stream_tool_call_frames(SimpleNamespace(), set(), {}, None))

    assert frames == []


@pytest.mark.asyncio
async def test_tool_call_frames_emit_nothing_when_the_entry_cannot_be_formatted() -> None:
    formatter = _RecordingFormatter([None])
    emitted: set[str] = set()

    with patch(f"{HELPERS}.format_tool_call_entry", formatter):
        frames = await _drain(
            _stream_tool_call_frames(SimpleNamespace(tool_calls=[_tc("call_1")]), emitted, {}, None)
        )

    assert frames == []
    assert emitted == set()


@pytest.mark.asyncio
async def test_tool_call_frames_buffer_the_mcp_app_for_deferred_emission() -> None:
    formatter = _RecordingFormatter([_mcp_tool_entry()])
    pending: dict[str, dict[str, Any]] = {}

    with patch(f"{HELPERS}.format_tool_call_entry", formatter):
        frames = await _drain(
            _stream_tool_call_frames(
                SimpleNamespace(tool_calls=[_tc("call_1")]), set(), pending, "u"
            )
        )

    assert frames == [_sse({"tool_data": _mcp_tool_entry()})]
    assert pending == {
        "call_1": {
            "tool_category": "custom_mcp",
            "tool_name": "get_time",
            "server_url": "https://mcp.example.com/mcp",
            "mcp_ui": {"resource_uri": "ui://get-time/app.html", "csp": "default-src 'self'"},
            "timestamp": "2026-08-27T00:00:00Z",
            "tool_arguments": {"tz": "UTC"},
        }
    }


# ── _stream_tool_message_frames ──────────────────────────────────────


def _pending_app() -> dict[str, Any]:
    return {
        "tool_category": "custom_mcp",
        "tool_name": "get_time",
        "server_url": "https://mcp.example.com/mcp",
        "mcp_ui": {"resource_uri": "ui://get-time/app.html"},
        "timestamp": "2026-08-27T00:00:00Z",
        "tool_arguments": {"tz": "UTC"},
    }


def _mcp_app_frame(tool_result: Any) -> str:
    return _sse(
        {
            "tool_data": {
                "tool_name": "mcp_app",
                "tool_category": "custom_mcp",
                "data": {
                    "tool_call_id": "call_1",
                    "tool_name": "get_time",
                    "server_url": "https://mcp.example.com/mcp",
                    "resource_uri": "ui://get-time/app.html",
                    "html_content": "<h1>12:00</h1>",
                    "tool_result": tool_result,
                    "csp": "default-src 'self'",
                    "permissions": ["clipboard-read"],
                    "tool_arguments": {"tz": "UTC"},
                },
                "timestamp": "2026-08-27T00:00:00Z",
            }
        }
    )


@pytest.mark.asyncio
async def test_tool_message_emits_the_tool_output_frame() -> None:
    chunk = ToolMessage(content="12:00 UTC", tool_call_id="call_1", name="get_time")

    frames = await _drain(_stream_tool_message_frames(chunk, "stream-1", {}, "user-1"))

    assert frames == [_sse({"tool_output": {"tool_call_id": "call_1", "output": "12:00 UTC"}})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chunk",
    [
        pytest.param(
            ToolMessage(content="x", tool_call_id="call_1", name="plan_tasks"), id="plan_tasks"
        ),
        pytest.param(
            ToolMessage(content="x", tool_call_id="call_1", name="update_tasks"), id="update_tasks"
        ),
        pytest.param(
            ToolMessage(
                content="x",
                tool_call_id="call_1",
                name="custom_todo",
                additional_kwargs={"todo_tool": True},
            ),
            id="todo_tool-flagged",
        ),
    ],
)
async def test_todo_tool_messages_emit_no_tool_output(chunk: ToolMessage) -> None:
    assert await _drain(_stream_tool_message_frames(chunk, "stream-1", {}, "user-1")) == []


@pytest.mark.asyncio
async def test_only_the_first_copy_of_a_tool_result_is_streamed_per_session() -> None:
    create_session("stream-1", RunKind.LIVE)
    chunk = ToolMessage(content="12:00 UTC", tool_call_id="call_1", name="get_time")
    try:
        first = await _drain(_stream_tool_message_frames(chunk, "stream-1", {}, None))
        second = await _drain(_stream_tool_message_frames(chunk, "stream-1", {}, None))
    finally:
        teardown_session("stream-1")

    assert first == [_sse({"tool_output": {"tool_call_id": "call_1", "output": "12:00 UTC"}})]
    assert second == []


@pytest.mark.asyncio
async def test_a_run_without_a_stream_id_claims_under_the_empty_key() -> None:
    create_session("", RunKind.LIVE)
    chunk = ToolMessage(content="12:00 UTC", tool_call_id="call_1", name="get_time")
    try:
        first = await _drain(_stream_tool_message_frames(chunk, None, {}, None))
        second = await _drain(_stream_tool_message_frames(chunk, None, {}, None))
    finally:
        teardown_session("")

    assert first == [_sse({"tool_output": {"tool_call_id": "call_1", "output": "12:00 UTC"}})]
    assert second == []


@pytest.mark.asyncio
async def test_tool_message_emits_the_deferred_mcp_app_frame_with_the_result() -> None:
    pending = {"call_1": _pending_app()}
    chunk = ToolMessage(content="12:00 UTC", tool_call_id="call_1", name="get_time")
    resource = {
        "html": "<h1>12:00</h1>",
        "csp": "default-src 'self'",
        "permissions": ["clipboard-read"],
    }

    with patch(f"{HELPERS}.fetch_mcp_ui_resource", AsyncMock(return_value=resource)) as fetch:
        frames = await _drain(_stream_tool_message_frames(chunk, "stream-1", pending, "user-1"))

    assert frames == [
        _sse({"tool_output": {"tool_call_id": "call_1", "output": "12:00 UTC"}}),
        _mcp_app_frame("12:00 UTC"),
    ]
    assert pending == {}
    fetch.assert_awaited_once_with(
        server_url="https://mcp.example.com/mcp",
        resource_uri="ui://get-time/app.html",
        user_id="user-1",
    )


@pytest.mark.asyncio
async def test_a_failed_mcp_app_fetch_warns_and_still_ships_the_tool_output() -> None:
    pending = {"call_1": _pending_app()}
    chunk = ToolMessage(content="12:00 UTC", tool_call_id="call_1", name="get_time")

    with (
        patch(f"{HELPERS}.fetch_mcp_ui_resource", AsyncMock(side_effect=RuntimeError("boom"))),
        patch(f"{HELPERS}.log", MagicMock()) as logger,
    ):
        frames = await _drain(_stream_tool_message_frames(chunk, "stream-1", pending, "user-1"))

    assert frames == [_sse({"tool_output": {"tool_call_id": "call_1", "output": "12:00 UTC"}})]
    assert logger.warning.call_args.args == ("Failed to emit mcp_app event",)


# ── _stream_custom ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_custom_events_are_forwarded_verbatim() -> None:
    state = _StreamAccumulators()

    frames = await _drain(_stream_custom({"progress": "working"}, state, "user-1"))

    assert frames == [_sse({"progress": "working"})]
    assert state.pending_mcp_apps == {}


@pytest.mark.asyncio
async def test_a_subagent_tool_data_event_buffers_its_mcp_app() -> None:
    state = _StreamAccumulators()
    payload = {"tool_data": _mcp_tool_entry()}

    frames = await _drain(_stream_custom(payload, state, "user-1"))

    assert frames == [_sse(payload)]
    assert state.pending_mcp_apps == {
        "call_1": {
            "tool_category": "custom_mcp",
            "tool_name": "get_time",
            "server_url": "https://mcp.example.com/mcp",
            "mcp_ui": {"resource_uri": "ui://get-time/app.html", "csp": "default-src 'self'"},
            "timestamp": "2026-08-27T00:00:00Z",
            "tool_arguments": {"tz": "UTC"},
        }
    }


@pytest.mark.asyncio
async def test_a_subagent_tool_output_emits_the_deferred_mcp_app_frame() -> None:
    state = _StreamAccumulators(pending_mcp_apps={"call_1": _pending_app()})
    payload = {"tool_output": {"tool_call_id": "call_1", "output": "12:00 UTC"}}
    resource = {
        "html": "<h1>12:00</h1>",
        "csp": "default-src 'self'",
        "permissions": ["clipboard-read"],
    }

    with patch(f"{HELPERS}.fetch_mcp_ui_resource", AsyncMock(return_value=resource)) as fetch:
        frames = await _drain(_stream_custom(payload, state, "user-1"))

    assert frames == [_sse(payload), _mcp_app_frame("12:00 UTC")]
    assert state.pending_mcp_apps == {}
    fetch.assert_awaited_once_with(
        server_url="https://mcp.example.com/mcp",
        resource_uri="ui://get-time/app.html",
        user_id="user-1",
    )


@pytest.mark.asyncio
async def test_a_subagent_tool_output_with_no_tool_call_id_claims_the_empty_key() -> None:
    state = _StreamAccumulators(pending_mcp_apps={"": _pending_app()})
    payload = {"tool_output": {"output": "12:00 UTC"}}
    resource = {
        "html": "<h1>12:00</h1>",
        "csp": "default-src 'self'",
        "permissions": ["clipboard-read"],
    }

    with patch(f"{HELPERS}.fetch_mcp_ui_resource", AsyncMock(return_value=resource)):
        frames = await _drain(_stream_custom(payload, state, "user-1"))

    assert len(frames) == 2
    assert frames[0] == _sse(payload)
    assert state.pending_mcp_apps == {}


@pytest.mark.asyncio
async def test_a_subagent_tool_output_for_an_unbuffered_call_only_forwards() -> None:
    state = _StreamAccumulators(pending_mcp_apps={"call_9": _pending_app()})
    payload = {"tool_output": {"tool_call_id": "call_1", "output": "12:00 UTC"}}

    frames = await _drain(_stream_custom(payload, state, "user-1"))

    assert frames == [_sse(payload)]
    assert state.pending_mcp_apps == {"call_9": _pending_app()}


@pytest.mark.asyncio
async def test_a_failed_subagent_mcp_app_fetch_warns_with_its_own_message() -> None:
    state = _StreamAccumulators(pending_mcp_apps={"call_1": _pending_app()})
    payload = {"tool_output": {"tool_call_id": "call_1", "output": "12:00 UTC"}}

    with (
        patch(f"{HELPERS}.fetch_mcp_ui_resource", AsyncMock(side_effect=RuntimeError("boom"))),
        patch(f"{HELPERS}.log", MagicMock()) as logger,
    ):
        frames = await _drain(_stream_custom(payload, state, "user-1"))

    assert frames == [_sse(payload)]
    assert logger.warning.call_args.args == ("Failed to emit mcp_app from subagent",)


# ── _stream_updates ──────────────────────────────────────────────────


def _boundary_frame(message_id: str, discarded: bool) -> str:
    return _sse({"message_boundary": {"message_id": message_id, "discarded": discarded}})


@pytest.mark.asyncio
async def test_updates_emit_tool_data_and_a_boundary_only_for_the_agent_node() -> None:
    formatter = _RecordingFormatter([{"tool_name": "card"}])
    state = _StreamAccumulators()
    reply = AIMessage(content="on it", id="msg-1")
    payload = {
        "tools": {"messages": [AIMessage(content="stale", id="msg-0")]},
        "agent": {"messages": [reply]},
    }

    with patch(f"{HELPERS}.format_tool_call_entry", formatter):
        frames = await _drain(_stream_updates(payload, state, True, "user-1"))

    assert frames == [_boundary_frame("msg-1", False)]
    assert formatter.calls == []


@pytest.mark.asyncio
async def test_updates_from_the_agent_node_without_messages_emit_nothing() -> None:
    state = _StreamAccumulators()

    assert await _drain(_stream_updates({"agent": {"llm_usage": {}}}, state, True, "u")) == []


@pytest.mark.asyncio
async def test_updates_emit_the_model_fallback_frame_once_per_stream() -> None:
    state = _StreamAccumulators()
    fell_back = {"gaia_fell_back": True, "gaia_fallback_model": "openai/gpt-5-mini"}
    payload = {
        "agent": {
            "messages": [
                AIMessage(content="a", id="msg-1", response_metadata=fell_back),
                AIMessage(content="b", id="msg-2", response_metadata=fell_back),
            ]
        }
    }

    frames = await _drain(_stream_updates(payload, state, True, "user-1"))

    assert frames == [
        _sse({"model_fallback": {"model": "openai/gpt-5-mini"}}),
        _boundary_frame("msg-2", False),
    ]
    assert state.fallback_emitted is True


@pytest.mark.asyncio
async def test_updates_buffer_the_mcp_app_and_pass_the_user_id_through() -> None:
    formatter = _RecordingFormatter([_mcp_tool_entry()])
    state = _StreamAccumulators()
    reply = AIMessage(
        content="",
        id="msg-1",
        tool_calls=[{"id": "call_1", "name": "get_time", "args": {"tz": "UTC"}}],
    )

    with patch(f"{HELPERS}.format_tool_call_entry", formatter):
        frames = await _drain(_stream_updates({"agent": {"messages": [reply]}}, state, True, "u-1"))

    assert frames == [
        _sse({"tool_data": _mcp_tool_entry()}),
        _boundary_frame("msg-1", True),
    ]
    assert state.pending_mcp_apps["call_1"]["tool_name"] == "get_time"
    assert formatter.calls[0][1]["user_id"] == "u-1"


# ── _stream_messages ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_silent_messages_emit_nothing() -> None:
    state = _StreamAccumulators()
    chunk = AIMessage(content="internal", id="msg-1")

    frames = await _drain(_stream_messages((chunk, {"silent": True}), state, True, "s1", "u1"))

    assert frames == []
    assert state.message_texts == {}


@pytest.mark.asyncio
async def test_comms_reply_text_is_streamed_and_held_for_its_boundary() -> None:
    state = _StreamAccumulators()
    chunk = AIMessage(content="hello", id="msg-1")

    frames = await _drain(_stream_messages((chunk, {}), state, True, "s1", "u1"))

    assert frames == [_sse({"response": "hello"})]
    assert state.message_texts == {"msg-1": "hello"}


@pytest.mark.asyncio
async def test_messages_thread_the_stream_id_into_the_tool_output_claim() -> None:
    create_session("stream-1", RunKind.LIVE)
    state = _StreamAccumulators()
    chunk = ToolMessage(content="12:00 UTC", tool_call_id="call_1", name="get_time")
    try:
        first = await _drain(_stream_messages((chunk, {}), state, True, "stream-1", "u1"))
        second = await _drain(_stream_messages((chunk, {}), state, True, "stream-1", "u1"))
    finally:
        teardown_session("stream-1")

    assert first == [_sse({"tool_output": {"tool_call_id": "call_1", "output": "12:00 UTC"}})]
    assert second == []


@pytest.mark.asyncio
async def test_messages_thread_the_user_id_into_the_mcp_resource_fetch() -> None:
    state = _StreamAccumulators(pending_mcp_apps={"call_1": _pending_app()})
    chunk = ToolMessage(content="12:00 UTC", tool_call_id="call_1", name="get_time")

    with patch(
        f"{HELPERS}.fetch_mcp_ui_resource", AsyncMock(return_value={"html": "<h1>12:00</h1>"})
    ) as fetch:
        await _drain(_stream_messages((chunk, {}), state, True, "stream-1", "user-1"))

    assert fetch.await_args.kwargs["user_id"] == "user-1"


# ── execute_graph_streaming ──────────────────────────────────────────


class _FakeGraph:
    """A graph whose ``astream`` replays a fixed list of stream events."""

    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self._events = events

    def astream(self, *_args: Any, **_kwargs: Any) -> AsyncGenerator[tuple[Any, ...], None]:
        async def _gen() -> AsyncGenerator[tuple[Any, ...], None]:
            for event in self._events:
                yield event

        return _gen()


def _config(stream_id: str | None, user_id: str) -> dict[str, Any]:
    return {
        "agent_name": "comms_agent",
        "configurable": {"stream_id": stream_id, "user_id": user_id},
    }


@pytest.mark.asyncio
async def test_streaming_run_threads_the_user_id_into_every_stream_mode() -> None:
    formatter = _RecordingFormatter([{"tool_name": "card"}])
    reply = AIMessage(
        content="",
        id="msg-1",
        tool_calls=[{"id": "call_1", "name": "get_time", "args": {}}],
    )
    graph = _FakeGraph(
        [
            (("ns",), "updates", {"agent": {"messages": [reply]}}),
            (("ns",), "custom", {"progress": "working"}),
        ]
    )
    config = _config(None, "user-1")

    with (
        patch(f"{HELPERS}.format_tool_call_entry", formatter),
        patch(f"{HELPERS}.stream_manager.is_cancelled", AsyncMock(return_value=False)),
    ):
        frames = [frame async for frame in execute_graph_streaming(graph, {}, config)]  # type: ignore[arg-type]  # a scripted fake stands in for the compiled graph

    assert frames == [
        _sse({"tool_data": {"tool_name": "card"}}),
        _boundary_frame("msg-1", True),
        _sse({"progress": "working"}),
        f"nostream: {json.dumps({'complete_message': ''})}",
        "data: [DONE]\n\n",
    ]
    assert formatter.calls[0][1]["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_a_streaming_run_threads_the_user_id_into_every_mcp_resource_fetch() -> None:
    """Both deferred-app paths — the ToolMessage one and the subagent one — need the user."""
    second_entry = _mcp_tool_entry()
    second_entry["data"] = dict(second_entry["data"], tool_call_id="call_2")
    graph = _FakeGraph(
        [
            (("ns",), "custom", {"tool_data": _mcp_tool_entry()}),
            (
                ("ns",),
                "messages",
                (ToolMessage(content="12:00 UTC", tool_call_id="call_1", name="get_time"), {}),
            ),
            (("ns",), "custom", {"tool_data": second_entry}),
            (("ns",), "custom", {"tool_output": {"tool_call_id": "call_2", "output": "13:00 UTC"}}),
        ]
    )

    with (
        patch(f"{HELPERS}.stream_manager.is_cancelled", AsyncMock(return_value=False)),
        patch(
            f"{HELPERS}.fetch_mcp_ui_resource", AsyncMock(return_value={"html": "<h1>x</h1>"})
        ) as fetch,
    ):
        frames = [
            frame
            async for frame in execute_graph_streaming(graph, {}, _config("stream-1", "u-1"))  # type: ignore[arg-type]  # a scripted fake stands in for the compiled graph
        ]

    assert [call.kwargs["user_id"] for call in fetch.await_args_list] == ["u-1", "u-1"]
    assert sum('"tool_name": "mcp_app"' in frame for frame in frames) == 2


@pytest.mark.asyncio
async def test_a_streaming_run_claims_tool_outputs_under_its_own_stream_id() -> None:
    chunk = ToolMessage(content="12:00 UTC", tool_call_id="call_1", name="get_time")
    graph = _FakeGraph([(("ns",), "messages", (chunk, {})), (("ns",), "messages", (chunk, {}))])
    create_session("stream-1", RunKind.LIVE)
    try:
        with patch(f"{HELPERS}.stream_manager.is_cancelled", AsyncMock(return_value=False)):
            frames = [
                frame
                async for frame in execute_graph_streaming(graph, {}, _config("stream-1", "u-1"))  # type: ignore[arg-type]  # a scripted fake stands in for the compiled graph
            ]
    finally:
        teardown_session("stream-1")

    assert frames == [
        _sse({"tool_output": {"tool_call_id": "call_1", "output": "12:00 UTC"}}),
        f"nostream: {json.dumps({'complete_message': ''})}",
        "data: [DONE]\n\n",
    ]


@pytest.mark.asyncio
async def test_a_cancelled_run_emits_the_cancelled_nostream_frame() -> None:
    chunk = AIMessage(content="partial answer", id="msg-1")
    graph = _FakeGraph(
        [
            (("ns",), "messages", (chunk, {})),
            (("ns",), "custom", {"progress": "never reached"}),
        ]
    )
    config = _config("stream-1", "user-1")
    cancelled = AsyncMock(side_effect=[False, True])

    with (
        patch(f"{HELPERS}.stream_manager.is_cancelled", cancelled),
        patch(f"{HELPERS}.record_interruption", AsyncMock()) as record,
    ):
        frames = [frame async for frame in execute_graph_streaming(graph, {}, config)]  # type: ignore[arg-type]  # a scripted fake stands in for the compiled graph

    assert frames == [
        _sse({"response": "partial answer"}),
        "nostream: " + json.dumps({"complete_message": "partial answer", "cancelled": True}),
        "data: [DONE]\n\n",
    ]
    record.assert_awaited_once_with(graph, config)


# ── _emit_mcp_app_event ──────────────────────────────────────────────
#
# The deferred MCP-App frame is assembled from two sources that can disagree:
# what the MCP server served back with the UI resource, and what the tool call
# declared in its ``mcp_ui`` metadata. Served values win, declared values are the
# fallback, and ``permissions`` bottoms out at ``[]`` rather than null — an
# iframe sandbox attribute built from null is not the same page as one built
# from an empty list. Each of those three layers gets its own test.


def _emit_meta(**overrides: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "tool_category": "custom_mcp",
        "tool_name": "get_time",
        "server_url": "https://mcp.example.com/mcp",
        "mcp_ui": {"resource_uri": "ui://get-time/app.html"},
        "timestamp": "2026-08-27T00:00:00Z",
        "tool_arguments": {"tz": "UTC"},
    }
    meta.update(overrides)
    return meta


def _emit_frame(csp: Any, permissions: Any, tool_arguments: Any) -> str:
    return _sse(
        {
            "tool_data": {
                "tool_name": "mcp_app",
                "tool_category": "custom_mcp",
                "data": {
                    "tool_call_id": "call_1",
                    "tool_name": "get_time",
                    "server_url": "https://mcp.example.com/mcp",
                    "resource_uri": "ui://get-time/app.html",
                    "html_content": "<h1>12:00</h1>",
                    "tool_result": "12:00 UTC",
                    "csp": csp,
                    "permissions": permissions,
                    "tool_arguments": tool_arguments,
                },
                "timestamp": "2026-08-27T00:00:00Z",
            }
        }
    )


@pytest.mark.asyncio
async def test_the_served_csp_and_permissions_win_over_the_declared_ones() -> None:
    meta = _emit_meta(
        mcp_ui={
            "resource_uri": "ui://get-time/app.html",
            "csp": "declared-src 'none'",
            "permissions": ["declared-only"],
        }
    )
    resource = {
        "html": "<h1>12:00</h1>",
        "csp": "served-src 'self'",
        "permissions": ["clipboard-read"],
    }

    with patch(f"{HELPERS}.fetch_mcp_ui_resource", AsyncMock(return_value=resource)):
        frames = await _drain(_emit_mcp_app_event(meta, "call_1", "12:00 UTC", "user-1", "nope"))

    assert frames == [_emit_frame("served-src 'self'", ["clipboard-read"], {"tz": "UTC"})]


@pytest.mark.asyncio
async def test_the_declared_csp_and_permissions_are_used_when_none_are_served() -> None:
    meta = _emit_meta(
        mcp_ui={
            "resource_uri": "ui://get-time/app.html",
            "csp": "declared-src 'none'",
            "permissions": ["declared-only"],
        }
    )

    with patch(
        f"{HELPERS}.fetch_mcp_ui_resource", AsyncMock(return_value={"html": "<h1>12:00</h1>"})
    ):
        frames = await _drain(_emit_mcp_app_event(meta, "call_1", "12:00 UTC", "user-1", "nope"))

    assert frames == [_emit_frame("declared-src 'none'", ["declared-only"], {"tz": "UTC"})]


@pytest.mark.asyncio
async def test_undeclared_permissions_bottom_out_at_an_empty_list() -> None:
    meta = _emit_meta()
    del meta["tool_arguments"]

    with patch(
        f"{HELPERS}.fetch_mcp_ui_resource", AsyncMock(return_value={"html": "<h1>12:00</h1>"})
    ):
        frames = await _drain(_emit_mcp_app_event(meta, "call_1", "12:00 UTC", "user-1", "nope"))

    assert frames == [_emit_frame(None, [], {})]


@pytest.mark.asyncio
async def test_a_run_without_a_user_id_fetches_the_resource_with_an_empty_one() -> None:
    with patch(
        f"{HELPERS}.fetch_mcp_ui_resource", AsyncMock(return_value={"html": "<h1>12:00</h1>"})
    ) as fetch:
        await _drain(_emit_mcp_app_event(_emit_meta(), "call_1", "12:00 UTC", None, "nope"))

    fetch.assert_awaited_once_with(
        server_url="https://mcp.example.com/mcp",
        resource_uri="ui://get-time/app.html",
        user_id="",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource",
    [
        pytest.param({"html": ""}, id="empty-html"),
        pytest.param({"csp": "served-src 'self'"}, id="no-html-key"),
        pytest.param(None, id="resource-is-not-a-dict"),
    ],
)
async def test_no_mcp_app_frame_without_html(resource: Any) -> None:
    with patch(f"{HELPERS}.fetch_mcp_ui_resource", AsyncMock(return_value=resource)):
        frames = await _drain(
            _emit_mcp_app_event(_emit_meta(), "call_1", "12:00 UTC", "user-1", "nope")
        )

    assert frames == []


@pytest.mark.asyncio
async def test_a_failed_resource_fetch_logs_the_error_and_emits_no_frame() -> None:
    with (
        patch(f"{HELPERS}.fetch_mcp_ui_resource", AsyncMock(side_effect=RuntimeError("boom"))),
        patch(f"{HELPERS}.log", MagicMock()) as logger,
    ):
        frames = await _drain(
            _emit_mcp_app_event(_emit_meta(), "call_1", "12:00 UTC", "user-1", "Fetch gave up")
        )

    assert frames == []
    assert logger.warning.call_args.args == ("Fetch gave up",)
    assert logger.warning.call_args.kwargs == {"error": "boom", "error_type": "RuntimeError"}
