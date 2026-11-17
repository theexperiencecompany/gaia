"""Context gathering + formatting for the briefing run.

The service does deterministic work (fact assembly, persistence, delivery); this
module reads the world the agent needs to see and formats it into the prompt
blocks. Every block is plain text — the agent turns it into the payload.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.constants.briefing import (
    BRIEFING_KIND_DAILY,
    BRIEFING_RHYTHM_WORKFLOW_KEYS,
    LOOKBACK_MAX_DAYS,
    WEEK_LIST_LIMIT,
    WINBACK_THRESHOLD,
)
from app.constants.integrations import GOOGLE_CALENDAR_INTEGRATION_ID
from app.constants.memory import MemoryKind
from app.constants.todos import (
    FAILED_LABEL,
    GAIA_TRACKED_LABEL,
    NEEDS_USER_LABELS,
    TodoCompleter,
    WaitingOn,
)
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.memory.engine import memory_engine
from app.memory.mappers import entry_to_note
from app.models.brief_pool_models import GoalOrigin
from app.models.briefing_models import (
    BRIEFING_ITEM_STATES,
    BriefingEvent,
    BriefingKind,
    BriefingModel,
    BriefingMood,
    BriefingWeek,
    BriefingWeekDay,
)
from app.models.calendar_models import GoogleCalendarEventResource
from app.models.todo_models import ExternalRefSource, TodoDocument
from app.models.user_models import UserDocument
from app.services.briefing import wind_down
from app.services.briefing.candidates.subjects import subject_key
from app.services.calendar_service import get_calendar_events
from app.services.integrations.user_integrations import get_connected_integration_ids
from app.utils.errors import IntegrationNotConnectedError
from shared.py.wide_events import log

# Open tracked todos the brief reports on (in progress / waiting on the user / failed).
_TRACKED_WORK_LIMIT = 20
# Background workflow runs the look-back lists, newest first.
_LOOKBACK_EXECUTIONS_LIMIT = 20


@dataclass
class UserClock:
    tz: ZoneInfo
    now_local: datetime
    date_str: str
    day_of_year: int

    def day_of(self, moment: datetime) -> date:
        """Return the user's local day a moment falls on; a naive moment is UTC, as Mongo stores it."""
        return _aware(moment).astimezone(self.tz).date()


@dataclass
class WinbackState:
    unacknowledged: int
    last_was_winback: bool

    @property
    def is_winback(self) -> bool:
        return self.unacknowledged >= WINBACK_THRESHOLD

    @property
    def should_back_off(self) -> bool:
        # A winback already went out and the user is still silent — don't repeat
        # it the next day; back off until there's activity.
        return self.last_was_winback and self.unacknowledged >= WINBACK_THRESHOLD


@dataclass
class CompletedWork:
    """What got done since a cutoff, by who finished it."""

    gaia: list[TodoDocument] = field(default_factory=list)
    user: list[TodoDocument] = field(default_factory=list)
    #: Closed by an event it watched, or before who closed a todo was recorded.
    closed: list[TodoDocument] = field(default_factory=list)


def finished_by(doc: TodoDocument) -> TodoCompleter | None:
    """Return who closed a completed todo; None for a tracked one closed before that was recorded.

    Before completed_by existed only the user ever closed a todo of their own.
    """
    if doc.completed_by is not None:
        return doc.completed_by
    return None if is_gaia_tracked(doc) else TodoCompleter.USER


#: Who closed a todo the brief reports as done, besides the user, who never reads as GAIA.
_REPORTED_CLOSERS: frozenset[TodoCompleter | None] = frozenset(
    {TodoCompleter.GAIA, TodoCompleter.TRIGGER, None}
)


@dataclass(frozen=True)
class OpenSubjects:
    """How many open things GAIA's tracked work holds in each state, each subject once."""

    running: int = 0
    blocked: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.running + self.blocked + self.failed


@dataclass
class TrackedWork:
    """GAIA's tracked todos by state — the deterministic world the brief reports."""

    completed: list[TodoDocument] = field(default_factory=list)
    running: list[TodoDocument] = field(default_factory=list)
    #: Waiting on the user (NEEDS_USER_LABELS): the inbox desk's threads they owe a reply, approvals.
    blocked: list[TodoDocument] = field(default_factory=list)
    failed: list[TodoDocument] = field(default_factory=list)
    #: Every open subject by state, however many: the lists above stop at a read limit.
    open_subjects: OpenSubjects = field(default_factory=lambda: OpenSubjects())

    @property
    def is_empty(self) -> bool:
        return not (self.completed or self.running or self.blocked or self.failed)


@dataclass(frozen=True)
class OwnTodos:
    """How many open todos of their own the user has, and how many of those are past due."""

    open: int
    overdue: int


async def count_own_todos(user_id: str, clock: UserClock) -> OwnTodos:
    """Count the user's own open todos, and those due before today began on their clock."""
    return OwnTodos(
        open=await todo_repository.count_open_user_todos(user_id),
        overdue=await todo_repository.count_open_user_todos(
            user_id, due_before=day_start_utc(clock)
        ),
    )


def is_gaia_tracked(doc: TodoDocument) -> bool:
    return GAIA_TRACKED_LABEL in doc.labels


def resolve_clock(user_timezone: str | None) -> UserClock:
    tz = ZoneInfo(user_timezone or "UTC")
    now_local = datetime.now(tz)
    return UserClock(
        tz=tz,
        now_local=now_local,
        date_str=now_local.date().isoformat(),
        day_of_year=now_local.timetuple().tm_yday,
    )


def due_on(due_at: datetime, clock: UserClock) -> str:
    """Say a due date the way the brief does, on the user's own day: today, or its weekday and date."""
    day = clock.day_of(due_at)
    return "today" if day.isoformat() == clock.date_str else day.strftime("%a %b %-d")


def day_start_utc(clock: UserClock, days_ago: int = 0) -> datetime:
    day = clock.now_local.date() - timedelta(days=days_ago)
    return datetime.combine(day, time.min, tzinfo=clock.tz).astimezone(UTC)


async def last_brief(
    user_id: str, clock: UserClock, kind: BriefingKind = BRIEFING_KIND_DAILY
) -> BriefingModel | None:
    """Return the latest brief of kind before today; a same-day re-run looks past its own."""
    return await briefing_repository.get_before_date(user_id, kind=kind, before_date=clock.date_str)


def lookback_since(clock: UserClock, last: BriefingModel | None) -> datetime:
    """Return when the look-back starts: the last brief, at most LOOKBACK_MAX_DAYS back.

    With no brief before, it starts at yesterday's local midnight.
    """
    if last is None:
        return day_start_utc(clock, days_ago=1)
    return max(_aware(last.created_at), day_start_utc(clock, days_ago=LOOKBACK_MAX_DAYS))


def when_sent(last: BriefingModel, clock: UserClock) -> str:
    """Name the last brief's day as the user would: yesterday, or its weekday and date."""
    day = date.fromisoformat(last.date)
    if day == clock.now_local.date() - timedelta(days=1):
        return "yesterday"
    return day.strftime("on %A %b %-d")


# Users type junk into onboarding ("nothing", "n/a"); junk is not a goal.
_JUNK_FOCUS_VALUES = {"nothing", "none", "n/a", "na", "-", "idk", "no"}


def has_meaningful_focus(focus: str | None) -> bool:
    """Whether the onboarding focus is a real stated goal (not blank or junk)."""
    cleaned = (focus or "").strip()
    return bool(cleaned) and cleaned.lower() not in _JUNK_FOCUS_VALUES


@dataclass(frozen=True)
class StatedGoal:
    """A goal the user stated, and the names it is about, which link their todos to it."""

    statement: str
    origin: GoalOrigin
    terms: tuple[str, ...] = ()


async def stated_goals(user_id: str, user: UserDocument) -> list[StatedGoal]:
    """Return the onboarding focus, when it is a real goal, then what memory says they work toward."""
    focus = (user.onboarding.focus if user.onboarding else "").strip()
    goals = [StatedGoal(focus, GoalOrigin.ONBOARDING)] if has_meaningful_focus(focus) else []
    result = await memory_engine.recall(
        user_id, "what is the user currently working on and their goals", limit=5
    )
    # A weak fallback recall is whatever memory sat nearest, and an experience is something
    # that happened: neither is what the user works toward.
    recalled = result.memories if result.has_confident_match else []
    for entry in (e for e in recalled if e.kind is MemoryKind.FACT):
        statement = entry_to_note(entry).strip()
        if statement and statement not in {g.statement for g in goals}:
            terms = tuple(entity.name for entity in entry.entities)
            goals.append(StatedGoal(statement, GoalOrigin.MEMORY, terms))
    return goals


def format_goal_block(goals: list[StatedGoal]) -> tuple[str, bool]:
    """Return (formatted goal block, has_goal); has_goal gates cold-start."""
    if not goals:
        return (
            "No stated goal on record yet — treat goal discovery as part of today's job.",
            False,
        )
    lines = [
        f"Stated goal: {g.statement}" if g.origin is GoalOrigin.ONBOARDING else f"- {g.statement}"
        for g in goals
    ]
    return ("\n".join(lines), True)


async def gather_tracked_work(user_id: str, since: datetime) -> TrackedWork:
    """GAIA's tracked todos: completed since the cutoff, plus every open one by state.

    The inbox desk itself is left out: it is always open, and the brief reports it
    through its findings (its thread and proposal sub-todos) instead.
    """
    work = TrackedWork()
    for doc in await todo_repository.list_completed_since(user_id, since=since):
        if is_gaia_tracked(doc) and finished_by(doc) in _REPORTED_CLOSERS:
            work.completed.append(doc)
    # Every open one is read so the totals are whole; the brief reports on the newest.
    everything = [
        doc
        for doc in await todo_repository.list_active_tracked(user_id, limit=0)
        if doc.external_ref is None or doc.external_ref.source is not ExternalRefSource.INBOX_DESK
    ]
    whole = _by_state(everything)
    work.running, work.blocked, work.failed = _by_state(everything[:_TRACKED_WORK_LIMIT])
    work.open_subjects = OpenSubjects(*(len({subject_key(doc) for doc in docs}) for docs in whole))
    return work


def _by_state(
    docs: list[TodoDocument],
) -> tuple[list[TodoDocument], list[TodoDocument], list[TodoDocument]]:
    """Split open tracked todos into GAIA's open work, what waits on the user (a question asked too), and failed."""
    running: list[TodoDocument] = []
    blocked: list[TodoDocument] = []
    failed: list[TodoDocument] = []
    for doc in docs:
        if FAILED_LABEL in doc.labels:
            failed.append(doc)
        elif NEEDS_USER_LABELS.intersection(doc.labels) or doc.waiting_on is WaitingOn.USER:
            blocked.append(doc)
        else:
            running.append(doc)
    return running, blocked, failed


async def gather_completed_since(user_id: str, since: datetime) -> CompletedWork:
    """Return what got done since, by who finished it; housekeeping's closures are nobody's work."""
    work = CompletedWork()
    lists = {
        TodoCompleter.GAIA: work.gaia,
        TodoCompleter.USER: work.user,
        TodoCompleter.TRIGGER: work.closed,
        None: work.closed,
    }
    for doc in await todo_repository.list_completed_since(user_id, since=since):
        finisher = finished_by(doc)
        if finisher in lists:
            lists[finisher].append(doc)
    return work


def _title(doc: TodoDocument) -> str:
    return doc.title or "untitled"


async def format_lookback_block(
    user_id: str, last: BriefingModel | None, since: datetime, clock: UserClock
) -> str:
    """Return what the last brief planned, then what got done and ran since it.

    A brief older than LOOKBACK_MAX_DAYS is named by its date but not quoted: its plan is stale.
    """
    completed = await gather_completed_since(user_id, since)
    briefing_workflows = await workflow_repository.find_system_workflows(
        user_id, BRIEFING_RHYTHM_WORKFLOW_KEYS
    )
    executions = await workflow_executions_repository.list_since(
        user_id,
        since,
        exclude_workflow_ids=[w.id for w in briefing_workflows],
        limit=_LOOKBACK_EXECUTIONS_LIMIT,
    )

    parts: list[str] = []
    if last is None:
        parts.append("No prior briefing — this is the first look-back.")
    elif _aware(last.created_at) < since:
        parts.append(
            f"The last brief went out {when_sent(last, clock)}, over {LOOKBACK_MAX_DAYS} days "
            f"ago; what it said is stale, so this looks back over the last {LOOKBACK_MAX_DAYS} days."
        )
    else:
        told = [
            f"- {BRIEFING_ITEM_STATES[item.kind].lower()}: {item.text}"
            for section in last.payload.sections
            for item in section.items
            if item.text
        ]
        if told:
            parts.append(
                f"Your last brief, {when_sent(last, clock)}, told the user about:\n"
                + "\n".join(told)
            )

    if completed.gaia or completed.user or completed.closed:
        done = [f"- GAIA finished: {_title(d)}" for d in completed.gaia]
        done += [f"- The user finished: {_title(d)}" for d in completed.user]
        done += [f"- {_closed_how(d)}: {_title(d)}" for d in completed.closed]
        parts.append("Actually completed since then:\n" + "\n".join(done))
    else:
        parts.append("Nothing was completed since the last briefing.")

    if executions:
        # workflow_executions carries no workflow_title field; "Workflow" is the
        # generic label every run has used for as long as the field's been gone.
        ex_lines = [
            f"- Workflow [{d.status}]" + (f": {d.summary}" if d.summary else "") for d in executions
        ]
        parts.append("Background workflow runs since then:\n" + "\n".join(ex_lines))

    return "\n\n".join(parts)


def _closed_how(doc: TodoDocument) -> str:
    if finished_by(doc) is TodoCompleter.TRIGGER:
        return "Closed when an event it watched fired"
    return "Closed (who closed it is not recorded)"


def _aware(moment: datetime) -> datetime:
    """Mongo returns naive UTC datetimes; normalize before comparing."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def compute_winback_state(user: UserDocument, recent: int = 10) -> WinbackState:
    """Count consecutive most-recent daily briefings the user never acknowledged.

    Acknowledged means the user acted on any surface since it went out; opening the
    brief is such an act. A todo completing is NOT an ack: GAIA completes its own todos,
    so winback would never fire. The user's last activity is read once.
    """
    briefings = await briefing_repository.list_recent(
        user.id, limit=recent, kind=BRIEFING_KIND_DAILY
    )
    if not briefings:
        return WinbackState(unacknowledged=0, last_was_winback=False)

    last_active = await wind_down.latest_activity_since(user.id, _aware(briefings[-1].created_at))
    unacknowledged = 0
    for briefing in briefings:
        if last_active is not None and last_active >= _aware(briefing.created_at):
            break
        unacknowledged += 1

    last_mood: BriefingMood | str = briefings[0].payload.mood
    return WinbackState(unacknowledged=unacknowledged, last_was_winback=last_mood == "winback")


def _to_event(event: GoogleCalendarEventResource, tz: ZoneInfo) -> BriefingEvent | None:
    start = event.start
    if start is None:
        return None
    if start.dateTime:
        local = datetime.fromisoformat(start.dateTime).astimezone(tz)
        ends = event.end.dateTime if event.end is not None else None
        end = datetime.fromisoformat(ends).astimezone(tz) if ends else None
        timed = end is not None and end > local and end.date() == local.date()
        day = local.date().isoformat()
        at = local.strftime("%H:%M")
        until = end.strftime("%H:%M") if end is not None and timed else None
    elif start.date:
        day, at, until = start.date, None, None
    else:
        return None
    return BriefingEvent(
        date=day,
        start=at,
        end=until,
        title=(event.summary or "").strip() or "Untitled event",
        location=event.location,
        calendar=event.calendarTitle,
        response=event.response,
        organizer=event.organizer_name,
        guests=event.guests,
    )


class CalendarGap(StrEnum):
    """Why a brief has no calendar to read."""

    NOT_CONNECTED = "not_connected"
    #: A connected calendar did not answer: nothing can be said about the day's events.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CalendarUnread:
    """The calendar a brief could not read, and why; never the same as an empty one."""

    gap: CalendarGap


async def read_calendar(
    user_id: str, start: datetime, end: datetime
) -> list[GoogleCalendarEventResource] | CalendarUnread:
    """Return the user's calendar events from start to end as Google sends them, declined ones left out.

    A connected calendar that fails to answer, even for one of its calendars, is unavailable.
    """
    if GOOGLE_CALENDAR_INTEGRATION_ID not in await get_connected_integration_ids(user_id):
        return CalendarUnread(CalendarGap.NOT_CONNECTED)
    try:
        response = await get_calendar_events(
            user_id, time_min=start.isoformat(), time_max=end.isoformat(), fetch_all=True
        )
    except (IntegrationNotConnectedError, HTTPException):
        log.warning("briefing.calendar_unavailable")
        return CalendarUnread(CalendarGap.UNAVAILABLE)
    if response.calendars_failed:
        log.warning(
            "briefing.calendar_unavailable", calendars_failed=len(response.calendars_failed)
        )
        return CalendarUnread(CalendarGap.UNAVAILABLE)
    return [event for event in response.events if not event.declined_by_user]


@dataclass(frozen=True)
class DayCalendar:
    """One read of the calendar: today's events, or why it went unread, and the week behind them."""

    today: list[BriefingEvent] | CalendarUnread
    #: The series window's events as Google sent them; none when the calendar went unread.
    week: list[GoogleCalendarEventResource]

    @property
    def events(self) -> list[BriefingEvent]:
        """Return today's events; none when the calendar went unread."""
        return self.today if isinstance(self.today, list) else []

    @property
    def tally(self) -> int | CalendarGap:
        """Return how many events today holds, or why the calendar went unread."""
        return len(self.today) if isinstance(self.today, list) else self.today.gap


async def read_day_calendar(
    user_id: str, clock: UserClock, start: datetime, end: datetime
) -> DayCalendar:
    """Read the calendar once over start to end and take today's events from it."""
    raw = await read_calendar(user_id, start, end)
    if isinstance(raw, CalendarUnread):
        return DayCalendar(today=raw, week=[])
    return DayCalendar(today=events_on(raw, clock, clock.now_local.date(), 1), week=raw)


def events_on(
    raw: list[GoogleCalendarEventResource], clock: UserClock, first: date, days: int
) -> list[BriefingEvent]:
    """Return the events starting on the days local days from first, ordered by start (all-day first)."""
    last = first + timedelta(days=days)
    events = [
        e
        for e in (_to_event(event, clock.tz) for event in raw)
        if e is not None and first <= date.fromisoformat(e.date) < last
    ]
    return sorted(events, key=lambda e: (e.date, e.start or ""))


async def gather_calendar(
    user_id: str, clock: UserClock, *, days: int, days_ahead: int = 0
) -> list[BriefingEvent] | CalendarUnread:
    """Return the user's calendar events over days local days from days_ahead, or why it went unread."""
    start = day_start_utc(clock, days_ago=-days_ahead)
    raw = await read_calendar(user_id, start, start + timedelta(days=days))
    if isinstance(raw, CalendarUnread):
        return raw
    return events_on(raw, clock, clock.now_local.date() + timedelta(days=days_ahead), days)


def week_start_utc(clock: UserClock) -> datetime:
    """Return this week's Monday, local midnight, in UTC: the weekly digest's window start."""
    return day_start_utc(clock, days_ago=clock.now_local.weekday())


def count_week(
    clock: UserClock, completed: CompletedWork, ahead: list[BriefingEvent] | CalendarUnread
) -> BriefingWeek:
    """Count this week's completions (gathered since week_start_utc) by owner and day, beside the week ahead."""
    monday = clock.now_local.date() - timedelta(days=clock.now_local.weekday())
    days = [BriefingWeekDay(you=0, gaia=0) for _ in range(7)]
    for docs, by_gaia in ((completed.gaia, True), (completed.user, False)):
        for doc in reversed(docs):
            if doc.completed_at is None:
                continue
            index = (clock.day_of(doc.completed_at) - monday).days
            if not 0 <= index < len(days):
                continue
            if by_gaia:
                days[index].gaia += 1
            else:
                days[index].you += 1
    listed = ahead[:WEEK_LIST_LIMIT] if isinstance(ahead, list) else []
    return BriefingWeek(days=days, ahead=listed)
