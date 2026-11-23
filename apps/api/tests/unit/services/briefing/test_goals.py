"""What the brief knows the user is working toward: what memory recalls.

The memory engine is the faked seam; every assertion is on the goals or the block the run
would hand the agent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.factories import make_user_id

from app.constants.memory import MemoryEntityType, MemoryKind
from app.models.memory_models import MemoryEntityRef, MemoryEntry, MemorySearchResult
from app.services.briefing import goals as goals_module
from app.services.briefing.goals import (
    StatedGoal,
    format_goal_block,
    stated_goals,
)

USER_ID = make_user_id()


def _memory(note: str, *entities: str, kind: MemoryKind = MemoryKind.FACT) -> MemoryEntry:
    """Return a recalled memory: its content and the names it is about."""
    return MemoryEntry(
        content=note,
        kind=kind,
        entities=[
            MemoryEntityRef(id=e, name=e, entity_type=MemoryEntityType.PROJECT) for e in entities
        ],
    )


def _recalled(*memories: MemoryEntry, confident: bool = True) -> MemorySearchResult:
    return MemorySearchResult(memories=list(memories), has_confident_match=confident)


class TestStatedGoals:
    @pytest.fixture
    def recall(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        recall = AsyncMock(return_value=_recalled())
        monkeypatch.setattr(goals_module, "memory_engine", SimpleNamespace(recall=recall))
        return recall

    async def test_no_memories_asks_for_goal_discovery(self, recall: AsyncMock) -> None:
        goals = await stated_goals(USER_ID)

        assert goals == []
        assert format_goal_block(goals) == (
            "No stated goal on record yet — treat goal discovery as part of today's job."
        )

    async def test_recalled_memories_are_shown_once_each(self, recall: AsyncMock) -> None:
        recall.return_value = _recalled(
            _memory("Raising a seed round", "Accel"), _memory("Raising a seed round", "Accel")
        )

        goals = await stated_goals(USER_ID)

        assert goals == [StatedGoal("Raising a seed round", ("Accel",))]
        assert format_goal_block(goals) == "- Raising a seed round"

    async def test_each_goal_is_its_own_line(self, recall: AsyncMock) -> None:
        recall.return_value = _recalled(
            _memory("Raising a seed round"), _memory("Hiring a designer")
        )

        goals = await stated_goals(USER_ID)

        assert format_goal_block(goals) == "- Raising a seed round\n- Hiring a designer"

    async def test_memory_is_asked_what_the_user_is_working_on(self, recall: AsyncMock) -> None:
        await stated_goals(USER_ID)

        recall.assert_awaited_once_with(
            USER_ID, "what is the user currently working on and their goals", limit=5
        )

    async def test_a_weak_fallback_recall_is_no_goal(self, recall: AsyncMock) -> None:
        """Regression: the top five nearest memories became goals however weakly they matched."""
        recall.return_value = _recalled(_memory("Likes oat milk"), confident=False)

        assert await stated_goals(USER_ID) == []

    async def test_something_that_happened_is_no_goal(self, recall: AsyncMock) -> None:
        recall.return_value = _recalled(
            _memory("Had a call with Priya", kind=MemoryKind.EXPERIENCE),
            _memory("Shipping the v2 launch"),
        )

        goals = await stated_goals(USER_ID)

        assert [g.statement for g in goals] == ["Shipping the v2 launch"]

    async def test_a_blank_memory_is_not_a_goal(self, recall: AsyncMock) -> None:
        recall.return_value = _recalled(_memory("   "), _memory("Hiring a designer"))

        goals = await stated_goals(USER_ID)

        assert format_goal_block(goals) == "- Hiring a designer"

    async def test_a_goal_carries_the_day_it_was_mentioned_as_the_brief_writes_a_day(
        self, recall: AsyncMock
    ) -> None:
        """Regression: an ISO mention date let the voice write "June 17", which no fact held."""
        recall.return_value = _recalled(
            _memory("300 users for GAIA").model_copy(
                update={"mentioned_at": datetime(2026, 6, 17, 9, tzinfo=UTC)}
            )
        )

        goals = await stated_goals(USER_ID)

        assert format_goal_block(goals) == "- 300 users for GAIA [mentioned Wed Jun 17, 2026]"

    async def test_a_recall_failure_fails_the_run(self, recall: AsyncMock) -> None:
        """Goal knowledge gates the brief; a broken memory store must not read as no goal."""
        recall.side_effect = RuntimeError("vector store down")

        with pytest.raises(RuntimeError, match="vector store down"):
            await stated_goals(USER_ID)
