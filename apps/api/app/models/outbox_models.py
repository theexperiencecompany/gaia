"""The outbox's two collections: items (a report and where it stands) and messages (the ledger).

user_id is the recipient: shared spaces later fan a report out per recipient.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.repositories.base import UserScopedDocument
from app.services.outbox.judge_models import ItemJudgement
from app.services.outbox.models import (
    ComposeMode,
    DropReason,
    ItemFailure,
    ItemHold,
    ItemState,
    MessageState,
    OutboxReport,
    UrgencyClass,
)
from shared.py.analytics.catalog.delivery import ProactiveDestinationBasis, ProactiveDestinationKind


class OutboxItemDocument(UserScopedDocument):
    """One submitted report and its delivery state."""

    report_id: str
    report: OutboxReport
    state: ItemState = ItemState.RECEIVED
    urgency: UrgencyClass | None = None
    mode: ComposeMode | None = None
    drop_reason: DropReason | None = None
    #: What the Judge and the Rails made of the item; None for an item no Judge was asked about.
    judgement: ItemJudgement | None = None
    #: Set while the item is held, and kept after its release.
    hold: ItemHold | None = None
    failure: ItemFailure | None = None
    #: Set while a compose owns the item, and kept after, so the message it produced is findable.
    compose_attempt_id: str | None = None
    #: How many times the chat apps' broker refused a message carrying this item, which went back to the queue.
    transport_retries: int = 0
    #: How many times the recovery sweep drove the item again, and when it last did.
    recovery_attempts: int = 0
    recovered_at: datetime | None = None
    #: The report_id of the item that replaced this one.
    superseded_by: str | None = None
    expires_at: datetime
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OutboxItemUpdate(BaseModel):
    """Typed $set fields of an item; the transitions themselves are compare-and-set methods."""

    model_config = ConfigDict(extra="forbid")

    state: ItemState


class OutboxMessageDocument(UserScopedDocument):
    """One message the outbox composed for a user: what was said, to whom, where, and what became of it."""

    compose_attempt_id: str
    report_ids: list[str]
    state: MessageState = MessageState.SENDING
    mode: ComposeMode
    max_class: UrgencyClass
    parts: list[str]
    degraded: bool = False
    destination: ProactiveDestinationKind
    destination_basis: ProactiveDestinationBasis
    #: The conversation the alert went to.
    conversation_id: str
    #: Every conversation the message was recorded in, the alert's first.
    recorded_in: list[str]
    sent_at: datetime | None = None
    expires_at: datetime
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OutboxMessageUpdate(BaseModel):
    """Typed $set fields of a message."""

    model_config = ConfigDict(extra="forbid")

    state: MessageState
