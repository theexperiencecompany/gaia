"""Decide whether a workflow run should be asked to author a playbook.

The gate, not the prompt: a run is asked only when there is nothing working to
replay. A playbook that ran cleanly has already answered the question, and
re-asking would spend output tokens re-deciding it on every fire.
"""

from app.agents.prompts.playbook_prompts import (
    PLAYBOOK_CHECK_BRIEF,
    PLAYBOOK_HEAL_BRIEF,
    PLAYBOOK_HEAL_NO_REASON,
    PLAYBOOK_HEAL_VERDICTS,
)
from app.constants.log_tags import LogTag
from app.db.repositories.playbooks import playbook_repository
from app.models.playbook_models import PlaybookDocument, PlaybookRunStatus
from shared.py.wide_events import log


async def playbook_check_brief(workflow_id: str, user_id: str) -> str:
    """The ``<playbook_check>`` block for this run, or ``""`` to stay silent.

    The check brief when the workflow has no playbook at all. The heal brief,
    carrying the recorded reason, when it has one whose last replay stopped or
    finished with a result that was not trusted. Silent when a playbook ran
    cleanly or has not been tried yet.

    Never raises: a lookup failure means the run proceeds without the check,
    which costs a deferred playbook, not a failed workflow.
    """
    try:
        playbook = await playbook_repository.get_for_workflow(workflow_id, user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.WORKFLOW} playbook_check_brief: lookup failed; skipping the check",
            workflow_id=workflow_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return ""

    if playbook is None:
        return PLAYBOOK_CHECK_BRIEF
    if playbook.last_run_status in HEAL_STATUSES:
        return heal_brief(playbook)
    return ""


HEAL_STATUSES = frozenset({PlaybookRunStatus.FAILED, PlaybookRunStatus.SUSPECT})


def heal_brief(playbook: PlaybookDocument) -> str:
    """The heal brief for a playbook whose last replay stopped or was not trusted."""
    verdict = PLAYBOOK_HEAL_VERDICTS.get(playbook.last_run_status.value, "did not hold")
    reason = (playbook.last_run_reason or "").strip() or PLAYBOOK_HEAL_NO_REASON
    return PLAYBOOK_HEAL_BRIEF.format(verdict=verdict, reason=reason)
