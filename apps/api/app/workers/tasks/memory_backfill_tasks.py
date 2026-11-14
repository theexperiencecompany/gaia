"""Daily backfill of long-term memory for users who predate the memory engine.

Users created before the live memory pipeline shipped have conversation history
that never went through memory_node. A daily cron (backfill_active_users)
scans for active (ActivityStatus.ACTIVE), pre-launch, not-yet-backfilled users and enqueues a
per-user job (backfill_user_memories) that replays their conversations
through memory_engine.retain and notifies them once their memory is ready.

The memory_backfilled marker makes the whole thing idempotent and, as a
free side effect, picks up users who only just became active again: when a
dormant account comes back from any surface its last_active_at is bumped, so
the next cron run sees it as eligible and backfills it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from app.constants.memory import (
    MEMORY_BACKFILL_ELIGIBLE_BEFORE,
    MEMORY_BACKFILL_MAX_CONVERSATIONS,
    MEMORY_BACKFILL_MAX_USERS_PER_RUN,
    MemorySourceType,
)
from app.constants.notifications import MEMORY_SETTINGS_URL
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.users import user_repository
from app.memory.consolidation import cancel_consolidation
from app.memory.engine import memory_engine
from app.models.conversation_models import ConversationDocument
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
    RedirectConfig,
)
from app.services.notification_service import notification_service
from app.utils.redis_utils import RedisPoolManager
from app.utils.timezone import as_utc
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import MemoryContext, UserContext, log

_BACKFILL_TASK = "backfill_user_memories"


async def backfill_active_users(ctx: Mapping[str, object]) -> str:  # noqa: ARG001 -- contract
    """Daily cron: enqueue a memory backfill for eligible users, capped per run.

    Capping per run drains the backlog gradually instead of spiking the
    extraction LLM; the marker means the next run resumes with whoever is left
    (plus anyone who became active in the meantime).
    """
    remaining = await user_repository.count_backfill_candidates(MEMORY_BACKFILL_ELIGIBLE_BEFORE)
    candidate_ids = await user_repository.find_backfill_candidate_ids(
        MEMORY_BACKFILL_ELIGIBLE_BEFORE, limit=MEMORY_BACKFILL_MAX_USERS_PER_RUN
    )

    pool = await RedisPoolManager.get_pool()
    enqueued = 0
    for user_id in candidate_ids:
        # Deterministic job id: a user already queued/running is not
        # re-enqueued by an overlapping cron run.
        job = await enqueue_worker_job(
            pool, _BACKFILL_TASK, user_id, _job_id=f"membackfill:{user_id}"
        )
        if job is not None:
            enqueued += 1

    log.set(eligible_remaining=remaining, enqueued=enqueued)
    return f"memory backfill: enqueued {enqueued}, {max(remaining - enqueued, 0)} still pending"


async def backfill_user_memories(ctx: Mapping[str, object], user_id: str) -> str:  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    """Replay one user's conversations into memory, then notify them.

    Idempotent: re-checks the marker, and the engine's reconciliation dedups
    facts, so a retry never double-stores. The marker is set even on a zero-fact
    no-op so the cron won't keep re-selecting the user.
    """
    log.set(user=UserContext(id=user_id))
    user = await user_repository.get(user_id)
    if user is None or user.memory_backfilled is not None:
        log.set(skipped=True)
        return f"skip {user_id}: missing or already backfilled"

    user_name = user.name or "the user"
    # Most-recent conversations, replayed oldest-first so journal dates and
    # recency-based reconciliation land on the right days.
    conversations = await conversation_repository.recent_for_user(
        user_id, limit=MEMORY_BACKFILL_MAX_CONVERSATIONS
    )
    conversations.reverse()

    facts = 0
    processed = 0
    for conversation in conversations:
        messages = _conversation_to_messages(conversation)
        if not messages:
            continue
        result = await memory_engine.retain(
            user_id,
            messages,
            source_type=MemorySourceType.CONVERSATION,
            source_id=conversation.conversation_id,
            user_name=user_name,
            now=_conversation_date(conversation),
        )
        facts += result.facts_extracted
        processed += 1

    if processed:
        # Each retain only scheduled a debounced (120s) consolidation; cancel it
        # and run inline so memory is ready before notify, and the result
        # survives a worker restart that would otherwise drop the debounced pass.
        await cancel_consolidation(user_id)
        last_day = max(_conversation_date(conversation).date() for conversation in conversations)
        await memory_engine.summarize_episode(user_id, last_day)
        await memory_engine.consolidate(user_id)

    await user_repository.mark_memory_backfilled(user_id)
    log.set(
        memory=MemoryContext(operation="retain", facts_extracted=facts, result_count=facts),
        conversations=processed,
    )

    # Only tell the user when something was actually learned — a 0-fact
    # no-op shouldn't surface a "we organized your memories" message.
    if facts > 0:
        await _notify_memory_ready(user_id)

    return f"backfilled {user_id}: {processed} conversations, {facts} facts"


def _conversation_to_messages(conversation: ConversationDocument) -> list[dict[str, str]]:
    """Map a stored conversation's embedded messages to extraction format."""
    role_map = {"user": "user", "bot": "assistant"}
    messages: list[dict[str, str]] = []
    for msg in conversation.messages:
        role = role_map.get(msg.type)
        content = msg.response.strip()
        if role and content:
            messages.append({"role": role, "content": content})
    return messages


def _conversation_date(conversation: ConversationDocument) -> datetime:
    """Best-effort original timestamp so replayed facts land on the right day."""
    created_at = conversation.createdAt
    try:
        stamp = datetime.fromisoformat(created_at) if created_at else conversation.updatedAt
    except ValueError:
        stamp = conversation.updatedAt
    return as_utc(stamp) or datetime.now(UTC)


async def _notify_memory_ready(user_id: str) -> None:
    """Tell the user their memory was just seeded, linking to the memory page."""
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                type=NotificationType.INFO,
                priority=2,
                content=NotificationContent(
                    title="Your memory is ready",
                    body=(
                        "GAIA just organized memories from your past conversations — it now "
                        "remembers your context, preferences, and the people you mention. "
                        "Review or edit anything anytime."
                    ),
                    actions=[
                        NotificationAction(
                            type=ActionType.REDIRECT,
                            label="View memories",
                            style=ActionStyle.PRIMARY,
                            config=ActionConfig(
                                redirect=RedirectConfig(
                                    url=MEMORY_SETTINGS_URL,
                                    open_in_new_tab=False,
                                    close_notification=True,
                                )
                            ),
                        )
                    ],
                ),
                metadata={"source": "memory_backfill"},
            )
        )
    except Exception as e:
        log.warning("memory_backfill.notification_failed", user_id=user_id, error=str(e)[:200])
