"""Core-context assembly (``app.memory.context``) — journal labels on the user's local day."""

from datetime import UTC, date as date_type, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.memory import context, user_time

USER = "user-1"

# 20:00 UTC on June 30 is already July 1 in Asia/Kolkata (UTC+5:30).
FIXED_NOW = datetime(2026, 6, 30, 20, 0, tzinfo=UTC)
KOLKATA_TODAY = date_type(2026, 7, 1)


def make_episode(
    day: date_type,
    entries: list[dict[str, str]] | None = None,
    summary: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(date=day, entries=entries or [], summary=summary)


@pytest.fixture
def seams() -> Any:
    """Mock every seam: Redis cache, pg_store, and the user-timezone lookup."""
    with (
        patch.object(context, "get_cache", AsyncMock(return_value=None)),
        patch.object(context, "set_cache", AsyncMock()) as set_cache,
        patch.object(context.pg_store, "get_documents", AsyncMock(return_value=[])),
        patch.object(
            context.pg_store, "get_episodes_range", AsyncMock(return_value=[])
        ) as episodes,
        patch.object(
            user_time.user_repository,
            "get",
            AsyncMock(return_value=SimpleNamespace(timezone="Asia/Kolkata")),
        ) as get_user,
        patch.object(user_time, "datetime") as clock,
    ):
        clock.now.return_value = FIXED_NOW
        yield SimpleNamespace(episodes=episodes, get_user=get_user, set_cache=set_cache)


@pytest.mark.unit
class TestGetCoreContextLocalDay:
    async def test_episode_range_spans_the_users_local_yesterday_to_today(
        self, seams: SimpleNamespace
    ) -> None:
        await context.get_core_context(USER)
        # "Today" comes from THIS user's stored timezone, not someone else's.
        seams.get_user.assert_awaited_once_with(USER)
        assert seams.episodes.await_args.args == (
            USER,
            date_type(2026, 6, 30),
            KOLKATA_TODAY,
        )

    async def test_today_label_matches_the_users_local_day(self, seams: SimpleNamespace) -> None:
        seams.episodes.return_value = [
            make_episode(KOLKATA_TODAY, entries=[{"time": "01:30", "text": "chatted with GAIA"}])
        ]
        out = await context.get_core_context(USER)
        assert "### Today (2026-07-01)" in out
        assert "- 01:30 chatted with GAIA" in out

    async def test_previous_local_day_is_labeled_yesterday_with_its_summary(
        self, seams: SimpleNamespace
    ) -> None:
        seams.episodes.return_value = [
            make_episode(date_type(2026, 6, 30), summary="A productive day.")
        ]
        out = await context.get_core_context(USER)
        assert "### Yesterday (2026-06-30)\nA productive day." in out

    async def test_missing_user_falls_back_to_utc_today(self, seams: SimpleNamespace) -> None:
        seams.get_user.return_value = None
        await context.get_core_context(USER)
        assert seams.episodes.await_args.args == (
            USER,
            date_type(2026, 6, 29),
            date_type(2026, 6, 30),
        )


@pytest.mark.unit
class TestFormatRecentActivity:
    def test_today_emits_the_newest_two_entries_with_an_omitted_note(self) -> None:
        today = KOLKATA_TODAY
        episode = make_episode(
            today,
            entries=[
                {"time": "09:00", "text": "one"},
                {"time": "10:00", "text": "two"},
                {"time": "11:00", "text": "three"},
            ],
        )
        out = context._format_recent_activity([episode], today)
        assert out == (
            "### Today (2026-07-01)\n- 10:00 two\n- 11:00 three\n- (earlier entries omitted)"
        )

    def test_past_day_without_a_summary_falls_back_to_its_entries(self) -> None:
        episode = make_episode(date_type(2026, 6, 30), entries=[{"time": "09:00", "text": "one"}])
        out = context._format_recent_activity([episode], KOLKATA_TODAY)
        assert out == "### Yesterday (2026-06-30)\n- 09:00 one"

    def test_empty_days_are_omitted(self) -> None:
        assert context._format_recent_activity([make_episode(KOLKATA_TODAY)], KOLKATA_TODAY) == ""
