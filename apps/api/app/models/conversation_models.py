"""Persistence-side models for the ``conversations`` collection.

These are distinct from the API request/response models in ``chat_models`` — they
describe the document as it is actually stored and read back. The embedded
``messages`` array reuses ``MessageModel``; a before-validator runs the legacy
tool-data normalization at the read boundary so the rest of the app never sees an
un-normalized message.

Timestamps are the legacy camelCase pair: ``createdAt`` is an ISO string written
at insert time, ``updatedAt`` is a BSON date bumped via ``$currentDate`` on every
write. They are intentionally NOT the base's stamped snake_case ``created_at`` /
``updated_at`` — normalizing them to the standard pair is a tracked follow-up, so
the repository bumps ``updatedAt`` explicitly on each write rather than relying on
the base's auto-stamp.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.repositories.base import UserScopedDocument
from app.models.chat_models import ConversationSource, MessageModel, SystemPurpose
from app.utils.tool_data_utils import convert_legacy_tool_data


def _normalize_messages(value: object) -> object:
    """Run legacy per-tool-field → unified ``tool_data`` conversion on each message."""
    if isinstance(value, list):
        return [convert_legacy_tool_data(m) if isinstance(m, dict) else m for m in value]
    return value


def _coerce_source(value: object) -> object:
    """Map a stored source string to the enum, tolerating unknown legacy values."""
    if isinstance(value, (ConversationSource, str)):
        return ConversationSource.coerce(value)
    return value


class ConversationDocument(UserScopedDocument):
    """A conversation and its embedded message history as stored in MongoDB.

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
    is_onboarding_conversation: bool | None = None
    starred: bool | None = None
    messages: list[MessageModel] = Field(default_factory=list)
    # Conversation-level artifact registry: one entry per agent-written file,
    # deduped by path. Kept as raw dicts — the element shape is owned by
    # services/chat/artifacts_registry.py and mirrored verbatim to the client.
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    createdAt: str | None = None
    updatedAt: datetime | None = None

    _normalize_messages = field_validator("messages", mode="before")(_normalize_messages)
    _coerce_source = field_validator("source", mode="before")(_coerce_source)


class ConversationUpdate(BaseModel):
    """Typed ``$set`` fields for a conversation. The repository bumps ``updatedAt``
    itself, so it is not part of the update surface."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    starred: bool | None = None
    is_unread: bool | None = None


class ConversationSummary(BaseModel):
    """The projected conversation-list row — every field the web list consumes,
    without the heavy ``messages`` array."""

    model_config = ConfigDict(extra="allow")

    conversation_id: str
    user_id: str
    description: str | None = None
    starred: bool | None = None
    is_system_generated: bool | None = None
    is_onboarding_conversation: bool | None = None
    system_purpose: SystemPurpose | None = None
    is_unread: bool | None = None
    source: ConversationSource | None = None
    createdAt: str | None = None
    updatedAt: datetime | None = None

    _coerce_source = field_validator("source", mode="before")(_coerce_source)


class ConversationMessageHit(BaseModel):
    """A single conversation message tagged with its conversation id — the shape of
    the pinned-messages and message-search results."""

    conversation_id: str
    message: MessageModel

    @field_validator("message", mode="before")
    @classmethod
    def _normalize_message(cls, value: object) -> object:
        return convert_legacy_tool_data(value) if isinstance(value, dict) else value


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


class _ConversationIdRow(BaseModel):
    """Projection of just a conversation id (owner lookups)."""

    model_config = ConfigDict(extra="ignore")

    conversation_id: str


class _MessageProjectionRow(BaseModel):
    """Positional ``messages.$`` projection — a one-element messages slice."""

    model_config = ConfigDict(extra="ignore")

    messages: list[MessageModel] = Field(default_factory=list)


class _OnboardingProbeRow(BaseModel):
    """Projection for the onboarding-demo prompt gate: the flag plus message list."""

    model_config = ConfigDict(extra="ignore")

    is_onboarding_conversation: bool | None = None
    messages: list[MessageModel] = Field(default_factory=list)

    @field_validator("messages", mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        return _normalize_messages(value)


class OnboardingProbe(BaseModel):
    """The onboarding-demo gate result: whether this is the demo conversation and
    how many messages it holds."""

    is_onboarding_conversation: bool | None = None
    message_count: int = 0
