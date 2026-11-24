"""The world one brief run reads and writes, for the run's unit tests under tests/unit/services/briefing/run.

Faked only where the run leaves the process: its stores (in-memory, tests/briefing_store_fakes), the
model, memory recall, the scouts, Google Calendar, the edition render and blob store, links, the
notification orchestrator, the chat platform, the Briefings conversation and PostHog; the clock is
frozen. Everything between runs for real. The stand-in model answers from what the run built for it
(the fact pool it composes over, the facts the voice is held to), never from a prompt's words.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError
import pytest
import time_machine

from app.agents.llm.exceptions import MalformedStructuredOutputError
from app.agents.prompts.briefing_prompts import (
    VoiceSituation,
    build_briefing_voice_prompt,
    build_weekly_voice_prompt,
)
from app.config.settings import settings
from app.constants.briefing import (
    GAIA_APP_NAME,
    MAX_BRIEF_BLOCKS,
    MAX_ITEMS_PER_BLOCK,
    PLAIN_BRIEF_HEADLINE,
    WINBACK_THRESHOLD,
    BriefAction,
    BriefForm,
    BriefingBag,
    BriefingKind,
    BriefItemSource,
    BriefOutcome,
    EditionFamily,
)
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.memory import MemoryEntityType, MemoryKind
from app.constants.notifications import BriefNotificationKind, NotificationKind
from app.constants.todos import FAILED_LABEL, GAIA_TRACKED_LABEL, TodoCompleter, WaitingOn
from app.constants.workflows import WorkflowDelivery
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.briefing_state import briefing_state_repository
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.email_verdicts import email_verdict_repository
from app.db.repositories.pending_brief_items import pending_brief_items_repository
from app.db.repositories.reminders import reminder_repository
from app.db.repositories.signal_memory import signal_memory_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.memory.engine import memory_engine
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import BriefComposition
from app.models.brief_document_models import BriefDelivery, BriefingModel, DeliveryStep
from app.models.brief_models import PendingBriefItemDocument
from app.models.brief_payload_models import BriefingEvent, BriefingPayload, BriefVoice
from app.models.briefing_state_models import BriefingStateDocument, BriefingWindDown, ShuffleBag
from app.models.calendar_models import GoogleCalendarEventDateTime, GoogleCalendarEventResource
from app.models.chat_models import ConversationSource
from app.models.memory_models import (
    MemoryEntityRef,
    MemoryEntry,
    MemorySearchResult,
)
from app.models.notification.notification_models import ChannelDeliveryStatus, NotificationStatus
from app.models.scout_models import (
    ScoutOutcome,
    ScoutResult,
    ScoutSkipReason,
    Signal,
    SignalImportance,
    SignalMemoryDocument,
)
from app.models.short_link_models import RecordTarget, ShortLink
from app.models.todo_models import TodoDocument
from app.models.user_models import UserDocument
from app.models.workflow_execution_models import WorkflowExecutionDocument
from app.models.workflow_models import TriggerConfig, TriggerType, WorkflowDocument
from app.services.briefing import (
    calendar_read,
    checked_call,
    daily,
    delivery,
    pipeline,
    prose,
    publish,
    store,
    weekly,
)
from app.services.briefing.calendar_read import CalendarGap
from app.services.briefing.clock import resolve_clock
from app.services.briefing.composition import headings as composition_headings
from app.services.briefing.composition.headings import HeadingVerdict, HeadingVerdicts
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.editions.stamps import stamp_weights
from app.services.briefing.fact_pool.pool import FactPool, build_fact_pool
from app.services.briefing.facts import FactSources, build_facts
from app.services.briefing.goals import StatedGoal
from app.services.briefing.kinds import KIND_SPECS
from app.services.briefing.prose import Voiced, Writing
from app.services.briefing.quiet_note import QuietFacts, quiet_note
from app.services.briefing.scouts import service as scout_service
from app.services.briefing.slots import BriefFact
from app.services.briefing.wind_down import ladder_state
from app.services.briefing.work import TrackedWork
from app.services.delivery.chat_channel import ChatChannel, InApp
from app.services.notification_service import notification_service
from app.services.outbound_delivery import OutboundResult
from app.services.render.image import RenderedImage
from app.workers.brief_slots import slot_minute
from tests.briefing_factories import make_briefing_payload
from tests.briefing_store_fakes import (
    InMemoryApprovalLedger,
    InMemoryBriefings,
    InMemoryBriefingState,
    InMemoryConversations,
    InMemoryEmailVerdicts,
    InMemoryPendingBriefItems,
    InMemoryReminders,
    InMemorySignalMemory,
    InMemoryTodos,
    InMemoryUserIntegrations,
    InMemoryUsers,
    InMemoryWorkflowExecutions,
    InMemoryWorkflows,
    install,
)
from tests.factories import make_todo, make_user_id

USER = make_user_id()
TZ = "Asia/Kolkata"
#: The minute past the hour the user's brief slots land at.
SLOT_MINUTE = f"{slot_minute(USER):02d}"
# 07:05 in Kolkata on Wednesday 14 October 2026.
NOW = datetime(2026, 10, 14, 1, 35, tzinfo=UTC)
DATE = "2026-10-14"
#: Yesterday's local midnight: where the look-back starts after yesterday's brief.
DAY_START = datetime(2026, 10, 12, 18, 30, tzinfo=UTC)
#: Monday's local midnight: where the week the digest recaps starts.
WEEK_START = datetime(2026, 10, 11, 18, 30, tzinfo=UTC)
TODAY_START = datetime(2026, 10, 13, 18, 30, tzinfo=UTC)
#: The end of the week ahead the weekly lists: seven local days from tomorrow.
WEEK_AHEAD_END = TODAY_START + timedelta(days=8)
EVENT = BriefingEvent(date="2026-10-14", start="11:00", title="Sequoia")
FRIDAY_PITCH = BriefingEvent(date="2026-10-16", start="15:00", title="Pitch to Accel")
CHAT = ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-1", basis="priority")
RENDERED = RenderedImage(image=b"edition-png", fold=0.3, paper=(0.1, 0.2, 0.9, 0.8))
BRIEF_ID = "brief_abc123"
EDITION_KEY = "edition0key0of0the0brief0abc0123"
EDITION_URL = f"{settings.HOST}/api/v1/briefings/editions/{EDITION_KEY}/png?t="
CHAT_EDITION_URL = f"{settings.HOST}/api/v1/briefings/editions/{EDITION_KEY}/jpg?t="
BRIEF_LINK = f"{settings.SHORTLINK_BASE_URL}/briefabc123"
ORCHESTRATED = ["inapp", "email"]
DIGEST_REPORT = "3 new papers on retrieval\nThe longest is 40 pages; two cite your draft."
#: When the default world's completions were finished: inside every window a run reads.
JUST_NOW = NOW - timedelta(hours=1)
DORMANT_SINCE = datetime(2026, 10, 1, tzinfo=UTC)
#: When the default reader was last active: inside the week that keeps them active, before any brief.
LAST_SEEN = NOW - timedelta(days=6)
#: When an idle reader was last active: past the week that keeps a reader active.
IDLE_SINCE = NOW - timedelta(days=8)
SHIP_V2 = StatedGoal("Ship v2")

# ---- The stand-in model ------------------------------------------------------------------

#: In a scripted voice field, one title slot per fact the voice is held to, in their order.
EVERY_FACT = "<every fact>"
#: In a scripted voice field, the id of the fact whose title holds TITLE.
_FACT_OF = re.compile(r"<fact of ([^>]+)>")

VOICE: dict[str, str] = {
    "headline": "Your morning, sorted",
    "lede": "Everything else is moving.",
    "caption": "Onward.",
    "mood": "packed",
    "message": EVERY_FACT,
}
WEEKLY_VOICE: dict[str, str] = {
    "headline": "A good week",
    "lede": "The deck went out and the CRM sync needs a look.",
    "caption": "Same time next week.",
    "mood": "weekly",
    "message": EVERY_FACT,
}

#: A scripted answer of the voice: its fields, or the error its structured call raises.
Reply = dict[str, str] | Exception


def fact_id(writing: Writing, title: str) -> int:
    found = [n for n, fact in writing.values.facts.items() if title in fact.title]
    assert found, f"no fact the voice was shown is titled {title!r}"
    return found[0]


def _filled(writing: Writing, text: str) -> str:
    """Fill a scripted field's tokens from the facts the voice is held to."""
    text = _FACT_OF.sub(lambda m: str(fact_id(writing, m.group(1))), text)
    every = "\n".join(f"[[fact:{n}]]" for n in writing.values.facts) or "A quiet day."
    return text.replace(EVERY_FACT, every)


def wrote(message: str, **fields: str) -> dict[str, str]:
    return {**VOICE, "message": message, **fields}


def weekly_reply(**fields: str) -> dict[str, str]:
    return {**WEEKLY_VOICE, **fields}


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


def items_block(heading: str, items: list[dict[str, object]]) -> dict[str, object]:
    return {"kind": "items", "state": _group_state(items), "heading": heading, "items": items}


def composes_by_state(
    schema: type[BriefComposition], _prompt: str, *, pool: FactPool, **_: object
) -> BriefComposition:
    """Stand in for the composer: what asks, then GAIA's work done, then running, then the apps'.

    A group runs to as many blocks as its items fill, up to the brief's last block.
    """
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
    blocks = [
        items_block(h, items[n : n + MAX_ITEMS_PER_BLOCK])
        for h, items in groups.items()
        for n in range(0, len(items), MAX_ITEMS_PER_BLOCK)
    ]
    return schema.model_validate({"blocks": blocks[:MAX_BRIEF_BLOCKS]})


def composed(
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
        blocks += [items_block(h, [placed(t) for t in titles]) for h, titles in groups.items()]
        return schema.model_validate({"blocks": blocks})

    return answer


def with_block(
    composer: Callable[..., BriefComposition], block: dict[str, object]
) -> Callable[..., BriefComposition]:
    """Stand in for composer, adding block after what it placed."""

    def answer(schema: type[BriefComposition], prompt: str, **kw: object) -> BriefComposition:
        placed = [b.model_dump() for b in composer(schema, prompt, **kw).blocks]
        return schema.model_validate({"blocks": [*placed, block]})

    return answer


CHART: dict[str, object] = {
    "kind": "chart",
    "chart": "bar",
    "series_ids": ["gaia_finished"],
    "title": "Finished",
    "takeaway": "One thing done.",
}
PROGRESS: dict[str, object] = {"kind": "progress", "goal_id": "g1"}


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


def salvaged(event: dict[str, Any], call_name: str) -> list[dict[str, Any]]:
    """Return the run's salvages of one checked call: voice or composition."""
    return [
        e
        for e in event["errors"]
        if e["msg"] == "briefing.checked_call_salvaged" and e["call"] == call_name
    ]


# ---- What the stores hold -----------------------------------------------------------------


def tracked(todo_id: str, title: str, **fields: Any) -> TodoDocument:
    """Return one of GAIA's tracked todos for the user."""
    return make_todo(title, GAIA_TRACKED_LABEL, id=todo_id, user_id=USER, **fields)


def own(todo_id: str, title: str, **fields: Any) -> TodoDocument:
    """Return one of the user's own todos."""
    return make_todo(title, id=todo_id, user_id=USER, **fields)


def brief_work() -> TrackedWork:
    return TrackedWork(
        blocked=[tracked("b1", "Approve the Priya reply")],
        completed=[tracked("c1", "Investor update")],
    )


def held(item_id: str, title: str, text: str) -> PendingBriefItemDocument:
    return PendingBriefItemDocument(
        id=item_id,
        user_id=USER,
        source=BriefItemSource.WORKFLOW,
        source_id=f"wf-{item_id}",
        source_title=title,
        conversation_id=f"conv-{item_id}",
        text=text,
    )


def from_google(event: BriefingEvent) -> GoogleCalendarEventResource:
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


def delivered(channel: str) -> ChannelDeliveryStatus:
    return ChannelDeliveryStatus(channel_type=channel, status=NotificationStatus.DELIVERED)


def notified(*channels: ChannelDeliveryStatus) -> SimpleNamespace:
    """Return what notification_service.notify does: the stored record, here only its channels."""
    return SimpleNamespace(record=SimpleNamespace(channels=list(channels)))


def skipped(app: str, reason: ScoutSkipReason = ScoutSkipReason.FAILED) -> ScoutResult:
    return ScoutResult(
        integration_id=app.lower(), app=app, outcome=ScoutOutcome.SKIPPED, skip_reason=reason
    )


def completions(
    gaia: Sequence[TodoDocument] = (), user: Sequence[TodoDocument] = ()
) -> list[TodoDocument]:
    """Return todos as the store holds them once completed: by whom, and when."""
    return [
        d.model_copy(
            update={
                "completed": True,
                "completed_by": by,
                "completed_at": d.completed_at or JUST_NOW,
            }
        )
        for docs, by in ((gaia, TodoCompleter.GAIA), (user, TodoCompleter.USER))
        for d in docs
    ]


def own_open(count: int, overdue: int = 0) -> list[TodoDocument]:
    """Return count open todos of the user's own, overdue of them due before today began."""
    return [
        own(
            f"own-{n}",
            f"Own todo {n}",
            due_date=DAY_START if n < overdue else None,
            updated_at=NOW - timedelta(minutes=n),
        )
        for n in range(count)
    ]


def failed_run(world: World, *, started_at: datetime = NOW - timedelta(days=1)) -> None:
    """Have the CRM sync workflow fail."""
    world.executions.rows.append(
        WorkflowExecutionDocument(
            execution_id="e1",
            workflow_id="wf-sync",
            user_id=USER,
            status="failed",
            started_at=started_at,
            error_message="HubSpot token expired",
        )
    )
    world.workflows.rows.append(
        WorkflowDocument(
            delivery=WorkflowDelivery.NOW,
            id="wf-sync",
            user_id=USER,
            title="CRM sync",
            prompt="Sync the CRM",
            steps=[],
            trigger_config=TriggerConfig(type=TriggerType.MANUAL, enabled=True),
        )
    )


def a_full_week(world: World) -> None:
    """Fill every weekly source: GAIA's and the user's work, a failed run and an event ahead."""
    failed_run(world)
    deck = tracked("g1", "Investor deck", canvas_content="# Deck\nFinal numbers in")
    world.todos.rows.clear()
    world.todos.add(*completions([deck], [own("u1", "Send the deck")]))
    world.calendar = [FRIDAY_PITCH]


LOGIN = Signal(
    integration_id="linear",
    app="Linear",
    external_id="ENG-12",
    kind="issue assigned to you",
    title="Fix the login redirect",
    importance=SignalImportance.HIGH,
    url="https://linear.app/acme/issue/ENG-12",
    state="In Progress",
)
DOCS = Signal(
    integration_id="linear",
    app="Linear",
    external_id="ENG-40",
    kind="issue assigned to you",
    title="Refresh the onboarding docs",
    url="https://linear.app/acme/issue/ENG-40",
    state="Todo",
)


def scouted(*signals: Signal) -> list[ScoutResult]:
    return [
        ScoutResult(
            integration_id="linear", app="Linear", outcome=ScoutOutcome.REPLAYED, signals=[*signals]
        )
    ]


def remembered(external_id: str, last_state: str) -> SignalMemoryDocument:
    return SignalMemoryDocument(
        user_id=USER,
        integration_id="linear",
        external_id=external_id,
        first_seen=NOW - timedelta(days=3),
        times_shown=1,
        last_shown=NOW - timedelta(days=2),
        last_state=last_state,
    )


def delivered_plan(
    kind: BriefNotificationKind = NotificationKind.BRIEFING_DAILY,
) -> BriefDelivery:
    """Return the delivery of a brief that went out on every step."""
    return BriefDelivery(
        push=True, notification_kind=kind, done=list(DeliveryStep), completed_at=JUST_NOW
    )


def local_midnight(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(TZ)).astimezone(UTC)


def stored_brief(
    day: str, form: BriefForm, kind: BriefingKind = BriefingKind.DAILY, **payload: Any
) -> BriefingModel:
    """Return a brief of day as the store holds it once delivered, written at that day's local midnight."""
    note = form is BriefForm.QUIET_NOTE
    return BriefingModel(
        id=f"b-{day}-{kind}",
        user_id=USER,
        date=day,
        kind=kind,
        payload=make_briefing_payload(date=day, form=form, **payload),
        delivery=delivered_plan(
            NotificationKind.BRIEFING_NOTE
            if note
            else NotificationKind.BRIEFING_WEEKLY
            if kind is BriefingKind.WEEKLY
            else NotificationKind.BRIEFING_DAILY
        ),
        created_at=local_midnight(day),
    )


#: Yesterday's daily brief, which every default run follows; its lines are none the voice repeats.
YESTERDAY = stored_brief(
    "2026-10-13",
    BriefForm.EDITION,
    headline="Yesterday, in short",
    lede="A slower start.",
    caption="Until tomorrow.",
)


def _memory_fact(goal: StatedGoal, mentioned_at: datetime | None) -> MemoryEntry:
    return MemoryEntry(
        content=goal.statement,
        kind=MemoryKind.FACT,
        mentioned_at=mentioned_at,
        entities=[
            MemoryEntityRef(id=f"entity-{t}", name=t, entity_type=MemoryEntityType.PROJECT)
            for t in goal.terms
        ],
    )


# ---- The world the run reads and writes ---------------------------------------------------


@dataclass
class World:
    """The run's stores, held in memory, and its seams beyond the process, with what the run built."""

    users: InMemoryUsers
    briefings: InMemoryBriefings = field(default_factory=lambda: InMemoryBriefings(BRIEF_ID))
    states: InMemoryBriefingState = field(default_factory=InMemoryBriefingState)
    pending: InMemoryPendingBriefItems = field(default_factory=InMemoryPendingBriefItems)
    memories: InMemorySignalMemory = field(default_factory=InMemorySignalMemory)
    todos: InMemoryTodos = field(default_factory=InMemoryTodos)
    workflows: InMemoryWorkflows = field(default_factory=InMemoryWorkflows)
    executions: InMemoryWorkflowExecutions = field(default_factory=InMemoryWorkflowExecutions)
    verdicts: InMemoryEmailVerdicts = field(default_factory=InMemoryEmailVerdicts)
    approvals: InMemoryApprovalLedger = field(default_factory=InMemoryApprovalLedger)
    reminders: InMemoryReminders = field(default_factory=InMemoryReminders)
    conversations: InMemoryConversations = field(default_factory=InMemoryConversations)
    integrations: InMemoryUserIntegrations = field(default_factory=InMemoryUserIntegrations)
    #: Links: the URL each minted link becomes, by (user, target type, target id).
    mint: AsyncMock = field(default_factory=lambda: AsyncMock(return_value=BRIEF_LINK))
    notify: AsyncMock = field(
        default_factory=lambda: AsyncMock(
            return_value=notified(*(delivered(c) for c in ORCHESTRATED))
        )
    )
    post: AsyncMock = field(
        default_factory=lambda: AsyncMock(return_value=OutboundResult.PUBLISHED)
    )
    render: AsyncMock = field(default_factory=lambda: AsyncMock(return_value=RENDERED))
    store_edition: AsyncMock = field(default_factory=lambda: AsyncMock(return_value=EDITION_KEY))
    capture: MagicMock = field(default_factory=MagicMock)
    brief_message: AsyncMock = field(default_factory=AsyncMock)
    voice_prompt: MagicMock = field(
        default_factory=lambda: MagicMock(wraps=build_briefing_voice_prompt)
    )
    weekly_prompt: MagicMock = field(
        default_factory=lambda: MagicMock(wraps=build_weekly_voice_prompt)
    )
    #: What memory recalls of the user's goals: their facts, each one a goal.
    goals: list[StatedGoal] = field(default_factory=lambda: [SHIP_V2])
    #: When the user mentioned the goals memory recalls; None when memory kept no date.
    goals_mentioned_at: datetime | None = None
    chat: ChatChannel | None = CHAT
    scouts: list[ScoutResult] = field(default_factory=list)
    #: The composition model, answering from the pool; by default it groups every item by state.
    composer: AsyncMock = field(default_factory=lambda: AsyncMock(side_effect=composes_by_state))
    #: The voice's answers in order, the last one repeated: fields, or the error the call raises.
    replies: list[Reply] = field(default_factory=lambda: [VOICE])
    #: The voice model, answering replies from the facts it is held to.
    voice: AsyncMock = field(default_factory=AsyncMock)
    #: The heading check's model; by default every heading fits its items.
    headings: AsyncMock = field(default_factory=lambda: AsyncMock(side_effect=_every_heading_fits))
    #: What the user's calendar holds, as Google sends it, or why it went unread.
    calendar: list[BriefingEvent] | CalendarGap = field(default_factory=lambda: [EVENT])
    #: Google Calendar, answering from calendar.
    fetch_calendar: AsyncMock = field(default_factory=AsyncMock)
    #: What the run built: the fact pool, the facts' sources, the voice's writing, its signals.
    pool: FactPool | None = None
    fact_sources: FactSources | None = None
    writing: Writing | None = None
    signals: list[tuple[int, BriefCandidate]] = field(default_factory=list)

    @property
    def user(self) -> UserDocument:
        return self.users.rows[USER]

    @user.setter
    def user(self, user: UserDocument) -> None:
        self.users.rows = {USER: user} if user.id == USER else {}

    @property
    def state(self) -> BriefingStateDocument:
        return self.states.row(USER)

    @state.setter
    def state(self, state: BriefingStateDocument) -> None:
        self.states.rows[USER] = state

    @property
    def bags(self) -> dict[BriefingBag, ShuffleBag]:
        """The user's shuffle bags, as the stored briefing state holds them."""
        return self.state.shuffle_bags

    @property
    def held(self) -> list[PendingBriefItemDocument]:
        return self.pending.rows

    @held.setter
    def held(self, items: list[PendingBriefItemDocument]) -> None:
        self.pending.rows = list(items)

    @property
    def memory(self) -> list[SignalMemoryDocument]:
        return self.memories.rows

    @memory.setter
    def memory(self, rows: list[SignalMemoryDocument]) -> None:
        self.memories.rows = list(rows)

    @property
    def briefs(self) -> dict[str, BriefingModel]:
        """The briefings collection: each stored brief by id, as the run left it."""
        return self.briefings.rows

    def track(self, work: TrackedWork) -> None:
        """Store GAIA's tracked work as the todos collection holds it, each todo in its state."""
        self.todos.add(*completions(work.completed))
        self.todos.add(*(d.model_copy(update={"completed": False}) for d in work.running))
        self.todos.add(
            *(
                d.model_copy(update={"completed": False, "waiting_on": WaitingOn.USER})
                for d in work.blocked
            )
        )
        self.todos.add(
            *(
                d.model_copy(update={"completed": False, "labels": [*d.labels, FAILED_LABEL]})
                for d in work.failed
            )
        )

    def connect(self, *apps: str) -> None:
        """Connect the user's apps, by display name."""
        self.integrations.connect(USER, *(app.lower() for app in apps))

    def fact(self, title: str) -> BriefFact:
        """Return the fact titled title that the voice was held to."""
        assert self.writing is not None, "the voice was never asked"
        return self.writing.values.facts[fact_id(self.writing, title)]

    def today(self, kind: BriefingKind | None = None) -> BriefingModel | None:
        """Return the brief stored for today, of kind when given."""
        found = [b for b in self.briefs.values() if b.date == DATE and kind in (None, b.kind)]
        assert len(found) <= 1, f"more than one brief stored today: {[b.kind for b in found]}"
        return found[0] if found else None

    def stored(self) -> BriefingPayload:
        brief = self.today()
        assert brief is not None, "no brief was stored today"
        return brief.payload

    def delivered_to(self, kind: BriefingKind = BriefingKind.DAILY) -> list[str]:
        """Return the channels today's brief of kind reached, once its delivery completed."""
        brief = self.today(kind)
        assert brief is not None and brief.delivery is not None
        assert brief.delivery.completed_at is not None
        return brief.delivered_channels

    def sent_plainly(self) -> BriefingPayload:
        """Assert the brief still went out, voiced plainly from its facts: never nothing."""
        payload = self.stored()
        assert payload.headline == PLAIN_BRIEF_HEADLINE
        self.notify.assert_awaited()
        return payload

    def nothing_sent(self) -> None:
        assert self.today() is None, "a brief was stored today"
        self.notify.assert_not_awaited()
        self.post.assert_not_awaited()
        assert self.pending.consumed == []

    def family_first(self, family: EditionFamily) -> None:
        """Pin today's edition family; the default world pins Memo, as Air Mail adds a stamp line."""
        order = [f for f, n in DAILY_FAMILY_WEIGHTS.items() for _ in range(n)]
        order.remove(family)
        self.bags[BriefingBag.EDITION_FAMILY] = ShuffleBag(order=[family, *order], index=0)

    def stamp_first(self, city: str) -> None:
        """Pin today's Air Mail stamp: the pass over every hosted city opens on city."""
        others = sorted(set(stamp_weights()) - {city})
        self.bags[BriefingBag.STAMP_CITY] = ShuffleBag(order=[city, *others], index=0)

    def briefs_read(self, briefs: list[BriefingModel]) -> None:
        """Have the briefings collection hold exactly these briefs."""
        self.briefs.clear()
        self.briefs.update({b.id: b for b in briefs})


# ---- Where the reader stands ---------------------------------------------------------------


def dormant(world: World) -> None:
    """Have the loop wound down since DORMANT_SINCE, its reader stating no goal and never active since."""
    world.user = UserDocument(id=USER, timezone=TZ, email="a@b.c")
    world.goals = []
    world.state = BriefingStateDocument(
        user_id=USER, wind_down=BriefingWindDown(idle_days=3, wound_down_since=DORMANT_SINCE)
    )


def idle_day(world: World, streak: int) -> None:
    """Make today a day with nothing to report and no goal, reaching the given idle streak."""
    world.goals = []
    if streak:
        world.state.wind_down = BriefingWindDown(idle_days=streak - 1, date="2026-10-13")


def winback(world: World) -> None:
    """Have the last WINBACK_THRESHOLD daily briefs go out with the reader never active since."""
    days = ["2026-10-13", "2026-10-12", "2026-10-11"][:WINBACK_THRESHOLD]
    world.briefs_read(
        [
            stored_brief(
                day,
                BriefForm.EDITION,
                headline=f"Brief {n}",
                lede=f"Lede {n}.",
                caption=f"Caption {n}.",
            )
            for n, day in enumerate(days)
        ]
    )


def situation(world: World) -> VoiceSituation:
    return world.voice_prompt.call_args.kwargs["situation"]


def setup_block(world: World) -> str:
    return world.voice_prompt.call_args.kwargs["blocks"].setup


def idle_days(world: World) -> int:
    """Return the idle streak the stored ladder holds."""
    return ladder_state(world.state).idle_days


def quiet_day(world: World) -> None:
    """Nothing to place, nothing on the calendar and the goal asked yesterday: the ladder says nothing.

    The reader was active since, so no winback stands and the goal question was not ignored.
    """
    world.calendar = []
    world.state.wind_down = BriefingWindDown(goal_asked_at=NOW - timedelta(days=1))
    world.user.last_active_at = JUST_NOW


def shown_before(world: World, *todo_ids: str, times: int) -> None:
    """Have earlier briefs shown each todo times, waiting on the user as it still is."""
    world.memory = [
        SignalMemoryDocument(
            user_id=USER,
            integration_id="gaia",
            external_id=f"todo:{todo_id}",
            first_seen=NOW - timedelta(days=3),
            times_shown=times,
            last_shown=NOW - timedelta(days=1),
            last_state="you",
        )
        for todo_id in todo_ids
    ]


def expected_note(kind: BriefingKind, facts: QuietFacts) -> str:
    """Return the quiet note the quiet-note module writes on the run's clock for facts."""
    return quiet_note(resolve_clock(TZ), KIND_SPECS[kind], facts).message or ""


def todo_link(todo_id: str) -> str:
    return f"{settings.SHORTLINK_BASE_URL}/todo-{todo_id}"


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

    def facts(chosen: Any, sources: FactSources, values: Any, clock: Any) -> Any:
        w.fact_sources = sources
        w.signals = [(i, c) for picked in chosen.picked for i, c in picked if c.signal is not None]
        return build_facts(chosen, sources, values, clock)

    async def written(user_id: str, prompt: str, writing: Writing) -> Voiced:
        w.writing = writing
        return await prose.written_brief(user_id, prompt, writing)

    monkeypatch.setattr(pipeline, "build_fact_pool", pooled)
    monkeypatch.setattr(pipeline, "build_facts", facts)
    monkeypatch.setattr(pipeline, "written_brief", written)


def _attached(mint: AsyncMock) -> Callable[[str, RecordTarget], Awaitable[ShortLink | None]]:
    """Attach the link whose URL mint names, so a test states links as the URLs they become."""

    async def attach(user_id: str, target: RecordTarget) -> ShortLink | None:
        url = await mint(user_id, target.type, target.id)
        if url is None:
            return None
        slug = url.removeprefix(f"{settings.SHORTLINK_BASE_URL}/")
        return ShortLink(slug=slug, user_id=user_id, target=target)

    return attach


def _install_stores(monkeypatch: pytest.MonkeyPatch, w: World) -> None:
    for repository, fake in (
        (user_repository, w.users),
        (briefing_repository, w.briefings),
        (briefing_state_repository, w.states),
        (pending_brief_items_repository, w.pending),
        (signal_memory_repository, w.memories),
        (todo_repository, w.todos),
        (workflow_repository, w.workflows),
        (workflow_executions_repository, w.executions),
        (email_verdict_repository, w.verdicts),
        (approval_ledger_repository, w.approvals),
        (reminder_repository, w.reminders),
        (conversation_repository, w.conversations),
        (user_integration_repository, w.integrations),
    ):
        install(monkeypatch, repository, fake)


def _install_seams(monkeypatch: pytest.MonkeyPatch, w: World) -> None:
    """Fake what the run reaches beyond the process: the model, memory, apps, delivery and analytics."""

    async def recall(user_id: str, _query: str, *, limit: int) -> MemorySearchResult:
        facts = (
            [_memory_fact(g, w.goals_mentioned_at) for g in w.goals][:limit]
            if user_id == USER
            else []
        )
        return MemorySearchResult(memories=facts, has_confident_match=bool(facts))

    async def chat_target(user_id: str) -> ChatChannel | InApp:
        return w.chat if user_id == USER and w.chat else InApp(reason="no_chat_app")

    async def calendar_of(user_id: str, start: datetime, end: datetime) -> object:
        if isinstance(w.calendar, CalendarGap):
            return w.calendar
        return [from_google(e) for e in w.calendar] if user_id == USER else []

    async def scouts_of(user: UserDocument) -> list[ScoutResult]:
        return w.scouts if user.id == USER else []

    w.voice.side_effect = _speaks(w)
    w.fetch_calendar.side_effect = calendar_of
    monkeypatch.setattr(memory_engine, "recall", recall)
    monkeypatch.setattr(checked_call, "ainvoke_structured", _model(w))
    monkeypatch.setattr(composition_headings, "ainvoke_structured", w.headings)
    monkeypatch.setattr(scout_service, "run_scouts", scouts_of)
    monkeypatch.setattr(calendar_read, "fetch_calendar", w.fetch_calendar)
    monkeypatch.setattr(prose, "attach_link", _attached(w.mint))
    monkeypatch.setattr(store, "attach_link", _attached(w.mint))
    monkeypatch.setattr(store, "render_edition_png", w.render)
    monkeypatch.setattr(store, "store_edition", w.store_edition)
    monkeypatch.setattr(notification_service, "notify", w.notify)
    monkeypatch.setattr(delivery, "post_brief_message", w.brief_message)
    monkeypatch.setattr(delivery, "resolve_proactive_target", chat_target)
    monkeypatch.setattr(delivery, "post_to_platform_chat", w.post)
    monkeypatch.setattr(publish, "capture", w.capture)
    monkeypatch.setattr(daily, "build_briefing_voice_prompt", w.voice_prompt)
    monkeypatch.setattr(weekly, "build_weekly_voice_prompt", w.weekly_prompt)
    monkeypatch.setattr(settings, "INSTANCE_SECRET", "s" * 48)


def run_world(monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    """Build the default world: Ada, back after yesterday's brief, one todo of her own done, Sequoia today."""
    w = World(
        users=InMemoryUsers(
            UserDocument(
                id=USER,
                timezone=TZ,
                email="a@b.c",
                name="Ada",
                last_active_at=LAST_SEEN,
            )
        )
    )
    w.briefs[YESTERDAY.id] = YESTERDAY
    w.todos.add(*completions(user=[own("u1", "Gym")]))
    w.integrations.connect(USER, GMAIL_INTEGRATION_ID)
    w.family_first(EditionFamily.MEMO)
    _install_stores(monkeypatch, w)
    _install_seams(monkeypatch, w)
    _records_what_the_run_built(monkeypatch, w)
    with time_machine.travel(NOW, tick=False):
        yield w
