"""The daily brief and weekly recap runs, end to end through the service.

Faked seams: the user lookup, the agent (``call_agent_silent``), the briefing
repository, the notification orchestrator, the channel resolver, the bot-chat
sync and the context reads (tested in ``test_context.py``). Assertions are on
what gets stored and what gets delivered — and, on every failure path, that
nothing is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.constants.briefing import MAX_BRIEF_ITEMS, BriefingBag
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.briefing_models import (
    BriefingEvent,
    BriefingModel,
    BriefingPayload,
    BriefingTallies,
    BriefingWeek,
    BriefingWeekDay,
)
from app.models.todo_models import TodoDocument
from app.models.user_models import ShuffleBag
from app.services.briefing import context, service
from app.services.briefing.dormancy import DormancyState
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS

_USER = "user-1"
_EVENT = BriefingEvent(date="2026-10-14", start="11:00", title="Sequoia")
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
    bags: dict[str, ShuffleBag] = field(default_factory=dict)
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
        service.context,
        "gather_completed_since",
        AsyncMock(return_value=context.CompletedWork(user=[_todo("u1", "Gym")])),
    )
    monkeypatch.setattr(service.dormancy, "record_idle_day", AsyncMock(return_value=0))
    monkeypatch.setattr(
        service.dormancy, "reactivation_signal_since", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(service, "track", MagicMock())

    async def get_bag(user_id: str, bag: BriefingBag) -> ShuffleBag | None:
        return w.bags.get(bag.value)

    async def set_bag(user_id: str, bag: BriefingBag, state: ShuffleBag) -> None:
        w.bags[bag.value] = state

    monkeypatch.setattr(service.user_repository, "get_briefing_bag", get_bag)
    monkeypatch.setattr(service.user_repository, "set_briefing_bag", set_bag)
    monkeypatch.setattr(service.context, "gather_calendar", AsyncMock(return_value=[_EVENT]))
    monkeypatch.setattr(
        service.context,
        "gather_week",
        AsyncMock(return_value=BriefingWeek(days=[BriefingWeekDay(you=1, gaia=2)] * 7)),
    )
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
        assert payload.template_family in DAILY_FAMILY_WEIGHTS
        assert world.bags["edition_family"].order.count(payload.template_family) >= 1
        assert payload.calendar == [_EVENT]
        assert payload.tallies == BriefingTallies(done_by_you=1, done_by_gaia=0)
        assert "11:00: Sequoia" in world.agent.await_args.kwargs["request"].message
        assert [(s.title, [i.text for i in s.items]) for s in payload.sections] == [
            ("NEEDS YOU", ["Approve the Priya reply"]),
            ("GAIA'S WORK", ["Investor update"]),
        ]
        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == _CHANNELS
        assert request.metadata["kind"] == NOTIFICATION_KIND_BRIEFING_DAILY
        assert request.metadata["platform_parts"] == [
            "Two things need you\n\n"
            "• Approve the Priya reply\n\n"
            "Overnight I finished Investor update.\n\n"
            "Full brief: https://heygaia.io/briefings"
        ]
        assert request.content.rich_content == payload.model_dump()
        world.set_channels.assert_awaited_once()
        assert world.set_channels.await_args.args[3] == _CHANNELS
        world.chat_sync.assert_awaited_once()
        assert world.chat_sync.await_args.args[2:] == (
            request.metadata["platform_parts"],
            _CHANNELS,
        )

    @staticmethod
    def _postal_first(world: World) -> None:
        pool = [f for f, n in DAILY_FAMILY_WEIGHTS.items() for _ in range(n)]
        pool.remove("postal")
        world.bags["edition_family"] = ShuffleBag(order=["postal", *pool], index=0)

    async def test_an_air_mail_brief_records_its_stamp_city(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            service, "hosted_stamp_weights", lambda: {"paris": 1, "tokyo": 1, "lima": 1}
        )
        self._postal_first(world)

        await service.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        assert payload.template_family == "postal"
        assert payload.stamp_city in {"paris", "tokyo", "lima"}
        assert world.bags["stamp_city"].order[0] == payload.stamp_city

    async def test_before_the_stamps_are_uploaded_air_mail_carries_no_city(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service, "hosted_stamp_weights", dict)
        self._postal_first(world)

        await service.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        assert payload.template_family == "postal"
        assert payload.stamp_city is None
        assert "stamp_city" not in world.bags

    async def test_a_non_postal_brief_draws_no_stamp(self, world: World) -> None:
        pool = [f for f, n in DAILY_FAMILY_WEIGHTS.items() for _ in range(n)]
        pool.remove("memo")
        world.bags["edition_family"] = ShuffleBag(order=["memo", *pool], index=0)

        await service.run_daily_briefing(_USER)

        assert _stored_payload(world).stamp_city is None
        assert "stamp_city" not in world.bags

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
        assert payload.template_family == "weekly"
        assert payload.week is not None
        assert payload.tallies == BriefingTallies(done_by_you=7, done_by_gaia=14)
        assert payload.headline == "A good week"
        request = world.notify.await_args.args[0]
        assert request.metadata["kind"] == NOTIFICATION_KIND_BRIEFING_WEEKLY
        assert request.metadata["platform_parts"] == [
            "A good week\n\nThis week I finished Item 0, Item 1 and 1 more.\n\n"
            "Full brief: https://heygaia.io/briefings"
        ]

    async def test_recap_over_the_item_cap_fails_and_sends_nothing(self, world: World) -> None:
        world.agent.return_value = SimpleNamespace(message=_fenced(_weekly(MAX_BRIEF_ITEMS + 1)))

        with pytest.raises(service.BriefingGenerationError, match="at most"):
            await service.run_weekly_digest(_USER)

        _assert_nothing_sent(world)
