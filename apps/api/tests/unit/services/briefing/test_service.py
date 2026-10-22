"""The daily brief and weekly recap runs, end to end through the service.

Faked seams: user lookup, call_agent_silent, the briefing repository, pending brief
items, the notification orchestrator, the chat channel resolver, the edition image
host, the platform chat post and the context reads. Assertions are on what gets
stored and delivered, and on every failure path, that nothing is.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, sentinel

import pytest
from tests.helpers import captured_wide_event
import time_machine

from app.constants.briefing import (
    FIRST_WEEK_DAYS,
    IDLE_DORMANT_DAYS,
    MAX_BRIEF_ITEMS,
    WEEKLY_KICKER,
    WINBACK_THRESHOLD,
    BriefingBag,
    BriefingFrequency,
    BriefingRunOutcome,
)
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
    ProactiveMessageClass,
)
from app.constants.todos import GAIA_TRACKED_LABEL
from app.constants.user_activity import ActivityStatus
from app.models.brief_models import PendingBriefItemDocument
from app.models.briefing_models import (
    BriefingEvent,
    BriefingModel,
    BriefingPayload,
    BriefingSchedule,
    BriefingTallies,
    BriefingWeek,
    BriefingWeekDay,
)
from app.models.chat_models import ConversationSource
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationStatus,
)
from app.models.todo_models import TodoDocument
from app.models.user_models import (
    BriefingBootstrap,
    BriefingDormancy,
    ShuffleBag,
    UserDocument,
)
from app.services.briefing import context, service
from app.services.briefing.dormancy import DormancyState
from app.services.briefing.edition_email import HostedEditionImage
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.delivery.chat_channel import ChatChannel
from app.services.outbound_delivery import OutboundResult
from app.utils.message_breaks import split_message_bubbles
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingSent

_USER = "64f1c0ffee0000000000abcd"
_TZ = "Asia/Kolkata"
# 07:05 on 14 Oct in Kolkata; the brief's day starts at local midnight.
_NOW = datetime(2026, 10, 14, 1, 35, tzinfo=UTC)
_DATE = "2026-10-14"
_DAY_START = datetime(2026, 10, 12, 18, 30, tzinfo=UTC)
# Monday 12 Oct, local midnight: the weekly digest counts from the start of the week.
_WEEK_START = datetime(2026, 10, 11, 18, 30, tzinfo=UTC)
_EVENT = BriefingEvent(date="2026-10-14", start="11:00", title="Sequoia")
_CHAT = ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-1")
_EDITION = HostedEditionImage(
    display_url="https://cdn.example/f_auto/brief", chat_url="https://cdn.example/f_jpg/brief"
)
_BRIEF_ID = "brief_abc123"
_ORCHESTRATED = ["inapp", "email"]

# The fake model writes its message from exactly the facts it was shown, so it
# mentions every need and event and cites nothing else; a reply holding this token
# gets the prompt's facts block in its place.
_FACTS_SHOWN = "<the facts shown>"
_FACTS_HEADER = "## TODAY'S FACTS (final: voice them, never alter them)\n"

_VOICE = {
    "headline": "Your morning, sorted",
    "lede": "Everything else is moving.",
    "caption": "Onward.",
    "mood": "packed",
    "message": _FACTS_SHOWN,
}


def _facts_shown(prompt: str) -> str:
    return prompt.split(_FACTS_HEADER, 1)[1].split("\n\n## ", 1)[0]


def _message_written(prompt: str, reply: str) -> str:
    """Return reply with the facts token replaced by the prompt's facts, JSON-escaped."""
    if _FACTS_HEADER not in prompt:
        return reply
    return reply.replace(_FACTS_SHOWN, json.dumps(_facts_shown(prompt))[1:-1])


_DIGEST_REPORT = "3 new papers on retrieval\nThe longest is 40 pages; two cite your draft."


def _delivered(channel: str) -> ChannelDeliveryStatus:
    return ChannelDeliveryStatus(channel_type=channel, status=NotificationStatus.DELIVERED)


def _fenced(data: dict[str, Any]) -> str:
    return f"```json\n{json.dumps(data)}\n```"


def _todo(todo_id: str, title: str) -> TodoDocument:
    return TodoDocument(id=todo_id, user_id=_USER, title=title, labels=[GAIA_TRACKED_LABEL])


def _held(item_id: str, title: str, text: str) -> PendingBriefItemDocument:
    return PendingBriefItemDocument(
        id=item_id,
        user_id=_USER,
        workflow_id=f"wf-{item_id}",
        workflow_title=title,
        conversation_id=f"conv-{item_id}",
        text=text,
    )


@dataclass
class World:
    """Every seam the run touches, with a happy-path default."""

    agent: AsyncMock
    upsert: AsyncMock
    set_channels: AsyncMock
    notify: AsyncMock
    post: AsyncMock
    host_image: AsyncMock
    consume: AsyncMock
    capture: MagicMock
    voice_prompt: MagicMock
    weekly_prompt: MagicMock
    recent: AsyncMock = field(default_factory=lambda: AsyncMock(return_value=[]))
    clear_bootstrap: AsyncMock = field(default_factory=AsyncMock)
    was_delivered: AsyncMock = field(default_factory=lambda: AsyncMock(return_value=False))
    clear_dormancy: AsyncMock = field(default_factory=AsyncMock)
    enter_dormancy: AsyncMock = field(default_factory=AsyncMock)
    activity: ActivityStatus = ActivityStatus.ACTIVE
    connected_apps: list[str] = field(default_factory=list)
    bags: dict[str, ShuffleBag] = field(default_factory=dict)
    work: context.TrackedWork = field(default_factory=context.TrackedWork)
    held: list[PendingBriefItemDocument] = field(default_factory=list)
    user: UserDocument = field(
        default_factory=lambda: UserDocument(id=_USER, timezone=_TZ, email="a@b.c", name="Ada")
    )
    chat: ChatChannel | None = _CHAT


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    w = World(
        agent=AsyncMock(return_value=SimpleNamespace(message=_fenced(_VOICE))),
        upsert=AsyncMock(
            side_effect=lambda user_id, date, kind, payload, *, edition_image_url: BriefingModel(
                id=_BRIEF_ID,
                user_id=user_id,
                date=date,
                kind=kind,
                payload=payload,
                edition_image_url=edition_image_url,
            )
        ),
        set_channels=AsyncMock(),
        notify=AsyncMock(
            return_value=SimpleNamespace(channels=[_delivered(c) for c in _ORCHESTRATED])
        ),
        post=AsyncMock(return_value=OutboundResult.PUBLISHED),
        host_image=AsyncMock(side_effect=lambda payload, *, render_key: _EDITION),
        consume=AsyncMock(),
        capture=MagicMock(),
        voice_prompt=MagicMock(wraps=service.build_briefing_voice_prompt),
        weekly_prompt=MagicMock(wraps=service.build_weekly_digest_prompt),
    )

    # Seams keyed on the user: a read for anyone else finds nothing. The stored
    # shuffle bags ride on the user document, as they do in Mongo.
    async def get_user(user_id: str) -> UserDocument | None:
        if user_id != w.user.id:
            return None
        w.user.briefing_shuffle_bags = {BriefingBag(k): v for k, v in w.bags.items()} or None
        return w.user

    monkeypatch.setattr(service.user_repository, "get", AsyncMock(side_effect=get_user))
    monkeypatch.setattr(service.briefing_repository, "was_delivered", w.was_delivered)
    monkeypatch.setattr(service.user_repository, "clear_briefing_bootstrap", w.clear_bootstrap)
    monkeypatch.setattr(service.dormancy, "clear_dormancy", w.clear_dormancy)
    monkeypatch.setattr(service.dormancy, "enter_dormancy", w.enter_dormancy)
    monkeypatch.setattr(service, "build_briefing_voice_prompt", w.voice_prompt)
    monkeypatch.setattr(service, "build_weekly_digest_prompt", w.weekly_prompt)

    async def model(**kwargs: Any) -> SimpleNamespace:
        reply = await w.agent(**kwargs)
        return SimpleNamespace(message=_message_written(kwargs["request"].message, reply.message))

    monkeypatch.setattr(service, "call_agent_silent", model)
    monkeypatch.setattr(service.briefing_repository, "list_recent", w.recent)
    monkeypatch.setattr(service.briefing_repository, "upsert_briefing", w.upsert)
    monkeypatch.setattr(service.briefing_repository, "set_delivered_channels", w.set_channels)
    monkeypatch.setattr(
        service.briefing_repository, "has_daily_briefing", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(service.notification_service, "create_notification", w.notify)
    monkeypatch.setattr(
        service,
        "resolve_chat_channel",
        AsyncMock(side_effect=lambda user_id: w.chat if user_id == _USER else None),
    )
    monkeypatch.setattr(service, "host_edition_image", w.host_image)
    monkeypatch.setattr(service, "post_to_platform_chat", w.post)
    monkeypatch.setattr(service, "capture", w.capture)
    monkeypatch.setattr(
        service.pending_brief_items_repository,
        "list_for_user",
        AsyncMock(side_effect=lambda *_, **__: list(w.held)),
    )
    monkeypatch.setattr(service.pending_brief_items_repository, "consume", w.consume)
    monkeypatch.setattr(
        service.chat_sync, "format_replies_block", AsyncMock(return_value="No replies.")
    )
    monkeypatch.setattr(
        service.context, "format_goal_block", AsyncMock(return_value=("Ship v2", True))
    )
    monkeypatch.setattr(
        service.context, "get_yesterday_payload", AsyncMock(return_value=sentinel.yesterday)
    )
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
    monkeypatch.setattr(service.dormancy, "latest_activity_since", AsyncMock(return_value=None))
    monkeypatch.setattr(
        service,
        "activity_status_of",
        AsyncMock(side_effect=lambda user_id: w.activity if user_id == _USER else None),
    )
    monkeypatch.setattr(
        service,
        "get_connected_integrations_named",
        AsyncMock(
            side_effect=lambda user_id: [{"id": a.lower(), "name": a} for a in w.connected_apps]
            if user_id == _USER
            else []
        ),
    )

    async def set_bag(user_id: str, bag: BriefingBag, state: ShuffleBag) -> None:
        assert user_id == _USER
        w.bags[bag.value] = state

    monkeypatch.setattr(service.user_repository, "set_briefing_bag", set_bag)
    monkeypatch.setattr(service.context, "gather_calendar", AsyncMock(return_value=[_EVENT]))
    monkeypatch.setattr(
        service.context,
        "gather_week",
        AsyncMock(return_value=BriefingWeek(days=[BriefingWeekDay(you=1, gaia=2)] * 7)),
    )
    with time_machine.travel(_NOW, tick=False):
        yield w


def _stored_payload(w: World) -> BriefingPayload:
    w.upsert.assert_awaited_once()
    return w.upsert.await_args.args[3]


def _prompt(w: World) -> str:
    return w.agent.await_args.kwargs["request"].message


def _assert_nothing_sent(w: World) -> None:
    w.upsert.assert_not_awaited()
    w.notify.assert_not_awaited()
    w.post.assert_not_awaited()
    w.consume.assert_not_awaited()


class TestDailyBrief:
    async def test_brief_is_stored_then_delivered_in_app_by_email_and_as_a_chat_image(
        self, world: World
    ) -> None:
        world.work = context.TrackedWork(
            blocked=[_todo("b1", "Approve the Priya reply")],
            completed=[_todo("c1", "Investor update")],
        )

        await service.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        assert payload.headline == "Your morning, sorted"
        assert payload.template_family in DAILY_FAMILY_WEIGHTS
        assert world.bags["edition_family"].order.count(payload.template_family) >= 1
        assert payload.calendar == [_EVENT]
        assert payload.tallies == BriefingTallies(done_by_you=1, done_by_gaia=0)
        assert "11:00: Sequoia" in _prompt(world)
        assert [(s.title, [i.text for i in s.items]) for s in payload.sections] == [
            ("Needs you", ["Approve the Priya reply"]),
            ("GAIA's work", ["Investor update"]),
        ]
        assert [i.todo_id for s in payload.sections for i in s.items] == ["b1", "c1"]
        message = _facts_shown(_prompt(world))
        assert payload.message == message
        assert world.upsert.await_args.kwargs["edition_image_url"] == _EDITION.display_url
        request = world.notify.await_args.args[0]
        assert request.metadata["edition_image_url"] == _EDITION.display_url
        assert request.content.actions[0].config.redirect.url == f"/brief/{_BRIEF_ID}"
        assert [c.channel_type for c in request.channels] == _ORCHESTRATED
        assert request.metadata["kind"] == NOTIFICATION_KIND_BRIEFING_DAILY
        assert request.content.body == message
        assert request.content.rich_content == payload.model_dump()
        world.host_image.assert_awaited_once()
        post = world.post.await_args.kwargs
        assert (post["channel"], post["image"].url) == (_CHAT, _EDITION.chat_url)
        assert split_message_bubbles(post["text"]) == [
            "Your morning, sorted",
            f"{message}\n\nFull brief: {service.full_brief_url(_BRIEF_ID)}",
        ]
        world.set_channels.assert_awaited_once()
        assert world.set_channels.await_args.args[3] == [*_ORCHESTRATED, "telegram"]

    async def test_without_a_chat_platform_nothing_is_posted(self, world: World) -> None:
        world.chat = None

        await service.run_daily_briefing(_USER)

        world.host_image.assert_awaited_once()
        world.post.assert_not_awaited()
        assert world.set_channels.await_args.args[3] == _ORCHESTRATED

    async def test_every_render_is_hosted_under_one_fresh_opaque_key(self, world: World) -> None:
        """The image URL goes out in emails and public links, so it names no user, kind or date."""
        await service.run_daily_briefing(_USER)
        await service.run_daily_briefing(_USER)

        keys = [c.kwargs["render_key"] for c in world.host_image.await_args_list]
        assert len(keys) == 2 and keys[0] != keys[1]
        assert re.fullmatch(r"[0-9a-f]{32}", keys[0])

    async def test_the_edition_is_addressed_to_the_user_by_name(self, world: World) -> None:
        await service.run_daily_briefing(_USER)

        assert _stored_payload(world).recipient_name == "Ada"
        assert "You're writing to Ada" in world.voice_prompt.call_args.kwargs["blocks"].reader

    async def test_a_user_who_gave_no_name_is_addressed_by_none(self, world: World) -> None:
        """Regression: the brief greeted "Dear Delivered", a name guessed from delivered+dev@resend.dev."""
        world.user = UserDocument(id=_USER, timezone=_TZ, email="delivered+dev@resend.dev")

        await service.run_daily_briefing(_USER)

        assert _stored_payload(world).recipient_name is None
        assert "writing to" not in world.voice_prompt.call_args.kwargs["blocks"].reader
        assert "Delivered" not in world.voice_prompt.call_args.kwargs["blocks"].context

    async def test_an_empty_day_stays_in_app_and_spends_no_draw(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing needs the user, nothing is on the calendar, nothing ran overnight."""
        world.work = context.TrackedWork()
        bags_before = dict(world.bags)
        monkeypatch.setattr(service.context, "gather_calendar", AsyncMock(return_value=[]))

        await service.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        assert payload.sections == [] and payload.calendar == []
        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == ["inapp"]
        world.post.assert_not_awaited()
        assert world.bags == bags_before

    async def test_email_is_left_out_when_the_user_turned_it_off(self, world: World) -> None:
        world.user = UserDocument(
            id=_USER, timezone="UTC", email="a@b.c", notification_channel_prefs={"email": False}
        )

        await service.run_daily_briefing(_USER)

        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == ["inapp"]

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
        seeded = world.bags["edition_family"].order

        await service.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        assert payload.template_family == "postal"
        # The stored pass was read and advanced, not reshuffled from scratch.
        assert world.bags["edition_family"] == ShuffleBag(order=seeded, index=1)
        assert payload.stamp_city in {"paris", "tokyo", "lima"}
        assert world.bags["stamp_city"].order[0] == payload.stamp_city

    async def test_a_brief_that_fails_to_deliver_keeps_both_bags_where_they_were(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A draw is spent only by a brief that went out: a failed run burns no member."""
        monkeypatch.setattr(service, "hosted_stamp_weights", lambda: {"paris": 1, "tokyo": 1})
        self._postal_first(world)
        family_before = world.bags["edition_family"]
        world.notify.side_effect = RuntimeError("orchestrator down")

        with pytest.raises(RuntimeError, match="orchestrator down"):
            await service.run_daily_briefing(_USER)

        assert world.bags["edition_family"] == family_before
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
        assert "2 lower-priority item(s) are not in this brief" in _prompt(world)

    async def test_voice_the_agent_botched_stores_and_sends_nothing(self, world: World) -> None:
        world.agent.return_value = SimpleNamespace(message="Sorry, something went wrong.")

        with pytest.raises(service.BriefingGenerationError):
            await service.run_daily_briefing(_USER)

        _assert_nothing_sent(world)

    async def test_unknown_user_fails_loud(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service.user_repository, "get", AsyncMock(return_value=None))

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
        world.post.assert_not_awaited()

    async def test_only_channels_that_reached_the_user_are_recorded_and_counted(
        self, world: World
    ) -> None:
        world.chat = None
        world.notify.return_value = SimpleNamespace(
            channels=[
                _delivered("inapp"),
                ChannelDeliveryStatus(channel_type="email", status=NotificationStatus.FAILED),
                ChannelDeliveryStatus(
                    channel_type="telegram", status=NotificationStatus.DELIVERED, skipped=True
                ),
            ]
        )

        await service.run_daily_briefing(_USER)

        assert world.set_channels.await_args.args[3] == ["inapp"]
        sent = world.capture.call_args.args[1]
        assert sent.channel_count == 1

    async def test_a_brief_already_delivered_today_is_not_sent_again(self, world: World) -> None:
        world.was_delivered.return_value = True

        outcome = await service.run_daily_briefing(_USER)

        assert outcome is BriefingRunOutcome.ALREADY_DELIVERED
        world.was_delivered.assert_awaited_once_with(_USER, _DATE, "daily")
        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    async def test_a_sent_brief_reports_it_was_sent(self, world: World) -> None:
        assert await service.run_daily_briefing(_USER) is BriefingRunOutcome.SENT


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

        assert await service.run_weekly_digest(_USER) is BriefingRunOutcome.SENT

        payload = _stored_payload(world)
        # Masthead and date come from code, whatever the model wrote.
        assert (payload.kicker, payload.date) == (WEEKLY_KICKER, _DATE)
        assert world.upsert.await_args.args[2] == "weekly"
        assert payload.template_family == "weekly"
        assert payload.week is not None
        assert payload.tallies == BriefingTallies(done_by_you=7, done_by_gaia=14)
        assert payload.headline == "A good week"
        request = world.notify.await_args.args[0]
        assert request.metadata["kind"] == NOTIFICATION_KIND_BRIEFING_WEEKLY
        assert request.content.body == "good week!"
        # The recap is always pushed: it reaches the chat app, not only the in-app page.
        assert world.post.await_args.kwargs["origin"] == "weekly brief"
        world.consume.assert_not_awaited()

    async def test_a_recap_already_delivered_today_is_not_sent_again(self, world: World) -> None:
        world.was_delivered.return_value = True

        assert await service.run_weekly_digest(_USER) is BriefingRunOutcome.ALREADY_DELIVERED

        world.was_delivered.assert_awaited_once_with(_USER, _DATE, "weekly")
        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    async def test_recap_over_the_item_cap_fails_and_sends_nothing(self, world: World) -> None:
        world.agent.return_value = SimpleNamespace(message=_fenced(_weekly(MAX_BRIEF_ITEMS + 1)))

        with pytest.raises(service.BriefingGenerationError, match="at most"):
            await service.run_weekly_digest(_USER)

        _assert_nothing_sent(world)

    @pytest.mark.parametrize("message", [None, ""])
    async def test_a_recap_without_a_message_fails_and_sends_nothing(
        self, world: World, message: str | None
    ) -> None:
        world.agent.return_value = SimpleNamespace(
            message=_fenced({**_weekly(3), "message": message})
        )

        with pytest.raises(service.BriefingGenerationError, match="no message"):
            await service.run_weekly_digest(_USER)

        _assert_nothing_sent(world)


class TestHeldItemsJoinTheBrief:
    """Results held for the brief become one section of it.

    The held results come from brief-delivery workflows; each
    appears once and is cleared once the brief went out.
    """

    async def test_held_items_are_a_section_between_needs_you_and_gaias_work(
        self, world: World
    ) -> None:
        world.work = context.TrackedWork(
            blocked=[_todo("b1", "Approve the Priya reply")],
            completed=[_todo("c1", "Investor update")],
        )
        world.held = [_held("h1", "Paper digest", _DIGEST_REPORT)]

        await service.run_daily_briefing(_USER)

        assert [(s.title, [i.text for i in s.items]) for s in _stored_payload(world).sections] == [
            ("Needs you", ["Approve the Priya reply"]),
            ("While you were away", ["Paper digest: 3 new papers on retrieval"]),
            ("GAIA's work", ["Investor update"]),
        ]
        # The headline and lede are voiced from the items, so a report's body never
        # reaches the prompt to be claimed from.
        assert "Paper digest: 3 new papers on retrieval" in _prompt(world)
        assert "two cite your draft" not in _prompt(world)
        world.consume.assert_awaited_once_with(_USER, ["h1"])

    async def test_an_item_already_in_the_brief_is_shown_once_and_still_cleared(
        self, world: World
    ) -> None:
        world.work = context.TrackedWork(completed=[_todo("c1", "Digest: 3 new papers")])
        world.held = [
            _held("h1", "Digest", "3 new papers\nmore detail"),
            _held("h2", "Paper digest", _DIGEST_REPORT),
            _held("h3", "Paper  digest", _DIGEST_REPORT),
        ]

        await service.run_daily_briefing(_USER)

        texts = [i.text for s in _stored_payload(world).sections for i in s.items]
        assert texts == ["Paper digest: 3 new papers on retrieval", "Digest: 3 new papers"]
        world.consume.assert_awaited_once()
        assert world.consume.await_args.args[0] == _USER
        assert sorted(world.consume.await_args.args[1]) == ["h1", "h2", "h3"]

    async def test_held_items_the_cap_leaves_out_wait_for_the_next_brief(
        self, world: World
    ) -> None:
        world.work = context.TrackedWork(
            blocked=[_todo(f"b{i}", f"Blocked {i}") for i in range(MAX_BRIEF_ITEMS - 1)]
        )
        world.held = [_held("h1", "Digest", "first"), _held("h2", "Paper digest", "second")]

        await service.run_daily_briefing(_USER)

        texts = [i.text for s in _stored_payload(world).sections for i in s.items]
        assert texts[-1] == "Digest: first"
        assert "1 lower-priority item(s) are not in this brief" in _prompt(world)
        world.consume.assert_awaited_once_with(_USER, ["h1"])

    async def test_gaias_work_fills_only_the_room_needs_you_and_held_results_leave(
        self, world: World
    ) -> None:
        world.work = context.TrackedWork(
            blocked=[_todo(f"b{i}", f"Blocked {i}") for i in range(5)],
            running=[_todo(f"r{i}", f"Running {i}") for i in range(3)],
        )
        world.held = [_held("h1", "Digest", "first"), _held("h2", "Paper digest", "second")]

        await service.run_daily_briefing(_USER)

        sections = _stored_payload(world).sections
        assert [(s.title, len(s.items)) for s in sections] == [
            ("Needs you", 5),
            ("While you were away", 2),
            ("GAIA's work", 1),
        ]
        assert "2 lower-priority item(s) are not in this brief" in _prompt(world)

    async def test_a_failed_delivery_clears_nothing(self, world: World) -> None:
        world.held = [_held("h1", "Paper digest", _DIGEST_REPORT)]
        world.notify.side_effect = RuntimeError("orchestrator down")

        with pytest.raises(RuntimeError):
            await service.run_daily_briefing(_USER)

        world.consume.assert_not_awaited()


def _voiced(headline: str, lede: str) -> SimpleNamespace:
    return SimpleNamespace(message=_fenced({**_VOICE, "headline": headline, "lede": lede}))


_LIVE_CONTRADICTION = _voiced(
    "Arjun's contract redlines need you today",
    "The Inbox desk also flagged 2 items needing you, and 1 event today.",
)


class TestTheProseMatchesTheItems:
    """The headline and lede are checked against the final items before anything renders.

    Regression: a live brief's headline named a need over an empty needs-you section and
    its lede counted an event over an empty calendar.
    """

    async def test_a_contradicting_voice_is_regenerated_once_with_the_problems(
        self, world: World
    ) -> None:
        world.work = context.TrackedWork(completed=[_todo("c1", "Investor update")])
        world.agent.side_effect = [
            _LIVE_CONTRADICTION,
            _voiced("The investor update is done", "Nothing on the calendar today."),
        ]

        await service.run_daily_briefing(_USER)

        assert world.agent.await_count == 2
        retry = world.agent.await_args_list[1].kwargs["request"].message
        assert "no item needs them" in retry
        assert _stored_payload(world).headline == "The investor update is done"

    async def test_a_voice_that_contradicts_twice_fails_and_sends_nothing(
        self, world: World
    ) -> None:
        world.work = context.TrackedWork(completed=[_todo("c1", "Investor update")])
        world.agent.side_effect = [_LIVE_CONTRADICTION, _LIVE_CONTRADICTION]

        with pytest.raises(service.BriefingGenerationError, match="needs them; the prose"):
            await service.run_daily_briefing(_USER)

        _assert_nothing_sent(world)

    async def test_a_count_the_model_was_shown_may_be_voiced(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: 5 open todos were shown to the model, then rejected when it said 5."""
        monkeypatch.setattr(
            service.context, "user_open_todo_summary", AsyncMock(return_value=(5, ["Gym"]))
        )
        monkeypatch.setattr(service.context, "gather_calendar", AsyncMock(return_value=[]))
        world.agent.return_value = _voiced("5 open todos, a quiet morning", "Nothing else today.")

        await service.run_daily_briefing(_USER)

        assert "[COUNTS] your open todos: 5\n" in _prompt(world)
        assert world.agent.await_count == 1
        assert _stored_payload(world).headline == "5 open todos, a quiet morning"

    async def test_a_count_the_model_was_not_shown_is_still_rejected(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            service.context, "user_open_todo_summary", AsyncMock(return_value=(5, []))
        )
        world.agent.return_value = _voiced("6 open todos", "A quiet morning.")

        with pytest.raises(service.BriefingGenerationError, match="counts 6"):
            await service.run_daily_briefing(_USER)

        _assert_nothing_sent(world)


def _wrote(message: str) -> SimpleNamespace:
    return SimpleNamespace(message=_fenced({**_VOICE, "message": message}))


_SKIPS_PRIYA = _wrote("Sequoia at 11:00, and the investor update went out.")


class TestTheMessageCoversTheDay:
    """The written message is checked for everything waiting on the user and every event."""

    async def test_a_message_that_skips_a_need_is_regenerated_with_it_named(
        self, world: World
    ) -> None:
        world.work = _brief_work()
        world.agent.side_effect = [_SKIPS_PRIYA, _wrote(_FACTS_SHOWN)]

        await service.run_daily_briefing(_USER)

        assert world.agent.await_count == 2
        retry = world.agent.await_args_list[1].kwargs["request"].message
        assert "never mentions 'Approve the Priya reply'" in retry
        assert _stored_payload(world).message == _facts_shown(_prompt(world))

    async def test_a_message_that_skips_a_need_twice_fails_and_sends_nothing(
        self, world: World
    ) -> None:
        world.work = _brief_work()
        world.agent.side_effect = [_SKIPS_PRIYA, _SKIPS_PRIYA]

        with pytest.raises(service.BriefingGenerationError, match="Priya"):
            await service.run_daily_briefing(_USER)

        _assert_nothing_sent(world)

    async def test_a_winback_note_need_not_cover_everything(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.work = _brief_work()
        monkeypatch.setattr(
            service.context,
            "compute_winback_state",
            AsyncMock(
                return_value=context.WinbackState(
                    unacknowledged=WINBACK_THRESHOLD, last_was_winback=False
                )
            ),
        )
        world.agent.return_value = _wrote("The investor update is still sitting here, want it?")

        await service.run_daily_briefing(_USER)

        assert world.agent.await_count == 1
        assert _stored_payload(world).mood == "winback"

    async def test_the_model_sees_how_recent_briefs_opened(self, world: World) -> None:
        def brief(message: str | None) -> BriefingModel:
            payload = BriefingPayload.model_validate(
                {**_weekly(0), "mood": "packed", "message": message}
            )
            return BriefingModel(id="b", user_id=_USER, date="2026-10-13", payload=payload)

        world.recent.return_value = [brief("\n  Priya replied overnight.\nMore."), brief(None)]

        await service.run_daily_briefing(_USER)

        world.recent.assert_awaited_once_with(_USER, limit=5, kind="daily")
        assert "HOW YOUR LAST BRIEFS OPENED" in _prompt(world)
        assert "- Priya replied overnight.\n" in _prompt(world)


class TestOneSubjectIsOneItem:
    """Regression: three approval requests for one Acme MSA renewal became one line with three links."""

    async def test_todos_with_the_same_title_reach_the_model_and_the_page_as_one_counted_item(
        self, world: World
    ) -> None:
        world.work = context.TrackedWork(
            blocked=[
                _todo("b1", "Approve the Acme MSA renewal"),
                _todo("b2", "Approve the Acme MSA renewal"),
                _todo("b3", "approve the  Acme MSA renewal"),
                _todo("b4", "Reply to Daniel"),
            ]
        )

        await service.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        items = [(it.text, it.todo_id, it.count) for s in payload.sections for it in s.items]
        assert items == [("Approve the Acme MSA renewal", "b1", 3), ("Reply to Daniel", "b4", 1)]
        facts = _facts_shown(_prompt(world))
        assert facts.count("Acme MSA renewal") == 1
        assert "Approve the Acme MSA renewal | 3 requests, one item" in facts
        assert "Reply to Daniel | 1 requests" not in facts
        assert "waiting on you: 2" in facts
        assert [(s.value, s.label) for s in payload.stats] == [("2", "waiting on you")]

    async def test_subtasks_of_one_parent_are_one_item(self, world: World) -> None:
        world.work = context.TrackedWork(
            blocked=[
                TodoDocument(
                    id=f"b{n}",
                    user_id=_USER,
                    title=title,
                    labels=[GAIA_TRACKED_LABEL],
                    parent_todo_id="acme",
                )
                for n, title in enumerate(["Approve the Acme MSA", "Sign the Acme order form"])
            ]
        )

        await service.run_daily_briefing(_USER)

        items = [(it.text, it.count) for s in _stored_payload(world).sections for it in s.items]
        assert items == [("Approve the Acme MSA", 2)]


def _brief_work() -> context.TrackedWork:
    return context.TrackedWork(
        blocked=[_todo("b1", "Approve the Priya reply")],
        completed=[_todo("c1", "Investor update")],
    )


class TestTheDailyRunWiring:
    """Every read is scoped to the user and the last local day, and every write records it."""

    async def test_every_read_is_for_this_user_and_the_last_local_day(self, world: World) -> None:
        await service.run_daily_briefing(_USER)

        ctx = service.context
        ctx.format_goal_block.assert_awaited_once_with(_USER, world.user)
        ctx.get_yesterday_payload.assert_awaited_once_with(_USER, before_date=_DATE)
        ctx.format_lookback_block.assert_awaited_once_with(_USER, sentinel.yesterday, _DAY_START)
        assert ctx.compute_winback_state.await_args.args[0].id == _USER
        service.briefing_repository.has_daily_briefing.assert_awaited_once_with(_USER)
        ctx.gather_tracked_work.assert_awaited_once_with(_USER, _DAY_START)
        ctx.user_open_todo_summary.assert_awaited_once_with(_USER)
        ctx.gather_completed_since.assert_awaited_once_with(_USER, _DAY_START)
        calendar_call = ctx.gather_calendar.await_args
        assert calendar_call.args[0] == _USER and calendar_call.kwargs == {"days": 1}
        assert (calendar_call.args[1].date_str, calendar_call.args[1].tz.key) == (_DATE, _TZ)
        service.pending_brief_items_repository.list_for_user.assert_awaited_once_with(
            _USER, sort=[("created_at", 1)]
        )
        service.chat_sync.format_replies_block.assert_awaited_once_with(_USER, _DAY_START)
        service.dormancy.record_idle_day.assert_awaited_once_with(
            _USER, service.dormancy.state_from_user(world.user), False, _DATE
        )
        prompt_args = world.voice_prompt.call_args.kwargs
        assert prompt_args["date_local"] == _DATE
        assert (
            prompt_args["blocks"].goal,
            prompt_args["blocks"].lookback,
            prompt_args["blocks"].replies,
        ) == ("Ship v2", "-", "No replies.")
        assert prompt_args["situation"].is_first_briefing is False
        assert prompt_args["situation"].winback is False
        assert prompt_args["situation"].wind_down is None

    async def test_a_users_first_brief_is_voiced_as_their_first(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            service.briefing_repository, "has_daily_briefing", AsyncMock(return_value=False)
        )

        await service.run_daily_briefing(_USER)

        assert world.voice_prompt.call_args.kwargs["situation"].is_first_briefing is True

    async def test_the_agent_runs_once_in_the_background_on_a_fresh_daily_thread(
        self, world: World
    ) -> None:
        await service.run_daily_briefing(_USER)

        call = world.agent.await_args.kwargs
        request = call["request"]
        assert [(m["role"], m["content"]) for m in request.messages] == [("user", request.message)]
        assert re.fullmatch(
            rf"briefing-daily-{_USER}-{_DATE}-[0-9a-f]{{6}}", call["conversation_id"]
        )
        assert (call["user"].user_id, call["user"].timezone) == (_USER, _TZ)
        assert call["options"].trigger_context == {"execution_mode": "background"}
        assert call["options"].source == "briefing"

    async def test_the_brief_is_dated_and_stamped_in_the_users_timezone(self, world: World) -> None:
        world.work = _brief_work()

        await service.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        assert (payload.kicker, payload.date, payload.generated_at) == (
            "THE MORNING BRIEF",
            _DATE,
            "7:05 AM",
        )
        assert payload.hue == 79
        assert payload.mood == "packed"
        assert payload.caption == "Onward."
        assert payload.message == _facts_shown(_prompt(world))
        assert [(s.value, s.label) for s in payload.stats] == [
            ("1", "done since yesterday"),
            ("1", "waiting on you"),
        ]

    async def test_a_zero_count_is_never_shown_to_the_model(self, world: World) -> None:
        world.work = context.TrackedWork(running=[_todo("r1", "Research")])

        await service.run_daily_briefing(_USER)

        assert "[COUNTS] in progress: 1\n" in _prompt(world)

    async def test_delivery_opens_the_brief_and_posts_the_image_as_the_daily_brief(
        self, world: World
    ) -> None:
        world.work = _brief_work()

        await service.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        assert [c.args[0] for c in world.host_image.await_args_list] == [payload]
        request = world.notify.await_args.args[0]
        assert request.priority == 2
        action = request.content.actions[0]
        assert (action.label, action.style) == ("Open briefing", "primary")
        redirect = action.config.redirect
        assert (redirect.open_in_new_tab, redirect.close_notification) == (False, True)
        assert (request.metadata["briefing_id"], request.metadata["date"]) == (_BRIEF_ID, _DATE)
        post = world.post.await_args.kwargs
        assert post["user"].user_id == _USER
        assert (post["origin"], post["image"].filename) == ("daily brief", "gaia-daily-brief.jpg")
        assert post["message_class"] is ProactiveMessageClass.ROUTINE

    async def test_a_sent_brief_records_its_channels_and_reports_one_event(
        self, world: World
    ) -> None:
        world.work = _brief_work()

        await service.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        channels = [*_ORCHESTRATED, "telegram"]
        world.set_channels.assert_awaited_once_with(_USER, _DATE, "daily", channels)
        world.capture.assert_called_once_with(
            UserId(_USER),
            BriefingSent(
                kind="daily",
                family=payload.template_family or "",
                mood="packed",
                item_count=2,
                channel_count=3,
            ),
        )

    async def test_the_run_is_tagged_on_its_wide_event(self, world: World) -> None:
        async with captured_wide_event() as event:
            await service.run_daily_briefing(_USER)

        assert (event["component"], event["operation"], event["user_id"]) == (
            "briefing",
            "run_daily_briefing",
            _USER,
        )

    @pytest.mark.parametrize("email", [None, "   "])
    async def test_email_is_left_out_without_an_address(
        self, world: World, email: str | None
    ) -> None:
        world.user = UserDocument(id=_USER, timezone=_TZ, email=email)

        await service.run_daily_briefing(_USER)

        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == ["inapp"]


class TestTheFactsTheModelVoices:
    """The facts block is the whole truth the model may voice, built by code."""

    async def test_counts_and_one_line_per_item_with_its_artifact(self, world: World) -> None:
        blocked = _todo("b1", "Approve the reply")
        blocked.canvas_content = "Draft ready"
        world.work = context.TrackedWork(
            blocked=[blocked],
            failed=[_todo("f1", "Sync"), _todo("f2", "Scrape")],
            completed=[_todo("c1", "Deck")],
            running=[_todo("r1", "Research"), _todo("r2", "Outreach")],
        )
        world.held = [_held("h1", "Digest", "first")]

        await service.run_daily_briefing(_USER)

        assert (
            "[COUNTS] waiting on you: 3 · done: 1 · in progress: 2 · while you were away: 1\n"
            "[Needs you]\n"
            "- Waiting on you: Approve the reply | summary: Draft ready"
            " | artifact holds ~11 chars | waiting on you\n"
            "- Failed: Sync | artifact holds ~0 chars\n"
            "- Failed: Scrape | artifact holds ~0 chars\n"
            "[While you were away]\n"
            "- Note: Digest: first\n"
            "[GAIA's work]\n"
            "- Done: Deck | artifact holds ~0 chars\n"
            "- In progress: Research | artifact holds ~0 chars\n"
            "- In progress: Outreach | artifact holds ~0 chars\n"
            "The user's own todo list is empty."
        ) in _prompt(world)
        assert "lower-priority" not in _prompt(world)
        assert "GAIA has no tracked work" not in _prompt(world)
        assert [(s.value, s.label) for s in _stored_payload(world).stats] == [
            ("1", "done since yesterday"),
            ("2", "in progress"),
            ("1", "waiting on you"),
        ]

    async def test_a_summary_drops_headings_comments_tables_and_rules(self, world: World) -> None:
        doc = _todo("c1", "Deck")
        doc.canvas_content = (
            "# Title\n  ## Indented heading\n<!-- hidden -->\n| a | b |\n---\n\n"
            "First line\n   \nSecond line"
        )
        cut = _todo("c2", "Long")
        cut.canvas_content = "x" * 239 + " yz"
        world.work = context.TrackedWork(completed=[doc, cut])

        await service.run_daily_briefing(_USER)

        assert "- Done: Deck | summary: First line Second line | artifact holds" in _prompt(world)
        assert f"- Done: Long | summary: {'x' * 239} | artifact holds" in _prompt(world)

    async def test_the_size_hint_counts_the_deliverable_not_its_logs(self, world: World) -> None:
        doc = _todo("c1", "Pick a forum")
        doc.canvas_content = (
            "Intro line\n<!-- note -->\n\n## Result\nDecision made\n"
            "## Activity Log\nstep one\n\nstep two\n## timeline\nx"
        )
        world.work = context.TrackedWork(completed=[doc])

        await service.run_daily_briefing(_USER)

        assert "| artifact holds ~24 chars" in _prompt(world)

    async def test_a_todo_in_two_states_keeps_its_first_artifact(self, world: World) -> None:
        first, again, blocked = _todo("c1", "Deck"), _todo("c1", "Deck"), _todo("b1", "Reply")
        first.canvas_content, again.canvas_content, blocked.canvas_content = "One", "Two", "Three"
        world.work = context.TrackedWork(completed=[first], running=[again], blocked=[blocked])

        await service.run_daily_briefing(_USER)

        prompt = _prompt(world)
        assert "- Done: Deck | summary: One | artifact holds ~3 chars\n" in prompt
        assert "- In progress: Deck | summary: One | artifact holds ~3 chars\n" in prompt
        assert (
            "- Waiting on you: Reply | summary: Three | artifact holds ~5 chars | waiting" in prompt
        )

    async def test_with_nothing_tracked_the_model_is_told_nothing_ran(self, world: World) -> None:
        await service.run_daily_briefing(_USER)

        assert "\n[COUNTS]" not in _prompt(world)
        assert (
            "GAIA has no tracked work and no background work ran. Do not claim anything "
            "ran, finished, or is pending beyond what is stated here.\n"
            "The user's own todo list is empty.\n"
            "Today's calendar (user-local 24h times):\n- 11:00: Sequoia"
        ) in _prompt(world)

    @pytest.mark.parametrize(
        ("summary", "counts", "note"),
        [
            (
                (2, ["Gym", "Taxes"]),
                "[COUNTS] your open todos: 2\n",
                "The user's own open todos (first few: Gym; Taxes) are counted in [COUNTS]"
                "; never voice that list as clear or empty.\n",
            ),
            (
                (3, []),
                "[COUNTS] your open todos: 3\n",
                "The user's own open todos are counted in [COUNTS]"
                "; never voice that list as clear or empty.\n",
            ),
        ],
    )
    async def test_the_users_own_todos_are_counted(
        self,
        world: World,
        monkeypatch: pytest.MonkeyPatch,
        summary: tuple[int, list[str]],
        counts: str,
        note: str,
    ) -> None:
        monkeypatch.setattr(
            service.context, "user_open_todo_summary", AsyncMock(return_value=summary)
        )

        await service.run_daily_briefing(_USER)

        assert counts in _prompt(world)
        assert note in _prompt(world)

    async def test_an_untimed_event_reads_all_day_and_none_reads_empty(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        offsite = BriefingEvent(date=_DATE, title="Offsite")
        monkeypatch.setattr(
            service.context, "gather_calendar", AsyncMock(return_value=[offsite, _EVENT])
        )
        await service.run_daily_briefing(_USER)
        assert (
            "is empty.\nToday's calendar (user-local 24h times):\n"
            "- all day: Offsite\n- 11:00: Sequoia\n\n## YESTERDAY"
        ) in _prompt(world)

        monkeypatch.setattr(service.context, "gather_calendar", AsyncMock(return_value=[]))
        await service.run_daily_briefing(_USER)
        assert (
            "is empty.\nThe user's calendar has nothing today (or no calendar is connected)."
            "\n\n## YESTERDAY"
        ) in _prompt(world)

    async def test_a_held_result_with_a_blank_report_shows_only_its_source(
        self, world: World
    ) -> None:
        world.held = [_held("h1", "Digest", "  \n ")]

        await service.run_daily_briefing(_USER)

        assert [i.text for s in _stored_payload(world).sections for i in s.items] == ["Digest: "]


class TestTheGoalHold:
    """An existing user's first brief waits for a goal, but only through the grace window."""

    @staticmethod
    def _pending(world: World, since: datetime) -> None:
        world.user = UserDocument(
            id=_USER,
            timezone=_TZ,
            email="a@b.c",
            briefing_bootstrap=BriefingBootstrap(pending=True, since=since),
        )

    @staticmethod
    def _no_goal(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            service.context, "format_goal_block", AsyncMock(return_value=("", False))
        )

    @pytest.mark.parametrize(
        "since", [_NOW - timedelta(days=1), (_NOW - timedelta(days=1)).replace(tzinfo=None)]
    )
    async def test_inside_the_grace_window_without_a_goal_nothing_is_sent(
        self, world: World, monkeypatch: pytest.MonkeyPatch, since: datetime
    ) -> None:
        self._pending(world, since)
        self._no_goal(monkeypatch)

        await service.run_daily_briefing(_USER)

        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    @pytest.mark.parametrize("age", [timedelta(days=3), timedelta(days=4)])
    async def test_once_the_grace_window_has_passed_the_brief_goes_out(
        self, world: World, monkeypatch: pytest.MonkeyPatch, age: timedelta
    ) -> None:
        self._pending(world, _NOW - age)
        self._no_goal(monkeypatch)

        await service.run_daily_briefing(_USER)

        world.upsert.assert_awaited_once()
        world.clear_bootstrap.assert_awaited_once_with(_USER)

    async def test_a_known_goal_releases_the_hold_and_clears_it(self, world: World) -> None:
        self._pending(world, _NOW - timedelta(hours=1))

        await service.run_daily_briefing(_USER)

        world.upsert.assert_awaited_once()
        world.clear_bootstrap.assert_awaited_once_with(_USER)

    async def test_a_hold_already_released_does_not_wait(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.user = UserDocument(
            id=_USER,
            timezone=_TZ,
            briefing_bootstrap=BriefingBootstrap(pending=False, since=_NOW),
        )
        self._no_goal(monkeypatch)

        await service.run_daily_briefing(_USER)

        world.upsert.assert_awaited_once()

    async def test_a_user_never_held_has_nothing_to_clear(self, world: World) -> None:
        await service.run_daily_briefing(_USER)

        world.clear_bootstrap.assert_not_awaited()


_DORMANT_SINCE = datetime(2026, 10, 1, tzinfo=UTC)


def _dormant(world: World) -> None:
    world.user = UserDocument(
        id=_USER,
        timezone=_TZ,
        email="a@b.c",
        briefing_dormancy=BriefingDormancy(idle_days=3, dormant_since=_DORMANT_SINCE),
    )


class TestTheIdleLadder:
    """Nothing to report escalates to a warning, then one goodbye, then dormancy."""

    async def test_a_dormant_user_who_came_back_is_woken_and_briefed(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _dormant(world)
        monkeypatch.setattr(service.dormancy, "latest_activity_since", AsyncMock(return_value=_NOW))

        await service.run_daily_briefing(_USER)

        (user_id, since), _ = service.dormancy.latest_activity_since.await_args
        assert (user_id, since) == (_USER, _DORMANT_SINCE)
        world.clear_dormancy.assert_awaited_once_with(_USER)
        assert service.dormancy.record_idle_day.await_args.args[1] == DormancyState(
            idle_days=0, date=None, dormant_since=None
        )
        world.upsert.assert_awaited_once()

    @pytest.mark.parametrize(
        ("work", "held", "has_goal", "idle"),
        [
            (context.TrackedWork(), [], False, True),
            (_brief_work(), [], False, False),
            (context.TrackedWork(), [_held("h1", "Digest", "first")], False, False),
            (context.TrackedWork(), [], True, False),
        ],
    )
    async def test_a_day_is_idle_only_with_no_work_no_held_results_and_no_goal(
        self,
        world: World,
        monkeypatch: pytest.MonkeyPatch,
        work: context.TrackedWork,
        held: list[PendingBriefItemDocument],
        has_goal: bool,
        idle: bool,
    ) -> None:
        world.work, world.held = work, held
        monkeypatch.setattr(
            service.context, "format_goal_block", AsyncMock(return_value=("", has_goal))
        )

        await service.run_daily_briefing(_USER)

        assert service.dormancy.record_idle_day.await_args.args[2] is idle

    @pytest.mark.parametrize(("idle_days", "stage"), [(2, "warn"), (3, "final")])
    async def test_the_idle_streak_sets_the_wind_down_and_the_goodbye_goes_dormant(
        self, world: World, monkeypatch: pytest.MonkeyPatch, idle_days: int, stage: str
    ) -> None:
        monkeypatch.setattr(
            service.context, "format_goal_block", AsyncMock(return_value=("", False))
        )
        monkeypatch.setattr(service.dormancy, "record_idle_day", AsyncMock(return_value=idle_days))

        await service.run_daily_briefing(_USER)

        assert world.voice_prompt.call_args.kwargs["situation"].wind_down == stage
        if stage == "final":
            world.enter_dormancy.assert_awaited_once_with(_USER)
        else:
            world.enter_dormancy.assert_not_awaited()

    async def test_the_wind_down_message_is_pushed_even_on_an_empty_day(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            service.context, "format_goal_block", AsyncMock(return_value=("", False))
        )
        monkeypatch.setattr(service.dormancy, "record_idle_day", AsyncMock(return_value=2))
        monkeypatch.setattr(service.context, "gather_calendar", AsyncMock(return_value=[]))

        await service.run_daily_briefing(_USER)

        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == _ORCHESTRATED
        world.post.assert_awaited_once()

    async def test_a_long_streak_with_work_to_report_does_not_wind_down(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service.dormancy, "record_idle_day", AsyncMock(return_value=5))

        await service.run_daily_briefing(_USER)

        assert world.voice_prompt.call_args.kwargs["situation"].wind_down is None
        world.enter_dormancy.assert_not_awaited()

    @pytest.mark.parametrize(("idle_days", "voiced_winback"), [(0, True), (3, False)])
    async def test_a_winback_is_voiced_unless_the_brief_is_winding_down(
        self,
        world: World,
        monkeypatch: pytest.MonkeyPatch,
        idle_days: int,
        voiced_winback: bool,
    ) -> None:
        monkeypatch.setattr(
            service.context,
            "compute_winback_state",
            AsyncMock(
                return_value=context.WinbackState(
                    unacknowledged=WINBACK_THRESHOLD, last_was_winback=False
                )
            ),
        )
        monkeypatch.setattr(
            service.context, "format_goal_block", AsyncMock(return_value=("", False))
        )
        monkeypatch.setattr(service.dormancy, "record_idle_day", AsyncMock(return_value=idle_days))

        await service.run_daily_briefing(_USER)

        assert world.voice_prompt.call_args.kwargs["situation"].winback is voiced_winback
        assert _stored_payload(world).mood == "winback"


def _idle_day(monkeypatch: pytest.MonkeyPatch, streak: int) -> None:
    """Make today a day with nothing to report, at the given idle streak."""
    monkeypatch.setattr(service.context, "format_goal_block", AsyncMock(return_value=("", False)))
    monkeypatch.setattr(service.dormancy, "record_idle_day", AsyncMock(return_value=streak))


class TestTheFirstWeek:
    """A new account's first week helps it get value instead of winding down."""

    async def test_a_first_week_account_never_climbs_the_idle_ladder(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.user.created_at = _NOW - timedelta(days=FIRST_WEEK_DAYS, seconds=-1)
        _idle_day(monkeypatch, IDLE_DORMANT_DAYS)

        await service.run_daily_briefing(_USER)

        assert service.dormancy.record_idle_day.await_args.args[2] is False
        assert world.voice_prompt.call_args.kwargs["situation"].wind_down is None
        assert world.voice_prompt.call_args.kwargs["situation"].first_week is True
        world.enter_dormancy.assert_not_awaited()

    async def test_the_ladder_runs_once_the_first_week_is_over(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.user.created_at = _NOW - timedelta(days=FIRST_WEEK_DAYS)
        _idle_day(monkeypatch, IDLE_DORMANT_DAYS)

        await service.run_daily_briefing(_USER)

        assert service.dormancy.record_idle_day.await_args.args[2] is True
        assert world.voice_prompt.call_args.kwargs["situation"].wind_down == "final"
        assert world.voice_prompt.call_args.kwargs["situation"].first_week is False
        world.enter_dormancy.assert_awaited_once_with(_USER)

    @pytest.mark.parametrize(
        ("apps", "line"),
        [(["Gmail", "Notion"], "Apps they've connected: Gmail, Notion."), ([], "none yet")],
    )
    async def test_a_first_week_brief_sees_the_apps_actually_connected(
        self, world: World, apps: list[str], line: str
    ) -> None:
        world.user.created_at = _NOW - timedelta(days=1)
        world.connected_apps = apps

        await service.run_daily_briefing(_USER)

        assert "THEIR GAIA SETUP" in _prompt(world)
        assert line in _prompt(world)

    async def test_an_older_account_is_shown_no_setup(self, world: World) -> None:
        world.user.created_at = _NOW - timedelta(days=30)
        world.connected_apps = ["Gmail"]

        await service.run_daily_briefing(_USER)

        assert "THEIR GAIA SETUP" not in _prompt(world)


class TestTheLighterCadenceOffer:
    """A user who stopped coming back is offered fewer briefs, with their real cadence."""

    async def test_an_idle_user_is_offered_a_lighter_cadence(self, world: World) -> None:
        world.activity = ActivityStatus.IDLE
        world.user.briefing_schedule = BriefingSchedule(
            frequency=BriefingFrequency.WEEKDAYS, hour=9
        )

        await service.run_daily_briefing(_USER)

        assert world.voice_prompt.call_args.kwargs["situation"].offer_lighter_cadence is True
        assert "a daily brief Monday to Friday at 09:00" in _prompt(world)
        assert "offer a lighter rhythm" in _prompt(world)

    async def test_an_active_user_is_not(self, world: World) -> None:
        await service.run_daily_briefing(_USER)

        assert world.voice_prompt.call_args.kwargs["situation"].offer_lighter_cadence is False
        assert "offer a lighter rhythm" not in _prompt(world)


_NOISE_BLOCKS = '```json\n\n```\n```json\n{oops\n```\n```json\n{"a": 1}\n```\n'


class TestTheAgentOutput:
    """The model's text must hold one valid JSON object; anything else fails loudly."""

    async def test_the_voice_is_found_past_empty_malformed_and_foreign_blocks(
        self, world: World
    ) -> None:
        world.agent.return_value = SimpleNamespace(message=_NOISE_BLOCKS + _fenced(_VOICE))

        await service.run_daily_briefing(_USER)

        assert _stored_payload(world).headline == "Your morning, sorted"

    async def test_a_missing_voice_names_the_start_of_what_came_back(self, world: World) -> None:
        raw = "y" * 400
        world.agent.return_value = SimpleNamespace(message=raw)

        with pytest.raises(service.BriefingGenerationError) as err:
            await service.run_daily_briefing(_USER)

        assert str(err.value) == (
            f"No valid voice JSON in agent output (first 300 chars): {raw[:300]!r}"
        )

    async def test_a_lede_alone_contradicting_the_items_is_sent_back(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service.context, "gather_calendar", AsyncMock(return_value=[]))
        world.work = context.TrackedWork(completed=[_todo("c1", "Investor update")])
        world.agent.side_effect = [
            _voiced("The investor update is done", "You have a meeting at noon."),
            _voiced("The investor update is done", "Nothing else today."),
        ]
        problem = "the prose mentions an event, but today's calendar is empty"

        async with captured_wide_event() as event:
            await service.run_daily_briefing(_USER)

        assert world.agent.await_count == 2
        assert problem in world.agent.await_args_list[1].kwargs["request"].message
        warning = {"msg": "briefing.voice_contradicted_items", "problems": [problem]}
        assert warning in event["warnings"]


def _weekly_completed() -> context.CompletedWork:
    deck = _todo("g0", "Deck")
    deck.canvas_content = "# Deck\nFinal numbers in"
    gaia = [deck, _todo("g1", ""), *[_todo(f"g{i}", f"G{i}") for i in range(2, 16)]]
    user = [_todo("u0", ""), *[_todo(f"u{i}", f"U{i}") for i in range(1, 16)]]
    return context.CompletedWork(gaia=gaia, user=user)


class TestTheWeeklyRunWiring:
    async def test_the_week_is_read_for_this_user_and_summarised_for_the_model(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            service.context, "gather_completed_since", AsyncMock(return_value=_weekly_completed())
        )
        world.agent.return_value = SimpleNamespace(message=_fenced(_weekly(3)))

        async with captured_wide_event() as event:
            await service.run_weekly_digest(_USER)

        service.context.gather_completed_since.assert_awaited_once_with(_USER, _WEEK_START)
        week_call = service.context.gather_week.await_args
        assert (week_call.args[0], week_call.args[1].date_str) == (_USER, _DATE)
        # The prose and the tallies read the same completions: one window for both.
        assert week_call.args[2] is service.context.gather_completed_since.return_value
        shipped = "\n".join(
            ["- Deck: Final numbers in", "- untitled", *[f"- G{i}" for i in range(2, 15)]]
        )
        finished = "\n".join(["- untitled", *[f"- U{i}" for i in range(1, 15)]])
        assert world.weekly_prompt.call_args.kwargs == {
            "date_local": _DATE,
            "week_summary_block": (
                "GAIA completed 16 todo(s); you completed 16.\n\n"
                f"GAIA shipped:\n{shipped}\n\nYou finished:\n{finished}"
            ),
        }
        assert world.agent.await_args.kwargs["conversation_id"].startswith(
            f"briefing-weekly-{_USER}-{_DATE}-"
        )
        payload = _stored_payload(world)
        assert (payload.hue, payload.generated_at) == (79, "7:05 AM")
        assert (event["component"], event["operation"], event["user_id"]) == (
            "briefing",
            "run_weekly_digest",
            _USER,
        )

    async def test_a_recap_exactly_at_the_cap_is_kept_past_other_blocks(self, world: World) -> None:
        world.agent.return_value = SimpleNamespace(
            message=_NOISE_BLOCKS + _fenced(_weekly(MAX_BRIEF_ITEMS))
        )

        await service.run_weekly_digest(_USER)

        assert sum(len(s.items) for s in _stored_payload(world).sections) == MAX_BRIEF_ITEMS

    async def test_a_recap_missing_from_the_output_names_its_start(self, world: World) -> None:
        raw = "z" * 400
        world.agent.return_value = SimpleNamespace(message=raw)

        with pytest.raises(service.BriefingGenerationError) as err:
            await service.run_weekly_digest(_USER)

        assert str(err.value) == (
            f"No valid BriefingPayload in agent output (first 300 chars): {raw[:300]!r}"
        )
        _assert_nothing_sent(world)

    async def test_an_unknown_user_fails_loud(self, world: World) -> None:
        world.user = UserDocument(id="someone-else", timezone=_TZ)

        with pytest.raises(service.BriefingGenerationError, match=f"unknown user {_USER}$"):
            await service.run_weekly_digest(_USER)

        world.agent.assert_not_awaited()

    @pytest.mark.parametrize("came_back", [False, True])
    async def test_a_dormant_loop_recaps_only_once_the_user_came_back(
        self, world: World, monkeypatch: pytest.MonkeyPatch, came_back: bool
    ) -> None:
        _dormant(world)
        world.agent.return_value = SimpleNamespace(message=_fenced(_weekly(3)))
        monkeypatch.setattr(
            service.dormancy,
            "latest_activity_since",
            AsyncMock(return_value=_NOW if came_back else None),
        )

        await service.run_weekly_digest(_USER)

        (user_id, since), _ = service.dormancy.latest_activity_since.await_args
        assert (user_id, since) == (_USER, _DORMANT_SINCE)
        assert world.upsert.await_count == int(came_back)

    async def test_a_stalled_agent_fails_the_run_instead_of_hanging(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def stall(**_: object) -> None:
            await asyncio.Event().wait()

        world.agent.side_effect = stall
        monkeypatch.setattr(service, "WEEKLY_GENERATION_TIMEOUT_SECONDS", 0)

        run = asyncio.ensure_future(service.run_weekly_digest(_USER))
        try:
            done, _ = await asyncio.wait({run}, timeout=5)
            assert run in done
            assert isinstance(run.exception(), TimeoutError)
        finally:
            run.cancel()
        _assert_nothing_sent(world)
