"""Typed schema for the chat SSE event vocabulary.

Single source of truth for every frame the chat stream emits — FORMAT/EMIT
helpers build payloads through these models, not inline literals (frontend
mirror: libs/shared/ts/src/chat/schema.ts).

Byte-compatibility: model_dump() must serialize to the exact bytes the old
inline literal produced — field order must match, and exclude_none is set
per-field to match which fields the literal always vs conditionally included.
keepalive and progress frames are intentionally unmodeled (differing byte
shape / ~two dozen scattered emit sites); both stay in the frontend Zod schema.

Replay-completeness: the event log is a turn's sole source of truth, so any
new client-visible fact must live in a frame, never assumed to survive in
client memory, and must never encode an implicit request-shape assumption.
"""

from typing import Any

from pydantic import BaseModel

from app.models.hil_models import HILApprovalStatus

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


class ApprovalRequestEntryData(BaseModel):
    """Inner ``data`` object of a HIL ``approval_request`` entry."""

    approval_id: str
    tool_call_id: str
    gated_tool_name: str
    integration_name: str | None
    summary: str
    # The gated call's own arguments — arbitrary LLM-authored JSON, no fixed schema.
    args_preview: dict[str, Any]
    status: HILApprovalStatus
    feedback: str | None
    auto_reason: str | None
    timeout_seconds: int


class ApprovalRequestEntry(BaseModel):
    """The ``approval_request`` tool_data entry built by ``hil.bridge``.

    Emitted (wrapped in a ``tool_data`` envelope) when a gated call asks for the
    user's decision, and re-emitted in its resolved status once decided —
    ``stream_utils._append_or_upsert_tool_data`` replaces the earlier frame in
    the persisted turn so only the final status survives.
    """

    tool_name: str
    tool_category: str
    data: ApprovalRequestEntryData
    timestamp: str


class ToolOutputPayload(BaseModel):
    """Result text for a completed tool call, keyed by its ``tool_call_id``."""

    tool_call_id: str
    output: str
    subagent_id: str | None = None


class MessageBoundaryPayload(BaseModel):
    """End of one assistant message inside a turn.

    ``discarded`` is true when that message turned out to carry tool calls, which
    makes any text it streamed a MOMENT-1 preamble ("let me get that set up…")
    the user must not keep — the real reply arrives as the next message. The
    frame exists because the wire streams that text BEFORE the tool call, so a
    live consumer has already shown it by the time we know, and has to retract
    it rather than leave a duplicate reply on screen.
    """

    message_id: str
    discarded: bool


class ReasoningPayload(BaseModel):
    """A streamed reasoning ("thinking") delta from the model."""

    content: str
    subagent_id: str | None = None


class SubagentStartPayload(BaseModel):
    """Lifecycle payload marking a delegated subagent beginning execution."""

    subagent_id: str
    subagent_name: str
    #: The subagent's stable id (todos, gmail): what a playbook's handoff: names.
    #: subagent_id is this dispatch's row (unique per call) — right for nesting,
    #: wrong for matching a call back to the subagent that made it.
    subagent: str | None = None
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


class ModelFallbackFrame(BaseModel):
    """One-time notice that the primary model failed and a backup answered.

    Emitted at most once per stream; the frontend surfaces it as a quiet toast.
    """

    model_fallback: dict[str, str]


class MainResponseCompleteFrame(BaseModel):
    """Marks the primary assistant response as finished.

    ``usage`` carries the turn's aggregate token usage (per-model input/output/
    cached counts from the LangChain usage_metadata) — consumed by eval
    transports for real token accounting; optional and backward-compatible.
    """

    main_response_complete: bool
    usage: dict[str, Any] | None = None


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
