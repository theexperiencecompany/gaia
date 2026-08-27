"""Decide whether a workflow run should be asked to author a playbook.

The gate, not the prompt: a run is asked only when there is nothing working to
replay. A playbook that ran cleanly has already answered the question, and
re-asking would spend output tokens re-deciding it on every fire.
"""

from app.agents.prompts.playbook_prompts import (
    PLAYBOOK_CHECK_BRIEF,
    PLAYBOOK_HEAL_ALREADY_RAN,
    PLAYBOOK_HEAL_BRIEF,
    PLAYBOOK_HEAL_NO_REASON,
    PLAYBOOK_HEAL_VERDICTS,
)
from app.constants.agents import PLAYBOOK_DECLINE_LIMIT
from app.constants.log_tags import LogTag
from app.db.repositories.playbooks import playbook_repository
from app.db.repositories.workflows import workflow_repository
from app.models.playbook_models import PlaybookDocument, PlaybookRunStatus
from app.models.workflow_models import WorkflowDocument
from app.services.workflow.playbook.workflow_hash import workflow_hash
from shared.py.wide_events import log


async def playbook_check_brief(
    workflow_id: str, user_id: str, *, fallback_note: str | None = None
) -> str:
    """The ``<playbook_check>`` block for this run, or ``""`` to stay silent.

    The check brief when the workflow has no playbook at all, unless earlier
    runs have declined it ``PLAYBOOK_DECLINE_LIMIT`` times for the workflow as
    it stands. The heal brief, carrying the recorded reason, when it has one
    whose last replay stopped or finished with a result that was not trusted.
    Silent when a playbook ran cleanly or has not been tried yet.

    ``fallback_note`` is the record of a replay that stopped partway in THIS
    fire. It is merged into the heal brief verbatim, so the executor reads
    "these steps already ran" next to "do the work yourself" instead of only
    the second.

    Never raises: a lookup failure means the run proceeds without the check,
    which costs a deferred playbook, not a failed workflow.
    """
    try:
        playbook = await playbook_repository.get_for_workflow(workflow_id, user_id)
        workflow = (
            await workflow_repository.get_for_user(workflow_id, user_id)
            if playbook is None
            else None
        )
    except Exception as e:
        log.warning(
            f"{LogTag.WORKFLOW} playbook_check_brief: lookup failed; skipping the check",
            workflow_id=workflow_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return ""

    if playbook is None:
        if workflow is not None and declined_for_good(workflow):
            log.set_ns(
                "playbook",
                check_skipped="declined",
                declines=workflow.playbook_declines,
            )
            return ""
        if fallback_note:
            return f"{fallback_note.strip()}\n\n{PLAYBOOK_CHECK_BRIEF}"
        return PLAYBOOK_CHECK_BRIEF
    if fallback_note or playbook.last_run_status in HEAL_STATUSES:
        return heal_brief(playbook, fallback_note=fallback_note)
    return ""


HEAL_STATUSES = frozenset({PlaybookRunStatus.FAILED, PlaybookRunStatus.SUSPECT})


def declined_for_good(workflow: WorkflowDocument) -> bool:
    """Declined past the limit for the workflow exactly as it stands now."""
    return (
        workflow.playbook_declines >= PLAYBOOK_DECLINE_LIMIT
        and workflow.playbook_declined_hash == workflow_hash(workflow.prompt, workflow.steps)
    )


def heal_brief(playbook: PlaybookDocument, *, fallback_note: str | None = None) -> str:
    """The heal brief for a playbook whose last replay stopped or was not trusted."""
    verdict = PLAYBOOK_HEAL_VERDICTS.get(playbook.last_run_status.value, "did not hold")
    reason = (playbook.last_run_reason or "").strip() or PLAYBOOK_HEAL_NO_REASON
    already_ran = (
        PLAYBOOK_HEAL_ALREADY_RAN.format(fallback_note=fallback_note.strip())
        if fallback_note
        else ""
    )
    return PLAYBOOK_HEAL_BRIEF.format(verdict=verdict, reason=reason, already_ran=already_ran)
