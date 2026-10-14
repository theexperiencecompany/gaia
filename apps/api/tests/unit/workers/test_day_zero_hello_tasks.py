"""GAIA's first text after a user links a chat platform: guards, parsing, delivery.

The agent turn, the platform publish, the user repository and analytics are the
faked seams; channel picking, prompt building and the user context are real.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import time_machine

from app.constants.chat import ConversationSource
from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.notifications import ProactiveMessageClass
from app.models.user_models import DayZeroHello, UserDocument
from app.services.briefing import service as briefing_service
from app.services.delivery.chat_channel import ChatChannel
from app.services.outbound_delivery import OutboundResult
from app.workers.tasks import day_zero_hello_tasks as hello
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingDayZeroHelloSent
from tests.helpers import WideEventRecorder

_USER = "64f1c0ffee0000000000abcd"
_NOW = datetime(2026, 10, 14, 9, tzinfo=UTC)
_TASK = "send_day_zero_hello"


def _user(**overrides: Any) -> UserDocument:
    data: dict[str, Any] = {
        "id": _USER,
        "name": "Ada Lovelace",
        "created_at": _NOW - timedelta(days=1),
        "platform_links": {"telegram": {"id": "42"}},
    }
    data.update(overrides)
    return UserDocument(**data)


class Seams:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.get_user = AsyncMock(return_value=_user())
        self.mark_sent = AsyncMock()
        self.goal = AsyncMock(return_value=("Stated goal: raise a seed round", True))
        self.agent = AsyncMock(return_value=SimpleNamespace(message='["Hi Ada!", "Brief at 8."]'))
        self.post = AsyncMock(return_value=OutboundResult.PUBLISHED)
        self.capture = MagicMock()
        monkeypatch.setattr(hello.user_repository, "get", self.get_user)
        monkeypatch.setattr(hello.user_repository, "mark_day_zero_hello_sent", self.mark_sent)
        monkeypatch.setattr(hello.context, "format_goal_block", self.goal)
        monkeypatch.setattr(briefing_service, "call_agent_silent", self.agent)
        monkeypatch.setattr(hello, "post_to_platform_chat", self.post)
        monkeypatch.setattr(hello, "capture", self.capture)
        self.recorder = WideEventRecorder()

    async def send(self, platform: str = "telegram") -> str:
        with patch("shared.py.wide_events._loguru", self.recorder):
            return await hello.send_day_zero_hello({}, _USER, platform)

    @property
    def event(self) -> dict[str, Any]:
        return self.recorder.event(_TASK)

    def assert_nothing_sent(self) -> None:
        self.agent.assert_not_awaited()
        self.post.assert_not_awaited()
        self.mark_sent.assert_not_awaited()
        self.capture.assert_not_called()


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch) -> Iterator[Seams]:
    with time_machine.travel(_NOW, tick=False):
        yield Seams(monkeypatch)


class TestParseBubbles:
    @pytest.mark.parametrize(
        "raw",
        [
            '["Hi", "Second"]',
            'Here you go:\n```json\n["Hi", "Second"]\n```',
            '```\n["Hi", "Second"]\n```',
            '``` ```\n```json\n["Hi", "Second"]\n```',
            '```json\nnot json\n```\n```json\n["Hi", "Second"]\n```',
            '["  Hi  ", "", "   ", "Second"]',
        ],
        ids=["bare", "fenced", "plain-fence", "empty-first", "bad-first", "blanks-dropped"],
    )
    def test_the_first_valid_array_of_strings_is_the_bubbles(self, raw: str) -> None:
        assert hello._parse_bubbles(raw) == ["Hi", "Second"]

    @pytest.mark.parametrize(
        "raw", ["Hi there!", '{"text": "Hi"}', '["Hi", 3]', '["", "  "]', "```json\n```"]
    )
    def test_anything_else_fails_the_run(self, raw: str) -> None:
        with pytest.raises(hello.DayZeroHelloError, match="No valid bubble array"):
            hello._parse_bubbles(raw)

    def test_the_failure_quotes_the_first_300_characters(self) -> None:
        raw = "x" * 299 + "yz"

        with pytest.raises(hello.DayZeroHelloError) as raised:
            hello._parse_bubbles(raw)

        assert str(raised.value) == (
            f"No valid bubble array in agent output (first 300 chars): {raw[:300]!r}"
        )


class TestGuards:
    async def test_an_unsupported_platform_is_skipped(self, seams: Seams) -> None:
        assert await seams.send("myspace") == f"skip {_USER}: unsupported platform myspace"

        seams.get_user.assert_not_awaited()
        assert seams.event["skipped"] == "unsupported_platform"
        assert seams.event["platform"] == "myspace"

    async def test_an_unknown_user_is_skipped(self, seams: Seams) -> None:
        seams.get_user.return_value = None

        assert await seams.send() == f"skip {_USER}: unknown user"

        seams.get_user.assert_awaited_once_with(_USER)
        assert seams.event["skipped"] == "unknown_user"
        seams.assert_nothing_sent()

    async def test_the_hello_goes_out_once_ever(self, seams: Seams) -> None:
        seams.get_user.return_value = _user(
            day_zero_hello=DayZeroHello(sent_at=_NOW, platform="discord")
        )

        assert await seams.send() == f"skip {_USER}: day-zero hello already sent"

        assert seams.event["skipped"] == "already_sent"
        seams.assert_nothing_sent()

    @pytest.mark.parametrize(
        "created_at",
        [None, _NOW - timedelta(days=14, seconds=1)],
        ids=["unknown-age", "just-past-14-days"],
    )
    async def test_an_old_account_is_not_a_day_zero_moment(
        self, seams: Seams, created_at: datetime | None
    ) -> None:
        seams.get_user.return_value = _user(created_at=created_at)

        assert await seams.send() == f"skip {_USER}: account older than 14 days"

        assert seams.event["skipped"] == "account_too_old"
        seams.assert_nothing_sent()

    @pytest.mark.parametrize(
        "created_at",
        [_NOW - timedelta(days=14), (_NOW - timedelta(days=13)).replace(tzinfo=None)],
        ids=["exactly-14-days", "naive-utc-from-mongo"],
    )
    async def test_an_account_up_to_14_days_old_is_greeted(
        self, seams: Seams, created_at: datetime
    ) -> None:
        seams.get_user.return_value = _user(created_at=created_at)

        assert await seams.send() == f"sent day-zero hello to {_USER} on telegram"

    async def test_a_platform_unlinked_before_the_job_ran_is_skipped(self, seams: Seams) -> None:
        seams.get_user.return_value = _user(platform_links={"discord": {"id": "7"}})

        assert await seams.send() == f"skip {_USER}: telegram not linked"

        assert seams.event["skipped"] == "not_linked"
        seams.assert_nothing_sent()


class TestDelivery:
    async def test_the_bubbles_land_in_the_linked_chat_and_the_flag_is_set(
        self, seams: Seams
    ) -> None:
        assert await seams.send() == f"sent day-zero hello to {_USER} on telegram"

        post = seams.post.await_args.kwargs
        assert post["channel"] == ChatChannel(
            source=ConversationSource.TELEGRAM, platform_user_id="42"
        )
        assert post["text"] == f"Hi Ada!{NEW_MESSAGE_BREAKER}Brief at 8."
        assert post["origin"] == "day-zero hello"
        assert post["user"].user_id == _USER
        # A hello the user just asked for by linking must not wait out their quiet hours.
        assert post["message_class"] is ProactiveMessageClass.USER_TRIGGERED
        seams.mark_sent.assert_awaited_once_with(_USER, "telegram")
        seams.capture.assert_called_once_with(
            UserId(_USER), BriefingDayZeroHelloSent(platform="telegram", has_goal=True)
        )
        assert (seams.event["bubbles"], seams.event["has_goal"]) == (2, True)
        assert seams.event["user"] == {"id": _USER}
        assert "skipped" not in seams.event

    async def test_the_agent_writes_from_the_users_first_name_and_goal(self, seams: Seams) -> None:
        await seams.send()

        seams.goal.assert_awaited_once_with(_USER, seams.get_user.return_value)
        run = seams.agent.await_args.kwargs
        prompt = run["request"].message
        assert "texting Ada for the first time" in prompt
        assert "Stated goal: raise a seed round" in prompt
        assert "OFFER one specific" in prompt
        assert [m["content"] for m in run["request"].messages] == [prompt]
        assert [m["role"] for m in run["request"].messages] == ["user"]
        assert run["user"].user_id == _USER
        assert re.fullmatch(rf"dayzero-{_USER}-[0-9a-f]{{6}}", run["conversation_id"])
        assert run["options"].trigger_context == {"execution_mode": "background"}
        assert run["options"].source == "day_zero_hello"

    @pytest.mark.parametrize("name", [None, "   "])
    async def test_a_user_without_a_name_is_greeted_as_there(
        self, seams: Seams, name: str | None
    ) -> None:
        seams.get_user.return_value = _user(name=name)
        seams.goal.return_value = ("No stated goal on record yet.", False)

        await seams.send()

        prompt = seams.agent.await_args.kwargs["request"].message
        assert "texting there for the first time" in prompt
        assert "ask ONE specific question" in prompt
        seams.capture.assert_called_once_with(
            UserId(_USER), BriefingDayZeroHelloSent(platform="telegram", has_goal=False)
        )

    async def test_a_skipped_publish_leaves_the_flag_unset(self, seams: Seams) -> None:
        seams.post.return_value = OutboundResult.SKIPPED

        assert await seams.send() == f"skip {_USER}: publish skipped (telegram)"

        assert seams.event["skipped"] == "publish_skipped"
        seams.mark_sent.assert_not_awaited()
        seams.capture.assert_not_called()

    async def test_a_failed_publish_raises_for_a_retry_and_leaves_the_flag_unset(
        self, seams: Seams
    ) -> None:
        seams.post.return_value = OutboundResult.FAILED

        with pytest.raises(
            hello.DayZeroHelloError,
            match=f"^day-zero hello publish failed for {_USER} on telegram$",
        ):
            await seams.send()

        seams.mark_sent.assert_not_awaited()
        seams.capture.assert_not_called()
