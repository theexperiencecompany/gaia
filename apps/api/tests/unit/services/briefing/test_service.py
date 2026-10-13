"""The daily brief and weekly recap runs, end to end through the service.

Faked seams: the user lookup, the agent (``call_agent_silent``), the briefing
repository, the notification orchestrator, the channel resolver, the bot-chat
sync and the context reads (tested in ``test_context.py``). Assertions are on
what gets stored and what gets delivered — and, on every failure path, that
nothing is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.constants.briefing import MAX_BRIEF_ITEMS
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.briefing_models import BriefingModel, BriefingPayload
from app.models.todo_models import TodoDocument
from app.services.briefing import context, service
from app.services.briefing.dormancy import DormancyState
from app.services.briefing.editions import family_for_date

_USER = "user-1"
_CHANNELS = ["inapp", "telegram", "email"]

_VOICE = {
    "headline": "Two things need you",
    "lede": "Everything else is moving.",
    "caption": "Onward.",
    "mood": "packed",
    "bubbles": ["morning! two things need you", "the rest is handled"],
}


def _fenced(data: dict[str, Any]) -> str:
    return f"```json\n{json.dumps(data)}\n```"


def _todo(todo_id: str, title: str) -> TodoDocument:
    return TodoDocument(id=todo_id, user_id=_USER, title=title, labels=[GAIA_TRACKED_LABEL])


@dataclass
class World:
    """Every seam the run touches, with a happy-path default."""

    agent: AsyncMock
    upsert: AsyncMock
    set_channels: AsyncMock
    notify: AsyncMock
    chat_sync: AsyncMock
    work: context.TrackedWork = field(default_factory=context.TrackedWork)
    user: dict[str, Any] = field(default_factory=lambda: {"timezone": "UTC", "email": "a@b.c"})


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    w = World(
        agent=AsyncMock(return_value=SimpleNamespace(message=_fenced(_VOICE))),
        upsert=AsyncMock(
            side_effect=lambda user_id, date, kind, payload: BriefingModel(
                user_id=user_id, date=date, kind=kind, payload=payload
            )
        ),
        set_channels=AsyncMock(),
        notify=AsyncMock(
            return_value=SimpleNamespace(
                channels=[SimpleNamespace(channel_type=c) for c in _CHANNELS]
            )
        ),
        chat_sync=AsyncMock(),
    )
    monkeypatch.setattr(service, "get_user_by_id", AsyncMock(side_effect=lambda _: dict(w.user)))
    monkeypatch.setattr(service, "call_agent_silent", w.agent)
    monkeypatch.setattr(service.briefing_repository, "upsert_briefing", w.upsert)
    monkeypatch.setattr(service.briefing_repository, "set_delivered_channels", w.set_channels)
    monkeypatch.setattr(
        service.briefing_repository, "has_daily_briefing", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(service.notification_service, "create_notification", w.notify)
    monkeypatch.setattr(
        service.delivery_channels, "resolve_briefing_channels", AsyncMock(return_value=_CHANNELS)
    )
    monkeypatch.setattr(service.chat_sync, "persist_delivered_brief", w.chat_sync)
    monkeypatch.setattr(
        service.chat_sync, "format_replies_block", AsyncMock(return_value="No replies.")
    )
    monkeypatch.setattr(
        service.context, "format_goal_block", AsyncMock(return_value=("Ship v2", True))
    )
    monkeypatch.setattr(service.context, "get_yesterday_payload", AsyncMock(return_value=None))
    monkeypatch.setattr(service.context, "format_lookback_block", AsyncMock(return_value="-"))
    monkeypatch.setattr(
        service.context,
        "compute_winback_state",
        AsyncMock(return_value=context.WinbackState(unacknowledged=0, last_was_winback=False)),
    )
    monkeypatch.setattr(
        service.context, "gather_tracked_work", AsyncMock(side_effect=lambda *_: w.work)
    )
    monkeypatch.setattr(service.context, "user_open_todo_summary", AsyncMock(return_value=(0, [])))
    monkeypatch.setattr(
        service.context, "gather_completed_since", AsyncMock(return_value=context.CompletedWork())
    )
    monkeypatch.setattr(service.dormancy, "record_idle_day", AsyncMock(return_value=0))
    monkeypatch.setattr(
        service.dormancy, "reactivation_signal_since", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(service, "track", MagicMock())
    return w


def _stored_payload(w: World) -> BriefingPayload:
    w.upsert.assert_awaited_once()
    return w.upsert.await_args.args[3]


def _assert_nothing_sent(w: World) -> None:
    w.upsert.assert_not_awaited()
    w.notify.assert_not_awaited()
    w.chat_sync.assert_not_awaited()


class TestDailyBrief:
    async def test_brief_is_stored_then_delivered_to_the_resolved_channels(
        self, world: World
    ) -> None:
        world.work = context.TrackedWork(
            blocked=[_todo("b1", "Approve the Priya reply")],
            completed=[_todo("c1", "Investor update")],
        )

        await service.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        assert payload.headline == "Two things need you"
        assert payload.template_family == family_for_date(datetime.now(UTC).date().isoformat())
        assert [(s.title, [i.text for i in s.items]) for s in payload.sections] == [
            ("NEEDS YOU", ["Approve the Priya reply"]),
            ("GAIA'S WORK", ["Investor update"]),
        ]
        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == _CHANNELS
        assert request.metadata["kind"] == NOTIFICATION_KIND_BRIEFING_DAILY
        assert request.metadata["platform_parts"] == _VOICE["bubbles"]
        assert request.content.rich_content == payload.model_dump()
        world.set_channels.assert_awaited_once()
        assert world.set_channels.await_args.args[3] == _CHANNELS
        world.chat_sync.assert_awaited_once()
        assert world.chat_sync.await_args.args[2:] == (_VOICE["bubbles"], _CHANNELS)

    async def test_brief_holds_at_most_the_cap_with_needs_you_first(self, world: World) -> None:
        world.work = context.TrackedWork(
            running=[_todo(f"r{i}", f"Running {i}") for i in range(6)],
            blocked=[_todo(f"b{i}", f"Blocked {i}") for i in range(3)],
            failed=[_todo("f1", "Failed one")],
        )

        await service.run_daily_briefing(_USER)

        items = [i for s in _stored_payload(world).sections for i in s.items]
        assert len(items) == MAX_BRIEF_ITEMS
        assert [i.kind for i in items[:4]] == ["you", "you", "you", "failed"]
        prompt = world.agent.await_args.kwargs["request"].message
        assert "2 lower-priority item(s) are not in this brief" in prompt

    async def test_voice_the_agent_botched_stores_and_sends_nothing(self, world: World) -> None:
        world.agent.return_value = SimpleNamespace(message="Sorry, something went wrong.")

        with pytest.raises(service.BriefingGenerationError):
            await service.run_daily_briefing(_USER)

        _assert_nothing_sent(world)

    async def test_unknown_user_fails_loud(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service, "get_user_by_id", AsyncMock(return_value=None))

        with pytest.raises(service.BriefingGenerationError, match="unknown user"):
            await service.run_daily_briefing(_USER)

        world.agent.assert_not_awaited()

    async def test_dormant_user_without_activity_is_skipped_before_the_agent(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            service.dormancy,
            "state_from_user",
            lambda _: DormancyState(idle_days=3, date=None, dormant_since=MagicMock()),
        )

        await service.run_daily_briefing(_USER)

        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    async def test_ignored_winback_backs_off(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            service.context,
            "compute_winback_state",
            AsyncMock(return_value=context.WinbackState(unacknowledged=5, last_was_winback=True)),
        )

        await service.run_daily_briefing(_USER)

        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    async def test_a_failed_delivery_records_no_channels(self, world: World) -> None:
        world.notify.side_effect = RuntimeError("orchestrator down")

        with pytest.raises(RuntimeError):
            await service.run_daily_briefing(_USER)

        world.upsert.assert_awaited_once()
        world.set_channels.assert_not_awaited()
        world.chat_sync.assert_not_awaited()


def _weekly(item_count: int) -> dict[str, Any]:
    return {
        "kicker": "THE WEEK IN REVIEW",
        "date": "2026-10-11",
        "headline": "A good week",
        "lede": "Nine things shipped.",
        "stats": [{"value": "3 hrs", "label": "saved"}],
        "sections": [
            {
                "numeral": "I",
                "title": "WHAT SHIPPED",
                "items": [{"text": f"Item {i}", "kind": "lookback"} for i in range(item_count)],
            }
        ],
        "mood": "weekly",
        "caption": "Same time next week.",
        "hue": 0,
        "message": "good week!",
    }


class TestWeeklyRecap:
    async def test_recap_is_stored_and_delivered_as_weekly(self, world: World) -> None:
        world.agent.return_value = SimpleNamespace(message=_fenced(_weekly(3)))

        await service.run_weekly_digest(_USER)

        payload = _stored_payload(world)
        assert world.upsert.await_args.args[2] == "weekly"
        assert payload.headline == "A good week"
        request = world.notify.await_args.args[0]
        assert request.metadata["kind"] == NOTIFICATION_KIND_BRIEFING_WEEKLY
        assert request.metadata["platform_parts"] == ["good week!"]

    async def test_recap_over_the_item_cap_fails_and_sends_nothing(self, world: World) -> None:
        world.agent.return_value = SimpleNamespace(message=_fenced(_weekly(MAX_BRIEF_ITEMS + 1)))

        with pytest.raises(service.BriefingGenerationError, match="at most"):
            await service.run_weekly_digest(_USER)

        _assert_nothing_sent(world)
