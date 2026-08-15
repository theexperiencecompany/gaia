"""Stress: ARQ task idempotency under replay.

Real code under test: ``backfill_user_memories`` in
``app/workers/tasks/memory_backfill_tasks.py``. ARQ delivers at-least-once:
a worker that dies mid-job, or a scheduled retry, re-runs the task function.
The task must therefore be idempotent — its second run must not re-extract
memories, re-notify the user, or re-write the marker.

The observable side effects are the ``memory_backfilled`` marker on the user
document, the ``memory_engine.retain`` calls, and the "Your memory is ready"
notification. The repositories and engine are fakes (stateful where the
invariant needs state); the task logic is the real module code.
"""

from collections.abc import AsyncGenerator
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.memory.ingestion import RetainResult
from app.models.chat_models import MessageModel
from app.models.conversation_models import ConversationDocument
from app.models.user_models import UserDocument
from app.workers.tasks.memory_backfill_tasks import backfill_user_memories

pytestmark = pytest.mark.stress

MODULE = "app.workers.tasks.memory_backfill_tasks"


class _FakeUserRepository:
    """User repo whose ``memory_backfilled`` marker flips on mark_memory_backfilled.

    The marker is the idempotency guard under test: it must survive a mock
    boundary, so the fake carries real state across task invocations.
    """

    def __init__(self, doc: UserDocument) -> None:
        self._doc = doc
        self.mark_calls = 0

    async def get(self, user_id: str) -> UserDocument | None:
        return self._doc

    async def mark_memory_backfilled(self, user_id: str) -> None:
        self.mark_calls += 1
        self._doc.memory_backfilled = datetime.now(UTC)


class _Backend:
    """The mocked seams of one backfill run, observable after the task ran."""

    def __init__(
        self,
        user_repo: _FakeUserRepository,
        retain: AsyncMock,
        notify: AsyncMock,
        summarize: AsyncMock,
        consolidate: AsyncMock,
    ) -> None:
        self.user_repo = user_repo
        self.retain = retain
        self.notify = notify
        self.summarize = summarize
        self.consolidate = consolidate


def _conversation(cid: str, content: str) -> ConversationDocument:
    return ConversationDocument(
        conversation_id=cid,
        user_id="user-1",
        messages=[
            MessageModel(type="user", response=content),
            MessageModel(type="bot", response=f"answer: {content}"),
        ],
        createdAt="2025-06-01T10:00:00Z",
    )


@contextmanager
def _backend(
    user: UserDocument, conversations: list[ConversationDocument], *, facts: int = 2
) -> AsyncGenerator[_Backend, None]:
    user_repo = _FakeUserRepository(user)
    convo_repo = MagicMock()
    convo_repo.recent_for_user = AsyncMock(return_value=conversations)
    retain = AsyncMock(return_value=RetainResult(facts_extracted=facts))
    notify = AsyncMock()
    summarize = AsyncMock()
    consolidate = AsyncMock()
    with (
        patch(f"{MODULE}.user_repository", user_repo),
        patch(f"{MODULE}.conversation_repository", convo_repo),
        patch(f"{MODULE}.memory_engine.retain", retain),
        patch(f"{MODULE}.memory_engine.summarize_episode", summarize),
        patch(f"{MODULE}.memory_engine.consolidate", consolidate),
        patch(f"{MODULE}.cancel_consolidation", AsyncMock()),
        patch(f"{MODULE}.notification_service.create_notification", notify),
    ):
        yield _Backend(user_repo, retain, notify, summarize, consolidate)


class TestBackfillUserMemoriesIdempotency:
    async def test_double_invocation_does_not_double_process_or_double_notify(self):
        """A retried job must be a no-op: second run skips, side effects stay at one."""
        user = UserDocument(name="Arya", memory_backfilled=None)
        conversations = [
            _conversation("c1", "plan the launch"),
            _conversation("c2", "review the deck"),
        ]

        with _backend(user, conversations) as b:
            first = await backfill_user_memories({}, "user-1")
            second = await backfill_user_memories({}, "user-1")

        assert first == "backfilled user-1: 2 conversations, 4 facts"
        assert second == "skip user-1: missing or already backfilled"
        assert b.retain.await_count == 2
        assert b.notify.await_count == 1
        assert b.summarize.await_count == 1
        assert b.consolidate.await_count == 1
        assert b.user_repo.mark_calls == 1

    async def test_user_already_marked_is_skipped_with_zero_side_effects(self):
        """The marker guard itself: without it, the second run would re-extract
        and re-notify — this test goes red the moment the guard is removed."""
        user = UserDocument(name="Arya", memory_backfilled=datetime(2026, 1, 1, tzinfo=UTC))

        with _backend(user, [_conversation("c1", "hi")]) as b:
            result = await backfill_user_memories({}, "user-1")

        assert result == "skip user-1: missing or already backfilled"
        b.retain.assert_not_awaited()
        b.notify.assert_not_awaited()
        assert b.user_repo.mark_calls == 0

    async def test_zero_fact_backfill_still_marks_but_does_not_notify(self):
        """The marker is set even for a no-op so the cron stops re-selecting the
        user, while the notification is suppressed — the idempotency loop closes
        without spamming the user."""
        user = UserDocument(name="Arya", memory_backfilled=None)

        with _backend(user, [_conversation("c1", "hi")], facts=0) as b:
            result = await backfill_user_memories({}, "user-1")

        assert result == "backfilled user-1: 1 conversations, 0 facts"
        assert b.user_repo.mark_calls == 1
        b.notify.assert_not_awaited()
