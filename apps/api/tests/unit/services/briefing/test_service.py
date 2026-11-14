"""The daily brief and weekly recap runs, end to end through the service.

Faked seams: user lookup, call_agent_silent, the briefing repository, pending brief
items, the notification orchestrator, the chat channel resolver, the edition image
host, the platform chat post and the context reads. Assertions are on what gets
stored and delivered, and on every failure path, that nothing is.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import re
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, sentinel

import pytest
from tests.helpers import captured_wide_event
import time_machine

from app.agents.prompts.briefing_prompts import (
    VoiceSituation,
    build_briefing_voice_prompt,
    build_weekly_voice_prompt,
    voice_unreadable_note,
)
from app.constants.briefing import (
    FIRST_WEEK_DAYS,
    IDLE_DORMANT_DAYS,
    MAX_BRIEF_HEADLINE_CHARS,
    WEEKLY_KICKER,
    WINBACK_THRESHOLD,
    BriefAction,
    BriefingBag,
    BriefingFrequency,
    BriefingRunOutcome,
    BriefItemSource,
    BriefOutcome,
    SectionKey,
)
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
    ProactiveMessageClass,
)
from app.constants.todos import GAIA_TRACKED_LABEL, NEEDS_REPLY_LABEL
from app.constants.user_activity import ActivityStatus
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.hil import hil_approval_repository
from app.db.repositories.pending_brief_items import pending_brief_items_repository
from app.db.repositories.reminders import reminder_repository
from app.db.repositories.signal_memory import signal_memory_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_models import PendingBriefItemDocument
from app.models.briefing_models import (
    BriefingEvent,
    BriefingModel,
    BriefingPayload,
    BriefingSchedule,
    BriefingTallies,
    BriefingWeek,
    BriefingWeekDay,
    EditionRender,
    NewStamp,
)
from app.models.chat_models import ConversationSource
from app.models.hil_models import ApprovalLedgerDocument
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationStatus,
)
from app.models.scout_models import (
    ScoutOutcome,
    ScoutResult,
    ScoutSkipReason,
    Signal,
    SignalImportance,
    SignalMemoryDocument,
)
from app.models.short_link_models import ShortLinkTargetType
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.user_models import (
    BriefingBootstrap,
    BriefingDormancy,
    ShuffleBag,
    UserDocument,
)
from app.models.workflow_execution_models import WorkflowExecutionDocument
from app.services.briefing import (
    chat_sync,
    context,
    daily,
    delivery,
    dormancy,
    edition_draws,
    errors,
    faithfulness,
    prose,
    publish,
    silent_turn,
    store,
    weekly,
)
from app.services.briefing.candidates import judge
from app.services.briefing.candidates.judge import BriefSelectionAnswer
from app.services.briefing.dormancy import DormancyState
from app.services.briefing.edition_email import HostedEditionImage
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.faithfulness import (
    CheckedSpecific,
    UnsupportedClaim,
    UnsupportedClaims,
)
from app.services.briefing.scouts import service as scout_service
from app.services.delivery.chat_channel import ChatChannel, InApp
from app.services.notification_service import notification_service
from app.services.outbound_delivery import OutboundResult
from app.utils.errors import AppError
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
_CHAT = ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-1", basis="priority")
_EDITION = HostedEditionImage(
    display_url="https://cdn.example/f_auto/brief",
    chat_url="https://cdn.example/f_jpg/brief",
    fold=0.3,
    paper=(0.1, 0.2, 0.9, 0.8),
)
_BRIEF_ID = "brief_abc123"
_BRIEF_LINK = "https://heygaia.link/briefabc123"
_ORCHESTRATED = ["inapp", "email"]

# The fake model writes its message from exactly the facts it was shown: a reply holding
# this token gets, in its place, one title slot per fact the facts block numbers, and
# "<fact of TITLE>" becomes the number of the fact with that title.
_FACTS_SHOWN = "<the facts shown>"
# The daily's facts are today's, the weekly's this week's.
_FACTS_HEADER = re.compile(
    r"## (?:TODAY'S|THIS WEEK'S) FACTS \(final: voice them, never alter them\)\n"
)

_VOICE = {
    "headline": "Your morning, sorted",
    "lede": "Everything else is moving.",
    "caption": "Onward.",
    "mood": "packed",
    "message": _FACTS_SHOWN,
}


_FACT_LINE = re.compile(r"^- fact (\d+) \| ", re.M)


def _facts_shown(prompt: str) -> str:
    """Return the prompt's facts block."""
    return _FACTS_HEADER.split(prompt, maxsplit=1)[1].split("\n\n## ", 1)[0]


_FACT_OF = re.compile(r"<fact of ([^>]+)>")


def _naming_every_fact(prompt: str) -> str:
    """Return a message naming each fact of the facts block by its title slot, in order."""
    ids = dict.fromkeys(_FACT_LINE.findall(_facts_shown(prompt)))
    return "\n".join(f"[[fact:{fact_id}]]" for fact_id in ids) or "A quiet day."


def _fact_of(prompt: str, title: str) -> str:
    found = re.search(rf"^- fact (\d+) \| [^\n]*{re.escape(title)}", prompt, re.M)
    assert found is not None, f"no fact is titled {title!r}"
    return found.group(1)


def _message_written(prompt: str, reply: str) -> str:
    """Return reply with the facts token and each fact-of token filled in from the prompt."""
    if not _FACTS_HEADER.search(prompt):
        return reply
    reply = _FACT_OF.sub(lambda m: _fact_of(prompt, m.group(1)), reply)
    return reply.replace(_FACTS_SHOWN, json.dumps(_naming_every_fact(prompt))[1:-1])


_DIGEST_REPORT = "3 new papers on retrieval\nThe longest is 40 pages; two cite your draft."


_CANDIDATE_LINE = re.compile(r"^(\d+)\. \[[^\]]+\] (needs_you|update|gaia_did|event)", re.M)
_FILED_UNDER = {"needs_you": "needs_you", "update": "updates", "gaia_did": "gaia_did"}
_CANDIDATE_TITLE = re.compile(
    r"^(\d+)\. \[[^\]]+\] [a-z_]+(?:, important)?: (.+?)(?: \| .*)?$", re.M
)
# How the stand-in judge words what its line does not settle: asks reply, reports changed.
_SECTION_READS_AS = {
    "lead": {"action": "reply"},
    "needs_you": {"action": "reply"},
    "updates": {"outcome": "changed"},
    "gaia_did": {"outcome": "finished"},
}


def _worded(prompt: str, section: str, candidate_id: int) -> dict[str, object]:
    """Word a kept candidate as a judge would: its own title, its section's action or outcome."""
    titles = {int(n): title for n, title in _CANDIDATE_TITLE.findall(prompt)}
    return {"id": candidate_id, "title": titles[candidate_id], **_SECTION_READS_AS[section]}


def _files_by_kind(
    schema: type[BriefSelectionAnswer], prompt: str, **_: object
) -> BriefSelectionAnswer:
    """Stand in for the selection model: file every candidate where its producer would, in order."""
    lists: dict[str, list[dict[str, object]]] = {"needs_you": [], "updates": [], "gaia_did": []}
    for number, kind in _CANDIDATE_LINE.findall(prompt):
        if kind in _FILED_UNDER:
            section = _FILED_UNDER[kind]
            lists[section].append(_worded(prompt, section, int(number)))
    return schema.model_validate(lists)


def _judged(
    lead: tuple[str, str] | None = None, **sections: list[str]
) -> Callable[..., BriefSelectionAnswer]:
    """Stand in for a selection model that files candidates by title and drops the rest."""

    def answer(
        schema: type[BriefSelectionAnswer], prompt: str, **_: object
    ) -> BriefSelectionAnswer:
        ids = {title: int(n) for n, title in _CANDIDATE_TITLE.findall(prompt)}
        lists = {
            key: [_worded(prompt, key, ids[title]) for title in titles]
            for key, titles in sections.items()
        }
        kept = {c["id"] for chosen in lists.values() for c in chosen}
        if lead is not None:
            kept.add(ids[lead[0]])
        return schema.model_validate(
            {
                **lists,
                "lead": _worded(prompt, "lead", ids[lead[0]]) if lead else None,
                "offer": lead[1] if lead else None,
                "dropped": [i for i in ids.values() if i not in kept],
            }
        )

    return answer


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
        source=BriefItemSource.WORKFLOW,
        source_id=f"wf-{item_id}",
        source_title=title,
        conversation_id=f"conv-{item_id}",
        text=text,
    )


@dataclass
class World:
    """Every seam the run touches, with a happy-path default."""

    agent: AsyncMock
    upsert: AsyncMock
    mint: AsyncMock
    set_channels: AsyncMock
    notify: AsyncMock
    post: AsyncMock
    host_image: AsyncMock
    consume: AsyncMock
    capture: MagicMock
    voice_prompt: MagicMock
    weekly_prompt: MagicMock
    #: The faithfulness model; by default every claim holds.
    checker: AsyncMock
    recent: AsyncMock = field(default_factory=lambda: AsyncMock(return_value=[]))
    stamped: AsyncMock = field(default_factory=lambda: AsyncMock(return_value=[]))
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
    scouts: list[ScoutResult] = field(default_factory=list)
    memory: list[SignalMemoryDocument] = field(default_factory=list)
    shown: AsyncMock = field(default_factory=AsyncMock)
    seen: AsyncMock = field(default_factory=AsyncMock)
    brief_message: AsyncMock = field(default_factory=AsyncMock)
    #: The context and repository reads the run makes, by name, as patched.
    reads: dict[str, AsyncMock] = field(default_factory=dict)
    #: The selection model; by default it files every candidate where its producer would.
    judge: AsyncMock = field(default_factory=lambda: AsyncMock(side_effect=_files_by_kind))


def _seam(
    monkeypatch: pytest.MonkeyPatch, w: World, owner: object, name: str, mock: AsyncMock
) -> None:
    monkeypatch.setattr(owner, name, mock)
    w.reads[name] = mock


def _patch_context_reads(monkeypatch: pytest.MonkeyPatch, w: World) -> None:
    """Patch what the run gathers its context from (work, goals, dormancy, apps) and the scouts."""
    _seam(monkeypatch, w, chat_sync, "format_replies_block", AsyncMock(return_value="No replies."))
    _seam(monkeypatch, w, context, "format_goal_block", AsyncMock(return_value=("Ship v2", True)))
    _seam(
        monkeypatch, w, context, "get_yesterday_payload", AsyncMock(return_value=sentinel.yesterday)
    )
    _seam(monkeypatch, w, context, "format_lookback_block", AsyncMock(return_value="-"))
    _seam(
        monkeypatch,
        w,
        context,
        "compute_winback_state",
        AsyncMock(return_value=context.WinbackState(unacknowledged=0, last_was_winback=False)),
    )
    _seam(monkeypatch, w, context, "gather_tracked_work", AsyncMock(side_effect=lambda *_: w.work))
    _seam(monkeypatch, w, context, "user_open_todo_summary", AsyncMock(return_value=(0, [])))
    _seam(
        monkeypatch,
        w,
        context,
        "gather_completed_since",
        AsyncMock(return_value=context.CompletedWork(user=[_todo("u1", "Gym")])),
    )
    _seam(monkeypatch, w, dormancy, "record_idle_day", AsyncMock(return_value=0))
    _seam(monkeypatch, w, dormancy, "latest_activity_since", AsyncMock(return_value=None))
    monkeypatch.setattr(
        daily,
        "activity_status_of",
        AsyncMock(side_effect=lambda user_id: w.activity if user_id == _USER else None),
    )
    monkeypatch.setattr(
        daily,
        "get_connected_integrations_named",
        AsyncMock(
            side_effect=lambda user_id: [{"id": a.lower(), "name": a} for a in w.connected_apps]
            if user_id == _USER
            else []
        ),
    )

    monkeypatch.setattr(
        scout_service,
        "run_scouts",
        AsyncMock(side_effect=lambda user: w.scouts if user.id == _USER else []),
    )
    monkeypatch.setattr(
        signal_memory_repository,
        "find_for",
        AsyncMock(side_effect=lambda user_id, signals: list(w.memory) if user_id == _USER else []),
    )
    monkeypatch.setattr(signal_memory_repository, "record_seen", w.seen)
    monkeypatch.setattr(signal_memory_repository, "mark_shown", w.shown)


@pytest.fixture
def checker(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    model = AsyncMock(return_value=UnsupportedClaims(specifics=[]))
    monkeypatch.setattr(faithfulness, "ainvoke_structured", model)
    return model


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, checker: AsyncMock) -> Iterator[World]:
    w = World(
        checker=checker,
        agent=AsyncMock(return_value=SimpleNamespace(message=_fenced(_VOICE))),
        upsert=AsyncMock(
            side_effect=lambda user_id, date, kind, payload, *, briefing_id, edition: BriefingModel(
                id=briefing_id,
                user_id=user_id,
                date=date,
                kind=kind,
                payload=payload,
                edition_image_url=edition.image_url,
            )
        ),
        mint=AsyncMock(return_value=_BRIEF_LINK),
        set_channels=AsyncMock(),
        notify=AsyncMock(
            return_value=SimpleNamespace(channels=[_delivered(c) for c in _ORCHESTRATED])
        ),
        post=AsyncMock(return_value=OutboundResult.PUBLISHED),
        host_image=AsyncMock(side_effect=lambda payload, *, owner_id, render_key: _EDITION),
        consume=AsyncMock(),
        capture=MagicMock(),
        voice_prompt=MagicMock(wraps=build_briefing_voice_prompt),
        weekly_prompt=MagicMock(wraps=build_weekly_voice_prompt),
    )

    # Seams keyed on the user: a read for anyone else finds nothing. The stored
    # shuffle bags ride on the user document, as they do in Mongo.
    async def get_user(user_id: str) -> UserDocument | None:
        if user_id != w.user.id:
            return None
        w.user.briefing_shuffle_bags = {BriefingBag(k): v for k, v in w.bags.items()} or None
        return w.user

    monkeypatch.setattr(user_repository, "get", AsyncMock(side_effect=get_user))
    monkeypatch.setattr(briefing_repository, "was_delivered", w.was_delivered)
    monkeypatch.setattr(user_repository, "clear_briefing_bootstrap", w.clear_bootstrap)
    monkeypatch.setattr(dormancy, "clear_dormancy", w.clear_dormancy)
    monkeypatch.setattr(dormancy, "enter_dormancy", w.enter_dormancy)
    monkeypatch.setattr(daily, "build_briefing_voice_prompt", w.voice_prompt)
    monkeypatch.setattr(weekly, "build_weekly_voice_prompt", w.weekly_prompt)

    async def model(**kwargs: Any) -> SimpleNamespace:
        reply = await w.agent(**kwargs)
        return SimpleNamespace(message=_message_written(kwargs["request"].message, reply.message))

    monkeypatch.setattr(silent_turn, "call_agent_silent", model)
    monkeypatch.setattr(briefing_repository, "list_recent", w.recent)
    monkeypatch.setattr(briefing_repository, "list_stamped", w.stamped)
    monkeypatch.setattr(briefing_repository, "upsert_briefing", w.upsert)
    monkeypatch.setattr(briefing_repository, "briefing_id_for", AsyncMock(return_value=_BRIEF_ID))
    monkeypatch.setattr(briefing_repository, "set_delivered_channels", w.set_channels)
    monkeypatch.setattr(prose, "optional_short_link", w.mint)
    monkeypatch.setattr(store, "optional_short_link", w.mint)
    _seam(monkeypatch, w, briefing_repository, "has_daily_briefing", AsyncMock(return_value=True))
    monkeypatch.setattr(notification_service, "create_notification", w.notify)
    monkeypatch.setattr(delivery, "post_brief_message", w.brief_message)
    monkeypatch.setattr(
        delivery,
        "resolve_proactive_target",
        AsyncMock(
            side_effect=lambda user_id: (
                w.chat if user_id == _USER and w.chat else InApp(reason="no_chat_app")
            )
        ),
    )
    monkeypatch.setattr(store, "host_edition_image", w.host_image)
    monkeypatch.setattr(delivery, "post_to_platform_chat", w.post)
    monkeypatch.setattr(publish, "capture", w.capture)
    _seam(
        monkeypatch,
        w,
        pending_brief_items_repository,
        "list_for_user",
        AsyncMock(side_effect=lambda *_, **__: list(w.held)),
    )
    monkeypatch.setattr(pending_brief_items_repository, "consume", w.consume)
    _patch_context_reads(monkeypatch, w)

    async def set_bag(user_id: str, bag: BriefingBag, state: ShuffleBag) -> None:
        assert user_id == _USER
        w.bags[bag.value] = state

    monkeypatch.setattr(user_repository, "set_briefing_bag", set_bag)
    _seam(monkeypatch, w, context, "gather_calendar", AsyncMock(return_value=[_EVENT]))
    monkeypatch.setattr(judge, "ainvoke_structured", w.judge)
    for owner, name in (
        (approval_ledger_repository, "list_pending_for_user"),
        (hil_approval_repository, "list_pending_for_user"),
        (reminder_repository, "find_scheduled_between"),
        (todo_repository, "list_open_user_todos"),
    ):
        _seam(monkeypatch, w, owner, name, AsyncMock(return_value=[]))
    _seam(monkeypatch, w, workflow_executions_repository, "list_since", AsyncMock(return_value=[]))
    _seam(monkeypatch, w, workflow_repository, "find_system_workflows", AsyncMock(return_value=[]))
    _seam(
        monkeypatch, w, todo_repository, "find_latest_by_external_ref", AsyncMock(return_value=None)
    )
    _seam(
        monkeypatch,
        w,
        context,
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


def _family_first(w: World, family: str) -> None:
    """Pin today's edition family: the default draw is random, and Air Mail adds a stamp line."""
    pool = [f for f, n in DAILY_FAMILY_WEIGHTS.items() for _ in range(n)]
    pool.remove(family)
    w.bags["edition_family"] = ShuffleBag(order=[family, *pool], index=0)


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
        _family_first(world, "memo")

        await daily.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        assert payload.headline == "Your morning, sorted"
        assert payload.template_family == "memo"
        assert payload.calendar == [_EVENT]
        assert payload.tallies == BriefingTallies(done_by_you=1, done_by_gaia=0)
        assert "11:00 AM: Sequoia" in _prompt(world)
        assert [(s.title, [i.text for i in s.items]) for s in payload.sections] == [
            ("Needs you", ["Approve the Priya reply"]),
            ("GAIA's work", ["Investor update"]),
        ]
        assert [i.todo_id for s in payload.sections for i in s.items] == ["b1", "c1"]
        message = "Approve the Priya reply\nInvestor update\nSequoia"
        assert payload.message == message
        assert world.upsert.await_args.kwargs["edition"] == EditionRender(
            image_url=_EDITION.display_url, fold=0.3, paper=[0.1, 0.2, 0.9, 0.8]
        )
        request = world.notify.await_args.args[0]
        assert request.metadata["edition_image_url"] == _EDITION.display_url
        # One URL, minted before the render: the edition's codes, the email image and the chat post.
        world.mint.assert_awaited_with(_USER, ShortLinkTargetType.BRIEFING, _BRIEF_ID)
        assert world.host_image.await_args.args[0].link == _BRIEF_LINK
        assert request.metadata["brief_url"] == _BRIEF_LINK
        assert request.content.actions[0].config.redirect.url == f"/brief/{_BRIEF_ID}"
        assert [c.channel_type for c in request.channels] == _ORCHESTRATED
        assert request.metadata["kind"] == NOTIFICATION_KIND_BRIEFING_DAILY
        # GAIA's Briefings-conversation message carries the same folded card the notification does.
        user_id, text, card = world.brief_message.await_args.args
        assert (user_id, text, card.briefing_id, card.kind) == (_USER, message, _BRIEF_ID, "daily")
        assert (card.needs_you_count, card.edition_image_url) == (1, _EDITION.display_url)
        assert request.metadata["needs_you_count"] == card.needs_you_count
        assert request.content.body == message
        assert request.content.rich_content == payload.model_dump()
        world.host_image.assert_awaited_once()
        post = world.post.await_args.kwargs
        assert (post["channel"], post["image"].url) == (_CHAT, _EDITION.chat_url)
        assert split_message_bubbles(post["text"]) == [
            "Your morning, sorted",
            f"{message}\n\nFull brief: {_BRIEF_LINK}",
        ]
        world.set_channels.assert_awaited_once()
        assert world.set_channels.await_args.args[3] == [*_ORCHESTRATED, "telegram"]

    async def test_without_a_chat_platform_nothing_is_posted(self, world: World) -> None:
        world.chat = None

        await daily.run_daily_briefing(_USER)

        world.host_image.assert_awaited_once()
        world.post.assert_not_awaited()
        assert world.set_channels.await_args.args[3] == _ORCHESTRATED

    async def test_every_render_is_hosted_under_one_fresh_opaque_key(self, world: World) -> None:
        """The image URL goes out in emails and public links, so it names no user, kind or date."""
        await daily.run_daily_briefing(_USER)
        await daily.run_daily_briefing(_USER)

        assert {c.kwargs["owner_id"] for c in world.host_image.await_args_list} == {_USER}
        keys = [c.kwargs["render_key"] for c in world.host_image.await_args_list]
        assert len(keys) == 2 and keys[0] != keys[1]
        assert re.fullmatch(r"[0-9a-f]{32}", keys[0])

    async def test_the_edition_is_addressed_to_the_user_by_name(self, world: World) -> None:
        await daily.run_daily_briefing(_USER)

        assert _stored_payload(world).recipient_name == "Ada"
        assert "You're writing to Ada" in world.voice_prompt.call_args.kwargs["blocks"].reader

    async def test_a_user_who_gave_no_name_is_addressed_by_none(self, world: World) -> None:
        """Regression: the brief greeted "Dear Delivered", a name guessed from delivered+dev@resend.dev."""
        world.user = UserDocument(id=_USER, timezone=_TZ, email="delivered+dev@resend.dev")

        await daily.run_daily_briefing(_USER)

        assert _stored_payload(world).recipient_name is None
        assert "writing to" not in world.voice_prompt.call_args.kwargs["blocks"].reader
        assert "Delivered" not in world.voice_prompt.call_args.kwargs["blocks"].context

    async def test_an_empty_day_stays_in_app_and_spends_no_draw(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing needs the user, nothing is on the calendar, nothing ran overnight."""
        world.work = context.TrackedWork()
        bags_before = dict(world.bags)
        _seam(monkeypatch, world, context, "gather_calendar", AsyncMock(return_value=[]))

        await daily.run_daily_briefing(_USER)

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

        await daily.run_daily_briefing(_USER)

        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == ["inapp"]

    async def test_an_air_mail_brief_records_its_stamp_city(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            edition_draws, "hosted_stamp_weights", lambda: {"paris": 1, "tokyo": 1, "lima": 1}
        )
        _family_first(world, "postal")
        seeded = world.bags["edition_family"].order

        await daily.run_daily_briefing(_USER)

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
        monkeypatch.setattr(edition_draws, "hosted_stamp_weights", lambda: {"paris": 1, "tokyo": 1})
        _family_first(world, "postal")
        family_before = world.bags["edition_family"]
        world.notify.side_effect = RuntimeError("orchestrator down")

        with pytest.raises(RuntimeError, match="orchestrator down"):
            await daily.run_daily_briefing(_USER)

        assert world.bags["edition_family"] == family_before
        assert "stamp_city" not in world.bags

    async def test_a_first_stamp_is_announced_on_every_channel(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(edition_draws, "hosted_stamp_weights", lambda: {"tokyo": 1})
        _family_first(world, "postal")

        await daily.run_daily_briefing(_USER)

        assert _stored_payload(world).new_stamp == NewStamp(
            city="Tokyo", country="Japan", collected=1, total=85
        )
        world.stamped.assert_awaited_once_with(_USER)
        line = "New stamp: Tokyo, Japan. 1 of 85 collected. [See your stamps]("
        assert line in world.post.await_args.kwargs["text"]
        assert line in world.notify.await_args.args[0].content.body
        assert world.capture.call_args.args[1].stamp_collected is True
        world.stamped.assert_awaited_once_with(_USER)

    async def test_a_city_already_collected_is_not_announced_again(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(edition_draws, "hosted_stamp_weights", lambda: {"tokyo": 1})
        _family_first(world, "postal")
        earlier = BriefingModel(
            user_id=_USER,
            date="2026-09-01",
            payload=BriefingPayload(
                kicker="K",
                date="2026-09-01",
                headline="h",
                lede="l",
                mood="clear",
                caption="c",
                template_family="postal",
                stamp_city="tokyo",
            ),
        )
        world.stamped.return_value = [earlier]

        await daily.run_daily_briefing(_USER)

        assert _stored_payload(world).stamp_city == "tokyo"
        assert _stored_payload(world).new_stamp is None
        assert "New stamp" not in world.post.await_args.kwargs["text"]

    async def test_a_non_postal_brief_draws_no_stamp(self, world: World) -> None:
        _family_first(world, "memo")

        await daily.run_daily_briefing(_USER)

        assert _stored_payload(world).stamp_city is None
        assert "stamp_city" not in world.bags

    async def test_each_section_holds_at_most_its_cap_in_the_judges_order(
        self, world: World
    ) -> None:
        """Regression: needs-you was truncated by a fixed order, never by what mattered."""
        world.work = context.TrackedWork(
            running=[_todo(f"r{i}", f"Running {i}") for i in range(6)],
            blocked=[_todo(f"b{i}", f"Blocked {i}") for i in range(5)],
            failed=[_todo("f1", "Failed one")],
        )
        world.judge.side_effect = _judged(
            needs_you=["Failed one", *(f"Blocked {i}" for i in range(5))],
            gaia_did=[f"Running {i}" for i in range(6)],
        )

        await daily.run_daily_briefing(_USER)

        sections = _stored_payload(world).sections
        assert [(s.key, [i.text for i in s.items]) for s in sections] == [
            (SectionKey.NEEDS_YOU, ["Failed one", "Blocked 0", "Blocked 1", "Blocked 2"]),
            (SectionKey.GAIA_DID, ["Running 0", "Running 1", "Running 2"]),
        ]
        assert [s.numeral for s in sections] == ["I", "II"]
        assert [(s.key, s.more) for s in sections] == [
            (SectionKey.NEEDS_YOU, 2),
            (SectionKey.GAIA_DID, 3),
        ]

    async def test_the_judges_lead_opens_the_brief_with_its_offer(self, world: World) -> None:
        world.work = _brief_work()
        world.judge.side_effect = _judged(
            lead=("Approve the Priya reply", "Send the reply once you approve"),
            gaia_did=["Investor update"],
        )

        await daily.run_daily_briefing(_USER)

        lead, work = _stored_payload(world).sections
        assert (lead.key, lead.title, lead.numeral) == (SectionKey.LEAD, "First up", "I")
        assert [(i.text, i.kind, i.offer) for i in lead.items] == [
            ("Approve the Priya reply", "you", "Send the reply once you approve")
        ]
        assert [(i.text, i.offer) for i in work.items] == [("Investor update", None)]
        sent = world.capture.call_args.args[1]
        assert (sent.lead_count, sent.needs_you_count, sent.updates_count, sent.gaia_did_count) == (
            1,
            0,
            0,
            1,
        )

    async def test_a_selection_the_judge_breaks_twice_fails_and_sends_nothing(
        self, world: World
    ) -> None:
        world.work = _brief_work()
        world.judge.side_effect = None
        world.judge.return_value = BriefSelectionAnswer.model_validate(
            {"needs_you": [{"id": 99, "action": "reply", "title": "Nobody"}]}
        )

        with pytest.raises(AppError, match="selection judge broke its contract"):
            await daily.run_daily_briefing(_USER)

        assert world.judge.await_count == 2
        _assert_nothing_sent(world)

    async def test_voice_the_agent_botched_stores_and_sends_nothing(self, world: World) -> None:
        world.agent.return_value = SimpleNamespace(message="Sorry, something went wrong.")

        with pytest.raises(errors.BriefingGenerationError):
            await daily.run_daily_briefing(_USER)

        _assert_nothing_sent(world)

    async def test_unknown_user_fails_loud(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(user_repository, "get", AsyncMock(return_value=None))

        with pytest.raises(errors.BriefingGenerationError, match="unknown user"):
            await daily.run_daily_briefing(_USER)

        world.agent.assert_not_awaited()

    async def test_dormant_user_without_activity_is_skipped_before_the_agent(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            dormancy,
            "state_from_user",
            lambda _: DormancyState(idle_days=3, date=None, dormant_since=MagicMock()),
        )

        await daily.run_daily_briefing(_USER)

        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    async def test_ignored_winback_backs_off(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seam(
            monkeypatch,
            world,
            context,
            "compute_winback_state",
            AsyncMock(return_value=context.WinbackState(unacknowledged=5, last_was_winback=True)),
        )

        await daily.run_daily_briefing(_USER)

        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    async def test_a_failed_delivery_records_no_channels(self, world: World) -> None:
        world.notify.side_effect = RuntimeError("orchestrator down")

        with pytest.raises(RuntimeError):
            await daily.run_daily_briefing(_USER)

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

        await daily.run_daily_briefing(_USER)

        assert world.set_channels.await_args.args[3] == ["inapp"]
        sent = world.capture.call_args.args[1]
        assert sent.channel_count == 1

    async def test_a_brief_already_delivered_today_is_not_sent_again(self, world: World) -> None:
        world.was_delivered.return_value = True

        outcome = await daily.run_daily_briefing(_USER)

        assert outcome is BriefingRunOutcome.ALREADY_DELIVERED
        world.was_delivered.assert_awaited_once_with(_USER, _DATE, "daily")
        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    async def test_a_sent_brief_reports_it_was_sent(self, world: World) -> None:
        assert await daily.run_daily_briefing(_USER) is BriefingRunOutcome.SENT


_WEEKLY_VOICE = {
    "headline": "A good week",
    "lede": "The deck went out and the CRM sync needs a look.",
    "caption": "Same time next week.",
    "mood": "weekly",
    "message": _FACTS_SHOWN,
}


def _weekly_voiced(**fields: str) -> SimpleNamespace:
    return SimpleNamespace(message=_fenced({**_WEEKLY_VOICE, **fields}))


def _failed_run(monkeypatch: pytest.MonkeyPatch, world: World) -> None:
    """Have the CRM sync workflow fail this week."""
    world.reads["list_since"].return_value = [
        WorkflowExecutionDocument(
            execution_id="e1",
            workflow_id="wf-sync",
            user_id=_USER,
            status="failed",
            started_at=_NOW - timedelta(days=1),
            error_message="HubSpot token expired",
        )
    ]
    monkeypatch.setattr(
        workflow_repository,
        "find_by_ids_for_user",
        AsyncMock(return_value=[SimpleNamespace(id="wf-sync", title="CRM sync")]),
    )


_FRIDAY_PITCH = BriefingEvent(date="2026-10-16", start="15:00", title="Pitch to Accel")


def _a_full_week(monkeypatch: pytest.MonkeyPatch, world: World) -> None:
    """Fill every weekly source: GAIA's and the user's work, a failed run and an event ahead."""
    _failed_run(monkeypatch, world)
    deck = _todo("g1", "Investor deck")
    deck.canvas_content = "# Deck\nFinal numbers in"
    _seam(
        monkeypatch,
        world,
        context,
        "gather_completed_since",
        AsyncMock(
            return_value=context.CompletedWork(gaia=[deck], user=[_todo("u1", "Send the deck")])
        ),
    )
    _seam(
        monkeypatch,
        world,
        context,
        "gather_week",
        AsyncMock(
            return_value=BriefingWeek(
                days=[BriefingWeekDay(you=1, gaia=2)] * 7,
                shipped=["Send the deck"],
                handled=["Investor deck"],
                ahead=[_FRIDAY_PITCH],
            )
        ),
    )


class TestWeeklyRecap:
    async def test_recap_is_stored_and_delivered_as_weekly(self, world: World) -> None:
        world.agent.return_value = _weekly_voiced()

        assert await weekly.run_weekly_digest(_USER) is BriefingRunOutcome.SENT

        payload = _stored_payload(world)
        # Masthead, date and mood come from code, whatever the model wrote.
        assert (payload.kicker, payload.date, payload.mood) == (WEEKLY_KICKER, _DATE, "weekly")
        assert world.upsert.await_args.args[2] == "weekly"
        assert payload.template_family == "weekly"
        assert payload.week == world.reads["gather_week"].return_value
        assert payload.tallies == BriefingTallies(done_by_you=7, done_by_gaia=14)
        assert payload.headline == "A good week"
        request = world.notify.await_args.args[0]
        assert request.metadata["kind"] == NOTIFICATION_KIND_BRIEFING_WEEKLY
        assert request.content.body == payload.message == "Gym"
        # The recap is always pushed: it reaches the chat app, not only the in-app page.
        assert world.post.await_args.kwargs["origin"] == "weekly brief"
        world.consume.assert_not_awaited()

    async def test_a_recap_already_delivered_today_is_not_sent_again(self, world: World) -> None:
        world.was_delivered.return_value = True

        assert await weekly.run_weekly_digest(_USER) is BriefingRunOutcome.ALREADY_DELIVERED

        world.was_delivered.assert_awaited_once_with(_USER, _DATE, "weekly")
        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    async def test_code_builds_the_sections_from_the_weeks_candidates(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: the model wrote the whole weekly payload, its sections and items included."""
        _a_full_week(monkeypatch, world)
        world.agent.return_value = _weekly_voiced()

        await weekly.run_weekly_digest(_USER)

        payload = _stored_payload(world)
        assert [
            (s.key, s.title, [(i.text, i.kind) for i in s.items]) for s in payload.sections
        ] == [
            (SectionKey.NEEDS_YOU, "Needs you", [("CRM sync failed", "failed")]),
            (SectionKey.UPDATES, "You finished", [("Send the deck", "lookback")]),
            (SectionKey.GAIA_DID, "GAIA's work", [("Investor deck", "lookback")]),
        ]
        assert payload.message == "CRM sync failed\nSend the deck\nInvestor deck\nPitch to Accel"
        assert payload.week == world.reads["gather_week"].return_value
        (since,) = world.reads["list_since"].await_args.args[1:2]
        assert since == _WEEK_START

    async def test_the_week_ahead_is_timed_by_its_day_and_the_judge_reads_the_week(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _a_full_week(monkeypatch, world)
        world.agent.return_value = _weekly_voiced(
            lede="Then [[fact:<fact of Pitch to Accel>]] on [[fact:<fact of Pitch to Accel>.time]]."
        )

        await weekly.run_weekly_digest(_USER)

        assert _stored_payload(world).lede == "Then Pitch to Accel on Fri 3:00 PM."
        facts = _facts_shown(_prompt(world))
        assert "The week ahead:\n- fact " in facts and "| Fri 3:00 PM: Pitch to Accel" in facts
        assert "summary: Final numbers in" in facts
        assert "weekly digest" in world.judge.await_args.args[1]
        assert "## THIS WEEK'S FACTS" in _prompt(world)


class TestTheWeeklyHoldsToItsFacts:
    """The weekly's prose is held to its facts by the daily's slots, coverage and faithfulness check."""

    async def test_an_unsupported_claim_is_regenerated_once_with_the_claim_named(
        self, world: World
    ) -> None:
        invented = UnsupportedClaim(
            quote="closed the Sequoia round", fact="absent", truth="no fact names a round"
        )
        world.agent.side_effect = [
            _weekly_voiced(lede="You closed the Sequoia round."),
            _weekly_voiced(),
        ]
        world.checker.side_effect = [_claims(invented), _claims()]

        await weekly.run_weekly_digest(_USER)

        assert world.agent.await_count == 2
        assert invented.problem() in world.agent.await_args_list[1].kwargs["request"].message
        assert _stored_payload(world).lede == _WEEKLY_VOICE["lede"]
        assert "lede: You closed the Sequoia round.\n" in _checked_prompt(world)
        assert world.weekly_prompt.call_args.kwargs["blocks"].context in _checked_prompt(world)

    async def test_a_recap_unsupported_twice_fails_and_sends_nothing(self, world: World) -> None:
        invented = UnsupportedClaim(quote="shipped twelve features", fact="absent", truth="one")
        world.agent.return_value = _weekly_voiced(lede="You shipped twelve features.")
        world.checker.return_value = _claims(invented)

        with pytest.raises(errors.BriefingGenerationError, match="no fact holds it"):
            await weekly.run_weekly_digest(_USER)

        assert world.checker.await_count == 2
        _assert_nothing_sent(world)

    async def test_a_typed_count_is_sent_back_before_the_checker_runs(self, world: World) -> None:
        world.agent.side_effect = [_weekly_voiced(lede="You finished 9 things."), _weekly_voiced()]

        await weekly.run_weekly_digest(_USER)

        retry = world.agent.await_args_list[1].kwargs["request"].message
        assert "the lede types '9' itself" in retry
        assert world.checker.await_count == 1

    async def test_a_message_that_skips_the_failed_run_or_the_week_ahead_is_sent_back(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _a_full_week(monkeypatch, world)
        world.agent.side_effect = [
            _weekly_voiced(message="Good week. [Send the deck](fact:<fact of Send the deck>)."),
            _weekly_voiced(),
        ]

        await weekly.run_weekly_digest(_USER)

        retry = world.agent.await_args_list[1].kwargs["request"].message
        assert "the message never refers to fact" in retry
        assert "(CRM sync failed)" in retry and "(Pitch to Accel)" in retry

    async def test_a_recap_without_a_message_fails_and_sends_nothing(self, world: World) -> None:
        world.agent.return_value = _weekly_voiced(message="")

        with pytest.raises(errors.BriefingGenerationError, match="message"):
            await weekly.run_weekly_digest(_USER)

        _assert_nothing_sent(world)


class TestHeldItemsJoinTheBrief:
    """Results held for the brief are candidates like any other.

    The held results come from brief-delivery workflows and the inbox desk; each
    appears once and is cleared once the brief went out.
    """

    async def test_a_held_result_joins_gaias_work_and_is_cleared(self, world: World) -> None:
        world.work = _brief_work()
        world.held = [_held("h1", "Paper digest", _DIGEST_REPORT)]

        await daily.run_daily_briefing(_USER)

        assert [(s.key, [i.text for i in s.items]) for s in _stored_payload(world).sections] == [
            (SectionKey.NEEDS_YOU, ["Approve the Priya reply"]),
            (SectionKey.GAIA_DID, ["Paper digest: 3 new papers on retrieval", "Investor update"]),
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

        await daily.run_daily_briefing(_USER)

        texts = [i.text for s in _stored_payload(world).sections for i in s.items]
        assert texts == ["Paper digest: 3 new papers on retrieval", "Digest: 3 new papers"]
        world.consume.assert_awaited_once()
        assert world.consume.await_args.args[0] == _USER
        assert sorted(world.consume.await_args.args[1]) == ["h1", "h2", "h3"]

    async def test_a_held_result_the_judge_dropped_is_cleared_and_one_past_the_cap_waits(
        self, world: World
    ) -> None:
        world.work = context.TrackedWork(completed=[_todo(f"c{i}", f"Done {i}") for i in range(3)])
        world.held = [_held("h1", "Digest", "first"), _held("h2", "Paper digest", "second")]
        world.judge.side_effect = _judged(
            gaia_did=["Done 0", "Done 1", "Done 2", "Paper digest: second"]
        )

        await daily.run_daily_briefing(_USER)

        texts = [i.text for s in _stored_payload(world).sections for i in s.items]
        assert texts == ["Done 0", "Done 1", "Done 2"]
        world.consume.assert_awaited_once_with(_USER, ["h1"])

    async def test_an_inbox_desk_finding_is_a_gmail_update(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        desk = _todo("desk-1", "Inbox desk")
        monkeypatch.setattr(
            todo_repository, "find_latest_by_external_ref", AsyncMock(return_value=desk)
        )
        finding = _held("h1", "Inbox desk", "Stripe payout of 2,400 dollars landed")
        world.held = [
            finding.model_copy(update={"source": BriefItemSource.TODO, "source_id": "desk-1"})
        ]

        await daily.run_daily_briefing(_USER)

        [section] = _stored_payload(world).sections
        assert section.key is SectionKey.UPDATES
        assert [(i.text, i.app, i.kind) for i in section.items] == [
            ("Stripe payout of 2,400 dollars landed", "Gmail", "note")
        ]
        assert _stored_payload(world).sources_read == ["Gmail", "Google Calendar"]

    async def test_a_failed_delivery_clears_nothing(self, world: World) -> None:
        world.held = [_held("h1", "Paper digest", _DIGEST_REPORT)]
        world.notify.side_effect = RuntimeError("orchestrator down")

        with pytest.raises(RuntimeError):
            await daily.run_daily_briefing(_USER)

        world.consume.assert_not_awaited()


def _voiced(headline: str, lede: str) -> SimpleNamespace:
    return SimpleNamespace(message=_fenced({**_VOICE, "headline": headline, "lede": lede}))


_LIVE_CONTRADICTION = _voiced(
    "Arjun's contract redlines need you today",
    "The Inbox desk also flagged a few items needing you, and an event today.",
)
_ARJUN = UnsupportedClaim(
    quote="Arjun's contract redlines need you", fact="absent", truth="no fact names Arjun"
)


def _claims(*claims: UnsupportedClaim) -> UnsupportedClaims:
    """Stand in for a checker answer that judged each claim's specific as the claim says."""
    return UnsupportedClaims(
        specifics=[
            CheckedSpecific(
                quote=c.quote,
                verdict="absent" if c.fact == "absent" else "contradicted",
                fact=None if c.fact == "absent" else c.fact,
                truth=c.truth,
            )
            for c in claims
        ]
    )


def _checked_prompt(world: World, call: int = 0) -> str:
    return world.checker.await_args_list[call].args[1]


class TestTheProseHoldsToItsFacts:
    """The rendered headline, lede, caption and message are checked against the facts before anything renders.

    Regression: a live brief's headline named a need over an empty needs-you section and
    its lede counted an event over an empty calendar.
    """

    async def test_an_unsupported_claim_is_regenerated_once_with_the_claims_named(
        self, world: World
    ) -> None:
        world.work = context.TrackedWork(completed=[_todo("c1", "Investor update")])
        world.agent.side_effect = [
            _LIVE_CONTRADICTION,
            _voiced("The investor update is done", "Sequoia is the one thing on today."),
        ]
        world.checker.side_effect = [_claims(_ARJUN), _claims()]

        await daily.run_daily_briefing(_USER)

        assert world.agent.await_count == 2
        retry = world.agent.await_args_list[1].kwargs["request"].message
        assert (
            f"YOUR LAST BRIEF WAS REJECTED\nIt did not match today's facts:\n- {_ARJUN.problem()}\n"
        ) in retry
        assert _stored_payload(world).headline == "The investor update is done"

    async def test_a_brief_unsupported_twice_fails_and_sends_nothing(self, world: World) -> None:
        world.work = context.TrackedWork(completed=[_todo("c1", "Investor update")])
        world.agent.side_effect = [_LIVE_CONTRADICTION, _LIVE_CONTRADICTION]
        world.checker.return_value = _claims(_ARJUN)

        with pytest.raises(errors.BriefingGenerationError, match="no fact holds it"):
            await daily.run_daily_briefing(_USER)

        assert world.checker.await_count == 2
        _assert_nothing_sent(world)

    async def test_the_checker_reads_the_rendered_prose_and_everything_the_writer_was_shown(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seam(
            monkeypatch,
            world,
            context,
            "format_goal_block",
            AsyncMock(return_value=("Raise a seed round from Accel", True)),
        )
        world.agent.return_value = _voiced(
            "Sequoia at [[fact:<fact of Sequoia>.time]]", "Then the Accel intro."
        )

        await daily.run_daily_briefing(_USER)

        checked = _checked_prompt(world)
        assert "headline: Sequoia at ⟦11:00 AM⟧\n" in checked
        assert "lede: Then the Accel intro.\n" in checked
        assert "message:\n⟦Sequoia⟧\n" in checked
        assert "[[" not in checked.split("## THE BRIEF", 1)[1]
        assert _stored_payload(world).headline == "Sequoia at 11:00 AM"
        blocks = world.voice_prompt.call_args.kwargs["blocks"]
        assert blocks.context in checked
        assert "Raise a seed round from Accel" in checked
        assert world.checker.await_args.args[0] is UnsupportedClaims

    async def test_a_count_the_model_was_shown_is_voiced_by_its_slot(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: 5 open todos were shown to the model, then rejected when it said 5."""
        _seam(
            monkeypatch,
            world,
            context,
            "user_open_todo_summary",
            AsyncMock(return_value=(5, ["Gym"])),
        )
        _seam(monkeypatch, world, context, "gather_calendar", AsyncMock(return_value=[]))
        world.agent.return_value = _voiced(
            "[[count:open_todos]] open todos, a quiet morning", "Nothing else today."
        )

        await daily.run_daily_briefing(_USER)

        assert "[COUNTS] open_todos: 5\n" in _prompt(world)
        assert world.agent.await_count == 1
        assert _stored_payload(world).headline == "5 open todos, a quiet morning"

    @pytest.mark.parametrize(
        ("headline", "named"),
        [
            ("6 open todos", "the headline types '6' itself"),
            ("[[count:done]] done overnight", "[[count:done]] is not a count the facts list"),
            ("[[fact:9]] is waiting", "fact:9 is no fact shown today"),
        ],
    )
    async def test_a_figure_typed_or_a_slot_naming_nothing_shown_is_regenerated(
        self, world: World, monkeypatch: pytest.MonkeyPatch, headline: str, named: str
    ) -> None:
        _seam(
            monkeypatch, world, context, "user_open_todo_summary", AsyncMock(return_value=(5, []))
        )
        world.agent.side_effect = [
            _voiced(headline, "A quiet morning."),
            _voiced("A quiet one", "-"),
        ]

        await daily.run_daily_briefing(_USER)

        assert named in world.agent.await_args_list[1].kwargs["request"].message
        assert world.checker.await_count == 1
        assert _stored_payload(world).headline == "A quiet one"

    async def test_a_headline_past_its_limit_once_filled_is_regenerated(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        long_title = "Sign " + "the long agreement " * 6
        _seam(
            monkeypatch,
            world,
            context,
            "gather_calendar",
            AsyncMock(return_value=[BriefingEvent(date=_DATE, start="11:00", title=long_title)]),
        )
        world.agent.side_effect = [
            _voiced("Today: [[fact:1]]", "One event."),
            _voiced("One long signing today", "One event."),
        ]

        await daily.run_daily_briefing(_USER)

        retry = world.agent.await_args_list[1].kwargs["request"].message
        assert (
            f"the headline once its slots are filled: String should have at most "
            f"{MAX_BRIEF_HEADLINE_CHARS} characters"
        ) in retry
        assert _stored_payload(world).headline == "One long signing today"


class TestTheMessageCoversTheDay:
    """The message refers, by a slot, to every fact waiting on the user and every event."""

    async def test_a_message_that_skips_a_need_or_an_event_is_regenerated_with_them_named(
        self, world: World
    ) -> None:
        world.work = _brief_work()
        world.agent.side_effect = [
            _wrote("The investor update went out."),
            _wrote(_FACTS_SHOWN),
        ]

        await daily.run_daily_briefing(_USER)

        retry = world.agent.await_args_list[1].kwargs["request"].message
        assert "the message never refers to fact 1 (Approve the Priya reply)" in retry
        assert "the message never refers to fact 3 (Sequoia)" in retry
        assert "fact 2 (Investor update)" not in retry
        assert world.checker.await_count == 1
        assert _stored_payload(world).message == "Approve the Priya reply\nInvestor update\nSequoia"

    async def test_a_reference_by_phrase_or_by_time_covers_a_fact(self, world: World) -> None:
        world.work = _brief_work()
        world.agent.return_value = _wrote("[Priya's reply](fact:1) first, then [[fact:3.time]].")

        await daily.run_daily_briefing(_USER)

        assert world.agent.await_count == 1
        assert _stored_payload(world).message == "Priya's reply first, then 11:00 AM."

    async def test_a_message_that_skips_a_need_twice_fails_and_sends_nothing(
        self, world: World
    ) -> None:
        world.work = _brief_work()
        world.agent.return_value = _wrote("[Sequoia](fact:3) at eleven.")

        with pytest.raises(errors.BriefingGenerationError, match="never refers to fact 1"):
            await daily.run_daily_briefing(_USER)

        world.checker.assert_not_awaited()
        _assert_nothing_sent(world)

    async def test_a_winback_note_need_not_cover_everything(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.work = _brief_work()
        _seam(
            monkeypatch,
            world,
            context,
            "compute_winback_state",
            AsyncMock(
                return_value=context.WinbackState(
                    unacknowledged=WINBACK_THRESHOLD, last_was_winback=False
                )
            ),
        )
        world.agent.return_value = _wrote("The investor update is still sitting here, want it?")

        await daily.run_daily_briefing(_USER)

        assert world.agent.await_count == 1
        assert _stored_payload(world).mood == "winback"


_RAW_NEWLINE_PARAGRAPHS = SimpleNamespace(
    message=_fenced({**_VOICE, "message": f"{_FACTS_SHOWN}<para>That is the day."}).replace(
        "<para>", "\n\n"
    )
)
_MOOD_LEFT_OUT = SimpleNamespace(
    message=_fenced({key: value for key, value in _VOICE.items() if key != "mood"})
)


@pytest.mark.unit
class TestAnUnreadableVoiceIsRetried:
    """Regression: 2 of 3 live daily runs failed with "No valid voice JSON" and no retry."""

    async def test_a_message_with_raw_newlines_between_paragraphs_is_read(
        self, world: World
    ) -> None:
        """The live failing reply wrote its paragraphs with literal newlines inside the string."""
        world.agent.return_value = _RAW_NEWLINE_PARAGRAPHS

        await daily.run_daily_briefing(_USER)

        assert world.agent.await_count == 1
        assert _stored_payload(world).message.endswith("\n\nThat is the day.")

    async def test_an_unreadable_reply_is_retried_once_with_its_problem_named(
        self, world: World
    ) -> None:
        world.agent.side_effect = [_MOOD_LEFT_OUT, SimpleNamespace(message=_fenced(_VOICE))]

        await daily.run_daily_briefing(_USER)

        assert world.agent.await_count == 2
        first = world.agent.await_args_list[0].kwargs["request"].message
        retry = world.agent.await_args_list[1].kwargs["request"].message
        assert retry == f"{first}\n\n{voice_unreadable_note(['mood: Field required'])}"
        assert _stored_payload(world).headline == _VOICE["headline"]

    async def test_an_unreadable_reply_is_logged_by_length_and_problems_never_its_text(
        self, world: World
    ) -> None:
        world.agent.side_effect = [_MOOD_LEFT_OUT, SimpleNamespace(message=_fenced(_VOICE))]

        async with captured_wide_event() as event:
            await daily.run_daily_briefing(_USER)

        first = world.agent.await_args_list[0].kwargs["request"].message
        assert {
            "msg": "briefing.voice_unreadable",
            "raw_length": len(_message_written(first, _MOOD_LEFT_OUT.message)),
            "problems": ["mood: Field required"],
        } in event["warnings"]

    def test_the_failure_lists_every_problem_joined(self) -> None:
        error = errors.VoiceUnreadableError(["first problem", "second problem"])

        assert str(error) == "No valid voice JSON in agent output: first problem; second problem"

    async def test_a_reply_unreadable_twice_fails_naming_the_shape_not_the_text(
        self, world: World
    ) -> None:
        cut_short = SimpleNamespace(message='```json\n{"headline": "Arjun needs the redlines\n```')
        world.agent.side_effect = [_MOOD_LEFT_OUT, cut_short]

        with pytest.raises(errors.VoiceUnreadableError) as err:
            await daily.run_daily_briefing(_USER)

        assert err.value.problems == [
            "invalid JSON: Unterminated string starting at (char 13 of 38)"
        ]
        assert "Arjun" not in str(err.value)
        _assert_nothing_sent(world)


def _wrote(message: str) -> SimpleNamespace:
    return SimpleNamespace(message=_fenced({**_VOICE, "message": message}))


class TestWhatTheWriterIsShown:
    async def test_the_model_sees_how_recent_briefs_opened(self, world: World) -> None:
        def brief(message: str | None) -> BriefingModel:
            payload = BriefingPayload(
                kicker="K",
                date="2026-10-13",
                headline="h",
                lede="l",
                mood="packed",
                caption="c",
                message=message,
                template_family="swiss",
            )
            return BriefingModel(id="b", user_id=_USER, date="2026-10-13", payload=payload)

        world.recent.return_value = [brief("\n  Priya replied overnight.\nMore."), brief(None)]

        await daily.run_daily_briefing(_USER)

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

        await daily.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        items = [(it.text, it.todo_id, it.count) for s in payload.sections for it in s.items]
        assert items == [("Approve the Acme MSA renewal", "b1", 3), ("Reply to Daniel", "b4", 1)]
        facts = _facts_shown(_prompt(world))
        assert facts.count("Acme MSA renewal") == 1
        assert "Approve the Acme MSA renewal | 3 requests, one item" in facts
        assert "Reply to Daniel | 1 requests" not in facts
        assert "[COUNTS] needs_you: 2 · events: 1\n" in facts
        assert [(s.value, s.label) for s in payload.stats] == [("2", "waiting on you")]

    async def test_two_requests_for_one_subject_are_counted_as_two(self, world: World) -> None:
        world.work = context.TrackedWork(
            blocked=[
                _todo("b1", "Approve the Acme MSA renewal"),
                _todo("b2", "Approve the Acme MSA renewal"),
            ]
        )

        await daily.run_daily_briefing(_USER)

        assert "Approve the Acme MSA renewal | 2 requests, one item" in _facts_shown(_prompt(world))

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

        await daily.run_daily_briefing(_USER)

        items = [(it.text, it.count) for s in _stored_payload(world).sections for it in s.items]
        assert items == [("Approve the Acme MSA", 2)]

    async def test_threads_the_inbox_desk_opened_are_one_item_each(self, world: World) -> None:
        world.work = context.TrackedWork(
            blocked=[
                TodoDocument(
                    id=f"t{n}",
                    user_id=_USER,
                    title=title,
                    labels=[GAIA_TRACKED_LABEL, NEEDS_REPLY_LABEL],
                    parent_todo_id="desk",
                    external_ref=ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id=f"th{n}"),
                )
                for n, title in enumerate(["Priya · pitch deck", "Arjun · contract"])
            ]
        )

        await daily.run_daily_briefing(_USER)

        items = [(it.text, it.count) for s in _stored_payload(world).sections for it in s.items]
        assert items == [("Priya · pitch deck", 1), ("Arjun · contract", 1)]


def _brief_work() -> context.TrackedWork:
    return context.TrackedWork(
        blocked=[_todo("b1", "Approve the Priya reply")],
        completed=[_todo("c1", "Investor update")],
    )


class TestTheDailyRunWiring:
    """Every read is scoped to the user and the last local day, and every write records it."""

    async def test_the_producers_read_this_user_since_the_last_local_day(
        self, world: World
    ) -> None:
        world.held = [_held("h1", "Paper digest", _DIGEST_REPORT)]

        await daily.run_daily_briefing(_USER)

        cast(
            "AsyncMock", approval_ledger_repository.list_pending_for_user
        ).assert_awaited_once_with(_USER)
        cast("AsyncMock", hil_approval_repository.list_pending_for_user).assert_awaited_once_with(
            _USER, _NOW
        )
        assert world.reads["list_since"].await_args.args == (_USER, _DAY_START)
        assert world.reads["find_latest_by_external_ref"].await_args.args[0] == _USER

    async def test_the_selection_is_asked_for_this_user_on_their_clock(self, world: World) -> None:
        world.work = _brief_work()

        await daily.run_daily_briefing(_USER)

        assert world.judge.await_args.kwargs["config"] == {"configurable": {"user_id": _USER}}
        assert f"Today is {_DATE} ({_TZ})." in world.judge.await_args.args[1]

    async def test_a_user_without_a_timezone_is_judged_on_utc(self, world: World) -> None:
        world.user.timezone = None
        world.work = _brief_work()

        await daily.run_daily_briefing(_USER)

        assert "(UTC)." in world.judge.await_args.args[1]

    async def test_the_wide_event_counts_the_candidates_the_selection_chose_from(
        self, world: World
    ) -> None:
        world.work = _brief_work()

        async with captured_wide_event() as event:
            await daily.run_daily_briefing(_USER)

        assert event["brief_selection"]["candidates"] == 3

    async def test_every_read_is_for_this_user_and_the_last_local_day(self, world: World) -> None:
        await daily.run_daily_briefing(_USER)

        world.reads["format_goal_block"].assert_awaited_once_with(_USER, world.user)
        world.reads["get_yesterday_payload"].assert_awaited_once_with(_USER, before_date=_DATE)
        world.reads["format_lookback_block"].assert_awaited_once_with(
            _USER, sentinel.yesterday, _DAY_START
        )
        assert world.reads["compute_winback_state"].await_args.args[0].id == _USER
        world.reads["has_daily_briefing"].assert_awaited_once_with(_USER)
        world.reads["gather_tracked_work"].assert_awaited_once_with(_USER, _DAY_START)
        world.reads["user_open_todo_summary"].assert_awaited_once_with(_USER)
        world.reads["gather_completed_since"].assert_awaited_once_with(_USER, _DAY_START)
        calendar_call = world.reads["gather_calendar"].await_args
        assert calendar_call.args[0] == _USER and calendar_call.kwargs == {"days": 1}
        assert (calendar_call.args[1].date_str, calendar_call.args[1].tz.key) == (_DATE, _TZ)
        world.reads["list_for_user"].assert_awaited_once_with(_USER, sort=[("created_at", 1)])
        world.reads["format_replies_block"].assert_awaited_once_with(_USER, _DAY_START)
        world.reads["record_idle_day"].assert_awaited_once_with(
            _USER, dormancy.state_from_user(world.user), False, _DATE
        )
        prompt_args = world.voice_prompt.call_args.kwargs
        assert prompt_args["date_local"] == _DATE
        assert (
            prompt_args["blocks"].goal,
            prompt_args["blocks"].lookback,
            prompt_args["blocks"].replies,
        ) == ("Ship v2", "-", "No replies.")
        assert prompt_args["situation"] == VoiceSituation()

    async def test_a_users_first_brief_is_voiced_as_their_first(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seam(
            monkeypatch,
            world,
            briefing_repository,
            "has_daily_briefing",
            AsyncMock(return_value=False),
        )

        await daily.run_daily_briefing(_USER)

        assert world.voice_prompt.call_args.kwargs["situation"].is_first_briefing is True

    async def test_the_agent_runs_once_in_the_background_on_a_fresh_daily_thread(
        self, world: World
    ) -> None:
        await daily.run_daily_briefing(_USER)

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

        await daily.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        assert (payload.kicker, payload.date, payload.generated_at) == (
            "THE MORNING BRIEF",
            _DATE,
            "7:05 AM",
        )
        assert payload.hue == 79
        assert payload.mood == "packed"
        assert payload.caption == "Onward."
        assert payload.message == "Approve the Priya reply\nInvestor update\nSequoia"
        assert [(s.value, s.label) for s in payload.stats] == [
            ("1", "done since yesterday"),
            ("1", "waiting on you"),
        ]

    async def test_a_zero_count_is_never_shown_to_the_model(self, world: World) -> None:
        world.work = context.TrackedWork(running=[_todo("r1", "Research")])

        await daily.run_daily_briefing(_USER)

        assert "[COUNTS] in_progress: 1 · events: 1\n" in _prompt(world)

    async def test_delivery_opens_the_brief_and_posts_the_image_as_the_daily_brief(
        self, world: World
    ) -> None:
        world.work = _brief_work()

        await daily.run_daily_briefing(_USER)

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
        _family_first(world, "memo")

        await daily.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        channels = [*_ORCHESTRATED, "telegram"]
        world.set_channels.assert_awaited_once_with(_USER, _DATE, "daily", channels)
        world.capture.assert_called_once_with(
            UserId(_USER),
            BriefingSent(
                kind="daily",
                family=payload.template_family,
                mood="packed",
                item_count=2,
                channel_count=3,
                signal_count=0,
                stamp_collected=payload.new_stamp is not None,
                lead_count=0,
                needs_you_count=1,
                updates_count=0,
                gaia_did_count=1,
                source_count=1,
            ),
        )

    async def test_the_run_is_tagged_on_its_wide_event(self, world: World) -> None:
        async with captured_wide_event() as event:
            await daily.run_daily_briefing(_USER)

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

        await daily.run_daily_briefing(_USER)

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

        await daily.run_daily_briefing(_USER)

        assert (
            "[COUNTS] needs_you: 3 · done: 1 · in_progress: 1 · while_away: 1 · events: 1\n"
            "[Needs you]\n"
            "- fact 1 | Waiting on you: Approve the reply | summary: Draft ready"
            " | artifact holds ~11 chars | waiting on you | linkable\n"
            "- fact 2 | Failed: Sync | artifact holds ~0 chars\n"
            "- fact 3 | Failed: Scrape | artifact holds ~0 chars\n"
            "[GAIA's work]\n"
            "- fact 4 | Note: Digest: first\n"
            "- fact 5 | Done: Deck | artifact holds ~0 chars\n"
            "- fact 6 | In progress: Research | artifact holds ~0 chars\n"
            "The user's own todo list is empty.\n"
            "Today's calendar:\n"
            "- fact 8 | 11:00 AM: Sequoia"
        ) in _prompt(world)
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

        await daily.run_daily_briefing(_USER)

        assert "| Done: Deck | summary: First line Second line | artifact holds" in _prompt(world)
        assert f"| Done: Long | summary: {'x' * 239} | artifact holds" in _prompt(world)

    async def test_the_size_hint_counts_the_deliverable_not_its_logs(self, world: World) -> None:
        doc = _todo("c1", "Pick a forum")
        doc.canvas_content = (
            "Intro line\n<!-- note -->\n\n## Result\nDecision made\n"
            "## Activity Log\nstep one\n\nstep two\n## timeline\nx"
        )
        world.work = context.TrackedWork(completed=[doc])

        await daily.run_daily_briefing(_USER)

        assert "| artifact holds ~24 chars" in _prompt(world)

    async def test_a_todo_in_two_states_keeps_its_first_artifact(self, world: World) -> None:
        first, again, blocked = _todo("c1", "Deck"), _todo("c1", "Deck"), _todo("b1", "Reply")
        first.canvas_content, again.canvas_content, blocked.canvas_content = "One", "Two", "Three"
        world.work = context.TrackedWork(completed=[first], running=[again], blocked=[blocked])

        await daily.run_daily_briefing(_USER)

        prompt = _prompt(world)
        assert (
            "- fact 2 | Done: Deck | summary: One | artifact holds ~3 chars | linkable\n" in prompt
        )
        assert (
            "- fact 3 | In progress: Deck | summary: One | artifact holds ~3 chars | linkable\n"
            in prompt
        )
        assert (
            "- fact 1 | Waiting on you: Reply | summary: Three | artifact holds ~5 chars | waiting"
            in prompt
        )

    async def test_with_nothing_tracked_the_model_is_told_nothing_ran(self, world: World) -> None:
        await daily.run_daily_briefing(_USER)

        assert (
            "[COUNTS] events: 1\n"
            "GAIA has no tracked work and no background work ran. Do not claim anything "
            "ran, finished, or is pending beyond what is stated here.\n"
            "The user's own todo list is empty.\n"
            "Today's calendar:\n- fact 1 | 11:00 AM: Sequoia"
        ) in _prompt(world)

    @pytest.mark.parametrize(
        ("summary", "counts", "note"),
        [
            (
                (2, ["Gym", "Taxes"]),
                "[COUNTS] open_todos: 2 · events: 1\n",
                "The user's own open todos (first few: Gym; Taxes) are counted in [COUNTS]"
                "; never voice that list as clear or empty.\n",
            ),
            (
                (3, []),
                "[COUNTS] open_todos: 3 · events: 1\n",
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
        _seam(
            monkeypatch, world, context, "user_open_todo_summary", AsyncMock(return_value=summary)
        )

        await daily.run_daily_briefing(_USER)

        assert counts in _prompt(world)
        assert note in _prompt(world)

    async def test_an_untimed_event_reads_all_day_and_none_reads_empty(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        offsite = BriefingEvent(date=_DATE, title="Offsite")
        _seam(
            monkeypatch,
            world,
            context,
            "gather_calendar",
            AsyncMock(return_value=[offsite, _EVENT]),
        )
        await daily.run_daily_briefing(_USER)
        assert (
            "is empty.\nToday's calendar:\n"
            "- fact 1 | all day: Offsite\n- fact 2 | 11:00 AM: Sequoia\n\n## YESTERDAY"
        ) in _prompt(world)

        _seam(monkeypatch, world, context, "gather_calendar", AsyncMock(return_value=[]))
        await daily.run_daily_briefing(_USER)
        assert (
            "is empty.\nThe user's calendar has nothing today (or no calendar is connected)."
            "\n\n## YESTERDAY"
        ) in _prompt(world)

    async def test_a_held_result_with_a_blank_report_shows_only_its_source(
        self, world: World
    ) -> None:
        world.held = [_held("h1", "Digest", "  \n ")]

        await daily.run_daily_briefing(_USER)

        assert [i.text for s in _stored_payload(world).sections for i in s.items] == ["Digest"]


def _todo_link(todo_id: str) -> str:
    return f"https://heygaia.link/todo-{todo_id}"


class TestOnlyTheItemsTheBriefLinksAreShared:
    """A forwarded brief exposes exactly the deliverables its message links, nothing more."""

    @pytest.fixture(autouse=True)
    def keyed_mint(self, world: World) -> None:
        def mint(user_id: str, target_type: ShortLinkTargetType, target_id: str) -> str:
            if user_id != _USER:
                raise AssertionError(f"minted for {user_id!r}, not the brief's owner")
            if target_type is ShortLinkTargetType.TODO_DELIVERABLE:
                return _todo_link(target_id)
            return _BRIEF_LINK

        world.mint.side_effect = mint
        deck, reply = _todo("c1", "Deck"), _todo("b1", "Reply")
        deck.canvas_content, reply.canvas_content = "Ten slides", "A draft reply"
        world.work = context.TrackedWork(completed=[deck], blocked=[reply])

    @staticmethod
    def _voice(world: World, message: str) -> None:
        world.agent.return_value = _wrote(f"{message}\nSequoia at [[fact:3.time]].")

    async def test_a_linked_item_gets_its_link_on_its_phrase_and_an_unlinked_one_is_never_minted(
        self, world: World
    ) -> None:
        # b1 (needs you) is fact 1, c1 (done) fact 2, Sequoia fact 3; only the reply is linked.
        self._voice(world, "the deck is done\n[the reply](fact:1) waits on you")

        await daily.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        assert payload.message == (
            f"the deck is done\n[the reply]({_todo_link('b1')}) waits on you\nSequoia at 11:00 AM."
        )
        links = {it.todo_id: it.link for sec in payload.sections for it in sec.items}
        assert links == {"b1": _todo_link("b1"), "c1": None}
        minted = [c.args[2] for c in world.mint.await_args_list]
        assert minted == ["b1", _BRIEF_ID]

    async def test_one_item_is_linked_once_however_often_its_slot_is_written(
        self, world: World
    ) -> None:
        """Regression: one approval became one line with three raw links."""
        self._voice(
            world, "the [deck](fact:2) is done, [open it](fact:2)\n[the reply](fact:1) waits on you"
        )

        await daily.run_daily_briefing(_USER)

        message = _stored_payload(world).message or ""
        assert message.count(_todo_link("c1")) == 1
        assert message.startswith(f"the [deck]({_todo_link('c1')}) is done, open it\n")

    async def test_a_slot_with_no_link_behind_it_leaves_its_phrase_as_text(
        self, world: World
    ) -> None:
        """Sharing turned off (or a failed mint) leaves the sentence, not a raw slot."""
        world.mint.side_effect = lambda user_id, target_type, target_id: (
            None if target_type is ShortLinkTargetType.TODO_DELIVERABLE else _BRIEF_LINK
        )
        self._voice(world, "the [deck](fact:2) is done\nthe [reply](fact:1) waits")

        await daily.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        assert payload.message == "the deck is done\nthe reply waits\nSequoia at 11:00 AM."
        assert all(it.link is None for sec in payload.sections for it in sec.items)

    async def test_a_resolved_link_is_markdown_on_its_phrase_in_the_chat_post(
        self, world: World
    ) -> None:
        self._voice(world, "[The shortlist is ready](fact:2)\n[the reply](fact:1) waits on you")

        await daily.run_daily_briefing(_USER)

        text = world.post.await_args.kwargs["text"]
        assert (
            f"[The shortlist is ready]({_todo_link('c1')})\n[the reply]({_todo_link('b1')}) waits"
            in text
        )

    @pytest.mark.parametrize(
        ("written", "named"),
        [
            # Live: the model wrapped the facts' token in its phrase and "[...|]" reached users.
            ("[Book flights for the Berlin offsite|[[fact:2]]]", "'offsite|]'"),
            ("[[fact:2|The shortlist is ready]]", "'[[fact:2|The'"),
            ("[The shortlist is ready|(fact:2)]", "'ready|(fact:2)]'"),
            ("[The shortlist is ready] (fact:2)", "'(fact:2)'"),
            ("[The shortlist is ready](link:1)", "'[The shortlist is ready](link:1)'"),
            ("[The shortlist is ready](fact:7)", "fact:7 is no fact shown today"),
        ],
    )
    async def test_a_malformed_or_unknown_link_is_regenerated_once_with_it_named(
        self, world: World, written: str, named: str
    ) -> None:
        world.agent.side_effect = [
            _wrote(f"{written}\n[the reply](fact:1) waits on you\n[Sequoia](fact:3)"),
            _wrote(
                "[The shortlist is ready](fact:2)\n[the reply](fact:1) waits on you\n[Sequoia](fact:3)"
            ),
        ]

        await daily.run_daily_briefing(_USER)

        assert world.agent.await_count == 2
        retry = world.agent.await_args_list[1].kwargs["request"].message
        assert named in retry
        assert _stored_payload(world).message == (
            f"[The shortlist is ready]({_todo_link('c1')})\n"
            f"[the reply]({_todo_link('b1')}) waits on you\nSequoia"
        )

    async def test_a_link_malformed_twice_fails_and_sends_nothing(self, world: World) -> None:
        world.agent.side_effect = [
            _wrote(
                "[Book flights for the Berlin offsite|[[fact:2]]]\n[the reply](fact:1) waits on you"
            )
        ] * 2

        with pytest.raises(errors.BriefingGenerationError, match="malformed slot"):
            await daily.run_daily_briefing(_USER)

        _assert_nothing_sent(world)

    async def test_an_item_with_nothing_to_open_is_not_linkable(self, world: World) -> None:
        deck = _todo("c1", "Deck")
        deck.canvas_content = "Ten slides"
        world.work = context.TrackedWork(failed=[_todo("f1", "Sync")], completed=[deck])
        self._voice(world, "the [sync](fact:1) failed\nthe [deck](fact:2) is done")

        await daily.run_daily_briefing(_USER)

        assert "- fact 1 | Failed: Sync | artifact holds ~0 chars\n" in _prompt(world)
        assert (
            "- fact 2 | Done: Deck | summary: Ten slides | artifact holds ~10 chars | linkable\n"
            in (_prompt(world))
        )
        assert (_stored_payload(world).message or "").startswith(
            f"the sync failed\nthe [deck]({_todo_link('c1')}) is done"
        )
        assert [c.args[2] for c in world.mint.await_args_list] == ["c1", _BRIEF_ID]

    async def test_a_brief_without_a_heygaia_link_still_goes_out_to_its_app_page(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.services.briefing.message.settings.FRONTEND_URL", "https://app.test"
        )
        world.mint.side_effect = lambda *_: None

        await daily.run_daily_briefing(_USER)

        request = world.notify.await_args.args[0]
        assert request.metadata["brief_url"] == f"https://app.test/brief/{_BRIEF_ID}"
        assert world.host_image.await_args.args[0].link == f"https://app.test/brief/{_BRIEF_ID}"
        world.post.assert_awaited_once()
        assert world.post.await_args.kwargs["text"].endswith(
            f"Full brief: https://app.test/brief/{_BRIEF_ID}"
        )


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
    def _no_goal(monkeypatch: pytest.MonkeyPatch, world: World) -> None:
        _seam(monkeypatch, world, context, "format_goal_block", AsyncMock(return_value=("", False)))

    @pytest.mark.parametrize(
        "since", [_NOW - timedelta(days=1), (_NOW - timedelta(days=1)).replace(tzinfo=None)]
    )
    async def test_inside_the_grace_window_without_a_goal_nothing_is_sent(
        self, world: World, monkeypatch: pytest.MonkeyPatch, since: datetime
    ) -> None:
        self._pending(world, since)
        self._no_goal(monkeypatch, world)

        await daily.run_daily_briefing(_USER)

        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    @pytest.mark.parametrize("age", [timedelta(days=3), timedelta(days=4)])
    async def test_once_the_grace_window_has_passed_the_brief_goes_out(
        self, world: World, monkeypatch: pytest.MonkeyPatch, age: timedelta
    ) -> None:
        self._pending(world, _NOW - age)
        self._no_goal(monkeypatch, world)

        await daily.run_daily_briefing(_USER)

        world.upsert.assert_awaited_once()
        world.clear_bootstrap.assert_awaited_once_with(_USER)

    async def test_a_known_goal_releases_the_hold_and_clears_it(self, world: World) -> None:
        self._pending(world, _NOW - timedelta(hours=1))

        await daily.run_daily_briefing(_USER)

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
        self._no_goal(monkeypatch, world)

        await daily.run_daily_briefing(_USER)

        world.upsert.assert_awaited_once()

    async def test_a_user_never_held_has_nothing_to_clear(self, world: World) -> None:
        await daily.run_daily_briefing(_USER)

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
        _seam(monkeypatch, world, dormancy, "latest_activity_since", AsyncMock(return_value=_NOW))

        await daily.run_daily_briefing(_USER)

        (user_id, since), _ = world.reads["latest_activity_since"].await_args
        assert (user_id, since) == (_USER, _DORMANT_SINCE)
        world.clear_dormancy.assert_awaited_once_with(_USER)
        assert world.reads["record_idle_day"].await_args.args[1] == DormancyState(
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
        _seam(
            monkeypatch, world, context, "format_goal_block", AsyncMock(return_value=("", has_goal))
        )

        await daily.run_daily_briefing(_USER)

        assert world.reads["record_idle_day"].await_args.args[2] is idle

    @pytest.mark.parametrize(("idle_days", "stage"), [(2, "warn"), (3, "final")])
    async def test_the_idle_streak_sets_the_wind_down_and_the_goodbye_goes_dormant(
        self, world: World, monkeypatch: pytest.MonkeyPatch, idle_days: int, stage: str
    ) -> None:
        _seam(monkeypatch, world, context, "format_goal_block", AsyncMock(return_value=("", False)))
        _seam(monkeypatch, world, dormancy, "record_idle_day", AsyncMock(return_value=idle_days))

        await daily.run_daily_briefing(_USER)

        assert world.voice_prompt.call_args.kwargs["situation"].wind_down == stage
        if stage == "final":
            world.enter_dormancy.assert_awaited_once_with(_USER)
        else:
            world.enter_dormancy.assert_not_awaited()

    async def test_the_wind_down_message_is_pushed_even_on_an_empty_day(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seam(monkeypatch, world, context, "format_goal_block", AsyncMock(return_value=("", False)))
        _seam(monkeypatch, world, dormancy, "record_idle_day", AsyncMock(return_value=2))
        _seam(monkeypatch, world, context, "gather_calendar", AsyncMock(return_value=[]))

        await daily.run_daily_briefing(_USER)

        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == _ORCHESTRATED
        world.post.assert_awaited_once()

    async def test_a_long_streak_with_work_to_report_does_not_wind_down(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seam(monkeypatch, world, dormancy, "record_idle_day", AsyncMock(return_value=5))

        await daily.run_daily_briefing(_USER)

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
        _seam(
            monkeypatch,
            world,
            context,
            "compute_winback_state",
            AsyncMock(
                return_value=context.WinbackState(
                    unacknowledged=WINBACK_THRESHOLD, last_was_winback=False
                )
            ),
        )
        _seam(monkeypatch, world, context, "format_goal_block", AsyncMock(return_value=("", False)))
        _seam(monkeypatch, world, dormancy, "record_idle_day", AsyncMock(return_value=idle_days))

        await daily.run_daily_briefing(_USER)

        assert world.voice_prompt.call_args.kwargs["situation"].winback is voiced_winback
        assert _stored_payload(world).mood == "winback"


def _idle_day(monkeypatch: pytest.MonkeyPatch, world: World, streak: int) -> None:
    """Make today a day with nothing to report, at the given idle streak."""
    _seam(monkeypatch, world, context, "format_goal_block", AsyncMock(return_value=("", False)))
    _seam(monkeypatch, world, dormancy, "record_idle_day", AsyncMock(return_value=streak))


class TestTheFirstWeek:
    """A new account's first week helps it get value instead of winding down."""

    async def test_a_first_week_account_never_climbs_the_idle_ladder(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.user.created_at = _NOW - timedelta(days=FIRST_WEEK_DAYS, seconds=-1)
        _idle_day(monkeypatch, world, IDLE_DORMANT_DAYS)

        await daily.run_daily_briefing(_USER)

        assert world.reads["record_idle_day"].await_args.args[2] is False
        assert world.voice_prompt.call_args.kwargs["situation"].wind_down is None
        assert world.voice_prompt.call_args.kwargs["situation"].first_week is True
        world.enter_dormancy.assert_not_awaited()

    async def test_the_ladder_runs_once_the_first_week_is_over(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.user.created_at = _NOW - timedelta(days=FIRST_WEEK_DAYS)
        _idle_day(monkeypatch, world, IDLE_DORMANT_DAYS)

        await daily.run_daily_briefing(_USER)

        assert world.reads["record_idle_day"].await_args.args[2] is True
        assert world.voice_prompt.call_args.kwargs["situation"].wind_down == "final"
        assert world.voice_prompt.call_args.kwargs["situation"].first_week is False
        world.enter_dormancy.assert_awaited_once_with(_USER)

    @pytest.mark.parametrize(
        ("apps", "line"),
        [
            (["Gmail", "Notion"], "Apps they've connected: Gmail, Notion."),
            ([], "Apps they've connected: none yet."),
        ],
    )
    async def test_a_first_week_brief_sees_the_apps_actually_connected(
        self, world: World, apps: list[str], line: str
    ) -> None:
        world.user.created_at = _NOW - timedelta(days=1)
        world.connected_apps = apps

        await daily.run_daily_briefing(_USER)

        assert "THEIR GAIA SETUP" in _prompt(world)
        assert line in _prompt(world)

    async def test_an_older_account_is_shown_no_setup(self, world: World) -> None:
        world.user.created_at = _NOW - timedelta(days=30)
        world.connected_apps = ["Gmail"]

        await daily.run_daily_briefing(_USER)

        assert "THEIR GAIA SETUP" not in _prompt(world)


class TestTheLighterCadenceOffer:
    """A user who stopped coming back is offered fewer briefs, with their real cadence."""

    async def test_an_idle_user_is_offered_a_lighter_cadence(self, world: World) -> None:
        world.activity = ActivityStatus.IDLE
        world.user.briefing_schedule = BriefingSchedule(
            frequency=BriefingFrequency.WEEKDAYS, hour=9
        )

        await daily.run_daily_briefing(_USER)

        assert world.voice_prompt.call_args.kwargs["situation"].offer_lighter_cadence is True
        assert "a daily brief Monday to Friday at 09:00" in _prompt(world)
        assert "offer a lighter rhythm" in _prompt(world)

    async def test_a_first_week_idle_user_sees_their_cadence_and_apps_on_separate_lines(
        self, world: World
    ) -> None:
        world.activity = ActivityStatus.IDLE
        world.user.created_at = _NOW - timedelta(days=1)
        world.connected_apps = ["Gmail"]

        await daily.run_daily_briefing(_USER)

        assert (
            "Their briefs now: a daily brief every day at 08:00, plus the Sunday evening "
            "weekly digest.\nApps they've connected: Gmail."
        ) in _prompt(world)

    async def test_an_active_user_is_not(self, world: World) -> None:
        await daily.run_daily_briefing(_USER)

        assert world.voice_prompt.call_args.kwargs["situation"].offer_lighter_cadence is False
        assert "offer a lighter rhythm" not in _prompt(world)


_NOISE_BLOCKS = '```json\n\n```\n```json\n{oops\n```\n```json\n{"a": 1}\n```\n'


class TestTheAgentOutput:
    """The model's text must hold one valid JSON object; anything else fails loudly."""

    async def test_the_voice_is_found_past_empty_malformed_and_foreign_blocks(
        self, world: World
    ) -> None:
        world.agent.return_value = SimpleNamespace(message=_NOISE_BLOCKS + _fenced(_VOICE))

        await daily.run_daily_briefing(_USER)

        assert _stored_payload(world).headline == "Your morning, sorted"

    async def test_a_missing_voice_names_why_without_echoing_the_reply(self, world: World) -> None:
        world.agent.return_value = SimpleNamespace(message="y" * 400)

        with pytest.raises(errors.BriefingGenerationError) as err:
            await daily.run_daily_briefing(_USER)

        assert str(err.value) == (
            "No valid voice JSON in agent output: invalid JSON: Expecting value (char 0 of 400)"
        )

    async def test_a_lede_alone_making_an_unsupported_claim_is_sent_back(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seam(monkeypatch, world, context, "gather_calendar", AsyncMock(return_value=[]))
        world.work = context.TrackedWork(completed=[_todo("c1", "Investor update")])
        world.agent.side_effect = [
            _voiced("The investor update is done", "You have a meeting at noon."),
            _voiced("The investor update is done", "Nothing else today."),
        ]
        claim = UnsupportedClaim(quote="a meeting at noon", fact="absent", truth="no events today")
        world.checker.side_effect = [_claims(claim), _claims()]

        async with captured_wide_event() as event:
            await daily.run_daily_briefing(_USER)

        assert world.agent.await_count == 2
        assert claim.problem() in world.agent.await_args_list[1].kwargs["request"].message
        assert {"msg": "briefing.voice_rejected", "problems": [claim.problem()]} in event[
            "warnings"
        ]


def _weekly_completed() -> context.CompletedWork:
    deck = _todo("g0", "Deck")
    deck.canvas_content = "# Deck\nFinal numbers in"
    gaia = [deck, *[_todo(f"g{i}", f"G{i}") for i in range(1, 16)]]
    user = [_todo(f"u{i}", f"U{i}") for i in range(16)]
    return context.CompletedWork(gaia=gaia, user=user)


class TestTheWeeklyRunWiring:
    async def test_the_week_is_read_for_this_user_from_monday_in_one_window(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seam(
            monkeypatch,
            world,
            context,
            "gather_completed_since",
            AsyncMock(return_value=_weekly_completed()),
        )
        world.agent.return_value = _weekly_voiced()

        async with captured_wide_event() as event:
            await weekly.run_weekly_digest(_USER)

        world.reads["gather_completed_since"].assert_awaited_once_with(_USER, _WEEK_START)
        week_call = world.reads["gather_week"].await_args
        assert (week_call.args[0], week_call.args[1].date_str) == (_USER, _DATE)
        # The sections, the prose and the tallies read the same completions: one window for all.
        assert week_call.args[2] is world.reads["gather_completed_since"].return_value
        judged = world.judge.await_args.args[1]
        assert "[GAIA] gaia_did: Deck" in judged
        assert "[GAIA] update: U15" in judged
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
        assert event["brief_selection"]["candidates"] == 32

    async def test_the_voice_is_found_past_other_blocks(self, world: World) -> None:
        world.agent.return_value = SimpleNamespace(message=_NOISE_BLOCKS + _fenced(_WEEKLY_VOICE))

        await weekly.run_weekly_digest(_USER)

        assert _stored_payload(world).headline == "A good week"

    async def test_a_recap_missing_from_the_output_twice_fails_naming_why(
        self, world: World
    ) -> None:
        world.agent.return_value = SimpleNamespace(message="z" * 400)

        with pytest.raises(errors.BriefingGenerationError) as err:
            await weekly.run_weekly_digest(_USER)

        assert str(err.value) == (
            "No valid voice JSON in agent output: invalid JSON: Expecting value (char 0 of 400)"
        )
        assert world.agent.await_count == 2
        _assert_nothing_sent(world)

    async def test_an_unknown_user_fails_loud(self, world: World) -> None:
        world.user = UserDocument(id="someone-else", timezone=_TZ)

        with pytest.raises(errors.BriefingGenerationError, match=f"unknown user {_USER}$"):
            await weekly.run_weekly_digest(_USER)

        world.agent.assert_not_awaited()

    @pytest.mark.parametrize("came_back", [False, True])
    async def test_a_dormant_loop_recaps_only_once_the_user_came_back(
        self, world: World, monkeypatch: pytest.MonkeyPatch, came_back: bool
    ) -> None:
        _dormant(world)
        world.agent.return_value = _weekly_voiced()
        _seam(
            monkeypatch,
            world,
            dormancy,
            "latest_activity_since",
            AsyncMock(return_value=_NOW if came_back else None),
        )

        await weekly.run_weekly_digest(_USER)

        (user_id, since), _ = world.reads["latest_activity_since"].await_args
        assert (user_id, since) == (_USER, _DORMANT_SINCE)
        assert world.upsert.await_count == int(came_back)

    async def test_a_stalled_agent_fails_the_run_instead_of_hanging(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def stall(**_: object) -> None:
            await asyncio.Event().wait()

        world.agent.side_effect = stall
        monkeypatch.setattr(weekly, "WEEKLY_GENERATION_TIMEOUT_SECONDS", 0)

        run = asyncio.ensure_future(weekly.run_weekly_digest(_USER))
        try:
            done, _ = await asyncio.wait({run}, timeout=5)
            assert run in done
            assert isinstance(run.exception(), TimeoutError)
        finally:
            run.cancel()
        _assert_nothing_sent(world)


_LOGIN = Signal(
    integration_id="linear",
    app="Linear",
    external_id="ENG-12",
    kind="issue assigned to you",
    title="Fix the login redirect",
    importance=SignalImportance.HIGH,
    url="https://linear.app/acme/issue/ENG-12",
    state="In Progress",
)
_DOCS = Signal(
    integration_id="linear",
    app="Linear",
    external_id="ENG-40",
    kind="issue assigned to you",
    title="Refresh the onboarding docs",
    url="https://linear.app/acme/issue/ENG-40",
    state="Todo",
)


def _scouted(*signals: Signal) -> list[ScoutResult]:
    return [
        ScoutResult(
            integration_id="linear", app="Linear", outcome=ScoutOutcome.REPLAYED, signals=[*signals]
        )
    ]


def _saying(text: str) -> SimpleNamespace:
    return SimpleNamespace(message=_fenced({**_VOICE, "message": f"{_FACTS_SHOWN} {text}"}))


class TestSignalsInTheBrief:
    """What the scouts found reaches the writer with its memory, and is remembered as shown."""

    async def test_signals_reach_the_writer_grouped_per_app_with_their_memory(
        self, world: World
    ) -> None:
        world.scouts = _scouted(_LOGIN, _DOCS)
        world.memory = [
            SignalMemoryDocument(
                user_id=_USER,
                integration_id="linear",
                external_id="ENG-12",
                first_seen=_NOW - timedelta(days=3),
                times_shown=1,
                last_shown=_NOW - timedelta(days=2),
                last_state="Todo",
            )
        ]
        world.judge.side_effect = _judged(needs_you=[_LOGIN.title], updates=[_DOCS.title])
        world.agent.return_value = _saying("[the login redirect](fact:1) still needs you.")

        await daily.run_daily_briefing(_USER)

        prompt = _prompt(world)
        assert "[ACROSS THEIR APPS] 2 item(s) in 1 app(s)\n[Linear] 2 item(s)\n" in prompt
        assert (
            "- fact 1 | important | issue assigned to you: Fix the login redirect"
            " | state: In Progress | linkable | first seen 3 days ago, mentioned"
            " 1 time(s), last 2 days ago, moved from Todo to In Progress"
        ) in prompt
        assert "- fact 2 | other | issue assigned to you: Refresh the onboarding docs" in prompt
        assert "new today" in prompt
        assert (_stored_payload(world).message or "").endswith(
            f"[the login redirect]({_LOGIN.url}) still needs you."
        )

    async def test_a_day_with_only_signals_is_pushed_and_counted(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(context, "gather_calendar", AsyncMock(return_value=[]))
        world.scouts = _scouted(_DOCS)
        world.agent.return_value = _saying(
            "[Refresh the docs](fact:<fact of Refresh>) when you can."
        )

        await daily.run_daily_briefing(_USER)

        world.post.assert_awaited_once()
        assert world.capture.call_args.args[1].signal_count == 1

    async def test_only_the_signals_the_message_spoke_of_are_marked_shown(
        self, world: World
    ) -> None:
        world.scouts = _scouted(_LOGIN, _DOCS)
        world.judge.side_effect = _judged(needs_you=[_LOGIN.title], updates=[_DOCS.title])
        world.agent.return_value = _saying("[[fact:<fact of Fix the login>]] is yours today.")

        await daily.run_daily_briefing(_USER)

        world.shown.assert_awaited_once_with(_USER, [_LOGIN], _NOW)
        world.seen.assert_awaited_once_with(_USER, [_LOGIN, _DOCS], _NOW)
        needs_you, updates = _stored_payload(world).sections
        assert [(i.text, i.kind) for i in updates.items] == [(_DOCS.title, "note")]


class TestEverySourceReachesItsSection:
    """The brief is built from every source, not from tracked todos alone."""

    async def test_an_app_signal_a_desk_finding_an_approval_and_a_failed_run_each_land_in_place(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.scouts = [
            *_scouted(_LOGIN),
            ScoutResult(
                integration_id="notion",
                app="Notion",
                outcome=ScoutOutcome.SKIPPED,
                skip_reason=ScoutSkipReason.FAILED,
            ),
        ]
        desk = _todo("desk-1", "Inbox desk")
        world.reads["find_latest_by_external_ref"].return_value = desk
        world.held = [
            _held("h1", "Inbox desk", "Stripe payout of 2,400 dollars landed").model_copy(
                update={"source": BriefItemSource.TODO, "source_id": "desk-1"}
            )
        ]
        pending = [
            ApprovalLedgerDocument(
                approval_id="ap_1",
                conversation_id="conv-1",
                user_id=_USER,
                fingerprint="fp-1",
                tool_name="GMAIL_SEND_EMAIL",
                summary="Send the invoice to Acme",
            )
        ]
        monkeypatch.setattr(
            approval_ledger_repository, "list_pending_for_user", AsyncMock(return_value=pending)
        )
        world.reads["list_since"].return_value = [
            WorkflowExecutionDocument(
                execution_id="e1",
                workflow_id="wf-sync",
                user_id=_USER,
                status="failed",
                started_at=_NOW - timedelta(hours=2),
                error_message="HubSpot token expired",
            )
        ]
        monkeypatch.setattr(
            workflow_repository,
            "find_by_ids_for_user",
            AsyncMock(return_value=[SimpleNamespace(id="wf-sync", title="CRM sync")]),
        )
        world.agent.return_value = _saying("[Fix the login](fact:<fact of Fix the login>) today.")

        await daily.run_daily_briefing(_USER)

        payload = _stored_payload(world)
        assert [
            (s.key, [(i.text, i.app, i.kind, i.action or i.outcome) for i in s.items])
            for s in payload.sections
        ] == [
            (
                SectionKey.NEEDS_YOU,
                [
                    ("Send the invoice to Acme", "Gmail", "you", BriefAction.APPROVE),
                    ("CRM sync failed", "GAIA", "failed", BriefAction.RETRY),
                    ("Fix the login redirect", "Linear", "you", BriefAction.REPLY),
                ],
            ),
            (
                SectionKey.UPDATES,
                [("Stripe payout of 2,400 dollars landed", "Gmail", "note", BriefOutcome.CHANGED)],
            ),
        ]
        assert payload.sections[0].items[2].url == _LOGIN.url
        assert payload.sources_read == ["Linear", "Gmail", "Google Calendar"]
        assert [(u.app, u.reason) for u in payload.sources_unavailable] == [
            ("Notion", ScoutSkipReason.FAILED)
        ]
        event = world.capture.call_args.args[1]
        assert (event.needs_you_count, event.updates_count, event.source_count) == (3, 1, 3)
        world.consume.assert_awaited_once_with(_USER, ["h1"])
        world.shown.assert_awaited_once_with(_USER, [_LOGIN], _NOW)


class TestTheWeeklyRunHandsItsInputs:
    """Every producer, the judge and the prompt are given this user, their clock and the week."""

    async def test_the_producers_and_the_judge_are_asked_for_this_user_this_week(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.agent.return_value = _weekly_voiced()
        spy = AsyncMock(wraps=judge.select_candidates)
        monkeypatch.setattr(weekly, "select_candidates", spy)

        await weekly.run_weekly_digest(_USER)

        assert world.reads["list_since"].await_args.args == (_USER, _WEEK_START)
        assert spy.await_args.args[0] == _USER
        assert spy.await_args.args[3] == _NOW
        assert world.judge.await_args.kwargs["config"] == {"configurable": {"user_id": _USER}}
        assert f"Today is {_DATE} ({_TZ})." in world.judge.await_args.args[1]

    async def test_a_user_without_a_timezone_is_judged_on_utc(self, world: World) -> None:
        world.user.timezone = None
        world.agent.return_value = _weekly_voiced()

        await weekly.run_weekly_digest(_USER)

        assert "(UTC)." in world.judge.await_args.args[1]

    async def test_the_voice_is_given_the_reader_and_goal_and_no_lookback_replies_or_todos(
        self, world: World
    ) -> None:
        world.agent.return_value = _weekly_voiced()

        await weekly.run_weekly_digest(_USER)

        world.reads["format_goal_block"].assert_awaited_once_with(_USER, world.user)
        call = world.weekly_prompt.call_args.kwargs
        blocks = call["blocks"]
        assert call["date_local"] == _DATE
        assert "You're writing to Ada" in blocks.reader
        assert blocks.goal == "Ship v2"
        assert (blocks.lookback, blocks.replies) == ("", "")
        assert "open_todos" not in blocks.facts

    async def test_the_sources_read_and_the_links_are_the_users(self, world: World) -> None:
        deck = _todo("g0", "Deck")
        deck.canvas_content = "Ten slides"
        world.reads["gather_completed_since"].return_value = context.CompletedWork(gaia=[deck])
        world.reads["gather_week"].return_value = BriefingWeek(
            days=[BriefingWeekDay(you=1, gaia=2)] * 7, ahead=[_FRIDAY_PITCH]
        )
        world.mint.side_effect = lambda user_id, target_type, target_id: (
            _todo_link(target_id) if user_id == _USER else None
        )
        world.agent.return_value = _weekly_voiced(
            message="[the deck](fact:1) is done\n[[fact:2]] on Friday at [[fact:2.time]]."
        )

        await weekly.run_weekly_digest(_USER)

        payload = _stored_payload(world)
        assert payload.sources_read == ["Google Calendar"]
        assert f"[the deck]({_todo_link('g0')})" in (payload.message or "")
