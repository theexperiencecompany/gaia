"""The simulated outside world: each app's records, every change to them, and when each app was down.

A World is a pure function of its scenario: the state at any instant is the initial records
with every change up to that instant applied. The fake server and the oracle build the same
World from the same scenario, so what the server answered and what the oracle expects agree.
"""

from collections.abc import Callable
import copy
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Literal


class App(StrEnum):
    CALENDAR = "googlecalendar"
    GITHUB = "github"
    TODOIST = "todoist"


class FaultMode(StrEnum):
    """How an app misbehaves during a fault window, as its real API would."""

    UNAVAILABLE = "unavailable"  # 503 from the provider
    DEAD_GRANT = "dead_grant"  # 401: the token was revoked and Composio's refresh failed
    RATE_LIMITED = "rate_limited"  # 429 with retry-after


@dataclass
class CalendarEvent:
    id: str
    title: str
    created: datetime
    updated: datetime
    #: Timed events carry start/end and the organizer's zone; all-day events carry all_day.
    start: datetime | None = None
    end: datetime | None = None
    organizer_tz: str = "UTC"
    all_day: date | None = None
    status: Literal["confirmed", "cancelled"] = "confirmed"
    self_response: Literal["accepted", "declined", "needsAction"] = "accepted"
    location: str | None = None


@dataclass
class GithubItem:
    number: int
    title: str
    kind: Literal["pr", "issue"]
    author: str
    created: datetime
    updated: datetime
    assignees: list[str] = field(default_factory=list)
    reviewers: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    state: Literal["open", "closed"] = "open"
    closed_at: datetime | None = None


@dataclass
class TodoistTask:
    id: str
    #: None is a malformed record: the provider sent the task without its content.
    content: str | None
    project_id: str
    created: datetime
    updated: datetime
    priority: int = 1
    due_date: date | None = None
    due_datetime: datetime | None = None
    completed_at: datetime | None = None
    deleted: bool = False


@dataclass
class AppState:
    calendar: dict[str, CalendarEvent] = field(default_factory=dict)
    github: dict[int, GithubItem] = field(default_factory=dict)
    todoist: dict[str, TodoistTask] = field(default_factory=dict)


@dataclass(frozen=True)
class Change:
    """One thing that happened in an app, with the record it touched and how it changed it."""

    at: datetime
    app: App
    kind: str  # created, edited, closed, reassigned, deleted, moved, cancelled, declined, completed
    ref: str  # the record's id in its app (event id, issue number, task id)
    summary: str
    apply: Callable[[AppState], None] = field(compare=False, repr=False)


@dataclass(frozen=True)
class Fault:
    app: App
    start: datetime
    end: datetime
    mode: FaultMode

    def covers(self, at: datetime) -> bool:
        return self.start <= at < self.end


@dataclass
class World:
    """One simulated user's apps: their starting records, every change, and every fault."""

    me: str  # the user's handle in their apps
    timezone: str
    initial: AppState
    changes: list[Change]
    faults: list[Fault]

    def __post_init__(self) -> None:
        self.changes.sort(key=lambda c: c.at)

    def state_at(self, at: datetime) -> AppState:
        state = copy.deepcopy(self.initial)
        for change in self.changes:
            if change.at > at:
                break
            change.apply(state)
        return state

    def fault_at(self, app: App, at: datetime) -> Fault | None:
        return next((f for f in self.faults if f.app == app and f.covers(at)), None)

    def changes_between(self, start: datetime, end: datetime) -> list[Change]:
        return [c for c in self.changes if start < c.at <= end]
