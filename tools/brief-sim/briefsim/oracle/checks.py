"""Deterministic checks of every stored brief against the world's ground truth.

Each check names the bug family it guards and returns Findings with the simulated day, the
item, what the world says and what GAIA printed. A check only judges what it can identify:
an item it cannot tie to a world record is not guessed at.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import re

from briefsim.oracle.logs import LoggedError
from briefsim.oracle.truth import Brief, Truth, app_of_label, parse_instant, words
from briefsim.world.model import App, CalendarEvent

#: Page sizes the apps (and GAIA's own list limits) cut results at; a count equal to one is suspect.
PAGE_SIZES = frozenset({10, 20, 25, 30, 50, 100})
_COUNT = re.compile(
    r"\b(\d{1,4})\s+(?:new\s+|open\s+|assigned\s+|overdue\s+|unread\s+|pending\s+)*"
    r"(issues?|prs?|pull requests?|tasks?|todos?|to-dos?|meetings?|events?|reviews?)\b",
    re.IGNORECASE,
)
_EMPTY_CALENDAR = re.compile(
    r"\b(no (?:meetings|events)|nothing on (?:your|the) calendar|calendar is (?:clear|empty|free)|"
    r"clear calendar|free day|no calls)\b",
    re.IGNORECASE,
)
_NEW = re.compile(r"\bnew\b", re.IGNORECASE)
_DUE_PHRASE = re.compile(
    r"\b(?:(due|overdue since)\s+(today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
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
    weekday = _WEEKDAYS.index(when)
    if phrase.lower() == "due":
        return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)
    return today - timedelta(days=(today.weekday() - weekday) % 7 or 7)


def check_due_dates(truth: Truth, brief: Brief) -> list[Finding]:
    """Guard: UTC dates shown as local. "Due Thursday" / "overdue since Friday" matches the task's local due date."""
    findings = []
    state = truth.state_at(brief.stored_at)
    for item in brief.items:
        if item.todoist is None:
            continue
        task = state.todoist[item.todoist]
        for match in _DUE_PHRASE.finditer(f"{item.text} {item.detail or ''}"):
            said = _said_due(match.group(1), match.group(2), brief.local_date)
            due = task.due_date
            if due != said:
                findings.append(
                    _finding(
                        "local_date",
                        brief,
                        f"task '{task.content}'",
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
            len([t for t in tasks if t.created > since]),
        },
        "meeting": {len(events), len([e for e in events if e.self_response != "declined"])},
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


def check_no_stale_repeat(truth: Truth, brief: Brief) -> list[Finding]:
    """Guard: stale items resurfacing daily. An app item unchanged since the last brief is not shown again."""
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
        if not changed:
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


CHECKS: dict[str, Callable[[Truth, Brief], list[Finding]]] = {
    "local_date": check_local_date,
    "true_total": check_true_total,
    "new_is_new": check_new_is_new,
    "failed_source": check_failed_source,
    "no_stale_repeat": check_no_stale_repeat,
    "due_dates": check_due_dates,
    "credit_owner": check_credit_owner,
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
    """Return a finding for every local day with no daily brief stored, with what GAIA logged as the cause."""
    first = origin.astimezone(truth.tz).date()
    stored = {b.local_date for b in truth.briefs if b.kind == "daily"}
    findings = []
    for offset in range(1, days):
        day = first + timedelta(days=offset)
        if day in stored:
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
                    "daily brief",
                    "one stored",
                    "none; " + ("; ".join(causes) or "nothing logged"),
                )
            )
        )
    return findings
