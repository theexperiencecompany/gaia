"""The daily brief and weekly recap runs, end to end through the service.

Faked seams: user lookup, call_agent_silent, the briefing repository, pending brief
items, the notification orchestrator, the chat channel resolver, the edition image
host, the platform chat post and the context reads. Assertions are on what gets
stored and delivered, and on every failure path, that nothing is.
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
from app.models.brief_models import PendingBriefItemDocument
from app.models.briefing_models import (
    BriefingEvent,
    BriefingModel,
    BriefingPayload,
    BriefingTallies,
    BriefingWeek,
    BriefingWeekDay,
)
from app.models.chat_models import ConversationSource
from app.models.todo_models import TodoDocument
from app.models.user_models import ShuffleBag, UserDocument
from app.services.briefing import context, service
from app.services.briefing.dormancy import DormancyState
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.delivery.chat_channel import ChatChannel
from app.services.outbound_delivery import OutboundResult

_USER = "64f1c0ffee0000000000abcd"
_EVENT = BriefingEvent(date="2026-10-14", start="11:00", title="Sequoia")
_CHAT = ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-1")
_IMAGE_URL = "https://cdn.example/brief_chat.png"
_EDITION_URL = "https://cdn.example/brief.png"
_BRIEF_ID = "brief_abc123"
_ORCHESTRATED = ["inapp", "email"]

_VOICE = {
    "headline": "Your morning, sorted",
    "lede": "Everything else is moving.",
    "caption": "Onward.",
    "mood": "packed",
    "bubbles": ["morning!", "the rest is handled"],
}

_DIGEST_REPORT = "3 new papers on retrieval\nThe longest is 40 pages; two cite your draft."


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
    bags: dict[str, ShuffleBag] = field(default_factory=dict)
    work: context.TrackedWork = field(default_factory=context.TrackedWork)
    held: list[PendingBriefItemDocument] = field(default_factory=list)
    user: UserDocument = field(
        default_factory=lambda: UserDocument(id=_USER, timezone="UTC", email="a@b.c")
    )
    chat: ChatChannel | None = _CHAT


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
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
            return_value=SimpleNamespace(
                channels=[SimpleNamespace(channel_type=c) for c in _ORCHESTRATED]
            )
        ),
        post=AsyncMock(return_value=OutboundResult.PUBLISHED),
        host_image=AsyncMock(
            side_effect=lambda payload, *, user_id, kind, crop_to_paper: (
                _IMAGE_URL if crop_to_paper else _EDITION_URL
            )
        ),
        consume=AsyncMock(),
        capture=MagicMock(),
    )
    monkeypatch.setattr(service.user_repository, "get", AsyncMock(side_effect=lambda _: w.user))
    monkeypatch.setattr(service, "call_agent_silent", w.agent)
    monkeypatch.setattr(service.briefing_repository, "upsert_briefing", w.upsert)
    monkeypatch.setattr(service.briefing_repository, "set_delivered_channels", w.set_channels)
    monkeypatch.setattr(
        service.briefing_repository, "has_daily_briefing", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(service.notification_service, "create_notification", w.notify)
    monkeypatch.setattr(service, "resolve_chat_channel", AsyncMock(side_effect=lambda _: w.chat))
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
            ("NEEDS YOU", ["Approve the Priya reply"]),
            ("GAIA'S WORK", ["Investor update"]),
        ]
        skim = (
            "Your morning, sorted\n\n"
            "• Approve the Priya reply\n\n"
            "Overnight I finished Investor update.\n\n"
            f"Full brief: https://heygaia.io/brief/{_BRIEF_ID}"
        )
        assert world.upsert.await_args.kwargs["edition_image_url"] == _EDITION_URL
        request = world.notify.await_args.args[0]
        assert request.metadata["edition_image_url"] == _EDITION_URL
        assert request.content.actions[0].config.redirect.url == f"/brief/{_BRIEF_ID}"
        assert [c.channel_type for c in request.channels] == _ORCHESTRATED
        assert request.metadata["kind"] == NOTIFICATION_KIND_BRIEFING_DAILY
        assert request.content.body == skim
        assert request.content.rich_content == payload.model_dump()
        assert world.host_image.await_args.kwargs["crop_to_paper"] is True
        post = world.post.await_args.kwargs
        assert (post["channel"], post["text"], post["image"].url) == (_CHAT, skim, _IMAGE_URL)
        world.set_channels.assert_awaited_once()
        assert world.set_channels.await_args.args[3] == [*_ORCHESTRATED, "telegram"]

    async def test_without_a_chat_platform_no_chat_image_is_rendered_or_posted(
        self, world: World
    ) -> None:
        world.chat = None

        await service.run_daily_briefing(_USER)

        # Only the full edition is rendered: it is the in-app page's and the email's image.
        assert [c.kwargs["crop_to_paper"] for c in world.host_image.await_args_list] == [False]
        world.post.assert_not_awaited()
        assert world.set_channels.await_args.args[3] == _ORCHESTRATED

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
        assert request.content.body == (
            "A good week\n\nThis week I finished Item 0, Item 1 and 1 more.\n\n"
            f"Full brief: https://heygaia.io/brief/{_BRIEF_ID}"
        )
        world.consume.assert_not_awaited()

    async def test_recap_over_the_item_cap_fails_and_sends_nothing(self, world: World) -> None:
        world.agent.return_value = SimpleNamespace(message=_fenced(_weekly(MAX_BRIEF_ITEMS + 1)))

        with pytest.raises(service.BriefingGenerationError, match="at most"):
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
            ("NEEDS YOU", ["Approve the Priya reply"]),
            ("WHILE YOU WERE AWAY", ["Paper digest: 3 new papers on retrieval"]),
            ("GAIA'S WORK", ["Investor update"]),
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
        world.consume.assert_awaited_once_with(_USER, ["h1"])

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

        with pytest.raises(service.BriefingGenerationError, match="contradict"):
            await service.run_daily_briefing(_USER)

        _assert_nothing_sent(world)
