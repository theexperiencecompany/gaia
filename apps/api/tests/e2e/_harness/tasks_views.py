"""What a user can see of their tasks, in words that outlive todos and workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class TaskNotFoundError(Exception):
    """The user asked for a task, or a part of one, that is not there."""


class TaskRefusedError(Exception):
    """The app refused the user's change to a task, saying why."""


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
    #: When GAIA next looks at the task.
    next_run: datetime | None = None
    #: Why the system paused the task, as the panel names it; None while it is on.
    paused_reason: str | None = None
    #: The apps the task waits to be connected again before it resumes.
    paused_for_apps: tuple[str, ...] = ()
    #: The task shows it waits on something outside GAIA: a reply, an approval, a block.
    blocked: bool = False
    #: The app events its subscriptions' "only when" conditions turned away, by what each was about.
    skipped_events: tuple[str, ...] = ()


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
    #: The run replayed the task's saved calls instead of reasoning the work out.
    replayed: bool = False
    #: An app event the task listens for started the run.
    by_event: bool = False


@dataclass(frozen=True)
class RepeatingTaskView:
    """A task GAIA runs on a schedule or an app event, as its page shows it."""

    id: str
    title: str
    active: bool
    next_run: datetime | None = None
    paused_reason: str | None = None
    #: The events its "only when" condition turned away, by what each was about.
    skipped_events: tuple[str, ...] = ()


class OnEvent(StrEnum):
    """What an app event a task listens for does to it."""

    RUN = "execute"
    TELL_ME = "notify"
    CLOSE = "complete"
    UNBLOCK = "unblock"


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
class KeepsWaiting:
    """GAIA checks on what it waits for, finds it not there yet, and keeps waiting."""

    report: str


@dataclass(frozen=True)
class Breaks:
    """The model provider is down for the whole run."""


@dataclass(frozen=True)
class NeedsApproval:
    """GAIA reaches an action the user asked to approve first, and waits on the approval."""

    asking: str


@dataclass(frozen=True)
class OpensSubtasks:
    """GAIA splits the work into sub-tasks and waits for them."""

    titles: tuple[str, ...]
    report: str


@dataclass(frozen=True)
class OpensReplyTask:
    """GAIA finds an email thread that needs the user's reply and opens a sub-task for it."""

    thread_id: str
    title: str
    report: str


@dataclass(frozen=True)
class SavesPlaybook:
    """GAIA does a repeating task's work with a tool call and saves the calls to replay next time."""

    report: str


@dataclass(frozen=True)
class ReplaysPlaybook:
    """GAIA replays the saved calls without reasoning the work out, and writes up their result."""

    report: str


#: What GAIA does on one run, as a journey scripts it.
GaiaRun = (
    Finishes
    | Reports
    | Asks
    | KeepsWaiting
    | Breaks
    | OpensSubtasks
    | NeedsApproval
    | OpensReplyTask
    | SavesPlaybook
    | ReplaysPlaybook
)


@dataclass(frozen=True)
class ChatLine:
    """One message in a task's chat, the user's or GAIA's."""

    by_user: bool
    text: str
    #: The tool cards the message shows, by the tool each one is for.
    cards: tuple[str, ...] = ()


@dataclass(frozen=True)
class Delivered:
    """A message GAIA posted to the user about a task: in the app, or on a linked platform."""

    title: str
    body: str
    channel: str
