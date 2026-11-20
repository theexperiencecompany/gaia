"""The weekly digest's standing: read for this user, from where their idle ladder stood.

The memory engine is the faked seam.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.factories import make_user_id
from tests.helpers import user_clock

from app.constants.memory import MemoryKind
from app.models.briefing_state_models import BriefingStateDocument, BriefingWindDown
from app.models.memory_models import MemoryEntry, MemorySearchResult
from app.models.user_models import UserDocument
from app.services.briefing import goals as goals_module
from app.services.briefing.goals import StatedGoal
from app.services.briefing.weekly import WeeklyStanding, stand_weekly

USER_ID = make_user_id()
CLOCK = user_clock("Asia/Kolkata", date(2026, 11, 16))


async def test_a_running_loops_digest_stands_on_the_users_goals_and_its_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def recall(user_id: str, _query: str, *, limit: int) -> MemorySearchResult:
        mine = [MemoryEntry(content="Ship v3 by December", kind=MemoryKind.FACT)]
        return MemorySearchResult(
            memories=mine if user_id == USER_ID else [], has_confident_match=True
        )

    monkeypatch.setattr(
        goals_module, "memory_engine", SimpleNamespace(recall=AsyncMock(side_effect=recall))
    )
    ladder = BriefingWindDown(
        idle_days=2, date="2026-11-15", goal_asked_at=datetime(2026, 11, 2, tzinfo=UTC)
    )
    user = UserDocument(id=USER_ID)

    state = BriefingStateDocument(user_id=USER_ID, wind_down=ladder)

    standing = await stand_weekly(user, state, CLOCK)

    assert standing == WeeklyStanding(
        user=user,
        state=state,
        clock=CLOCK,
        goals=[StatedGoal("Ship v3 by December")],
        prior=ladder,
    )
