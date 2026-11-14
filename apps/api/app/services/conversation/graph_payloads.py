"""The one translation of a graph run's stream events into the payloads a conversation streams.

A comms run's events pass through payloads_for_stream_event, which also holds back text that
may turn out to be a hand-off preamble; an executor's stream writer events pass through
payloads_of_custom. Both produce the same typed payloads, which tool_cards folds.
"""

from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass, field
import json
from typing import cast

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.agents.core.background.session import claim_tool_output
from app.agents.core.comms_directive import visible_comms_text, visible_comms_text_so_far
from app.agents.core.held_replies import HeldReplies, drop_retracted_text, last_ai_message
from app.agents.llm.reasoning import extract_reasoning_delta
from app.models.agent_models import StreamChunkMetadata
from app.models.conversation_frame_models import (
    MessageBoundaryEvent,
    ReasoningEvent,
    ResponseEvent,
    StreamPayload,
    StreamPayloadType,
    ToolDataEvent,
    ToolOutputEvent,
)
from app.models.mcp_app_models import McpUiMetadata, McpUiResource
from app.models.stream_events import MessageBoundaryPayload, ReasoningPayload, ToolOutputPayload
from app.models.tool_data_models import ToolDataEntry
from app.services.chat.chunks import normalize_custom_event
from app.services.mcp.mcp_resource_fetcher import fetch_mcp_ui_resource
from app.utils.agent_utils import NodeMessagesUpdate, ToolCallView, format_tool_call_entry
from app.utils.multimodal import MessageContent, extract_text_content, has_media_blocks
from shared.py.wide_events import log

_PAYLOADS: TypeAdapter[StreamPayload] = TypeAdapter(StreamPayload)
_PAYLOAD_KEYS = frozenset(StreamPayloadType)
#: The graph node that runs the model; only its updates announce tool calls.
_MODEL_NODE = "agent"
_TODO_TOOLS = frozenset({"plan_tasks", "update_tasks"})


class _SubagentToolOutput(BaseModel):
    """A subagent's forwarded tool_output frame, read to release its deferred MCP App."""

    model_config = ConfigDict(extra="ignore")

    tool_call_id: str = ""
    output: object = None


class _CustomEvent(BaseModel):
    """A custom-stream payload, read as far as releasing a subagent's MCP App needs."""

    model_config = ConfigDict(extra="ignore")

    tool_data: object = None
    tool_output: _SubagentToolOutput | None = None


class _McpUiHead(BaseModel):
    """An mcp_ui hint, read only for whether it names a resource."""

    model_config = ConfigDict(extra="ignore")

    resource_uri: str | None = None


class _McpAppCallData(BaseModel):
    """The call fields of a tool_calls_data entry's data an MCP App needs."""

    model_config = ConfigDict(extra="ignore")

    tool_call_id: str | None = None
    tool_name: str = ""
    inputs: dict[str, object] = Field(default_factory=dict)


class _McpAppEntry(BaseModel):
    """A tool_data entry, read for the MCP App it may announce; lenient, as every entry is checked."""

    model_config = ConfigDict(extra="ignore")

    tool_name: str = ""
    tool_category: str = ""
    mcp_server_url: str | None = None
    mcp_ui: dict[str, object] | None = None
    timestamp: str | None = None
    data: _McpAppCallData | None = None


class _ToolMessageKwargs(BaseModel):
    """The additional_kwargs the todo tools stamp on their ToolMessages."""

    model_config = ConfigDict(extra="ignore")

    todo_tool: bool = False


@dataclass(slots=True, frozen=True)
class _PendingMcpApp:
    """An MCP-App tool call awaiting its result, so the mcp_app card can carry both."""

    tool_category: str
    tool_name: str
    server_url: str
    mcp_ui: McpUiMetadata
    timestamp: str | None
    tool_arguments: dict[str, object]


@dataclass
class GraphStreamState:
    """The per-run state payloads_for_stream_event threads through its stream handlers."""

    complete_message: str = ""
    held: HeldReplies = field(default_factory=HeldReplies)
    emitted_tool_calls: set[str] = field(default_factory=set)
    # MCP App UI metadata is seen on "updates"; its card waits for the ToolMessage result.
    pending_mcp_apps: dict[str, _PendingMcpApp] = field(default_factory=dict)
    # The visible text of each held message already streamed.
    released_text: dict[str, str] = field(default_factory=dict)


def payloads_of_custom(data: Mapping[str, object]) -> list[StreamPayload]:
    """Return the payloads one custom stream event carries: one per card when it carries several."""
    normalized = normalize_custom_event(dict(data))
    key = next((key for key in normalized if key in _PAYLOAD_KEYS), None)
    if key is None:
        return []
    value = normalized[key]
    values = value if key == StreamPayloadType.TOOL_DATA and isinstance(value, list) else [value]
    return [_PAYLOADS.validate_python({"type": key, key: item}) for item in values]


def _boundary(message_id: str, *, discarded: bool) -> MessageBoundaryEvent:
    return MessageBoundaryEvent(
        message_boundary=MessageBoundaryPayload(message_id=message_id, discarded=discarded)
    )


def _json_safe_tool_result(content: MessageContent) -> object:
    """Return the raw tool result handed to an MCP-UI iframe, as JSON-serializable data, inline media text-extracted out."""
    if has_media_blocks(content):
        return extract_text_content(content)
    try:
        json.dumps(content)
    except TypeError:
        model_dump = getattr(content, "model_dump", None)
        if callable(model_dump):
            return model_dump()
        if hasattr(content, "__dict__"):
            return dict(content.__dict__)
        return str(content)
    return content


async def _mcp_app_card(
    app_meta: _PendingMcpApp,
    tool_call_id: str,
    tool_result: object,
    user_id: str | None,
    failure_message: str,
) -> AsyncGenerator[StreamPayload]:
    """Fetch the MCP-UI resource and yield the deferred mcp_app card for one tool call."""
    try:
        ui_details = await fetch_mcp_ui_resource(
            server_url=app_meta.server_url,
            resource_uri=app_meta.mcp_ui.resource_uri,
            user_id=user_id or "",
        )
        ui_resource = McpUiResource.model_validate(ui_details) if ui_details is not None else None
        if ui_resource is not None and ui_resource.html:
            card: ToolDataEntry = {
                "tool_name": "mcp_app",
                "tool_category": app_meta.tool_category,
                "data": {
                    "tool_call_id": tool_call_id,
                    "tool_name": app_meta.tool_name,
                    "server_url": app_meta.server_url,
                    "resource_uri": app_meta.mcp_ui.resource_uri,
                    "html_content": ui_resource.html,
                    "tool_result": tool_result,
                    "csp": ui_resource.csp if ui_resource.csp is not None else app_meta.mcp_ui.csp,
                    "permissions": ui_resource.permissions
                    if ui_resource.permissions is not None
                    else app_meta.mcp_ui.permissions,
                    "tool_arguments": app_meta.tool_arguments,
                },
                "timestamp": app_meta.timestamp,
            }
            yield ToolDataEvent(tool_data=card)
    except Exception as _e:
        log.warning(failure_message, error=str(_e), error_type=type(_e).__name__)


def _pending_mcp_app(entry: object) -> tuple[str, _PendingMcpApp] | None:
    """Return the MCP-App record a tool_calls_data entry announces, keyed by its call id; None for any other entry."""
    if not isinstance(entry, dict):
        return None
    app_entry = _McpAppEntry.model_validate(entry)
    if app_entry.tool_name != "tool_calls_data" or not app_entry.mcp_ui:
        return None
    if not _McpUiHead.model_validate(app_entry.mcp_ui).resource_uri:
        return None
    if app_entry.data is None or not app_entry.data.tool_call_id:
        return None
    return app_entry.data.tool_call_id, _PendingMcpApp(
        tool_category=app_entry.tool_category,
        tool_name=app_entry.data.tool_name,
        server_url=app_entry.mcp_server_url or "",
        mcp_ui=McpUiMetadata.model_validate(app_entry.mcp_ui),
        timestamp=app_entry.timestamp,
        tool_arguments=app_entry.data.inputs,
    )


def _buffer_mcp_app(tool_entry: object, pending_mcp_apps: dict[str, _PendingMcpApp]) -> None:
    pending = _pending_mcp_app(tool_entry)
    if pending is not None:
        tool_call_id, app = pending
        pending_mcp_apps[tool_call_id] = app


async def _tool_call_cards(
    msg: object,
    emitted_tool_calls: set[str],
    pending_mcp_apps: dict[str, _PendingMcpApp],
    user_id: str | None,
) -> AsyncGenerator[StreamPayload]:
    """Yield a card for each not-yet-shown tool call this message announces."""
    if not isinstance(msg, AIMessage) or not msg.tool_calls:
        return
    for tc in msg.tool_calls:
        call = ToolCallView.model_validate(tc)
        if not call.id or call.id in emitted_tool_calls:
            continue
        tool_entry = await format_tool_call_entry(tc, user_id=user_id)
        if tool_entry:
            yield ToolDataEvent(tool_data=tool_entry)
            emitted_tool_calls.add(call.id)
            _buffer_mcp_app(tool_entry, pending_mcp_apps)


async def _updates(
    payload: Mapping[str, object], state: GraphStreamState, is_comms: bool, user_id: str | None
) -> AsyncGenerator[StreamPayload]:
    """Handle one updates event: the model node's tool cards and message boundaries."""
    # Pre-model hooks also produce updates carrying historical tool calls; only the model node's count.
    state_update = payload.get(_MODEL_NODE)
    if not isinstance(state_update, dict):
        return
    messages = NodeMessagesUpdate.model_validate(state_update).messages
    for msg in messages:
        async for card in _tool_call_cards(
            msg, state.emitted_tool_calls, state.pending_mcp_apps, user_id
        ):
            yield card
    # The node finished, so the message's fate is decided: kept, or a discarded hand-off preamble.
    closing = last_ai_message(messages)
    closing_text = "" if closing is None else _finish_visible_text(state, closing.id or "")
    state.complete_message, boundary_id, discarded = state.held.settle(
        messages, state.complete_message, reply_tier=is_comms
    )
    if boundary_id is not None:
        if closing_text and not discarded:
            yield ResponseEvent(response=closing_text)
        yield _boundary(boundary_id, discarded=discarded)


async def _tool_message_payloads(
    chunk: ToolMessage,
    stream_id: str | None,
    pending_mcp_apps: dict[str, _PendingMcpApp],
    user_id: str | None,
) -> AsyncGenerator[StreamPayload]:
    """Yield a ToolMessage's tool output, plus any deferred mcp_app card."""
    # Todo tools already stream todo_progress.
    if (
        chunk.name in _TODO_TOOLS
        or _ToolMessageKwargs.model_validate(chunk.additional_kwargs).todo_tool
    ):
        return
    # claim_tool_output dedups: the run that announced the call wins over the executor's own driver.
    if claim_tool_output(stream_id or "", chunk.tool_call_id):
        yield ToolOutputEvent(
            tool_output=ToolOutputPayload(
                tool_call_id=chunk.tool_call_id, output=extract_text_content(chunk.content)
            )
        )
    app_meta = pending_mcp_apps.pop(chunk.tool_call_id, None)
    if app_meta:
        async for card in _mcp_app_card(
            app_meta,
            chunk.tool_call_id,
            _json_safe_tool_result(chunk.content),
            user_id,
            "Failed to emit mcp_app event",
        ):
            yield card


def _stream_visible_text(state: GraphStreamState, message_id: str) -> str:
    """Return the next piece of a streaming comms message a user may see, and mark it streamed."""
    visible = visible_comms_text_so_far(state.held.texts[message_id])
    new = visible[len(state.released_text.get(message_id, "")) :]
    if new:
        state.released_text[message_id] = visible
    return new


def _finish_visible_text(state: GraphStreamState, message_id: str) -> str:
    """Return the rest of a finished comms message a user may see, and forget it streamed."""
    sent = state.released_text.pop(message_id, "")
    return visible_comms_text(state.held.texts.get(message_id, ""))[len(sent) :]


async def _messages(
    payload: tuple[BaseMessage, StreamChunkMetadata],
    state: GraphStreamState,
    is_comms: bool,
    stream_id: str | None,
    user_id: str | None,
) -> AsyncGenerator[StreamPayload]:
    """Handle one messages event: streamed reply text and thinking, or a ToolMessage result."""
    metadata: StreamChunkMetadata
    chunk, metadata = payload
    if metadata.get("silent"):
        return
    if isinstance(chunk, AIMessage | AIMessageChunk):
        # Comms thinking streams like the executor's, as a top-level thinking block.
        if is_comms and (reasoning_delta := extract_reasoning_delta(chunk)):
            yield ReasoningEvent(reasoning=ReasoningPayload(content=reasoning_delta))
        held = state.held.hold(chunk, metadata, reply_tier=is_comms)
        if held.text:
            if held.abandoned_id is not None:
                # Retract the failed attempt's text before the retry streams the reply again.
                yield _boundary(held.abandoned_id, discarded=True)
            if visible := _stream_visible_text(state, held.message_id):
                yield ResponseEvent(response=visible)
    elif isinstance(chunk, ToolMessage):
        async for tool_payload in _tool_message_payloads(
            chunk, stream_id, state.pending_mcp_apps, user_id
        ):
            yield tool_payload


async def _custom(
    payload: object, state: GraphStreamState, user_id: str | None
) -> AsyncGenerator[StreamPayload]:
    """Handle one custom event: its payloads, then a subagent's deferred MCP App."""
    drop_retracted_text(payload, state.held.texts, state.released_text)
    if not isinstance(payload, dict):
        return
    for custom in payloads_of_custom(payload):
        yield custom
    event = _CustomEvent.model_validate(payload)
    # Custom MCP tools run inside subagents, so their cards arrive as forwarded custom events.
    _buffer_mcp_app(event.tool_data, state.pending_mcp_apps)
    if event.tool_output is not None:
        tc_id = event.tool_output.tool_call_id
        app_meta = state.pending_mcp_apps.pop(tc_id, None)
        if app_meta:
            async for card in _mcp_app_card(
                app_meta,
                tc_id,
                event.tool_output.output,
                user_id,
                "Failed to emit mcp_app from subagent",
            ):
                yield card


async def payloads_for_stream_event(
    event: tuple[object, ...],
    state: GraphStreamState,
    is_comms: bool,
    stream_id: str | None,
    user_id: str | None,
) -> AsyncGenerator[StreamPayload]:
    """Yield the payloads one LangGraph stream event (namespace, mode, payload) produces."""
    if len(event) != 3:
        return
    _namespace, stream_mode, payload = event
    # Each mode's payload shape is LangGraph's contract (Type Safety item 12).
    match stream_mode:
        case "updates":
            payloads = _updates(cast(Mapping[str, object], payload), state, is_comms, user_id)
        case "messages":
            payloads = _messages(
                cast(tuple[BaseMessage, StreamChunkMetadata], payload),
                state,
                is_comms,
                stream_id,
                user_id,
            )
        case "custom":
            payloads = _custom(payload, state, user_id)
        case _:
            return
    async for streamed in payloads:
        yield streamed


def flush_held_payloads(state: GraphStreamState) -> list[StreamPayload]:
    """Return the text a run still owes once its stream ends, folding that text into complete_message."""
    # A run that ends without its closing node update still owes the user what it streamed.
    owed: list[StreamPayload] = [
        ResponseEvent(response=visible)
        for message_id in list(state.held.texts)
        if (visible := _finish_visible_text(state, message_id))
    ]
    state.complete_message = state.held.flush(state.complete_message)
    return owed
