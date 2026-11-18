"""One brief run, daily or weekly, end to end through run_brief: what is stored, delivered and recorded.

Faked seams: the stores the run reads and writes, the model, the notification orchestrator, the
chat post and the edition render. The stand-in model answers from what the run built for it
(the fact pool it composes over, the facts the voice is held to), never from a prompt's words.
Each module's own rules (fact lines, slots, claims, the checked call, the quiet note's words,
sections) are proven beside that module; here, that the run wires them and how it ends.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
import re
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, call

from prometheus_client import REGISTRY
from pydantic import BaseModel, ValidationError
import pytest
from tests.factories import make_briefing_payload, make_todo, make_user_id
from tests.helpers import captured_wide_event
import time_machine

from app.agents.core import agent as agent_module
from app.agents.llm.client import metered_config
from app.agents.llm.exceptions import MalformedStructuredOutputError
from app.agents.prompts.brief_fact_prompts import UNNAMED_READER
from app.agents.prompts.briefing_prompts import (
    RecentLines,
    VoiceSituation,
    build_briefing_voice_prompt,
    build_weekly_voice_prompt,
)
from app.config.settings import settings
from app.constants.briefing import (
    BRIEF_VOICE_LABEL,
    FIRST_WEEK_DAYS,
    GAIA_APP_NAME,
    IDLE_DORMANT_DAYS,
    MAX_BRIEF_BLOCKS,
    MAX_VOICE_ATTEMPTS,
    PLAIN_BRIEF_HEADLINE,
    WEEKLY_KICKER,
    WINBACK_THRESHOLD,
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
    NotificationKind,
    ProactiveMessageClass,
)
from app.constants.todos import GAIA_TRACKED_LABEL, TodoCompleter
from app.constants.user_activity import ActivityStatus
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.briefing_state import briefing_state_repository
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
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import BriefComposition, SectionBlock
from app.models.brief_document_models import (
    BriefDelivery,
    BriefingModel,
    DeliveryStep,
    EditionRender,
)
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
    UnreadSource,
)
from app.models.brief_pool_models import GoalOrigin
from app.models.brief_settings_models import BriefingSchedule
from app.models.brief_slot_models import CountName
from app.models.brief_view_models import BriefNoteNotification
from app.models.briefing_state_models import (
    BriefingBootstrap,
    BriefingStateDocument,
    BriefingWindDown,
    ShuffleBag,
)
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
from app.models.short_link_models import RecordTarget, ShortLink, ShortLinkTargetType
from app.models.todo_models import ExternalRefSource, TodoDocument
from app.models.user_activity_models import UserActivityDates
from app.models.user_models import UserDocument
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
from app.services.briefing.clock import resolve_clock
from app.services.briefing.composition import headings as composition_headings
from app.services.briefing.composition.headings import HeadingVerdict, HeadingVerdicts
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.editions.artworks import artwork_weights
from app.services.briefing.fact_pool.pool import FactPool, build_fact_pool
from app.services.briefing.facts import WEEK_AHEAD, FactSources, build_facts
from app.services.briefing.goals import StatedGoal
from app.services.briefing.kinds import KIND_SPECS
from app.services.briefing.lookback import Lookback, WinbackState
from app.services.briefing.pipeline import run_brief
from app.services.briefing.prose import Writing, reader_block
from app.services.briefing.quiet_note import QuietFacts, quiet_note
from app.services.briefing.scouts import service as scout_service
from app.services.briefing.slots import BriefFact
from app.services.briefing.wind_down import latest_activity_since
from app.services.briefing.work import BriefReads, OpenSubjects, OwnTodos, TrackedWork
from app.services.cost_budget import DAILY_BUDGET_STOP_FREE
from app.services.delivery.chat_channel import ChatChannel, InApp
from app.services.notification_service import notification_service
from app.services.outbound_delivery import OutboundResult
from app.services.render.image import RenderedImage
from app.utils.message_breaks import split_message_bubbles
from app.workers.brief_slots import slot_minute
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingSent

# The run reads and writes Redis (scout refresh claims, spend); give it a per-test one.
pytestmark = pytest.mark.usefixtures("fake_redis")

_USER = make_user_id()
_SLOT_MINUTE = f"{slot_minute(_USER):02d}"
_TZ = "Asia/Kolkata"
# 07:05 on 14 Oct in Kolkata; the brief's day starts at local midnight.
_NOW = datetime(2026, 10, 14, 1, 35, tzinfo=UTC)
_DATE = "2026-10-14"
_DAY_START = datetime(2026, 10, 12, 18, 30, tzinfo=UTC)
# Monday 12 Oct, local midnight: the weekly digest counts from the start of the week.
_WEEK_START = datetime(2026, 10, 11, 18, 30, tzinfo=UTC)
_TODAY_START = datetime(2026, 10, 13, 18, 30, tzinfo=UTC)
# The week ahead runs seven local days from tomorrow; what falls due in it is the weekly's.
_WEEK_AHEAD_END = _TODAY_START + timedelta(days=8)
_EVENT = BriefingEvent(date="2026-10-14", start="11:00", title="Sequoia")
_FRIDAY_PITCH = BriefingEvent(date="2026-10-16", start="15:00", title="Pitch to Accel")
_CHAT = ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-1", basis="priority")
_RENDERED = RenderedImage(image=b"edition-png", fold=0.3, paper=(0.1, 0.2, 0.9, 0.8))
_BRIEF_ID = "brief_abc123"
_EDITION_KEY = "edition0key0of0the0brief0abc0123"
_EDITION_URL = f"{settings.HOST}/api/v1/briefings/editions/{_EDITION_KEY}/png?t="
_CHAT_EDITION_URL = f"{settings.HOST}/api/v1/briefings/editions/{_EDITION_KEY}/jpg?t="
_BRIEF_LINK = f"{settings.SHORTLINK_BASE_URL}/briefabc123"
_ORCHESTRATED = ["inapp", "email"]
_DIGEST_REPORT = "3 new papers on retrieval\nThe longest is 40 pages; two cite your draft."
#: When the default world's completions were finished: inside every window a run reads.
_JUST_NOW = _NOW - timedelta(hours=1)
_DORMANT_SINCE = datetime(2026, 10, 1, tzinfo=UTC)
#: The real activity read, which the world fixture stands in for.
_LATEST_ACTIVITY_SINCE = latest_activity_since

# ---- The stand-in model ------------------------------------------------------------------

#: In a scripted voice field, one title slot per fact the voice is held to, in their order.
_EVERY_FACT = "<every fact>"
#: In a scripted voice field, the id of the fact whose title holds TITLE.
_FACT_OF = re.compile(r"<fact of ([^>]+)>")

_VOICE: dict[str, str] = {
    "headline": "Your morning, sorted",
    "lede": "Everything else is moving.",
    "caption": "Onward.",
    "mood": "packed",
    "message": _EVERY_FACT,
}
_WEEKLY_VOICE: dict[str, str] = {
    "headline": "A good week",
    "lede": "The deck went out and the CRM sync needs a look.",
    "caption": "Same time next week.",
    "mood": "weekly",
    "message": _EVERY_FACT,
}

#: A scripted answer of the voice: its fields, or the error its structured call raises.
Reply = dict[str, str] | Exception


def _fact_id(writing: Writing, title: str) -> int:
    found = [n for n, fact in writing.values.facts.items() if title in fact.title]
    assert found, f"no fact the voice was shown is titled {title!r}"
    return found[0]


def _filled(writing: Writing, text: str) -> str:
    """Fill a scripted field's tokens from the facts the voice is held to."""
    text = _FACT_OF.sub(lambda m: str(_fact_id(writing, m.group(1))), text)
    every = "\n".join(f"[[fact:{n}]]" for n in writing.values.facts) or "A quiet day."
    return text.replace(_EVERY_FACT, every)


def _wrote(message: str, **fields: str) -> dict[str, str]:
    return {**_VOICE, "message": message, **fields}


def _weekly(**fields: str) -> dict[str, str]:
    return {**_WEEKLY_VOICE, **fields}


def _placed(item_id: int, item: BriefCandidate, *, asks: bool | None = None) -> dict[str, object]:
    """Word an item as a composer would: its own title, on its ask's or its report's side."""
    asking = item.state.needs_you if asks is None else asks
    side: dict[str, BriefAction | BriefOutcome] = (
        {"action": item.action or BriefAction.REPLY}
        if asking
        else {"outcome": item.outcome or BriefOutcome.FINISHED}
    )
    return {
        "id": item_id,
        "title": item.title,
        "action": None,
        "outcome": None,
        "detail": None,
    } | side


def _group_state(items: list[dict[str, object]]) -> str:
    """Name the state a group of placed items is in: its asks, its running work, else done."""
    if all(i["action"] is not None for i in items):
        return "needs_you"
    return "in_progress" if all(i["outcome"] == BriefOutcome.STARTED for i in items) else "done"


def _items_block(heading: str, items: list[dict[str, object]]) -> dict[str, object]:
    return {"kind": "items", "state": _group_state(items), "heading": heading, "items": items}


def _composes_by_state(
    schema: type[BriefComposition], _prompt: str, *, pool: FactPool, **_: object
) -> BriefComposition:
    """Stand in for the composer: what asks, then GAIA's work done, then running, then the apps'."""
    groups: dict[str, list[dict[str, object]]] = {
        "Needs you": [],
        "GAIA's work": [],
        "Still running": [],
        "From your apps": [],
    }
    for item_id, item in pool.items.items():
        if item.is_event:
            continue
        placed = _placed(item_id, item)
        if item.state.needs_you:
            heading = "Needs you"
        elif placed["outcome"] == BriefOutcome.STARTED:
            heading = "Still running"
        else:
            heading = "GAIA's work" if item.app == GAIA_APP_NAME else "From your apps"
        groups[heading].append(placed)
    return schema.model_validate(
        {"blocks": [_items_block(h, items) for h, items in groups.items() if items]}
    )


def _composed(
    groups: dict[str, list[str]],
    *,
    lead: tuple[str, str] | None = None,
    reports: frozenset[str] = frozenset(),
) -> Callable[..., BriefComposition]:
    """Stand in for a composer that places pool items by title under each heading, the lead first.

    reports are titles placed as reports (with an outcome) whatever their state.
    """

    def answer(
        schema: type[BriefComposition], _prompt: str, *, pool: FactPool, **_: object
    ) -> BriefComposition:
        by_title = {item.title: (n, item) for n, item in pool.items.items()}

        def placed(title: str) -> dict[str, object]:
            item_id, item = by_title[title]
            return _placed(item_id, item, asks=False if title in reports else None)

        blocks: list[dict[str, object]] = []
        if lead is not None:
            title, offer = lead
            blocks.append({"kind": "lead", "item": placed(title), "offer": offer})
        blocks += [_items_block(h, [placed(t) for t in titles]) for h, titles in groups.items()]
        return schema.model_validate({"blocks": blocks})

    return answer


def _with_block(
    composer: Callable[..., BriefComposition], block: dict[str, object]
) -> Callable[..., BriefComposition]:
    """Stand in for composer, adding block after what it placed."""

    def answer(schema: type[BriefComposition], prompt: str, **kw: object) -> BriefComposition:
        placed = [b.model_dump() for b in composer(schema, prompt, **kw).blocks]
        return schema.model_validate({"blocks": [*placed, block]})

    return answer


_CHART: dict[str, object] = {
    "kind": "chart",
    "chart": "bar",
    "series_ids": ["gaia_finished"],
    "title": "Finished",
    "takeaway": "One thing done.",
}
_PROGRESS: dict[str, object] = {"kind": "progress", "goal_id": "g1"}


def _every_heading_fits(
    schema: type[HeadingVerdicts], _prompt: str, **_: object
) -> HeadingVerdicts:
    """Stand in for the heading check: every group, whatever its number, fits its heading."""
    return schema(
        verdicts=[
            HeadingVerdict(block=n, fits=True, misfits=[], why="fits")
            for n in range(1, MAX_BRIEF_BLOCKS + 1)
        ]
    )


# ---- The world the run reads and writes ---------------------------------------------------


def _tracked(todo_id: str, title: str, **fields: Any) -> TodoDocument:
    """Return one of GAIA's tracked todos for the user."""
    return make_todo(title, GAIA_TRACKED_LABEL, id=todo_id, user_id=_USER, **fields)


def _brief_work() -> TrackedWork:
    return TrackedWork(
        blocked=[_tracked("b1", "Approve the Priya reply")],
        completed=[_tracked("c1", "Investor update")],
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


def _skipped(app: str, reason: ScoutSkipReason = ScoutSkipReason.FAILED) -> ScoutResult:
    return ScoutResult(
        integration_id=app.lower(), app=app, outcome=ScoutOutcome.SKIPPED, skip_reason=reason
    )


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


def _brief(
    day: str, form: BriefForm, kind: BriefingKind = BriefingKind.DAILY, **payload: Any
) -> BriefingModel:
    return BriefingModel(
        id=f"b-{day}-{kind}",
        user_id=_USER,
        date=day,
        kind=kind,
        payload=make_briefing_payload(date=day, form=form, **payload),
    )


@dataclass
class World:
    """Every seam the run touches, with a happy-path default, and what the run built for the model."""

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
    clear_wind_down: AsyncMock = field(default_factory=AsyncMock)
    enter_wind_down: AsyncMock = field(default_factory=AsyncMock)
    goal_asked: AsyncMock = field(default_factory=AsyncMock)
    activity: ActivityStatus = ActivityStatus.ACTIVE
    connected_apps: list[str] = field(default_factory=list)
    bags: dict[str, ShuffleBag] = field(default_factory=dict)
    work: TrackedWork = field(default_factory=TrackedWork)
    held: list[PendingBriefItemDocument] = field(default_factory=list)
    user: UserDocument = field(
        default_factory=lambda: UserDocument(id=_USER, timezone=_TZ, email="a@b.c", name="Ada")
    )
    #: The user's briefing_state row; its shuffle bags are bags, as the run stored them.
    state: BriefingStateDocument = field(
        default_factory=lambda: BriefingStateDocument(user_id=_USER)
    )
    chat: ChatChannel | None = _CHAT
    scouts: list[ScoutResult] = field(default_factory=list)
    memory: list[SignalMemoryDocument] = field(default_factory=list)
    shown: AsyncMock = field(default_factory=AsyncMock)
    seen: AsyncMock = field(default_factory=AsyncMock)
    brief_message: AsyncMock = field(default_factory=AsyncMock)
    #: The context and repository reads the run makes, by name, as patched.
    reads: dict[str, AsyncMock] = field(default_factory=dict)
    #: The composition model, answering from the pool; by default it groups every item by state.
    composer: AsyncMock = field(default_factory=lambda: AsyncMock(side_effect=_composes_by_state))
    #: The voice's answers in order, the last one repeated: fields, or the error the call raises.
    replies: list[Reply] = field(default_factory=lambda: [_VOICE])
    #: The voice model, answering replies from the facts it is held to.
    voice: AsyncMock = field(default_factory=AsyncMock)
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
    #: What the run built: the fact pool, the facts' sources, the voice's writing, its signals.
    pool: FactPool | None = None
    fact_sources: FactSources | None = None
    writing: Writing | None = None
    signals: list[tuple[int, BriefCandidate]] = field(default_factory=list)

    def fact(self, title: str) -> BriefFact:
        """Return the fact titled title that the voice was held to."""
        assert self.writing is not None, "the voice was never asked"
        return self.writing.values.facts[_fact_id(self.writing, title)]

    def stored(self) -> BriefingPayload:
        self.upsert.assert_awaited()
        return self.upsert.await_args.args[0].payload

    def delivered_to(self, kind: BriefingKind = BriefingKind.DAILY) -> list[str]:
        """Return the channels the stored brief of kind reached, once its delivery completed."""
        [brief] = [b for b in self.briefs.values() if b.kind == kind]
        assert brief.delivery is not None and brief.delivery.completed_at is not None
        return brief.delivered_channels

    def sent_plainly(self) -> BriefingPayload:
        """Assert the brief still went out, voiced plainly from its facts: never nothing."""
        payload = self.stored()
        assert payload.headline == PLAIN_BRIEF_HEADLINE
        self.notify.assert_awaited()
        return payload

    def nothing_sent(self) -> None:
        self.upsert.assert_not_awaited()
        self.notify.assert_not_awaited()
        self.post.assert_not_awaited()
        self.consume.assert_not_awaited()

    def family_first(self, family: EditionFamily) -> None:
        """Pin today's edition family: the default draw is random, and Air Mail adds a stamp line."""
        order = [f for f, n in DAILY_FAMILY_WEIGHTS.items() for _ in range(n)]
        order.remove(family)
        self.bags["edition_family"] = ShuffleBag(order=[family, *order], index=0)

    def briefs_read(self, briefs: list[BriefingModel]) -> None:
        """Have list_recent read these briefs, newest first: every kind, or the drawn ones alone."""
        self.recent.side_effect = lambda user_id, *, limit, editions_only=False, **_k: [
            b
            for b in briefs
            if user_id == _USER and (not editions_only or b.payload.form is BriefForm.EDITION)
        ][:limit]


def _seam(
    monkeypatch: pytest.MonkeyPatch, w: World, owner: object, name: str, mock: AsyncMock
) -> None:
    monkeypatch.setattr(owner, name, mock)
    w.reads[name] = mock


def _goals_seam(monkeypatch: pytest.MonkeyPatch, w: World, read: AsyncMock) -> None:
    """Have both kinds read the user's goals from read."""
    _seam(monkeypatch, w, daily, "stated_goals", read)
    monkeypatch.setattr(weekly, "stated_goals", read)


def _model(w: World) -> Callable[..., Awaitable[BaseModel]]:
    """Stand in for every checked structured call: the voice answers its schema, the composer the rest."""

    async def structured(schema: type[BaseModel], prompt: str, **kwargs: Any) -> BaseModel:
        if schema is BriefVoice:
            return await w.voice(schema, prompt, **kwargs)
        assert w.pool is not None, "composed before the pool was built"
        return await w.composer(schema, prompt, pool=w.pool, **kwargs)

    return structured


def _speaks(w: World) -> Callable[..., Awaitable[BriefVoice]]:
    """Answer the voice's call with the next scripted reply, its tokens filled from the writing."""

    async def voice(schema: type[BriefVoice], _prompt: str, **_: object) -> BriefVoice:
        reply = w.replies.pop(0) if len(w.replies) > 1 else w.replies[0]
        if isinstance(reply, Exception):
            raise reply
        assert w.writing is not None, "voiced before the writing was set"
        fields = {k: v if k == "mood" else _filled(w.writing, v) for k, v in reply.items()}
        try:
            return schema.model_validate(fields)
        except ValidationError as exc:
            raise MalformedStructuredOutputError(f"BriefVoice: {exc}") from exc

    return voice


def _records_what_the_run_built(monkeypatch: pytest.MonkeyPatch, w: World) -> None:
    """Record, on its way through, the pool, the facts' sources, the writing and the signals voiced."""

    async def pooled(*args: Any) -> FactPool:
        w.pool = await build_fact_pool(*args)
        return w.pool

    def facts(chosen: Any, sources: FactSources, clock: Any) -> Any:
        w.fact_sources = sources
        w.signals = [(i, c) for picked in chosen.picked for i, c in picked if c.signal is not None]
        return build_facts(chosen, sources, clock)

    async def written(user_id: str, prompt: str, writing: Writing) -> tuple[BriefVoice, BriefVoice]:
        w.writing = writing
        return await prose.written_brief(user_id, prompt, writing)

    monkeypatch.setattr(pipeline, "build_fact_pool", pooled)
    monkeypatch.setattr(pipeline, "build_facts", facts)
    monkeypatch.setattr(pipeline, "written_brief", written)


def _attached(
    mint: AsyncMock,
) -> Callable[[str, RecordTarget], Awaitable[ShortLink | None]]:
    """Attach the link whose URL mint names, so a test states links as the URLs they become."""

    async def attach(user_id: str, target: RecordTarget) -> ShortLink | None:
        url = await mint(user_id, target.type, target.id)
        if url is None:
            return None
        slug = url.removeprefix(f"{settings.SHORTLINK_BASE_URL}/")
        return ShortLink(slug=slug, user_id=user_id, target=target)

    return attach


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
        brief = w.briefs[briefing_id]
        assert brief.user_id == user_id and brief.delivery is not None
        delivery = brief.delivery
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


def _patch_context_reads(monkeypatch: pytest.MonkeyPatch, w: World) -> None:
    """Patch what the run gathers its context from (work, goals, wind_down, apps) and the scouts."""
    _seam(monkeypatch, w, chat_sync, "format_replies_block", AsyncMock(return_value="No replies."))
    _goals_seam(
        monkeypatch, w, AsyncMock(return_value=[StatedGoal("Ship v2", GoalOrigin.ONBOARDING)])
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


def _store_briefing_state(monkeypatch: pytest.MonkeyPatch, w: World) -> None:
    """Keep the user's briefing_state row in memory; its shuffle bags are w.bags, as Mongo holds them."""

    async def state_for(user_id: str) -> BriefingStateDocument:
        assert user_id == _USER
        w.state.shuffle_bags = {BriefingBag(k): v for k, v in w.bags.items()}
        return w.state

    async def set_bag(user_id: str, bag: BriefingBag, state: ShuffleBag) -> None:
        assert user_id == _USER
        w.bags[bag.value] = state

    monkeypatch.setattr(briefing_state_repository, "state_for", state_for)
    monkeypatch.setattr(briefing_state_repository, "clear_bootstrap", w.clear_bootstrap)
    monkeypatch.setattr(briefing_state_repository, "clear_wind_down", w.clear_wind_down)
    monkeypatch.setattr(briefing_state_repository, "enter_wind_down", w.enter_wind_down)
    monkeypatch.setattr(briefing_state_repository, "record_goal_question", w.goal_asked)
    monkeypatch.setattr(briefing_state_repository, "set_bag", set_bag)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    w = World(
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
    w.voice.side_effect = _speaks(w)

    # Seams keyed on the user: a read for anyone else finds nothing.
    async def get_user(user_id: str) -> UserDocument | None:
        return w.user if user_id == w.user.id else None

    monkeypatch.setattr(user_repository, "get", AsyncMock(side_effect=get_user))
    _store_briefs(monkeypatch, w)
    _store_briefing_state(monkeypatch, w)
    _records_what_the_run_built(monkeypatch, w)
    monkeypatch.setattr(daily, "build_briefing_voice_prompt", w.voice_prompt)
    monkeypatch.setattr(weekly, "build_weekly_voice_prompt", w.weekly_prompt)
    monkeypatch.setattr(checked_call, "ainvoke_structured", _model(w))
    monkeypatch.setattr(composition_headings, "ainvoke_structured", w.headings)
    monkeypatch.setattr(briefing_repository, "list_recent", w.recent)
    monkeypatch.setattr(briefing_repository, "list_stamped", w.stamped)
    monkeypatch.setattr(briefing_repository, "briefing_id_for", AsyncMock(return_value=_BRIEF_ID))
    monkeypatch.setattr(prose, "attach_link", _attached(w.mint))
    monkeypatch.setattr(store, "attach_link", _attached(w.mint))
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
        user=[make_todo("Gym", id="u1", user_id=_USER)]
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


def _salvaged(event: dict[str, Any], call: str) -> list[dict[str, Any]]:
    """Return the run's salvages of one checked call: voice or composition."""
    return [
        e
        for e in event["errors"]
        if e["msg"] == "briefing.checked_call_salvaged" and e["call"] == call
    ]


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


def _a_full_week(monkeypatch: pytest.MonkeyPatch, world: World) -> None:
    """Fill every weekly source: GAIA's and the user's work, a failed run and an event ahead."""
    _failed_run(monkeypatch, world)
    deck = _tracked("g1", "Investor deck", canvas_content="# Deck\nFinal numbers in")
    world.reads["list_completed_since"].return_value = _completions(
        [deck], [make_todo("Send the deck", id="u1", user_id=_USER)]
    )
    # GAIA's tracked work finished this week is the daily's own read, from Monday.
    world.work = TrackedWork(completed=[deck])
    world.calendar = [_FRIDAY_PITCH]
    world.week.return_value = BriefingWeek(
        days=[BriefingWeekDay(you=1, gaia=2)] * 7, ahead=[_FRIDAY_PITCH]
    )


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


def _remembered(external_id: str, last_state: str) -> SignalMemoryDocument:
    return SignalMemoryDocument(
        user_id=_USER,
        integration_id="linear",
        external_id=external_id,
        first_seen=_NOW - timedelta(days=3),
        times_shown=1,
        last_shown=_NOW - timedelta(days=2),
        last_state=last_state,
    )


def _winback(monkeypatch: pytest.MonkeyPatch, world: World) -> None:
    _seam(
        monkeypatch,
        world,
        daily,
        "compute_winback_state",
        AsyncMock(
            return_value=WinbackState(unacknowledged=WINBACK_THRESHOLD, last_was_winback=False)
        ),
    )


# ---- The daily brief ----------------------------------------------------------------------


class TestADailyBrief:
    async def test_it_is_stored_then_delivered_in_app_by_email_and_as_a_chat_image(
        self, world: World
    ) -> None:
        world.work = _brief_work()
        world.family_first(EditionFamily.MEMO)

        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        payload = world.stored()
        assert payload.headline == "Your morning, sorted"
        assert (payload.template_family, payload.stamp_city, payload.artwork_id) == (
            "memo",
            None,
            None,
        )
        assert "stamp_city" not in world.bags and "artwork" not in world.bags
        assert payload.calendar == [_EVENT]
        assert payload.tallies == BriefingTallies(done_by_you=1, done_by_gaia=0)
        assert world.fact("Sequoia").time == "11:00 AM"
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
        assert request.details.card.edition.image_url.startswith(_EDITION_URL)
        # One URL, minted before the render: the edition's codes, the email image and the chat post.
        world.mint.assert_awaited_with(_USER, ShortLinkTargetType.BRIEFING, _BRIEF_ID)
        assert world.render.await_args.args[0].link == _BRIEF_LINK
        assert request.details.brief_url == _BRIEF_LINK
        assert request.content.actions[0].config.redirect.url == f"/brief/{_BRIEF_ID}"
        assert [c.channel_type for c in request.channels] == _ORCHESTRATED
        assert request.details.kind == NotificationKind.BRIEFING_DAILY
        # GAIA's Briefings-conversation message carries the same folded card the notification does.
        user_id, text, card = world.brief_message.await_args.args
        assert (user_id, text, card.briefing_id, card.kind) == (_USER, message, _BRIEF_ID, "daily")
        assert card.needs_you_count == 1
        assert card.edition is not None and card.edition.image_url.startswith(_EDITION_URL)
        assert request.details.card == card
        assert request.content.body == message
        assert request.content.rich_content is None
        world.render.assert_awaited_once()
        post = world.post.await_args.kwargs
        assert post["channel"] == _CHAT
        assert post["image"].url.startswith(_CHAT_EDITION_URL)
        assert split_message_bubbles(post["text"]) == [
            "Your morning, sorted",
            f"{message}\n\nFull brief: {_BRIEF_LINK}",
        ]
        assert world.delivered_to() == [*_ORCHESTRATED, "telegram"]

    async def test_without_a_chat_platform_nothing_is_posted(self, world: World) -> None:
        world.chat = None

        await run_brief(_USER, BriefingKind.DAILY)

        world.render.assert_awaited_once()
        world.post.assert_not_awaited()
        assert world.delivered_to() == _ORCHESTRATED

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

        assert world.stored().recipient_name == "Ada"
        assert world.voice_prompt.call_args.kwargs["blocks"].reader == reader_block(world.user)

    async def test_a_user_who_gave_no_name_is_addressed_by_none(self, world: World) -> None:
        """Regression: the brief greeted "Dear Delivered", a name guessed from delivered+dev@resend.dev."""
        world.user = UserDocument(id=_USER, timezone=_TZ, email="delivered+dev@resend.dev")

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.stored().recipient_name is None
        assert world.pool is not None and world.pool.context.reader == UNNAMED_READER
        assert "Delivered" not in world.voice.await_args.args[1]

    async def test_the_pool_is_composed_for_the_reader_on_their_day_beside_recent_openings(
        self, world: World
    ) -> None:
        world.recent.return_value = [
            _brief("2026-10-13", BriefForm.EDITION, message="Priya replied overnight.")
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.pool is not None
        context = world.pool.context
        assert (context.reader, context.clock.date_str, str(context.clock.tz)) == (
            "Ada",
            _DATE,
            _TZ,
        )
        assert (context.calendar, context.calendar_span) == (1, "today")
        assert context.recent_openings == ["Priya replied overnight."]

    @pytest.mark.parametrize("kind", [BriefingKind.DAILY, BriefingKind.WEEKLY])
    async def test_a_user_with_no_name_or_timezone_is_composed_for_as_the_user_in_utc(
        self, world: World, kind: BriefingKind
    ) -> None:
        world.replies = [_weekly() if kind is BriefingKind.WEEKLY else _VOICE]
        world.user = UserDocument(id=_USER, email="delivered+dev@resend.dev")

        await run_brief(_USER, kind)

        assert world.pool is not None
        context = world.pool.context
        assert (context.reader, context.clock.date_str, str(context.clock.tz)) == (
            UNNAMED_READER,
            _DATE,
            "UTC",
        )

    async def test_an_empty_day_stays_in_app_and_spends_no_draw(self, world: World) -> None:
        """Nothing needs the user, nothing is on the calendar, nothing ran overnight."""
        bags_before = dict(world.bags)
        world.calendar = []

        await run_brief(_USER, BriefingKind.DAILY)

        payload = world.stored()
        assert payload.sections == [] and payload.calendar == []
        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == ["inapp"]
        world.post.assert_not_awaited()
        assert world.bags == bags_before

    async def test_the_brief_is_dated_and_stamped_in_the_users_timezone(self, world: World) -> None:
        world.work = _brief_work()

        await run_brief(_USER, BriefingKind.DAILY)

        payload = world.stored()
        assert (payload.kicker, payload.date, payload.generated_at) == (
            "THE MORNING BRIEF",
            _DATE,
            "7:05 AM",
        )
        assert (payload.hue, payload.mood, payload.caption) == (79, "packed", "Onward.")
        assert [(s.value, s.label) for s in payload.stats] == [
            ("1", "done since last brief"),
            ("1", "waiting on you"),
        ]

    async def test_delivery_opens_the_brief_and_posts_the_image_as_the_daily_brief(
        self, world: World
    ) -> None:
        world.work = _brief_work()

        await run_brief(_USER, BriefingKind.DAILY)

        payload = world.stored()
        assert [c.args[0] for c in world.render.await_args_list] == [payload]
        request = world.notify.await_args.args[0]
        assert request.priority == 2
        action = request.content.actions[0]
        assert (action.label, action.style) == ("Open briefing", "primary")
        redirect = action.config.redirect
        assert (redirect.open_in_new_tab, redirect.close_notification) == (False, True)
        card = request.details.card
        assert (card.briefing_id, card.date) == (_BRIEF_ID, _DATE)
        post = world.post.await_args.kwargs
        assert post["user"].user_id == _USER
        assert (post["origin"], post["image"].filename) == ("daily brief", "gaia-daily-brief.jpg")
        assert post["message_class"] is ProactiveMessageClass.ROUTINE

    @pytest.mark.parametrize(
        "user",
        [
            UserDocument(
                id=_USER, timezone="UTC", email="a@b.c", notification_channel_prefs={"email": False}
            ),
            UserDocument(id=_USER, timezone=_TZ, email=None),
            UserDocument(id=_USER, timezone=_TZ, email="   "),
        ],
        ids=["turned-off", "no-address", "blank-address"],
    )
    async def test_email_is_left_out_when_it_is_off_or_has_no_address(
        self, world: World, user: UserDocument
    ) -> None:
        world.user = user

        await run_brief(_USER, BriefingKind.DAILY)

        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == ["inapp"]

    async def test_a_calendar_that_did_not_answer_is_named_unavailable_never_empty(
        self, world: World
    ) -> None:
        """Regression: a calendar read that failed reached the voice as a day with nothing on it."""
        world.work = _brief_work()
        world.calendar = CalendarGap.UNAVAILABLE

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.pool is not None and world.pool.context.calendar is CalendarGap.UNAVAILABLE
        assert world.fact_sources is not None
        assert world.fact_sources.calendar.gap is CalendarGap.UNAVAILABLE
        assert [(u.app, u.reason) for u in world.stored().sources_unavailable] == [
            ("Google Calendar", ScoutSkipReason.FAILED)
        ]

    async def test_an_app_the_brief_could_not_read_is_named_to_the_composer_and_the_voice(
        self, world: World
    ) -> None:
        world.work = _brief_work()
        world.scouts = [_skipped("Notion")]
        notion = [UnreadSource(app="Notion", reason=ScoutSkipReason.FAILED)]

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.pool is not None and world.pool.context.unread == notion
        assert world.fact_sources is not None and world.fact_sources.unread == notion
        assert world.stored().sources_unavailable == notion


class TestTheEdition:
    async def test_an_air_mail_brief_records_its_stamp_city_and_advances_the_stored_pass(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            edition_draws, "stamp_weights", lambda: {"paris": 1, "tokyo": 1, "lima": 1}
        )
        world.family_first(EditionFamily.POSTAL)
        seeded = world.bags["edition_family"].order

        await run_brief(_USER, BriefingKind.DAILY)

        payload = world.stored()
        assert payload.template_family == "postal"
        # The stored pass was read and advanced, not reshuffled from scratch.
        assert world.bags["edition_family"] == ShuffleBag(order=seeded, index=1)
        assert payload.stamp_city in {"paris", "tokyo", "lima"}
        assert world.bags["stamp_city"].order[0] == payload.stamp_city

    @pytest.mark.parametrize(
        ("family", "bag"),
        [(EditionFamily.POSTAL, "stamp_city"), (EditionFamily.ALMANAC, "artwork")],
    )
    async def test_a_brief_that_fails_to_deliver_spends_no_draw(
        self, world: World, monkeypatch: pytest.MonkeyPatch, family: EditionFamily, bag: str
    ) -> None:
        """A draw is spent only by a brief that went out: a failed run burns no member."""
        monkeypatch.setattr(edition_draws, "stamp_weights", lambda: {"paris": 1, "tokyo": 1})
        world.family_first(family)
        family_before = world.bags["edition_family"]
        world.notify.side_effect = RuntimeError("orchestrator down")

        with pytest.raises(RuntimeError, match="orchestrator down"):
            await run_brief(_USER, BriefingKind.DAILY)

        assert world.bags["edition_family"] == family_before
        assert bag not in world.bags

    async def test_a_first_stamp_is_announced_on_every_channel(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(edition_draws, "stamp_weights", lambda: {"tokyo": 1})
        world.family_first(EditionFamily.POSTAL)

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.stored().new_stamp == NewStamp(
            city="Tokyo", country="Japan", collected=1, total=85
        )
        world.stamped.assert_awaited_once_with(_USER)
        line = "New stamp: Tokyo, Japan. 1 of 85 collected. [See your stamps]("
        assert line in world.post.await_args.kwargs["text"]
        assert line in world.notify.await_args.args[0].content.body
        assert world.capture.call_args.args[1].stamp_collected is True

    async def test_a_city_already_collected_is_not_announced_again(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(edition_draws, "stamp_weights", lambda: {"tokyo": 1})
        world.family_first(EditionFamily.POSTAL)
        world.stamped.return_value = [
            _brief(
                "2026-09-01",
                BriefForm.EDITION,
                template_family=EditionFamily.POSTAL,
                stamp_city="tokyo",
            )
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        assert (world.stored().stamp_city, world.stored().new_stamp) == ("tokyo", None)
        assert "New stamp" not in world.post.await_args.kwargs["text"]

    async def test_the_next_framed_brief_hangs_the_next_painting_of_the_pass(
        self, world: World
    ) -> None:
        world.family_first(EditionFamily.EXHIBITION)
        order = sorted(artwork_weights())
        world.bags["artwork"] = ShuffleBag(order=order, index=3)

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.stored().artwork_id == order[3]
        assert world.bags["artwork"] == ShuffleBag(order=order, index=4)

    async def test_a_block_the_drawn_edition_cannot_draw_moves_to_the_briefs_page(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.work = _brief_work()
        world.composer.side_effect = _with_block(
            _composed({"Waiting": ["Approve the Priya reply"]}), _PROGRESS
        )
        monkeypatch.setattr(edition_draws, "families_drawing", lambda *_: set())
        world.family_first(EditionFamily.MENU)

        await run_brief(_USER, BriefingKind.DAILY)

        payload = world.stored()
        assert [b.kind for b in payload.undrawn] == ["progress"]
        assert [b.kind for b in payload.blocks] == ["items"]

    async def test_a_brief_its_only_edition_cannot_draw_is_still_sent(self, world: World) -> None:
        """Regression (#1804 review): with only Menu on, a progress-only brief drew nothing and was never pushed."""
        world.calendar = []
        world.work = _brief_work()
        world.state.editions = {
            family: EditionChoice.OFF for family in DAILY_FAMILY_WEIGHTS if family != "menu"
        }
        world.composer.side_effect = lambda schema, _prompt, **_k: schema.model_validate(
            {"blocks": [_PROGRESS]}
        )

        await run_brief(_USER, BriefingKind.DAILY)

        payload = world.stored()
        assert (payload.template_family, payload.blocks) == ("menu", [])
        assert [b.kind for b in payload.undrawn] == ["progress"]
        world.post.assert_awaited_once()


class TestTheComposition:
    async def test_a_composition_broken_on_every_attempt_still_sends_what_holds_of_it(
        self, world: World
    ) -> None:
        """Dhruv's Nov 11: a heading typing a stray "9" failed the brief and he got nothing."""
        world.work = _brief_work()
        world.composer.side_effect = None
        world.composer.return_value = BriefComposition.model_validate(
            {
                "blocks": [
                    _items_block(
                        "9 things waiting",
                        [
                            {
                                "id": 1,
                                "action": "approve",
                                "outcome": None,
                                "title": "Priya reply",
                                "detail": None,
                            }
                        ],
                    )
                ]
            }
        )

        async with captured_wide_event() as event:
            assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        assert world.composer.await_count == 2
        assert len(_salvaged(event, "composition")) == 1
        (section,) = world.stored().sections
        assert (section.title, [i.text for i in section.items]) == ("Needs you", ["Priya reply"])
        world.notify.assert_awaited()

    async def test_the_composition_is_one_call_metered_to_the_user(self, world: World) -> None:
        world.work = _brief_work()

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.composer.await_args.kwargs["config"] == metered_config(_USER)


class TestTheVoice:
    async def test_the_voice_is_one_structured_call_metered_to_the_user_never_an_agent_turn(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Live: a capped user's voice turn came back as the usage-limit stop text, and the brief failed."""
        capped_turn = AsyncMock(return_value=SimpleNamespace(message=DAILY_BUDGET_STOP_FREE))
        monkeypatch.setattr(agent_module, "call_agent_silent", capped_turn)

        await run_brief(_USER, BriefingKind.DAILY)

        schema, _ = world.voice.await_args.args
        kwargs = world.voice.await_args.kwargs
        assert schema is BriefVoice
        assert (kwargs["label"], kwargs["config"]) == (BRIEF_VOICE_LABEL, metered_config(_USER))
        assert kwargs["options"].schema_held
        assert world.voice.await_count == 1
        capped_turn.assert_not_awaited()
        assert world.stored().headline == _VOICE["headline"]
        assert AIFeature.for_label(BRIEF_VOICE_LABEL) is AIFeature.BRIEFING

    @pytest.mark.parametrize("kind", [BriefingKind.DAILY, BriefingKind.WEEKLY])
    async def test_a_voice_unreadable_on_every_attempt_still_sends_the_brief_plainly(
        self, world: World, kind: BriefingKind
    ) -> None:
        world.replies = [MalformedStructuredOutputError("invalid JSON: Expecting value")]

        async with captured_wide_event() as event:
            assert await run_brief(_USER, kind) is BriefingRunOutcome.SENT

        assert world.voice.await_count == MAX_VOICE_ATTEMPTS
        assert len(_salvaged(event, "voice")) == 1
        world.sent_plainly()

    async def test_the_stored_brief_holds_each_slot_filled_from_its_fact(
        self, world: World
    ) -> None:
        world.replies = [
            {**_VOICE, "headline": "Sequoia at [[fact:<fact of Sequoia>.time]]", "message": "-"}
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.stored().headline == "Sequoia at 11:00 AM"

    async def test_a_count_the_voice_was_shown_is_voiced_by_its_slot(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: 5 open todos were shown to the model, then rejected when it said 5."""
        _seam(monkeypatch, world, BriefReads, "own_todos", _own_todos(5))
        world.calendar = []
        world.replies = [{**_VOICE, "headline": "[[count:open_todos]] open todos, a quiet morning"}]

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.writing is not None
        assert world.writing.values.counts[CountName.OPEN_TODOS] == 5
        assert world.voice.await_count == 1
        assert world.stored().headline == "5 open todos, a quiet morning"

    async def test_the_voice_is_held_to_what_recent_briefs_printed_of_every_kind(
        self, world: World
    ) -> None:
        world.recent.return_value = [
            _brief("2026-10-13", BriefForm.EDITION, message="\n  Priya replied overnight.\nMore."),
            _brief("2026-10-12", BriefForm.EDITION, BriefingKind.WEEKLY, message=None),
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        world.recent.assert_awaited_once_with(_USER, limit=5)
        assert world.writing is not None and world.writing.recent == RecentLines(
            headlines=["Your morning, sorted"] * 2,
            ledes=["Everything else is moving."] * 2,
            captions=["Onward."] * 2,
            openings=["Priya replied overnight."],
        )

    async def test_a_message_that_leaves_out_the_lead_is_sent_back_until_it_names_it(
        self, world: World
    ) -> None:
        world.work = _brief_work()
        world.composer.side_effect = _composed(
            {"Done overnight": ["Investor update"]},
            lead=("Approve the Priya reply", "Send the reply once you approve"),
        )
        world.replies = [
            _wrote("The investor update went out."),
            _wrote("[Priya's reply](fact:<fact of Priya>) is first; the investor update went out."),
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.writing is not None
        assert world.writing.lead == _fact_id(world.writing, "Approve the Priya reply")
        assert world.voice.await_count == 2
        assert world.stored().message == "Priya's reply is first; the investor update went out."

    async def test_a_winback_need_not_refer_to_the_lead_and_reads_as_a_winback(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _winback(monkeypatch, world)
        world.work = _brief_work()
        world.composer.side_effect = _composed(
            {"Done overnight": ["Investor update"]},
            lead=("Approve the Priya reply", "Send the reply once you approve"),
        )
        world.replies = [_wrote("The investor update went out.")]

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.writing is not None and world.writing.lead is None
        assert world.voice.await_count == 1
        assert (world.stored().message, world.stored().mood) == (
            "The investor update went out.",
            "winback",
        )

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
        world.replies = [{**_VOICE, "lede": "The Q3 board memo went out."}]

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.writing is not None and "Q3" in world.writing.values.quoted
        assert world.stored().lede == "The Q3 board memo went out."
        assert world.voice.await_count == 1

    @pytest.mark.parametrize("kind", [BriefingKind.DAILY, BriefingKind.WEEKLY])
    async def test_a_figure_from_the_goal_they_stated_may_be_typed(
        self, world: World, monkeypatch: pytest.MonkeyPatch, kind: BriefingKind
    ) -> None:
        """Replay of Nov 8: "a goal of 300 users" was refused, and the retry dropped the goal."""
        goal = StatedGoal("Their growth goal for GAIA is 300 users.", GoalOrigin.MEMORY)
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[goal]))
        reply = _weekly() if kind is BriefingKind.WEEKLY else _VOICE
        world.replies = [{**reply, "lede": "Still aiming for 300 users?"}]

        await run_brief(_USER, kind)

        assert world.stored().lede == "Still aiming for 300 users?"
        assert world.voice.await_count == 1


class TestLinks:
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
        world.work = TrackedWork(
            completed=[_tracked("c1", "Deck", canvas_content="Ten slides")],
            blocked=[_tracked("b1", "Reply", canvas_content="A draft reply")],
        )

    async def test_a_linked_item_gets_its_link_on_its_phrase_and_an_unlinked_one_is_never_minted(
        self, world: World
    ) -> None:
        world.replies = [_wrote("the deck is done\n[the reply](fact:<fact of Reply>) waits on you")]

        await run_brief(_USER, BriefingKind.DAILY)

        payload = world.stored()
        assert payload.message == f"the deck is done\n[the reply]({_todo_link('b1')}) waits on you"
        links = {it.todo_id: it.link for sec in payload.sections for it in sec.items}
        assert links == {"b1": _todo_link("b1"), "c1": None}
        assert [c.args[2] for c in world.mint.await_args_list] == ["b1", _BRIEF_ID]
        assert f"[the reply]({_todo_link('b1')}) waits" in world.post.await_args.kwargs["text"]

    async def test_a_slot_with_no_link_behind_it_leaves_its_phrase_as_text(
        self, world: World
    ) -> None:
        """Sharing turned off (or a failed mint) leaves the sentence, not a raw slot."""
        world.mint.side_effect = lambda user_id, target_type, target_id: (
            None if target_type is ShortLinkTargetType.TODO_DELIVERABLE else _BRIEF_LINK
        )
        world.replies = [_wrote("the [reply](fact:<fact of Reply>) waits")]

        await run_brief(_USER, BriefingKind.DAILY)

        payload = world.stored()
        assert payload.message == "the reply waits"
        assert all(it.link is None for sec in payload.sections for it in sec.items)


def _todo_link(todo_id: str) -> str:
    return f"{settings.SHORTLINK_BASE_URL}/todo-{todo_id}"


class TestHeldResults:
    """Results held for the brief are candidates like any other, cleared once the brief went out."""

    async def test_a_held_result_joins_gaias_work_and_every_held_result_is_cleared(
        self, world: World
    ) -> None:
        world.work = _brief_work()
        world.held = [_held("h1", "Paper digest", _DIGEST_REPORT), _held("h2", "Digest", "first")]
        world.composer.side_effect = _composed(
            {
                "Needs you": ["Approve the Priya reply"],
                "GAIA's work": ["Paper digest: 3 new papers on retrieval", "Investor update"],
            }
        )

        await run_brief(_USER, BriefingKind.DAILY)

        payload = world.stored()
        assert [(s.title, [i.text for i in s.items]) for s in payload.sections] == [
            ("Needs you", ["Approve the Priya reply"]),
            ("GAIA's work", ["Paper digest: 3 new papers on retrieval", "Investor update"]),
        ]
        # Nothing left out is lost: it is on the brief's full page.
        assert [(i.title, i.app, i.kind) for i in payload.uncomposed] == [
            ("Digest: first", "GAIA", "note")
        ]
        # A report's body never reaches the voice to be claimed from.
        assert "two cite your draft" not in world.voice.await_args.args[1]
        world.consume.assert_awaited_once_with(_USER, ["h1", "h2"])

    async def test_an_item_already_in_the_brief_is_shown_once_and_still_cleared(
        self, world: World
    ) -> None:
        world.work = TrackedWork(completed=[_tracked("c1", "Digest: 3 new papers")])
        world.held = [
            _held("h1", "Digest", "3 new papers\nmore detail"),
            _held("h2", "Paper digest", _DIGEST_REPORT),
            _held("h3", "Paper  digest", _DIGEST_REPORT),
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        texts = [i.text for s in world.stored().sections for i in s.items]
        assert texts == ["Paper digest: 3 new papers on retrieval", "Digest: 3 new papers"]
        world.consume.assert_awaited_once()
        assert world.consume.await_args.args[0] == _USER
        assert sorted(world.consume.await_args.args[1]) == ["h1", "h2", "h3"]

    async def test_a_held_result_with_a_blank_report_shows_only_its_source(
        self, world: World
    ) -> None:
        world.held = [_held("h1", "Digest", "  \n ")]

        await run_brief(_USER, BriefingKind.DAILY)

        assert [i.text for s in world.stored().sections for i in s.items] == ["Digest"]


class TestOneSubjectIsOneItem:
    async def test_todos_on_one_subject_reach_the_voice_and_the_page_as_one_counted_item(
        self, world: World
    ) -> None:
        """Regression: three approval requests for one Acme MSA renewal became one line with three links."""
        world.work = TrackedWork(
            blocked=[
                _tracked("b1", "Approve the Acme MSA renewal"),
                _tracked("b2", "Approve the Acme MSA renewal"),
                _tracked("b3", "approve the  Acme MSA renewal"),
                _tracked("b4", "Reply to Daniel"),
            ]
        )

        await run_brief(_USER, BriefingKind.DAILY)

        payload = world.stored()
        items = [(it.text, it.todo_id, it.count) for s in payload.sections for it in s.items]
        assert items == [("Approve the Acme MSA renewal", "b1", 3), ("Reply to Daniel", "b4", 1)]
        assert world.fact("Acme MSA renewal").count == 3
        assert world.writing is not None
        assert world.writing.values.counts[CountName.NEEDS_YOU] == 2
        assert [(s.value, s.label) for s in payload.stats] == [("2", "waiting on you")]


class TestSourcesReachTheBrief:
    async def test_an_app_signal_a_desk_finding_an_approval_and_a_failed_run_each_land_in_place(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.scouts = [*_scouted(_LOGIN), _skipped("Notion")]
        world.reads["find_latest_by_external_ref"].return_value = _tracked("desk-1", "Inbox desk")
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
        _failed_run(monkeypatch, world)
        world.reads["list_since"].return_value[0].started_at = _NOW - timedelta(hours=2)

        await run_brief(_USER, BriefingKind.DAILY)

        payload = world.stored()
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

    async def test_the_signals_placed_reach_the_voice_with_what_earlier_briefs_said(
        self, world: World
    ) -> None:
        world.scouts = _scouted(_LOGIN, _DOCS)
        world.memory = [_remembered("ENG-12", "Todo")]
        world.composer.side_effect = _composed(
            {"Needs you": [_LOGIN.title], "From your apps": [_DOCS.title]},
            reports=frozenset({_DOCS.title}),
        )
        world.replies = [
            _wrote("[the login redirect](fact:<fact of Fix the login>) still needs you.")
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        assert [(c.signal.title, c.memory) for _, c in world.signals if c.signal] == [
            (_LOGIN.title, world.memory[0]),
            (_DOCS.title, None),
        ]
        assert world.voice_prompt.call_args.kwargs["blocks"].signals
        assert world.stored().message == f"[the login redirect]({_LOGIN.url}) still needs you."

    async def test_every_signal_the_brief_placed_is_marked_shown_named_or_not(
        self, world: World
    ) -> None:
        """Regression: a signal placed in the edition but not named in the message came back as new."""
        world.scouts = _scouted(_LOGIN, _DOCS)
        world.composer.side_effect = _composed(
            {"Needs you": [_LOGIN.title], "From your apps": [_DOCS.title]},
            reports=frozenset({_DOCS.title}),
        )
        world.replies = [_wrote("[[fact:<fact of Fix the login>]] is yours today.")]

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
        _, updates = world.stored().sections
        assert [(i.text, i.kind) for i in updates.items] == [(_DOCS.title, "note")]

    async def test_a_day_with_only_signals_is_pushed_and_counted(self, world: World) -> None:
        world.calendar = []
        world.scouts = _scouted(_DOCS)

        await run_brief(_USER, BriefingKind.DAILY)

        world.post.assert_awaited_once()
        assert world.capture.call_args.args[1].signal_count == 1


# ---- The quiet note -----------------------------------------------------------------------


def _quiet_day(world: World) -> None:
    """Nothing to place, nothing on the calendar and the goal asked yesterday: the ladder says nothing."""
    world.work = TrackedWork()
    world.calendar = []
    world.state.wind_down = BriefingWindDown(goal_asked_at=_NOW - timedelta(days=1))


def _shown_before(world: World, todo_id: str, times: int) -> None:
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


def _expected_note(kind: BriefingKind, facts: QuietFacts) -> str:
    """Return the quiet note the quiet-note module writes on the run's clock for facts."""
    return quiet_note(resolve_clock(_TZ), KIND_SPECS[kind], facts).message or ""


class TestAQuietDay:
    async def test_a_quiet_day_sends_its_note_and_no_edition(self, world: World) -> None:
        """Founder decision: a day with nothing placed and nothing on the calendar sends a plain note."""
        _quiet_day(world)
        bags_before = dict(world.bags)

        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        world.render.assert_not_awaited()
        world.voice.assert_not_awaited()
        payload = world.stored()
        assert payload.form is BriefForm.QUIET_NOTE
        assert payload.message == _expected_note(BriefingKind.DAILY, QuietFacts(calendar=None))
        assert world.upsert.await_args.args[0].edition is None
        request = world.notify.await_args.args[0]
        assert request.details == BriefNoteNotification(kind=NotificationKind.BRIEFING_NOTE)
        assert request.content.rich_content is None
        assert [c.channel_type for c in request.channels] == ["inapp", "email"]
        posted = world.post.await_args.kwargs
        assert (posted["text"], posted["image"]) == (payload.message, None)
        world.brief_message.assert_awaited_once_with(_USER, payload.message, None)
        assert world.capture.call_args.args[1].form == "quiet_note"
        assert world.bags == bags_before

    async def test_the_note_says_what_the_run_could_not_read_and_what_is_overdue(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _quiet_day(world)
        world.calendar = CalendarGap.UNAVAILABLE
        world.scouts = [_skipped("GitHub", ScoutSkipReason.SIGNED_OUT), _skipped("Notion")]
        _seam(monkeypatch, world, BriefReads, "own_todos", _own_todos(200, overdue=70))
        unread = [
            UnreadSource(app="GitHub", reason=ScoutSkipReason.SIGNED_OUT),
            UnreadSource(app="Notion", reason=ScoutSkipReason.FAILED),
        ]

        await run_brief(_USER, BriefingKind.DAILY)

        payload = world.stored()
        assert payload.message == _expected_note(
            BriefingKind.DAILY,
            QuietFacts(calendar=CalendarGap.UNAVAILABLE, overdue=70, unread=unread),
        )
        assert payload.sources_unavailable == unread

    async def test_a_quiet_note_accounts_for_the_held_results_it_carries(
        self, world: World
    ) -> None:
        _quiet_day(world)
        world.held = [_held("h1", "Paper digest", _DIGEST_REPORT)]
        world.composer.side_effect = None
        world.composer.return_value = BriefComposition(blocks=[])

        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        assert world.stored().form is BriefForm.QUIET_NOTE
        world.consume.assert_awaited_once_with(_USER, ["h1"])

    @pytest.mark.parametrize(
        ("blocked", "form"),
        [(["b1"], BriefForm.QUIET_NOTE), (["b1", "b2"], BriefForm.EDITION)],
        ids=["only-repeats", "something-new-beside-repeats"],
    )
    async def test_a_day_holding_only_what_earlier_briefs_showed_is_quiet(
        self, world: World, blocked: list[str], form: BriefForm
    ) -> None:
        """Replay: the same three undated todos were drawn as a fresh edition day after day."""
        _quiet_day(world)
        titles = {"b1": "Approve the Acme MSA", "b2": "Reply to Daniel"}
        world.work = TrackedWork(blocked=[_tracked(t, titles[t]) for t in blocked])
        _shown_before(world, "b1", times=2)

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.stored().form is form

    async def test_a_day_of_repeats_whose_chart_shows_what_moved_is_an_edition(
        self, world: World
    ) -> None:
        _quiet_day(world)
        world.work = TrackedWork(blocked=[_tracked("b1", "Approve the Acme MSA")])
        _shown_before(world, "b1", times=2)
        world.reads["list_completed_since"].return_value = _completions(
            [_tracked("c1", "Investor update")]
        )
        world.composer.side_effect = _with_block(
            _composed({"Waiting": ["Approve the Acme MSA"]}), _CHART
        )

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.stored().form is BriefForm.EDITION

    async def test_a_day_with_an_event_is_an_edition_not_a_note(self, world: World) -> None:
        _quiet_day(world)
        world.calendar = [_EVENT]

        await run_brief(_USER, BriefingKind.DAILY)

        payload = world.stored()
        assert payload.form is BriefForm.EDITION
        assert [e.title for e in payload.calendar] == ["Sequoia"]
        world.render.assert_awaited_once()

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
        _quiet_day(world)
        days = ["2026-10-13", "2026-10-12", "2026-10-11"]
        world.briefs_read([_brief(day, form) for day, form in zip(days, before)])

        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.SILENT

        # Nothing is stored, so a silent day can never count toward the winback streak.
        world.nothing_sent()
        world.goal_asked.assert_not_awaited()

    async def test_a_quiet_weekly_before_it_does_not_silence_the_daily(self, world: World) -> None:
        _quiet_day(world)
        world.briefs_read(
            [
                _brief("2026-10-13", BriefForm.QUIET_NOTE, BriefingKind.WEEKLY),
                _brief("2026-10-13", BriefForm.EDITION),
            ]
        )

        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT
        assert world.stored().form is BriefForm.QUIET_NOTE


# ---- The weekly digest --------------------------------------------------------------------


class TestAWeeklyDigest:
    async def test_the_digest_is_stored_and_delivered_as_weekly_and_always_pushed(
        self, world: World
    ) -> None:
        world.replies = [_weekly()]

        assert await run_brief(_USER, BriefingKind.WEEKLY) is BriefingRunOutcome.SENT

        payload = world.stored()
        # Masthead, date and mood come from code, whatever the model wrote.
        assert (payload.kicker, payload.date, payload.mood) == (WEEKLY_KICKER, _DATE, "weekly")
        assert world.upsert.await_args.args[0].kind == "weekly"
        assert payload.template_family == "weekly"
        assert payload.week == world.week.return_value
        # The tallies count the week's completions themselves: the user's one todo.
        assert payload.tallies == BriefingTallies(done_by_you=1, done_by_gaia=0)
        assert payload.headline == "A good week"
        request = world.notify.await_args.args[0]
        assert request.details.kind == NotificationKind.BRIEFING_WEEKLY
        assert request.content.body == payload.message == "Gym"
        # The recap is always pushed: it reaches the chat app, not only the in-app page.
        assert world.post.await_args.kwargs["origin"] == "weekly brief"
        world.consume.assert_not_awaited()

    async def test_code_builds_the_sections_from_the_weeks_candidates(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: the model wrote the whole weekly payload, its sections and items included."""
        _a_full_week(monkeypatch, world)
        world.replies = [_weekly()]
        world.composer.side_effect = _composed(
            {
                "Needs you": ["CRM sync failed"],
                "You finished": ["Send the deck"],
                "GAIA's work": ["Investor deck"],
            }
        )

        await run_brief(_USER, BriefingKind.WEEKLY)

        payload = world.stored()
        assert [(s.title, [(i.text, i.kind) for i in s.items]) for s in payload.sections] == [
            ("Needs you", [("CRM sync failed", "failed")]),
            ("You finished", [("Send the deck", "lookback")]),
            ("GAIA's work", [("Investor deck", "lookback")]),
        ]
        assert payload.message == "CRM sync failed\nSend the deck\nInvestor deck\nPitch to Accel"
        assert payload.week == world.week.return_value
        assert payload.sources_read == ["Google Calendar"]
        assert world.reads["list_since"].await_args.args[1] == _WEEK_START

    async def test_the_weekly_reads_this_users_week_ahead_once(self, world: World) -> None:
        await run_brief(_USER, BriefingKind.WEEKLY)

        # One read: this week from Monday, then the seven local days from tomorrow to 22 Oct.
        world.reads["fetch_calendar"].assert_awaited_once_with(
            _USER, _WEEK_START, datetime(2026, 10, 21, 18, 30, tzinfo=UTC)
        )

    async def test_a_lead_the_weekly_edition_cannot_draw_moves_to_the_briefs_page(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _a_full_week(monkeypatch, world)
        world.replies = [_weekly()]
        world.composer.side_effect = _composed(
            {"GAIA's work": ["Investor deck"]}, lead=("CRM sync failed", "I can rerun it.")
        )

        await run_brief(_USER, BriefingKind.WEEKLY)

        payload = world.stored()
        assert payload.undrawn == [SectionBlock(kind="lead", section=0)]
        assert payload.blocks == [SectionBlock(kind="items", section=1)]
        assert [s.items[0].text for s in payload.sections] == ["CRM sync failed", "Investor deck"]

    async def test_a_digest_that_leaves_out_its_lead_is_sent_back_then_sent_plainly(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _a_full_week(monkeypatch, world)
        world.composer.side_effect = _composed(
            {"GAIA's work": ["Investor deck"]}, lead=("CRM sync failed", "I can rerun it.")
        )
        world.replies = [_weekly(message="Good week.")]

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert world.writing is not None
        assert world.writing.lead == _fact_id(world.writing, "CRM sync failed")
        assert world.voice.await_count == MAX_VOICE_ATTEMPTS
        assert (world.sent_plainly().message or "").startswith("- CRM sync failed\n")

    async def test_the_week_ahead_is_voiced_by_its_days_facts(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _a_full_week(monkeypatch, world)
        world.replies = [
            _weekly(
                lede="Then [[fact:<fact of Pitch to Accel>]] on Friday at "
                "[[fact:<fact of Pitch to Accel>.time]]."
            )
        ]

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert world.fact_sources is not None and world.fact_sources.span is WEEK_AHEAD
        assert world.stored().lede == "Then Pitch to Accel on Friday at 3:00 PM."

    async def test_a_frequency_word_its_facts_carry_is_kept(self, world: World) -> None:
        world.reads["list_completed_since"].return_value = _completions(
            user=[make_todo("Send the usual deck", id="u1", user_id=_USER)]
        )
        world.replies = [_weekly(lede="The usual deck went out.")]

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert world.voice.await_count == 1
        assert world.stored().lede == "The usual deck went out."

    async def test_the_weekly_is_sent_back_for_a_line_a_recent_daily_printed(
        self, world: World
    ) -> None:
        """The weekly passed no recent lines and the daily read only dailies."""
        world.recent.return_value = [
            _brief("2026-10-13", BriefForm.EDITION, headline="A good week")
        ]
        world.replies = [_weekly(), _weekly(headline="A full week")]

        await run_brief(_USER, BriefingKind.WEEKLY)

        world.recent.assert_awaited_once_with(_USER, limit=5)
        assert world.writing is not None and world.writing.recent.headlines == ["A good week"]
        assert world.voice.await_count == 2
        assert world.stored().headline == "A full week"

    async def test_gaias_week_is_recapped_from_its_own_work_and_mail_alone(
        self, world: World
    ) -> None:
        finished = [
            _tracked(f"g{n}", f"Research {n}", updated_at=_NOW - timedelta(days=1))
            for n in range(6)
        ]
        world.reads["list_completed_since"].return_value = _completions(finished)
        world.work = TrackedWork(completed=finished[:1])
        # Meeting hours and the last day's mail sort are not GAIA's week: neither is counted.
        world.reads["fetch_calendar"].side_effect = lambda *_: [
            GoogleCalendarEventResource(
                summary="Board",
                start=GoogleCalendarEventDateTime(dateTime="2026-10-13T10:00:00+05:30"),
                end=GoogleCalendarEventDateTime(dateTime="2026-10-13T11:00:00+05:30"),
            )
        ]
        world.reads["verdicts_since"].return_value = [
            EmailVerdictDocument(
                user_id=_USER, message_id="m1", answers={}, bucket=DeskBucket.REPLY, created_at=_NOW
            )
        ]
        world.replies = [_weekly(lede="I finished [[series:gaia_finished.total]] tasks.")]

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert world.fact_sources is not None and world.fact_sources.recap is not None
        assert [s.id for s in world.fact_sources.recap.series] == ["gaia_finished"]
        assert world.stored().lede == "I finished 6 tasks."

    async def test_every_read_is_this_users_over_the_week_and_the_week_ahead(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _a_full_week(monkeypatch, world)
        world.scouts = [*_scouted(_LOGIN), _skipped("Notion")]
        world.recent.return_value = [
            _brief("2026-10-13", BriefForm.EDITION, message="Priya replied overnight.")
        ]
        world.memory = [_remembered("ENG-12", "In Progress")]
        _seam(monkeypatch, world, BriefReads, "own_todos", _own_todos(80, 70))
        world.reads["list_open_user_todos"].return_value = [
            make_todo(
                "File the VAT return", id="o1", user_id=_USER, due_date=_NOW + timedelta(days=1)
            )
        ]
        world.replies = [
            _weekly(
                message="[The deck](fact:<fact of Investor deck>) is done. "
                "[[fact:<fact of Investor deck>]] shipped, "
                "[Priya](fact:<fact of Fix the login redirect>) waits."
            )
        ]

        await run_brief(_USER, BriefingKind.WEEKLY)

        world.reads["tracked_work"].assert_called_once_with(_WEEK_START)
        assert world.voice.await_args.kwargs["config"] == metered_config(_USER)
        assert world.reads["own_todos"].call_args.args[0].date_str == _DATE
        world.reads["find_scheduled_between"].assert_awaited_once_with(
            _USER, _TODAY_START, _WEEK_AHEAD_END
        )
        world.reads["list_open_user_todos"].assert_awaited_once_with(_USER, limit=0)
        assert world.week.call_args.args[2] == [_FRIDAY_PITCH]
        assert all(c.args[0] == _USER and c.args[2] == _NOW for c in world.seen.await_args_list)
        assert world.pool is not None
        assert world.pool.context.recent_openings == ["Priya replied overnight."]
        prompt_args = world.weekly_prompt.call_args.kwargs
        assert prompt_args["date_local"] == _DATE
        assert prompt_args["blocks"].reader == reader_block(world.user)
        assert prompt_args["blocks"].signals
        assert [(c.signal.title, c.memory) for _, c in world.signals if c.signal] == [
            (_LOGIN.title, world.memory[0])
        ]
        assert world.writing is not None
        counts = world.writing.values.counts
        assert (counts[CountName.OPEN_TODOS], counts[CountName.OVERDUE_TODOS]) == (80, 70)
        assert world.fact("File the VAT return").time == "Thu Oct 15"
        world.mint.assert_any_await(_USER, ShortLinkTargetType.TODO_DELIVERABLE, "g1")
        payload = world.stored()
        assert [(u.app, u.reason) for u in payload.sources_unavailable] == [
            ("Notion", ScoutSkipReason.FAILED)
        ]
        assert world.capture.call_args.args[1].signal_count == 1
        shown_by, _, shown_at = world.shown.await_args.args
        assert (shown_by, shown_at) == (_USER, _NOW)

    async def test_what_waits_on_the_user_reaches_the_weekly_and_is_remembered_as_shown(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The weekly read only failed runs, completions and the calendar, and scouts with no signals."""
        world.work = TrackedWork(blocked=[_tracked("b1", "Approve the Priya reply")])
        world.scouts = _scouted(_LOGIN)
        _seam(monkeypatch, world, BriefReads, "own_todos", _own_todos(80, 70))
        world.replies = [_weekly(lede="Two things wait on you.")]

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert world.fact("Approve the Priya reply").kind is not None
        assert world.fact(_LOGIN.title).title == _LOGIN.title
        assert world.writing is not None
        assert world.writing.values.counts[CountName.OVERDUE_TODOS] == 70
        world.seen.assert_awaited()
        assert "todo:b1" in [seen.external_id for seen in world.shown.await_args.args[1]]

    async def test_the_week_is_read_for_this_user_from_monday_in_one_window(
        self, world: World
    ) -> None:
        deck = _tracked("g0", "Deck", canvas_content="# Deck\nFinal numbers in")
        gaia = [deck, *[_tracked(f"g{i}", f"G{i}") for i in range(1, 16)]]
        completed = _completions(
            gaia, [make_todo(f"U{i}", id=f"u{i}", user_id=_USER) for i in range(16)]
        )
        world.reads["list_completed_since"].return_value = completed
        world.work = TrackedWork(completed=gaia)
        world.replies = [_weekly()]
        world.composer.side_effect = _composed({"This week": ["Deck", "U15"]})

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.WEEKLY)

        week_call = world.week.call_args
        assert week_call.args[0].date_str == _DATE
        # The sections, the prose and the tallies read the same completions: one window for all.
        assert [d.id for d in week_call.args[1].docs] == [d.id for d in completed]
        assert world.stored().tallies == BriefingTallies(done_by_you=16, done_by_gaia=16)
        assert world.pool is not None
        finished = {c.title: c.finished_by for c in world.pool.items.values()}
        assert (finished["Deck"], finished["U15"]) == (TodoCompleter.GAIA, TodoCompleter.USER)
        # The week's series run Monday to today, the calendar's among them.
        assert (
            call(_USER, _WEEK_START, datetime(2026, 10, 21, 18, 30, tzinfo=UTC))
            in world.reads["fetch_calendar"].await_args_list
        )
        world.reads["list_completed_since"].assert_awaited_once_with(_USER, since=_WEEK_START)
        payload = world.stored()
        assert (payload.hue, payload.generated_at) == (79, "7:05 AM")
        assert (
            event["brief_composition"]["pool_items"],
            event["brief_composition"]["items"],
            event["brief_composition"]["uncomposed"],
        ) == (32, 2, 30)
        assert len(payload.uncomposed) == 30

    async def test_the_goals_and_the_pool_are_the_users_and_the_weeks(self, world: World) -> None:
        world.replies = [_weekly()]
        world.user.name = "Ada Lovelace"
        world.calendar = [_FRIDAY_PITCH]

        await run_brief(_USER, BriefingKind.WEEKLY)

        world.reads["stated_goals"].assert_awaited_once_with(_USER, world.user)
        assert world.reads["list_since"].await_args.args == (_USER, _WEEK_START)
        assert world.composer.await_args.kwargs["config"] == metered_config(_USER)
        assert world.pool is not None
        context = world.pool.context
        assert (context.reader, str(context.clock.tz), context.calendar) == ("Ada", _TZ, 1)
        assert context.calendar_span == WEEK_AHEAD.words
        assert world.weekly_prompt.call_args.kwargs["blocks"].goal == "Stated goal: Ship v2"
        payload = world.stored()
        assert [b.kind for b in payload.blocks] == ["items"]
        assert payload.uncomposed == []

    @pytest.mark.parametrize("came_back", [False, True])
    async def test_a_dormant_loop_wakes_only_on_the_users_own_activity_never_the_digest(
        self, world: World, monkeypatch: pytest.MonkeyPatch, came_back: bool
    ) -> None:
        _dormant(world)
        world.replies = [_weekly()]
        monkeypatch.setattr(wind_down, "latest_activity_since", _LATEST_ACTIVITY_SINCE)
        last_active = _DORMANT_SINCE + (timedelta(days=1) if came_back else -timedelta(days=1))
        monkeypatch.setattr(
            user_repository,
            "get_activity_dates",
            AsyncMock(
                side_effect=lambda user_id: UserActivityDates(last_active_at=last_active)
                if user_id == _USER
                else None
            ),
        )

        outcome = await run_brief(_USER, BriefingKind.WEEKLY)

        assert outcome is (BriefingRunOutcome.SENT if came_back else BriefingRunOutcome.DORMANT)
        assert bool(world.clear_wind_down.await_count) is came_back
        assert bool(world.upsert.await_count) is came_back


class TestAQuietWeek:
    async def test_an_empty_week_sends_the_quiet_note_and_never_an_edition(
        self, world: World
    ) -> None:
        world.calendar = []
        world.reads["list_completed_since"].return_value = []

        assert await run_brief(_USER, BriefingKind.WEEKLY) is BriefingRunOutcome.SENT

        world.composer.assert_not_awaited()
        world.voice.assert_not_awaited()
        world.render.assert_not_awaited()
        payload = world.stored()
        assert world.upsert.await_args.args[0].kind == "weekly"
        assert (payload.form, payload.kicker) == (BriefForm.QUIET_NOTE, WEEKLY_KICKER)
        assert payload.message == _expected_note(BriefingKind.WEEKLY, QuietFacts(calendar=None))

    @pytest.mark.regression
    async def test_a_weekly_only_readers_last_empty_digest_says_goodbye_before_winding_down(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: a weekly-only loop stopped silently after its third empty digest."""
        world.state.schedule = BriefingSchedule(frequency=BriefingFrequency.WEEKLY_ONLY)
        world.calendar = []
        world.reads["list_completed_since"].return_value = []
        _idle_day(monkeypatch, world, IDLE_DORMANT_DAYS)
        world.replies = [_weekly()]

        assert await run_brief(_USER, BriefingKind.WEEKLY) is BriefingRunOutcome.SENT

        assert world.weekly_prompt.call_args.kwargs["goodbye"] is True
        world.post.assert_awaited_once()
        world.enter_wind_down.assert_awaited_once_with(_USER)

    async def test_a_week_whose_goal_work_sat_stuck_is_recapped_never_quiet(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Replay: a quiet week dropped the stalled growth goal the old weekly recapped."""
        world.calendar = []
        world.reads["list_completed_since"].return_value = []
        goal = StatedGoal("Launch Atlas", GoalOrigin.MEMORY, terms=("Atlas",))
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[goal]))
        world.reads["list_open_user_todos"].return_value = [
            make_todo("Atlas pricing", id="a2", user_id=_USER, updated_at=_NOW - timedelta(days=9)),
            make_todo(
                "Atlas press list", id="a3", user_id=_USER, updated_at=_NOW - timedelta(days=2)
            ),
        ]
        world.composer.side_effect = lambda schema, _prompt, **_k: schema.model_validate(
            {"blocks": [_PROGRESS]}
        )
        world.replies = [_weekly()]

        await run_brief(_USER, BriefingKind.WEEKLY)

        assert world.stored().form is BriefForm.EDITION
        assert world.pool is not None
        [atlas] = world.pool.goals
        assert (atlas.statement, atlas.open, atlas.stalled) == (
            "Launch Atlas",
            2,
            ["Atlas pricing"],
        )

    async def test_a_quiet_week_note_goes_on_from_the_last_edition_and_is_counted(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.calendar = CalendarGap.UNAVAILABLE
        world.reads["list_completed_since"].return_value = []
        _seam(monkeypatch, world, BriefReads, "own_todos", _own_todos(3, 3))
        world.reads["list_open_user_todos"].return_value = [
            make_todo("Sort the garage", id="u9", user_id=_USER)
        ]
        edition = _brief("2026-10-05", BriefForm.EDITION, BriefingKind.WEEKLY)
        world.briefs_read(
            [_brief("2026-10-07", BriefForm.QUIET_NOTE, BriefingKind.WEEKLY), edition]
        )

        await run_brief(_USER, BriefingKind.WEEKLY)

        payload = world.stored()
        assert payload.message == _expected_note(
            BriefingKind.WEEKLY,
            QuietFacts(
                calendar=CalendarGap.UNAVAILABLE, overdue=3, still_quiet=True, last_edition=edition
            ),
        )
        assert (payload.lede, payload.caption, payload.template_family) == ("", "", None)
        channels = world.delivered_to(BriefingKind.WEEKLY)
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


# ---- Where the daily reader stands --------------------------------------------------------


def _dormant(world: World) -> None:
    world.user = UserDocument(id=_USER, timezone=_TZ, email="a@b.c")
    world.state = BriefingStateDocument(
        user_id=_USER, wind_down=BriefingWindDown(idle_days=3, wound_down_since=_DORMANT_SINCE)
    )


def _idle_day(monkeypatch: pytest.MonkeyPatch, world: World, streak: int) -> None:
    """Make today a day with nothing to report, at the given idle streak."""
    _goals_seam(monkeypatch, world, AsyncMock(return_value=[]))
    _seam(monkeypatch, world, wind_down, "record_idle_day", AsyncMock(return_value=streak))


def _situation(world: World) -> VoiceSituation:
    return world.voice_prompt.call_args.kwargs["situation"]


def _setup(world: World) -> str:
    return world.voice_prompt.call_args.kwargs["blocks"].setup


class TestTheGoalHold:
    """An existing user's first brief waits for a goal, but only through the grace window."""

    @staticmethod
    def _pending(world: World, since: datetime) -> None:
        world.user = UserDocument(id=_USER, timezone=_TZ, email="a@b.c")
        world.state = BriefingStateDocument(
            user_id=_USER, bootstrap=BriefingBootstrap(pending=True, since=since)
        )

    @pytest.mark.parametrize(
        "since", [_NOW - timedelta(days=1), (_NOW - timedelta(days=1)).replace(tzinfo=None)]
    )
    async def test_inside_the_grace_window_without_a_goal_nothing_is_sent(
        self, world: World, monkeypatch: pytest.MonkeyPatch, since: datetime
    ) -> None:
        self._pending(world, since)
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[]))

        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.BOOTSTRAP_PENDING

        world.voice.assert_not_awaited()
        world.nothing_sent()

    @pytest.mark.parametrize("age", [timedelta(days=3), timedelta(days=4)])
    async def test_once_the_grace_window_has_passed_the_brief_goes_out(
        self, world: World, monkeypatch: pytest.MonkeyPatch, age: timedelta
    ) -> None:
        self._pending(world, _NOW - age)
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[]))

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
        world.user = UserDocument(id=_USER, timezone=_TZ)
        world.state = BriefingStateDocument(
            user_id=_USER, bootstrap=BriefingBootstrap(pending=False, since=_NOW)
        )
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[]))

        await run_brief(_USER, BriefingKind.DAILY)

        world.upsert.assert_awaited()

    async def test_a_user_never_held_has_nothing_to_clear(self, world: World) -> None:
        await run_brief(_USER, BriefingKind.DAILY)

        world.clear_bootstrap.assert_not_awaited()


class TestTheIdleLadder:
    """Nothing to report escalates to a warning, then one goodbye, then dormancy."""

    async def test_a_dormant_user_who_came_back_is_woken_and_briefed(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _dormant(world)
        _seam(monkeypatch, world, wind_down, "latest_activity_since", AsyncMock(return_value=_NOW))

        await run_brief(_USER, BriefingKind.DAILY)

        (user_id, since), _ = world.reads["latest_activity_since"].await_args
        assert (user_id, since) == (_USER, _DORMANT_SINCE)
        world.clear_wind_down.assert_awaited_once_with(_USER)
        assert world.reads["record_idle_day"].await_args.args[1] == BriefingWindDown(
            idle_days=0, date=None, wound_down_since=None
        )
        world.upsert.assert_awaited()

    async def test_a_woken_user_asked_for_a_goal_two_days_ago_is_not_asked_again(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _dormant(world)
        assert world.state.wind_down is not None
        world.state.wind_down.goal_asked_at = _NOW - timedelta(days=2)
        _goals_seam(monkeypatch, world, AsyncMock(return_value=[]))
        _seam(monkeypatch, world, wind_down, "latest_activity_since", AsyncMock(return_value=_NOW))

        await run_brief(_USER, BriefingKind.DAILY)

        world.goal_asked.assert_not_awaited()
        assert _situation(world).goal_asked_recently is True

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
        goals = [StatedGoal("Ship v2", GoalOrigin.ONBOARDING)] if has_goal else []
        _goals_seam(monkeypatch, world, AsyncMock(return_value=goals))

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.reads["record_idle_day"].await_args.args[2] is idle

    @pytest.mark.parametrize(
        ("has_goal", "asked_days_ago", "asks"),
        [
            (True, None, True),
            (True, 2, False),
            (True, 7, True),
            (False, None, True),
            (False, 2, False),
            (False, 7, True),
        ],
        ids=[
            "goal-never-asked",
            "goal-asked-two-days-ago",
            "goal-asked-a-week-ago",
            "no-goal-never-asked",
            "no-goal-asked-two-days-ago",
            "no-goal-asked-a-week-ago",
        ],
    )
    async def test_the_goal_is_asked_about_or_for_once_a_week_and_each_ask_is_recorded(
        self,
        world: World,
        monkeypatch: pytest.MonkeyPatch,
        has_goal: bool,
        asked_days_ago: int | None,
        asks: bool,
    ) -> None:
        asked_at = None if asked_days_ago is None else _NOW - timedelta(days=asked_days_ago)
        world.user = UserDocument(id=_USER, timezone=_TZ, email="a@b.c")
        world.state = BriefingStateDocument(
            user_id=_USER, wind_down=BriefingWindDown(goal_asked_at=asked_at)
        )
        goals = [StatedGoal("Ship v2", GoalOrigin.ONBOARDING)] if has_goal else []
        _goals_seam(monkeypatch, world, AsyncMock(return_value=goals))
        _seam(monkeypatch, world, wind_down, "latest_activity_since", AsyncMock(return_value=_NOW))

        await run_brief(_USER, BriefingKind.DAILY)

        assert _situation(world).goal_asked_recently is not asks
        assert world.goal_asked.await_count == int(asks)

    @pytest.mark.parametrize(("idle_days", "stage"), [(2, WindDown.WARN), (3, WindDown.FINAL)])
    async def test_the_idle_streak_sets_the_wind_down_and_the_goodbye_goes_dormant(
        self, world: World, monkeypatch: pytest.MonkeyPatch, idle_days: int, stage: WindDown
    ) -> None:
        _idle_day(monkeypatch, world, idle_days)

        await run_brief(_USER, BriefingKind.DAILY)

        assert _situation(world).wind_down == stage
        if stage is WindDown.FINAL:
            world.enter_wind_down.assert_awaited_once_with(_USER)
        else:
            world.enter_wind_down.assert_not_awaited()

    async def test_the_wind_down_message_is_pushed_even_on_an_empty_day(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _idle_day(monkeypatch, world, 2)
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

        assert _situation(world).wind_down is None
        world.enter_wind_down.assert_not_awaited()

    @pytest.mark.parametrize(("idle_days", "voiced_winback"), [(0, True), (3, False)])
    async def test_a_winback_is_voiced_unless_the_brief_is_winding_down(
        self,
        world: World,
        monkeypatch: pytest.MonkeyPatch,
        idle_days: int,
        voiced_winback: bool,
    ) -> None:
        _winback(monkeypatch, world)
        _idle_day(monkeypatch, world, idle_days)

        await run_brief(_USER, BriefingKind.DAILY)

        assert _situation(world).winback is voiced_winback
        assert world.stored().mood == "winback"

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

        assert _situation(world).is_first_briefing is True


class TestTheFirstWeek:
    """A new account's first week helps it get value instead of winding down."""

    async def test_a_first_week_account_never_climbs_the_idle_ladder(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.user.created_at = _NOW - timedelta(days=FIRST_WEEK_DAYS, seconds=-1)
        _idle_day(monkeypatch, world, IDLE_DORMANT_DAYS)

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.reads["record_idle_day"].await_args.args[2] is False
        assert (_situation(world).wind_down, _situation(world).first_week) == (None, True)
        world.enter_wind_down.assert_not_awaited()

    async def test_the_ladder_runs_once_the_first_week_is_over(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.user.created_at = _NOW - timedelta(days=FIRST_WEEK_DAYS)
        _idle_day(monkeypatch, world, IDLE_DORMANT_DAYS)

        await run_brief(_USER, BriefingKind.DAILY)

        assert world.reads["record_idle_day"].await_args.args[2] is True
        assert (_situation(world).wind_down, _situation(world).first_week) == (
            WindDown.FINAL,
            False,
        )
        world.enter_wind_down.assert_awaited_once_with(_USER)

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

        assert _setup(world) == line

    async def test_an_older_account_is_shown_no_setup(self, world: World) -> None:
        world.user.created_at = _NOW - timedelta(days=30)
        world.connected_apps = ["Gmail"]

        await run_brief(_USER, BriefingKind.DAILY)

        assert _setup(world) == ""


class TestTheLighterCadenceOffer:
    """A user who stopped coming back is offered fewer briefs, with their real cadence."""

    async def test_an_idle_user_is_offered_a_lighter_cadence_beside_their_cadence(
        self, world: World
    ) -> None:
        world.activity = ActivityStatus.IDLE
        world.state.schedule = BriefingSchedule(frequency=BriefingFrequency.WEEKDAYS, hour=9)

        await run_brief(_USER, BriefingKind.DAILY)

        assert _situation(world).offer_lighter_cadence is True
        [cadence] = _setup(world).splitlines()
        assert cadence.startswith(
            f"Their briefs now: a daily brief Monday to Friday at 9:{_SLOT_MINUTE} AM"
        )

    async def test_a_first_week_idle_user_sees_their_cadence_and_apps_on_separate_lines(
        self, world: World
    ) -> None:
        world.activity = ActivityStatus.IDLE
        world.user.created_at = _NOW - timedelta(days=1)
        world.connected_apps = ["Gmail"]

        await run_brief(_USER, BriefingKind.DAILY)

        assert _setup(world).splitlines() == [
            f"Their briefs now: a daily brief every day at 8:{_SLOT_MINUTE} AM, plus the weekly "
            f"digest on Sunday at 5:{_SLOT_MINUTE} PM.",
            "Apps they've connected: Gmail.",
        ]

    async def test_an_active_user_is_not(self, world: World) -> None:
        await run_brief(_USER, BriefingKind.DAILY)

        assert (_situation(world).offer_lighter_cadence, _setup(world)) == (False, "")


# ---- How a run ends -----------------------------------------------------------------------


class TestHowARunEnds:
    @pytest.mark.parametrize("kind", [BriefingKind.DAILY, BriefingKind.WEEKLY])
    async def test_an_unknown_user_fails_loud(self, world: World, kind: BriefingKind) -> None:
        world.user = UserDocument(id=make_user_id(), timezone=_TZ)

        with pytest.raises(errors.BriefingGenerationError, match=f"unknown user {_USER}$"):
            await run_brief(_USER, kind)

        world.voice.assert_not_awaited()

    async def test_a_dormant_user_without_activity_is_skipped_before_the_model(
        self, world: World
    ) -> None:
        _dormant(world)

        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.DORMANT

        world.voice.assert_not_awaited()
        world.nothing_sent()

    async def test_an_ignored_winback_backs_off(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seam(
            monkeypatch,
            world,
            daily,
            "compute_winback_state",
            AsyncMock(return_value=WinbackState(unacknowledged=5, last_was_winback=True)),
        )

        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.WINBACK_BACKOFF

        world.voice.assert_not_awaited()
        world.nothing_sent()

    @pytest.mark.parametrize("kind", [BriefingKind.DAILY, BriefingKind.WEEKLY])
    async def test_a_brief_already_delivered_today_is_not_sent_again(
        self, world: World, kind: BriefingKind
    ) -> None:
        await run_brief(_USER, kind)
        for seam in (world.voice, world.upsert, world.notify, world.post):
            seam.reset_mock()

        assert await run_brief(_USER, kind) is BriefingRunOutcome.ALREADY_DELIVERED

        world.voice.assert_not_awaited()
        world.nothing_sent()

    async def test_a_failed_delivery_records_no_channels_and_clears_nothing(
        self, world: World
    ) -> None:
        world.held = [_held("h1", "Paper digest", _DIGEST_REPORT)]
        world.notify.side_effect = RuntimeError("orchestrator down")

        with pytest.raises(RuntimeError):
            await run_brief(_USER, BriefingKind.DAILY)

        world.upsert.assert_awaited()
        assert all(b.delivered_channels == [] for b in world.briefs.values())
        world.post.assert_not_awaited()
        world.consume.assert_not_awaited()

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
        assert world.delivered_to() == [*_ORCHESTRATED, "telegram"]
        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.ALREADY_DELIVERED

    @pytest.mark.regression
    async def test_a_resumed_goodbye_still_puts_the_loop_to_sleep_and_spends_its_draw(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A goodbye whose delivery died was finished on the retry, but the loop never went dormant."""
        _idle_day(monkeypatch, world, IDLE_DORMANT_DAYS)
        world.post.side_effect = RuntimeError("worker killed")
        with pytest.raises(RuntimeError, match="worker killed"):
            await run_brief(_USER, BriefingKind.DAILY)
        world.enter_wind_down.assert_not_awaited()
        world.post.side_effect = None

        assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        world.enter_wind_down.assert_awaited_once_with(_USER)
        world.goal_asked.assert_awaited_once_with(_USER)
        assert BriefingBag.EDITION_FAMILY.value in world.bags

    @pytest.mark.regression
    async def test_a_resumed_brief_marks_what_it_placed_shown(self, world: World) -> None:
        world.scouts = _scouted(_LOGIN)
        world.post.side_effect = RuntimeError("worker killed")
        with pytest.raises(RuntimeError, match="worker killed"):
            await run_brief(_USER, BriefingKind.DAILY)
        world.shown.assert_not_awaited()
        world.post.side_effect = None

        await run_brief(_USER, BriefingKind.DAILY)

        world.shown.assert_awaited_once_with(
            _USER, [Sighting("linear", _LOGIN.external_id, _LOGIN.state)], _NOW
        )

    async def test_each_delivery_step_is_recorded_once_it_succeeds(self, world: World) -> None:
        await run_brief(_USER, BriefingKind.DAILY)

        [brief] = world.briefs.values()
        assert brief.delivery is not None
        assert brief.delivery.done == [
            DeliveryStep.NOTIFICATION,
            DeliveryStep.CONVERSATION,
            DeliveryStep.CHAT,
        ]

    @pytest.mark.parametrize("result", [OutboundResult.SKIPPED, OutboundResult.FAILED])
    async def test_a_chat_post_that_did_not_publish_records_no_platform(
        self, world: World, result: OutboundResult
    ) -> None:
        world.post.return_value = result

        await run_brief(_USER, BriefingKind.DAILY)

        world.post.assert_awaited_once()
        assert world.delivered_to() == _ORCHESTRATED

    async def test_an_unsent_email_is_reported_with_every_channels_status(
        self, world: World
    ) -> None:
        world.notify.return_value = SimpleNamespace(
            channels=[
                _delivered("inapp"),
                ChannelDeliveryStatus(channel_type="email", status=NotificationStatus.FAILED),
            ]
        )

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        [warning] = [w for w in event["warnings"] if w["msg"] == "briefing.email_not_sent"]
        assert warning["statuses"] == {"inapp": "delivered", "email": "failed"}

    async def test_a_brief_that_asked_for_no_email_reports_none_unsent(self, world: World) -> None:
        world.user.email = None
        world.notify.return_value = SimpleNamespace(channels=[_delivered("inapp")])

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        assert [c.channel_type for c in world.notify.await_args.args[0].channels] == ["inapp"]
        assert "briefing.email_not_sent" not in [w["msg"] for w in event.get("warnings", [])]

    async def test_a_resumed_delivery_reports_the_channels_earlier_steps_reached(
        self, world: World
    ) -> None:
        stored = _brief(_DATE, BriefForm.QUIET_NOTE, message="Gym").model_copy(
            update={
                "delivered_channels": ["telegram"],
                "delivery": BriefDelivery(
                    push=True,
                    notification_kind=NotificationKind.BRIEFING_NOTE,
                    done=[DeliveryStep.CHAT],
                ),
            }
        )
        world.briefs[stored.id] = stored

        async with captured_wide_event() as event:
            assert await run_brief(_USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        assert event["briefing"]["channels"] == ["telegram", *_ORCHESTRATED]

    async def test_a_brief_stored_without_a_delivery_plan_is_not_delivered(
        self, world: World
    ) -> None:
        stored = _brief(_DATE, BriefForm.EDITION, message="Gym")

        with pytest.raises(
            ValueError, match=f"^brief {stored.id} was stored without a delivery plan$"
        ):
            await delivery.deliver_brief(world.user, stored)

        world.notify.assert_not_awaited()

    async def test_resuming_an_edition_brief_stored_without_its_edition_fails_loud(
        self, world: World
    ) -> None:
        stored = _brief(_DATE, BriefForm.EDITION, message="Gym", link=_BRIEF_LINK).model_copy(
            update={
                "delivery": BriefDelivery(
                    push=True,
                    notification_kind=NotificationKind.BRIEFING_DAILY,
                    done=[DeliveryStep.CHAT],
                )
            }
        )
        world.briefs[stored.id] = stored

        with pytest.raises(ValueError, match=f"^briefing_daily brief {stored.id} was stored"):
            await run_brief(_USER, BriefingKind.DAILY)

        world.notify.assert_not_awaited()

    async def test_a_stalled_voice_fails_the_run_instead_of_hanging(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def stall(*_: object, **__: object) -> None:
            await asyncio.Event().wait()

        world.voice.side_effect = stall
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
        world.nothing_sent()


# ---- What a run reads and records ---------------------------------------------------------


class TestTheDailyRunReads:
    """Every read is scoped to the user and the last local day."""

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
            payload=make_briefing_payload(date="d"),
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
            _USER, wind_down.ladder_state(world.state), False, _DATE
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


class TestWhatARunRecords:
    async def test_the_wide_event_tags_the_run_and_records_its_pool_and_where_it_went(
        self, world: World
    ) -> None:
        world.work = _brief_work()

        async with captured_wide_event() as event:
            await run_brief(_USER, BriefingKind.DAILY)

        assert (event["component"], event["operation"], event["user_id"]) == (
            "briefing",
            "run_brief",
            _USER,
        )
        assert event["brief_composition"]["pool_items"] == 3
        briefing = event["briefing"]
        assert briefing["channels"] == [*_ORCHESTRATED, "telegram"]
        assert (briefing["pushed"], briefing["form"]) == (True, "edition")
        assert (briefing["kind"], briefing["outcome"]) == ("daily", "sent")

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
            return REGISTRY.get_sample_value("gaia_brief_run_total", labels) or 0.0

        sent, failed = count("sent"), count("failed")
        await run_brief(_USER, BriefingKind.DAILY)
        world.briefs.clear()
        world.notify.side_effect = RuntimeError("orchestrator down")
        with pytest.raises(RuntimeError, match="orchestrator down"):
            await run_brief(_USER, BriefingKind.DAILY)

        assert (count("sent") - sent, count("failed") - failed) == (1.0, 1.0)

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

        assert world.delivered_to() == ["inapp"]
        assert world.capture.call_args.args[1].channel_count == 1

    async def test_a_sent_brief_reports_one_event_counting_what_it_holds(
        self, world: World
    ) -> None:
        world.work = _brief_work()
        world.reads["list_completed_since"].return_value = _completions(
            [_tracked("c1", "Investor update")]
        )
        world.family_first(EditionFamily.MEMO)

        await run_brief(_USER, BriefingKind.DAILY)

        payload = world.stored()
        assert world.delivered_to() == [*_ORCHESTRATED, "telegram"]
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

    async def test_a_chart_in_the_brief_is_counted_among_its_blocks(self, world: World) -> None:
        world.work = _brief_work()
        world.reads["list_completed_since"].return_value = _completions(
            [_tracked("c1", "Investor update")]
        )
        world.composer.side_effect = _with_block(
            _composed({"Waiting": ["Approve the Priya reply"]}), _CHART
        )

        await run_brief(_USER, BriefingKind.DAILY)

        event = world.capture.call_args.args[1]
        assert (event.block_kinds, event.chart_count) == (["items", "chart"], 1)
