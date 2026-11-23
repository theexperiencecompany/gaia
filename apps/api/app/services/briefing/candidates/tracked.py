"""Todos as candidates: what waits on the user, their own open todos, GAIA's work, what got done."""

from collections.abc import Callable, Sequence
from datetime import datetime

from app.agents.prompts.brief_fact_prompts import (
    PAUSED_BECAUSE,
    STANDING_PAUSED,
    STANDING_TIMED_WAITS,
    STANDING_WAITING_ON_OTHERS,
    STANDING_WAITS,
)
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
from app.models.brief_candidate_models import BriefCandidate, CandidateOrigin, OutsideRef
from app.models.brief_item_models import ItemState
from app.models.todo_models import ExternalRefSource, TodoDocument
from app.services.briefing.candidates.app_names import integration_name
from app.services.briefing.candidates.subjects import subject_key
from app.services.briefing.work import TrackedWork, finished_by
from app.utils.timezone import as_utc


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
    docs: Sequence[TodoDocument],
    origin: CandidateOrigin,
    state: ItemState,
    *,
    action: Callable[[TodoDocument], BriefAction] | None = None,
    outcome: Callable[[TodoDocument], BriefOutcome | None] | None = None,
    stands: bool = False,
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
            origin=origin,
            source=source,
            app=app,
            ref=OutsideRef(integration_id=source, external_id=ref.id)
            if ref is not None and source != GAIA_SOURCE
            else None,
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
            standing=standing(doc) if stands else None,
            back_at=back_at(doc) if stands else None,
        )
    return list(by_subject.values())


def waiting_candidates(work: TrackedWork) -> list[BriefCandidate]:
    """Return the tracked todos waiting on the user, then the ones that failed."""
    tracked = CandidateOrigin.TRACKED
    return _grouped(work.blocked, tracked, ItemState.YOU, action=_asked) + _grouped(
        work.failed, tracked, ItemState.FAILED, action=_retried
    )


def own_todo_candidates(
    open_own: Sequence[TodoDocument], due_before: datetime, work: TrackedWork
) -> list[BriefCandidate]:
    """Return the user's own open todos due before the cutoff, most overdue first, then their oldest undated ones.

    An undated one is backlog: on their list, never the brief's news. A todo a tracked
    candidate already covers, by id or subject, is left to it. Ties keep creation order.
    """
    tracked = [*work.completed, *work.running, *work.blocked, *work.failed]
    tracked_ids = {doc.id for doc in tracked}
    tracked_subjects = {subject_key(doc) for doc in tracked}
    due = sorted(
        (d for d in open_own if d.due_date is not None and as_utc(d.due_date) < due_before),
        key=lambda d: (as_utc(d.due_date), d.id),
    )[:DUE_TODO_CANDIDATES_LIMIT]
    undated = sorted(
        (d for d in open_own if d.due_date is None), key=lambda d: (as_utc(d.created_at), d.id)
    )[:UNDATED_TODO_CANDIDATES_LIMIT]
    own = [
        d
        for d in [*due, *undated]
        if d.id not in tracked_ids and subject_key(d) not in tracked_subjects
    ]
    return [
        c if c.due_at is not None else c.model_copy(update={"origin": CandidateOrigin.BACKLOG})
        for c in _grouped(own, CandidateOrigin.OWN_TODO, ItemState.YOU, action=_attended)
    ]


def standing(doc: TodoDocument) -> str | None:
    """Say where open tracked work stands when it is not simply GAIA working: paused, waiting, unplanned."""
    if doc.pause_reason is not None:
        return STANDING_PAUSED.format(why=PAUSED_BECAUSE[doc.pause_reason])
    if WAITING_FOR_REPLY_LABEL in doc.labels:
        return STANDING_WAITING_ON_OTHERS
    return STANDING_WAITS.get(doc.waiting_on) if doc.waiting_on is not None else None


def back_at(doc: TodoDocument) -> datetime | None:
    """Return when GAIA comes back to open work whose standing waits on a time; None for any other."""
    timed = (
        doc.waiting_on in STANDING_TIMED_WAITS
        and doc.pause_reason is None
        and WAITING_FOR_REPLY_LABEL not in doc.labels
    )
    return doc.scheduled_at if timed else None


def _started(doc: TodoDocument) -> BriefOutcome | None:
    """Open work GAIA took up is started; paused or never-planned work is not."""
    if doc.pause_reason is not None or doc.waiting_on is WaitingOn.UNPLANNED:
        return None
    return BriefOutcome.STARTED


def _finished(_doc: TodoDocument) -> BriefOutcome:
    return BriefOutcome.FINISHED


def gaia_work_candidates(work: TrackedWork) -> list[BriefCandidate]:
    """Return what was done of GAIA's tracked work since the last brief, then what is still open."""
    tracked = CandidateOrigin.TRACKED
    return _grouped(work.completed, tracked, ItemState.LOOKBACK, outcome=_finished) + _grouped(
        work.running,
        tracked,
        ItemState.GAIA,
        outcome=_started,
        stands=True,
    )


def user_done_candidates(docs: list[TodoDocument]) -> list[BriefCandidate]:
    """Return what the user finished themselves, one candidate per subject."""
    return _grouped(docs, CandidateOrigin.USER_DONE, ItemState.LOOKBACK, outcome=_finished)
