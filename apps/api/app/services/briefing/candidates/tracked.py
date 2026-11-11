"""Todos as candidates: what waits on the user, what GAIA did or is doing, and what the user finished."""

from app.constants.briefing import GAIA_APP_NAME, GAIA_SOURCE, BriefAction, BriefOutcome
from app.constants.integrations import GMAIL_INTEGRATION_ID
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


def _grouped(
    docs: list[TodoDocument],
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
            action=action,
            outcome=outcome,
        )
    return list(by_subject.values())


def waiting_candidates(work: TrackedWork) -> list[BriefCandidate]:
    """Return the tracked todos waiting on the user, then the ones that failed."""
    return _grouped(work.blocked, "you", action=BriefAction.REVIEW) + _grouped(
        work.failed, "failed", action=BriefAction.RETRY
    )


def gaia_work_candidates(work: TrackedWork) -> list[BriefCandidate]:
    """Return what GAIA finished since the last brief, then what it is still working on."""
    return _grouped(work.completed, "lookback", outcome=BriefOutcome.FINISHED) + _grouped(
        work.running, "gaia", outcome=BriefOutcome.STARTED
    )


def user_done_candidates(docs: list[TodoDocument]) -> list[BriefCandidate]:
    """Return what the user finished themselves, one candidate per subject."""
    return _grouped(docs, "lookback", outcome=BriefOutcome.FINISHED)
