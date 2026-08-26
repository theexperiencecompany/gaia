"""Decide whether a workflow run should be asked to author a playbook.

The gate, not the prompt: a run is asked only when there is nothing working to
replay. A playbook that ran cleanly has already answered the question, and
re-asking would spend output tokens re-deciding it on every fire.
"""

from app.agents.prompts.playbook_prompts import PLAYBOOK_CHECK_BRIEF
from app.constants.log_tags import LogTag
from app.db.repositories.playbooks import playbook_repository
from app.models.playbook_models import PlaybookRunStatus
from shared.py.wide_events import log


async def playbook_check_brief(workflow_id: str, user_id: str) -> str:
    """The ``<playbook_check>`` block for this run, or ``""`` to stay silent.

    Asked when the workflow has no playbook at all, or has one whose last replay
    failed. Silent when a playbook ran cleanly or has not been tried yet.

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

    if playbook is not None and playbook.last_run_status is not PlaybookRunStatus.FAILED:
        return ""
    return PLAYBOOK_CHECK_BRIEF
