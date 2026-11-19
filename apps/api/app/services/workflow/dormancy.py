"""Pause the workflows of dormant users, and resume them when the user comes back.

Nothing else deactivates a workflow on inactivity: the only automatic paths are
mark_error (unrunnable) and set_steps (missing integration), neither of which
knows when a user was last seen — so a workflow armed months ago keeps firing.

Pausing goes through WorkflowService.deactivate_workflow, which also
unregisters the workflow's Composio triggers, rather than a bulk write.
Resume only ever touches workflows carrying DeactivationReason.USER_DORMANT,
so a workflow the user switched off themselves is never silently re-enabled.
"Dormant" is ActivityStatus.DORMANT, the one activity scale every surface records to.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.constants.log_tags import LogTag
from app.constants.user_activity import ActivityStatus
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.models.scheduler_models import DeactivationReason
from app.models.workflow_models import WorkflowDocument
from app.services.workflow.service import WorkflowService
from shared.py.wide_events import log


class DormantUserWorkflows(BaseModel):
    """One dormant user and the workflows the sweep would pause for them."""

    user_id: str
    last_active_at: datetime | None
    workflow_ids: list[str]


class DormancySweepResult(BaseModel):
    """What one sweep found and did.

    candidates is populated on a dry run too, which is what the CLI reports
    before anything is written.
    """

    dry_run: bool
    dormant_users: int
    workflows_paused: int
    failures: int
    candidates: list[DormantUserWorkflows] = Field(default_factory=list)


async def find_dormancy_candidates(*, max_users: int | None = None) -> list[DormantUserWorkflows]:
    """Return dormant users owning at least one activated workflow; max_users bounds a run."""
    candidates: list[DormantUserWorkflows] = []
    for user in await user_repository.find_by_activity_status(ActivityStatus.DORMANT):
        if max_users is not None and len(candidates) >= max_users:
            break
        workflows: list[WorkflowDocument] = await workflow_repository.find_activated_for_user(
            user.id
        )
        if not workflows:
            continue
        candidates.append(
            DormantUserWorkflows(
                user_id=user.id,
                last_active_at=user.last_active_at,
                workflow_ids=[w.id for w in workflows],
            )
        )
    return candidates


async def sweep_dormant_workflows(
    *, dry_run: bool = False, max_users: int | None = None
) -> DormancySweepResult:
    """Pause every activated workflow owned by a dormant user.

    dry_run resolves the same cohort and reports it without writing anything.
    A single workflow that fails to pause is counted and skipped rather than
    aborting the sweep for every other user.
    """
    candidates = await find_dormancy_candidates(max_users=max_users)
    paused: int = 0
    failures: int = 0

    if not dry_run:
        for candidate in candidates:
            for workflow_id in candidate.workflow_ids:
                try:
                    await WorkflowService.deactivate_workflow(
                        workflow_id,
                        candidate.user_id,
                        reason=DeactivationReason.USER_DORMANT,
                    )
                    paused += 1
                except Exception as e:
                    failures += 1
                    log.warning(
                        f"{LogTag.WORKFLOW} Dormancy pause failed for workflow",
                        workflow_id=workflow_id,
                        user_id=candidate.user_id,
                        error=str(e),
                        error_type=type(e).__name__,
                    )

    return DormancySweepResult(
        dry_run=dry_run,
        dormant_users=len(candidates),
        workflows_paused=paused,
        failures=failures,
        candidates=candidates,
    )


async def resume_dormancy_paused_workflows(user_id: str) -> int:
    """Re-activate the workflows this sweep paused for user_id; return the count resumed.

    A workflow whose integrations are no longer connected cannot be
    re-activated — it is left paused and logged rather than failing the others.
    """
    resumed = 0

    for workflow in await workflow_repository.find_paused_for_reason(
        user_id, DeactivationReason.USER_DORMANT
    ):
        try:
            await WorkflowService.activate_workflow(workflow.id, user_id)
            resumed += 1
        except Exception as e:
            log.warning(
                f"{LogTag.WORKFLOW} Dormancy resume skipped workflow",
                workflow_id=workflow.id,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    if resumed:
        log.info(
            f"{LogTag.WORKFLOW} Resumed workflows paused for dormancy",
            user_id=user_id,
            resumed=resumed,
        )
    return resumed
