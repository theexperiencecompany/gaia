"""The text a graph run answers with, told apart from the narration around its tool calls.

A model says "Let me check the mail." and calls a tool in the same message, and the wire
only reveals the tool call after that text has streamed. So every driver that reads a
graph's "messages" stream holds each message's text by id, and only a message that calls
no tool is part of the answer. A driver that concatenates raw chunks instead sends every
intermediate step to the user: a scheduled Inbox desk run did exactly that to Telegram.

HeldReplies is the one implementation. tests/meta/test_reply_text_assembly.py fails any
module that consumes the "messages" stream without it.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from langchain_core.messages import AIMessage, AIMessageChunk, ToolCall, ToolCallChunk

from app.constants.comms import TURN_ENDING_TOOL_NAMES
from app.models.agent_models import StreamChunkMetadata
from app.utils.message_breaks import append_message_bubble


class HeldChunk(NamedTuple):
    """What holding one model chunk did: its message, the text now held, any attempt it replaced."""

    message_id: str
    text: str
    abandoned_id: str | None = None


def announces_tool_call(chunk: AIMessage) -> bool:
    """Return whether this chunk already carries a work tool call, meaning any text is narration.

    tool_calls (complete) or tool_call_chunks (still assembling, on a chunk only) both count;
    a turn-ending call (answered, react, stay_silent) does not, since the words beside it are
    the reply.
    """
    calls: list[ToolCall] = chunk.tool_calls
    parts: list[ToolCallChunk] = chunk.tool_call_chunks if isinstance(chunk, AIMessageChunk) else []
    # A streamed call names itself in its first chunk only; the rest carry arguments.
    names = [call["name"] for call in calls] + [name for part in parts if (name := part["name"])]
    return any(name not in TURN_ENDING_TOOL_NAMES for name in names)


def last_ai_message(messages: Sequence[object]) -> AIMessage | None:
    """Return the model's own reply in a node update.

    A node update also carries RemoveMessage tombstones for pruned history,
    so "the message this node produced" is the last AI one, not the last one.
    """
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


@dataclass
class HeldReplies:
    """A run's streamed text, held per message until it is known to be a reply."""

    #: Text so far, by message id; delegated-tier chunks interleave on one stream.
    texts: dict[str, str] = field(default_factory=dict)
    tool_call_ids: set[str] = field(default_factory=set)
    #: The message id each node run is streaming, to spot a retried model attempt.
    attempt_by_node_run: dict[str, str] = field(default_factory=dict)

    def hold(
        self, chunk: AIMessage, metadata: StreamChunkMetadata, *, reply_tier: bool = True
    ) -> HeldChunk:
        """Hold one model chunk's text; reply_tier False is a tier whose text is never the answer."""
        message_id = chunk.id or ""
        if announces_tool_call(chunk):
            self.tool_call_ids.add(message_id)
        text = chunk.text
        if not (text and reply_tier) or message_id in self.tool_call_ids:
            return HeldChunk(message_id, "")
        abandoned_id = self._retract_abandoned_attempt(message_id, metadata)
        self.texts[message_id] = self.texts.get(message_id, "") + text
        return HeldChunk(message_id, text, abandoned_id)

    def _retract_abandoned_attempt(
        self, message_id: str, metadata: StreamChunkMetadata
    ) -> str | None:
        """Forget the text of an earlier model attempt in this node run; return its id.

        A retried or failed-over model call streams each attempt under its own message
        id within one node run, and only the last attempt ever reaches a boundary.
        """
        node_run = metadata.get("langgraph_checkpoint_ns")
        if node_run is None:
            return None
        previous = self.attempt_by_node_run.get(node_run)
        self.attempt_by_node_run[node_run] = message_id
        if previous is None or previous == message_id or previous not in self.texts:
            return None
        del self.texts[previous]
        return previous

    def mark_announced(self, message: AIMessage) -> None:
        """Record that a finished message called a tool, for a provider whose chunks never said so."""
        if announces_tool_call(message):
            self.tool_call_ids.add(message.id or "")

    def settle(
        self, messages: Sequence[object], complete_message: str, *, reply_tier: bool = True
    ) -> tuple[str, str | None]:
        """Keep the message a node just produced, a preamble before a hand-off included: it was said.

        Returns the updated complete_message plus the boundary's message id,
        None when the node produced none.
        """
        boundary = last_ai_message(messages) if reply_tier else None
        if boundary is None:
            return complete_message, None
        boundary_id = boundary.id or ""
        held = self.texts.pop(boundary_id, "")
        if held:
            complete_message = append_message_bubble(complete_message, held)
        return complete_message, boundary_id

    def supersede(self) -> None:
        """Forget every reply held so far: the run was sent back to work, so its answer comes after."""
        self.texts.clear()

    def flush(self, complete_message: str) -> str:
        """Append text whose message never reached a boundary (a cancelled run)."""
        for text in self.texts.values():
            if text:
                complete_message = append_message_bubble(complete_message, text)
        return complete_message

    def reply_text(self) -> str:
        """Return the answer of a run read to its end: every held message that called no tool."""
        answer = ""
        for message_id, text in self.texts.items():
            if message_id not in self.tool_call_ids:
                answer = append_message_bubble(answer, text)
        return answer
