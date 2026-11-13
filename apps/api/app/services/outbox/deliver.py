"""Deliver: claim a subject's queued items, compose them, and send the message exactly once.

The state machine lives in Mongo, not in locks. An item moves queued -> composing ->
sending -> sent|failed, each step a conditional write, so of two flushers only one
claims an item. Before any speech transport the message's ledger row is inserted
under a unique (user, compose attempt); the transport runs only for the insert that
won. A per-user Redis lock only saves the second flusher a compose.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.constants.log_tags import LogTag
from app.constants.outbox import (
    DEFAULT_LOCALE,
    OUTBOX_MESSAGE_RETENTION_SECONDS,
    OUTBOX_TRANSPORT_MAX_RETRIES,
    OUTBOX_TRANSPORT_RETRY_DELAY_SECONDS,
    OUTBOX_USER_LOCK_ACQUIRE_TIMEOUT_SECONDS,
    OUTBOX_USER_LOCK_LEASE_SECONDS,
    OUTBOX_USER_LOCK_MAX_HOLD_SECONDS,
    OUTBOX_USER_LOCK_PREFIX,
    OUTBOX_USER_LOCK_RENEW_SECONDS,
)
from app.constants.websocket import ReportSettledOutcome
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.outbox_items import outbox_items_repository
from app.db.repositories.outbox_messages import outbox_messages_repository
from app.models.chat_models import MessageModel, UpdateMessagesRequest
from app.models.outbox_models import OutboxItemDocument, OutboxMessageDocument
from app.models.user_models import AuthenticatedUser
from app.schemas.outbound import OutboundAttachment
from app.services.analytics_service import capture
from app.services.conversation_service import update_messages
from app.services.outbox import compose as compose_module
from app.services.outbox.approvals import approval_id_of_report, is_approval_open
from app.services.outbox.compose import Composed
from app.services.outbox.flush_queue import schedule_flush
from app.services.outbox.judge_models import PRIVATE_SENSITIVITIES
from app.services.outbox.metrics import (
    OUTBOX_ATTACHMENTS_FAILED,
    OUTBOX_ITEMS_DROPPED,
    OUTBOX_ITEMS_FAILED,
    OUTBOX_TRANSPORT_RETRIES,
)
from app.services.outbox.models import (
    ComposeMode,
    DropReason,
    ItemFailure,
    ItemState,
    MessageState,
    NoticeReport,
    UrgencyClass,
)
from app.services.outbox.prerendered import PrerenderedKind, prerendered_text
from app.services.outbox.router import (
    ChatChannel,
    InApp,
    NoDestinationError,
    Route,
    destination_of,
    route,
)
from app.services.outbox.settled import announce_attempt_settled, announce_items_settled
from app.services.outbox.transport.bot_queue import (
    OutboundResult,
    publish_outbound_file,
    publish_outbound_message,
    publish_outbound_photo,
)
from app.services.outbox.transport.push import push_approval_pending
from app.services.outbox.transport.voice import publish_spoken
from app.services.outbox.transport.ws_speech import publish_conversation_message
from app.utils import clock
from app.utils.auth_utils import load_user_context
from app.utils.redis_lock import DistributedLock
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.delivery import DeliveryMessageSent
from shared.py.wide_events import log


class OutboxUserNotFoundError(RuntimeError):
    """A report names a recipient that is not a user: there is no one to tell."""


#: A message's text is its part 0; its attachments are the parts after it.
TEXT_PART_COUNT = 1


class OutboxBrokerUnavailableError(RuntimeError):
    """The chat apps' broker took none of a message: it goes back to the queue and is flushed again."""


def locale_of(user: AuthenticatedUser) -> str:
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


def _preview_is_safe(item: OutboxItemDocument) -> bool:
    """Whether the Judge read the item and found it fit for a lock screen: an unjudged item is not."""
    judgement = item.judgement
    return (
        judgement is not None
        and judgement.verdict is not None
        and judgement.sensitivity not in PRIVATE_SENSITIVITIES
    )


def _push_body(included: list[OutboxItemDocument], composed: Composed, locale: str) -> str:
    """Return the text a push may show on a lock screen: the first bubble, only when every item was judged fit to preview."""
    if not all(_preview_is_safe(item) for item in included):
        return prerendered_text(PrerenderedKind.GENERIC_PREVIEW, locale)
    return composed.parts[0] if composed.parts else ""


async def _save_messages(
    conversation_id: str, user: AuthenticatedUser, parts: list[str]
) -> list[MessageModel]:
    messages = [
        MessageModel(type="bot", response=part, date=datetime.now(UTC).isoformat())
        for part in parts
    ]
    if not messages:
        return messages
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
    await announce_attempt_settled(user_id, attempt_id, ReportSettledOutcome.FAILED)
    log.error(
        f"{LogTag.NOTIFICATION} Outbox message not delivered",
        user_id=user_id,
        compose_attempt_id=attempt_id,
        failure=failure.value,
    )


async def _publish_attachment(
    target: ChatChannel,
    user_id: str,
    attachment: OutboundAttachment,
    *,
    attempt_id: str,
    part_index: int,
) -> bool:
    """Hand one file to the chat app's queue under its ledger message: a photo the bot fetches by URL, or an artifact by reference."""
    if attachment.url is not None:
        return await publish_outbound_photo(
            target.source,
            user_id,
            attachment.url,
            attachment.filename,
            attachment.caption,
            outbox_message_id=attempt_id,
            part_index=part_index,
        )
    if attachment.conversation_id is not None and attachment.path is not None:
        return await publish_outbound_file(
            target.source,
            user_id,
            attachment.conversation_id,
            attachment.path,
            attachment.filename,
            content_type=attachment.content_type,
            caption=attachment.caption,
            outbox_message_id=attempt_id,
            part_index=part_index,
        )
    raise ValueError("an outbound attachment names a URL or an artifact")


@dataclass(frozen=True, slots=True)
class _SentAs:
    """What a message is delivered as: the ledger message it is, the approval it asks about, what a lock screen shows."""

    attempt_id: str
    approval_id: str | None
    push_body: str


@dataclass(frozen=True, slots=True)
class _ChatAppDelivery:
    """What a chat app's queue took of a message: why none of it landed, and what the thread is to hold of it."""

    failure: ItemFailure | None
    thread_notes: list[str]


def _file_note(label: str, attachment: OutboundAttachment) -> str:
    """Name a file in the thread, with where it is kept when it is an artifact."""
    kept = f" (artifact {attachment.path})" if attachment.path is not None else ""
    return f"[{label}: {attachment.filename}{kept}]"


async def _degrade_attachment(
    target: ChatChannel, user_id: str, attachment: OutboundAttachment
) -> str | None:
    """Say an attachment the chat app's queue refused as its caption; return the caption told, None when it has none or that fails too."""
    OUTBOX_ATTACHMENTS_FAILED.inc()
    log.error(
        f"{LogTag.NOTIFICATION} Outbox attachment not delivered",
        user_id=user_id,
        platform=target.source.value,
        has_caption=attachment.caption is not None,
    )
    if attachment.caption is None:
        return None
    told = await publish_outbound_message(
        target.source,
        user_id,
        [attachment.caption],
        destination_override=target.platform_user_id,
    )
    return attachment.caption if told is OutboundResult.PUBLISHED else None


async def _deliver_to_chat_app(
    target: ChatChannel, user_id: str, composed: Composed, attempt_id: str
) -> _ChatAppDelivery:
    """Hand the message to the chat app's queue; return why none of it landed (None when something did) and the file notes for the thread.

    A refused attachment degrades to its caption and never undoes the text before it.
    Raises OutboxBrokerUnavailableError when the broker took none of the text; a publish that failed
    midway may still have been taken, so it is not resent and fails the item.
    """
    if composed.parts:
        result = await publish_outbound_message(
            target.source,
            user_id,
            composed.parts,
            destination_override=target.platform_user_id,
            ttl_seconds=composed.ttl_seconds,
            outbox_message_id=attempt_id,
        )
        if result is OutboundResult.BROKER_UNAVAILABLE:
            raise OutboxBrokerUnavailableError(user_id)
        if result is OutboundResult.FAILED:
            return _ChatAppDelivery(ItemFailure.TRANSPORT_FAILED, [])
        if result is OutboundResult.SKIPPED:
            return _ChatAppDelivery(ItemFailure.TRANSPORT_SKIPPED, [])
    delivered = bool(composed.parts)
    notes: list[str] = []
    for part_index, attachment in enumerate(composed.attachments, start=TEXT_PART_COUNT):
        if await _publish_attachment(
            target, user_id, attachment, attempt_id=attempt_id, part_index=part_index
        ):
            delivered = True
            notes.append(_file_note("Attached file", attachment))
            continue
        notes.append(_file_note("File not delivered", attachment))
        caption = await _degrade_attachment(target, user_id, attachment)
        if caption is not None:
            delivered = True
            notes.append(caption)
    failed = not delivered and bool(composed.attachments)
    return _ChatAppDelivery(ItemFailure.TRANSPORT_FAILED if failed else None, notes)


async def _alert_in_app(
    user_id: str,
    destination: Route,
    saved: dict[str, list[MessageModel]],
    sent: _SentAs,
    has_text: bool,
) -> None:
    """Show the recorded message in the app, and say it in the user's live call; an approval's ask also pushes to a backgrounded phone."""
    messages = saved[destination.alert_conversation_id]
    for message in messages:
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
    target = destination.target
    if isinstance(target, InApp) and target.call_room is not None and has_text:
        await publish_spoken(
            target.call_room, sent.attempt_id, [message.response for message in messages]
        )
    if sent.approval_id is not None and has_text:
        await push_approval_pending(
            user_id, destination.alert_conversation_id, sent.approval_id, sent.push_body
        )


async def _hand_back_for_retry(user_id: str, attempt_id: str) -> None:
    """Return a message the broker took none of to the queue and flush it again shortly, whatever job sent it.

    The flush finds the items by their refusal count, so a message that joined several subjects is
    composed and sent again whole.
    """
    await outbox_items_repository.release_sending(user_id, attempt_id)
    await outbox_messages_repository.finish_send(user_id, attempt_id, MessageState.FAILED)
    await schedule_flush(
        user_id, clock.now() + timedelta(seconds=OUTBOX_TRANSPORT_RETRY_DELAY_SECONDS)
    )
    OUTBOX_TRANSPORT_RETRIES.inc()
    log.warning(
        f"{LogTag.NOTIFICATION} Chat apps' broker refused the message; handed back for a retry",
        user_id=user_id,
        compose_attempt_id=attempt_id,
    )


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

    target = destination.target
    failure: ItemFailure | None = None
    notes: list[str] = []
    if isinstance(target, ChatChannel):
        try:
            delivery = await _deliver_to_chat_app(target, user_id, composed, attempt_id)
        except OutboxBrokerUnavailableError:
            await _hand_back_for_retry(user_id, attempt_id)
            return
        failure, notes = delivery.failure, delivery.thread_notes
    # A chat app's own chat is recorded only when that chat app got the message.
    recorded_in = (
        destination.recorded_in
        if not isinstance(target, ChatChannel) or failure is None
        else destination.recorded_in[1:]
    )
    try:
        saved = {
            conversation_id: await _save_messages(conversation_id, user, composed.parts)
            for conversation_id in recorded_in
        }
        # Recorded where it was asked, not alerted there: the chat shows it as unread.
        if composed.parts:
            for conversation_id in destination.recorded_in[1:]:
                await conversation_repository.set_unread(
                    conversation_id, user_id=user_id, unread=True
                )
    except Exception:
        await _fail_items(user_id, attempt_id, ItemFailure.RECORD_FAILED)
        raise
    if not isinstance(target, ChatChannel):
        await _alert_in_app(
            user_id,
            destination,
            saved,
            _SentAs(
                attempt_id=attempt_id,
                approval_id=next(
                    (
                        approval_id
                        for item in included
                        if (approval_id := approval_id_of_report(item.report_id)) is not None
                    ),
                    None,
                ),
                push_body=_push_body(included, composed, locale_of(user)),
            ),
            has_text=bool(composed.parts),
        )
    if failure is not None:
        await _fail_items(user_id, attempt_id, failure)
    else:
        await _settle_sent(user_id, attempt_id, message, included)

    # A chat app's thread holds only what that chat app received; a file it did not take is noted as
    # not delivered, so the thread can answer "send it".
    thread_parts = [*composed.parts, *notes]
    if thread_parts:
        thread_text = "\n\n".join(thread_parts)
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
    await announce_items_settled(
        included,
        ReportSettledOutcome.DELIVERED_HERE
        if message.destination == "in_app"
        else ReportSettledOutcome.DELIVERED_ELSEWHERE,
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


async def _drop_expired(
    user_id: str, attempt_id: str, items: list[OutboxItemDocument]
) -> list[OutboxItemDocument]:
    """Record the items whose valid_until has passed and never tell them; return the ones still worth telling."""
    now = clock.now()
    expired = [
        item.report_id
        for item in items
        if isinstance(item.report, NoticeReport)
        and item.report.valid_until is not None
        and item.report.valid_until <= now
    ]
    if not expired:
        return items
    dropped = await outbox_items_repository.drop_composing(
        user_id, attempt_id, expired, DropReason.EXPIRED
    )
    OUTBOX_ITEMS_DROPPED.labels(reason=DropReason.EXPIRED.value).inc(dropped)
    return [item for item in items if item.report_id not in expired]


async def _drop_answered_approvals(
    user_id: str, attempt_id: str, items: list[OutboxItemDocument]
) -> list[OutboxItemDocument]:
    """Record the approval asks the user can no longer answer and never tell them; return the rest."""
    moot = [
        item.report_id
        for item in items
        if (approval_id := approval_id_of_report(item.report_id)) is not None
        and not await is_approval_open(approval_id)
    ]
    if not moot:
        return items
    dropped = await outbox_items_repository.drop_composing(
        user_id, attempt_id, moot, DropReason.MOOT
    )
    OUTBOX_ITEMS_DROPPED.labels(reason=DropReason.MOOT.value).inc(dropped)
    return [item for item in items if item.report_id not in moot]


async def _flush(
    user: AuthenticatedUser, claim: Callable[[str], Awaitable[list[OutboxItemDocument]]]
) -> None:
    attempt_id = str(uuid4())
    items = await claim(attempt_id)
    if not items:
        log.info(
            f"{LogTag.NOTIFICATION} Outbox subject has nothing queued; another flusher took it",
            user_id=user.user_id,
        )
        return
    try:
        items = await _drop_expired(user.user_id, attempt_id, items)
        items = await _drop_answered_approvals(user.user_id, attempt_id, items)
        if not items:
            return
        destination = await route(
            user,
            items,
            chat_apps_down=max(item.transport_retries for item in items)
            >= OUTBOX_TRANSPORT_MAX_RETRIES,
        )
        composed = await compose_module.compose(
            items,
            user_id=user.user_id,
            mode=_mode_of(items),
            destination=destination,
            locale=locale_of(user),
        )
        if composed.skipped:
            dropped = await outbox_items_repository.drop_composing(
                user.user_id, attempt_id, composed.skipped, composed.skip_reason
            )
            OUTBOX_ITEMS_DROPPED.labels(reason=composed.skip_reason.value).inc(dropped)
            await announce_items_settled(
                [item for item in items if item.report_id in composed.skipped],
                ReportSettledOutcome.RECORDED,
            )
        if composed.included:
            await _send(user, items, destination, composed, attempt_id)
    except NoDestinationError:
        await outbox_items_repository.fail_composing(
            user.user_id, attempt_id, ItemFailure.NO_DESTINATION
        )
        OUTBOX_ITEMS_FAILED.labels(reason=ItemFailure.NO_DESTINATION.value).inc()
        await announce_attempt_settled(user.user_id, attempt_id, ReportSettledOutcome.FAILED)
        log.error(
            f"{LogTag.NOTIFICATION} Outbox message has nowhere to go; the user has no app conversation",
            user_id=user.user_id,
        )
    except BaseException:
        await outbox_items_repository.release_composing(user.user_id, attempt_id)
        raise


async def _flush_claimed(
    user_id: str, claim: Callable[[str], Awaitable[list[OutboxItemDocument]]]
) -> None:
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
        await _flush(user, claim)


async def flush_subject(user_id: str, subject_id: str) -> None:
    """Tell the user everything queued for one subject, as one message.

    Raises OutboxUserNotFoundError when user_id is no user. Items a failed step left
    composing go back to the queue for the job's retry; items already sending stay,
    since a text that may have gone out is never resent.
    """
    await _flush_claimed(
        user_id,
        lambda attempt_id: outbox_items_repository.claim_queued_for_subject(
            user_id, subject_id, attempt_id
        ),
    )


async def flush_items(user_id: str, report_ids: list[str]) -> None:
    """Tell the queued ones among the named reports as one message, whatever their subjects.

    Raises OutboxUserNotFoundError when user_id is no user. Items another flusher claimed
    are not in it.
    """
    await _flush_claimed(
        user_id,
        lambda attempt_id: outbox_items_repository.claim_queued(user_id, report_ids, attempt_id),
    )
