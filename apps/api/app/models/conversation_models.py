"""Persistence-side models for the ``conversations`` collection, plus the
conversation endpoints' response shapes.

The persistence models describe the document as it is actually stored and read
back — distinct from the API *request* models, which live in ``chat_models``.
A conversation's messages are its log's entries (conversation_log_models); the
old embedded message shape is known only to the entries migration.

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

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.constants.chat import BOT_CONVERSATION_SOURCES
from app.models.artifact_models import ArtifactRegistryEntry
from app.models.chat_models import ConversationModel, ConversationSource, SystemPurpose
from app.models.conversation_frame_models import EntryFrame, StateFrame
from app.models.conversation_log_models import ConversationState
from app.models.conversation_screen_models import ScreenItem, TextItem
from app.models.document_models import UserScopedDocument
from app.schemas.common import ResponseModel


def _coerce_source(value: object) -> object:
    """Map a stored source string to the enum, tolerating unknown legacy values."""
    if isinstance(value, (ConversationSource, str)):
        return ConversationSource.coerce(value)
    return value


class ConversationDocument(UserScopedDocument, ConversationModel):
    """A conversation head as the repository returns it: the create request's fields and what the server keeps.

    Undeclared stored fields (the old embedded messages, the migration's marks) never reach a client.
    """

    model_config = ConfigDict(extra="ignore")

    starred: bool | None = None
    # Derived on read from the log's state (never stored): live work awaits the user's approval.
    awaiting_approval: bool = Field(default=False, exclude=True)
    # The tracked todo whose chat this is: its runs execute here. Such a chat is
    # reached only from its todo, never listed (see _listed). Set once at creation.
    todo_id: str | None = None
    # Conversation-level artifact registry: one entry per agent-written file, deduped by path.
    artifacts: list[ArtifactRegistryEntry] = Field(default_factory=list)
    createdAt: str | None = None
    updatedAt: datetime | None = None

    _coerce_source = field_validator("source", mode="before")(_coerce_source)

    @property
    def listed(self) -> bool:
        """Whether the conversation list shows it: a bot chat lives on its platform, a todo's chat on its todo."""
        return self.todo_id is None and self.source not in BOT_CONVERSATION_SOURCES


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
    """A message's screen item, as the conversation's screen shows it, tagged with its conversation id."""

    conversation_id: str
    item: TextItem


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
    """The fields that say what a stored entry is and what it points at, read once from its raw fields."""

    model_config = ConfigDict(extra="ignore")

    kind: str | None = None
    reply_id: str | None = None
    task_id: str | None = None
    approval_id: str | None = None


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


class BulkWriteFault(BaseModel):
    """One failed operation of a Mongo bulk write: its position in the batch and the server's error code."""

    model_config = ConfigDict(extra="ignore")

    index: int
    code: int | None = None
    errmsg: str | None = None


class BulkWriteDetails(BaseModel):
    """The per-operation failures a BulkWriteError carries."""

    model_config = ConfigDict(extra="ignore")

    write_errors: list[BulkWriteFault] = Field(default_factory=list, alias="writeErrors")


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


class LogPage(BaseModel):
    """A run of the log's entries, oldest first, as the repository reads it.

    A page never starts inside an open span: it reaches back to the Reply, WorkStarted or
    ApprovalRequested of every settle, finish, join or decision it holds. state is the head's;
    cursor is the seq an older page is read before, set exactly when has_older.
    """

    entries: list[EntryFrame] = Field(default_factory=list)
    state: StateFrame
    has_older: bool = False
    cursor: int | None = None


class StoredConversation(ConversationDocument, LogPage):
    """A conversation as the repository reads it: its head's fields and the newest page of its log."""


class ConversationEntriesPage(ResponseModel):
    """A page of the conversation's screen, oldest first: the items its log page projects to.

    state is the head's, so a page alone shows the loading row, live work and approvals;
    cursor is the seq an older page is read before, set exactly when has_older.
    """

    items: list[ScreenItem] = Field(default_factory=list)
    state: StateFrame
    has_older: bool = False
    cursor: int | None = None


class LoadedConversation(ConversationDocument, ConversationEntriesPage):
    """A conversation as a load returns it: its head's fields and the newest page of its screen."""


class ConversationSyncRow(ConversationEntriesPage):
    """One batch-sync row: the conversation's client-visible fields, its newest page of items and its artifacts."""

    conversation_id: str
    description: str
    starred: bool | None = None
    is_system_generated: bool | None = None
    system_purpose: SystemPurpose | None = None
    is_unread: bool | None = None
    createdAt: str | None = None
    updatedAt: datetime | None = None
    # Mirrored verbatim from the document (see ConversationDocument.artifacts).
    artifacts: list[ArtifactRegistryEntry] = Field(default_factory=list)
    # Live work in the conversation awaits the user's approval: the sidebar's dot.
    awaiting_approval: bool = False
    todo_id: str | None = None
    source: ConversationSource | None = None
    # False for a chat the conversation list never shows (a todo's, a bot's): absent there is not deleted.
    listed: bool


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
