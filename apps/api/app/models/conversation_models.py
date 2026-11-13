"""Persistence-side models for the ``conversations`` collection, plus the
conversation endpoints' response shapes.

The persistence models describe the document as it is actually stored and read
back — distinct from the API *request* models, which live in ``chat_models``.
Messages are ``ConversationEntry`` rows read from conversation_entries, each with
its seq; a before-validator runs the legacy tool-data normalization at the read
boundary so the rest of the app never sees an un-normalized message.

The response models at the bottom of this file live here rather than alongside
the requests in ``chat_models`` because they are built from the persistence
shapes above (``ConversationSummary``, ``ConversationMessageHit``) — and
``conversation_models`` already imports ``chat_models``, so the other direction
would be a cycle.

Timestamps are the legacy camelCase pair: ``createdAt`` is an ISO string written
at insert time, ``updatedAt`` is a BSON date bumped via ``$currentDate`` on every
write. They are intentionally NOT the base's stamped snake_case ``created_at`` /
``updated_at`` — normalizing them to the standard pair is a tracked follow-up, so
the repository bumps ``updatedAt`` explicitly on each write rather than relying on
the base's auto-stamp.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.artifact_models import ArtifactRegistryEntry
from app.models.chat_models import (
    ConversationSource,
    MessageModel,
    SystemPurpose,
)
from app.models.conversation_log_models import ConversationState
from app.models.document_models import UserScopedDocument
from app.schemas.common import ResponseModel
from app.utils.tool_data_utils import convert_legacy_tool_data


def _coerce_source(value: object) -> object:
    """Map a stored source string to the enum, tolerating unknown legacy values."""
    if isinstance(value, (ConversationSource, str)):
        return ConversationSource.coerce(value)
    return value


class ConversationEntry(MessageModel):
    """One message of a conversation's log with the seq its append committed it under: order is seq, never a date."""

    seq: int

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        return convert_legacy_tool_data(value) if isinstance(value, dict) else value

    @classmethod
    def committed(cls, message: MessageModel, seq: int) -> ConversationEntry:
        """The message as committed at seq."""
        return cls.model_validate({**message.model_dump(), "seq": seq})


class ConversationDocument(UserScopedDocument):
    """A conversation as the repository returns it: its head fields and, where read, its entries.

    ``extra="allow"`` preserves stray/legacy top-level fields (e.g. ``artifacts``,
    ``metadata``) so a full-document read returns them verbatim, matching the
    pre-repository behaviour.
    """

    model_config = ConfigDict(extra="allow")

    conversation_id: str
    description: str = "New Chat"
    is_system_generated: bool | None = False
    system_purpose: SystemPurpose | None = None
    is_unread: bool | None = False
    source: ConversationSource | None = None
    is_onboarding_demo: bool = False
    starred: bool | None = None
    # Derived on read from the log's state (never stored): live work awaits the user's approval.
    awaiting_approval: bool = Field(default=False, exclude=True)
    # The tracked todo whose chat this is: its runs execute here. Such a chat is
    # reached only from its todo, never listed (see _listed). Set once at creation.
    todo_id: str | None = None
    # Assembled from conversation_entries by the reads that need history; never stored on the head.
    messages: list[ConversationEntry] = Field(default_factory=list)
    # Derived on read (never stored): messages older than the ones read exist; page them by seq.
    has_older: bool = False
    # Conversation-level artifact registry: one entry per agent-written file,
    # deduped by path; services/chat/artifacts_registry.py owns every write.
    artifacts: list[ArtifactRegistryEntry] = Field(default_factory=list)
    createdAt: str | None = None
    updatedAt: datetime | None = None

    _coerce_source = field_validator("source", mode="before")(_coerce_source)


class ConversationUpdate(BaseModel):
    """Typed ``$set`` fields for a conversation. The repository bumps ``updatedAt``
    itself, so it is not part of the update surface."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    starred: bool | None = None
    is_unread: bool | None = None


class ConversationSummary(ResponseModel):
    """The projected conversation-list row — every field the web list consumes,
    without the heavy ``messages`` array."""

    model_config = ConfigDict(extra="allow")

    conversation_id: str
    user_id: str
    description: str | None = None
    starred: bool | None = None
    is_system_generated: bool | None = None
    system_purpose: SystemPurpose | None = None
    is_unread: bool | None = None
    source: ConversationSource | None = None
    # Live work in the conversation awaits the user's approval: the sidebar's dot.
    awaiting_approval: bool = False
    createdAt: str | None = None
    updatedAt: datetime | None = None

    _coerce_source = field_validator("source", mode="before")(_coerce_source)


class ConversationMessageHit(BaseModel):
    """A single conversation message tagged with its conversation id — the shape of
    the pinned-messages and message-search results."""

    conversation_id: str
    message: ConversationEntry


class ConversationDescriptionHit(BaseModel):
    """A conversation matched by its description in a text search."""

    conversation_id: str
    description: str | None = None


class ConversationSearchResults(BaseModel):
    """The two facets of a conversation text search (``$facet`` output)."""

    messages: list[ConversationMessageHit] = Field(default_factory=list)
    conversations: list[ConversationDescriptionHit] = Field(default_factory=list)


class _SourceRow(BaseModel):
    """Projection of just a conversation's stored source string."""

    model_config = ConfigDict(extra="ignore")

    source: str | None = None


class _TodoBindingRow(BaseModel):
    """Projection of just the tracked todo a conversation belongs to."""

    model_config = ConfigDict(extra="ignore")

    todo_id: str | None = None


class _SystemGeneratedRow(BaseModel):
    """Projection of a conversation's system-generated flag and why it exists."""

    model_config = ConfigDict(extra="ignore")

    is_system_generated: bool | None = None
    system_purpose: SystemPurpose | None = None


class _ConversationIdRow(BaseModel):
    """Projection of just a conversation id (owner lookups)."""

    model_config = ConfigDict(extra="ignore")

    conversation_id: str


class _ConversationOwnerRow(_ConversationIdRow):
    """Projection of a conversation id and the user who owns it; anything else is a projection bug."""

    model_config = ConfigDict(extra="forbid")

    user_id: str


class MessageShape(BaseModel):
    """The fields that say what a stored message is and what it points at, read once from its raw fields."""

    model_config = ConfigDict(extra="ignore")

    kind: str | None = None
    type: str | None = None
    reply_id: str | None = None
    reacts_to_message_id: str | None = None
    response: str | None = None
    date: object = None
    message_id: str | None = None


class NotKeptFields(BaseModel):
    """Old message fields no client renders, so the log keeps them nowhere."""

    model_config = ConfigDict(extra="ignore")

    disclaimer: object = None
    subtype: object = None
    file: object = None
    filename: object = None
    filetype: object = None
    metadata: object = None

    def carried(self) -> bool:
        return any(value is not None for value in self.model_dump().values())


class StoredEntry(BaseModel):
    """One conversation_entries document, or one value of a head's outbox: its keys, then the message as stored."""

    model_config = ConfigDict(extra="allow")

    conversation_id: str
    user_id: str
    seq: int
    id: str
    at: datetime | None = None
    migration_fields: dict[str, str] | None = None
    # Set only on an amendable log entry (a reply, a user message): each amend bumps it.
    revision: int | None = None

    def message_fields(self) -> dict[str, object]:
        """Return the stored message's own fields: everything but the entry's keys and Mongo's _id."""
        return {key: value for key, value in (self.model_extra or {}).items() if key != "_id"}

    def shape(self) -> MessageShape:
        """Return the stored message's identifying fields."""
        return MessageShape.model_validate(self.message_fields())

    def document(self) -> dict[str, object]:
        """Return the entry exactly as it was read, to write it elsewhere unchanged."""
        return {
            key: value for key, value in self.model_dump(exclude_unset=True).items() if key != "_id"
        }


class EntryAddress(BaseModel):
    """Where a stored entry sits: its conversation and seq, projected."""

    model_config = ConfigDict(extra="ignore")

    conversation_id: str
    seq: int

    @property
    def key(self) -> tuple[str, int]:
        return (self.conversation_id, self.seq)


class EntryKey(BaseModel):
    """Which entry holds a seq: the id and seq of a stored entry, projected."""

    model_config = ConfigDict(extra="ignore")

    id: str
    seq: int


class LegacyMessage(BaseModel):
    """One element of the embedded messages array the entries migration copies, in whatever shape the old build wrote."""

    model_config = ConfigDict(extra="allow")

    message_id: str | None = None
    date: object = None

    def stored(self) -> dict[str, object]:
        """Return the element exactly as it is stored in the array."""
        return self.model_dump(exclude_unset=True)


class StepHolder(BaseModel):
    """Who holds a conversation's step: its epoch, and the Redis key that proves it alive."""

    epoch: int
    alive_key: str


class ConversationHead(BaseModel):
    """A conversations document as the entry log reads it: identity, log_head, outbox and log state."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    conversation_id: str
    user_id: str
    log_head: int | None = None
    outbox: dict[int, StoredEntry] = Field(default_factory=dict)
    existing: list[EntryKey] = Field(default_factory=list)
    # The conversation log's fold, absent until its first entry; the step holder; the last epoch handed out.
    state: ConversationState | None = None
    runner: StepHolder | None = None
    runner_epoch: int = 0


class EmbeddedHead(BaseModel):
    """A head as the entries migration reads it: the old embedded array, its fingerprint, and the log."""

    model_config = ConfigDict(extra="ignore")

    conversation_id: str
    user_id: str
    source: str | None = None
    log_head: int | None = None
    state: ConversationState | None = None
    messages: list[LegacyMessage] = Field(default_factory=list)
    migrated_fingerprint: int | None = None
    fingerprint: int = Field(alias="_fingerprint")


class HeadRefRow(BaseModel):
    """A head as a migration scan lists it: its _id as text, and identity."""

    model_config = ConfigDict(extra="forbid")

    head_id: str
    conversation_id: str
    user_id: str


# ---------------------------------------------------------------------------
# Conversation endpoint responses
# ---------------------------------------------------------------------------


class CreateConversationResponse(BaseModel):
    """Acknowledgement for a newly created conversation."""

    conversation_id: str
    user_id: str
    createdAt: str
    detail: str


class SystemConversationCreated(BaseModel):
    """A system-generated conversation (workflow / email / reminder processing).

    Carries more than :class:`CreateConversationResponse` because the caller that
    binds the conversation to its workflow reads the system flags back. Not an
    endpoint response — no route creates a system conversation.
    """

    conversation_id: str
    user_id: str
    description: str
    is_system_generated: bool
    system_purpose: SystemPurpose
    createdAt: str
    detail: str


class ConversationListResponse(ResponseModel):
    """One page of the conversation list: every starred conversation followed by
    the requested page of the non-starred ones."""

    conversations: list[ConversationSummary]
    total: int
    page: int
    limit: int
    total_pages: int


class ConversationSyncRow(ResponseModel):
    """One batch-sync row — the conversation's client-visible fields plus its full
    message history and artifact registry.

    """

    conversation_id: str
    description: str
    starred: bool | None = None
    is_system_generated: bool | None = None
    system_purpose: SystemPurpose | None = None
    is_unread: bool | None = None
    createdAt: str | None = None
    updatedAt: datetime | None = None
    messages: list[ConversationEntry] = Field(default_factory=list)
    # Messages older than these exist: GET /conversations/{id}/messages?before_seq= pages them.
    has_older: bool = False
    # Mirrored verbatim from the document (see ConversationDocument.artifacts).
    artifacts: list[ArtifactRegistryEntry] = Field(default_factory=list)
    # Live work in the conversation awaits the user's approval: the sidebar's dot.
    awaiting_approval: bool = False
    # The tracked todo this chat belongs to; clients keep such a chat out of their lists.
    todo_id: str | None = None
    # Where the chat originated; a bot chat is never listed, so clients need it to keep one cached.
    source: ConversationSource | None = None


class ConversationMessagesPage(ResponseModel):
    """The newest messages before a seq, oldest first; has_more when older ones remain."""

    messages: list[ConversationEntry]
    has_more: bool


class BatchSyncResponse(ResponseModel):
    """The conversations a client's sync request found stale."""

    conversations: list[ConversationSyncRow] = Field(default_factory=list)
    # Requested ids the user has no conversation for: a client drops them, as it
    # cannot learn of a deleted chat that is never listed (a tracked todo's).
    missing: list[str] = Field(default_factory=list)


class ConversationActionResponse(BaseModel):
    """Acknowledgement for a conversation-scoped action that reports back which
    conversation it applied to — delete, rename, mark read/unread."""

    message: str
    conversation_id: str


class DeleteAllConversationsResponse(BaseModel):
    """Acknowledgement for the bulk delete, which names no single conversation."""

    message: str


class StarConversationResponse(BaseModel):
    """Acknowledgement echoing the conversation's new starred state."""

    message: str
    starred: bool


class UpdateDescriptionResponse(ConversationActionResponse):
    """Rename acknowledgement, echoing the description that was stored."""

    description: str


class PinMessageResponse(BaseModel):
    """Acknowledgement echoing a message's new pinned state."""

    message: str
    pinned: bool


class PinnedMessagesResponse(ResponseModel):
    """Every pinned message across the user's conversations."""

    results: list[ConversationMessageHit] = Field(default_factory=list)
