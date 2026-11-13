"""JudgeContext: everything the Judge is shown about one item, assembled in code from authoritative sources.

The model never fetches anything. Each list is bounded by a constant, so the prompt cannot grow
with the user's history. A source the user does not have (an unconnected calendar) is absent, not empty.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from app.constants.attention_profile import DEFAULT_ATTENTION_PROFILE
from app.constants.chat import USER_MESSAGE_TYPE
from app.constants.log_tags import LogTag
from app.constants.outbox_judge import (
    HIT_RATE_SAMPLE,
    JUDGE_BATCH_MAX,
    JUDGE_BATCH_WINDOW_SECONDS,
    JUDGE_CALENDAR_EVENTS_MAX,
    JUDGE_CALENDAR_WINDOW_SECONDS,
    JUDGE_HELD_MAX,
    JUDGE_LEDGER_MAX,
    JUDGE_LEDGER_SUMMARY_CHARS,
    JUDGE_LEDGER_WINDOW_SECONDS,
    JUDGE_MEMORIES_MAX,
    JUDGE_MESSAGE_CHARS,
    JUDGE_MESSAGE_CONVERSATIONS,
    JUDGE_MESSAGES_MAX,
    JUDGE_MESSAGES_MAX_AGE_SECONDS,
    JUDGE_MESSAGES_PER_CONVERSATION,
    JUDGE_OPEN_SUBJECTS_MAX,
    JUDGE_SOURCE_EXCERPT_CHARS,
    JUDGE_UPCOMING_RUNS_MAX,
    UPCOMING_RUNS_WINDOW_SECONDS,
    WAIT_HISTORY_N,
)
from app.constants.todos import WaitingOn
from app.db.repositories.attention_profiles import attention_profiles_repository
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.outbox_items import outbox_items_repository
from app.db.repositories.outbox_messages import outbox_messages_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflows import workflow_repository
from app.memory.retrieval import recall
from app.models.attention_profile_models import ProfileAnswer
from app.models.chat_models import ConversationSource
from app.models.conversation_models import ConversationMessageRow
from app.models.outbox_models import OutboxItemDocument, OutboxMessageDocument
from app.models.presence_models import PresenceSnapshot
from app.models.quiet_hours_models import DEFAULT_QUIET_HOURS, QuietHours
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.services.calendar_service import get_calendar_events
from app.services.delivery.presence import read_presence, surfaces_by_recency
from app.services.outbox.judge_context_models import (
    AskView,
    CalendarEventView,
    DeliveryView,
    HeldView,
    ItemView,
    JudgeContext,
    MessageView,
    PendingAskView,
    PresenceView,
    RunView,
    SettingsView,
    SubjectView,
    UserView,
    WaitView,
)
from app.services.outbox.judge_verdict import UserClock
from app.services.outbox.models import (
    ItemState,
    NoticeReport,
    OutboxReport,
    RunReport,
    SubjectKind,
    facts_of,
)
from app.services.outbox.policy import urgency_of
from app.utils.errors import IntegrationNotConnectedError
from app.utils.timezone import Timezone
from shared.py.wide_events import log


def _bounded(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def _outcome_of(report: OutboxReport) -> str:
    match report:
        case RunReport(report=task_report):
            return task_report.outcome.value if task_report.outcome else ""
        case NoticeReport(outcome=outcome):
            return outcome.value


def _excerpt_of(report: OutboxReport) -> str | None:
    if not isinstance(report, RunReport):
        return None
    quotes = [fact.quote for fact in report.report.facts if fact.quote]
    return _bounded("\n".join(quotes), JUDGE_SOURCE_EXCERPT_CHARS) if quotes else None


def _item_view(report: OutboxReport) -> ItemView:
    return ItemView(
        producer=report.producer.value,
        outcome=_outcome_of(report),
        subject=report.subject.label,
        facts=facts_of(report),
        source_excerpt=_excerpt_of(report),
        producer_suggested={"urgency": urgency_of(report).name.lower()},
    )


def _clock_hours(quiet: QuietHours) -> tuple[str, str]:
    return f"{quiet.end_hour:02d}:00", f"{quiet.start_hour:02d}:00"


def _quiet_hours_of(user: AuthenticatedUser) -> QuietHours:
    return user.quiet_hours or DEFAULT_QUIET_HOURS


def user_clock(user: AuthenticatedUser) -> UserClock:
    """Return the user's timezone and quiet hours: the clock deadlines are read on."""
    return UserClock(Timezone.parse(user.timezone), _quiet_hours_of(user))


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _message_time(row: ConversationMessageRow) -> datetime | None:
    if row.date is None:
        return None
    try:
        return _as_utc(datetime.fromisoformat(row.date))
    except ValueError:
        return None


def _surface_of(row: ConversationMessageRow) -> str:
    source = ConversationSource.coerce(row.source)
    return source.value if source else ConversationSource.WEB.value


async def _recent_messages(
    user_id: str, now: datetime
) -> tuple[list[MessageView], list[MessageView]]:
    """Return the user's latest messages and GAIA's latest replies, across every surface, newest first."""
    since = now - timedelta(seconds=JUDGE_MESSAGES_MAX_AGE_SECONDS)
    rows = await conversation_repository.recent_messages(
        user_id,
        since=since,
        conversations=JUDGE_MESSAGE_CONVERSATIONS,
        per_conversation=JUDGE_MESSAGES_PER_CONVERSATION,
    )
    dated = [(at, row) for row in rows if (at := _message_time(row)) is not None]
    if len(dated) < len(rows):
        log.warning(
            f"{LogTag.NOTIFICATION} Judge context skipped messages with no readable date",
            skipped=len(rows) - len(dated),
        )
    newest = sorted((pair for pair in dated if pair[0] >= since), key=lambda p: p[0], reverse=True)
    views = [
        (
            row.type == USER_MESSAGE_TYPE,
            MessageView(
                at=at, surface=_surface_of(row), text=_bounded(row.response, JUDGE_MESSAGE_CHARS)
            ),
        )
        for at, row in newest[:JUDGE_MESSAGES_MAX]
    ]
    return (
        [view for from_user, view in views if from_user],
        [view for from_user, view in views if not from_user],
    )


async def _attention_profile(user_id: str) -> list[ProfileAnswer]:
    seed = [ProfileAnswer(q=q, a=a) for q, a in DEFAULT_ATTENTION_PROFILE]
    return (await attention_profiles_repository.get_or_seed(user_id, seed)).answers


async def _memories(user_id: str, report: OutboxReport) -> list[str]:
    query = f"{report.subject.label}. " + " ".join(facts_of(report))
    result = await recall(user_id, query, limit=JUDGE_MEMORIES_MAX)
    return [memory.content for memory in result.memories][:JUDGE_MEMORIES_MAX]


async def _calendar(user_id: str, now: datetime) -> list[CalendarEventView] | None:
    """Return the next day of the user's calendar; None when it is not connected or could not be read."""
    try:
        response = await get_calendar_events(
            user_id,
            time_min=now.isoformat(),
            time_max=(now + timedelta(seconds=JUDGE_CALENDAR_WINDOW_SECONDS)).isoformat(),
            max_results=JUDGE_CALENDAR_EVENTS_MAX,
        )
    except IntegrationNotConnectedError:
        return None
    except Exception as e:
        log.warning(
            f"{LogTag.NOTIFICATION} Judge context has no calendar: the read failed",
            error_type=type(e).__name__,
            error=str(e),
        )
        return None
    events = [
        CalendarEventView(
            start=event.start.dateTime or event.start.date or "",
            end=(event.end.dateTime or event.end.date) if event.end else None,
            title=event.summary or "",
        )
        for event in response.events
        if event.start is not None
    ]
    return events[:JUDGE_CALENDAR_EVENTS_MAX]


async def _hit_rate(user_id: str, conversation_id: str | None) -> float | None:
    """Return the share of a schedule's last runs that were told, read from the outbox's own record."""
    if conversation_id is None:
        return None
    settled = await outbox_items_repository.list_settled_for_owner(
        user_id, conversation_id, limit=HIT_RATE_SAMPLE
    )
    if not settled:
        return None
    return sum(item.state is ItemState.SENT for item in settled) / len(settled)


async def _upcoming_runs(user_id: str, now: datetime, todos: list[TodoDocument]) -> list[RunView]:
    """Return the user's scheduled runs due within the window, soonest first, each with its hit rate."""
    horizon = now + timedelta(seconds=UPCOMING_RUNS_WINDOW_SECONDS)
    workflows = await workflow_repository.find_activated_for_user(user_id)
    due: list[tuple[datetime, str, str, str, str | None]] = []
    for workflow in workflows:
        next_run = workflow.trigger_config.next_run
        if next_run is not None and now < _as_utc(next_run) <= horizon:
            conversation = await conversation_repository.find_workflow_conversation(
                user_id, workflow.id
            )
            due.append(
                (
                    _as_utc(next_run),
                    f"workflow:{workflow.id}",
                    SubjectKind.WORKFLOW_RUN.value,
                    workflow.title,
                    conversation.conversation_id if conversation else None,
                )
            )
    for todo in todos:
        if todo.scheduled_at is not None and now < _as_utc(todo.scheduled_at) <= horizon:
            due.append(
                (
                    _as_utc(todo.scheduled_at),
                    f"todo:{todo.id}",
                    SubjectKind.TODO_RUN.value,
                    todo.title,
                    await conversation_repository.find_todo_conversation_id(user_id, todo.id),
                )
            )
    due.sort(key=lambda entry: entry[0])
    return [
        RunView(
            run_id=run_id,
            kind=kind,
            label=label,
            starts_at=starts_at,
            hit_rate=await _hit_rate(user_id, conversation_id),
        )
        for starts_at, run_id, kind, label, conversation_id in due[:JUDGE_UPCOMING_RUNS_MAX]
    ]


def _batch_and_held(
    unsettled: list[OutboxItemDocument], now: datetime
) -> tuple[list[ItemView], list[HeldView]]:
    """Split the user's other unsettled items into what arrived with this one and what is already waiting."""
    window = timedelta(seconds=JUDGE_BATCH_WINDOW_SECONDS)
    batch = [
        item for item in unsettled if item.created_at and now - _as_utc(item.created_at) <= window
    ]
    held = [item for item in unsettled if item not in batch]
    return (
        [_item_view(item.report) for item in batch[:JUDGE_BATCH_MAX]],
        [
            HeldView(
                subject=item.report.subject.label,
                held_minutes=int((now - _as_utc(item.created_at)) / timedelta(minutes=1))
                if item.created_at
                else 0,
            )
            for item in held[:JUDGE_HELD_MAX]
        ],
    )


def _open_subjects(
    unsettled: list[OutboxItemDocument], todos_open: list[SubjectView]
) -> list[SubjectView]:
    told_soon = [
        SubjectView(label=item.report.subject.label, status=item.state.value, since=item.created_at)
        for item in unsettled
    ]
    return (told_soon + todos_open)[:JUDGE_OPEN_SUBJECTS_MAX]


def _delivery_views(sent: list[OutboxMessageDocument]) -> list[DeliveryView]:
    return [
        DeliveryView(
            at=message.sent_at,
            channel=message.destination,
            summary=_bounded(" ".join(message.parts), JUDGE_LEDGER_SUMMARY_CHARS),
        )
        for message in sent
        if message.sent_at
    ]


def _wait_views(waits: list[OutboxItemDocument]) -> list[WaitView]:
    return [
        WaitView(
            run_id=item.judgement.verdict.wait_for_run,
            subject=item.report.subject.label,
            decided_at=item.created_at,
        )
        for item in waits
        if item.judgement and item.judgement.verdict and item.judgement.verdict.wait_for_run
    ]


def _presence_view(presence: PresenceSnapshot) -> PresenceView:
    surfaces = surfaces_by_recency(presence)
    return PresenceView(
        last_active_surface=surfaces[0][0].value if surfaces else None,
        last_active_at=datetime.fromtimestamp(surfaces[0][1], tz=UTC) if surfaces else None,
        active_surfaces={
            source.value: datetime.fromtimestamp(at, tz=UTC) for source, at in surfaces
        },
    )


def _open_todos(todos: list[TodoDocument]) -> list[SubjectView]:
    return [
        SubjectView(
            label=todo.title,
            status=todo.waiting_on.value if todo.waiting_on else "running",
            since=todo.created_at,
        )
        for todo in todos
        if todo.waiting_on is not WaitingOn.USER
    ]


def _pending_asks(todos: list[TodoDocument]) -> list[PendingAskView]:
    return [
        PendingAskView(label=todo.title, question=todo.question, since=todo.updated_at)
        for todo in todos
        if todo.waiting_on is WaitingOn.USER and todo.question
    ]


def _settings_view(quiet: QuietHours) -> SettingsView:
    hours = f"{quiet.start_hour:02d}:00-{quiet.end_hour:02d}:00" if quiet.enabled else "off"
    return SettingsView(quiet_hours=hours)


async def build_judge_context(
    report: OutboxReport, user: AuthenticatedUser, *, now: datetime
) -> JudgeContext:
    """Assemble the state one report is judged in; raises when a source that exists cannot be read."""
    user_id = user.user_id
    (messages, profile, memories, calendar, unsettled, todos) = await asyncio.gather(
        _recent_messages(user_id, now),
        _attention_profile(user_id),
        _memories(user_id, report),
        _calendar(user_id, now),
        outbox_items_repository.list_unsettled(
            user_id,
            exclude_report_id=report.report_id,
            limit=JUDGE_BATCH_MAX + JUDGE_HELD_MAX + JUDGE_OPEN_SUBJECTS_MAX,
        ),
        todo_repository.find_running_tracked_for_user(user_id),
    )
    (runs, presence, sent, waits) = await asyncio.gather(
        _upcoming_runs(user_id, now, todos),
        read_presence(user_id),
        outbox_messages_repository.sent_since(
            user_id, now - timedelta(seconds=JUDGE_LEDGER_WINDOW_SECONDS), limit=JUDGE_LEDGER_MAX
        ),
        outbox_items_repository.list_waits(user_id, limit=WAIT_HISTORY_N),
    )
    quiet = _quiet_hours_of(user)
    wake, sleep = _clock_hours(quiet)
    batch, held = _batch_and_held(unsettled, now)
    return JudgeContext(
        now=now,
        user=UserView(
            timezone=Timezone.parse(user.timezone).value,
            usual_wake=wake,
            usual_sleep=sleep,
            attention_profile=profile,
        ),
        item=_item_view(report),
        other_items_in_batch=batch,
        ask=AskView(
            initiative=report.initiative.value,
            delivery_timing=report.delivery_policy.timing.value,
            may_wake=report.delivery_policy.may_wake,
        ),
        recent_user_messages=messages[0],
        recent_gaia_replies=messages[1],
        open_subjects=_open_subjects(unsettled, _open_todos(todos)),
        pending_asks=_pending_asks(todos),
        recent_deliveries=_delivery_views(sent),
        memory=memories,
        calendar=calendar,
        attention_settings=_settings_view(quiet),
        presence=_presence_view(presence),
        upcoming_runs=runs,
        held_items=held,
        past_waits=_wait_views(waits),
    )
