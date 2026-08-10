"""A compiled-graph stand-in that replays a scripted LangGraph event stream.

``execute_graph_streaming`` is the translator between LangGraph's three stream
modes and the chat SSE vocabulary. Driving it needs a graph whose ``astream``
emits an exact, chosen sequence of events — including sequences a real run only
produces under conditions a test cannot arrange (a pre-model hook replaying a
historical ``AIMessage``, a model-fallback marker in ``response_metadata``, a
silent-metadata chunk).

This double replaces only ``graph``. Everything the assertions cover —
frame shapes, the dedup set, the node gate, the tool-output join, the cancel
path — is the real production function.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage

#: One LangGraph event: (namespace, stream_mode, payload). ``subgraphs=True``
#: makes every event a 3-tuple; the root graph's namespace is ``()``.
Event = tuple[Any, ...]

ROOT: tuple[str, ...] = ()


def agent_update(*messages: BaseMessage, namespace: tuple[str, ...] = ROOT) -> Event:
    """An ``updates`` event from the LLM node — the only node whose tool calls stream."""
    return (namespace, "updates", {"agent": {"messages": list(messages)}})


def node_update(node: str, *messages: BaseMessage, namespace: tuple[str, ...] = ROOT) -> Event:
    """An ``updates`` event from any other node (pre-model hooks, tools)."""
    return (namespace, "updates", {node: {"messages": list(messages)}})


def message(
    chunk: BaseMessage,
    namespace: tuple[str, ...] = ROOT,
    **metadata: Any,
) -> Event:
    """A ``messages`` event: one model chunk or tool result, plus its metadata."""
    return (namespace, "messages", (chunk, metadata))


def text(content: str, **metadata: Any) -> Event:
    return message(AIMessageChunk(content=content), **metadata)


def tool_message(
    content: Any,
    tool_call_id: str,
    name: str | None = None,
    additional_kwargs: dict[str, Any] | None = None,
    **metadata: Any,
) -> Event:
    return message(
        ToolMessage(
            content=content,
            tool_call_id=tool_call_id,
            name=name,
            additional_kwargs=additional_kwargs or {},
        ),
        **metadata,
    )


def custom(payload: Any, namespace: tuple[str, ...] = ROOT) -> Event:
    """A ``custom`` event — how subagents, reasoning and progress reach the stream."""
    return (namespace, "custom", payload)


def flat(*events: Event) -> list[Event]:
    """Strip the namespace off each event, giving the 2-tuples LangGraph yields
    when ``subgraphs`` is not requested — the subagent driver's shape."""
    return [event[1:] for event in events]


def ai_message(content: str = "", **kwargs: Any) -> AIMessage:
    return AIMessage(content=content, **kwargs)


class _Snapshot:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values


class ScriptedGraph:
    """Replays ``events`` from ``astream``; records ``aupdate_state`` writes."""

    def __init__(
        self,
        events: Sequence[Event],
        state_values: dict[str, Any] | None = None,
    ) -> None:
        self.events = list(events)
        self.state_values = state_values if state_values is not None else {"messages": []}
        self.astream_kwargs: dict[str, Any] = {}
        self.state_updates: list[dict[str, Any]] = []
        self.closed = False
        #: How many state updates existed when aclose() was called; None if it
        #: was never called at all.
        self.updates_at_close: int | None = None
        #: How many events the consumer actually pulled. A cancelled run must
        #: stop pulling — draining the rest would let the graph keep working.
        self.yielded = 0

    def astream(self, initial_state: Any, **kwargs: Any) -> AsyncIterator[Event]:
        # **kwargs, not a fixed signature: the two drivers call astream
        # differently (subgraphs= vs durability=), and a test asserts on what
        # each one actually passed.
        self.astream_kwargs = {"initial_state": initial_state, **kwargs}

        async def _gen() -> AsyncIterator[Event]:
            for event in self.events:
                self.yielded += 1
                yield event

        gen = _gen()
        outer = self

        class _Tracked:
            """Wraps the generator so an explicit ``aclose()`` is observable.

            A ``finally:`` inside the generator is not: CPython runs it when the
            generator is collected, whether or not production ever closed it. A
            test asserting on a flag set there passes with the ``aclose()`` call
            deleted — which is exactly what happened to the cancellation test.
            """

            def __aiter__(self) -> AsyncIterator[Event]:
                return gen.__aiter__()

            async def __anext__(self) -> Event:
                return await gen.__anext__()

            async def aclose(self) -> None:
                outer.closed = True
                # Captured at close time so a test can assert the run was
                # stopped BEFORE the checkpoint was read and written.
                outer.updates_at_close = len(outer.state_updates)
                await gen.aclose()

        return _Tracked()

    async def aget_state(self, config: Any) -> _Snapshot:
        return _Snapshot(self.state_values)

    async def aupdate_state(self, config: Any, values: Any, as_node: str | None = None) -> None:
        self.state_updates.append({"values": values, "as_node": as_node})
