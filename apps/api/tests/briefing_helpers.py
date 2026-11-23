"""Helpers for the briefing stack's tests, apart from tests.helpers so the shared harness imports only base code."""

from collections.abc import (
    Awaitable,
    Callable,
    Iterator,
)
from contextlib import contextmanager
from datetime import date, datetime
import re
from unittest.mock import AsyncMock, patch
import zoneinfo

from app.agents.prompts.briefing_prompts import UNTRUSTED_DATA_NOTE
from app.constants.briefing import BriefingFrequency
from app.db.repositories.briefing_state import briefing_state_repository
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.users import user_repository
from app.models.brief_settings_models import BriefingSchedule
from app.models.briefing_state_models import BriefingStateDocument
from app.models.user_models import UserDocument
from app.services.briefing.clock import UserClock

_FENCE_RE = re.compile(r"<<[0-9a-f]{8,}>>")


def briefs_on(frequency: BriefingFrequency) -> Callable[[str], Awaitable[BriefingStateDocument]]:
    """Stand in for briefing_state_repository.state_for with briefs that run at frequency."""

    async def state_for(user_id: str) -> BriefingStateDocument:
        return BriefingStateDocument(
            user_id=user_id, schedule=BriefingSchedule(frequency=frequency)
        )

    return state_for


@contextmanager
def brief_loop_awake() -> Iterator[None]:
    """Serve brief_will_carry's reads past the workflow: a user with no dormancy or winback."""
    with (
        patch.object(
            user_repository, "get", new=AsyncMock(side_effect=lambda uid: UserDocument(id=uid))
        ),
        patch.object(
            briefing_state_repository, "state_for", new=briefs_on(BriefingFrequency.DAILY)
        ),
        patch.object(briefing_repository, "list_recent", new=AsyncMock(return_value=[])),
    ):
        yield


def unfenced(prompt: str) -> str:
    """Return the prompt outside its untrusted-data fences; fails unless it has one fence, announced once."""
    fences = set(_FENCE_RE.findall(prompt))
    assert len(fences) == 1, f"expected one untrusted-data fence, found {sorted(fences)}"
    (fence,) = fences
    announced = UNTRUSTED_DATA_NOTE.format(fence=fence)
    assert prompt.count(announced) == 1, "the fence is never said to hold data, not instructions"
    parts = prompt.replace(announced, "").split(fence)
    assert len(parts) % 2 == 1, "a fence is opened and never closed"
    return "".join(parts[0::2])


def user_clock(tz_name: str, day: date, hour: int = 8) -> UserClock:
    """Return the brief's clock for a user in tz_name at hour on their local day."""
    tz = zoneinfo.ZoneInfo(tz_name)
    now = datetime(day.year, day.month, day.day, hour, tzinfo=tz)
    return UserClock(
        tz=tz, now_local=now, date_str=day.isoformat(), day_of_year=now.timetuple().tm_yday
    )
