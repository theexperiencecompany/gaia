"""Watching live: the user wrote on the surface the subject lives on within the window."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.outbox import LIVE_WATCH_WINDOW_SECONDS
from app.models.chat_models import ConversationSource
from app.services.outbox.models import (
    Initiative,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    Subject,
    SubjectKind,
)
from app.services.outbox.watching import is_watched_live

NOW = 1_800_000_000
MODULE = "app.services.outbox.watching"


def _progress(owner: str | None = "conv-1") -> NoticeReport:
    return NoticeReport(
        report_id="p",
        recipient="u",
        producer=ProducerKind.BROWSER,
        subject=Subject(
            kind=SubjectKind.BROWSER_JOB, id="job", owner_conversation_id=owner, label="Browser"
        ),
        occurred_at=datetime(2026, 11, 10, tzinfo=UTC),
        initiative=Initiative.ASKED,
        outcome=NoticeOutcome.PROGRESS,
        facts=["Step 1"],
    )


async def _watched(
    report: NoticeReport, source: ConversationSource | None, last_seen: dict[str, int]
) -> bool:
    with (
        patch(f"{MODULE}.conversation_repository.get_source", AsyncMock(return_value=source)),
        patch(
            f"{MODULE}.read_presence",
            AsyncMock(return_value={"captured_at": NOW, "last_seen": last_seen}),
        ),
    ):
        return await is_watched_live(report)


async def test_a_user_who_wrote_on_the_subjects_surface_a_moment_ago_is_watching() -> None:
    assert await _watched(_progress(), ConversationSource.TELEGRAM, {"telegram": NOW - 30})


async def test_the_window_edge_is_still_watching_and_one_second_past_it_is_not() -> None:
    edge = {"telegram": NOW - LIVE_WATCH_WINDOW_SECONDS}
    assert await _watched(_progress(), ConversationSource.TELEGRAM, edge)
    past = {"telegram": NOW - LIVE_WATCH_WINDOW_SECONDS - 1}
    assert not await _watched(_progress(), ConversationSource.TELEGRAM, past)


async def test_activity_on_another_surface_is_not_watching_this_one() -> None:
    assert not await _watched(_progress(), ConversationSource.TELEGRAM, {"web": NOW - 5})


async def test_a_user_never_seen_anywhere_is_not_watching() -> None:
    assert not await _watched(_progress(), ConversationSource.TELEGRAM, {})


async def test_a_chat_in_the_app_is_the_web_surface() -> None:
    assert await _watched(_progress(), None, {"web": NOW - 5})


async def test_a_subject_with_no_owner_conversation_is_the_web_surface() -> None:
    with (
        patch(f"{MODULE}.conversation_repository.get_source", AsyncMock()) as get_source,
        patch(
            f"{MODULE}.read_presence",
            AsyncMock(return_value={"captured_at": NOW, "last_seen": {"web": NOW}}),
        ),
    ):
        assert await is_watched_live(_progress(owner=None))
    get_source.assert_not_awaited()


async def test_an_unreadable_presence_raises_instead_of_guessing() -> None:
    with (
        patch(f"{MODULE}.conversation_repository.get_source", AsyncMock(return_value=None)),
        patch(f"{MODULE}.read_presence", AsyncMock(side_effect=ConnectionError("redis down"))),
        pytest.raises(ConnectionError),
    ):
        await is_watched_live(_progress())
