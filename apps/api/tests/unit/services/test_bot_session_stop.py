"""A bot chat's /stop stops its conversation and keeps the session; /new stops it, then starts fresh."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.chat import ConversationSource
from app.db.repositories.bot_sessions import bot_session_repository
from app.models.bot_models import BotSessionDocument
from app.models.user_models import AuthenticatedUser
from app.models.work_cancel_models import WorkCancelled
from app.services import bot_session_stop, conversation_stop_service
from app.services.bot_session_stop import reset_bot_session, stop_bot_session
from app.services.browser.job_stop import RequesterChat
from shared.py.analytics.catalog.chat import ChatWorkStopped

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis")]

USER = AuthenticatedUser(user_id="507f1f77bcf86cd799439011", email="t@example.com", name="T")


def _session(conversation_id: str) -> BotSessionDocument:
    return BotSessionDocument(
        session_key="k",
        conversation_id=conversation_id,
        platform="discord",
        platform_user_id="user123",
        channel_id=None,
    )


class _Sessions:
    """The bot_sessions repository's reads and writes, recorded."""

    def __init__(self, current: BotSessionDocument | None) -> None:
        self.get_by_session_key = AsyncMock(return_value=current)
        self.delete_by_session_key = AsyncMock()


@pytest.fixture
def cancelled(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Stand in for cancel_all_work, which test_work_cancel covers."""
    mock = AsyncMock(return_value=WorkCancelled())
    monkeypatch.setattr(conversation_stop_service, "cancel_all_work", mock)
    return mock


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr(conversation_stop_service, "capture", mock)
    return mock


def _stop_events(captured: MagicMock) -> list[object]:
    return [c.args[1] for c in captured.call_args_list if isinstance(c.args[1], ChatWorkStopped)]


def _sessions(current: BotSessionDocument | None) -> Iterator[_Sessions]:
    sessions = _Sessions(current)
    with (
        patch.object(bot_session_repository, "get_by_session_key", sessions.get_by_session_key),
        patch.object(
            bot_session_repository, "delete_by_session_key", sessions.delete_by_session_key
        ),
    ):
        yield sessions


@pytest.fixture
def dm_session() -> Iterator[_Sessions]:
    yield from _sessions(_session("conv-dm"))


@pytest.fixture
def no_session() -> Iterator[_Sessions]:
    yield from _sessions(None)


class TestStop:
    async def test_a_dm_stop_reaches_the_users_runs_from_any_group_and_keeps_the_session(
        self, dm_session: _Sessions, cancelled: AsyncMock, captured: MagicMock
    ) -> None:
        await stop_bot_session("discord", "user123", "dm-chan", USER, is_dm=True)

        dm_session.get_by_session_key.assert_awaited_once_with("discord:user123:user123")
        cancelled.assert_awaited_once_with(
            "conv-dm", USER.user_id, RequesterChat(USER.user_id, ConversationSource.DISCORD)
        )
        dm_session.delete_by_session_key.assert_not_awaited()

    async def test_a_group_stop_reaches_only_that_groups_own_work(
        self, dm_session: _Sessions, cancelled: AsyncMock, captured: MagicMock
    ) -> None:
        await stop_bot_session("slack", "user123", "channel789", USER)

        dm_session.get_by_session_key.assert_awaited_once_with("slack:user123:channel789")
        cancelled.assert_awaited_once_with("conv-dm", USER.user_id, None)

    async def test_a_stop_is_the_users_stop_and_emits_work_stopped_once(
        self, dm_session: _Sessions, cancelled: AsyncMock, captured: MagicMock
    ) -> None:
        await stop_bot_session("slack", "user123", "channel789", USER)

        assert len(_stop_events(captured)) == 1

    async def test_a_chat_with_no_session_has_nothing_to_stop(
        self, no_session: _Sessions, cancelled: AsyncMock, captured: MagicMock
    ) -> None:
        result = await stop_bot_session("slack", "user123", "channel789", USER)

        assert result.conversation_id is None
        assert not result.work.stopped_anything
        cancelled.assert_not_awaited()


class TestReset:
    async def test_new_stops_the_old_conversations_work_then_replaces_the_session(
        self,
        dm_session: _Sessions,
        cancelled: AsyncMock,
        captured: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """/new leaves the old conversation; work left running there keeps reporting into it."""
        reset = AsyncMock(return_value="conv-new")
        monkeypatch.setattr(bot_session_stop.BotService, "reset_session", reset)

        new_id = await reset_bot_session("slack", "user123", "channel789", USER)

        assert new_id == "conv-new"
        cancelled.assert_awaited_once_with("conv-dm", USER.user_id, None)
        reset.assert_awaited_once_with("slack", "user123", "channel789", USER, is_dm=False)

    async def test_new_is_its_own_action_and_emits_no_work_stopped(
        self,
        dm_session: _Sessions,
        cancelled: AsyncMock,
        captured: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """One action, one event: /new is counted by bot:session_reset, never as a Stop too."""
        monkeypatch.setattr(
            bot_session_stop.BotService, "reset_session", AsyncMock(return_value="conv-new")
        )

        await reset_bot_session("slack", "user123", "channel789", USER)

        assert _stop_events(captured) == []
