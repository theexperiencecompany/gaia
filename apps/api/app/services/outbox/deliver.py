"""Deliver: claim a subject's queued items, compose them, and send the message exactly once.

The state machine lives in Mongo, not in locks. An item moves queued -> composing ->
sending -> sent|failed, each step a conditional write, so of two flushers only one
claims an item. Before any speech transport the message's ledger row is inserted
under a unique (user, compose attempt); the transport runs only for the insert that
won. A per-user Redis lock only saves the second flusher a compose.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.constants.log_tags import LogTag
from app.constants.outbox import (
    DEFAULT_LOCALE,
    OUTBOX_MESSAGE_RETENTION_SECONDS,
    OUTBOX_USER_LOCK_ACQUIRE_TIMEOUT_SECONDS,
    OUTBOX_USER_LOCK_LEASE_SECONDS,
    OUTBOX_USER_LOCK_MAX_HOLD_SECONDS,
    OUTBOX_USER_LOCK_PREFIX,
    OUTBOX_USER_LOCK_RENEW_SECONDS,
)
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.outbox_items import outbox_items_repository
from app.db.repositories.outbox_messages import outbox_messages_repository
from app.models.chat_models import MessageModel, UpdateMessagesRequest
from app.models.outbox_models import OutboxItemDocument, OutboxMessageDocument
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import capture
from app.services.conversation_service import update_messages
from app.services.outbox import compose as compose_module
from app.services.outbox.compose import Composed
from app.services.outbox.metrics import OUTBOX_ITEMS_DROPPED, OUTBOX_ITEMS_FAILED
from app.services.outbox.models import (
    ComposeMode,
    DropReason,
    ItemFailure,
    ItemState,
    MessageState,
    UrgencyClass,
)
from app.services.outbox.router import ChatChannel, NoDestinationError, Route, destination_of, route
from app.services.outbox.transport.bot_queue import OutboundResult, publish_outbound_message
from app.services.outbox.transport.ws_speech import publish_conversation_message
from app.utils import clock
from app.utils.auth_utils import load_user_context
from app.utils.redis_lock import DistributedLock
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.delivery import DeliveryMessageSent
from shared.py.wide_events import log


class OutboxUserNotFoundError(RuntimeError):
    """A report names a recipient that is not a user: there is no one to tell."""


def _locale_of(user: AuthenticatedUser) -> str:
    preferences = user.onboarding.preferences if user.onboarding is not None else None
    language = preferences.language if preferences is not None else None
    return language or DEFAULT_LOCALE


def _mode_of(items: list[OutboxItemDocument]) -> ComposeMode:
    modes = {item.mode for item in items}
    for mode in (ComposeMode.INTERRUPT, ComposeMode.ANSWER):
        if mode in modes:
            return mode
    return ComposeMode.UNSOLICITED


def _max_class(items: list[OutboxItemDocument]) -> UrgencyClass:
    return max(
        (item.urgency for item in items if item.urgency is not None), default=UrgencyClass.ROUTINE
    )


async def _save_messages(
    conversation_id: str, user: AuthenticatedUser, parts: list[str]
) -> list[MessageModel]:
    messages = [
        MessageModel(type="bot", response=part, date=datetime.now(UTC).isoformat())
        for part in parts
    ]
    for message in messages:
        message.message_id = str(uuid4())
    await update_messages(
        UpdateMessagesRequest(conversation_id=conversation_id, messages=messages), user=user
    )
    return messages


async def _fail_items(user_id: str, attempt_id: str, failure: ItemFailure) -> None:
    await outbox_items_repository.finish_send(user_id, attempt_id, ItemState.FAILED, failure)
    await outbox_messages_repository.finish_send(user_id, attempt_id, MessageState.FAILED)
    OUTBOX_ITEMS_FAILED.labels(reason=failure.value).inc()
    log.error(
        f"{LogTag.NOTIFICATION} Outbox message not delivered",
        user_id=user_id,
        compose_attempt_id=attempt_id,
        failure=failure.value,
    )


async def _alert(
    user_id: str, destination: Route, parts: list[str], saved: dict[str, list[MessageModel]]
) -> ItemFailure | None:
    """Alert the one destination; return why it did not land, or None when it did."""
    target = destination.target
    if isinstance(target, ChatChannel):
        result = await publish_outbound_message(
            target.source, user_id, parts, destination_override=target.platform_user_id
        )
        if result is OutboundResult.PUBLISHED:
            return None
        return (
            ItemFailure.TRANSPORT_SKIPPED
            if result is OutboundResult.SKIPPED
            else ItemFailure.TRANSPORT_FAILED
        )
    for message in saved[destination.alert_conversation_id]:
        await publish_conversation_message(
            user_id,
            destination.alert_conversation_id,
            {
                "type": "bot",
                "response": message.response,
                "message_id": message.message_id,
                "date": message.date,
                "kind": message.kind.value,
            },
        )
    return None


async def _send(
    user: AuthenticatedUser,
    items: list[OutboxItemDocument],
    destination: Route,
    composed: Composed,
    attempt_id: str,
) -> None:
    """Record, alert and settle one composed message; the attempt's items are composing on entry."""
    user_id = user.user_id
    included = [item for item in items if item.report_id in composed.included]
    destination_kind, destination_basis = destination_of(destination.target)
    message = OutboxMessageDocument(
        user_id=user_id,
        compose_attempt_id=attempt_id,
        report_ids=[item.report_id for item in included],
        mode=_mode_of(included),
        max_class=_max_class(included),
        parts=composed.parts,
        degraded=composed.degraded,
        destination=destination_kind,
        destination_basis=destination_basis,
        conversation_id=destination.alert_conversation_id,
        recorded_in=list(destination.recorded_in),
        expires_at=clock.now() + timedelta(seconds=OUTBOX_MESSAGE_RETENTION_SECONDS),
    )
    if not await outbox_messages_repository.insert_attempt(message):
        log.error(
            f"{LogTag.NOTIFICATION} Outbox ledger already holds this compose attempt; not sending",
            user_id=user_id,
            compose_attempt_id=attempt_id,
        )
        return
    if await outbox_items_repository.begin_send(user_id, attempt_id) != len(included):
        await _fail_items(user_id, attempt_id, ItemFailure.TRANSPORT_FAILED)
        return

    try:
        saved = {
            conversation_id: await _save_messages(conversation_id, user, composed.parts)
            for conversation_id in destination.recorded_in
        }
        # Recorded where it was asked, not alerted there: the chat shows it as unread.
        for conversation_id in destination.recorded_in[1:]:
            await conversation_repository.set_unread(conversation_id, user_id=user_id, unread=True)
    except Exception:
        await _fail_items(user_id, attempt_id, ItemFailure.RECORD_FAILED)
        raise
    failure = await _alert(user_id, destination, composed.parts, saved)
    if failure is not None:
        await _fail_items(user_id, attempt_id, failure)
    else:
        await _settle_sent(user_id, attempt_id, message, included)

    # A chat app's thread holds only what that chat app received.
    thread_text = "\n\n".join(composed.parts)
    for conversation_id in destination.recorded_in:
        if failure is None or conversation_id != destination.alert_conversation_id:
            await compose_module.record_in_thread(conversation_id, thread_text)


async def _settle_sent(
    user_id: str,
    attempt_id: str,
    message: OutboxMessageDocument,
    included: list[OutboxItemDocument],
) -> None:
    sent_at = clock.now()
    await outbox_items_repository.finish_send(user_id, attempt_id, ItemState.SENT)
    await outbox_messages_repository.finish_send(
        user_id, attempt_id, MessageState.SENT, sent_at=sent_at
    )
    first = included[0].report
    capture(
        UserId(user_id),
        DeliveryMessageSent(
            producer=first.producer.value,
            subject_kind=first.subject.kind.value,
            mode=message.mode.value,
            destination=message.destination,
            destination_basis=message.destination_basis,
            items_count=len(included),
            max_class=message.max_class.name.lower(),
            degraded=message.degraded,
        ),
        Dedupe(key=attempt_id, occurred_at=sent_at),
    )
    log.info(
        f"{LogTag.NOTIFICATION} Outbox message sent",
        user_id=user_id,
        compose_attempt_id=attempt_id,
        items=len(included),
        destination=message.destination,
    )


async def _flush(user: AuthenticatedUser, subject_id: str) -> None:
    attempt_id = str(uuid4())
    items = await outbox_items_repository.claim_queued_for_subject(
        user.user_id, subject_id, attempt_id
    )
    if not items:
        log.info(
            f"{LogTag.NOTIFICATION} Outbox subject has nothing queued; another flusher took it",
            user_id=user.user_id,
        )
        return
    try:
        destination = await route(user, items)
        composed = await compose_module.compose(
            items,
            user_id=user.user_id,
            mode=_mode_of(items),
            target=destination.target,
            conversation_id=destination.alert_conversation_id,
            locale=_locale_of(user),
        )
        if composed.skipped:
            dropped = await outbox_items_repository.drop_composing(
                user.user_id, attempt_id, composed.skipped, DropReason.COMPOSE_SKIPPED
            )
            OUTBOX_ITEMS_DROPPED.labels(reason=DropReason.COMPOSE_SKIPPED.value).inc(dropped)
        if composed.included:
            await _send(user, items, destination, composed, attempt_id)
    except NoDestinationError:
        await outbox_items_repository.fail_composing(
            user.user_id, attempt_id, ItemFailure.NO_DESTINATION
        )
        OUTBOX_ITEMS_FAILED.labels(reason=ItemFailure.NO_DESTINATION.value).inc()
        log.error(
            f"{LogTag.NOTIFICATION} Outbox message has nowhere to go; the user has no app conversation",
            user_id=user.user_id,
        )
    except BaseException:
        await outbox_items_repository.release_composing(user.user_id, attempt_id)
        raise


async def flush_subject(user_id: str, subject_id: str) -> None:
    """Tell the user everything queued for one subject, as one message.

    Raises OutboxUserNotFoundError when user_id is no user. Items a failed step left
    composing go back to the queue for the job's retry; items already sending stay,
    since a text that may have gone out is never resent.
    """
    user = await load_user_context(user_id)
    if user is None:
        raise OutboxUserNotFoundError(user_id)
    lock = DistributedLock(
        f"{OUTBOX_USER_LOCK_PREFIX}{user_id}",
        lease_seconds=OUTBOX_USER_LOCK_LEASE_SECONDS,
        acquire_timeout_seconds=OUTBOX_USER_LOCK_ACQUIRE_TIMEOUT_SECONDS,
        renew_seconds=OUTBOX_USER_LOCK_RENEW_SECONDS,
        max_hold_seconds=OUTBOX_USER_LOCK_MAX_HOLD_SECONDS,
    )
    # Not holding it is fine: the compare-and-set on the items decides who sends.
    async with lock.hold():
        await _flush(user, subject_id)
