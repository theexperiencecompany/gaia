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

Replay-completeness contract: the event log built from these frames is the
turn's source of truth. A client attaching mid-turn (reload, second tab)
reconstructs the ENTIRE turn from replay alone — so any new client-visible
fact about a turn must be carried in a frame, never assumed to survive in
client memory or local persistence (this is why ``conversation_initialized``
carries the user's message text, not just ids).

Frames must not encode implicit request-shape assumptions. Example of the bug
class: ``messages[-1]`` is the current user turn only when its role is
``user`` — clients omit empty-text (file-only) turns from history, so the last
entry can be the previous assistant reply. Derive such values defensively and
in exactly one helper, so the frame and the persisted record can never
disagree.
"""

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, JsonValue

from app.models.hil_models import ApprovalDescription
from app.schemas.common import ResponseModel
from shared.py.approvals import ActionResult, ApprovalDecider, ApprovalOutcome, ApprovalStatus

# ---------------------------------------------------------------------------
# Structured payloads (wrapped in a one-word envelope key at the emit site)
# ---------------------------------------------------------------------------


class ToolCallsDataEntryData(ResponseModel):
    """One tool call as its tool_calls_data card shows it; the fold adds its output once the tool returns."""

    tool_name: str
    tool_category: str
    message: str | None
    show_category: bool
    tool_call_id: str | None
    inputs: dict[str, object]
    icon_url: str | None
    integration_name: str | None
    output: str | None = Field(default=None, exclude_if=lambda output: output is None)
    #: Set when the output was cut: how many characters the tool returned.
    output_original_length: int | None = Field(
        default=None, exclude_if=lambda length: length is None
    )


class ToolCallReasoningStep(ResponseModel):
    """The model's thinking between tool calls, riding the tool-call channel as a step of its own."""

    tool_name: Literal["reasoning"]
    tool_category: Literal["reasoning"]
    message: str
    reasoning: str


#: A step a tool_calls_data card or a subagent group shows: a tool call, or the thinking around it.
ToolCallStep = ToolCallsDataEntryData | ToolCallReasoningStep
#: A tool_calls_data card's data: one step, or a run of thinking steps the fold keeps on one card.
ToolCallsCardData = ToolCallStep | list[ToolCallStep]


class ApprovalRequestEntryData(BaseModel):
    """Inner ``data`` object of a HIL ``approval_request`` entry."""

    approval_id: str
    tool_call_id: str
    gated_tool_name: str
    integration_name: str | None
    description: ApprovalDescription
    # The gated call's own arguments — arbitrary LLM-authored JSON, no fixed schema.
    args_preview: dict[str, JsonValue]
    # Where the approval stands: the one status every client renders; it is never re-derived.
    status: ApprovalStatus
    # How the log recorded its end (None while none is), who decided, and what the action did.
    outcome: ApprovalOutcome | None
    decider: ApprovalDecider | None = None
    action: ActionResult | None = None
    feedback: str | None
    auto_reason: str | None
    # When the user was asked, so a client can say how long ago.
    asked_at: AwareDatetime | None = None
    # The call asks in every mode, so clients must not offer "always allow" on it.
    always_asks: bool = False


class ApprovalRequestEntry(BaseModel):
    """An approval card: the screen draws one per ApprovalRequested entry, ended by its decision entries."""

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
    """End of one assistant message inside a turn; the next text opens a new bubble."""

    message_id: str


class ReasoningPayload(BaseModel):
    """A streamed reasoning ("thinking") delta from the model."""

    content: str
    subagent_id: str | None = None


#: "handoff" survives only in stored conversations; every new run is "spawned".
SubagentAgentType = Literal["handoff", "spawned"]


class SubagentStartPayload(BaseModel):
    """Lifecycle payload marking a delegated subagent beginning execution."""

    subagent_id: str
    subagent_name: str
    #: The integration id the removed handoff tool stamped; no current producer sets it.
    #: subagent_id is this dispatch's row (unique per call), not the subagent's identity.
    subagent: str | None = None
    agent_type: SubagentAgentType
    started_at: str
    icon_url: str | None = None
    tool_category: str | None = None
    parent_subagent_id: str | None = None


class SubagentEndPayload(BaseModel):
    """Lifecycle payload marking a delegated subagent finishing."""

    subagent_id: str
    duration_ms: int
    token_count: int | None = None


class SubagentGroupCardData(ResponseModel):
    """A subagent_group card's data as its start opens it; its end fills duration, tokens and completion."""

    subagent_id: str
    subagent: str | None
    subagent_name: str
    agent_type: SubagentAgentType
    started_at: str
    icon_url: str | None
    tool_category: str | None
    tool_calls: list[ToolCallStep] = Field(default_factory=list)
    duration_ms: int | None = None
    token_count: int | None = None
    completed_at: str | None = None
    nested_subagents: list["SubagentGroupCardData"] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Single-field frames (the envelope IS the frame)
# ---------------------------------------------------------------------------


class ResponseFrame(BaseModel):
    """Assistant text delta."""

    response: str


class FollowUpActionsFrame(BaseModel):
    """Suggested follow-up actions for the turn."""

    follow_up_actions: list[str]


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
