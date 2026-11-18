"""The work a brief reports, read once per run: what got done and by whom, GAIA's open work, the user's todos.

BriefReads is the run's one read of the todos store and the brief's own workflows; every
count and list the brief shows of that work is derived from it, each todo's finisher
classified once.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.constants.briefing import BRIEFING_RHYTHM_WORKFLOW_KEYS, WEEK_LIST_LIMIT
from app.constants.todos import (
    FAILED_LABEL,
    GAIA_TRACKED_LABEL,
    NEEDS_USER_LABELS,
    TodoCompleter,
    WaitingOn,
)
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_payload_models import BriefingEvent, BriefingWeek, BriefingWeekDay
from app.models.todo_models import ExternalRefSource, TodoDocument
from app.services.briefing.candidates.subjects import subject_key
from app.services.briefing.clock import UserClock
from app.utils.timezone import as_utc

# Open tracked todos the brief reports on (in progress / waiting on the user / failed).
_TRACKED_WORK_LIMIT = 20


def is_gaia_tracked(doc: TodoDocument) -> bool:
    return GAIA_TRACKED_LABEL in doc.labels


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
#: A closure by an event it watched, or one made before who closed a todo was recorded.
_CLOSED: frozenset[TodoCompleter | None] = frozenset({TodoCompleter.TRIGGER, None})


@dataclass(frozen=True)
class Finish:
    """One completed todo and who closed it."""

    doc: TodoDocument
    by: TodoCompleter | None


@dataclass(frozen=True)
class CompletedWork:
    """Todos completed in a span, newest completion first, each with who closed it."""

    finished: list[Finish] = field(default_factory=list)

    @classmethod
    def of(cls, docs: list[TodoDocument]) -> "CompletedWork":
        return cls([Finish(doc, finished_by(doc)) for doc in docs])

    def since(self, moment: datetime) -> "CompletedWork":
        """Return what was completed at or after moment."""
        return CompletedWork(
            [f for f in self.finished if (done := as_utc(f.doc.completed_at)) and done >= moment]
        )

    def by(self, closers: frozenset[TodoCompleter | None]) -> list[TodoDocument]:
        return [f.doc for f in self.finished if f.by in closers]

    @property
    def docs(self) -> list[TodoDocument]:
        return [f.doc for f in self.finished]

    @property
    def gaia(self) -> list[TodoDocument]:
        return self.by(frozenset({TodoCompleter.GAIA}))

    @property
    def user(self) -> list[TodoDocument]:
        return self.by(frozenset({TodoCompleter.USER}))

    @property
    def closed(self) -> list[TodoDocument]:
        """Closed by an event it watched, or before who closed a todo was recorded."""
        return self.by(_CLOSED)


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


@dataclass(frozen=True)
class BriefReads:
    """The run's one read of the todos store and of the brief's own workflows."""

    #: Completed since the earliest moment the run looks back to, newest completion first.
    completed: CompletedWork
    #: Every open tracked todo, most recently updated first.
    open_tracked: list[TodoDocument]
    #: Every open todo of the user's own, most recently updated first.
    open_own: list[TodoDocument]
    #: The briefing rhythm's own workflows, whose runs are never the user's work.
    rhythm_workflow_ids: list[str]

    def tracked_work(self, since: datetime) -> TrackedWork:
        """GAIA's tracked todos: completed since the cutoff, plus every open one by state.

        The inbox desk itself is left out: it is always open, and the brief reports it
        through its findings (its thread and proposal sub-todos) instead.
        """
        completed = [
            f.doc
            for f in self.completed.since(since).finished
            if is_gaia_tracked(f.doc) and f.by in _REPORTED_CLOSERS
        ]
        # Every open one counts toward the totals; the brief reports on the newest.
        everything = [
            doc
            for doc in self.open_tracked
            if doc.external_ref is None
            or doc.external_ref.source is not ExternalRefSource.INBOX_DESK
        ]
        running, blocked, failed = _by_state(everything[:_TRACKED_WORK_LIMIT])
        whole = _by_state(everything)
        return TrackedWork(
            completed=completed,
            running=running,
            blocked=blocked,
            failed=failed,
            open_subjects=OpenSubjects(*(len({subject_key(d) for d in docs}) for docs in whole)),
        )

    def own_todos(self, clock: UserClock) -> OwnTodos:
        """Count the user's own open todos, and those due before today began on their clock."""
        today = clock.day_start()
        overdue = [d for d in self.open_own if (due := as_utc(d.due_date)) and due < today]
        return OwnTodos(open=len(self.open_own), overdue=len(overdue))


async def read_work(user_id: str, since: datetime) -> BriefReads:
    """Read what the run reports of the user's work, once: completed since since, and everything open."""
    rhythm = await workflow_repository.find_system_workflows(user_id, BRIEFING_RHYTHM_WORKFLOW_KEYS)
    return BriefReads(
        completed=CompletedWork.of(
            await todo_repository.list_completed_since(user_id, since=since)
        ),
        open_tracked=await todo_repository.list_active_tracked(user_id, limit=0),
        open_own=await todo_repository.list_open_user_todos(user_id, limit=0),
        rhythm_workflow_ids=[w.id for w in rhythm],
    )


def count_week(
    clock: UserClock, completed: CompletedWork, ahead: list[BriefingEvent]
) -> BriefingWeek:
    """Count this week's completions by owner and day, beside the week ahead's first events."""
    monday = clock.today - timedelta(days=clock.today.weekday())
    days = [BriefingWeekDay(you=0, gaia=0) for _ in range(7)]
    for finish in completed.finished:
        if finish.by not in (TodoCompleter.GAIA, TodoCompleter.USER):
            continue
        if finish.doc.completed_at is None:
            continue
        index = (clock.day_of(finish.doc.completed_at) - monday).days
        if not 0 <= index < len(days):
            continue
        if finish.by is TodoCompleter.GAIA:
            days[index].gaia += 1
        else:
            days[index].you += 1
    return BriefingWeek(days=days, ahead=ahead[:WEEK_LIST_LIMIT])
