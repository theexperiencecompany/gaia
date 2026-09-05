"""Unit tests for app.workers.tasks.memory_backfill_tasks.

The daily cron that replays pre-memory-engine conversations into long-term
memory: ``backfill_active_users`` enqueues one deterministic job per eligible
user, and ``backfill_user_memories`` replays that user's conversations through
``memory_engine.retain``, consolidates inline, marks the user backfilled (the
idempotency marker), and notifies only when facts were actually learned.
"""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.memory import (
    MEMORY_BACKFILL_ACTIVE_DAYS,
    MEMORY_BACKFILL_ELIGIBLE_BEFORE,
    MEMORY_BACKFILL_MAX_CONVERSATIONS,
    MEMORY_BACKFILL_MAX_USERS_PER_RUN,
    MemorySourceType,
)
from app.memory.ingestion import MemorySource
from app.models.chat_models import MessageModel
from app.models.conversation_models import ConversationDocument
from app.models.user_models import UserDocument
from app.workers.tasks.memory_backfill_tasks import (
    _conversation_date,
    _conversation_to_messages,
    backfill_active_users,
    backfill_user_memories,
)

MODULE = "app.workers.tasks.memory_backfill_tasks"

USER_ID = "507f1f77bcf86cd799439011"


def _user(**overrides) -> UserDocument:
    fields: dict = {
        "id": USER_ID,
        "name": "Alice",
        "memory_backfilled": None,
    }
    fields.update(overrides)
    return UserDocument(**fields)


def _conversation(
    conversation_id: str = "conv-1",
    *,
    created_at: str = "2026-01-01T10:00:00+00:00",
    messages: list[dict] | None = None,
) -> ConversationDocument:
    msgs = messages or [
        {"type": "user", "response": "Remember I prefer morning meetings"},
        {"type": "bot", "response": "Got it."},
    ]
    return ConversationDocument(
        user_id=USER_ID,
        conversation_id=conversation_id,
        createdAt=created_at,
        messages=[MessageModel(**m) for m in msgs],
    )


def _pool() -> MagicMock:
    pool = MagicMock()
    pool.enqueue_job = AsyncMock(return_value=MagicMock())
    return pool


# ---------------------------------------------------------------------------
# _conversation_to_messages / _conversation_date — pure mapping helpers
# ---------------------------------------------------------------------------


class TestConversationToMessages:
    def test_maps_user_and_bot_roles(self):
        doc = _conversation(
            messages=[
                {"type": "user", "response": "hello"},
                {"type": "bot", "response": "hi there"},
            ]
        ).model_dump(mode="json")
        assert _conversation_to_messages(doc) == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

    def test_drops_empty_and_unknown_message_types(self):
        doc = {
            "messages": [
                {"type": "user", "response": "  "},
                {"type": "system", "response": "not mapped"},
                {"type": "user", "response": "kept"},
            ]
        }
        assert _conversation_to_messages(doc) == [{"role": "user", "content": "kept"}]

    def test_no_messages_yields_empty_list(self):
        assert _conversation_to_messages({"messages": []}) == []


class TestConversationDate:
    def test_aware_datetime_is_kept(self):
        dt = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        assert _conversation_date({"createdAt": dt}) == dt

    def test_naive_datetime_is_assumed_utc(self):
        dt = datetime(2026, 1, 1, 10, 0)
        assert _conversation_date({"createdAt": dt}) == dt.replace(tzinfo=UTC)

    def test_iso_string_is_parsed(self):
        assert _conversation_date({"createdAt": "2026-01-01T10:00:00+00:00"}) == datetime(
            2026, 1, 1, 10, 0, tzinfo=UTC
        )

    def test_garbage_falls_back_to_now(self):
        before = datetime.now(UTC)
        result = _conversation_date({"createdAt": "not-a-date"})
        after = datetime.now(UTC)
        assert before <= result <= after


# ---------------------------------------------------------------------------
# backfill_active_users — the daily cron
# ---------------------------------------------------------------------------


class TestBackfillActiveUsers:
    async def test_enqueues_one_deterministic_job_per_candidate(self):
        pool = _pool()
        with (
            patch(f"{MODULE}.user_repository.count_backfill_candidates", AsyncMock(return_value=3)),
            patch(
                f"{MODULE}.user_repository.find_backfill_candidate_ids",
                AsyncMock(return_value=["u1", "u2"]),
            ),
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        ):
            result = await backfill_active_users({})

        assert result == "memory backfill: enqueued 2, 1 still pending"
        assert pool.enqueue_job.await_count == 2
        args = [c.args for c in pool.enqueue_job.await_args_list]
        assert args == [
            ("backfill_user_memories", "u1"),
            ("backfill_user_memories", "u2"),
        ]
        job_ids = [c.kwargs["_job_id"] for c in pool.enqueue_job.await_args_list]
        assert job_ids == ["membackfill:u1", "membackfill:u2"]

    async def test_candidates_are_capped_per_run(self):
        pool = _pool()
        with (
            patch(f"{MODULE}.user_repository.count_backfill_candidates", AsyncMock(return_value=9)),
            patch(
                f"{MODULE}.user_repository.find_backfill_candidate_ids",
                AsyncMock(return_value=["u1", "u2"]),
            ) as find,
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        ):
            await backfill_active_users({})

        assert find.call_args.kwargs["limit"] == MEMORY_BACKFILL_MAX_USERS_PER_RUN

    async def test_cutoffs_are_active_window_and_pre_launch(self):
        pool = _pool()
        before = datetime.now(UTC)
        with (
            patch(f"{MODULE}.user_repository.count_backfill_candidates", AsyncMock(return_value=0)),
            patch(
                f"{MODULE}.user_repository.find_backfill_candidate_ids",
                AsyncMock(return_value=[]),
            ) as find,
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        ):
            await backfill_active_users({})

        after = datetime.now(UTC)
        expected_lower = before - timedelta(days=MEMORY_BACKFILL_ACTIVE_DAYS)
        expected_upper = after - timedelta(days=MEMORY_BACKFILL_ACTIVE_DAYS)
        active_since = find.call_args.args[0]
        assert expected_lower <= active_since <= expected_upper
        assert find.call_args.args[1] == MEMORY_BACKFILL_ELIGIBLE_BEFORE

    async def test_a_failed_enqueue_is_not_counted(self):
        pool = _pool()
        pool.enqueue_job = AsyncMock(return_value=None)
        with (
            patch(f"{MODULE}.user_repository.count_backfill_candidates", AsyncMock(return_value=2)),
            patch(
                f"{MODULE}.user_repository.find_backfill_candidate_ids",
                AsyncMock(return_value=["u1"]),
            ),
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        ):
            result = await backfill_active_users({})

        assert result == "memory backfill: enqueued 0, 2 still pending"

    async def test_no_candidates_short_circuits_to_zero(self):
        pool = _pool()
        with (
            patch(f"{MODULE}.user_repository.count_backfill_candidates", AsyncMock(return_value=0)),
            patch(
                f"{MODULE}.user_repository.find_backfill_candidate_ids",
                AsyncMock(return_value=[]),
            ),
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        ):
            result = await backfill_active_users({})

        assert result == "memory backfill: enqueued 0, 0 still pending"
        pool.enqueue_job.assert_not_awaited()


# ---------------------------------------------------------------------------
# backfill_user_memories — the per-user job
# ---------------------------------------------------------------------------


class TestBackfillUserMemories:
    @contextmanager
    def _patches(self, *, retain_facts: int = 3) -> Iterator[dict[str, AsyncMock]]:
        docs = [_conversation()]
        retain = AsyncMock(return_value=MagicMock(facts_extracted=retain_facts))
        mocks = {
            "get": AsyncMock(return_value=_user()),
            "recent": AsyncMock(return_value=docs),
            "retain": retain,
            "cancel": AsyncMock(),
            "summarize": AsyncMock(),
            "consolidate": AsyncMock(),
            "mark": AsyncMock(),
            "notify": AsyncMock(),
        }
        patches = [
            patch(f"{MODULE}.user_repository.get", mocks["get"]),
            patch(f"{MODULE}.conversation_repository.recent_for_user", mocks["recent"]),
            patch(f"{MODULE}.memory_engine.retain", mocks["retain"]),
            patch(f"{MODULE}.cancel_consolidation", mocks["cancel"]),
            patch(f"{MODULE}.memory_engine.summarize_episode", mocks["summarize"]),
            patch(f"{MODULE}.memory_engine.consolidate", mocks["consolidate"]),
            patch(f"{MODULE}.user_repository.mark_memory_backfilled", mocks["mark"]),
            patch(f"{MODULE}._notify_memory_ready", mocks["notify"]),
        ]
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            yield mocks

    async def test_missing_user_is_skipped(self):
        with self._patches() as mocks:
            mocks["get"].return_value = None
            result = await backfill_user_memories({}, USER_ID)

        assert result == f"skip {USER_ID}: missing or already backfilled"
        mocks["recent"].assert_not_awaited()

    async def test_already_backfilled_user_is_skipped(self):
        with self._patches() as mocks:
            mocks["get"].return_value = _user(memory_backfilled=datetime(2026, 2, 1, tzinfo=UTC))
            result = await backfill_user_memories({}, USER_ID)

        assert result == f"skip {USER_ID}: missing or already backfilled"
        mocks["recent"].assert_not_awaited()

    async def test_success_replays_oldest_first_consolidates_and_notifies(self):
        with self._patches(retain_facts=3) as mocks:
            result = await backfill_user_memories({}, USER_ID)

        assert result == f"backfilled {USER_ID}: 1 conversations, 3 facts"
        mocks["retain"].assert_awaited_once()
        # The task calls retain positionally: (user_id, messages, ...).
        assert mocks["retain"].await_args.args[0] == USER_ID
        assert mocks["retain"].await_args.args[1] == [
            {"role": "user", "content": "Remember I prefer morning meetings"},
            {"role": "assistant", "content": "Got it."},
        ]
        retain_kwargs = mocks["retain"].await_args.kwargs
        assert retain_kwargs["source"] == MemorySource(MemorySourceType.CONVERSATION, "conv-1")
        assert retain_kwargs["user_name"] == "Alice"
        assert retain_kwargs["now"].tzinfo is not None
        # The debounced consolidation is cancelled and run inline once.
        mocks["cancel"].assert_awaited_once_with(USER_ID)
        mocks["summarize"].assert_awaited_once_with(USER_ID, datetime(2026, 1, 1).date())
        mocks["consolidate"].assert_awaited_once_with(USER_ID)
        mocks["mark"].assert_awaited_once_with(USER_ID)
        mocks["notify"].assert_awaited_once_with(USER_ID)

    async def test_replays_most_recent_conversations(self):
        with self._patches() as mocks:
            await backfill_user_memories({}, USER_ID)

        # The limit is a hard contract: over-fetching blows the extraction budget.
        mocks["recent"].assert_awaited_once_with(USER_ID, limit=MEMORY_BACKFILL_MAX_CONVERSATIONS)

    async def test_zero_facts_still_marks_backfilled_but_never_notifies(self):
        with self._patches(retain_facts=0) as mocks:
            result = await backfill_user_memories({}, USER_ID)

        assert result == f"backfilled {USER_ID}: 1 conversations, 0 facts"
        mocks["mark"].assert_awaited_once()
        mocks["notify"].assert_not_awaited()

    async def test_conversation_without_extractable_messages_is_a_no_op(self):
        with self._patches() as mocks:
            mocks["recent"].return_value = [
                _conversation(messages=[{"type": "system", "response": "x"}])
            ]
            result = await backfill_user_memories({}, USER_ID)

        assert result == f"backfilled {USER_ID}: 0 conversations, 0 facts"
        mocks["retain"].assert_not_awaited()
        mocks["summarize"].assert_not_awaited()
        mocks["consolidate"].assert_not_awaited()
        mocks["mark"].assert_awaited_once()
        mocks["notify"].assert_not_awaited()

    async def test_retain_failure_propagates(self):
        with self._patches() as mocks:
            mocks["retain"].side_effect = RuntimeError("extraction llm down")
            with pytest.raises(RuntimeError, match="extraction llm down"):
                await backfill_user_memories({}, USER_ID)

        mocks["mark"].assert_not_awaited()
