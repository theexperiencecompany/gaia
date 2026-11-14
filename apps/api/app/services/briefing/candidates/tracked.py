"""Todos as candidates: what waits on the user, what is due, what GAIA did or is doing, what got done."""

from collections.abc import Callable
from datetime import datetime

from app.constants.briefing import (
    DUE_TODO_CANDIDATES_LIMIT,
    GAIA_APP_NAME,
    GAIA_SOURCE,
    BriefAction,
    BriefOutcome,
)
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.todos import NEEDS_REPLY_LABEL, WAITING_FOR_APPROVAL_LABEL
from app.db.repositories.todos import todo_repository
from app.models.brief_candidate_models import BriefCandidate
from app.models.briefing_models import BriefingItemKind
from app.models.todo_models import ExternalRefSource, TodoDocument
from app.services.briefing.candidates.app_names import integration_name
from app.services.briefing.candidates.subjects import subject_key
from app.services.briefing.context import TrackedWork


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
    outcome: BriefOutcome | None = None,
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
            detail=doc.description or None,
            due_at=doc.due_date,
            todo_id=doc.id,
            action=action(doc) if action is not None else None,
            outcome=outcome,
        )
    return list(by_subject.values())


def waiting_candidates(work: TrackedWork) -> list[BriefCandidate]:
    """Return the tracked todos waiting on the user, then the ones that failed."""
    return _grouped(work.blocked, "you", action=_asked) + _grouped(
        work.failed, "failed", action=_retried
    )


async def due_todo_candidates(
    user_id: str, due_before: datetime, work: TrackedWork
) -> list[BriefCandidate]:
    """Return the user's own open todos due before the cutoff that no tracked todo already covers."""
    tracked = [*work.completed, *work.running, *work.blocked, *work.failed]
    tracked_ids = {doc.id for doc in tracked}
    tracked_subjects = {subject_key(doc) for doc in tracked}
    docs = await todo_repository.list_open_user_todos(
        user_id, limit=DUE_TODO_CANDIDATES_LIMIT, due_before=due_before
    )
    due = [d for d in docs if d.id not in tracked_ids and subject_key(d) not in tracked_subjects]
    return _grouped(due, "you", action=_attended)


def gaia_work_candidates(work: TrackedWork) -> list[BriefCandidate]:
    """Return what GAIA finished since the last brief, then what it is still working on."""
    return _grouped(work.completed, "lookback", outcome=BriefOutcome.FINISHED) + _grouped(
        work.running, "gaia", outcome=BriefOutcome.STARTED
    )


def user_done_candidates(docs: list[TodoDocument]) -> list[BriefCandidate]:
    """Return what the user finished themselves, one candidate per subject."""
    return _grouped(docs, "lookback", outcome=BriefOutcome.FINISHED)
