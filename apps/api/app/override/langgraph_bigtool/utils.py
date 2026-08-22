"""
Utility functions for LangGraph bigtool agent.

Contains helper functions for tool selection formatting and type definitions.
"""

from collections.abc import Sequence
from typing import Annotated, NotRequired, TypedDict, cast

from langchain_core.messages import (
    AnyMessage,
    BaseMessage,
    MessageLikeRepresentation,
    RemoveMessage,
    ToolMessage,
    convert_to_messages,
)
from langchain_core.tools import BaseTool
from langgraph.channels.delta import DeltaChannel
from langgraph.graph.message import (
    REMOVE_ALL_MESSAGES,
    Messages,
    _messages_delta_reducer,
)
from langgraph.managed import RemainingSteps
from langgraph_bigtool.graph import State as _BigtoolState

from app.constants.llm import MESSAGES_SNAPSHOT_FREQUENCY


def _replace_todos(_left: list, right: list) -> list:
    """Last-write-wins reducer for the todos channel."""
    return right


def _is_remove_all(message: BaseMessage) -> bool:
    return isinstance(message, RemoveMessage) and message.id == REMOVE_ALL_MESSAGES


def messages_delta_reducer(state: list[AnyMessage], writes: Sequence[Messages]) -> list[AnyMessage]:
    """The canonical reducer for the ``messages`` channel.

    LangGraph's `_messages_delta_reducer` documents that it does NOT implement
    `REMOVE_ALL_MESSAGES`, so it passes that tombstone through as if it were an
    ordinary message. `SummarizationMiddleware` clears history with exactly that
    write, and every provider serializer rejects a `RemoveMessage` in a request
    ("Unexpected message with type RemoveMessage at the position 0"). This wraps
    the stock reducer with the one case it omits: a `REMOVE_ALL_MESSAGES`
    tombstone truncates everything accumulated so far and is itself consumed.

    Applying the sentinel in stream order — rather than, say, scanning for the
    last one — is what keeps the reducer batching-invariant, which
    `DeltaChannel` requires: `reducer(reducer(s, xs), ys) == reducer(s, xs + ys)`.

    Writes are `Messages`, not `list[AnyMessage]`: `RemoveMessage` is
    deliberately absent from the `AnyMessage` union, so only the wider type
    describes a batch that carries a tombstone. The return stays `AnyMessage` —
    every tombstone has been consumed by then, so the channel's value really
    does hold nothing but real messages.
    """
    flat: list[MessageLikeRepresentation] = []
    for write in writes:
        # A non-list write is one message, tuples included: ("human", "hi") is a
        # single message-like, and extending it would split it into two.
        if isinstance(write, list):
            flat.extend(write)
        else:
            flat.append(write)
    # Coerce first so a sentinel that arrived in raw dict form (HTTP-driven
    # input, a deserialized checkpoint blob) is recognised as one.
    coerced: list[BaseMessage] = convert_to_messages(flat)

    kept: list[BaseMessage] = []
    current = state
    for message in coerced:
        if _is_remove_all(message):
            current = []
            kept = []
            continue
        kept.append(message)
    # The stock reducer is annotated `list[AnyMessage]` but genuinely handles
    # targeted `RemoveMessage` tombstones, which that union excludes.
    return _messages_delta_reducer(current, [cast("list[AnyMessage]", kept)])


class State(_BigtoolState):
    """Extended state with todos channel for agent task management."""

    # Override MessagesState's plain add_messages channel with a DeltaChannel:
    # a full-snapshot channel re-serializes the entire message list into every
    # checkpoint, so a thread with N steps costs O(N²) storage (a single
    # runaway thread reached 17 GB). DeltaChannel persists only the per-step
    # delta and writes a full snapshot every MESSAGES_SNAPSHOT_FREQUENCY
    # updates. `messages_delta_reducer` wraps LangGraph's batching-invariant
    # messages reducer (dedup by id + RemoveMessage tombstoning) built for
    # DeltaChannel's `(state, list[writes]) -> state` batch contract — plain
    # `add_messages` is a `(left, right)` reducer and is not compatible.
    messages: Annotated[
        list[AnyMessage],
        DeltaChannel(
            reducer=messages_delta_reducer, snapshot_frequency=MESSAGES_SNAPSHOT_FREQUENCY
        ),
    ]
    todos: Annotated[list, _replace_todos]
    intent: str | None
    integration_usernames: dict[str, str]
    # LangGraph-managed countdown of supersteps left before the recursion
    # limit. acall_model reads it to warn the model to wrap up before the
    # hard GraphRecursionError.
    remaining_steps: RemainingSteps


# In-memory relay from `manage_system_prompts_node` to the model node, which
# tombstones the relayed ids out of the checkpoint. Overwritten each hook pass
# and popped before the node's update — never a state channel.
PRUNED_MESSAGE_IDS_KEY = "_pruned_message_ids"


def pop_pruned_tombstones(state: State) -> list[RemoveMessage]:
    """Pop ``PRUNED_MESSAGE_IDS_KEY`` and return its ids as RemoveMessage tombstones."""
    raw = cast("dict[str, object]", state).pop(PRUNED_MESSAGE_IDS_KEY, None)
    if raw is None:
        # Absent is fine: the hook may not have run this call.
        return []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise TypeError(f"{PRUNED_MESSAGE_IDS_KEY} must be list[str], got {type(raw).__name__}")
    pruned_ids = cast("list[str]", raw)
    return [RemoveMessage(id=message_id) for message_id in pruned_ids]


class RetrieveToolsResult(TypedDict):
    """Result from retrieve_tools function."""

    tools_to_bind: list[str]
    response: list[str]
    # Rendered block shown to the model instead of the bare name list.
    response_text: NotRequired[str]


def dedupe_str_list(items: Sequence[str]) -> list[str]:
    """Deduplicate strings while preserving first-seen order."""
    return list(dict.fromkeys(items))


def _tool_binding_key(tool: BaseTool) -> tuple[str, str | int]:
    """Build a stable key for tool binding de-duplication."""
    return ("name", tool.name)


def dedupe_tool_bindings(tools: Sequence[BaseTool]) -> list[BaseTool]:
    """Deduplicate tools for model binding while preserving order."""
    seen: set[tuple[str, str | int]] = set()
    deduped: list[BaseTool] = []
    for tool in tools:
        key = _tool_binding_key(tool)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tool)
    return deduped


def format_selected_tools(
    selected_tools: dict,
    tool_registry: dict[str, BaseTool],
    response_texts: dict[str, str] | None = None,
) -> tuple[list[ToolMessage], list[str]]:
    """Format selected tools, gracefully handling tools not in registry.

    Handles tools like subagent: prefixed ones that may not be in the registry.

    Args:
        selected_tools: Dict mapping tool_call_id to list of tool IDs
        tool_registry: Dict mapping tool ID to tool instance
        response_texts: Pre-rendered block per tool_call_id, used verbatim when present

    Returns:
        Tuple of (tool_messages, tool_ids) where tool_messages show available tools
        and tool_ids are the IDs to bind
    """
    tool_messages = []
    tool_ids = []

    for tool_call_id, batch in selected_tools.items():
        if response_texts and (rendered := response_texts.get(tool_call_id)):
            tool_messages.append(ToolMessage(rendered, tool_call_id=tool_call_id))
            tool_ids.extend(batch)
            continue
        tool_names = []
        for result in batch:
            # Handle tools that exist in registry
            if result in tool_registry:
                if isinstance(tool_registry[result], BaseTool):
                    tool_names.append(tool_registry[result].name)
                else:
                    tool_names.append(getattr(tool_registry[result], "__name__", result))
            else:
                # Handle tools not in registry (e.g., subagent: prefixed)
                tool_names.append(result)

        tool_messages.append(
            ToolMessage(f"Available tools: {tool_names}", tool_call_id=tool_call_id)
        )
        tool_ids.extend(batch)

    return tool_messages, tool_ids
