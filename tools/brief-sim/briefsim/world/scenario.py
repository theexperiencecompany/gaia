"""The founder's two weeks: how their calendar, GitHub and Todoist move day by day, and when each breaks.

Deterministic for a given origin and seed. Every record carries the details real apps send
and the brief has historically got wrong: events past local midnight (a different UTC date),
all-day and other-timezone events, moved/cancelled/declined events, more assigned issues than
one API page, unicode titles, a task with no content, and a day where nothing happens.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
import random
from zoneinfo import ZoneInfo

from briefsim.world.model import (
    App,
    AppState,
    CalendarEvent,
    Change,
    Fault,
    FaultMode,
    GithubItem,
    TodoistTask,
    World,
)

ME = "sim-founder"
TEAM = ["kavya-s", "dhruv-tec", "sankalp-a", "maria-lópez", "王伟"]
ISSUE_TITLES = [
    "Telegram bot drops attachments over 20MB",
    "Daily brief arrives twice for users in UTC-8",
    "Crash in the 日本語 locale when the reminder text has an emoji ☕",
    "Workflow editor loses the trigger after a rename",
    "Search ranks archived chats above live ones",
    "Voice agent cuts the last word of long replies",
    "Settings page: timezone dropdown resets to UTC",
    "Calendar card shows ‘Invalid Date’ for all-day events",
    "Export to PDF ignores right-to-left text (עברית)",
    "Todos: drag-and-drop reorders the wrong list",
    "Slack bot replies in the channel root instead of the thread",
    "Memory recall returns facts from another user's test account",
]
PR_TITLES = [
    "feat(voice): barge-in support for the LiveKit worker",
    "fix(bots): Slack thread replies land in the channel root",
    "chore(deps): bump undici from 7.24.0 to 7.29.0",
    "feat(briefing): weekly digest week-ahead strip",
    "fix(api): 409 on duplicate turn ids instead of 500",
    "refactor(web): move the composer into its own feature",
]
TASK_TITLES = [
    "File GST return (October)",
    "Renew heygaia.io domain",
    "Send the investor update",
    "Reply to Sankalp with voice latency numbers",
    "Book flights for the Bengaluru offsite",
    "Review the Q4 hiring plan",
    "Pay the AWS invoice",
    "Call the CA about advance tax",
    "Draft the launch post",
    "Sign the office lease renewal",
]
#: Assigned open issues at the start: more than GitHub's default page of 30.
INITIAL_ASSIGNED_ISSUES = 47


@dataclass(frozen=True)
class Clockwork:
    """Local wall-clock instants for the persona, counted in days from the origin's local date."""

    tz: ZoneInfo
    first_day: date

    def at(self, day: int, hour: int = 0, minute: int = 0) -> datetime:
        local = datetime.combine(self.first_day + timedelta(days=day), time(hour, minute), self.tz)
        return local.astimezone(UTC)

    def weekday(self, day: int) -> int:
        return (self.first_day + timedelta(days=day)).weekday()


def _put_issue(item: GithubItem) -> Callable[[AppState], None]:
    def apply(state: AppState) -> None:
        state.github[item.number] = item

    return apply


def _close_issue(number: int, at: datetime) -> Callable[[AppState], None]:
    def apply(state: AppState) -> None:
        item = state.github[number]
        item.state, item.closed_at, item.updated = "closed", at, at

    return apply


def _retitle(number: int, title: str, at: datetime) -> Callable[[AppState], None]:
    def apply(state: AppState) -> None:
        state.github[number].title, state.github[number].updated = title, at

    return apply


def _reassign(number: int, to: str, at: datetime) -> Callable[[AppState], None]:
    def apply(state: AppState) -> None:
        state.github[number].assignees, state.github[number].updated = [to], at

    return apply


def _put_event(event: CalendarEvent) -> Callable[[AppState], None]:
    def apply(state: AppState) -> None:
        state.calendar[event.id] = event

    return apply


def _move_event(event_id: str, start: datetime, at: datetime) -> Callable[[AppState], None]:
    def apply(state: AppState) -> None:
        event = state.calendar[event_id]
        length = (event.end or start) - (event.start or start)
        event.start, event.end, event.updated = start, start + length, at

    return apply


def _set_event(event_id: str, at: datetime, **fields: str) -> Callable[[AppState], None]:
    def apply(state: AppState) -> None:
        event = state.calendar[event_id]
        for name, value in fields.items():
            setattr(event, name, value)
        event.updated = at

    return apply


def _put_task(task: TodoistTask) -> Callable[[AppState], None]:
    def apply(state: AppState) -> None:
        state.todoist[task.id] = task

    return apply


def _complete_task(task_id: str, at: datetime) -> Callable[[AppState], None]:
    def apply(state: AppState) -> None:
        task = state.todoist[task_id]
        task.completed_at, task.updated = at, at

    return apply


def _delete_task(task_id: str, at: datetime) -> Callable[[AppState], None]:
    def apply(state: AppState) -> None:
        state.todoist[task_id].deleted, state.todoist[task_id].updated = True, at

    return apply


class _Builder:
    def __init__(self, clock: Clockwork, seed: int) -> None:
        self.clock = clock
        self.rng = random.Random(seed)
        self.initial = AppState()
        self.changes: list[Change] = []
        self.next_issue = 1300
        self.next_task = 8800

    def change(
        self, at: datetime, app: App, kind: str, ref: object, summary: str, apply: Callable
    ) -> None:
        self.changes.append(Change(at, app, kind, str(ref), summary, apply))

    def issue_number(self) -> int:
        self.next_issue += 1
        return self.next_issue

    def task_id(self) -> str:
        self.next_task += 1
        return str(self.next_task)

    def work_hour(self, day: int) -> datetime:
        return self.clock.at(day, self.rng.randint(10, 18), self.rng.choice([0, 15, 30, 45]))


def _seed_github(b: _Builder) -> None:
    for i in range(INITIAL_ASSIGNED_ISSUES):
        n = b.issue_number()
        title = f"{ISSUE_TITLES[i % len(ISSUE_TITLES)]} (#{i + 1})"
        at = b.clock.at(-b.rng.randint(3, 60), b.rng.randint(9, 19))
        b.initial.github[n] = GithubItem(
            number=n,
            title=title,
            kind="issue",
            author=b.rng.choice(TEAM),
            created=at,
            updated=at,
            assignees=[ME],
        )
    for i in range(4):
        n = b.issue_number()
        at = b.clock.at(-b.rng.randint(1, 6), 15)
        b.initial.github[n] = GithubItem(
            number=n,
            title=PR_TITLES[i],
            kind="pr",
            author=TEAM[i],
            created=at,
            updated=at,
            reviewers=[ME],
        )


def _evolve_github(b: _Builder, day: int) -> None:
    if b.clock.weekday(day) >= 5 and day % 7 != 5:
        return  # Sundays are quiet; Saturday gets one issue
    for _ in range(1 if b.clock.weekday(day) >= 5 else b.rng.randint(1, 2)):
        n, at = b.issue_number(), b.work_hour(day)
        title = b.rng.choice(ISSUE_TITLES)
        item = GithubItem(
            number=n,
            title=title,
            kind="issue",
            author=b.rng.choice(TEAM),
            created=at,
            updated=at,
            assignees=[ME],
        )
        b.change(at, App.GITHUB, "created", n, f"issue #{n} assigned: {title}", _put_issue(item))
    if b.clock.weekday(day) < 5 and day % 2 == 0:
        n, at = b.issue_number(), b.work_hour(day)
        title = b.rng.choice(PR_TITLES)
        item = GithubItem(
            number=n,
            title=title,
            kind="pr",
            author=b.rng.choice(TEAM),
            created=at,
            updated=at,
            reviewers=[ME],
        )
        b.change(
            at, App.GITHUB, "created", n, f"PR #{n} asks your review: {title}", _put_issue(item)
        )
    if b.clock.weekday(day) < 5:
        closing = b.rng.choice(sorted(b.initial.github))
        at = b.work_hour(day)
        b.change(at, App.GITHUB, "closed", closing, f"#{closing} closed", _close_issue(closing, at))


def _calendar_day(b: _Builder, day: int) -> None:
    clock = b.clock
    if clock.weekday(day) < 5:
        start = clock.at(day, 10, 30)
        event = CalendarEvent(
            f"standup-{day}",
            "GAIA standup",
            clock.at(day - 7, 9),
            clock.at(day - 7, 9),
            start=start,
            end=start + timedelta(minutes=15),
            organizer_tz=str(clock.tz),
        )
        b.change(
            clock.at(day - 1, 20), App.CALENDAR, "created", event.id, "standup", _put_event(event)
        )
        meeting = b.rng.choice(["Investor sync", "Design review", "1:1 with Kavya", "Hiring loop"])
        start = clock.at(day, 15, 0)
        event = CalendarEvent(
            f"meet-{day}",
            meeting,
            clock.at(day - 2, 11),
            clock.at(day - 2, 11),
            start=start,
            end=start + timedelta(minutes=45),
            organizer_tz=str(clock.tz),
        )
        b.change(
            clock.at(day - 2, 11), App.CALENDAR, "created", event.id, meeting, _put_event(event)
        )


def _calendar_specials(b: _Builder) -> None:
    clock = b.clock
    # Day 1, 00:30 local: the UTC date is the day before.
    start = clock.at(1, 0, 30)
    late = CalendarEvent(
        "late-call",
        "Call with Dodo Payments (US)",
        clock.at(-3, 12),
        clock.at(-3, 12),
        start=start,
        end=start + timedelta(minutes=30),
        organizer_tz="America/New_York",
    )
    b.change(clock.at(-3, 12), App.CALENDAR, "created", late.id, late.title, _put_event(late))
    # Day 2: an all-day offsite.
    offsite = CalendarEvent(
        "offsite",
        "Team offsite — Bengaluru",
        clock.at(-5, 10),
        clock.at(-5, 10),
        all_day=clock.first_day + timedelta(days=2),
    )
    b.change(
        clock.at(-5, 10), App.CALENDAR, "created", offsite.id, offsite.title, _put_event(offsite)
    )
    # Day 3: organised from Los Angeles at 09:00 Pacific, which is 22:30 local.
    la = ZoneInfo("America/Los_Angeles")
    la_day = (clock.at(3, 12)).astimezone(la).date()
    start = datetime.combine(la_day, time(9, 0), la).astimezone(UTC)
    pacific = CalendarEvent(
        "pacific",
        "Partner call (Pacific time)",
        clock.at(-1, 9),
        clock.at(-1, 9),
        start=start,
        end=start + timedelta(hours=1),
        organizer_tz="America/Los_Angeles",
    )
    b.change(
        clock.at(-1, 9), App.CALENDAR, "created", pacific.id, pacific.title, _put_event(pacific)
    )
    # Day 3's 15:00 meeting moves to 17:00 the evening before.
    b.change(
        clock.at(2, 19),
        App.CALENDAR,
        "moved",
        "meet-3",
        "meeting moved 15:00 -> 17:00",
        _move_event("meet-3", clock.at(3, 17), clock.at(2, 19)),
    )
    # Day 8's meeting is cancelled; day 9's is declined by the user.
    b.change(
        clock.at(7, 21),
        App.CALENDAR,
        "cancelled",
        "meet-8",
        "meeting cancelled",
        _set_event("meet-8", clock.at(7, 21), status="cancelled"),
    )
    b.change(
        clock.at(8, 18),
        App.CALENDAR,
        "declined",
        "meet-9",
        "you declined the meeting",
        _set_event("meet-9", clock.at(8, 18), self_response="declined"),
    )


def _seed_todoist(b: _Builder) -> None:
    for i, title in enumerate(TASK_TITLES[:8]):
        tid = b.task_id()
        due = b.clock.first_day + timedelta(days=b.rng.randint(-3, 6)) if i % 3 else None
        at = b.clock.at(-b.rng.randint(2, 20), 9)
        b.initial.todoist[tid] = TodoistTask(
            tid, title, "2302", at, at, priority=b.rng.randint(1, 4), due_date=due
        )


def _evolve_todoist(b: _Builder, day: int) -> None:
    clock = b.clock
    if day == 6:
        # Due 00:15 local on day 6: 18:45 UTC on day 5.
        tid, at = b.task_id(), clock.at(4, 20)
        due = clock.at(6, 0, 15)
        task = TodoistTask(
            tid,
            "Submit the grant application",
            "2302",
            at,
            at,
            priority=4,
            due_date=due.astimezone(clock.tz).date(),
            due_datetime=due,
        )
        b.change(at, App.TODOIST, "created", tid, task.content or "", _put_task(task))
    if day == 5:
        tid, at = b.task_id(), clock.at(5, 8)
        broken = TodoistTask(tid, None, "2302", at, at, due_date=clock.first_day + timedelta(5))
        b.change(
            at, App.TODOIST, "created", tid, "a task with no content (malformed)", _put_task(broken)
        )
        b.change(
            clock.at(7, 9),
            App.TODOIST,
            "deleted",
            tid,
            "malformed task deleted",
            _delete_task(tid, clock.at(7, 9)),
        )
    if clock.weekday(day) < 5 and day != 12:
        tid, at = b.task_id(), b.work_hour(day)
        title = b.rng.choice(TASK_TITLES)
        task = TodoistTask(
            tid,
            title,
            "2302",
            at,
            at,
            priority=b.rng.randint(1, 4),
            due_date=clock.first_day + timedelta(days=day + 1),
        )
        b.change(at, App.TODOIST, "created", tid, f"task added: {title}", _put_task(task))
        done = sorted(b.initial.todoist)[day % len(b.initial.todoist)]
        done_at = b.work_hour(day)
        b.change(
            done_at, App.TODOIST, "completed", done, "task completed", _complete_task(done, done_at)
        )


#: The day whose brief has nothing to report: no app changes since the day before's brief, no events.
EMPTY_DAY = 12


def _quiet(clock: Clockwork, changes: list[Change]) -> list[Change]:
    """Drop every change from the brief before the empty day to the day after it.

    Future events created inside that span are created just before it instead, so the
    days after keep their calendar.
    """
    start, end = clock.at(EMPTY_DAY - 1, 8), clock.at(EMPTY_DAY + 1)
    kept: list[Change] = []
    for change in changes:
        if not start <= change.at < end:
            kept.append(change)
        elif change.app is App.CALENDAR and change.kind == "created":
            kept.append(replace(change, at=start - timedelta(hours=1)))
    return kept


def founder_world(origin: datetime, days: int, seed: int = 7) -> World:
    """Build the busy founder's world from the origin instant (sim day 0) over days."""
    tz = ZoneInfo("Asia/Kolkata")
    clock = Clockwork(tz, origin.astimezone(tz).date())
    b = _Builder(clock, seed)
    _seed_github(b)
    _seed_todoist(b)
    _calendar_specials(b)
    for day in range(days):
        if day == EMPTY_DAY:
            continue
        _evolve_github(b, day)
        _calendar_day(b, day)
        _evolve_todoist(b, day)
    changes = _quiet(clock, b.changes)
    faults = [
        Fault(App.CALENDAR, clock.at(4), clock.at(5), FaultMode.UNAVAILABLE),
        Fault(App.GITHUB, clock.at(8, 6), clock.at(9, 12), FaultMode.DEAD_GRANT),
        Fault(App.TODOIST, clock.at(10, 7, 30), clock.at(10, 9, 30), FaultMode.RATE_LIMITED),
    ]
    return World(me=ME, timezone=str(tz), initial=b.initial, changes=changes, faults=faults)
