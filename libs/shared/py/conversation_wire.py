"""The conversation stream's wire shapes that every reader shares: the API writes them, voice reads them.

A reply reaches a client as bubbles the server split once, live and settled, and its tool
cards as the ordered timeline the server folded; no reader parses either again.
"""

from enum import StrEnum
from typing import Annotated, Any, Generic, Literal, NotRequired, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, with_config
from pydantic.config import JsonDict
from typing_extensions import TypedDict

# A defaulted field is always serialized, so the generated client type marks it required.
WIRE_CONFIG = ConfigDict(
    frozen=True, extra="forbid", json_schema_serialization_defaults_required=True
)

#: What the model writes between two bubbles, and how a reply's text joins its bubbles.
NEW_MESSAGE_BREAKER = "<NEW_MESSAGE_BREAK>"


def _required_keys_only(schema: JsonDict) -> None:
    """List only the keys the TypedDict requires: an absent NotRequired key is never serialized.

    Pydantic 2.12 marks every key required under a parent's json_schema_serialization_defaults_required.
    """
    schema["required"] = [
        key for key in ToolDataEntry.__annotations__ if key in ToolDataEntry.__required_keys__
    ]


@with_config(ConfigDict(json_schema_extra=_required_keys_only))
class ToolDataEntry(TypedDict):
    """One tool card: stored on messages and log entries, and streamed in frames.

    Every key an emitter stamps is declared, because Pydantic drops undeclared keys on dump.
    data is open on purpose: each tool owns the JSON its card reads.
    """

    tool_name: str
    # Any on purpose: it is JSON the tool owns, which the generated TypeScript reads as unknown.
    data: Any
    # Legacy stored entries predate it, so a read tolerates its absence.
    timestamp: NotRequired[str | None]
    # Which card renders the entry; plain per-tool entries are keyed off tool_name alone.
    tool_category: NotRequired[str]
    # Tags an entry produced inside a delegated subagent.
    subagent_id: NotRequired[str]
    # MCP App UI metadata and the server that serves it; a restored turn re-fetches the iframe with them.
    mcp_ui: NotRequired[dict[str, Any] | None]
    mcp_server_url: NotRequired[str | None]


class ImageData(BaseModel):
    """Generated-image metadata attached to a chat message."""

    url: str
    prompt: str
    improved_prompt: str | None = None


class ReplyToMessageData(BaseModel):
    """Data for the message being replied to."""

    id: str
    content: str
    role: Literal["user", "assistant"]


class ReplyOutcome(StrEnum):
    """How a finished reply ended."""

    ANSWERED = "answered"
    STOPPED = "stopped"
    # The user spoke over it: the saved reply is what they heard, up to Reply.heard_through.
    TRUNCATED = "truncated"
    FAILED = "failed"
    SILENT = "silent"


class FailureReason(StrEnum):
    """Why a reply failed; a client words the line it shows under the reply from it."""

    # The model call failed (a provider error, a dropped stream).
    MODEL_ERROR = "model_error"
    # The turn ran out of steps before it answered.
    STEP_LIMIT = "step_limit"
    # The process answering died; a later reply answers again.
    SERVER_RESTART = "server_restart"


class FrameKind(StrEnum):
    """Discriminator of an output frame on the conversation's event stream."""

    ENTRY = "entry"
    ENTRY_UPDATED = "entry_updated"
    REPLY_DELTA = "reply_delta"
    WORK_DELTA = "work_delta"
    RETRACT = "retract"
    STATE = "state"
    CONVERSATION_UPDATED = "conversation_updated"
    SCREEN = "screen"
    SCREEN_INSERT = "screen_insert"
    SCREEN_UPDATE = "screen_update"


class ScreenItemKind(StrEnum):
    """What one item of the screen shows."""

    USER = "user"
    REPLY = "reply"
    WORK = "work"
    NOTICE = "notice"
    WORKFLOW_FIRED = "workflow_fired"
    TODO_WOKE = "todo_woke"


class TimelineStepKind(StrEnum):
    """What one row of a tool timeline shows: a tool call, or a subagent's group of them."""

    TOOL = "tool"
    SUBAGENT = "subagent"


class TimelineStep(BaseModel):
    """One row of the tool thread, keyed stably across the stream.

    data is the tool-call entry, or the subagent group with its handoff_input, handoff_output and
    step_keys (one per tool call, in order) filled in.
    """

    model_config = WIRE_CONFIG

    kind: TimelineStepKind
    key: str
    data: JsonValue


class TimelineCard(BaseModel):
    """A card rendered on its own below the thread; a grouped tool's calls arrive as one card."""

    model_config = WIRE_CONFIG

    key: str
    card: ToolDataEntry


class ToolProgress(BaseModel):
    """The newest tool call's line, which the loading row shows while the item streams."""

    model_config = WIRE_CONFIG

    message: str = Field(min_length=1)
    tool_name: str
    tool_category: str
    integration_name: str | None
    icon_url: str | None
    show_category: bool


class ToolTimeline(BaseModel):
    """What an item's cards show, in order: the tool thread, then the cards rendered on their own."""

    model_config = WIRE_CONFIG

    steps: tuple[TimelineStep, ...] = ()
    cards: tuple[TimelineCard, ...] = ()
    progress: ToolProgress | None = None


class ScreenItemBase(BaseModel):
    """Where an item sits on the screen."""

    model_config = ConfigDict(frozen=True)

    # Stable for the item's whole life, live and reloaded.
    id: str = Field(min_length=1)
    # The log position the item became visible at; the screen is ordered by it.
    seq: int = Field(ge=1)
    at: AwareDatetime


class ReplyFile(BaseModel):
    """A session artifact a reply delivers, addressed by its path under the session's artifacts/."""

    model_config = ConfigDict(frozen=True)

    path: str = Field(min_length=1)
    content_type: str | None


class ReplyItem(ScreenItemBase):
    """GAIA's reply: its bubbles and own cards; outcome is None while it is still being written."""

    kind: Literal[ScreenItemKind.REPLY] = ScreenItemKind.REPLY
    bubbles: tuple[str, ...]
    tool_data: tuple[ToolDataEntry, ...]
    timeline: ToolTimeline
    follow_up_actions: tuple[str, ...]
    image: ImageData | None
    pinned: bool
    quote: ReplyToMessageData | None
    outcome: ReplyOutcome | None
    failure: FailureReason | None
    narrates: tuple[str, ...]
    # The user message a retry of this reply sends again; None when it answers none.
    retry_target: str | None
    # The files the reply and the work it narrates wrote; a chat platform uploads them once it settles.
    files: tuple[ReplyFile, ...]


class BubbleTextDelta(BaseModel):
    """More text for one bubble of the reply; a bubble past the last opens it."""

    model_config = WIRE_CONFIG

    type: Literal["bubble_text"] = "bubble_text"
    bubble: int = Field(ge=0)
    text: str


class BubblesDelta(BaseModel):
    """The reply's bubbles as they now stand, replacing every one shown: text the model took back is gone."""

    model_config = WIRE_CONFIG

    type: Literal["bubbles"] = "bubbles"
    bubbles: tuple[str, ...]


class CardsDelta(BaseModel):
    """The reply's cards as they now stand, with the timeline they fold to."""

    model_config = WIRE_CONFIG

    type: Literal["cards"] = "cards"
    tool_data: tuple[ToolDataEntry, ...]
    timeline: ToolTimeline


class FollowUpsDelta(BaseModel):
    """The suggestions offered under the reply."""

    model_config = WIRE_CONFIG

    type: Literal["follow_up_actions"] = "follow_up_actions"
    follow_up_actions: tuple[str, ...]


ReplyDelta = Annotated[
    BubbleTextDelta | BubblesDelta | CardsDelta | FollowUpsDelta, Field(discriminator="type")
]


class ReplyDeltaFrame(BaseModel):
    """Streamed content of one comms attempt; reply_id is None until its reply entry exists."""

    model_config = WIRE_CONFIG

    kind: Literal[FrameKind.REPLY_DELTA] = FrameKind.REPLY_DELTA
    attempt_id: str
    reply_id: str | None
    # 0-based, +1 per delta in the attempt; a client ignores an index it already applied.
    index: int = Field(ge=0)
    payload: ReplyDelta


class ConversationUpdatedFrame(BaseModel):
    """The conversation's own metadata changed: its title, once generated from the first message."""

    model_config = WIRE_CONFIG

    kind: Literal[FrameKind.CONVERSATION_UPDATED] = FrameKind.CONVERSATION_UPDATED
    description: str


class ScreenItemHeader(ScreenItemBase):
    """Any item, read only for where it sits: a reader that shows one kind skips the rest by it."""

    kind: ScreenItemKind


ItemT = TypeVar("ItemT")


class ScreenFrame(BaseModel, Generic[ItemT]):
    """The newest page of the screen; a client replaces what it holds from the first item's seq on."""

    model_config = WIRE_CONFIG

    kind: Literal[FrameKind.SCREEN] = FrameKind.SCREEN
    items: tuple[ItemT, ...]


class ScreenInsertFrame(BaseModel, Generic[ItemT]):
    """An item became visible; its seq is its position, before every item with a higher one."""

    model_config = WIRE_CONFIG

    kind: Literal[FrameKind.SCREEN_INSERT] = FrameKind.SCREEN_INSERT
    item: ItemT


class ScreenUpdateFrame(BaseModel, Generic[ItemT]):
    """An item already shown changed in place; it keeps its position."""

    model_config = WIRE_CONFIG

    kind: Literal[FrameKind.SCREEN_UPDATE] = FrameKind.SCREEN_UPDATE
    item: ItemT
