"""Deterministic checks of every stored brief against the world's ground truth.

Each check names the bug family it guards and returns Findings with the simulated day, the
item, what the world says and what GAIA printed. A check only judges what it can identify:
an item it cannot tie to a world record is not guessed at.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
import re

from briefsim.oracle.logs import LoggedError
from briefsim.oracle.truth import Brief, ShownItem, Truth, app_of_label, parse_instant, words
from briefsim.world.model import App, CalendarEvent

#: Page sizes the apps (and GAIA's own list limits) cut results at; a count equal to one is suspect.
PAGE_SIZES = frozenset({10, 20, 25, 30, 50, 100})
_COUNT = re.compile(
    r"(?<![#\d-])\b(\d{1,4})\s+(?:new\s+|open\s+|assigned\s+|overdue\s+|unread\s+|pending\s+)*"
    r"(issues?|prs?|pull requests?|tasks?|todos?|to-dos?|meetings?|events?|reviews?)\b",
    re.IGNORECASE,
)
_EMPTY_CALENDAR = re.compile(
    r"\b(no (?:meetings|events)|nothing on (?:your|the) calendar|calendar is (?:clear|empty|free)|"
    r"clear calendar|free day|no calls)\b",
    re.IGNORECASE,
)
_NEW = re.compile(r"\bnew\b", re.IGNORECASE)
DAILY_HOUR = 8
WEEKLY_HOUR = 17
SUNDAY = 6
#: A brief takes a minute or two to compose; one stored later than this after its hour is late.
ON_TIME_SLACK = timedelta(minutes=10)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_DUE_PHRASE = re.compile(
    r"\b(due|overdue since)\s+(today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2})\b",
    re.IGNORECASE,
)
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_GAIA_DID = re.compile(
    r"\bI(?:'ve| have)?\s+(?:finished|completed|closed|wrapped up|sent|booked|did|handled)\b[^.!?\n]*",
    re.IGNORECASE,
)
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AP]M)?\b", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    check: str
    day: str
    brief_id: str
    item: str
    expected: str
    got: str


def _finding(check: str, brief: Brief, item: str, expected: str, got: str) -> Finding:
    return Finding(
        check,
        brief.local_date.isoformat(),
        brief.doc.get("id") or brief.doc["_id"],
        item,
        expected,
        got,
    )


def _local_hhmm(at: datetime, truth: Truth) -> str:
    return at.astimezone(truth.tz).strftime("%H:%M")


def _event_local(event: CalendarEvent, truth: Truth) -> tuple[str, str | None]:
    """Return the event's (local date, local HH:MM or None for all day)."""
    if event.all_day is not None:
        return event.all_day.isoformat(), None
    assert event.start is not None
    return event.start.astimezone(truth.tz).date().isoformat(), _local_hhmm(event.start, truth)


def _calendar_dates(truth: Truth, brief: Brief) -> list[Finding]:
    """Check each calendar entry the brief lists is on its local day, at its local time."""
    today = {e.title: e for e in truth.local_day_events(brief)}
    known = {e.title: e for e in truth.state_at(brief.stored_at).calendar.values()}
    findings = []
    for shown in brief.payload.get("calendar") or []:
        title = shown.get("title", "")
        if title not in known:
            continue
        got = (shown.get("date", ""), shown.get("start"))
        if title not in today:
            findings.append(
                _finding(
                    "local_date",
                    brief,
                    f"event '{title}'",
                    "not on this local day",
                    f"listed for {got[0]}",
                )
            )
            continue
        want = _event_local(today[title], truth)
        if want != got:
            findings.append(
                _finding(
                    "local_date",
                    brief,
                    f"event '{title}'",
                    f"{want[0]} {want[1] or 'all day'}",
                    f"{got[0]} {got[1] or 'all day'}",
                )
            )
    return findings


def _clock_time(match: re.Match[str]) -> str:
    hour, minute, half = int(match.group(1)), int(match.group(2)), (match.group(3) or "").upper()
    if half:
        hour = hour % 12 + (12 if half == "PM" else 0)
    return f"{hour:02d}:{minute:02d}"


def _todo_times(truth: Truth, brief: Brief) -> list[Finding]:
    """Check every time printed on a GAIA todo is its due time in the user's zone."""
    todos = {str(t["todo_id"]): t for t in truth.gaia_todos(brief.stored_at)}
    findings = []
    for item in brief.items:
        todo = todos.get(str(item.todo_id)) if item.todo_id else None
        if todo is None:
            continue
        due = _local_hhmm(parse_instant(str(todo["due"])), truth)
        for match in _TIME.finditer(f"{item.text} {item.detail or ''}"):
            if _clock_time(match) != due:
                findings.append(
                    _finding(
                        "local_date",
                        brief,
                        f"todo '{todo['title']}'",
                        f"due {due} local",
                        match.group(0),
                    )
                )
    return findings


def check_local_date(truth: Truth, brief: Brief) -> list[Finding]:
    """Guard: UTC dates shown as local. The brief's date, its calendar and its todo times are local."""
    expected = brief.stored_at.astimezone(truth.tz).date()
    findings = []
    if brief.local_date != expected:
        findings.append(
            _finding(
                "local_date",
                brief,
                "brief date",
                expected.isoformat(),
                brief.local_date.isoformat(),
            )
        )
    if brief.kind == "daily":
        findings += _calendar_dates(truth, brief) + _todo_times(truth, brief)
    return findings


def _said_due(phrase: str, when: str, today: date) -> date:
    """Return the due date a phrase ("due Thursday", "overdue since Friday") states, seen on today."""
    when = when.lower()
    offsets = {"today": 0, "tomorrow": 1, "yesterday": -1}
    if when in offsets:
        return today + timedelta(days=offsets[when])
    if when[:3] in _MONTHS:
        month, day = _MONTHS.index(when[:3]) + 1, int(when.split()[-1])
        stated = date(today.year, month, day)
        # A date more than half a year ahead is last year's (a December brief saying "since Jan 3").
        return stated if (stated - today).days < 183 else date(today.year - 1, month, day)
    weekday = _WEEKDAYS.index(when)
    if phrase.lower() == "due":
        return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)
    return today - timedelta(days=(today.weekday() - weekday) % 7 or 7)


def _due_of(truth: Truth, brief: Brief, item: ShownItem) -> tuple[str, date | None] | None:
    """Return (name, local due date) of the Todoist task or GAIA todo an item is about, or None."""
    if item.todoist is not None:
        task = truth.state_at(brief.stored_at).todoist[item.todoist]
        return f"task '{task.content}'", task.due_date
    todo = next(
        (t for t in truth.gaia_todos(brief.stored_at) if str(t["todo_id"]) == item.todo_id), None
    )
    if todo is None:
        return None
    return f"todo '{todo['title']}'", parse_instant(str(todo["due"])).astimezone(truth.tz).date()


def check_due_dates(truth: Truth, brief: Brief) -> list[Finding]:
    """Guard: UTC dates shown as local. "Due today" / "overdue since Friday" matches the local due date."""
    findings = []
    for item in brief.items:
        due_of = _due_of(truth, brief, item)
        if due_of is None:
            continue
        name, due = due_of
        for match in _DUE_PHRASE.finditer(f"{item.text} {item.detail or ''}"):
            if due != _said_due(match.group(1), match.group(2), brief.local_date):
                findings.append(
                    _finding(
                        "local_date",
                        brief,
                        name,
                        f"due {due.isoformat() if due else 'never'} (local)",
                        f"'{match.group(0)}' on {brief.local_date:%a %d %b}",
                    )
                )
    return findings


def check_credit_owner(truth: Truth, brief: Brief) -> list[Finding]:
    """Guard: GAIA claims the user's own work. Something the user completed is never "I finished"."""
    titles = {
        str(r["todo_id"]): str(r["title"]) for r in truth.persona if r["action"] == "add_todo"
    }
    done_by_user = [
        titles[str(r["todo_id"])]
        for r in truth.persona
        if r["action"] == "complete_todo"
        and str(r.get("todo_id")) in titles
        and parse_instant(str(r["at"])) <= brief.stored_at
    ]
    findings = []
    for claim in _GAIA_DID.finditer(brief.text()):
        said = words(claim.group(0))
        for title in done_by_user:
            title_words = words(title)
            if len(said & title_words) / max(len(title_words), 1) >= 0.6:
                findings.append(
                    _finding(
                        "credit_owner",
                        brief,
                        title,
                        "credited to the user (they completed it)",
                        f"'{claim.group(0).strip()}'",
                    )
                )
    return findings


def _true_counts(truth: Truth, brief: Brief) -> dict[str, set[int]]:
    """Return every total a count in this brief could honestly mean, by noun family."""
    state = truth.state_at(brief.stored_at)
    me = truth.world.me
    previous = truth.previous(brief)
    since = previous.stored_at if previous else truth.connected_at
    open_issues = [
        i
        for i in state.github.values()
        if i.state == "open" and i.kind == "issue" and me in i.assignees
    ]
    reviews = [
        i
        for i in state.github.values()
        if i.state == "open" and i.kind == "pr" and me in i.reviewers
    ]
    open_prs = [i for i in state.github.values() if i.state == "open" and i.kind == "pr"]
    tasks = [t for t in state.todoist.values() if t.completed_at is None and not t.deleted]
    local_today = brief.local_date
    events = truth.local_day_events(brief)
    todos = truth.gaia_todos(brief.stored_at)
    # GAIA counts its own todos overdue when due before the user's day began.
    day_start = datetime.combine(local_today, time.min, truth.tz)
    overdue_todos = [t for t in todos if t.get("due") and parse_instant(str(t["due"])) < day_start]
    weekly = _weekly_counts(truth, brief) if brief.kind == "weekly" else {}
    issue_like = {
        len(open_issues),
        len([i for i in open_issues if i.created > since]),
        len([i for i in state.github.values() if i.closed_at and i.closed_at > since]),
    }
    return {
        "issue": issue_like,
        "pr": {len(reviews), len(open_prs), len([i for i in reviews if i.created > since])},
        "review": {len(reviews)},
        "task": {
            len(tasks),
            len([t for t in tasks if t.due_date == local_today]),
            len([t for t in tasks if t.due_date and t.due_date < local_today]),
            len(todos),
            len(overdue_todos),
            len([t for t in tasks if t.created > since]),
        }
        | weekly.get("task", set()),
        "meeting": {len(events), len([e for e in events if e.self_response != "declined"])}
        | weekly.get("meeting", set()),
    }


def _weekly_counts(truth: Truth, brief: Brief) -> dict[str, set[int]]:
    """Return the digest's own totals: what was finished since Monday and what the week ahead holds."""
    state = truth.state_at(brief.stored_at)
    monday = brief.local_date - timedelta(days=brief.local_date.weekday())
    week_start = datetime.combine(monday, datetime.min.time(), truth.tz)
    gaia_done = truth.gaia_todos_completed(week_start, brief.stored_at)
    todoist_done = len(
        [
            t
            for t in state.todoist.values()
            if t.completed_at is not None and week_start <= t.completed_at <= brief.stored_at
        ]
    )
    ahead = truth.local_events(brief, brief.local_date + timedelta(days=1), days=7)
    return {
        "task": {gaia_done, todoist_done, gaia_done + todoist_done},
        "meeting": {len(ahead), len([e for e in ahead if e.self_response != "declined"])},
    }


def _family(noun: str) -> str:
    noun = noun.lower()
    if noun.startswith(("pr", "pull")):
        return "pr"
    if noun.startswith("review"):
        return "review"
    if noun.startswith(("task", "todo", "to-do")):
        return "task"
    if noun.startswith(("meeting", "event")):
        return "meeting"
    return "issue"


def check_true_total(truth: Truth, brief: Brief) -> list[Finding]:
    """Guard: capped counts shown as totals. Every "N issues/PRs/tasks/meetings" is a real total."""
    findings = []
    truths = _true_counts(truth, brief)
    for match in _COUNT.finditer(brief.text()):
        count, family = int(match.group(1)), _family(match.group(2))
        honest = truths[family] | {1} if count == 1 else truths[family]
        if count in honest:
            continue
        capped = count in PAGE_SIZES and any(t > count for t in truths[family])
        findings.append(
            _finding(
                "true_total",
                brief,
                match.group(0),
                f"one of {sorted(truths[family])}"
                + (" (looks capped at a page size)" if capped else ""),
                str(count),
            )
        )
    return findings


def check_new_is_new(truth: Truth, brief: Brief) -> list[Finding]:
    """Guard: "first seen" treated as new. An item called new was created since the last brief."""
    findings = []
    previous = truth.previous(brief)
    since = previous.stored_at if previous else truth.connected_at
    state = truth.state_at(brief.stored_at)
    for item in brief.items:
        said = f"{item.section} {item.text} {item.detail or ''}"
        if not _NEW.search(said):
            continue
        created = None
        if item.github is not None:
            created = state.github[item.github].created
        elif item.todoist is not None:
            created = state.todoist[item.todoist].created
        if created is not None and created <= since:
            findings.append(
                _finding(
                    "new_is_new",
                    brief,
                    item.text,
                    f"created {created:%Y-%m-%d %H:%M} UTC, before {since:%Y-%m-%d %H:%M}",
                    "presented as new",
                )
            )
    return findings


def _unavailable_apps(brief: Brief) -> set[App]:
    flagged = set()
    for source in brief.payload.get("sources_unavailable") or []:
        app = app_of_label(source.get("app", ""))
        if app is not None:
            flagged.add(app)
    return flagged


def check_failed_source(truth: Truth, brief: Brief) -> list[Finding]:
    """Guard: failed source reads treated as empty. A source that failed is said to be unavailable."""
    findings = []
    flagged = _unavailable_apps(brief)
    for app, outcomes in truth.read_outcomes(brief).items():
        if "ok" in outcomes:
            continue
        failure = ",".join(sorted(outcomes))
        if app not in flagged:
            findings.append(
                _finding(
                    "failed_source",
                    brief,
                    app.value,
                    f"{app.value} marked unavailable ({failure})",
                    f"sources_unavailable={sorted(a.value for a in flagged)}",
                )
            )
        if app is App.CALENDAR and (claim := _EMPTY_CALENDAR.search(brief.text())):
            findings.append(
                _finding(
                    "failed_source",
                    brief,
                    "calendar",
                    "no claim about the day's meetings (read failed)",
                    f"says '{claim.group(0)}'",
                )
            )
    return findings


def _due_state(due: date | None, on: date) -> str:
    """Say where a task's due date stands on a day: none, upcoming, today or overdue."""
    if due is None:
        return "none"
    return "upcoming" if due > on else "today" if due == on else "overdue"


def _due_moved(truth: Truth, ref: str, previous: Brief, brief: Brief) -> bool:
    """Whether a Todoist task came due or went overdue between two briefs: news, not a repeat."""
    task = truth.state_at(brief.stored_at).todoist.get(ref)
    due = task.due_date if task is not None else None
    return _due_state(due, previous.local_date) != _due_state(due, brief.local_date)


def check_no_stale_repeat(truth: Truth, brief: Brief) -> list[Finding]:
    """Guard: stale items resurfacing daily. An app item unchanged since the last brief is not shown again.

    A task that came due or went overdue since the last brief has changed: the brief may say so.
    """
    previous = truth.previous(brief)
    if previous is None or brief.kind != "daily":
        return []
    before = {
        (i.github, i.todoist)
        for i in previous.items
        if i.github is not None or i.todoist is not None
    }
    findings = []
    for item in brief.items:
        key = (item.github, item.todoist)
        if key == (None, None) or key not in before:
            continue
        ref = str(item.github if item.github is not None else item.todoist)
        app = App.GITHUB if item.github is not None else App.TODOIST
        changed = [
            c
            for c in truth.world.changes_between(previous.stored_at, brief.stored_at)
            if c.app is app and c.ref == ref
        ]
        due_moved = app is App.TODOIST and _due_moved(truth, ref, previous, brief)
        if not changed and not due_moved:
            findings.append(
                _finding(
                    "no_stale_repeat",
                    brief,
                    item.text,
                    "not repeated: unchanged since the last brief",
                    f"shown again (also on {previous.local_date})",
                )
            )
    return findings


def _scheduled_at(truth: Truth, brief: Brief) -> datetime:
    """Return when the brief was due: 08:00 local daily, Sunday 17:00 local weekly, at the user's slot minute."""
    hour = WEEKLY_HOUR if brief.kind == "weekly" else DAILY_HOUR
    minute = truth.slot_minutes.get(brief.kind, 0)
    return datetime.combine(brief.local_date, time(hour, minute), truth.tz)


def check_on_time(truth: Truth, brief: Brief) -> list[Finding]:
    """Guard: briefs that arrive late (a lost job, a stuck run). Stored within minutes of its hour."""
    due = _scheduled_at(truth, brief)
    late = brief.stored_at - due
    if timedelta(0) <= late <= ON_TIME_SLACK:
        return []
    return [
        _finding(
            "on_time",
            brief,
            f"{brief.kind} brief",
            f"stored by {(due + ON_TIME_SLACK):%a %H:%M} local",
            f"stored {brief.stored_at.astimezone(truth.tz):%a %H:%M} local",
        )
    ]


def check_delivered(truth: Truth, brief: Brief) -> list[Finding]:
    """Guard: a brief stored but never delivered. One planned as a push reached its channels."""
    del truth
    delivery = brief.doc.get("delivery") or {}
    if not delivery.get("push") or brief.doc.get("delivered_channels"):
        return []
    return [
        _finding(
            "delivered",
            brief,
            f"{brief.kind} brief",
            "delivered to its channels",
            f"stored undelivered (delivery steps done: {delivery.get('done') or []})",
        )
    ]


CHECKS: dict[str, Callable[[Truth, Brief], list[Finding]]] = {
    "local_date": check_local_date,
    "true_total": check_true_total,
    "new_is_new": check_new_is_new,
    "failed_source": check_failed_source,
    "no_stale_repeat": check_no_stale_repeat,
    "due_dates": check_due_dates,
    "credit_owner": check_credit_owner,
    "on_time": check_on_time,
    "delivered": check_delivered,
}


def run_checks(truth: Truth) -> list[dict[str, str]]:
    return [
        asdict(f)
        for brief in truth.briefs
        for check in CHECKS.values()
        for f in check(truth, brief)
    ]


def missing_briefs(
    truth: Truth, days: int, origin: datetime, errors: list[LoggedError]
) -> list[dict[str, str]]:
    """Return a finding for every daily (and Sunday weekly) brief never stored, with what GAIA logged then."""
    first = origin.astimezone(truth.tz).date()
    stored = {(b.local_date, b.kind) for b in truth.briefs}
    findings = []
    for offset in range(1, days):
        day = first + timedelta(days=offset)
        kinds = ["daily", "weekly"] if day.weekday() == SUNDAY else ["daily"]
        for kind in kinds:
            if (day, kind) in stored:
                continue
            causes = sorted(
                {
                    f"{e.message}: {e.error}"
                    for e in errors
                    if e.at.astimezone(truth.tz).date() == day and "workflow" in e.message.lower()
                }
            )
            findings.append(
                asdict(
                    Finding(
                        "brief_stored",
                        day.isoformat(),
                        "",
                        f"{kind} brief",
                        "one stored",
                        "none; " + ("; ".join(causes) or "nothing logged that day"),
                    )
                )
            )
    return findings
