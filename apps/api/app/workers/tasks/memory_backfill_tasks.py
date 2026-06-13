"""Daily backfill of long-term memory for users who predate the memory engine.

Users created before the live memory pipeline shipped have conversation history
that never went through ``memory_node``. A daily cron (``backfill_active_users``)
scans for recently-active, pre-launch, not-yet-backfilled users and enqueues a
per-user job (``backfill_user_memories``) that replays their conversations
through ``memory_engine.retain`` and notifies them once their memory is ready.

The ``memory_backfilled`` marker makes the whole thing idempotent and, as a
free side effect, picks up users who only just became active again: when a
dormant account logs back in its ``last_active_at`` is bumped, so the next cron
run sees it as eligible and backfills it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bson import ObjectId

from app.constants.memory import (
    MEMORY_BACKFILL_ACTIVE_DAYS,
    MEMORY_BACKFILL_ELIGIBLE_BEFORE,
    MEMORY_BACKFILL_MAX_CONVERSATIONS,
    MEMORY_BACKFILL_MAX_USERS_PER_RUN,
    MemorySourceType,
)
from app.db.mongodb.collections import conversations_collection, users_collection
from app.memory.engine import memory_engine
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
from shared.py.wide_events import MemoryContext, UserContext, log, wide_task

_BACKFILL_TASK = "backfill_user_memories"
_MEMORY_SETTINGS_URL = "/settings/memory"


def _eligible_query() -> dict:
    """Recently-active, pre-launch users that haven't been backfilled yet.

    ``_id`` is a Mongo ObjectId whose generation time is the account's creation
    instant, so the launch cutoff is expressed against it directly — no reliance
    on a separate ``created_at`` field.
    """
    active_since = datetime.now(UTC) - timedelta(days=MEMORY_BACKFILL_ACTIVE_DAYS)
    return {
        "last_active_at": {"$gte": active_since},
        "_id": {"$lt": ObjectId.from_datetime(MEMORY_BACKFILL_ELIGIBLE_BEFORE)},
        "memory_backfilled": {"$exists": False},
    }


async def backfill_active_users(ctx: dict) -> str:
    """Daily cron: enqueue a memory backfill for eligible users, capped per run.

    Capping per run drains the backlog gradually instead of spiking the
    extraction LLM; the marker means the next run resumes with whoever is left
    (plus anyone who became active in the meantime).
    """
    async with wide_task("backfill_active_users"):
        query = _eligible_query()
        remaining = await users_collection.count_documents(query)
        candidates = (
            await users_collection.find(query, {"_id": 1})
            .sort("last_active_at", -1)
            .limit(MEMORY_BACKFILL_MAX_USERS_PER_RUN)
            .to_list(length=MEMORY_BACKFILL_MAX_USERS_PER_RUN)
        )

        pool = await RedisPoolManager.get_pool()
        enqueued = 0
        for user in candidates:
            user_id = str(user["_id"])
            # Deterministic job id: a user already queued/running is not
            # re-enqueued by an overlapping cron run.
            job = await pool.enqueue_job(_BACKFILL_TASK, user_id, _job_id=f"membackfill:{user_id}")
            if job is not None:
                enqueued += 1

        log.set(eligible_remaining=remaining, enqueued=enqueued)
        return f"memory backfill: enqueued {enqueued}, {max(remaining - enqueued, 0)} still pending"


async def backfill_user_memories(ctx: dict, user_id: str) -> str:
    """Replay one user's conversations into memory, then notify them.

    Idempotent: re-checks the marker, and the engine's reconciliation dedups
    facts, so a retry never double-stores. The marker is set even on a zero-fact
    no-op so the cron won't keep re-selecting the user.
    """
    async with wide_task("backfill_user_memories", user=UserContext(id=user_id)):
        oid = ObjectId(user_id)
        user = await users_collection.find_one({"_id": oid})
        if user is None or "memory_backfilled" in user:
            log.set(skipped=True)
            return f"skip {user_id}: missing or already backfilled"

        user_name = user.get("name") or "the user"
        # Most-recent conversations, replayed oldest-first so journal dates and
        # recency-based reconciliation land on the right days.
        docs = (
            await conversations_collection.find({"user_id": user_id})
            .sort("createdAt", -1)
            .limit(MEMORY_BACKFILL_MAX_CONVERSATIONS)
            .to_list(length=MEMORY_BACKFILL_MAX_CONVERSATIONS)
        )
        docs.reverse()

        facts = 0
        processed = 0
        for doc in docs:
            messages = _conversation_to_messages(doc)
            if not messages:
                continue
            result = await memory_engine.retain(
                user_id,
                messages,
                source_type=MemorySourceType.CONVERSATION,
                source_id=doc.get("conversation_id"),
                user_name=user_name,
                now=_conversation_date(doc),
            )
            facts += result.facts_extracted
            processed += 1

        await users_collection.update_one(
            {"_id": oid}, {"$set": {"memory_backfilled": datetime.now(UTC)}}
        )
        log.set(
            memory=MemoryContext(operation="retain", facts_extracted=facts, result_count=facts),
            conversations=processed,
        )

        # Only tell the user when something was actually learned — a 0-fact
        # no-op shouldn't surface a "we organized your memories" message.
        if facts > 0:
            await _notify_memory_ready(user_id)

        return f"backfilled {user_id}: {processed} conversations, {facts} facts"


def _conversation_to_messages(doc: dict) -> list[dict[str, str]]:
    """Map a stored conversation's embedded messages to extraction format."""
    role_map = {"user": "user", "bot": "assistant"}
    messages: list[dict[str, str]] = []
    for msg in doc.get("messages", []):
        role = role_map.get(msg.get("type", ""))
        content = (msg.get("response") or "").strip()
        if role and content:
            messages.append({"role": role, "content": content})
    return messages


def _conversation_date(doc: dict) -> datetime:
    """Best-effort original timestamp so replayed facts land on the right day."""
    value = doc.get("createdAt") or doc.get("updatedAt")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(UTC)


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
                                    url=_MEMORY_SETTINGS_URL,
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
