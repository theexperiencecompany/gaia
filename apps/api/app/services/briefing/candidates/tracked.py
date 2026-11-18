"""Todos as candidates: what waits on the user, their own open todos, GAIA's work, what got done."""

from collections.abc import Callable
from datetime import datetime

from app.constants.briefing import (
    DUE_TODO_CANDIDATES_LIMIT,
    GAIA_APP_NAME,
    GAIA_SOURCE,
    UNDATED_TODO_CANDIDATES_LIMIT,
    BriefAction,
    BriefOutcome,
)
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.todos import (
    NEEDS_REPLY_LABEL,
    WAITING_FOR_APPROVAL_LABEL,
    WAITING_FOR_REPLY_LABEL,
    WaitingOn,
)
from app.db.repositories.todos import todo_repository
from app.models.brief_candidate_models import BriefCandidate
from app.models.briefing_models import BriefingItemKind
from app.models.scheduler_models import DeactivationReason
from app.models.todo_models import ExternalRefSource, TodoDocument
from app.services.briefing.candidates.app_names import integration_name
from app.services.briefing.candidates.subjects import subject_key
from app.services.briefing.clock import UserClock, due_on
from app.services.briefing.work import TrackedWork, finished_by


def _source(doc: TodoDocument) -> tuple[str, str]:
    """Name where a todo came from: a mail thread the inbox desk opened is Gmail's, the rest GAIA's."""
    if doc.external_ref is not None and doc.external_ref.source is ExternalRefSource.GMAIL_THREAD:
        return GMAIL_INTEGRATION_ID, integration_name(GMAIL_INTEGRATION_ID)
    return GAIA_SOURCE, GAIA_APP_NAME


# What a todo waiting on the user asks, by the label that says why it waits; any other asks a look.
_ASKED_BY_LABEL: dict[str, BriefAction] = {
    WAITING_FOR_APPROVAL_LABEL: BriefAction.APPROVE,
    NEEDS_REPLY_LABEL: BriefAction.REPLY,
}


def _asked(doc: TodoDocument) -> BriefAction:
    if doc.waiting_on is WaitingOn.USER:
        return BriefAction.REPLY
    return next(
        (action for label, action in _ASKED_BY_LABEL.items() if label in doc.labels),
        BriefAction.REVIEW,
    )


def _retried(_doc: TodoDocument) -> BriefAction:
    return BriefAction.RETRY


def _attended(_doc: TodoDocument) -> BriefAction:
    return BriefAction.ATTEND


def _grouped(
    docs: list[TodoDocument],
    state: BriefingItemKind,
    *,
    action: Callable[[TodoDocument], BriefAction] | None = None,
    outcome: Callable[[TodoDocument], BriefOutcome | None] | None = None,
    standing: Callable[[TodoDocument], str | None] | None = None,
) -> list[BriefCandidate]:
    """One candidate per subject, counting the todos it stands for, in first-seen order."""
    by_subject: dict[str, BriefCandidate] = {}
    for doc in docs:
        key = subject_key(doc)
        if key in by_subject:
            by_subject[key].count += 1
            continue
        source, app = _source(doc)
        ref = doc.external_ref
        by_subject[key] = BriefCandidate(
            source=source,
            app=app,
            ref=f"{source}:{ref.id}" if ref is not None and source != GAIA_SOURCE else None,
            state=state,
            title=doc.title,
            # Of a todo the brief says only what is meant for the user: the question GAIA asks
            # them. Its description is GAIA's own brief to itself, never theirs to read.
            detail=(doc.question if doc.waiting_on is WaitingOn.USER else None) or None,
            due_at=doc.due_date,
            todo_id=doc.id,
            action=action(doc) if action is not None else None,
            outcome=outcome(doc) if outcome is not None else None,
            finished_by=finished_by(doc) if doc.completed else None,
            standing=standing(doc) if standing is not None else None,
        )
    return list(by_subject.values())


def waiting_candidates(work: TrackedWork) -> list[BriefCandidate]:
    """Return the tracked todos waiting on the user, then the ones that failed."""
    return _grouped(work.blocked, "you", action=_asked) + _grouped(
        work.failed, "failed", action=_retried
    )


async def own_todo_candidates(
    user_id: str, due_before: datetime, work: TrackedWork
) -> list[BriefCandidate]:
    """Return the user's own open todos due before the cutoff, then their oldest undated ones.

    An undated one is backlog: on their list, never the brief's news. A todo a tracked
    candidate already covers, by id or subject, is left to it.
    """
    tracked = [*work.completed, *work.running, *work.blocked, *work.failed]
    tracked_ids = {doc.id for doc in tracked}
    tracked_subjects = {subject_key(doc) for doc in tracked}

    docs = [
        *await todo_repository.list_open_user_todos(
            user_id, limit=DUE_TODO_CANDIDATES_LIMIT, due_before=due_before
        ),
        *await todo_repository.list_undated_user_todos(
            user_id, limit=UNDATED_TODO_CANDIDATES_LIMIT
        ),
    ]
    own = [d for d in docs if d.id not in tracked_ids and subject_key(d) not in tracked_subjects]
    return [
        c.model_copy(update={"backlog": c.due_at is None})
        for c in _grouped(own, "you", action=_attended)
    ]


_PAUSED_BECAUSE: dict[DeactivationReason, str] = {
    DeactivationReason.USER_DORMANT: "while the user was away",
    DeactivationReason.INTEGRATION_EXPIRED: "its app's connection expired",
    DeactivationReason.INTEGRATION_NEVER_CONNECTED: "the app it needs was never connected",
    DeactivationReason.SUBSCRIPTION_LAPSED: "the user's plan lapsed",
    DeactivationReason.INVALID_SCHEDULE: "its schedule is invalid",
    DeactivationReason.OWNER_NOT_FOUND: "its owner is gone",
}


def standing(doc: TodoDocument, clock: UserClock) -> str | None:
    """Say where open tracked work stands when it is not simply GAIA working: paused, waiting, unplanned."""
    when = due_on(doc.scheduled_at, clock) if doc.scheduled_at is not None else None
    if doc.pause_reason is not None:
        return f"paused: {_PAUSED_BECAUSE[doc.pause_reason]}"
    if WAITING_FOR_REPLY_LABEL in doc.labels:
        return "waiting on someone else's reply, not the user's"
    waits = {
        WaitingOn.EVENT: "waiting on an event it watches",
        WaitingOn.SUB_TODOS: "its sub-todos are doing the work",
        WaitingOn.TIME: "GAIA looks at it again" + (f" {when}" if when else ""),
        WaitingOn.UNPLANNED: "captured, not started: GAIA plans it" + (f" {when}" if when else ""),
    }
    return waits.get(doc.waiting_on) if doc.waiting_on is not None else None


def _started(doc: TodoDocument) -> BriefOutcome | None:
    """Open work GAIA took up is started; paused or never-planned work is not."""
    if doc.pause_reason is not None or doc.waiting_on is WaitingOn.UNPLANNED:
        return None
    return BriefOutcome.STARTED


def _finished(_doc: TodoDocument) -> BriefOutcome:
    return BriefOutcome.FINISHED


def gaia_work_candidates(work: TrackedWork, clock: UserClock) -> list[BriefCandidate]:
    """Return what was done of GAIA's tracked work since the last brief, then what is still open."""
    return _grouped(work.completed, "lookback", outcome=_finished) + _grouped(
        work.running, "gaia", outcome=_started, standing=lambda doc: standing(doc, clock)
    )


def user_done_candidates(docs: list[TodoDocument]) -> list[BriefCandidate]:
    """Return what the user finished themselves, one candidate per subject."""
    return _grouped(docs, "lookback", outcome=_finished)
