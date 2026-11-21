"""What a user can see of their tasks, in words that outlive todos and workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    paused: bool = False
    waiting_on_user: bool = False
    question: str | None = None
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


@dataclass(frozen=True)
class Delivered:
    """A message GAIA posted to the user about a task: in-app, or on a linked platform."""

    text: str
    channel: str
    extra: dict[str, object] = field(default_factory=dict)
