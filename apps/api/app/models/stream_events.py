"""Typed schema for the chat SSE event vocabulary.

Single source of truth for every frame the chat stream emits over the wire. The
FORMAT/EMIT helpers build their payloads through these models instead of inline
dict literals, so each shape is declared in exactly one place and can drift only
if this file changes.

Byte-compatibility contract: a model's ``model_dump()`` must serialize (via
``json.dumps``) to the exact bytes the old inline literal produced — the
frontend parser must not be able to tell the difference. That requires:

* field declaration order matches the literal's key order (``json.dumps``
  preserves dict insertion order; ``model_dump`` preserves field order);
* fields the literal always included (even as ``null``) are dumped without
  ``exclude_none``; fields the literal added conditionally use
  ``exclude_none=True`` at the call site.

Two frame families:

* structured-payload frames (``tool_data``, ``tool_output``, ``reasoning``,
  ``subagent_start``, ``subagent_end``) carry a nested object — the object is
  modeled here and wrapped in its one-word envelope key at the emit site;
* single-field frames (``response``, ``follow_up_actions``, ``error``,
  ``main_response_complete``, ``todo_progress``, ``conversation_description``,
  ``conversation_initialized``) are the envelope.

Two frames are intentionally not modeled here:

* ``keepalive`` is emitted by the stream manager as a compact literal
  (``{"keepalive":true}``) whose byte shape differs from ``json.dumps`` output;
* ``progress`` (``{"progress": "<text>"}``) is a trivial single-string frame
  emitted from ~two dozen scattered tool sites; both remain documented in the
  frontend Zod schema, which the parser validates against.

The frontend mirror of this vocabulary is ``libs/shared/ts/src/chat/schema.ts``.
"""

from typing import Any

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Structured payloads (wrapped in a one-word envelope key at the emit site)
# ---------------------------------------------------------------------------


class ToolCallsDataEntryData(BaseModel):
    """Inner ``data`` object of a ``tool_calls_data`` entry."""

    tool_name: str
    tool_category: str
    message: str | None
    show_category: bool
    tool_call_id: str | None
    inputs: dict[str, Any]
    icon_url: str | None
    integration_name: str | None


class ToolCallsDataEntry(BaseModel):
    """The ``tool_calls_data`` tool_data entry built by ``format_tool_call_entry``.

    Emitted (wrapped in a ``tool_data`` envelope) when a tool call's args are
    complete. Other tool_data variants (``mcp_app``, ``todo_progress``) ride the
    same envelope but are assembled at their own sites.
    """

    tool_name: str
    tool_category: str
    data: ToolCallsDataEntryData
    timestamp: str
    mcp_ui: dict[str, Any] | None
    mcp_server_url: str | None


class ToolOutputPayload(BaseModel):
    """Result text for a completed tool call, keyed by its ``tool_call_id``."""

    tool_call_id: str
    output: str
    subagent_id: str | None = None


class ReasoningPayload(BaseModel):
    """A streamed reasoning ("thinking") delta from the model."""

    content: str
    subagent_id: str | None = None


class SubagentStartPayload(BaseModel):
    """Lifecycle payload marking a delegated subagent beginning execution."""

    subagent_id: str
    subagent_name: str
    agent_type: str
    started_at: str
    icon_url: str | None = None
    tool_category: str | None = None
    parent_subagent_id: str | None = None


class SubagentEndPayload(BaseModel):
    """Lifecycle payload marking a delegated subagent finishing."""

    subagent_id: str
    duration_ms: int
    token_count: int | None = None


# ---------------------------------------------------------------------------
# Single-field frames (the envelope IS the frame)
# ---------------------------------------------------------------------------


class ResponseFrame(BaseModel):
    """Assistant text delta."""

    response: str


class FollowUpActionsFrame(BaseModel):
    """Suggested follow-up actions for the turn."""

    follow_up_actions: list[str]


class ErrorFrame(BaseModel):
    """Terminal error for the stream."""

    error: str


class MainResponseCompleteFrame(BaseModel):
    """Marks the primary assistant response as finished."""

    main_response_complete: bool


class TodoProgressFrame(BaseModel):
    """Envelope for a todo-progress snapshot."""

    todo_progress: dict[str, Any]


class ConversationDescriptionFrame(BaseModel):
    """A freshly generated conversation title/description."""

    conversation_description: str


class ConversationInitializedFrame(BaseModel):
    """Identity frame sent first: conversation + message ids for the turn.

    New conversations dump all fields (``conversation_description`` may be
    ``null`` and is still included); resumed conversations exclude the two
    conversation-level fields via ``model_dump(exclude=...)``.
    """

    conversation_id: str | None = None
    conversation_description: str | None = None
    # Single identity: this IS the client's send id (turn_id) when the client
    # provided one — the optimistic record already carries the final key.
    user_message_id: str
    # The user message text. Makes the event log a complete record of the
    # turn: a client that reloads before its local write ever committed can
    # reconstruct the user message from replay alone.
    user_message_content: str
    bot_message_id: str
    stream_id: str
