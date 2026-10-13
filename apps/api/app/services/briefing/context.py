"""Context gathering + formatting for the briefing run.

The service does deterministic work (fact assembly, persistence, delivery); this
module reads the world the agent needs to see and formats it into the prompt
blocks. Every block is plain text — the agent turns it into the payload.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.constants.briefing import (
    BRIEFING_KIND_DAILY,
    WEEK_LIST_LIMIT,
    WINBACK_THRESHOLD,
)
from app.constants.integrations import GOOGLE_CALENDAR_INTEGRATION_ID
from app.constants.todos import BLOCKING_LABELS, FAILED_LABEL, GAIA_TRACKED_LABEL
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.memory.engine import memory_engine
from app.memory.mappers import entry_to_note
from app.models.briefing_models import (
    BriefingEvent,
    BriefingKind,
    BriefingMood,
    BriefingPayload,
    BriefingWeek,
    BriefingWeekDay,
)
from app.models.calendar_models import GoogleCalendarEventResource
from app.models.todo_models import TodoDocument
from app.services.briefing import dormancy
from app.services.calendar_service import get_calendar_events
from app.services.integrations.user_integrations import get_connected_integration_ids
from shared.py.wide_events import log

# Open tracked todos the brief reports on (in progress / blocked / failed).
_TRACKED_WORK_LIMIT = 20


@dataclass
class UserClock:
    tz: ZoneInfo
    now_local: datetime
    date_str: str
    day_of_year: int


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
    gaia: list[TodoDocument] = field(default_factory=list)
    user: list[TodoDocument] = field(default_factory=list)


@dataclass
class TrackedWork:
    """GAIA's tracked todos by state — the deterministic world the brief reports."""

    completed: list[TodoDocument] = field(default_factory=list)
    running: list[TodoDocument] = field(default_factory=list)
    blocked: list[TodoDocument] = field(default_factory=list)
    failed: list[TodoDocument] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.completed or self.running or self.blocked or self.failed)


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


def day_start_utc(clock: UserClock, days_ago: int = 0) -> datetime:
    day = clock.now_local.date() - timedelta(days=days_ago)
    return datetime.combine(day, time.min, tzinfo=clock.tz).astimezone(UTC)


async def get_yesterday_payload(
    user_id: str, before_date: str, kind: BriefingKind = BRIEFING_KIND_DAILY
) -> BriefingPayload | None:
    """Latest daily briefing payload strictly before ``before_date`` (today).

    Excludes today so a same-day re-run compares against the real prior brief,
    not itself.
    """
    briefing = await briefing_repository.get_before_date(
        user_id, kind=kind, before_date=before_date
    )
    return briefing.payload if briefing else None


# Users type junk into onboarding ("nothing", "n/a"); junk is not a goal.
_JUNK_FOCUS_VALUES = {"nothing", "none", "n/a", "na", "-", "idk", "no"}


def has_meaningful_focus(focus: str | None) -> bool:
    """Whether the onboarding focus is a real stated goal (not blank or junk)."""
    cleaned = (focus or "").strip()
    return bool(cleaned) and cleaned.lower() not in _JUNK_FOCUS_VALUES


async def format_goal_block(user_id: str, user: dict) -> tuple[str, bool]:
    """Return (formatted goal block, has_goal). ``has_goal`` gates cold-start."""
    focus = ((user.get("onboarding") or {}).get("focus") or "").strip()
    if not has_meaningful_focus(focus):
        focus = ""
    lines: list[str] = []
    if focus:
        lines.append(f"Stated goal: {focus}")

    try:
        result = await memory_engine.recall(
            user_id, "what is the user currently working on and their goals", limit=5
        )
        for entry in result.memories:
            line = f"- {entry_to_note(entry).strip()}"
            if line != "- " and line not in lines:
                lines.append(line)
    except Exception as exc:
        # Memory recall is best-effort context, not a hard dependency of the run.
        log.warning("briefing.goal_block_recall_failed", user_id=user_id, error=str(exc))

    if not lines:
        return (
            "No stated goal on record yet — treat goal discovery as part of today's job.",
            False,
        )
    return ("\n".join(lines), True)


async def gather_tracked_work(user_id: str, since: datetime) -> TrackedWork:
    """GAIA's tracked todos: completed since ``since``, plus every open one by state."""
    work = TrackedWork()
    for doc in await todo_repository.list_completed_since(user_id, since=since):
        if is_gaia_tracked(doc):
            work.completed.append(doc)
    for doc in await todo_repository.list_active_tracked(user_id, limit=_TRACKED_WORK_LIMIT):
        if FAILED_LABEL in doc.labels:
            work.failed.append(doc)
        elif BLOCKING_LABELS.intersection(doc.labels):
            work.blocked.append(doc)
        else:
            work.running.append(doc)
    return work


async def gather_completed_since(user_id: str, since: datetime) -> CompletedWork:
    work = CompletedWork()
    for doc in await todo_repository.list_completed_since(user_id, since=since):
        (work.gaia if is_gaia_tracked(doc) else work.user).append(doc)
    return work


async def user_open_todo_summary(user_id: str) -> tuple[int, list[str]]:
    """Count + first titles of the user's own open todos, for the brief's facts.

    The voice pass gets these so an empty day can't be voiced as "all clear"
    while the user's own list still has work in it.
    """
    docs = await todo_repository.list_open_user_todos(user_id, limit=50)
    titles = [d.title or "untitled" for d in docs]
    return len(titles), titles[:5]


async def format_lookback_block(
    user_id: str, yesterday_payload: BriefingPayload | None, since: datetime
) -> str:
    completed = await gather_completed_since(user_id, since)
    executions = await workflow_executions_repository.list_since(user_id, since, limit=20)

    parts: list[str] = []
    if yesterday_payload:
        planned = [item.text for section in yesterday_payload.sections for item in section.items]
        if planned:
            parts.append(
                "Yesterday you told the user you'd focus on:\n"
                + "\n".join(f"- {p}" for p in planned if p)
            )
    else:
        parts.append("No prior briefing — this is the first look-back.")

    if completed.gaia or completed.user:
        done = [f"- GAIA finished: {d.title or 'untitled'}" for d in completed.gaia]
        done += [f"- You finished: {d.title or 'untitled'}" for d in completed.user]
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


async def compute_winback_state(user_id: str, recent: int = 10) -> WinbackState:
    """Count consecutive most-recent daily briefings the user never acknowledged.

    Acknowledgement is honest and channel-agnostic: the briefing was opened, OR the
    user was active since it went out (a reactivation signal — session active, or
    any message). A todo completing is deliberately NOT an ack: GAIA completes its
    own tracked todos autonomously, so counting completions would let GAIA
    acknowledge its own briefings and winback would never fire.

    The loop breaks at the first acknowledged briefing, so the reactivation-signal
    lookup runs only for the unacknowledged tail (at most one extra call past it).
    """
    briefings = await briefing_repository.list_recent(
        user_id, limit=recent, kind=BRIEFING_KIND_DAILY
    )
    if not briefings:
        return WinbackState(unacknowledged=0, last_was_winback=False)

    unacknowledged = 0
    for briefing in briefings:
        created_at = briefing.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        acknowledged = briefing.opened_at is not None or await dormancy.reactivation_signal_since(
            user_id, created_at
        )
        if acknowledged:
            break
        unacknowledged += 1

    last_mood: BriefingMood | str = briefings[0].payload.mood
    return WinbackState(unacknowledged=unacknowledged, last_was_winback=last_mood == "winback")


def _to_event(event: GoogleCalendarEventResource, tz: ZoneInfo) -> BriefingEvent | None:
    start = event.start
    if start is None:
        return None
    title = (event.summary or "").strip() or "Untitled event"
    if start.dateTime:
        local = datetime.fromisoformat(start.dateTime).astimezone(tz)
        return BriefingEvent(
            date=local.date().isoformat(),
            start=local.strftime("%H:%M"),
            title=title,
            location=event.location,
        )
    if start.date:
        return BriefingEvent(date=start.date, title=title, location=event.location)
    return None


async def gather_calendar(
    user_id: str, clock: UserClock, *, days: int, days_ahead: int = 0
) -> list[BriefingEvent]:
    """The user's calendar events over ``days`` local days starting ``days_ahead``
    days from today, in start order (all-day events first). Empty when no
    calendar is connected; a connected calendar that fails to answer raises."""
    if GOOGLE_CALENDAR_INTEGRATION_ID not in await get_connected_integration_ids(user_id):
        return []
    start = day_start_utc(clock, days_ago=-days_ahead)
    response = await get_calendar_events(
        user_id,
        time_min=start.isoformat(),
        time_max=(start + timedelta(days=days)).isoformat(),
        fetch_all=True,
    )
    events = [e for e in (_to_event(raw, clock.tz) for raw in response.events) if e]
    return sorted(events, key=lambda e: (e.date, e.start or ""))


async def gather_week(user_id: str, clock: UserClock) -> BriefingWeek:
    """Monday-to-Sunday completions of the week containing today, by owner and
    day, plus the calendar for the seven days ahead."""
    monday = clock.now_local.date() - timedelta(days=clock.now_local.weekday())
    since = datetime.combine(monday, time.min, tzinfo=clock.tz).astimezone(UTC)
    days = [BriefingWeekDay(you=0, gaia=0) for _ in range(7)]
    shipped: list[str] = []
    handled: list[str] = []
    for doc in reversed(await todo_repository.list_completed_since(user_id, since=since)):
        if doc.completed_at is None:
            continue
        completed_at = doc.completed_at
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=UTC)
        index = (completed_at.astimezone(clock.tz).date() - monday).days
        if not 0 <= index < len(days):
            continue
        if is_gaia_tracked(doc):
            days[index].gaia += 1
            handled.append(doc.title)
        else:
            days[index].you += 1
            shipped.append(doc.title)
    ahead = await gather_calendar(user_id, clock, days=7, days_ahead=1)
    return BriefingWeek(
        days=days,
        shipped=shipped[:WEEK_LIST_LIMIT],
        handled=handled[:WEEK_LIST_LIMIT],
        ahead=ahead[:WEEK_LIST_LIMIT],
    )
