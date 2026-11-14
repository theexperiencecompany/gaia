"""Todos as candidates: what waits on the user, what is due, what GAIA did or is doing, what got done."""

from datetime import datetime

from app.constants.briefing import (
    DUE_TODO_CANDIDATES_LIMIT,
    GAIA_APP_NAME,
    GAIA_SOURCE,
    BriefAction,
    BriefOutcome,
)
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.db.repositories.todos import todo_repository
from app.models.brief_candidate_models import BriefCandidate, CandidateKind
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


def _grouped(
    docs: list[TodoDocument],
    kind: CandidateKind,
    state: BriefingItemKind,
    *,
    action: BriefAction | None = None,
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
        by_subject[key] = BriefCandidate(
            source=source,
            app=app,
            kind=kind,
            state=state,
            title=doc.title,
            detail=doc.description or None,
            due_at=doc.due_date,
            todo_id=doc.id,
            action=action,
            outcome=outcome,
        )
    return list(by_subject.values())


def waiting_candidates(work: TrackedWork) -> list[BriefCandidate]:
    """Return the tracked todos waiting on the user, then the ones that failed."""
    return _grouped(
        work.blocked, CandidateKind.NEEDS_YOU, "you", action=BriefAction.REVIEW
    ) + _grouped(work.failed, CandidateKind.NEEDS_YOU, "failed", action=BriefAction.RETRY)


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
    return _grouped(due, CandidateKind.NEEDS_YOU, "you", action=BriefAction.ATTEND)


def gaia_work_candidates(work: TrackedWork) -> list[BriefCandidate]:
    """Return what GAIA finished since the last brief, then what it is still working on."""
    return _grouped(
        work.completed, CandidateKind.GAIA_DID, "lookback", outcome=BriefOutcome.FINISHED
    ) + _grouped(work.running, CandidateKind.GAIA_DID, "gaia", outcome=BriefOutcome.STARTED)


def user_done_candidates(docs: list[TodoDocument]) -> list[BriefCandidate]:
    """Return what the user finished themselves, one candidate per subject."""
    return _grouped(docs, CandidateKind.UPDATE, "lookback", outcome=BriefOutcome.FINISHED)
