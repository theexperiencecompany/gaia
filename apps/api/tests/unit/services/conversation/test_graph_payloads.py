"""payloads_for_stream_event never releases comms text it later takes back, and releases each MCP App's card once."""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
import pytest

from app.agents.core.background.session import RunKind, create_session, teardown_session
from app.agents.tools.core.registry import ToolRegistry
from app.db.repositories.short_links import short_link_repository
from app.models.conversation_frame_models import (
    MessageBoundaryEvent,
    ReasoningEvent,
    ResponseEvent,
    StreamPayload,
    ToolDataEvent,
    ToolOutputEvent,
)
from app.models.short_link_models import RecordTarget, ShortLinkTargetType
from app.models.stream_events import MessageBoundaryPayload, ReasoningPayload, ToolOutputPayload
from app.services.conversation.graph_payloads import (
    GraphStreamState,
    flush_held_payloads,
    payloads_for_stream_event,
)
from app.services.conversation.reply_text import ReplyText
from app.services.links.placeholders import link_placeholder
from app.utils.errors import ShownReplyRetriedError
from shared.py.conversation_wire import NEW_MESSAGE_BREAKER

_NODE_RUN = {"langgraph_checkpoint_ns": "agent:1"}


@pytest.fixture(autouse=True)
def _core_tools() -> Iterator[None]:
    """Name the hand-off's card from GAIA's real core tool registry."""
    registry = ToolRegistry()
    registry.setup()
    with patch(
        "app.utils.agent_utils.get_tool_registry", new_callable=AsyncMock, return_value=registry
    ):
        yield


async def _payloads(state: GraphStreamState, *events: tuple[object, ...]) -> list[StreamPayload]:
    return [
        payload
        for event in events
        async for payload in payloads_for_stream_event(event, state, True, None, None)
    ]


def _chunk(message_id: str, text: str) -> tuple[object, ...]:
    return ((), "messages", (AIMessageChunk(id=message_id, content=text), _NODE_RUN))


def _node_end(message: AIMessage) -> tuple[object, ...]:
    return ((), "updates", {"agent": {"messages": [message]}})


async def test_a_preamble_before_a_hand_off_stays_said() -> None:
    state = GraphStreamState()
    handoff = AIMessage(
        id="m1",
        content="Let me look into that.",
        tool_calls=[{"name": "handoff", "args": {"task": "x"}, "id": "c1"}],
    )
    payloads = await _payloads(state, _chunk("m1", "Let me look into that."), _node_end(handoff))
    shown = ReplyText()
    for payload in payloads:
        if isinstance(payload, ResponseEvent | MessageBoundaryEvent):
            shown = shown.take(payload)
    assert shown.text == "Let me look into that."
    assert payloads[-1] == MessageBoundaryEvent(
        message_boundary=MessageBoundaryPayload(message_id="m1")
    )


async def test_a_model_call_retried_after_its_text_showed_fails_instead_of_taking_it_back() -> None:
    state = GraphStreamState()
    assert await _payloads(state, _chunk("m1", "Your flight ")) == [
        ResponseEvent(response="Your flight ")
    ]
    with pytest.raises(ShownReplyRetriedError) as retried:
        await _payloads(state, _chunk("m2", "Your flight leaves"))
    assert retried.value.meta == {"abandoned_message_id": "m1"}


async def test_a_model_call_retried_before_any_text_showed_streams_the_new_attempt() -> None:
    state = GraphStreamState()
    # A lone "<" may still open a bubble break, so nothing of the first attempt was released.
    assert await _payloads(state, _chunk("m1", "<")) == []
    assert await _payloads(state, _chunk("m2", "Sure, done.")) == [
        ResponseEvent(response="Sure, done.")
    ]


_MODULE = "app.services.conversation.graph_payloads"
_DECLARED_CSP = {"connectDomains": ["https://declared.example"]}
_HTML: dict[str, object] = {"html": "<p>forecast</p>"}


def _mcp_entry(*, resource_uri: str | None = "ui://weather/card") -> dict[str, object]:
    return {
        "tool_name": "tool_calls_data",
        "tool_category": "weather",
        "mcp_server_url": "https://mcp.example/sse",
        "mcp_ui": {"resource_uri": resource_uri, "csp": _DECLARED_CSP, "permissions": ["geo"]},
        "timestamp": "2026-11-15T10:00:00Z",
        "data": {"tool_call_id": "call-1", "tool_name": "get_forecast", "inputs": {"city": "Pune"}},
    }


def _card(tool_result: object, *, csp: object, permissions: object) -> ToolDataEvent:
    return ToolDataEvent(
        tool_data={
            "tool_name": "mcp_app",
            "tool_category": "weather",
            "data": {
                "tool_call_id": "call-1",
                "tool_name": "get_forecast",
                "server_url": "https://mcp.example/sse",
                "resource_uri": "ui://weather/card",
                "html_content": "<p>forecast</p>",
                "tool_result": tool_result,
                "csp": csp,
                "permissions": permissions,
                "tool_arguments": {"city": "Pune"},
            },
            "timestamp": "2026-11-15T10:00:00Z",
        }
    )


_ANNOUNCE = _node_end(
    AIMessage(
        id="m1", content="", tool_calls=[{"name": "get_forecast", "args": {}, "id": "call-1"}]
    )
)


def _result(content: str | list[str | dict[str, object]]) -> tuple[object, ...]:
    return ((), "messages", (ToolMessage(content=content, tool_call_id="call-1"), _NODE_RUN))


def _apps(payloads: list[StreamPayload]) -> list[ToolDataEvent]:
    return [
        payload
        for payload in payloads
        if isinstance(payload, ToolDataEvent) and payload.tool_data["tool_name"] == "mcp_app"
    ]


async def _stream(events: list[tuple[object, ...]], user_id: str | None) -> list[StreamPayload]:
    state = GraphStreamState()
    return [
        payload
        for event in events
        async for payload in payloads_for_stream_event(event, state, False, None, user_id)
    ]


async def _run_app(
    entry: dict[str, object], resource: dict[str, object] | None, *results: tuple[object, ...]
) -> tuple[list[StreamPayload], AsyncMock]:
    fetch = AsyncMock(return_value=resource)
    with (
        patch(f"{_MODULE}.format_tool_call_entry", AsyncMock(return_value=entry)),
        patch(f"{_MODULE}.fetch_mcp_ui_resource", fetch),
    ):
        payloads = await _stream([_ANNOUNCE, *results], "user-1")
    return payloads, fetch


async def test_an_mcp_app_result_produces_its_card_with_the_served_ui_resource() -> None:
    served: dict[str, object] = {
        "html": "<p>forecast</p>",
        "csp": {"frameDomains": []},
        "permissions": ["camera"],
    }

    payloads, fetch = await _run_app(_mcp_entry(), served, _result('{"temp": 31}'))

    fetch.assert_awaited_once_with(
        server_url="https://mcp.example/sse", resource_uri="ui://weather/card", user_id="user-1"
    )
    assert _apps(payloads) == [
        _card('{"temp": 31}', csp={"frameDomains": []}, permissions=["camera"])
    ]
    outputs = [p.tool_output for p in payloads if isinstance(p, ToolOutputEvent)]
    assert [(o.tool_call_id, o.output) for o in outputs] == [("call-1", '{"temp": 31}')]


async def test_a_resource_without_its_own_csp_or_permissions_keeps_the_declared_ones() -> None:
    payloads, _fetch = await _run_app(_mcp_entry(), _HTML, _result("ok"))

    assert _apps(payloads) == [_card("ok", csp=_DECLARED_CSP, permissions=["geo"])]


async def test_a_card_is_released_once_for_its_call_even_when_the_result_repeats() -> None:
    payloads, fetch = await _run_app(_mcp_entry(), _HTML, _result("ok"), _result("ok"))

    assert len(_apps(payloads)) == 1
    fetch.assert_awaited_once()


async def test_the_app_gets_a_media_results_text_and_a_json_safe_result_as_is() -> None:
    image: dict[str, object] = {
        "type": "image",
        "source_type": "base64",
        "data": "AAAA",
        "mime_type": "image/png",
    }
    blocks: list[str | dict[str, object]] = [{"type": "text", "text": "sunny"}]

    media, _ = await _run_app(_mcp_entry(), _HTML, _result([*blocks, image]))
    plain, _ = await _run_app(_mcp_entry(), _HTML, _result(blocks))

    assert [card.tool_data["data"]["tool_result"] for card in _apps(media)] == ["sunny"]
    assert [card.tool_data["data"]["tool_result"] for card in _apps(plain)] == [blocks]


@pytest.mark.parametrize(
    "resource", [None, {"html": ""}, {"csp": {}}], ids=["missing", "empty-html", "no-html"]
)
async def test_no_card_without_html_to_render(resource: dict[str, object] | None) -> None:
    payloads, fetch = await _run_app(_mcp_entry(), resource, _result("ok"))

    fetch.assert_awaited_once()
    assert _apps(payloads) == []


async def test_a_run_without_a_user_fetches_the_resource_as_no_one() -> None:
    fetch = AsyncMock(return_value=_HTML)
    with (
        patch(f"{_MODULE}.format_tool_call_entry", AsyncMock(return_value=_mcp_entry())),
        patch(f"{_MODULE}.fetch_mcp_ui_resource", fetch),
    ):
        payloads = await _stream([_ANNOUNCE, _result("ok")], None)

    assert fetch.await_args.kwargs["user_id"] == ""
    assert len(_apps(payloads)) == 1


async def test_a_failed_resource_fetch_drops_the_card_and_keeps_the_stream() -> None:
    with (
        patch(f"{_MODULE}.format_tool_call_entry", AsyncMock(return_value=_mcp_entry())),
        patch(f"{_MODULE}.fetch_mcp_ui_resource", AsyncMock(side_effect=RuntimeError("down"))),
        patch(f"{_MODULE}.log") as log,
    ):
        payloads = await _stream([_ANNOUNCE, _result("ok")], None)

    assert _apps(payloads) == []
    assert any(isinstance(p, ToolOutputEvent) for p in payloads)
    log.warning.assert_called_once_with(
        "Failed to emit mcp_app event", error="down", error_type="RuntimeError"
    )


@pytest.mark.parametrize(
    "entry",
    [
        {**_mcp_entry(), "tool_name": "search"},
        {**_mcp_entry(), "mcp_ui": None},
        _mcp_entry(resource_uri=None),
        {**_mcp_entry(), "data": None},
        {**_mcp_entry(), "data": {"tool_name": "get_forecast"}},
    ],
    ids=["not-tool-calls-data", "no-mcp-ui", "no-resource", "no-data", "no-call-id"],
)
async def test_an_entry_that_announces_no_mcp_app_never_fetches_a_resource(
    entry: dict[str, object],
) -> None:
    payloads, fetch = await _run_app(entry, _HTML, _result("ok"))

    fetch.assert_not_awaited()
    assert _apps(payloads) == []


async def test_a_subagents_mcp_app_is_released_by_its_forwarded_tool_output() -> None:
    fetch = AsyncMock(return_value=_HTML)
    released = {"tool_output": {"tool_call_id": "call-1", "output": "31C"}}
    events: list[tuple[object, ...]] = [
        ((), "custom", {"tool_data": {**_mcp_entry(), "mcp_server_url": None}}),
        ((), "custom", {"tool_output": {"tool_call_id": "other", "output": "x"}}),
        ((), "custom", released),
        ((), "custom", released),
    ]
    with patch(f"{_MODULE}.fetch_mcp_ui_resource", fetch):
        payloads = await _stream(events, "user-1")

    fetch.assert_awaited_once_with(
        server_url="", resource_uri="ui://weather/card", user_id="user-1"
    )
    (card,) = _apps(payloads)
    assert card.tool_data["data"]["tool_call_id"] == "call-1"
    assert card.tool_data["data"]["server_url"] == ""
    assert card.tool_data["data"]["tool_result"] == "31C"
    assert card.tool_data["data"]["tool_arguments"] == {"city": "Pune"}


async def test_a_subagents_failed_fetch_names_the_subagent_path() -> None:
    events: list[tuple[object, ...]] = [
        ((), "custom", {"tool_data": _mcp_entry()}),
        ((), "custom", {"tool_output": {"tool_call_id": "call-1", "output": "x"}}),
    ]
    with (
        patch(f"{_MODULE}.fetch_mcp_ui_resource", AsyncMock(side_effect=ValueError("bad"))),
        patch(f"{_MODULE}.log") as log,
    ):
        payloads = await _stream(events, None)

    assert _apps(payloads) == []
    log.warning.assert_called_once_with(
        "Failed to emit mcp_app from subagent", error="bad", error_type="ValueError"
    )


def _search_entry(tc: dict[str, object], user_id: str | None) -> dict[str, object]:
    return {"tool_name": "search", "data": {"tool_call_id": tc["id"]}}


def _calls(*ids: str) -> tuple[object, ...]:
    calls = [{"name": "search", "args": {}, "id": call_id} for call_id in ids]
    return _node_end(AIMessage(id=f"m-{'-'.join(ids)}", content="", tool_calls=calls))


async def test_each_tool_call_gets_one_card_however_often_it_is_announced() -> None:
    entry = AsyncMock(side_effect=_search_entry)
    with patch(f"{_MODULE}.format_tool_call_entry", entry):
        payloads = await _stream([_calls("c1"), _calls("c1", "c2"), _calls("c1", "c2")], None)

    carded = [p.tool_data["data"]["tool_call_id"] for p in payloads if isinstance(p, ToolDataEvent)]
    assert carded == ["c1", "c2"]
    assert entry.await_count == 2


async def test_a_node_update_with_no_model_tool_calls_yields_no_card() -> None:
    entry = AsyncMock(side_effect=_search_entry)
    update = _node_end(AIMessage(id="m1", content="done"))
    echo = ((), "updates", {"agent": {"messages": [ToolMessage(content="x", tool_call_id="c9")]}})
    with patch(f"{_MODULE}.format_tool_call_entry", entry):
        payloads = await _stream([update, echo], None)

    assert not any(isinstance(p, ToolDataEvent) for p in payloads)
    entry.assert_not_awaited()


@pytest.mark.parametrize(
    ("name", "kwargs", "streamed"),
    [
        ("plan_tasks", {}, False),
        ("update_tasks", {}, False),
        ("search", {"todo_tool": True}, False),
        ("search", {}, True),
    ],
    ids=["plan-tasks", "update-tasks", "todo-flag", "plain"],
)
async def test_only_a_non_todo_tool_result_streams_its_output(
    name: str, kwargs: dict[str, object], streamed: bool
) -> None:
    result = ToolMessage(content="ok", tool_call_id="c1", name=name, additional_kwargs=kwargs)

    payloads = await _stream([((), "messages", (result, _NODE_RUN))], None)

    assert any(isinstance(p, ToolOutputEvent) for p in payloads) is streamed


def _boundary_of(message_id: str) -> MessageBoundaryEvent:
    return MessageBoundaryEvent(message_boundary=MessageBoundaryPayload(message_id=message_id))


async def test_what_a_message_held_back_while_streaming_is_said_when_its_node_ends() -> None:
    state = GraphStreamState()
    # A lone "<" may still open a bubble break, so it stays held until its message is whole.
    assert await _payloads(state, _chunk("m1", "<")) == []
    ended = await _payloads(state, _node_end(AIMessage(id="m1", content="<")))
    assert ended == [ResponseEvent(response="<"), _boundary_of("m1")]
    assert state.complete_message == "<"


async def test_a_message_with_no_id_is_said_whole_when_its_node_ends() -> None:
    state = GraphStreamState()
    unnamed = ((), "messages", (AIMessageChunk(content="<"), _NODE_RUN))
    assert await _payloads(state, unnamed) == []
    ended = await _payloads(state, _node_end(AIMessage(content="<")))
    assert ended == [ResponseEvent(response="<"), _boundary_of("")]


async def test_a_node_message_that_never_streamed_only_closes_its_bubble() -> None:
    state = GraphStreamState()
    ended = await _payloads(state, _node_end(AIMessage(id="m9", content="said elsewhere")))
    assert ended == [_boundary_of("m9")]
    assert state.complete_message == ""


async def test_an_executor_nodes_text_is_never_the_reply() -> None:
    state = GraphStreamState()
    events = [_chunk("m1", "working on it"), _node_end(AIMessage(id="m1", content="working on it"))]
    payloads = [
        payload
        for event in events
        async for payload in payloads_for_stream_event(event, state, False, None, None)
    ]
    assert payloads == []
    assert state.complete_message == ""


async def test_comms_thinking_streams_as_its_own_block() -> None:
    state = GraphStreamState()
    thinking = AIMessageChunk(
        id="m1", content="", additional_kwargs={"reasoning_content": "weighing it"}
    )
    assert await _payloads(state, ((), "messages", (thinking, _NODE_RUN))) == [
        ReasoningEvent(reasoning=ReasoningPayload(content="weighing it"))
    ]


async def test_a_retried_call_names_what_the_user_saw() -> None:
    state = GraphStreamState()
    await _payloads(state, _chunk("m1", "Your flight "))
    with pytest.raises(ShownReplyRetriedError) as retried:
        await _payloads(state, _chunk("m2", "Your flight leaves"))
    assert retried.value.message == "a model call was retried after the user saw part of its reply"


async def test_a_tool_result_streams_once_per_stream_however_often_it_arrives() -> None:
    result = ToolMessage(content="ok", tool_call_id="c1", name="search")
    event = ((), "messages", (result, _NODE_RUN))
    create_session("s1", RunKind.LIVE)
    try:
        state = GraphStreamState()
        payloads = [
            payload
            for _ in range(2)
            async for payload in payloads_for_stream_event(event, state, True, "s1", None)
        ]
    finally:
        teardown_session("s1")
    assert payloads == [
        ToolOutputEvent(tool_output=ToolOutputPayload(tool_call_id="c1", output="ok"))
    ]


async def test_a_stream_mode_it_does_not_read_yields_nothing() -> None:
    state = GraphStreamState()
    assert await _payloads(state, ((), "values", {"messages": []})) == []


async def test_text_a_cancelled_run_never_closed_is_owed_and_kept() -> None:
    state = GraphStreamState()
    await _payloads(state, _chunk("m1", "Done."), _node_end(AIMessage(id="m1", content="Done.")))
    await _payloads(state, _chunk("m2", "<"))
    assert flush_held_payloads(state) == [ResponseEvent(response="<")]
    assert state.complete_message == f"Done.{NEW_MESSAGE_BREAKER}<"


async def test_a_link_placeholder_streamed_in_pieces_is_released_whole_and_unresolved() -> None:
    """Regression: the runtime merge resolved placeholders as comms streamed, so the stored reply held the URL."""
    placeholder = link_placeholder(
        RecordTarget(type=ShortLinkTargetType.OPENUI_ARTIFACT, id="art_1")
    )
    head, tail = placeholder[:14], placeholder[14:]
    live = AsyncMock(return_value=SimpleNamespace(slug="ab12cd"))
    state = GraphStreamState()
    with patch.object(short_link_repository, "get_live_for_target", live):
        payloads = [
            payload
            for event in (
                _chunk("m1", f"Here it is: [the plan]({head}"),
                _chunk("m1", f"{tail}) and more"),
            )
            async for payload in payloads_for_stream_event(event, state, True, None, "u1")
        ]
        payloads += flush_held_payloads(state)

    shown = ReplyText()
    for payload in payloads:
        if isinstance(payload, ResponseEvent):
            shown = shown.take(payload)
    assert shown.text == f"Here it is: [the plan]({placeholder}) and more"
    assert payloads[0] == ResponseEvent(response="Here it is: ")
    live.assert_not_awaited()


async def test_a_reply_ending_on_a_link_placeholder_flushes_it_unresolved() -> None:
    placeholder = link_placeholder(
        RecordTarget(type=ShortLinkTargetType.OPENUI_ARTIFACT, id="art_1")
    )
    state = GraphStreamState()
    streamed = [
        payload
        async for payload in payloads_for_stream_event(
            _chunk("m1", f"Open {placeholder}"), state, True, None, "u1"
        )
    ]

    assert streamed == [ResponseEvent(response="Open ")]
    assert flush_held_payloads(state) == [ResponseEvent(response=placeholder)]


async def test_a_preamble_ending_on_a_link_placeholder_is_said_unresolved_at_the_hand_off() -> None:
    placeholder = link_placeholder(
        RecordTarget(type=ShortLinkTargetType.OPENUI_ARTIFACT, id="art_1")
    )
    handoff = AIMessage(
        id="m1",
        content=f"Drafted {placeholder}",
        tool_calls=[{"name": "handoff", "args": {"task": "x"}, "id": "c1"}],
    )
    state = GraphStreamState()
    payloads = [
        payload
        for event in (_chunk("m1", f"Drafted {placeholder}"), _node_end(handoff))
        async for payload in payloads_for_stream_event(event, state, True, None, "u1")
    ]

    assert [p for p in payloads if isinstance(p, ResponseEvent)] == [
        ResponseEvent(response="Drafted "),
        ResponseEvent(response=placeholder),
    ]
