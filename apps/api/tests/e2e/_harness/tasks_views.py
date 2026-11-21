"""What a user can see of their tasks, in words that outlive todos and workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class TaskNotFoundError(Exception):
    """The user asked for a task, or a part of one, that is not there."""


class RunOutcome(StrEnum):
    """How one run of a GAIA task ended, as its run history shows it."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Subtask:
    id: str
    title: str
    done: bool


@dataclass(frozen=True)
class TaskView:
    """One task as the list and its detail panel show it."""

    id: str
    title: str
    done: bool
    due: datetime | None = None
    subtasks: tuple[Subtask, ...] = ()
    #: Set only for a task that GAIA works on.
    by_gaia: bool = False
    failed: bool = False
    parent_id: str | None = None
    open_children: int = 0
    pending_approval: bool = False


@dataclass(frozen=True)
class Counts:
    today: int
    overdue: int
    completed: int


@dataclass(frozen=True)
class RunView:
    outcome: RunOutcome
    #: Why a skipped or failed run did not do its work, when the history says.
    reason: str | None = None


@dataclass(frozen=True)
class RepeatingTaskView:
    """A task GAIA runs on a schedule or an app event, as its page shows it."""

    id: str
    title: str
    active: bool
    next_run: datetime | None = None
    total_runs: int = 0
    paused_reason: str | None = None


class NoReply(StrEnum):
    """What GAIA does when the user leaves its question unanswered."""

    ASK_AGAIN = "ask_again"
    PROCEED = "proceed"
    HOLD = "hold"


@dataclass(frozen=True)
class Finishes:
    """GAIA does the work, closes the task, and reports."""

    report: str


@dataclass(frozen=True)
class Reports:
    """GAIA does this run's work and reports; the task stays as it is."""

    report: str


@dataclass(frozen=True)
class Asks:
    """GAIA asks the user a question and waits for the answer."""

    question: str
    if_no_reply: NoReply
    default: str | None = None


@dataclass(frozen=True)
class KeepsHolding:
    """GAIA checks back on an unanswered question and keeps waiting."""

    report: str


@dataclass(frozen=True)
class Breaks:
    """The model provider is down for the whole run."""


@dataclass(frozen=True)
class OpensSubtasks:
    """GAIA splits the work into sub-tasks and waits for them."""

    titles: tuple[str, ...]
    report: str


#: What GAIA does on one run, as a journey scripts it.
GaiaRun = Finishes | Reports | Asks | KeepsHolding | Breaks | OpensSubtasks


@dataclass(frozen=True)
class ChatLine:
    """One message in a task's chat, the user's or GAIA's."""

    by_user: bool
    text: str


@dataclass(frozen=True)
class Delivered:
    """A message GAIA posted to the user about a task: in the app, or on a linked platform."""

    title: str
    body: str
    channel: str
