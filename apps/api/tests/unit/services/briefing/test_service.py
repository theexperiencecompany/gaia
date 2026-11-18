"""The daily brief and weekly recap runs, end to end through the service.

Faked seams: user lookup, call_agent_silent, the briefing repository, pending brief
items, the notification orchestrator, the chat channel resolver, the edition image
host, the platform chat post and the context reads. Assertions are on what gets
stored and delivered, and on every failure path, that nothing is.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
import json
import re
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, call

from prometheus_client import REGISTRY
from pydantic import BaseModel, ValidationError
import pytest
from tests.helpers import captured_wide_event
import time_machine

from app.agents.core import agent as agent_module
from app.agents.llm.client import metered_config
from app.agents.llm.exceptions import MalformedStructuredOutputError
from app.agents.prompts.brief_fact_prompts import CALENDAR_UNAVAILABLE, NO_CALENDAR_CONNECTED
from app.agents.prompts.briefing_prompts import (
    VoiceSituation,
    build_briefing_voice_prompt,
    build_weekly_voice_prompt,
    voice_unreadable_note,
)
from app.config.settings import settings
from app.constants.briefing import (
    BRIEF_VOICE_LABEL,
    FIRST_WEEK_DAYS,
    IDLE_DORMANT_DAYS,
    LEAD_OFFERS,
    MAX_BRIEF_HEADLINE_CHARS,
    MAX_VOICE_ATTEMPTS,
    PLAIN_BRIEF_HEADLINE,
    WEEKLY_KICKER,
    WINBACK_THRESHOLD,
    ArtFamily,
    BriefAction,
    BriefForm,
    BriefingBag,
    BriefingFrequency,
    BriefingKind,
    BriefingRunOutcome,
    BriefItemSource,
    BriefOutcome,
    EditionChoice,
    EditionFamily,
    WindDown,
)
from app.constants.desk_buckets import DeskBucket
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_NOTE,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
    ProactiveMessageClass,
)
from app.constants.todos import GAIA_TRACKED_LABEL, NEEDS_REPLY_LABEL, TodoCompleter
from app.constants.user_activity import ActivityStatus
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.email_verdicts import email_verdict_repository
from app.db.repositories.hil import hil_approval_repository
from app.db.repositories.pending_brief_items import pending_brief_items_repository
from app.db.repositories.reminders import reminder_repository
from app.db.repositories.signal_memory import signal_memory_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_composition_models import BriefComposition, SectionBlock
from app.models.brief_document_models import BriefingModel, DeliveryStep, EditionRender
from app.models.brief_models import PendingBriefItemDocument
from app.models.brief_payload_models import (
    BriefingEvent,
    BriefingMood,
    BriefingPayload,
    BriefingTallies,
    BriefingWeek,
    BriefingWeekDay,
    BriefVoice,
    NewStamp,
)
from app.models.brief_pool_models import GoalOrigin
from app.models.brief_settings_models import BriefingSchedule
from app.models.calendar_models import GoogleCalendarEventDateTime, GoogleCalendarEventResource
from app.models.chat_models import ConversationSource
from app.models.email_verdict_models import EmailVerdictDocument
from app.models.hil_models import ApprovalLedgerDocument
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationStatus,
)
from app.models.scout_models import (
    ScoutOutcome,
    ScoutResult,
    ScoutSkipReason,
    Sighting,
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
from app.services.analytics_service import AIFeature
from app.services.briefing import (
    calendar_read,
    chat_sync,
    checked_call,
    daily,
    delivery,
    edition_draws,
    errors,
    pipeline,
    prose,
    publish,
    store,
    weekly,
    wind_down,
)
from app.services.briefing.calendar_read import CalendarGap
from app.services.briefing.candidates import pool as candidates_pool
from app.services.briefing.candidates.subjects import subject_key
from app.services.briefing.composition import headings as composition_headings
from app.services.briefing.composition.headings import HeadingVerdict, HeadingVerdicts
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.editions.artworks import artwork_weights, artworks_for
from app.services.briefing.goals import StatedGoal
from app.services.briefing.kinds import KIND_SPECS
from app.services.briefing.lookback import Lookback, WinbackState
from app.services.briefing.pipeline import run_brief
from app.services.briefing.prose import reader_block
from app.services.briefing.render import RenderedImage
from app.services.briefing.scouts import service as scout_service
from app.services.briefing.scouts.facts import SHOWN_NOT_TOTAL
from app.services.briefing.work import BriefReads, OpenSubjects, OwnTodos, TrackedWork
from app.services.cost_budget import DAILY_BUDGET_STOP_FREE
from app.services.delivery.chat_channel import ChatChannel, InApp
from app.services.notification_service import notification_service
from app.services.outbound_delivery import OutboundResult
from app.utils.general_utils import ELLIPSIS
from app.utils.markdown_utils import model_from_reply
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
_RENDERED = RenderedImage(image=b"edition-png", fold=0.3, paper=(0.1, 0.2, 0.9, 0.8))
_BRIEF_ID = "brief_abc123"
_EDITION_KEY = "edition0key0of0the0brief0abc0123"
_EDITION_URL = f"{settings.HOST}/api/v1/briefings/editions/{_EDITION_KEY}/png?t="
_CHAT_EDITION_URL = f"{settings.HOST}/api/v1/briefings/editions/{_EDITION_KEY}/jpg?t="
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
    """Return the prompt's facts block, inside its fence."""
    block = _FACTS_HEADER.split(prompt, maxsplit=1)[1].split("\n\n## ", 1)[0]
    return "\n".join(block.strip("\n").splitlines()[1:-1])


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


# One pool item line: "7. [GitHub] waiting on you, important: Title | detail | action review".
_POOL_ITEM = re.compile(
    r"^(\d+)\. \[([^\]]+)\] ([A-Za-z ,']+?)(?:, important)?: (.+?)(?: \| (.*))?$", re.M
)
_ASKING_STATES = {"waiting on you", "failed"}
_PRODUCER_SAYS = re.compile(r"\b(action|outcome) (\w+)\b")
# How the stand-in composer words what a line does not settle: asks reply, reports finished.
_UNSETTLED = {True: ("action", "reply"), False: ("outcome", "finished")}


@dataclass(frozen=True)
class _PoolItem:
    id: int
    app: str
    state: str
    title: str
    rest: str

    @property
    def asks(self) -> bool:
        return self.state in _ASKING_STATES

    def placed(self, *, asks: bool | None = None) -> dict[str, object]:
        """Word the item as a composer would: its own title, and its producer's action or outcome."""
        asking = self.asks if asks is None else asks
        side, value = _UNSETTLED[asking]
        for said_side, said in _PRODUCER_SAYS.findall(self.rest):
            if said_side == side:
                value = said
        placed: dict[str, object] = {
            "id": self.id,
            "title": self.title,
            "action": None,
            "outcome": None,
            "detail": None,
        }
        return {**placed, side: value}


def _pool_items(prompt: str) -> list[_PoolItem]:
    pool = prompt.split("## The pool", 1)[1].split("\nSERIES\n", 1)[0]
    return [
        _PoolItem(int(n), app, state, title, rest or "")
        for n, app, state, title, rest in _POOL_ITEM.findall(pool)
    ]


def _group_state(items: list[dict[str, object]]) -> str:
    """Name the state a group of placed items is in: its asks, its running work, else done."""
    if all(i["action"] is not None for i in items):
        return "needs_you"
    return "in_progress" if all(i["outcome"] == "started" for i in items) else "done"


def _composes_by_state(
    schema: type[BriefComposition], prompt: str, **_: object
) -> BriefComposition:
    """Stand in for the composer: what asks, then GAIA's work done, then running, then the apps'."""
    groups: dict[str, list[dict[str, object]]] = {
        "Needs you": [],
        "GAIA's work": [],
        "Still running": [],
        "From your apps": [],
    }
    for item in _pool_items(prompt):
        if item.state == "calendar event":
            continue
        placed = item.placed()
        if item.asks:
            heading = "Needs you"
        elif placed.get("outcome") == "started":
            heading = "Still running"
        else:
            heading = "GAIA's work" if item.app == "GAIA" else "From your apps"
        groups[heading].append(placed)
    return schema.model_validate(
        {
            "blocks": [
                {"kind": "items", "state": _group_state(items), "heading": heading, "items": items}
                for heading, items in groups.items()
                if items
            ]
        }
    )


_GROUP_LINE = re.compile(r"^block (\d+), heading ", re.M)


def _every_heading_fits(schema: type[HeadingVerdicts], prompt: str, **_: object) -> HeadingVerdicts:
    """Stand in for the heading check: every group the prompt lists fits its heading."""
    return schema(
        verdicts=[
            HeadingVerdict(block=int(n), fits=True, misfits=[], why="fits")
            for n in _GROUP_LINE.findall(prompt)
        ]
    )


def _composed(
    groups: dict[str, list[str]],
    *,
    lead: tuple[str, str] | None = None,
    reports: frozenset[str] = frozenset(),
) -> Callable[..., BriefComposition]:
    """Stand in for a composer that places items by title under each heading, the lead first.

    reports are titles placed as reports (with an outcome) whatever their state.
    """

    def placed(item: _PoolItem) -> dict[str, object]:
        return item.placed(asks=False) if item.title in reports else item.placed()

    def answer(schema: type[BriefComposition], prompt: str, **_: object) -> BriefComposition:
        by_title = {item.title: item for item in _pool_items(prompt)}
        blocks: list[dict[str, object]] = []
        if lead is not None:
            title, offer = lead
            blocks.append({"kind": "lead", "item": placed(by_title[title]), "offer": offer})
        for heading, titles in groups.items():
            items = [placed(by_title[t]) for t in titles]
            blocks.append(
                {"kind": "items", "state": _group_state(items), "heading": heading, "items": items}
            )
        return schema.model_validate({"blocks": blocks})

    return answer


def _from_google(event: BriefingEvent) -> GoogleCalendarEventResource:
    """Return the event as Google sends it: timed in Kolkata, or all-day."""
    if event.start is None:
        return GoogleCalendarEventResource(
            summary=event.title, start=GoogleCalendarEventDateTime(date=event.date)
        )
    start = f"{event.date}T{event.start}:00+05:30"
    return GoogleCalendarEventResource(
        summary=event.title,
        location=event.location,
        start=GoogleCalendarEventDateTime(dateTime=start),
        end=GoogleCalendarEventDateTime(dateTime=start),
    )


def _delivered(channel: str) -> ChannelDeliveryStatus:
    return ChannelDeliveryStatus(channel_type=channel, status=NotificationStatus.DELIVERED)


def _fenced(data: dict[str, Any]) -> str:
    return f"```json\n{json.dumps(data)}\n```"


def _todo(todo_id: str, title: str) -> TodoDocument:
    return TodoDocument(id=todo_id, user_id=_USER, title=title, labels=[GAIA_TRACKED_LABEL])


def _own_done(todo_id: str, title: str) -> TodoDocument:
    """Return a todo of the user's own that they finished."""
    return TodoDocument(
        id=todo_id, user_id=_USER, title=title, completed=True, completed_by=TodoCompleter.USER
    )


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
    notify: AsyncMock
    post: AsyncMock
    render: AsyncMock
    store_edition: AsyncMock
    consume: AsyncMock
    capture: MagicMock
    voice_prompt: MagicMock
    weekly_prompt: MagicMock
    recent: AsyncMock = field(default_factory=lambda: AsyncMock(return_value=[]))
    stamped: AsyncMock = field(default_factory=lambda: AsyncMock(return_value=[]))
    clear_bootstrap: AsyncMock = field(default_factory=AsyncMock)
    #: The briefings collection: each stored brief by id, as the run left it.
    briefs: dict[str, BriefingModel] = field(default_factory=dict)
    clear_dormancy: AsyncMock = field(default_factory=AsyncMock)
    enter_dormancy: AsyncMock = field(default_factory=AsyncMock)
    goal_asked: AsyncMock = field(default_factory=AsyncMock)
    activity: ActivityStatus = ActivityStatus.ACTIVE
    connected_apps: list[str] = field(default_factory=list)
    bags: dict[str, ShuffleBag] = field(default_factory=dict)
    work: TrackedWork = field(default_factory=TrackedWork)
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
    #: The composition model; by default it groups every item by whether it asks.
    composer: AsyncMock = field(default_factory=lambda: AsyncMock(side_effect=_composes_by_state))
    #: The voice's structured call; by default the agent's reply read as the voice.
    voice: Callable[..., Awaitable[BriefVoice]] | None = None
    #: The heading check's model; by default every heading fits its items.
    headings: AsyncMock = field(default_factory=lambda: AsyncMock(side_effect=_every_heading_fits))
    #: What the user's calendar holds, as Google sends it, or why it went unread.
    calendar: list[BriefingEvent] | CalendarGap = field(default_factory=lambda: [_EVENT])
    #: The weekly's per-day counts, as code counts them.
    week: MagicMock = field(
        default_factory=lambda: MagicMock(
            return_value=BriefingWeek(days=[BriefingWeekDay(you=1, gaia=2)] * 7)
        )
    )


def _seam(
    monkeypatch: pytest.MonkeyPatch, w: World, owner: object, name: str, mock: AsyncMock
) -> None:
    monkeypatch.setattr(owner, name, mock)
    w.reads[name] = mock


def _with_open_subjects(work: TrackedWork) -> TrackedWork:
    """Return the work as the full read returns it: open totals each subject once.

    What is done was finished by GAIA, unless a test says who.
    """

    def subjects(docs: list[TodoDocument]) -> int:
        return len({subject_key(d) for d in docs})

    return replace(
        work,
        completed=[
            d.model_copy(
                update={"completed": True, "completed_by": d.completed_by or TodoCompleter.GAIA}
            )
            for d in work.completed
        ],
        open_subjects=OpenSubjects(
            subjects(work.running), subjects(work.blocked), subjects(work.failed)
        ),
    )


def _own_todos(open_count: int, overdue: int = 0) -> MagicMock:
    """Stand in for the counts of the user's own todos: open, and of those past due."""
    return MagicMock(return_value=OwnTodos(open=open_count, overdue=overdue))


def _briefs_read(world: World, briefs: list[BriefingModel]) -> None:
    """Have list_recent read these briefs, newest first: every kind, or the drawn ones alone."""
    world.recent.side_effect = lambda user_id, *, limit, editions_only=False, **_k: [
        b
        for b in briefs
        if user_id == _USER and (not editions_only or b.payload.form is BriefForm.EDITION)
    ][:limit]


def _patch_context_reads(monkeypatch: pytest.MonkeyPatch, w: World) -> None:
    """Patch what the run gathers its context from (work, goals, wind_down, apps) and the scouts."""
    _seam(monkeypatch, w, chat_sync, "format_replies_block", AsyncMock(return_value="No replies."))
    _goals_seam(
        monkeypatch,
        w,
        AsyncMock(return_value=[StatedGoal("Ship v2", GoalOrigin.ONBOARDING)]),
    )
    _seam(monkeypatch, w, briefing_repository, "get_before_date", AsyncMock(return_value=None))
    _seam(monkeypatch, w, daily, "format_lookback_block", AsyncMock(return_value="-"))
    _seam(
        monkeypatch,
        w,
        daily,
        "compute_winback_state",
        AsyncMock(return_value=WinbackState(unacknowledged=0, last_was_winback=False)),
    )
    _seam(
        monkeypatch,
        w,
        BriefReads,
        "tracked_work",
        MagicMock(side_effect=lambda *_: _with_open_subjects(w.work)),
    )
    _seam(monkeypatch, w, BriefReads, "own_todos", _own_todos(0))
    _seam(monkeypatch, w, wind_down, "record_idle_day", AsyncMock(return_value=0))
    _seam(monkeypatch, w, wind_down, "latest_activity_since", AsyncMock(return_value=None))
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


def _voice_call(agent: AsyncMock) -> Callable[..., Awaitable[BriefVoice]]:
    """Stand in for the voice's structured call: agent's reply, its fact tokens filled, read as the voice."""

    async def voice_call(schema: type[BriefVoice], prompt: str, **kwargs: Any) -> BriefVoice:
        reply = await agent(schema=schema, prompt=prompt, **kwargs)
        text = _message_written(prompt, reply.message)
        parsed = model_from_reply(text, schema)
        if isinstance(parsed, list):
            raise MalformedStructuredOutputError("; ".join(parsed), llm_output=text)
        return parsed

    return voice_call


def _structured(w: World) -> Callable[..., Awaitable[BaseModel]]:
    """Stand in for every checked structured call: the voice answers its schema, the composer the rest."""

    async def call(schema: type[BaseModel], prompt: str, **kwargs: Any) -> BaseModel:
        if schema is BriefVoice:
            assert w.voice is not None
            return await w.voice(schema, prompt, **kwargs)
        return await w.composer(schema, prompt, **kwargs)

    return call


def _goals_seam(monkeypatch: pytest.MonkeyPatch, w: World, read: AsyncMock) -> None:
    """Have both kinds read the user's goals from read."""
    _seam(monkeypatch, w, daily, "stated_goals", read)
    monkeypatch.setattr(weekly, "stated_goals", read)


#: When the default world's completions were finished: inside every window a run reads.
_JUST_NOW = _NOW - timedelta(hours=1)


def _completions(
    gaia: Sequence[TodoDocument] = (), user: Sequence[TodoDocument] = ()
) -> list[TodoDocument]:
    """Return what list_completed_since reads: each todo completed, by whom, and when."""
    return [
        d.model_copy(
            update={
                "completed": True,
                "completed_by": by,
                "completed_at": d.completed_at or _JUST_NOW,
            }
        )
        for docs, by in ((gaia, TodoCompleter.GAIA), (user, TodoCompleter.USER))
        for d in docs
    ]


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    w = World(
        agent=AsyncMock(return_value=SimpleNamespace(message=_fenced(_VOICE))),
        upsert=AsyncMock(),
        mint=AsyncMock(return_value=_BRIEF_LINK),
        notify=AsyncMock(
            return_value=SimpleNamespace(channels=[_delivered(c) for c in _ORCHESTRATED])
        ),
        post=AsyncMock(return_value=OutboundResult.PUBLISHED),
        render=AsyncMock(return_value=_RENDERED),
        store_edition=AsyncMock(return_value=_EDITION_KEY),
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
    _store_briefs(monkeypatch, w)
    monkeypatch.setattr(user_repository, "clear_briefing_bootstrap", w.clear_bootstrap)
    monkeypatch.setattr(user_repository, "clear_briefing_dormancy", w.clear_dormancy)
    monkeypatch.setattr(user_repository, "enter_briefing_dormancy", w.enter_dormancy)
    monkeypatch.setattr(user_repository, "record_goal_question", w.goal_asked)
    monkeypatch.setattr(daily, "build_briefing_voice_prompt", w.voice_prompt)
    monkeypatch.setattr(weekly, "build_weekly_voice_prompt", w.weekly_prompt)

    w.voice = _voice_call(w.agent)
    monkeypatch.setattr(checked_call, "ainvoke_structured", _structured(w))
    monkeypatch.setattr(briefing_repository, "list_recent", w.recent)
    monkeypatch.setattr(briefing_repository, "list_stamped", w.stamped)
    monkeypatch.setattr(briefing_repository, "briefing_id_for", AsyncMock(return_value=_BRIEF_ID))
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
    monkeypatch.setattr(store, "render_edition_png", w.render)
    monkeypatch.setattr(store, "store_edition", w.store_edition)
    monkeypatch.setattr(settings, "INSTANCE_SECRET", "s" * 48)
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
    monkeypatch.setattr(composition_headings, "ainvoke_structured", w.headings)
    _seam(
        monkeypatch,
        w,
        calendar_read,
        "fetch_calendar",
        AsyncMock(
            side_effect=lambda user_id, start, end: (
                w.calendar
                if isinstance(w.calendar, CalendarGap)
                else [_from_google(e) for e in w.calendar]
            )
        ),
    )
    for repository, read in (
        (todo_repository, "list_completed_since"),
        (todo_repository, "list_external_ref_activity_since"),
        (todo_repository, "list_open_user_todos"),
        (todo_repository, "list_active_tracked"),
        (workflow_executions_repository, "list_run_moments_since"),
    ):
        _seam(monkeypatch, w, repository, read, AsyncMock(return_value=[]))
    # The user finished one todo of their own since the last brief.
    w.reads["list_completed_since"].return_value = _completions(
        user=[TodoDocument(id="u1", user_id=_USER, title="Gym")]
    )
    # Keyed apart: the executions repository's own list_since is a read of its own.
    w.reads["verdicts_since"] = AsyncMock(return_value=[])
    monkeypatch.setattr(email_verdict_repository, "list_since", w.reads["verdicts_since"])
    for owner, name in (
        (approval_ledger_repository, "list_pending_for_user"),
        (hil_approval_repository, "list_pending_for_user"),
        (reminder_repository, "find_scheduled_between"),
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
        candidates_pool,
        "get_connected_integration_ids",
        AsyncMock(side_effect=lambda user_id: [GMAIL_INTEGRATION_ID] if user_id == _USER else []),
    )
    monkeypatch.setattr(pipeline, "count_week", w.week)
    with time_machine.travel(_NOW, tick=False):
        yield w


def _store_briefs(monkeypatch: pytest.MonkeyPatch, w: World) -> None:
    """Keep the briefings collection in memory, written and read the way the repository does."""

    async def upsert(brief: BriefingModel) -> BriefingModel:
        before = w.briefs.get(brief.id)
        w.briefs[brief.id] = brief.model_copy(
            update={
                "payload": brief.payload.model_copy(deep=True),
                "delivery": brief.delivery.model_copy(deep=True) if brief.delivery else None,
                "delivered_channels": before.delivered_channels if before else [],
            }
        )
        return w.briefs[brief.id]

    async def record_step(
        user_id: str, briefing_id: str, step: DeliveryStep, reached: list[str]
    ) -> None:
        brief = w.briefs[briefing_id]
        assert brief.user_id == user_id and brief.delivery is not None
        brief.delivery.done.append(step)
        brief.delivered_channels.extend(c for c in reached if c not in brief.delivered_channels)

    async def complete_delivery(user_id: str, briefing_id: str) -> None:
        delivery = w.briefs[briefing_id].delivery
        assert delivery is not None
        delivery.completed_at = _NOW

    def find_for_date(user_id: str, date: str, kind: BriefingKind) -> BriefingModel | None:
        return next(
            (b for b in w.briefs.values() if (b.user_id, b.date, b.kind) == (user_id, date, kind)),
            None,
        )

    async def was_delivered(user_id: str, date: str, kind: BriefingKind) -> bool:
        brief = find_for_date(user_id, date, kind)
        return (
            brief is not None
            and brief.delivery is not None
            and brief.delivery.completed_at is not None
        )

    async def find(user_id: str, date: str, kind: BriefingKind) -> BriefingModel | None:
        return find_for_date(user_id, date, kind)

    w.upsert.side_effect = upsert
    monkeypatch.setattr(briefing_repository, "upsert_briefing", w.upsert)
    monkeypatch.setattr(briefing_repository, "record_step", record_step)
    monkeypatch.setattr(briefing_repository, "complete_delivery", complete_delivery)
    monkeypatch.setattr(briefing_repository, "find_for_date", find)
    monkeypatch.setattr(briefing_repository, "was_delivered", AsyncMock(side_effect=was_delivered))


def _delivered_to(w: World, kind: BriefingKind = BriefingKind.DAILY) -> list[str]:
    """Return the channels the stored brief of kind reached, once its delivery completed."""
    [brief] = [b for b in w.briefs.values() if b.kind == kind]
    assert brief.delivery is not None and brief.delivery.completed_at is not None
    return brief.delivered_channels


def _stored_payload(w: World) -> BriefingPayload:
    w.upsert.assert_awaited()
    return w.upsert.await_args.args[0].payload


def _prompt(w: World) -> str:
    return w.agent.await_args.kwargs["prompt"]


def _family_first(w: World, family: str) -> None:
    """Pin today's edition family: the default draw is random, and Air Mail adds a stamp line."""
    pool = [f for f, n in DAILY_FAMILY_WEIGHTS.items() for _ in range(n)]
    pool.remove(family)
    w.bags["edition_family"] = ShuffleBag(order=[family, *pool], index=0)


def _assert_sent_plainly(w: World) -> BriefingPayload:
    """Assert the brief still went out, voiced plainly from its facts: never nothing."""
    payload = _stored_payload(w)
    assert payload.headline == PLAIN_BRIEF_HEADLINE
    w.notify.assert_awaited()
    return payload


def _salvaged(event: dict[str, Any], call: str) -> list[dict[str, Any]]:
    """Return the run's salvages of one checked call: voice or composition."""
    return [
        e
        for e in event["errors"]
        if e["msg"] == "briefing.checked_call_salvaged" and e["call"] == call
    ]


def _assert_nothing_sent(w: World) -> None:
    w.upsert.assert_not_awaited()
    w.notify.assert_not_awaited()
    w.post.assert_not_awaited()
    w.consume.assert_not_awaited()


class TestDailyBrief:
    async def test_brief_is_stored_then_delivered_in_app_by_email_and_as_a_chat_image(
        self, world: World
    ) -> None:
        world.work = TrackedWork(
            blocked=[_todo("b1", "Approve the Priya reply")],
            completed=[_todo("c1", "Investor update")],
        )
        _family_first(world, "memo")

        await run_brief(_USER, BriefingKind.DAILY)

        payload = _stored_payload(world)
        assert payload.headline == "Your morning, sorted"
        assert payload.template_family == "memo"
        assert payload.calendar == [_EVENT]
        assert payload.tallies == BriefingTallies(done_by_you=1, done_by_gaia=0)
        assert "(11:00 AM): Sequoia" in _prompt(world)
        assert [(s.title, [i.text for i in s.items]) for s in payload.sections] == [
            ("Needs you", ["Approve the Priya reply"]),
            ("GAIA's work", ["Investor update"]),
        ]
        assert [i.todo_id for s in payload.sections for i in s.items] == ["b1", "c1"]
        message = "Approve the Priya reply\nInvestor update\nSequoia"
        assert payload.message == message
        assert world.upsert.await_args.args[0].edition == EditionRender(
            key=_EDITION_KEY, fold=0.3, paper=[0.1, 0.2, 0.9, 0.8]
        )
        world.store_edition.assert_awaited_once_with(_USER, _BRIEF_ID, _RENDERED.image)
        request = world.notify.await_args.args[0]
        assert request.metadata["edition"]["image_url"].startswith(_EDITION_URL)
        # One URL, minted before the render: the edition's codes, the email image and the chat post.
        world.mint.assert_awaited_with(_USER, ShortLinkTargetType.BRIEFING, _BRIEF_ID)
        assert world.render.await_args.args[0].link == _BRIEF_LINK
        assert request.metadata["brief_url"] == _BRIEF_LINK
        assert request.content.actions[0].config.redirect.url == f"/brief/{_BRIEF_ID}"
        assert [c.channel_type for c in request.channels] == _ORCHESTRATED
        assert request.metadata["kind"] == NOTIFICATION_KIND_BRIEFING_DAILY
        # GAIA's Briefings-conversation message carries the same folded card the notification does.
        user_id, text, card = world.brief_message.await_args.args
        assert (user_id, text, card.briefing_id, card.kind) == (_USER, message, _BRIEF_ID, "daily")
        assert card.needs_you_count == 1
        assert card.edition is not None and card.edition.image_url.startswith(_EDITION_URL)
        assert request.metadata["needs_you_count"] == card.needs_you_count
        assert request.content.body == message
        assert request.content.rich_content == payload.model_dump()
        world.render.assert_awaited_once()
        post = world.post.await_args.kwargs
        assert post["channel"] == _CHAT
        assert post["image"].url.startswith(_CHAT_EDITION_URL)
        assert split_message_bubbles(post["text"]) == [
            "Your morning, sorted",
            f"{message}\n\nFull brief: {_BRIEF_LINK}",
        ]
        assert _delivered_to(world) == [*_ORCHESTRATED, "telegram"]

    async def test_without_a_chat_platform_nothing_is_posted(self, world: World) -> None:
        world.chat = None

        await run_brief(_USER, BriefingKind.DAILY)

        world.render.assert_awaited_once()
        world.post.assert_not_awaited()
        assert _delivered_to(world) == _ORCHESTRATED

    async def test_a_rerun_stores_its_edition_over_the_one_its_brief_had(
        self, world: World
    ) -> None:
        world.notify.side_effect = RuntimeError("orchestrator down")
        with pytest.raises(RuntimeError, match="orchestrator down"):
            await run_brief(_USER, BriefingKind.DAILY)
        world.notify.side_effect = None
        await run_brief(_USER, BriefingKind.DAILY)

        stored = [c.args[:2] for c in world.store_edition.await_args_list]
        assert stored == [(_USER, _BRIEF_ID), (_USER, _BRIEF_ID)]

    async def test_the_edition_is_addressed_to_the_user_by_name(self, world: World) -> None:
        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).recipient_name == "Ada"
        assert "You're writing to Ada" in world.voice_prompt.call_args.kwargs["blocks"].reader

    async def test_a_user_who_gave_no_name_is_addressed_by_none(self, world: World) -> None:
        """Regression: the brief greeted "Dear Delivered", a name guessed from delivered+dev@resend.dev."""
        world.user = UserDocument(id=_USER, timezone=_TZ, email="delivered+dev@resend.dev")

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).recipient_name is None
        assert "writing to" not in world.voice_prompt.call_args.kwargs["blocks"].reader
        assert "Delivered" not in _prompt(world)

    async def test_the_composer_is_told_who_the_day_is_for_and_when(self, world: World) -> None:
        world.recent.return_value = [
            BriefingModel(
                id="b",
                user_id=_USER,
                date="2026-10-13",
                payload=BriefingPayload(
                    kicker="K",
                    date="2026-10-13",
                    headline="h",
                    lede="l",
                    mood=BriefingMood.PACKED,
                    caption="c",
                    message="Priya replied overnight.",
                    template_family=EditionFamily.SWISS,
                ),
            )
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        composed = world.composer.await_args.args[1]
        assert "You're writing to Ada" not in composed
        assert "Wed Oct 14, 2026, Asia/Kolkata." in composed
        assert "Calendar today: 1 event(s), every one listed below." in composed
        assert 'Recent briefs opened on: "Priya replied overnight."' in composed

    async def test_a_user_with_no_name_or_timezone_is_composed_for_as_the_user_in_utc(
        self, world: World
    ) -> None:
        world.user = UserDocument(id=_USER, email="delivered+dev@resend.dev")

        await run_brief(_USER, BriefingKind.DAILY)

        composed = world.composer.await_args.args[1]
        assert "composing the user's morning brief for 2026-10-14" in composed
        assert "Wed Oct 14, 2026, UTC." in composed

    async def test_a_winback_message_need_not_refer_to_the_lead(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seam(
            monkeypatch,
            world,
            daily,
            "compute_winback_state",
            AsyncMock(
                return_value=WinbackState(unacknowledged=WINBACK_THRESHOLD, last_was_winback=False)
            ),
        )
        world.work = _brief_work()
        world.composer.side_effect = _composed(
            {"Done overnight": ["Investor update"]},
            lead=("Approve the Priya reply", "Send the reply once you approve"),
        )

        world.agent.return_value = _wrote("The investor update went out.")

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.agent.await_count == 1
        assert _stored_payload(world).message == "The investor update went out."

    async def test_an_empty_day_stays_in_app_and_spends_no_draw(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing needs the user, nothing is on the calendar, nothing ran overnight."""
        world.work = TrackedWork()
        bags_before = dict(world.bags)
        world.calendar = []

        await run_brief(_USER, BriefingKind.DAILY)

        payload = _stored_payload(world)
        assert payload.sections == [] and payload.calendar == []
        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == ["inapp"]
        world.post.assert_not_awaited()
        assert world.bags == bags_before

    def _quiet(self, world: World) -> None:
        """Nothing to place and the goal asked yesterday, so the ladder says nothing today."""
        world.work = TrackedWork()
        world.user.briefing_dormancy = BriefingDormancy(goal_asked_at=_NOW - timedelta(days=1))

    async def test_a_quiet_note_accounts_for_the_held_results_it_carries(
        self, world: World
    ) -> None:
        self._quiet(world)
        world.calendar = []
        world.held = [_held("h1", "Paper digest", _DIGEST_REPORT)]
        world.composer.side_effect = None
        world.composer.return_value = BriefComposition(blocks=[])

        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        assert _stored_payload(world).form is BriefForm.QUIET_NOTE
        world.consume.assert_awaited_once_with(_USER, ["h1"])

    async def test_a_quiet_day_sends_a_two_line_note_and_no_edition(self, world: World) -> None:
        """Founder decision: a day with nothing placed and nothing on the calendar sends a plain note."""
        self._quiet(world)
        world.calendar = []
        bags_before = dict(world.bags)

        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        world.render.assert_not_awaited()
        world.agent.assert_not_awaited()
        payload = _stored_payload(world)
        assert payload.form is BriefForm.QUIET_NOTE
        assert payload.message == (
            "Nothing new needs you today, and your calendar is clear.\n"
            "I'll flag anything that comes in."
        )
        assert world.upsert.await_args.args[0].edition is None
        request = world.notify.await_args.args[0]
        assert request.metadata["kind"] == NOTIFICATION_KIND_BRIEFING_NOTE
        assert request.content.rich_content is None
        assert [c.channel_type for c in request.channels] == ["inapp", "email"]
        posted = world.post.await_args.kwargs
        assert (posted["text"], posted["image"]) == (payload.message, None)
        world.brief_message.assert_awaited_once_with(_USER, payload.message, None)
        assert world.capture.call_args.args[1].form == "quiet_note"
        assert world.bags == bags_before

    def _shown_before(self, world: World, todo_id: str, times: int) -> None:
        world.memory = [
            SignalMemoryDocument(
                user_id=_USER,
                integration_id="gaia",
                external_id=f"todo:{todo_id}",
                first_seen=_NOW - timedelta(days=3),
                times_shown=times,
                last_shown=_NOW - timedelta(days=1),
                last_state="you",
            )
        ]

    async def test_a_day_holding_only_what_earlier_briefs_showed_is_quiet(
        self, world: World
    ) -> None:
        """Replay: the same three undated todos were drawn as a fresh edition day after day."""
        self._quiet(world)
        world.calendar = []
        world.work = TrackedWork(blocked=[_todo("b1", "Approve the Acme MSA")])
        self._shown_before(world, "b1", times=2)

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).form is BriefForm.QUIET_NOTE
        world.render.assert_not_awaited()

    async def test_a_day_with_something_new_is_an_edition_even_beside_repeats(
        self, world: World
    ) -> None:
        self._quiet(world)
        world.calendar = []
        world.work = TrackedWork(
            blocked=[_todo("b1", "Approve the Acme MSA"), _todo("b2", "Reply to Daniel")]
        )
        self._shown_before(world, "b1", times=2)

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).form is BriefForm.EDITION

    async def test_a_quiet_day_whose_calendar_did_not_answer_says_so(self, world: World) -> None:
        self._quiet(world)
        world.calendar = CalendarGap.UNAVAILABLE

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).message == (
            "Nothing new needs you today. I couldn't read your calendar, so check it before you "
            "plan.\nI'll flag anything that comes in."
        )

    @staticmethod
    def _brief(day: str, form: BriefForm, kind: BriefingKind = BriefingKind.DAILY) -> BriefingModel:
        payload = BriefingPayload(
            form=form,
            kicker="K",
            date=day,
            headline="h",
            lede="",
            mood=BriefingMood.IDLE,
            caption="",
            template_family=None,
        )
        return BriefingModel(
            id=f"b-{day}-{kind}", user_id=_USER, date=day, kind=kind, payload=payload
        )

    @pytest.mark.parametrize(
        "before",
        [
            [BriefForm.QUIET_NOTE],
            [BriefForm.QUIET_NOTE, BriefForm.QUIET_NOTE, BriefForm.EDITION],
        ],
        ids=["the day after a quiet note", "a quiet streak"],
    )
    async def test_a_quiet_day_after_a_quiet_note_sends_nothing(
        self, world: World, before: list[BriefForm]
    ) -> None:
        """Founder: one quiet note says it is quiet; the days after it stay silent until something real."""
        self._quiet(world)
        world.calendar = []
        days = ["2026-10-13", "2026-10-12", "2026-10-11"]
        _briefs_read(world, [self._brief(day, form) for day, form in zip(days, before)])

        outcome = await run_brief(_USER, BriefingKind.DAILY)

        assert outcome is BriefingRunOutcome.SILENT
        # Nothing is stored, so a silent day can never count toward the winback streak.
        _assert_nothing_sent(world)
        world.goal_asked.assert_not_awaited()

    async def test_a_quiet_weekly_before_it_does_not_silence_the_daily(self, world: World) -> None:
        self._quiet(world)
        world.calendar = []
        _briefs_read(
            world,
            [
                self._brief("2026-10-13", BriefForm.QUIET_NOTE, kind=BriefingKind.WEEKLY),
                self._brief("2026-10-13", BriefForm.EDITION),
            ],
        )

        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT
        assert _stored_payload(world).form is BriefForm.QUIET_NOTE

    async def test_a_quiet_week_note_never_makes_a_daily_quiet_streak(self, world: World) -> None:
        """Replay: the day after a drawn daily, a quiet weekly made it "2 quiet days"."""
        self._quiet(world)
        world.calendar = []
        _briefs_read(
            world,
            [
                self._brief("2026-10-13", BriefForm.QUIET_NOTE, kind=BriefingKind.WEEKLY),
                self._brief("2026-10-13", BriefForm.EDITION),
            ],
        )

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).message.splitlines()[0] == (
            "Nothing new needs you today, and your calendar is clear."
        )

    async def test_a_quiet_day_with_an_app_unread_never_says_nothing_needs_them(
        self, world: World
    ) -> None:
        """Audit: an app that could not be read looked empty, and the note said nothing needs you."""
        self._quiet(world)
        world.calendar = []
        world.scouts = [
            ScoutResult(
                integration_id="notion",
                app="Notion",
                outcome=ScoutOutcome.SKIPPED,
                skip_reason=ScoutSkipReason.FAILED,
            )
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        note = _stored_payload(world)
        assert note.headline == "Nothing new in what I could read"
        assert note.message.splitlines()[:2] == [
            "Nothing new in what I could read, and your calendar is clear.",
            "I couldn't read Notion this time, so I can't say what they hold.",
        ]

    async def test_a_day_of_repeats_whose_chart_shows_what_moved_is_an_edition(
        self, world: World
    ) -> None:
        self._quiet(world)
        world.calendar = []
        world.work = TrackedWork(blocked=[_todo("b1", "Approve the Acme MSA")])
        self._shown_before(world, "b1", times=2)
        world.reads["list_completed_since"].return_value = [
            _todo("c1", "Investor update").model_copy(
                update={
                    "completed": True,
                    "completed_at": _NOW - timedelta(hours=1),
                    "completed_by": TodoCompleter.GAIA,
                }
            )
        ]
        placed = _composed({"Waiting": ["Approve the Acme MSA"]})

        def with_a_chart(
            schema: type[BriefComposition], prompt: str, **kw: object
        ) -> BriefComposition:
            chart = {
                "kind": "chart",
                "chart": "bar",
                "series_ids": ["gaia_finished"],
                "title": "Finished",
                "takeaway": "One thing done.",
            }
            blocks = [b.model_dump() for b in placed(schema, prompt, **kw).blocks]
            return schema.model_validate({"blocks": [*blocks, chart]})

        world.composer.side_effect = with_a_chart

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).form is BriefForm.EDITION

    async def test_a_quiet_day_names_every_app_it_could_not_read(self, world: World) -> None:
        self._quiet(world)
        world.calendar = []
        world.scouts = [
            ScoutResult(
                integration_id=integration,
                app=app,
                outcome=ScoutOutcome.SKIPPED,
                skip_reason=ScoutSkipReason.FAILED,
            )
            for integration, app in (("notion", "Notion"), ("linear", "Linear"))
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).message.splitlines()[1] == (
            "I couldn't read Notion or Linear this time, so I can't say what they hold."
        )

    async def test_a_quiet_day_asks_for_the_reconnect_a_signed_out_app_needs(
        self, world: World
    ) -> None:
        self._quiet(world)
        world.calendar = []
        world.scouts = [
            ScoutResult(
                integration_id=integration,
                app=app,
                outcome=ScoutOutcome.SKIPPED,
                skip_reason=reason,
            )
            for integration, app, reason in (
                ("github", "GitHub", ScoutSkipReason.SIGNED_OUT),
                ("notion", "Notion", ScoutSkipReason.FAILED),
            )
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        payload = _stored_payload(world)
        assert payload.message.splitlines()[1:3] == [
            "I couldn't read GitHub or Notion this time, so I can't say what they hold.",
            "Your GitHub sign-in expired: reconnect it in Settings, Integrations and I'll read "
            "it again.",
        ]
        assert [(u.app, u.reason) for u in payload.sources_unavailable] == [
            ("GitHub", ScoutSkipReason.SIGNED_OUT),
            ("Notion", ScoutSkipReason.FAILED),
        ]

    async def test_a_quiet_day_asks_for_every_reconnect_in_one_line(self, world: World) -> None:
        self._quiet(world)
        world.calendar = []
        world.scouts = [
            ScoutResult(
                integration_id=integration,
                app=app,
                outcome=ScoutOutcome.SKIPPED,
                skip_reason=ScoutSkipReason.SIGNED_OUT,
            )
            for integration, app in (("github", "GitHub"), ("linear", "Linear"))
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).message.splitlines()[2] == (
            "Your GitHub and Linear sign-ins expired: reconnect them in Settings, Integrations "
            "and I'll read them again."
        )

    async def test_a_quiet_day_counts_the_users_overdue_todos(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Replay: a user with 70 overdue todos of their own was never told of one."""
        self._quiet(world)
        world.calendar = []
        _seam(
            monkeypatch,
            world,
            BriefReads,
            "own_todos",
            _own_todos(200, overdue=70),
        )

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).message.splitlines()[1:] == [
            "70 of your own todos are past due.",
            "I'll flag anything that comes in.",
        ]

    async def test_a_day_with_an_event_is_an_edition_not_a_note(self, world: World) -> None:
        self._quiet(world)

        await run_brief(_USER, BriefingKind.DAILY)

        payload = _stored_payload(world)
        assert payload.form is BriefForm.EDITION
        assert [e.title for e in payload.calendar] == ["Sequoia"]
        world.render.assert_awaited_once()

    async def test_a_calendar_that_did_not_answer_is_named_unavailable_never_empty(
        self, world: World
    ) -> None:
        """Regression: a calendar read that failed reached the voice as a day with nothing on it."""
        world.work = _brief_work()
        world.calendar = CalendarGap.UNAVAILABLE

        await run_brief(_USER, BriefingKind.DAILY)

        assert CALENDAR_UNAVAILABLE in _facts_shown(_prompt(world))
        assert "The user's calendar has nothing today." not in _prompt(world)
        assert [(u.app, u.reason) for u in _stored_payload(world).sources_unavailable] == [
            ("Google Calendar", ScoutSkipReason.FAILED)
        ]

    async def test_email_is_left_out_when_the_user_turned_it_off(self, world: World) -> None:
        world.user = UserDocument(
            id=_USER, timezone="UTC", email="a@b.c", notification_channel_prefs={"email": False}
        )

        await run_brief(_USER, BriefingKind.DAILY)

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

        await run_brief(_USER, BriefingKind.DAILY)

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
            await run_brief(_USER, BriefingKind.DAILY)

        assert world.bags["edition_family"] == family_before
        assert "stamp_city" not in world.bags

    async def test_a_first_stamp_is_announced_on_every_channel(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(edition_draws, "hosted_stamp_weights", lambda: {"tokyo": 1})
        _family_first(world, "postal")

        await run_brief(_USER, BriefingKind.DAILY)

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
                mood=BriefingMood.CLEAR,
                caption="c",
                template_family=EditionFamily.POSTAL,
                stamp_city="tokyo",
            ),
        )
        world.stamped.return_value = [earlier]

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).stamp_city == "tokyo"
        assert _stored_payload(world).new_stamp is None
        assert "New stamp" not in world.post.await_args.kwargs["text"]

    async def test_a_family_with_no_stamp_or_frame_draws_neither(self, world: World) -> None:
        _family_first(world, "memo")

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).stamp_city is None
        assert _stored_payload(world).artwork_id is None
        assert "stamp_city" not in world.bags and "artwork" not in world.bags

    @pytest.mark.parametrize("family", ["exhibition", "broadsheet", "almanac"])
    async def test_a_framed_brief_hangs_a_fitting_painting_from_the_artwork_bag(
        self, world: World, family: str
    ) -> None:
        _family_first(world, family)

        await run_brief(_USER, BriefingKind.DAILY)

        artwork_id = _stored_payload(world).artwork_id
        assert artwork_id in artworks_for(ArtFamily(family))
        bag = world.bags["artwork"]
        assert bag.order[bag.index - 1] == artwork_id
        assert sorted(bag.order) == sorted(artwork_weights())

    async def test_the_next_framed_brief_hangs_the_next_painting_of_the_pass(
        self, world: World
    ) -> None:
        _family_first(world, "exhibition")
        order = sorted(artwork_weights())
        world.bags["artwork"] = ShuffleBag(order=order, index=3)

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).artwork_id == order[3]
        assert world.bags["artwork"] == ShuffleBag(order=order, index=4)

    async def test_a_framed_brief_that_fails_to_deliver_spends_no_painting(
        self, world: World
    ) -> None:
        _family_first(world, "almanac")
        world.notify.side_effect = RuntimeError("orchestrator down")

        with pytest.raises(RuntimeError, match="orchestrator down"):
            await run_brief(_USER, BriefingKind.DAILY)

        assert "artwork" not in world.bags

    async def test_the_brief_holds_the_composers_groups_under_its_headings_in_its_order(
        self, world: World
    ) -> None:
        """Regression: needs-you was truncated by a fixed order, never by what mattered."""
        world.work = TrackedWork(
            running=[_todo(f"r{i}", f"Running {i}") for i in range(3)],
            blocked=[_todo(f"b{i}", f"Blocked {i}") for i in range(3)],
            failed=[_todo("f1", "Failed one")],
        )
        world.composer.side_effect = _composed(
            {
                "Before the Sequoia call": ["Blocked 2", "Failed one"],
                "Still running": ["Running 1"],
            }
        )

        await run_brief(_USER, BriefingKind.DAILY)

        payload = _stored_payload(world)
        assert [(s.numeral, s.title, [i.text for i in s.items]) for s in payload.sections] == [
            ("I", "Before the Sequoia call", ["Blocked 2", "Failed one"]),
            ("II", "Still running", ["Running 1"]),
        ]
        assert payload.blocks == [
            SectionBlock(kind="items", section=0),
            SectionBlock(kind="items", section=1),
        ]
        assert sorted(i.title for i in payload.uncomposed) == [
            "Blocked 0",
            "Blocked 1",
            "Running 0",
            "Running 2",
        ]

    async def test_the_composers_lead_opens_the_brief_with_gaias_offer(self, world: World) -> None:
        world.work = _brief_work()
        world.composer.side_effect = _composed(
            {"Done overnight": ["Investor update"]},
            lead=("Approve the Priya reply", "Send the reply once you approve"),
        )

        await run_brief(_USER, BriefingKind.DAILY)

        lead, work = _stored_payload(world).sections
        assert (lead.title, lead.numeral) == ("First up", "I")
        [item] = lead.items
        assert (item.text, item.kind) == ("Approve the Priya reply", "you")
        assert item.action is not None and item.offer == LEAD_OFFERS[item.action]
        assert [(i.text, i.offer) for i in work.items] == [("Investor update", None)]
        assert _stored_payload(world).blocks[0] == SectionBlock(kind="lead", section=0)

    async def test_a_composition_broken_twice_still_sends_what_holds_of_it(
        self, world: World
    ) -> None:
        """Dhruv's Nov 11: a heading typing a stray "9" failed the brief and he got nothing."""
        world.work = _brief_work()
        world.composer.side_effect = None
        world.composer.return_value = BriefComposition.model_validate(
            {
                "blocks": [
                    {
                        "kind": "items",
                        "state": "needs_you",
                        "heading": "9 things waiting",
                        "items": [
                            {
                                "id": 1,
                                "action": "approve",
                                "outcome": None,
                                "title": "Priya reply",
                                "detail": None,
                            }
                        ],
                    }
                ]
            }
        )

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        assert world.composer.await_count == 2
        retry = world.composer.await_args_list[1].args[1]
        assert "block 1 (items) heading types '9'" in retry
        (salvaged,) = _salvaged(event, "composition")
        assert "'9'" in str(salvaged["problems"])
        (section,) = _stored_payload(world).sections
        assert (section.title, [i.text for i in section.items]) == ("Needs you", ["Priya reply"])
        world.notify.assert_awaited()

    async def test_an_id_the_pool_does_not_hold_is_dropped_by_code_not_sent_back(
        self, world: World
    ) -> None:
        world.work = _brief_work()
        world.composer.side_effect = _composed({"Waiting": ["Approve the Priya reply"]})
        placed = world.composer.side_effect

        def with_a_stranger(
            schema: type[BriefComposition], prompt: str, **kw: object
        ) -> BriefComposition:
            answer = placed(schema, prompt, **kw)
            stranger = answer.blocks[0].items[0].model_copy(update={"id": 99})
            block = answer.blocks[0].model_copy(
                update={"items": [*answer.blocks[0].items, stranger]}
            )
            return answer.model_copy(update={"blocks": [block]})

        world.composer.side_effect = with_a_stranger

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.composer.await_count == 1
        (section,) = _stored_payload(world).sections
        assert [i.text for i in section.items] == ["Approve the Priya reply"]

    async def test_a_heading_untrue_of_its_items_is_retried_with_the_items_named(
        self, world: World
    ) -> None:
        """Live brief: "Landed overnight" stood over a draft still waiting on approval."""
        world.work = _brief_work()
        world.composer.side_effect = _composed({"Landed overnight": ["Approve the Priya reply"]})
        world.headings.side_effect = [
            HeadingVerdicts(
                verdicts=[HeadingVerdict(block=1, fits=False, misfits=[1], why="still waits")]
            ),
            HeadingVerdicts(verdicts=[HeadingVerdict(block=1, fits=True, misfits=[], why="")]),
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        retry = world.composer.await_args_list[1].args[1]
        assert (
            'block 1 heading "Landed overnight" is not true of item 1 (waiting on you, review)'
            in retry
        )
        judged = world.headings.await_args_list[0].args[1]
        assert "- item 1: Approve the Priya reply | waiting on you | action review" in judged

    async def test_voice_the_agent_botched_still_sends_the_brief_plainly(
        self, world: World
    ) -> None:
        world.agent.return_value = SimpleNamespace(message="Sorry, something went wrong.")

        await run_brief(_USER, BriefingKind.DAILY)

        assert "Sorry" not in (_assert_sent_plainly(world).message or "")

    async def test_unknown_user_fails_loud(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(user_repository, "get", AsyncMock(return_value=None))

        with pytest.raises(errors.BriefingGenerationError, match="unknown user"):
            await run_brief(_USER, BriefingKind.DAILY)

        world.agent.assert_not_awaited()

    async def test_dormant_user_without_activity_is_skipped_before_the_agent(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            wind_down,
            "state_from_user",
            lambda _: BriefingDormancy(idle_days=3, date=None, dormant_since=MagicMock()),
        )

        await run_brief(_USER, BriefingKind.DAILY)

        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    async def test_ignored_winback_backs_off(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seam(
            monkeypatch,
            world,
            daily,
            "compute_winback_state",
            AsyncMock(return_value=WinbackState(unacknowledged=5, last_was_winback=True)),
        )

        await run_brief(_USER, BriefingKind.DAILY)

        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    async def test_a_failed_delivery_records_no_channels(self, world: World) -> None:
        world.notify.side_effect = RuntimeError("orchestrator down")

        with pytest.raises(RuntimeError):
            await run_brief(_USER, BriefingKind.DAILY)

        world.upsert.assert_awaited()
        assert all(b.delivered_channels == [] for b in world.briefs.values())
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

        await run_brief(_USER, BriefingKind.DAILY)

        assert _delivered_to(world) == ["inapp"]
        sent = world.capture.call_args.args[1]
        assert sent.channel_count == 1

    async def test_a_brief_already_delivered_today_is_not_sent_again(self, world: World) -> None:
        await run_brief(_USER, BriefingKind.DAILY)
        world.agent.reset_mock()
        world.upsert.reset_mock()
        world.notify.reset_mock()
        world.post.reset_mock()

        outcome = await run_brief(_USER, BriefingKind.DAILY)

        assert outcome is BriefingRunOutcome.ALREADY_DELIVERED
        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    async def test_a_run_that_died_mid_delivery_is_finished_not_resent_or_dropped(
        self, world: World
    ) -> None:
        """A killed worker's retry once saw no delivered channel, rebuilt the brief and sent it twice."""
        world.held = [_held("h1", "Paper digest", _DIGEST_REPORT)]
        world.post.side_effect = RuntimeError("worker killed")
        with pytest.raises(RuntimeError, match="worker killed"):
            await run_brief(_USER, BriefingKind.DAILY)
        world.consume.assert_not_awaited()
        world.post.side_effect = None

        async with captured_wide_event() as event:
            outcome = await run_brief(_USER, BriefingKind.DAILY)

        assert outcome is BriefingRunOutcome.SENT
        assert {k: event["briefing"][k] for k in ("kind", "resumed", "channels", "pushed")} == {
            "kind": "daily",
            "resumed": True,
            "channels": [*_ORCHESTRATED, "telegram"],
            "pushed": True,
        }
        world.render.assert_awaited_once()
        world.notify.assert_awaited_once()
        world.brief_message.assert_awaited_once()
        assert world.post.await_count == 2
        world.consume.assert_awaited_once_with(_USER, ["h1"])
        assert _delivered_to(world) == [*_ORCHESTRATED, "telegram"]
        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.ALREADY_DELIVERED

    async def test_a_sent_brief_reports_it_was_sent(self, world: World) -> None:
        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT


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
    world.reads["list_completed_since"].return_value = _completions(
        [deck], [_own_done("u1", "Send the deck")]
    )
    # GAIA's tracked work finished this week is the daily's own read, from Monday.
    world.work = TrackedWork(completed=[deck])
    world.calendar = [_FRIDAY_PITCH]
    world.week.return_value = BriefingWeek(
        days=[BriefingWeekDay(you=1, gaia=2)] * 7, ahead=[_FRIDAY_PITCH]
    )


class TestWeeklyRecap:
    async def test_recap_is_stored_and_delivered_as_weekly(self, world: World) -> None:
        world.agent.return_value = _weekly_voiced()

        assert await run_brief(_USER, BriefingKind.WEEKLY) is BriefingRunOutcome.SENT

        payload = _stored_payload(world)
        # Masthead, date and mood come from code, whatever the model wrote.
        assert (payload.kicker, payload.date, payload.mood) == (WEEKLY_KICKER, _DATE, "weekly")
        assert world.upsert.await_args.args[0].kind == "weekly"
        assert payload.template_family == "weekly"
        assert payload.week == world.week.return_value
        # The tallies count the week's completions themselves: the user's one todo.
        assert payload.tallies == BriefingTallies(done_by_you=1, done_by_gaia=0)
        assert payload.headline == "A good week"
        request = world.notify.await_args.args[0]
        assert request.metadata["kind"] == NOTIFICATION_KIND_BRIEFING_WEEKLY
        assert request.content.body == payload.message == "Gym"
        # The recap is always pushed: it reaches the chat app, not only the in-app page.
        assert world.post.await_args.kwargs["origin"] == "weekly brief"
        world.consume.assert_not_awaited()

    async def test_a_recap_already_delivered_today_is_not_sent_again(self, world: World) -> None:
        await run_brief(_USER, BriefingKind.WEEKLY)
        world.agent.reset_mock()
        world.upsert.reset_mock()
        world.notify.reset_mock()
        world.post.reset_mock()

        assert await run_brief(_USER, BriefingKind.WEEKLY) is BriefingRunOutcome.ALREADY_DELIVERED

        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    async def test_code_builds_the_sections_from_the_weeks_candidates(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: the model wrote the whole weekly payload, its sections and items included."""
        _a_full_week(monkeypatch, world)
        world.agent.return_value = _weekly_voiced()
        world.composer.side_effect = _composed(
            {
                "Needs you": ["CRM sync failed"],
                "You finished": ["Send the deck"],
                "GAIA's work": ["Investor deck"],
            }
        )

        await run_brief(_USER, BriefingKind.WEEKLY)

        payload = _stored_payload(world)
        assert [(s.title, [(i.text, i.kind) for i in s.items]) for s in payload.sections] == [
            ("Needs you", [("CRM sync failed", "failed")]),
            ("You finished", [("Send the deck", "lookback")]),
            ("GAIA's work", [("Investor deck", "lookback")]),
        ]
        assert payload.message == "CRM sync failed\nSend the deck\nInvestor deck\nPitch to Accel"
        assert payload.week == world.week.return_value
        (since,) = world.reads["list_since"].await_args.args[1:2]
        assert since == _WEEK_START

    async def test_the_weekly_reads_this_users_week_ahead(self, world: World) -> None:
        await run_brief(_USER, BriefingKind.WEEKLY)

        # One read: this week from Monday, then the seven local days from tomorrow to 22 Oct.
        world.reads["fetch_calendar"].assert_awaited_once_with(
            _USER, _WEEK_START, datetime(2026, 10, 21, 18, 30, tzinfo=UTC)
        )

    async def test_a_lead_the_weekly_edition_cannot_draw_moves_to_the_briefs_page(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _a_full_week(monkeypatch, world)
        world.agent.return_value = _weekly_voiced()
        world.composer.side_effect = _composed(
            {"GAIA's work": ["Investor deck"]}, lead=("CRM sync failed", "I can rerun it.")
        )

        await run_brief(_USER, BriefingKind.WEEKLY)

        payload = _stored_payload(world)
        assert payload.undrawn == [SectionBlock(kind="lead", section=0)]
        assert payload.blocks == [SectionBlock(kind="items", section=1)]
        assert [s.items[0].text for s in payload.sections] == ["CRM sync failed", "Investor deck"]

    async def test_the_week_ahead_is_timed_by_its_day_and_the_composer_reads_the_week(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _a_full_week(monkeypatch, world)
        world.agent.return_value = _weekly_voiced(
            lede="Then [[fact:<fact of Pitch to Accel>]] on Friday at "
            "[[fact:<fact of Pitch to Accel>.time]]."
        )

        await run_brief(_USER, BriefingKind.WEEKLY)

        # Timed as the daily times them: the day is the heading's, the slot says the time.
        assert _stored_payload(world).lede == "Then Pitch to Accel on Friday at 3:00 PM."
        facts = _facts_shown(_prompt(world))
        assert "The week ahead, 1 event(s):\nFri Oct 16, 1 event(s):\n- fact " in facts
        assert "(3:00 PM): Pitch to Accel" in facts
        assert "summary: Final numbers in" in facts
        assert "weekly digest for the week ending 2026-10-14" in world.composer.await_args.args[1]
        assert "## THIS WEEK'S FACTS" in _prompt(world)

    async def test_every_event_ahead_is_counted_by_day_and_the_busiest_day_is_named(
        self, world: World
    ) -> None:
        """Regression: the week ahead stopped at five events, so a six-meeting Monday read as five."""
        monday = [
            BriefingEvent(date="2026-10-19", start=f"{hour:02d}:00", title=f"Meeting {hour}")
            for hour in range(9, 15)
        ]
        world.calendar = [*monday, _FRIDAY_PITCH]

        await run_brief(_USER, BriefingKind.WEEKLY)

        facts = _facts_shown(_prompt(world))
        assert "The week ahead, 7 event(s):" in facts
        assert "Fri Oct 16, 1 event(s):" in facts
        assert "Mon Oct 19, 6 event(s), the week's busiest:" in facts
        assert all(f": Meeting {hour}" in facts for hour in range(9, 15))
        assert "Fri Oct 16, 1 event(s):" in facts

    async def test_a_week_of_equally_full_days_names_no_busiest_day(self, world: World) -> None:
        """Replay: six events on every day marked all seven the week's busiest."""
        world.calendar = [
            BriefingEvent(date=f"2026-10-{day}", start="09:00", title=f"Standup {day}")
            for day in range(15, 22)
        ]

        await run_brief(_USER, BriefingKind.WEEKLY)

        facts = _facts_shown(_prompt(world))
        assert "The week ahead, 7 event(s):" in facts
        assert "Thu Oct 15, 1 event(s):" in facts
        assert "busiest" not in facts


class TestTheWeeklyHoldsToItsFacts:
    """The weekly's prose is held to its facts by the daily's slots and lead."""

    async def test_a_typed_count_is_sent_back(self, world: World) -> None:
        world.agent.side_effect = [_weekly_voiced(lede="You finished 9 things."), _weekly_voiced()]

        await run_brief(_USER, BriefingKind.WEEKLY)

        retry = world.agent.await_args_list[1].kwargs["prompt"]
        assert "the lede types '9', a figure no fact carries" in retry

    async def test_a_recap_without_a_lead_need_not_name_the_failed_run_or_the_week_ahead(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _a_full_week(monkeypatch, world)
        world.agent.return_value = _weekly_voiced(
            message="Good week. [Send the deck](fact:<fact of Send the deck>)."
        )

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert world.agent.await_count == 1

    async def test_a_recap_that_leaves_out_its_lead_is_sent_back(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _a_full_week(monkeypatch, world)
        world.composer.side_effect = _composed(
            {"GAIA's work": ["Investor deck"]}, lead=("CRM sync failed", "I can rerun it.")
        )
        world.agent.return_value = _weekly_voiced(message="Good week.")

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert "(CRM sync failed)" in world.agent.await_args_list[1].kwargs["prompt"]
        assert (_assert_sent_plainly(world).message or "").startswith("- CRM sync failed\n")

    async def test_a_frequency_word_its_facts_carry_is_kept(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.reads["list_completed_since"].return_value = _completions(
            user=[_own_done("u1", "Send the usual deck")]
        )
        world.agent.return_value = _weekly_voiced(lede="The usual deck went out.")

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert world.agent.await_count == 1
        assert _stored_payload(world).lede == "The usual deck went out."

    async def test_the_recap_names_the_apps_behind_what_it_shows(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _a_full_week(monkeypatch, world)
        world.agent.return_value = _weekly_voiced()

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert _stored_payload(world).sources_read == ["Google Calendar"]

    async def test_a_recap_without_a_message_still_goes_out_plainly(self, world: World) -> None:
        world.agent.return_value = _weekly_voiced(message="")

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert _assert_sent_plainly(world).message


def _finished(todo_id: str, title: str, *, gaia: bool, days_ago: int) -> TodoDocument:
    done = _NOW - timedelta(days=days_ago)
    return TodoDocument(
        id=todo_id,
        user_id=_USER,
        title=title,
        labels=[GAIA_TRACKED_LABEL] if gaia else [],
        completed=True,
        completed_at=done,
        completed_by=TodoCompleter.GAIA if gaia else TodoCompleter.USER,
        updated_at=done,
    )


class TestTheWeeklyAnswersTheWeek:
    """Founder design: what moved and stuck per goal, GAIA's week grouped, what waits, next week."""

    async def test_an_empty_week_sends_the_quiet_note_and_never_an_edition(
        self, world: World
    ) -> None:
        world.calendar = []
        world.reads["list_completed_since"].return_value = []

        assert await run_brief(_USER, BriefingKind.WEEKLY) is BriefingRunOutcome.SENT

        world.composer.assert_not_awaited()
        world.agent.assert_not_awaited()
        world.render.assert_not_awaited()
        payload = _stored_payload(world)
        assert world.upsert.await_args.args[0].kind == "weekly"
        assert (payload.form, payload.kicker, payload.headline) == (
            BriefForm.QUIET_NOTE,
            WEEKLY_KICKER,
            "Nothing needs you this week",
        )
        assert payload.message == (
            "Nothing moved this week, and next week's calendar is clear.\n"
            "I'll flag anything that comes in."
        )

    async def test_a_week_whose_goal_work_sat_stuck_is_recapped_never_quiet(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Replay: a quiet week dropped the stalled growth goal the old weekly recapped."""
        world.calendar = []
        world.reads["list_completed_since"].return_value = []
        goal = StatedGoal("Launch Atlas", GoalOrigin.MEMORY, terms=("Atlas",))
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[goal]))
        stuck = TodoDocument(
            id="a2", user_id=_USER, title="Atlas pricing", updated_at=_NOW - timedelta(days=9)
        )
        world.reads["list_open_user_todos"].return_value = [stuck]
        world.composer.side_effect = lambda schema, _prompt, **_k: schema.model_validate(
            {"blocks": [{"kind": "progress", "goal_id": "g1"}]}
        )
        world.agent.return_value = _weekly_voiced()

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert _stored_payload(world).form is BriefForm.EDITION
        assert (
            '- "Launch Atlas": nothing linked to it finished, 0 finished since Mon Oct 12, 1 open'
            " | stuck a week or more: Atlas pricing"
        ) in _facts_shown(_prompt(world))

    async def test_the_weekly_is_sent_back_for_a_line_a_recent_daily_printed(
        self, world: World
    ) -> None:
        """The weekly passed no recent lines and the daily read only dailies."""
        daily_brief = BriefingPayload(
            kicker="K",
            date="2026-10-13",
            headline="A good week",
            lede="l",
            mood=BriefingMood.PACKED,
            caption="c",
            template_family=EditionFamily.SWISS,
        )
        world.recent.return_value = [
            BriefingModel(id="d", user_id=_USER, date="2026-10-13", payload=daily_brief)
        ]
        world.agent.side_effect = [_weekly_voiced(), _weekly_voiced(headline="A full week")]

        await run_brief(_USER, BriefingKind.WEEKLY)

        world.recent.assert_awaited_once_with(_USER, limit=5)
        retry = world.agent.await_args_list[1].kwargs["prompt"]
        assert "the headline repeats a recent brief's line ('A good week')" in retry
        assert "Headlines:\n- A good week" in retry
        assert _stored_payload(world).headline == "A full week"

    async def test_what_waits_on_the_user_reaches_the_weekly_and_is_remembered_as_shown(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The weekly read only failed runs, completions and the calendar, and scouts with no signals."""
        world.work = TrackedWork(blocked=[_todo("b1", "Approve the Priya reply")])
        world.scouts = _scouted(_LOGIN)
        _seam(monkeypatch, world, BriefReads, "own_todos", _own_todos(80, 70))
        world.agent.return_value = _weekly_voiced(lede="Two things wait on you.")

        await run_brief(_USER, BriefingKind.WEEKLY)

        facts = _facts_shown(_prompt(world))
        assert "Waiting on you: Approve the Priya reply" in facts
        assert "[[count:overdue_todos]] (70)" in facts
        assert "Fix the login redirect" in _prompt(world)
        world.seen.assert_awaited()
        shown = [seen.external_id for seen in world.shown.await_args.args[1]]
        assert "todo:b1" in shown

    async def test_gaias_week_is_one_grouped_count_per_kind_of_work(self, world: World) -> None:
        finished = [_finished(f"g{n}", f"Research {n}", gaia=True, days_ago=1) for n in range(6)]
        world.reads["list_completed_since"].return_value = finished
        world.work = TrackedWork(completed=finished[:1])
        # Meeting hours and the last day's mail sort are not GAIA's week: neither is counted.
        world.calendar = [BriefingEvent(date="2026-10-13", start="10:00", title="Board")]
        world.reads["verdicts_since"].return_value = [
            EmailVerdictDocument(
                user_id=_USER,
                message_id="m1",
                answers={},
                bucket=DeskBucket.REPLY,
                created_at=_NOW,
            )
        ]
        world.agent.return_value = _weekly_voiced(
            lede="I finished [[series:gaia_finished.total]] tasks."
        )

        await run_brief(_USER, BriefingKind.WEEKLY)

        facts = _facts_shown(_prompt(world))
        assert "[THE WEEK IN NUMBERS]" in facts
        numbers = facts.split("[THE WEEK IN NUMBERS]", 1)[1].split("\n[", 1)[0]
        assert numbers.splitlines()[1:] == [
            "- Tasks GAIA finished: [[series:gaia_finished.total]] (6 tasks)"
        ]
        assert _stored_payload(world).lede == "I finished 6 tasks."

    async def test_each_goal_says_what_moved_it_and_what_is_stuck_a_week_or_more(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        goal = StatedGoal("Launch Atlas", GoalOrigin.MEMORY, terms=("Atlas",))
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[goal]))
        world.reads["list_completed_since"].return_value = [
            _finished("a1", "Atlas landing page", gaia=False, days_ago=2)
        ]
        stuck = TodoDocument(
            id="a2",
            user_id=_USER,
            title="Atlas pricing",
            updated_at=_NOW - timedelta(days=9),
        )
        fresh = TodoDocument(
            id="a3", user_id=_USER, title="Atlas press list", updated_at=_NOW - timedelta(days=2)
        )
        world.reads["list_open_user_todos"].return_value = [stuck, fresh]
        world.agent.return_value = _weekly_voiced()

        await run_brief(_USER, BriefingKind.WEEKLY)

        facts = _facts_shown(_prompt(world))
        assert (
            '- "Launch Atlas": moved forward, 1 finished since Mon Oct 12 (1 by the user), 2 open:'
            " Atlas landing page | stuck a week or more: Atlas pricing"
        ) in facts


_TODAY_START = datetime(2026, 10, 13, 18, 30, tzinfo=UTC)
# The week ahead runs seven local days from tomorrow; what falls due in it is the weekly's.
_WEEK_AHEAD_END = _TODAY_START + timedelta(days=8)


class TestTheWeeklyReadsThisUsersWeek:
    """Every weekly read is the user's and the week's, and what it writes is stamped now."""

    async def test_every_read_is_this_users_over_the_week_and_the_week_ahead(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _a_full_week(monkeypatch, world)
        world.scouts = [
            *_scouted(_LOGIN),
            ScoutResult(
                integration_id="notion",
                app="Notion",
                outcome=ScoutOutcome.SKIPPED,
                skip_reason=ScoutSkipReason.FAILED,
            ),
        ]
        world.recent.return_value = [
            BriefingModel(
                id="d",
                user_id=_USER,
                date="2026-10-13",
                payload=BriefingPayload(
                    kicker="K",
                    date="2026-10-13",
                    headline="h",
                    lede="l",
                    mood=BriefingMood.PACKED,
                    caption="c",
                    message="Priya replied overnight.",
                    template_family=EditionFamily.SWISS,
                ),
            )
        ]
        world.memory = [
            SignalMemoryDocument(
                user_id=_USER,
                integration_id="linear",
                external_id="ENG-12",
                first_seen=_NOW - timedelta(days=3),
                times_shown=1,
                last_shown=_NOW - timedelta(days=2),
                last_state="In Progress",
            )
        ]
        _seam(monkeypatch, world, BriefReads, "own_todos", _own_todos(80, 70))
        due = TodoDocument(
            id="o1", user_id=_USER, title="File the VAT return", due_date=_NOW + timedelta(days=1)
        )
        world.reads["list_open_user_todos"].return_value = [due]
        world.agent.return_value = _weekly_voiced(
            message="[The deck](fact:<fact of Investor deck>) is done. [[fact:<fact of Investor deck>]]"
            " shipped, [Priya](fact:<fact of Fix the login redirect>) waits."
        )

        await run_brief(_USER, BriefingKind.WEEKLY)

        world.reads["tracked_work"].assert_called_once_with(_WEEK_START)
        assert world.agent.await_args.kwargs["config"] == metered_config(_USER)
        assert "first seen 3 days ago, mentioned 1 time(s), last 2 days ago" in _prompt(world)
        assert world.reads["own_todos"].call_args.args[0].date_str == _DATE
        world.reads["find_scheduled_between"].assert_awaited_once_with(
            _USER, _TODAY_START, _WEEK_AHEAD_END
        )
        world.reads["list_open_user_todos"].assert_awaited_once_with(_USER, limit=0)
        assert world.week.call_args.args[2] == [_FRIDAY_PITCH]
        assert all(c.args[0] == _USER and c.args[2] == _NOW for c in world.seen.await_args_list)
        assert "Recent briefs opened on" in world.composer.await_args.args[1]
        assert "Priya replied overnight." in world.composer.await_args.args[1]
        prompt_args = world.weekly_prompt.call_args.kwargs
        assert prompt_args["date_local"] == _DATE
        assert prompt_args["blocks"].reader == reader_block(world.user)
        facts = _facts_shown(_prompt(world))
        assert "[[count:open_todos]] (80)" in facts and "[[count:overdue_todos]] (70)" in facts
        assert "never voice that list as clear or empty." in facts
        assert "[[count:overdue_todos]] of them are past due" in facts
        assert "File the VAT return | time: [[fact:" in facts and "(Thu Oct 15)" in facts
        assert "[ACROSS THEIR APPS]" in _prompt(world)
        world.mint.assert_any_await(_USER, ShortLinkTargetType.TODO_DELIVERABLE, "g1")
        payload = _stored_payload(world)
        assert [(u.app, u.reason) for u in payload.sources_unavailable] == [
            ("Notion", ScoutSkipReason.FAILED)
        ]
        assert world.capture.call_args.args[1].signal_count == 1
        shown_by, _, shown_at = world.shown.await_args.args
        assert (shown_by, shown_at) == (_USER, _NOW)

    async def test_a_quiet_week_note_says_the_calendar_the_streak_and_whats_overdue(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.calendar = CalendarGap.UNAVAILABLE
        world.reads["list_completed_since"].return_value = []
        _seam(monkeypatch, world, BriefReads, "own_todos", _own_todos(3, 3))
        world.reads["list_open_user_todos"].return_value = [
            TodoDocument(id="u9", user_id=_USER, title="Sort the garage")
        ]

        def brief(day: str, form: BriefForm) -> BriefingModel:
            payload = BriefingPayload(
                form=form,
                kicker="K",
                date=day,
                headline="h",
                lede="",
                mood=BriefingMood.IDLE,
                caption="",
                template_family=None,
            )
            return BriefingModel(
                id=day, user_id=_USER, date=day, kind=BriefingKind.WEEKLY, payload=payload
            )

        _briefs_read(
            world,
            [brief("2026-10-07", BriefForm.QUIET_NOTE), brief("2026-10-05", BriefForm.EDITION)],
        )

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert _stored_payload(world).message.splitlines() == [
            "Still nothing new: 9 days since your brief on Monday Oct 5. I couldn't read "
            "your calendar, so check it before you plan.",
            "3 of your own todos are past due.",
            "I'll flag anything that comes in.",
        ]
        payload = _stored_payload(world)
        assert (payload.lede, payload.caption, payload.template_family) == ("", "", None)
        channels = _delivered_to(world, BriefingKind.WEEKLY)
        assert channels
        assert world.capture.call_args.args == (
            UserId(_USER),
            BriefingSent(
                kind=BriefingKind.WEEKLY,
                form="quiet_note",
                family=None,
                mood=BriefingMood.IDLE,
                item_count=0,
                channel_count=len(channels),
                signal_count=0,
                stamp_collected=False,
                block_kinds=[],
                chart_count=0,
                pool_item_count=1,
                series_count=0,
                source_count=0,
            ),
        )

    async def test_a_quiet_week_a_day_after_an_edition_says_since_yesterday(
        self, world: World
    ) -> None:
        world.calendar = []
        world.reads["list_completed_since"].return_value = []

        def brief(day: str, form: BriefForm, kind: BriefingKind) -> BriefingModel:
            payload = BriefingPayload(
                form=form,
                kicker="K",
                date=day,
                headline="h",
                lede="",
                mood=BriefingMood.IDLE,
                caption="",
                template_family=None,
            )
            return BriefingModel(id=day, user_id=_USER, date=day, kind=kind, payload=payload)

        _briefs_read(
            world,
            [
                brief("2026-10-13", BriefForm.EDITION, BriefingKind.DAILY),
                brief("2026-10-12", BriefForm.EDITION, BriefingKind.DAILY),
                brief("2026-10-07", BriefForm.QUIET_NOTE, BriefingKind.WEEKLY),
            ],
        )

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert _stored_payload(world).message.splitlines()[0] == (
            "Still nothing new since your brief yesterday, and next week's calendar is clear."
        )
        assert call(_USER, limit=1, editions_only=True) in world.recent.await_args_list

    async def test_a_quiet_week_names_every_app_it_could_not_read(self, world: World) -> None:
        world.calendar = []
        world.reads["list_completed_since"].return_value = []
        world.scouts = [
            ScoutResult(
                integration_id=integration,
                app=app,
                outcome=ScoutOutcome.SKIPPED,
                skip_reason=ScoutSkipReason.FAILED,
            )
            for integration, app in (("notion", "Notion"), ("linear", "Linear"))
        ]

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert _stored_payload(world).message.splitlines() == [
            "Nothing new in what I could read, and next week's calendar is clear.",
            "I couldn't read Notion or Linear this time, so I can't say what they hold.",
            "I'll flag anything that comes in.",
        ]

    async def test_the_weekly_never_calls_an_empty_own_list_clear_beside_gaias_open_work(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _a_full_week(monkeypatch, world)
        world.work = replace(world.work, running=[_todo("r1", "Research the venue")])
        world.agent.return_value = _weekly_voiced()

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert (
            "The user has no todos of their own outside GAIA's tracked work, which holds "
            "[[count:open_tracked]] open: never call their todo list empty or clear."
        ) in _facts_shown(_prompt(world)).splitlines()


class TestHeldItemsJoinTheBrief:
    """Results held for the brief are candidates like any other.

    The held results come from brief-delivery workflows and the inbox desk; each
    appears once and is cleared once the brief went out.
    """

    async def test_a_held_result_joins_gaias_work_and_is_cleared(self, world: World) -> None:
        world.work = _brief_work()
        world.held = [_held("h1", "Paper digest", _DIGEST_REPORT)]

        await run_brief(_USER, BriefingKind.DAILY)

        assert [(s.title, [i.text for i in s.items]) for s in _stored_payload(world).sections] == [
            ("Needs you", ["Approve the Priya reply"]),
            ("GAIA's work", ["Paper digest: 3 new papers on retrieval", "Investor update"]),
        ]
        # The headline and lede are voiced from the items, so a report's body never
        # reaches the prompt to be claimed from.
        assert "Paper digest: 3 new papers on retrieval" in _prompt(world)
        assert "two cite your draft" not in _prompt(world)
        world.consume.assert_awaited_once_with(_USER, ["h1"])

    async def test_an_item_already_in_the_brief_is_shown_once_and_still_cleared(
        self, world: World
    ) -> None:
        world.work = TrackedWork(completed=[_todo("c1", "Digest: 3 new papers")])
        world.held = [
            _held("h1", "Digest", "3 new papers\nmore detail"),
            _held("h2", "Paper digest", _DIGEST_REPORT),
            _held("h3", "Paper  digest", _DIGEST_REPORT),
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        texts = [i.text for s in _stored_payload(world).sections for i in s.items]
        assert texts == ["Paper digest: 3 new papers on retrieval", "Digest: 3 new papers"]
        world.consume.assert_awaited_once()
        assert world.consume.await_args.args[0] == _USER
        assert sorted(world.consume.await_args.args[1]) == ["h1", "h2", "h3"]

    async def test_a_held_result_left_out_of_the_composition_is_on_the_page_and_cleared(
        self, world: World
    ) -> None:
        """Nothing the composition leaves out is lost: it is on the brief's full page."""
        world.work = TrackedWork(completed=[_todo(f"c{i}", f"Done {i}") for i in range(3)])
        world.held = [_held("h1", "Digest", "first"), _held("h2", "Paper digest", "second")]
        world.composer.side_effect = _composed(
            {"Done overnight": ["Done 0", "Done 1", "Done 2", "Paper digest: second"]}
        )

        await run_brief(_USER, BriefingKind.DAILY)

        payload = _stored_payload(world)
        texts = [i.text for s in payload.sections for i in s.items]
        assert texts == ["Done 0", "Done 1", "Done 2", "Paper digest: second"]
        assert [(i.title, i.app, i.kind) for i in payload.uncomposed] == [
            ("Digest: first", "GAIA", "note")
        ]
        world.consume.assert_awaited_once_with(_USER, ["h1", "h2"])

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

        await run_brief(_USER, BriefingKind.DAILY)

        [section] = _stored_payload(world).sections
        assert section.title == "From your apps"
        assert [(i.text, i.app, i.kind) for i in section.items] == [
            ("Stripe payout of 2,400 dollars landed", "Gmail", "note")
        ]
        assert _stored_payload(world).sources_read == ["Gmail", "Google Calendar"]

    async def test_a_failed_delivery_clears_nothing(self, world: World) -> None:
        world.held = [_held("h1", "Paper digest", _DIGEST_REPORT)]
        world.notify.side_effect = RuntimeError("orchestrator down")

        with pytest.raises(RuntimeError):
            await run_brief(_USER, BriefingKind.DAILY)

        world.consume.assert_not_awaited()


def _voiced(headline: str, lede: str) -> SimpleNamespace:
    return SimpleNamespace(message=_fenced({**_VOICE, "headline": headline, "lede": lede}))


class TestTheProseHoldsToItsFacts:
    """The headline, lede, caption and message are held to their slots before anything renders."""

    async def test_an_app_the_brief_could_not_read_is_named_to_the_composer_and_the_voice(
        self, world: World
    ) -> None:
        world.work = _brief_work()
        world.scouts = [
            ScoutResult(
                integration_id="notion",
                app="Notion",
                outcome=ScoutOutcome.SKIPPED,
                skip_reason=ScoutSkipReason.FAILED,
            )
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        unread = (
            "Not read this time: Notion. Nothing is known about what they hold today: never say "
            "they hold nothing, or that nothing there needs the user."
        )
        assert unread in world.composer.await_args.args[1]
        assert unread in _facts_shown(_prompt(world))

    async def test_a_message_calling_a_failed_item_a_success_is_sent_back(
        self, world: World
    ) -> None:
        """Dhruv: the message said a charge was marked successful while its item said it failed."""
        world.work = TrackedWork(failed=[_todo("f1", "Fastlane charge")])
        world.agent.side_effect = [
            _wrote("The [Fastlane charge](fact:1) was marked successful."),
            _wrote("The [Fastlane charge](fact:1) needs a retry."),
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        retry = world.agent.await_args_list[1].kwargs["prompt"]
        assert (
            "the message says fact 1 'successful', but its state is failed; say where it stands "
            "as its line does"
        ) in retry
        assert "needs a retry" in (_stored_payload(world).message or "")

    async def test_a_message_giving_an_item_another_facts_date_is_sent_back(
        self, world: World
    ) -> None:
        """Dhruv: "Tue Nov 17" was said of an intro whose own line said Nov 9 or 10."""
        intro = _todo("b1", "Reschedule the LogForge intro")
        intro.description = "Adan offered Nov 9 or 10"
        world.work = TrackedWork(
            blocked=[intro], running=[_todo("r1", "Book the venue for Nov 17")]
        )
        world.agent.side_effect = [
            _wrote("You picked Nov 17 for the [LogForge intro](fact:1)."),
            _wrote("[The LogForge intro](fact:1) waits on your pick."),
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        retry = world.agent.await_args_list[1].kwargs["prompt"]
        assert "the message says '17' of fact 1, but that is another fact's" in retry

    async def test_an_invite_the_user_left_unanswered_says_so_with_its_end_and_calendar(
        self, world: World
    ) -> None:
        """Audit: events carried no RSVP, organizer, guests, end or calendar."""
        world.calendar = []
        world.reads["fetch_calendar"].side_effect = lambda user_id, start, end: [
            GoogleCalendarEventResource.model_validate(
                {
                    "summary": "Sequoia",
                    "calendarTitle": "Work",
                    "start": {"dateTime": "2026-10-14T11:00:00+05:30"},
                    "end": {"dateTime": "2026-10-14T11:30:00+05:30"},
                    "organizer": {"displayName": "Roelof"},
                    "attendees": [
                        {"email": "ada@b.c", "self": True, "responseStatus": "needsAction"},
                        {"email": "roelof@s.c"},
                    ],
                }
            )
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        assert (
            "- fact 1 | [[fact:1.time]] (11:00 AM): Sequoia | until 11:30 AM | on the Work "
            "calendar | organized by Roelof | 1 other(s) invited | the user has not answered "
            "the invite"
        ) in _facts_shown(_prompt(world))

    async def test_the_stored_brief_holds_each_slot_filled_from_its_fact(
        self, world: World
    ) -> None:
        world.agent.return_value = _voiced(
            "Sequoia at [[fact:<fact of Sequoia>.time]]", "Then the Accel intro."
        )

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).headline == "Sequoia at 11:00 AM"
        assert _stored_payload(world).message == "Sequoia"

    async def test_a_count_the_model_was_shown_is_voiced_by_its_slot(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: 5 open todos were shown to the model, then rejected when it said 5."""
        _seam(monkeypatch, world, BriefReads, "own_todos", _own_todos(5))
        world.calendar = []
        world.agent.return_value = _voiced(
            "[[count:open_todos]] open todos, a quiet morning", "Nothing else today."
        )

        await run_brief(_USER, BriefingKind.DAILY)

        assert "[COUNTS] [[count:open_todos]] (5)\n" in _prompt(world)
        assert world.agent.await_count == 1
        assert _stored_payload(world).headline == "5 open todos, a quiet morning"

    @pytest.mark.parametrize(
        ("headline", "named"),
        [
            ("6 open todos", "the headline types '6', a figure no fact carries"),
            ("[[count:done]] done overnight", "[[count:done]] is not a count the facts list"),
            ("[[fact:9]] is waiting", "fact:9 is no fact shown today"),
        ],
    )
    async def test_a_figure_typed_or_a_slot_naming_nothing_shown_is_regenerated(
        self, world: World, monkeypatch: pytest.MonkeyPatch, headline: str, named: str
    ) -> None:
        _seam(monkeypatch, world, BriefReads, "own_todos", _own_todos(5))
        world.agent.side_effect = [
            _voiced(headline, "A quiet morning."),
            _voiced("A quiet one", "-"),
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        assert named in world.agent.await_args_list[1].kwargs["prompt"]
        assert _stored_payload(world).headline == "A quiet one"

    async def test_a_headline_past_its_limit_once_filled_is_regenerated(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        long_title = "Sign " + "the long agreement " * 6
        world.calendar = [BriefingEvent(date=_DATE, start="11:00", title=long_title)]
        world.agent.side_effect = [
            _voiced("Today: [[fact:1]]", "One event."),
            _voiced("One long signing today", "One event."),
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        retry = world.agent.await_args_list[1].kwargs["prompt"]
        assert (
            f"the headline once its slots are filled: String should have at most "
            f"{MAX_BRIEF_HEADLINE_CHARS} characters"
        ) in retry
        assert _stored_payload(world).headline == "One long signing today"


class TestTheMessageRefersToTheLead:
    """The message refers to the lead through a slot; the rest of the day is the voice's call."""

    async def test_a_message_need_not_name_every_need_or_event(self, world: World) -> None:
        """E2E: briefs failed for naming a need in plain words; the edition already shows them all."""
        world.work = _brief_work()
        world.agent.return_value = _wrote("The investor update went out.")

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.agent.await_count == 1
        assert _stored_payload(world).message == "The investor update went out."

    async def test_a_message_that_leaves_out_the_lead_is_regenerated_naming_only_the_lead(
        self, world: World
    ) -> None:
        world.work = _brief_work()
        world.composer.side_effect = _composed(
            {"Done overnight": ["Investor update"]},
            lead=("Approve the Priya reply", "Send the reply once you approve"),
        )
        world.agent.side_effect = [
            _wrote("The investor update went out."),
            _wrote("[Priya's reply](fact:1) is first; the investor update went out."),
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        retry = world.agent.await_args_list[1].kwargs["prompt"]
        assert "the message never refers to the lead, fact 1 (Approve the Priya reply)" in retry
        assert "Sequoia" not in retry.rsplit("## YOUR LAST BRIEF WAS REJECTED", 1)[1]
        assert (
            _stored_payload(world).message
            == "Priya's reply is first; the investor update went out."
        )

    async def test_a_message_that_leaves_out_the_lead_on_every_attempt_fails(
        self, world: World
    ) -> None:
        world.work = _brief_work()
        world.composer.side_effect = _composed(
            {}, lead=("Approve the Priya reply", "Send the reply once you approve")
        )
        world.agent.return_value = _wrote("[Sequoia](fact:3) at eleven.")

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        payload = _assert_sent_plainly(world)
        # The plain brief leads with the lead, as the composition did.
        assert (payload.message or "").startswith("- Approve the Priya reply\n")
        assert "never refers to the lead" in _salvaged(event, "voice")[0]["problems"]

    async def test_a_winback_note_need_not_cover_everything(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.work = _brief_work()
        _seam(
            monkeypatch,
            world,
            daily,
            "compute_winback_state",
            AsyncMock(
                return_value=WinbackState(unacknowledged=WINBACK_THRESHOLD, last_was_winback=False)
            ),
        )
        world.agent.return_value = _wrote("The investor update is still sitting here, want it?")

        await run_brief(_USER, BriefingKind.DAILY)

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

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.agent.await_count == 1
        assert _stored_payload(world).message.endswith("\n\nThat is the day.")

    async def test_an_unreadable_reply_is_retried_once_with_its_problem_named(
        self, world: World
    ) -> None:
        world.agent.side_effect = [_MOOD_LEFT_OUT, SimpleNamespace(message=_fenced(_VOICE))]

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.agent.await_count == 2
        first = world.agent.await_args_list[0].kwargs["prompt"]
        retry = world.agent.await_args_list[1].kwargs["prompt"]
        assert (
            retry
            == f"{first}\n\n{voice_unreadable_note(['mood: Field required'], _message_written(first, _MOOD_LEFT_OUT.message))}"
        )
        assert _stored_payload(world).headline == _VOICE["headline"]

    async def test_an_unreadable_reply_is_logged_by_its_problems(self, world: World) -> None:
        world.agent.side_effect = [_MOOD_LEFT_OUT, SimpleNamespace(message=_fenced(_VOICE))]

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        warning = next(
            w for w in event["warnings"] if w["msg"] == "briefing.checked_call_unreadable"
        )
        assert warning["problems"] == ["mood: Field required"]

    async def test_a_reply_off_the_schema_names_its_fields_never_its_text(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        try:
            BriefVoice.model_validate({"headline": "Arjun's redlines", "lede": "x", "caption": "y"})
        except ValidationError as error:
            off_schema = MalformedStructuredOutputError(
                f"BriefVoice: tool-call arguments do not fit the schema: {error}"
            )
            off_schema.__cause__ = error
        world.voice = AsyncMock(side_effect=off_schema)

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        _assert_sent_plainly(world)
        (salvaged,) = _salvaged(event, "voice")
        assert "mood: Field required; message: Field required" in salvaged["problems"]
        assert "Arjun" not in str(event["warnings"]) + str(event["errors"])

    async def test_a_reply_unreadable_on_every_attempt_names_the_shape_and_sends_a_plain_brief(
        self, world: World
    ) -> None:
        cut_short = SimpleNamespace(message='```json\n{"headline": "Arjun needs the redlines\n```')
        world.agent.side_effect = [_MOOD_LEFT_OUT] * (MAX_VOICE_ATTEMPTS - 1) + [cut_short]

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        (salvaged,) = _salvaged(event, "voice")
        assert (
            "invalid JSON: Unterminated string starting at (char 13 of 38)" in salvaged["problems"]
        )
        assert "Arjun" not in salvaged["problems"]
        assert "Arjun" not in (_assert_sent_plainly(world).message or "")


def _wrote(message: str) -> SimpleNamespace:
    return SimpleNamespace(message=_fenced({**_VOICE, "message": message}))


class TestWhatTheWriterIsShown:
    async def test_the_model_sees_what_recent_briefs_printed(self, world: World) -> None:
        def brief(message: str | None) -> BriefingModel:
            payload = BriefingPayload(
                kicker="K",
                date="2026-10-13",
                headline="h",
                lede="l",
                mood=BriefingMood.PACKED,
                caption="c",
                message=message,
                template_family=EditionFamily.SWISS,
            )
            return BriefingModel(id="b", user_id=_USER, date="2026-10-13", payload=payload)

        world.recent.return_value = [brief("\n  Priya replied overnight.\nMore."), brief(None)]

        await run_brief(_USER, BriefingKind.DAILY)

        # Every kind: a weekly's lines are as stale to the next daily as a daily's.
        world.recent.assert_awaited_once_with(_USER, limit=5)
        assert (
            "Headlines:\n- h\n- h\nLedes:\n- l\n- l\nCaptions:\n- c\n- c\n"
            "Message openings:\n- Priya replied overnight.\n"
        ) in _prompt(world)


class TestOneSubjectIsOneItem:
    """Regression: three approval requests for one Acme MSA renewal became one line with three links."""

    async def test_todos_with_the_same_title_reach_the_model_and_the_page_as_one_counted_item(
        self, world: World
    ) -> None:
        world.work = TrackedWork(
            blocked=[
                _todo("b1", "Approve the Acme MSA renewal"),
                _todo("b2", "Approve the Acme MSA renewal"),
                _todo("b3", "approve the  Acme MSA renewal"),
                _todo("b4", "Reply to Daniel"),
            ]
        )

        await run_brief(_USER, BriefingKind.DAILY)

        payload = _stored_payload(world)
        items = [(it.text, it.todo_id, it.count) for s in payload.sections for it in s.items]
        assert items == [("Approve the Acme MSA renewal", "b1", 3), ("Reply to Daniel", "b4", 1)]
        facts = _facts_shown(_prompt(world))
        assert facts.count("Acme MSA renewal") == 1
        assert (
            "Approve the Acme MSA renewal | [[fact:1.count]] (3) todos on this one subject" in facts
        )
        assert "Reply to Daniel | 1 requests" not in facts
        assert (
            "[COUNTS] [[count:needs_you]] (2) · [[count:open_tracked]] (2) · [[count:events]] (1)\n"
            in facts
        )
        assert [(s.value, s.label) for s in payload.stats] == [("2", "waiting on you")]

    async def test_two_requests_for_one_subject_are_counted_as_two(self, world: World) -> None:
        world.work = TrackedWork(
            blocked=[
                _todo("b1", "Approve the Acme MSA renewal"),
                _todo("b2", "Approve the Acme MSA renewal"),
            ]
        )

        await run_brief(_USER, BriefingKind.DAILY)

        assert (
            "Approve the Acme MSA renewal | [[fact:1.count]] (2) todos on this one subject"
            in _facts_shown(_prompt(world))
        )

    async def test_subtasks_of_one_parent_are_one_item(self, world: World) -> None:
        world.work = TrackedWork(
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

        await run_brief(_USER, BriefingKind.DAILY)

        items = [(it.text, it.count) for s in _stored_payload(world).sections for it in s.items]
        assert items == [("Approve the Acme MSA", 2)]

    async def test_threads_the_inbox_desk_opened_are_one_item_each(self, world: World) -> None:
        world.work = TrackedWork(
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

        await run_brief(_USER, BriefingKind.DAILY)

        items = [(it.text, it.count) for s in _stored_payload(world).sections for it in s.items]
        assert items == [("Priya · pitch deck", 1), ("Arjun · contract", 1)]


def _brief_work() -> TrackedWork:
    return TrackedWork(
        blocked=[_todo("b1", "Approve the Priya reply")],
        completed=[_todo("c1", "Investor update")],
    )


class TestTheDailyRunWiring:
    """Every read is scoped to the user and the last local day, and every write records it."""

    async def test_the_producers_read_this_user_since_the_last_local_day(
        self, world: World
    ) -> None:
        world.held = [_held("h1", "Paper digest", _DIGEST_REPORT)]

        await run_brief(_USER, BriefingKind.DAILY)

        cast(
            "AsyncMock", approval_ledger_repository.list_pending_for_user
        ).assert_awaited_once_with(_USER)
        cast("AsyncMock", hil_approval_repository.list_pending_for_user).assert_awaited_once_with(
            _USER, _NOW
        )
        assert world.reads["list_since"].await_args.args == (_USER, _DAY_START)
        assert world.reads["find_latest_by_external_ref"].await_args.args[0] == _USER

    async def test_the_composition_is_asked_for_this_user(self, world: World) -> None:
        world.work = _brief_work()

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.composer.await_args.kwargs["config"] == {"configurable": {"user_id": _USER}}

    async def test_the_wide_event_counts_the_pool_the_composition_chose_from(
        self, world: World
    ) -> None:
        world.work = _brief_work()

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        assert event["brief_composition"]["pool_items"] == 3

    async def test_the_wide_event_records_where_the_brief_went(self, world: World) -> None:
        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        assert event["briefing"]["channels"] == [*_ORCHESTRATED, "telegram"]
        assert (event["briefing"]["pushed"], event["briefing"]["form"]) == (True, "edition")
        assert (event["briefing"]["kind"], event["briefing"]["outcome"]) == ("daily", "sent")

    async def test_an_email_wanted_and_not_sent_is_a_warning(self, world: World) -> None:
        world.notify.return_value = SimpleNamespace(
            channels=[
                _delivered("inapp"),
                ChannelDeliveryStatus(channel_type="email", status=NotificationStatus.FAILED),
            ]
        )

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        assert [w["msg"] for w in event["warnings"]].count("briefing.email_not_sent") == 1

    async def test_every_run_is_counted_by_kind_and_how_it_ended(self, world: World) -> None:
        def count(outcome: str) -> float:
            labels = {"kind": "daily", "outcome": outcome}
            return REGISTRY.get_sample_value("gaia_briefing_run_total", labels) or 0.0

        sent, failed = count("sent"), count("failed")
        await run_brief(_USER, BriefingKind.DAILY)
        world.briefs.clear()
        world.notify.side_effect = RuntimeError("orchestrator down")
        with pytest.raises(RuntimeError, match="orchestrator down"):
            await run_brief(_USER, BriefingKind.DAILY)

        assert (count("sent") - sent, count("failed") - failed) == (1.0, 1.0)

    @pytest.mark.parametrize(
        ("sent_days_ago", "since"),
        [
            # Friday's brief, read on Monday: the weekend is in the look-back.
            (3, _NOW - timedelta(days=3)),
            # Back after three weeks: the look-back stops at a week.
            (21, _DAY_START - timedelta(days=6)),
        ],
    )
    async def test_the_look_back_starts_at_the_last_brief_within_a_week(
        self, world: World, sent_days_ago: int, since: datetime
    ) -> None:
        sent = _NOW - timedelta(days=sent_days_ago)
        last = BriefingModel(
            user_id=_USER,
            date=sent.date().isoformat(),
            payload=BriefingPayload(
                kicker="K",
                date="d",
                headline="H",
                lede="L",
                mood=BriefingMood.CLEAR,
                caption="C",
                template_family=EditionFamily.SWISS,
            ),
            created_at=sent,
        )
        world.reads["get_before_date"].return_value = last

        await run_brief(_USER, BriefingKind.DAILY)

        world.reads["tracked_work"].assert_called_once_with(since)
        assert world.reads["format_lookback_block"].await_args.args[2] == Lookback(last, since)

    async def test_every_read_is_for_this_user_and_the_last_local_day(self, world: World) -> None:
        await run_brief(_USER, BriefingKind.DAILY)

        world.reads["stated_goals"].assert_awaited_once_with(_USER, world.user)
        world.reads["get_before_date"].assert_awaited_once_with(
            _USER, kind=BriefingKind.DAILY, before_date=_DATE
        )
        lookback = world.reads["format_lookback_block"].await_args.args
        assert (lookback[0], lookback[2]) == (_USER, Lookback(None, _DAY_START))
        # The look-back reads the run's own read of what got done: the user's Gym.
        assert [d.title for d in lookback[1].completed.docs] == ["Gym"]
        assert (lookback[3].date_str, lookback[3].tz.key) == (_DATE, _TZ)
        assert world.reads["compute_winback_state"].await_args.args[0].id == _USER
        world.reads["has_daily_briefing"].assert_awaited_once_with(_USER)
        world.reads["tracked_work"].assert_called_once_with(_DAY_START)
        assert world.reads["own_todos"].call_args.args[0].date_str == _DATE
        # One read of what got done, from the series window's first day (before the look-back).
        world.reads["list_completed_since"].assert_awaited_once_with(
            _USER, since=datetime(2026, 10, 7, 18, 30, tzinfo=UTC)
        )
        world.reads["list_for_user"].assert_awaited_once_with(_USER, sort=[("created_at", 1)])
        world.reads["format_replies_block"].assert_awaited_once_with(_USER, _DAY_START)
        world.reads["record_idle_day"].assert_awaited_once_with(
            _USER, wind_down.state_from_user(world.user), False, _DATE
        )
        prompt_args = world.voice_prompt.call_args.kwargs
        assert prompt_args["date_local"] == _DATE
        assert (
            prompt_args["blocks"].goal,
            prompt_args["blocks"].lookback,
            prompt_args["blocks"].replies,
        ) == ("Stated goal: Ship v2", "-", "No replies.")
        assert prompt_args["situation"] == VoiceSituation()

    async def test_the_pool_reads_this_users_week_ending_today(self, world: World) -> None:
        await run_brief(_USER, BriefingKind.DAILY)

        # Seven local days ending today: 8 Oct, Kolkata midnight, to the midnight after 14 Oct.
        week_start = datetime(2026, 10, 7, 18, 30, tzinfo=UTC)
        world.reads["fetch_calendar"].assert_awaited_once_with(
            _USER, week_start, datetime(2026, 10, 14, 18, 30, tzinfo=UTC)
        )
        world.reads["list_completed_since"].assert_awaited_once_with(_USER, since=week_start)
        world.reads["list_external_ref_activity_since"].assert_awaited_once_with(
            _USER, ExternalRefSource.GMAIL_THREAD, since=week_start
        )
        world.reads["list_run_moments_since"].assert_awaited_once_with(
            _USER, week_start, exclude_workflow_ids=[]
        )
        world.reads["verdicts_since"].assert_awaited_once_with(
            _USER, since=_NOW - timedelta(days=1)
        )

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

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.voice_prompt.call_args.kwargs["situation"].is_first_briefing is True

    async def test_the_voice_is_one_structured_call_metered_to_the_user(self, world: World) -> None:
        await run_brief(_USER, BriefingKind.DAILY)

        call = world.agent.await_args.kwargs
        assert call["schema"] is BriefVoice
        assert call["label"] == BRIEF_VOICE_LABEL
        assert call["config"] == metered_config(_USER)
        assert call["options"].schema_held
        assert world.agent.await_count == 1

    async def test_a_user_at_todays_usage_limit_still_gets_their_brief(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Live: a capped user's voice turn came back as the usage-limit stop text, and the brief failed."""
        capped_turn = AsyncMock(return_value=SimpleNamespace(message=DAILY_BUDGET_STOP_FREE))
        monkeypatch.setattr(agent_module, "call_agent_silent", capped_turn)
        world.work = _brief_work()

        await run_brief(_USER, BriefingKind.DAILY)

        capped_turn.assert_not_awaited()
        assert _stored_payload(world).headline == _VOICE["headline"]
        assert AIFeature.for_label(BRIEF_VOICE_LABEL) is AIFeature.BRIEFING

    async def test_the_brief_is_dated_and_stamped_in_the_users_timezone(self, world: World) -> None:
        world.work = _brief_work()

        await run_brief(_USER, BriefingKind.DAILY)

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
            ("1", "done since last brief"),
            ("1", "waiting on you"),
        ]

    async def test_a_zero_count_is_never_shown_to_the_model(self, world: World) -> None:
        world.work = TrackedWork(running=[_todo("r1", "Research")])

        await run_brief(_USER, BriefingKind.DAILY)

        assert (
            "[COUNTS] [[count:in_progress]] (1) · [[count:open_tracked]] (1) · [[count:events]] (1)\n"
            in _prompt(world)
        )

    async def test_delivery_opens_the_brief_and_posts_the_image_as_the_daily_brief(
        self, world: World
    ) -> None:
        world.work = _brief_work()

        await run_brief(_USER, BriefingKind.DAILY)

        payload = _stored_payload(world)
        assert [c.args[0] for c in world.render.await_args_list] == [payload]
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
        world.reads["list_completed_since"].return_value = [
            _todo("c1", "Investor update").model_copy(
                update={
                    "completed": True,
                    "completed_at": _NOW - timedelta(hours=1),
                    "completed_by": TodoCompleter.GAIA,
                }
            )
        ]
        _family_first(world, "memo")

        await run_brief(_USER, BriefingKind.DAILY)

        payload = _stored_payload(world)
        assert _delivered_to(world) == [*_ORCHESTRATED, "telegram"]
        world.capture.assert_called_once_with(
            UserId(_USER),
            BriefingSent(
                kind=BriefingKind.DAILY,
                form="edition",
                family=payload.template_family,
                mood=BriefingMood.PACKED,
                item_count=2,
                channel_count=3,
                signal_count=0,
                stamp_collected=payload.new_stamp is not None,
                block_kinds=["items", "items"],
                chart_count=0,
                pool_item_count=3,
                series_count=1,
                source_count=1,
            ),
        )

    async def test_a_block_the_drawn_edition_cannot_draw_moves_to_the_briefs_page(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.work = _brief_work()
        placed = _composed({"Waiting": ["Approve the Priya reply"]})

        def with_progress(
            schema: type[BriefComposition], prompt: str, **kw: object
        ) -> BriefComposition:
            base = placed(schema, prompt, **kw)
            return schema.model_validate(
                {
                    "blocks": [
                        *(b.model_dump() for b in base.blocks),
                        {"kind": "progress", "goal_id": "g1"},
                    ]
                }
            )

        world.composer.side_effect = with_progress
        monkeypatch.setattr(edition_draws, "families_drawing", lambda *_: set())
        _family_first(world, "menu")

        await run_brief(_USER, BriefingKind.DAILY)

        payload = _stored_payload(world)
        assert [b.kind for b in payload.undrawn] == ["progress"]
        assert [b.kind for b in payload.blocks] == ["items"]

    async def test_a_brief_its_only_edition_cannot_draw_is_still_sent(self, world: World) -> None:
        """Regression (#1804 review): with only Menu on, a progress-only brief drew nothing and was never pushed."""
        world.calendar = []
        world.work = _brief_work()
        world.user.briefing_editions = {
            family: EditionChoice.OFF for family in DAILY_FAMILY_WEIGHTS if family != "menu"
        }
        world.composer.side_effect = lambda schema, _prompt, **_k: schema.model_validate(
            {"blocks": [{"kind": "progress", "goal_id": "g1"}]}
        )

        await run_brief(_USER, BriefingKind.DAILY)

        payload = _stored_payload(world)
        assert (payload.template_family, payload.blocks) == ("menu", [])
        assert [b.kind for b in payload.undrawn] == ["progress"]
        world.post.assert_awaited_once()

    async def test_a_chart_in_the_brief_is_counted_among_its_blocks(self, world: World) -> None:
        world.work = _brief_work()
        world.reads["list_completed_since"].return_value = [
            _todo("c1", "Investor update").model_copy(
                update={
                    "completed": True,
                    "completed_at": _NOW - timedelta(hours=1),
                    "completed_by": TodoCompleter.GAIA,
                }
            )
        ]
        placed = _composed({"Waiting": ["Approve the Priya reply"]})

        def with_a_chart(
            schema: type[BriefComposition], prompt: str, **kw: object
        ) -> BriefComposition:
            base = placed(schema, prompt, **kw)
            chart = {
                "kind": "chart",
                "chart": "bar",
                "series_ids": ["gaia_finished"],
                "title": "Finished",
                "takeaway": "One thing done.",
            }
            return schema.model_validate(
                {"blocks": [*(b.model_dump() for b in base.blocks), chart]}
            )

        world.composer.side_effect = with_a_chart

        await run_brief(_USER, BriefingKind.DAILY)

        event = world.capture.call_args.args[1]
        assert (event.block_kinds, event.chart_count) == (["items", "chart"], 1)

    async def test_the_run_is_tagged_on_its_wide_event(self, world: World) -> None:
        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        assert (event["component"], event["operation"], event["user_id"]) == (
            "briefing",
            "run_brief",
            _USER,
        )

    @pytest.mark.parametrize("email", [None, "   "])
    async def test_email_is_left_out_without_an_address(
        self, world: World, email: str | None
    ) -> None:
        world.user = UserDocument(id=_USER, timezone=_TZ, email=email)

        await run_brief(_USER, BriefingKind.DAILY)

        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == ["inapp"]


class TestTheFactsTheModelVoices:
    """The facts block is the whole truth the model may voice, built by code."""

    async def test_counts_and_one_line_per_item_with_its_artifact(self, world: World) -> None:
        blocked = _todo("b1", "Approve the reply")
        blocked.canvas_content = "Draft ready"
        world.work = TrackedWork(
            blocked=[blocked],
            failed=[_todo("f1", "Sync"), _todo("f2", "Scrape")],
            completed=[_todo("c1", "Deck")],
            running=[_todo("r1", "Research"), _todo("r2", "Outreach")],
        )
        world.held = [_held("h1", "Digest", "first")]

        await run_brief(_USER, BriefingKind.DAILY)

        assert (
            "[COUNTS] [[count:needs_you]] (3) · [[count:done]] (1) · [[count:in_progress]] (2) · [[count:while_away]] (1) · [[count:open_tracked]] (5) · [[count:events]] (1)\n"
            "[Needs you]\n"
            "- fact 1 | Waiting on you: Approve the reply"
            " | artifact holds ~11 chars | waiting on you | linkable\n"
            "- fact 2 | Failed: Sync | artifact holds ~0 chars\n"
            "- fact 3 | Failed: Scrape | artifact holds ~0 chars\n"
            "[GAIA's work]\n"
            "- fact 4 | Note: Digest: first\n"
            "- fact 5 | Done by GAIA: Deck | artifact holds ~0 chars\n"
            "[Still running]\n"
            "- fact 6 | In progress: Research | artifact holds ~0 chars\n"
            "- fact 7 | In progress: Outreach | artifact holds ~0 chars\n"
            "The user has no todos of their own outside GAIA's tracked work, which holds "
            "[[count:open_tracked]] open: never call their todo list empty or clear.\n"
            "Today's calendar:\n"
            "- fact 8 | [[fact:8.time]] (11:00 AM): Sequoia"
        ) in _prompt(world)
        assert "No tracked work, results or app items need them today" not in _prompt(world)
        assert [(s.value, s.label) for s in _stored_payload(world).stats] == [
            ("1", "done since last brief"),
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
        world.work = TrackedWork(completed=[doc, cut])

        await run_brief(_USER, BriefingKind.DAILY)

        assert "| Done by GAIA: Deck | summary: First line Second line | artifact holds" in _prompt(
            world
        )
        assert f"| Done by GAIA: Long | summary: {'x' * 239}{ELLIPSIS} | artifact holds" in _prompt(
            world
        )

    async def test_the_size_hint_counts_the_deliverable_not_its_logs(self, world: World) -> None:
        doc = _todo("c1", "Pick a forum")
        doc.canvas_content = (
            "Intro line\n<!-- note -->\n\n## Result\nDecision made\n"
            "## Activity Log\nstep one\n\nstep two\n## timeline\nx"
        )
        world.work = TrackedWork(completed=[doc])

        await run_brief(_USER, BriefingKind.DAILY)

        assert "| artifact holds ~24 chars" in _prompt(world)

    async def test_a_todo_in_two_states_keeps_its_first_artifact(self, world: World) -> None:
        first, again, blocked = _todo("c1", "Deck"), _todo("c1", "Deck"), _todo("b1", "Reply")
        first.canvas_content, again.canvas_content, blocked.canvas_content = "One", "Two", "Three"
        world.work = TrackedWork(completed=[first], running=[again], blocked=[blocked])

        await run_brief(_USER, BriefingKind.DAILY)

        prompt = _prompt(world)
        assert (
            "- fact 2 | Done by GAIA: Deck | summary: One | artifact holds ~3 chars | linkable\n"
            in prompt
        )
        assert (
            "- fact 3 | In progress: Deck | summary: One | artifact holds ~3 chars | linkable\n"
            in prompt
        )
        assert "- fact 1 | Waiting on you: Reply | artifact holds ~5 chars | waiting" in prompt

    async def test_with_nothing_tracked_the_model_is_told_nothing_ran(self, world: World) -> None:
        await run_brief(_USER, BriefingKind.DAILY)

        assert (
            "[COUNTS] [[count:events]] (1)\n"
            "No tracked work, results or app items need them today. Do not claim anything ran, "
            "finished, or is pending beyond what is stated here.\n"
            "The user's own todo list is empty.\n"
            "Today's calendar:\n- fact 1 | [[fact:1.time]] (11:00 AM): Sequoia"
        ) in _prompt(world)

    async def test_the_users_own_todos_are_counted_never_listed(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seam(monkeypatch, world, BriefReads, "own_todos", _own_todos(2))

        await run_brief(_USER, BriefingKind.DAILY)

        assert "[COUNTS] [[count:open_todos]] (2) · [[count:events]] (1)\n" in _prompt(world)
        assert (
            "The user's own open todos are counted in [COUNTS]"
            "; never voice that list as clear or empty.\n"
        ) in _prompt(world)

    async def test_the_users_overdue_todos_are_counted_by_their_slot(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Replay: a heavy user's 70 overdue todos were never mentioned."""
        _seam(monkeypatch, world, BriefReads, "own_todos", _own_todos(200, 70))
        world.agent.return_value = _saying("[[count:overdue_todos]] of your todos are past due.")

        await run_brief(_USER, BriefingKind.DAILY)

        facts = _facts_shown(_prompt(world))
        assert "[[count:open_todos]] (200) · [[count:overdue_todos]] (70)" in facts
        assert "[[count:overdue_todos]] of them are past due" in facts
        assert (_stored_payload(world).message or "").endswith("70 of your todos are past due.")

    async def test_an_untimed_event_reads_all_day_and_none_reads_empty(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        offsite = BriefingEvent(date=_DATE, title="Offsite")
        world.calendar = [offsite, _EVENT]
        await run_brief(_USER, BriefingKind.DAILY)
        assert _facts_shown(_prompt(world)).endswith(
            "is empty.\nToday's calendar:\n"
            "- fact 1 | all day: Offsite\n- fact 2 | [[fact:2.time]] (11:00 AM): Sequoia"
        )

        world.calendar = []
        world.briefs.clear()
        await run_brief(_USER, BriefingKind.DAILY)
        assert _facts_shown(_prompt(world)).endswith(
            "is empty.\nThe user's calendar has nothing today."
        )

    async def test_with_no_calendar_connected_no_prompt_calls_the_calendar_empty(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: every brief for a user with no calendar said their calendar was empty."""
        world.calendar = CalendarGap.NOT_CONNECTED

        await run_brief(_USER, BriefingKind.DAILY)

        composed = world.composer.await_args.args[1]
        assert _facts_shown(_prompt(world)).endswith(f"is empty.\n{NO_CALENDAR_CONNECTED}")
        assert NO_CALENDAR_CONNECTED in composed
        assert "Nothing on the calendar" not in composed

    async def test_a_held_result_with_a_blank_report_shows_only_its_source(
        self, world: World
    ) -> None:
        world.held = [_held("h1", "Digest", "  \n ")]

        await run_brief(_USER, BriefingKind.DAILY)

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
        world.work = TrackedWork(completed=[deck], blocked=[reply])

    @staticmethod
    def _voice(world: World, message: str) -> None:
        world.agent.return_value = _wrote(f"{message}\nSequoia at [[fact:3.time]].")

    async def test_a_linked_item_gets_its_link_on_its_phrase_and_an_unlinked_one_is_never_minted(
        self, world: World
    ) -> None:
        # b1 (needs you) is fact 1, c1 (done) fact 2, Sequoia fact 3; only the reply is linked.
        self._voice(world, "the deck is done\n[the reply](fact:1) waits on you")

        await run_brief(_USER, BriefingKind.DAILY)

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

        await run_brief(_USER, BriefingKind.DAILY)

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

        await run_brief(_USER, BriefingKind.DAILY)

        payload = _stored_payload(world)
        assert payload.message == "the deck is done\nthe reply waits\nSequoia at 11:00 AM."
        assert all(it.link is None for sec in payload.sections for it in sec.items)

    async def test_a_resolved_link_is_markdown_on_its_phrase_in_the_chat_post(
        self, world: World
    ) -> None:
        self._voice(world, "[The shortlist is ready](fact:2)\n[the reply](fact:1) waits on you")

        await run_brief(_USER, BriefingKind.DAILY)

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

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.agent.await_count == 2
        retry = world.agent.await_args_list[1].kwargs["prompt"]
        assert named in retry
        assert _stored_payload(world).message == (
            f"[The shortlist is ready]({_todo_link('c1')})\n"
            f"[the reply]({_todo_link('b1')}) waits on you\nSequoia"
        )

    async def test_a_link_malformed_on_every_attempt_still_sends_a_plain_brief(
        self, world: World
    ) -> None:
        world.agent.side_effect = [
            _wrote(
                "[Book flights for the Berlin offsite|[[fact:2]]]\n[the reply](fact:1) waits on you"
            )
        ] * MAX_VOICE_ATTEMPTS

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        payload = _assert_sent_plainly(world)
        assert payload.message == "- Reply\n- Deck\n- Sequoia (11:00 AM)"
        assert "malformed slot" in _salvaged(event, "voice")[0]["problems"]

    async def test_an_item_with_nothing_to_open_is_not_linkable(self, world: World) -> None:
        deck = _todo("c1", "Deck")
        deck.canvas_content = "Ten slides"
        world.work = TrackedWork(failed=[_todo("f1", "Sync")], completed=[deck])
        self._voice(world, "the [sync](fact:1) failed\nthe [deck](fact:2) is done")

        await run_brief(_USER, BriefingKind.DAILY)

        assert "- fact 1 | Failed: Sync | artifact holds ~0 chars\n" in _prompt(world)
        assert (
            "- fact 2 | Done by GAIA: Deck | summary: Ten slides | artifact holds ~10 chars | linkable\n"
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

        await run_brief(_USER, BriefingKind.DAILY)

        request = world.notify.await_args.args[0]
        assert request.metadata["brief_url"] == f"https://app.test/brief/{_BRIEF_ID}"
        assert world.render.await_args.args[0].link == f"https://app.test/brief/{_BRIEF_ID}"
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
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[]))

    @pytest.mark.parametrize(
        "since", [_NOW - timedelta(days=1), (_NOW - timedelta(days=1)).replace(tzinfo=None)]
    )
    async def test_inside_the_grace_window_without_a_goal_nothing_is_sent(
        self, world: World, monkeypatch: pytest.MonkeyPatch, since: datetime
    ) -> None:
        self._pending(world, since)
        self._no_goal(monkeypatch, world)

        await run_brief(_USER, BriefingKind.DAILY)

        world.agent.assert_not_awaited()
        _assert_nothing_sent(world)

    @pytest.mark.parametrize("age", [timedelta(days=3), timedelta(days=4)])
    async def test_once_the_grace_window_has_passed_the_brief_goes_out(
        self, world: World, monkeypatch: pytest.MonkeyPatch, age: timedelta
    ) -> None:
        self._pending(world, _NOW - age)
        self._no_goal(monkeypatch, world)

        await run_brief(_USER, BriefingKind.DAILY)

        world.upsert.assert_awaited()
        world.clear_bootstrap.assert_awaited_once_with(_USER)

    async def test_a_known_goal_releases_the_hold_and_clears_it(self, world: World) -> None:
        self._pending(world, _NOW - timedelta(hours=1))

        await run_brief(_USER, BriefingKind.DAILY)

        world.upsert.assert_awaited()
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

        await run_brief(_USER, BriefingKind.DAILY)

        world.upsert.assert_awaited()

    async def test_a_user_never_held_has_nothing_to_clear(self, world: World) -> None:
        await run_brief(_USER, BriefingKind.DAILY)

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
    """Nothing to report escalates to a warning, then one goodbye, then wind_down."""

    async def test_a_dormant_user_who_came_back_is_woken_and_briefed(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _dormant(world)
        _seam(monkeypatch, world, wind_down, "latest_activity_since", AsyncMock(return_value=_NOW))

        await run_brief(_USER, BriefingKind.DAILY)

        (user_id, since), _ = world.reads["latest_activity_since"].await_args
        assert (user_id, since) == (_USER, _DORMANT_SINCE)
        world.clear_dormancy.assert_awaited_once_with(_USER)
        assert world.reads["record_idle_day"].await_args.args[1] == BriefingDormancy(
            idle_days=0, date=None, dormant_since=None
        )
        world.upsert.assert_awaited()

    async def test_a_woken_user_asked_for_a_goal_two_days_ago_is_not_asked_again(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _dormant(world)
        assert world.user.briefing_dormancy is not None
        world.user.briefing_dormancy.goal_asked_at = _NOW - timedelta(days=2)
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[]))
        _seam(monkeypatch, world, wind_down, "latest_activity_since", AsyncMock(return_value=_NOW))

        await run_brief(_USER, BriefingKind.DAILY)

        world.goal_asked.assert_not_awaited()
        assert world.voice_prompt.call_args.kwargs["situation"].goal_asked_recently is True

    @pytest.mark.parametrize(
        ("work", "held", "has_goal", "idle"),
        [
            (TrackedWork(), [], False, True),
            (_brief_work(), [], False, False),
            (TrackedWork(), [_held("h1", "Digest", "first")], False, False),
            (TrackedWork(), [], True, False),
        ],
    )
    async def test_a_day_is_idle_only_with_no_work_no_held_results_and_no_goal(
        self,
        world: World,
        monkeypatch: pytest.MonkeyPatch,
        work: TrackedWork,
        held: list[PendingBriefItemDocument],
        has_goal: bool,
        idle: bool,
    ) -> None:
        world.work, world.held = work, held
        _goals_seam(
            monkeypatch,
            world,
            AsyncMock(
                return_value=[StatedGoal("Ship v2", GoalOrigin.ONBOARDING)] if has_goal else []
            ),
        )

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.reads["record_idle_day"].await_args.args[2] is idle

    @pytest.mark.parametrize(
        ("asked_days_ago", "asks", "told_it_asked"),
        [(None, True, False), (2, False, True), (7, True, False)],
        ids=["never-asked", "asked-two-days-ago", "asked-a-week-ago"],
    )
    async def test_a_remembered_goal_is_asked_about_once_a_week_and_each_ask_is_recorded(
        self,
        world: World,
        monkeypatch: pytest.MonkeyPatch,
        asked_days_ago: int | None,
        asks: bool,
        told_it_asked: bool,
    ) -> None:
        asked_at = None if asked_days_ago is None else _NOW - timedelta(days=asked_days_ago)
        world.user = UserDocument(
            id=_USER,
            timezone=_TZ,
            email="a@b.c",
            briefing_dormancy=BriefingDormancy(goal_asked_at=asked_at),
        )
        goal = StatedGoal("Ship v2", GoalOrigin.ONBOARDING)
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[goal]))
        _seam(monkeypatch, world, wind_down, "latest_activity_since", AsyncMock(return_value=_NOW))

        await run_brief(_USER, BriefingKind.DAILY)

        situation = world.voice_prompt.call_args.kwargs["situation"]
        assert situation.goal_asked_recently is told_it_asked
        assert world.goal_asked.await_count == int(asks)
        assert world.reads["record_idle_day"].await_args.args[2] is False

    @pytest.mark.parametrize(
        ("asked_days_ago", "asks"),
        [(None, True), (2, False), (7, True)],
        ids=["never-asked", "asked-two-days-ago", "asked-a-week-ago"],
    )
    async def test_a_user_with_no_goal_is_asked_for_one_once_a_week(
        self,
        world: World,
        monkeypatch: pytest.MonkeyPatch,
        asked_days_ago: int | None,
        asks: bool,
    ) -> None:
        asked_at = None if asked_days_ago is None else _NOW - timedelta(days=asked_days_ago)
        world.user = UserDocument(
            id=_USER,
            timezone=_TZ,
            email="a@b.c",
            briefing_dormancy=BriefingDormancy(goal_asked_at=asked_at),
        )
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[]))

        await run_brief(_USER, BriefingKind.DAILY)

        situation = world.voice_prompt.call_args.kwargs["situation"]
        assert situation.goal_asked_recently is not asks
        assert world.goal_asked.await_count == int(asks)

    @pytest.mark.parametrize(("idle_days", "stage"), [(2, WindDown.WARN), (3, WindDown.FINAL)])
    async def test_the_idle_streak_sets_the_wind_down_and_the_goodbye_goes_dormant(
        self, world: World, monkeypatch: pytest.MonkeyPatch, idle_days: int, stage: str
    ) -> None:
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[]))
        _seam(monkeypatch, world, wind_down, "record_idle_day", AsyncMock(return_value=idle_days))

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.voice_prompt.call_args.kwargs["situation"].wind_down == stage
        if stage is WindDown.FINAL:
            world.enter_dormancy.assert_awaited_once_with(_USER)
        else:
            world.enter_dormancy.assert_not_awaited()

    async def test_the_wind_down_message_is_pushed_even_on_an_empty_day(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[]))
        _seam(monkeypatch, world, wind_down, "record_idle_day", AsyncMock(return_value=2))
        world.calendar = []

        await run_brief(_USER, BriefingKind.DAILY)

        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == _ORCHESTRATED
        world.post.assert_awaited_once()

    async def test_a_long_streak_with_work_to_report_does_not_wind_down(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seam(monkeypatch, world, wind_down, "record_idle_day", AsyncMock(return_value=5))

        await run_brief(_USER, BriefingKind.DAILY)

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
            daily,
            "compute_winback_state",
            AsyncMock(
                return_value=WinbackState(unacknowledged=WINBACK_THRESHOLD, last_was_winback=False)
            ),
        )
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[]))
        _seam(monkeypatch, world, wind_down, "record_idle_day", AsyncMock(return_value=idle_days))

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.voice_prompt.call_args.kwargs["situation"].winback is voiced_winback
        assert _stored_payload(world).mood == "winback"


def _idle_day(monkeypatch: pytest.MonkeyPatch, world: World, streak: int) -> None:
    """Make today a day with nothing to report, at the given idle streak."""
    _goals_seam(monkeypatch, world, AsyncMock(return_value=[]))
    _seam(monkeypatch, world, wind_down, "record_idle_day", AsyncMock(return_value=streak))


class TestTheFirstWeek:
    """A new account's first week helps it get value instead of winding down."""

    async def test_a_first_week_account_never_climbs_the_idle_ladder(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.user.created_at = _NOW - timedelta(days=FIRST_WEEK_DAYS, seconds=-1)
        _idle_day(monkeypatch, world, IDLE_DORMANT_DAYS)

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.reads["record_idle_day"].await_args.args[2] is False
        assert world.voice_prompt.call_args.kwargs["situation"].wind_down is None
        assert world.voice_prompt.call_args.kwargs["situation"].first_week is True
        world.enter_dormancy.assert_not_awaited()

    async def test_the_ladder_runs_once_the_first_week_is_over(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.user.created_at = _NOW - timedelta(days=FIRST_WEEK_DAYS)
        _idle_day(monkeypatch, world, IDLE_DORMANT_DAYS)

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.reads["record_idle_day"].await_args.args[2] is True
        assert world.voice_prompt.call_args.kwargs["situation"].wind_down is WindDown.FINAL
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

        await run_brief(_USER, BriefingKind.DAILY)

        assert "THEIR GAIA SETUP" in _prompt(world)
        assert line in _prompt(world)

    async def test_an_older_account_is_shown_no_setup(self, world: World) -> None:
        world.user.created_at = _NOW - timedelta(days=30)
        world.connected_apps = ["Gmail"]

        await run_brief(_USER, BriefingKind.DAILY)

        assert "THEIR GAIA SETUP" not in _prompt(world)


class TestTheLighterCadenceOffer:
    """A user who stopped coming back is offered fewer briefs, with their real cadence."""

    async def test_an_idle_user_is_offered_a_lighter_cadence(self, world: World) -> None:
        world.activity = ActivityStatus.IDLE
        world.user.briefing_schedule = BriefingSchedule(
            frequency=BriefingFrequency.WEEKDAYS, hour=9
        )

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.voice_prompt.call_args.kwargs["situation"].offer_lighter_cadence is True
        assert "a daily brief Monday to Friday at 09:00" in _prompt(world)
        assert "offer a lighter rhythm" in _prompt(world)

    async def test_a_first_week_idle_user_sees_their_cadence_and_apps_on_separate_lines(
        self, world: World
    ) -> None:
        world.activity = ActivityStatus.IDLE
        world.user.created_at = _NOW - timedelta(days=1)
        world.connected_apps = ["Gmail"]

        await run_brief(_USER, BriefingKind.DAILY)

        assert (
            "Their briefs now: a daily brief every day at 08:00, plus the weekly digest on "
            "Sunday at 17:00.\nApps they've connected: Gmail."
        ) in _prompt(world)

    async def test_an_active_user_is_not(self, world: World) -> None:
        await run_brief(_USER, BriefingKind.DAILY)

        assert world.voice_prompt.call_args.kwargs["situation"].offer_lighter_cadence is False
        assert "offer a lighter rhythm" not in _prompt(world)


_NOISE_BLOCKS = '```json\n\n```\n```json\n{oops\n```\n```json\n{"a": 1}\n```\n'


class TestTheAgentOutput:
    """The model's text must hold one valid JSON object; anything else fails loudly."""

    async def test_the_voice_is_found_past_empty_malformed_and_foreign_blocks(
        self, world: World
    ) -> None:
        world.agent.return_value = SimpleNamespace(message=_NOISE_BLOCKS + _fenced(_VOICE))

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).headline == "Your morning, sorted"

    async def test_a_missing_voice_names_why_without_echoing_the_reply(self, world: World) -> None:
        world.agent.return_value = SimpleNamespace(message="y" * 400)

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        (salvaged,) = _salvaged(event, "voice")
        assert salvaged["problems"] == "invalid JSON: Expecting value (char 0 of 400)"
        _assert_sent_plainly(world)

    async def test_a_lede_alone_typing_a_figure_is_sent_back_and_logged(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.calendar = []
        world.work = TrackedWork(completed=[_todo("c1", "Investor update")])
        world.agent.side_effect = [
            _voiced("The investor update is done", "You have 3 meetings."),
            _voiced("The investor update is done", "Nothing else today."),
        ]
        problem = "the lede types '3', a figure no fact carries; say it in words, from the facts, or leave it out"

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        assert world.agent.await_count == 2
        assert problem in world.agent.await_args_list[1].kwargs["prompt"]
        assert {
            "msg": "briefing.checked_call_rejected",
            "call": "voice",
            "problems": [problem],
        } in event["warnings"]


def _weekly_gaia() -> list[TodoDocument]:
    deck = _todo("g0", "Deck")
    deck.canvas_content = "# Deck\nFinal numbers in"
    return [deck, *[_todo(f"g{i}", f"G{i}") for i in range(1, 16)]]


def _weekly_completed() -> list[TodoDocument]:
    return _completions(_weekly_gaia(), [_own_done(f"u{i}", f"U{i}") for i in range(16)])


class TestTheWeeklyRunWiring:
    async def test_the_week_is_read_for_this_user_from_monday_in_one_window(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.reads["list_completed_since"].return_value = _weekly_completed()
        world.work = TrackedWork(completed=_weekly_gaia())
        _seam(
            monkeypatch,
            world,
            BriefReads,
            "tracked_work",
            MagicMock(side_effect=lambda *_: _with_open_subjects(world.work)),
        )
        world.agent.return_value = _weekly_voiced()
        world.composer.side_effect = _composed({"This week": ["Deck", "U15"]})

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.WEEKLY)

        week_call = world.week.call_args
        assert week_call.args[0].date_str == _DATE
        # The sections, the prose and the tallies read the same completions: one window for all.
        assert [d.id for d in week_call.args[1].docs] == [d.id for d in _weekly_completed()]
        assert _stored_payload(world).tallies == BriefingTallies(done_by_you=16, done_by_gaia=16)
        composed = world.composer.await_args.args[1]
        assert "[GAIA] done by GAIA: Deck" in composed
        assert "[GAIA] done by the user: U15" in composed
        # The week's series run Monday to today, the calendar's among them.
        assert (
            call(_USER, _WEEK_START, datetime(2026, 10, 21, 18, 30, tzinfo=UTC))
            in world.reads["fetch_calendar"].await_args_list
        )
        world.reads["list_completed_since"].assert_awaited_once_with(_USER, since=_WEEK_START)
        payload = _stored_payload(world)
        assert (payload.hue, payload.generated_at) == (79, "7:05 AM")
        assert (event["component"], event["operation"], event["user_id"]) == (
            "briefing",
            "run_brief",
            _USER,
        )
        assert (
            event["brief_composition"]["pool_items"],
            event["brief_composition"]["items"],
            event["brief_composition"]["uncomposed"],
        ) == (32, 2, 30)
        assert len(payload.uncomposed) == 30

    async def test_the_goals_composition_and_pool_are_the_users_and_the_weeks(
        self, world: World
    ) -> None:
        world.agent.return_value = _weekly_voiced()
        world.user.name = "Ada Lovelace"
        world.calendar = [_FRIDAY_PITCH]

        await run_brief(_USER, BriefingKind.WEEKLY)

        world.reads["stated_goals"].assert_awaited_once_with(_USER, world.user)
        assert world.reads["list_since"].await_args.args == (_USER, _WEEK_START)
        assert world.composer.await_args.kwargs["config"] == {"configurable": {"user_id": _USER}}
        composed = world.composer.await_args.args[1]
        assert f"Wed Oct 14, 2026, {_TZ}." in composed
        assert "Calendar in the week ahead: 1 event(s), every one listed below." in composed
        assert "Recent briefs opened on" not in composed
        blocks = world.weekly_prompt.call_args.kwargs["blocks"]
        assert blocks.goal == "Stated goal: Ship v2"
        assert "The user's own todo list is empty." in blocks.facts
        payload = _stored_payload(world)
        assert [b.kind for b in payload.blocks] == ["items"]
        assert payload.uncomposed == []

    async def test_a_user_without_a_name_or_timezone_is_read_to_as_the_unnamed_reader_on_utc(
        self, world: World
    ) -> None:
        world.agent.return_value = _weekly_voiced()
        world.user.name = None
        world.user.timezone = None

        await run_brief(_USER, BriefingKind.WEEKLY)

        composed = world.composer.await_args.args[1]
        assert "composing the user's weekly digest" in composed
        assert "Wed Oct 14, 2026, UTC." in composed

    async def test_the_voice_is_found_past_other_blocks(self, world: World) -> None:
        world.agent.return_value = SimpleNamespace(message=_NOISE_BLOCKS + _fenced(_WEEKLY_VOICE))

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert _stored_payload(world).headline == "A good week"

    async def test_a_recap_missing_from_the_output_on_every_attempt_fails_naming_why(
        self, world: World
    ) -> None:
        world.agent.return_value = SimpleNamespace(message="z" * 400)

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.WEEKLY)

        (salvaged,) = _salvaged(event, "voice")
        assert "invalid JSON: Expecting value (char 0 of 400)" in salvaged["problems"]
        assert world.agent.await_count == MAX_VOICE_ATTEMPTS
        _assert_sent_plainly(world)

    async def test_an_unknown_user_fails_loud(self, world: World) -> None:
        world.user = UserDocument(id="someone-else", timezone=_TZ)

        with pytest.raises(errors.BriefingGenerationError, match=f"unknown user {_USER}$"):
            await run_brief(_USER, BriefingKind.WEEKLY)

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
            wind_down,
            "latest_activity_since",
            AsyncMock(return_value=_NOW if came_back else None),
        )

        await run_brief(_USER, BriefingKind.WEEKLY)

        (user_id, since), _ = world.reads["latest_activity_since"].await_args
        assert (user_id, since) == (_USER, _DORMANT_SINCE)
        assert bool(world.upsert.await_count) is came_back

    async def test_a_stalled_agent_fails_the_run_instead_of_hanging(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def stall(**_: object) -> None:
            await asyncio.Event().wait()

        world.agent.side_effect = stall
        monkeypatch.setitem(
            KIND_SPECS,
            BriefingKind.WEEKLY,
            replace(KIND_SPECS[BriefingKind.WEEKLY], voice_timeout_seconds=0),
        )

        run = asyncio.ensure_future(run_brief(_USER, BriefingKind.WEEKLY))
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


class TestTheVoiceQuotesItsFacts:
    async def test_a_figure_from_a_facts_own_words_may_be_typed_in_the_prose(
        self, world: World
    ) -> None:
        """Live brief: the lede quoted Maya's "1x" preference and was refused on every attempt."""
        maya = _LOGIN.model_copy(
            update={
                "title": "Term sheet sign-off",
                "people": ["Maya Chen"],
                "text": "Can you confirm the 1x non-participating preference by Friday?",
            }
        )
        world.scouts = _scouted(maya)
        world.composer.side_effect = _composed({"Waiting on you": ["Term sheet sign-off"]})
        world.agent.return_value = SimpleNamespace(
            message=_fenced(
                {
                    **_VOICE,
                    "headline": "Maya needs an answer",
                    "lede": "Confirm the 1x preference.",
                    "message": "[Maya's sign-off](fact:<fact of Term sheet sign-off>), then [[fact:<fact of Sequoia>]].",
                }
            )
        )

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).lede == "Confirm the 1x preference."
        assert world.agent.await_count == 1

    async def test_a_figure_from_what_was_done_since_the_last_brief_may_be_typed(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """E2E busy day: the message named a closed thread from the look-back and was refused."""
        _seam(
            monkeypatch,
            world,
            daily,
            "format_lookback_block",
            AsyncMock(
                return_value="Actually completed since then:\n- GAIA finished: Q3 board memo"
            ),
        )
        world.agent.return_value = _voiced("A light morning", "The Q3 board memo went out.")

        await run_brief(_USER, BriefingKind.DAILY)

        assert _stored_payload(world).lede == "The Q3 board memo went out."
        assert world.agent.await_count == 1


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
        world.composer.side_effect = _composed(
            {"Needs you": [_LOGIN.title], "From your apps": [_DOCS.title]},
            reports=frozenset({_DOCS.title}),
        )
        world.agent.return_value = _saying("[the login redirect](fact:1) still needs you.")

        await run_brief(_USER, BriefingKind.DAILY)

        prompt = _prompt(world)
        assert (
            f"[ACROSS THEIR APPS] 2 item(s) shown from 1 app(s). {SHOWN_NOT_TOTAL}\n"
            "[Linear] 2 item(s) shown\n"
        ) in prompt
        assert (
            "- fact 1 | important | issue assigned to you: Fix the login redirect"
            " | state: In Progress | linkable | first seen 3 days ago, mentioned"
            " 1 time(s), last 2 days ago, moved from Todo to In Progress"
        ) in prompt
        assert "- fact 2 | other | issue assigned to you: Refresh the onboarding docs" in prompt
        assert "first seen today, created date unknown" in prompt
        assert (_stored_payload(world).message or "").endswith(
            f"[the login redirect]({_LOGIN.url}) still needs you."
        )

    async def test_a_day_with_only_signals_is_pushed_and_counted(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.calendar = []
        world.scouts = _scouted(_DOCS)
        world.agent.return_value = _saying(
            "[Refresh the docs](fact:<fact of Refresh>) when you can."
        )

        await run_brief(_USER, BriefingKind.DAILY)

        world.post.assert_awaited_once()
        assert world.capture.call_args.args[1].signal_count == 1

    async def test_every_signal_the_brief_placed_is_marked_shown_named_or_not(
        self, world: World
    ) -> None:
        """Regression: a signal placed in the edition but not named in the message came back as new."""
        world.scouts = _scouted(_LOGIN, _DOCS)
        world.composer.side_effect = _composed(
            {"Needs you": [_LOGIN.title], "From your apps": [_DOCS.title]},
            reports=frozenset({_DOCS.title}),
        )
        world.agent.return_value = _saying("[[fact:<fact of Fix the login>]] is yours today.")

        await run_brief(_USER, BriefingKind.DAILY)

        world.shown.assert_awaited_once_with(
            _USER,
            [
                Sighting("linear", _LOGIN.external_id, _LOGIN.state),
                Sighting("linear", _DOCS.external_id, _DOCS.state),
            ],
            _NOW,
        )
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

        await run_brief(_USER, BriefingKind.DAILY)

        payload = _stored_payload(world)
        assert [
            (s.title, [(i.text, i.app, i.kind, i.action or i.outcome) for i in s.items])
            for s in payload.sections
        ] == [
            (
                "Needs you",
                [
                    ("Send the invoice to Acme", "Gmail", "you", BriefAction.APPROVE),
                    ("CRM sync failed", "GAIA", "failed", BriefAction.RETRY),
                    ("Fix the login redirect", "Linear", "you", BriefAction.REPLY),
                ],
            ),
            (
                "From your apps",
                [("Stripe payout of 2,400 dollars landed", "Gmail", "note", BriefOutcome.FINISHED)],
            ),
        ]
        assert payload.sections[0].items[2].url == _LOGIN.url
        assert payload.sources_read == ["Gmail", "Linear", "Google Calendar"]
        assert [(u.app, u.reason) for u in payload.sources_unavailable] == [
            ("Notion", ScoutSkipReason.FAILED)
        ]
        event = world.capture.call_args.args[1]
        assert (event.block_kinds, event.item_count, event.pool_item_count, event.source_count) == (
            ["items", "items"],
            4,
            5,
            3,
        )
        world.consume.assert_awaited_once_with(_USER, ["h1"])
        # Everything placed is remembered as shown; the held finding is cleared instead.
        world.shown.assert_awaited_once_with(
            _USER,
            [
                Sighting("gaia", "approval:ap_1", "you"),
                Sighting("gaia", "workflow:wf-sync", "failed"),
                Sighting("linear", _LOGIN.external_id, _LOGIN.state),
            ],
            _NOW,
        )
