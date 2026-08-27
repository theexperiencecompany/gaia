"""Pause the workflows of users who have stopped using GAIA, and resume them on return.

Nothing else deactivates a workflow on inactivity: the only automatic paths are
``mark_error`` (unrunnable) and ``set_steps`` (missing integration), neither of
which knows when a user was last seen. So a workflow armed months ago keeps
firing — burning LLM spend and delivering notifications nobody is reading.

Pausing goes through ``WorkflowService.deactivate_workflow`` rather than a bulk
write: that is the path that also unregisters the workflow's Composio triggers,
and an integration workflow whose webhook is still registered keeps firing no
matter what ``activated`` says.

Resume only ever touches workflows carrying ``DeactivationReason.USER_DORMANT``.
A workflow the user switched off themselves records no reason, so coming back
from dormancy can never silently re-enable something they deliberately disabled.

"Dormant" is decided across every signal available, never ``last_active_at``
alone: that field is bumped only by a WorkOS web login, so on its own it means
"hasn't opened the web app" and a bot-only user looks dormant while using GAIA
daily. See ``_is_really_dormant``.
"""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.usage_daily import usage_daily_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.models.workflow_models import DeactivationReason, WorkflowDocument
from app.services.workflow.service import WorkflowService
from shared.py.wide_events import log

# 30 days. The original 90 was chosen when the activity signals were both
# incomplete (bot chat recorded nothing) and circular — a user's own workflow
# executions stamped their conversations' ``updatedAt`` and incremented their
# ``usage_daily`` count, so anyone with an armed integration workflow could
# never be judged dormant and the wide threshold was covering for it. Both
# signals now count only human-initiated activity (system conversations are
# excluded from ``has_activity_since``; ``trigger_workflow_executions`` no
# longer records activity), so a month of silence on every real surface —
# web login, chat from any bot, metered feature use — is dormancy.
DORMANCY_THRESHOLD = timedelta(days=30)


class DormantUserWorkflows(BaseModel):
    """One dormant user and the workflows the sweep would pause for them."""

    user_id: str
    last_active_at: datetime | None
    workflow_ids: list[str]


class DormancySweepResult(BaseModel):
    """What one sweep found and did. ``candidates`` is populated on a dry run too,
    which is what the CLI reports before anything is written."""

    dry_run: bool
    cutoff: datetime
    dormant_users: int
    workflows_paused: int
    failures: int
    candidates: list[DormantUserWorkflows] = Field(default_factory=list)


async def _is_really_dormant(user_id: str, cutoff: datetime) -> bool:
    """Whether ``user_id`` shows no activity on ANY signal since ``cutoff``.

    ``users.last_active_at`` is bumped only by a WorkOS web login, so on its own
    it reports "hasn't opened the web app", not "hasn't used GAIA" — a user who
    lives in Telegram looks permanently dormant. Chat activity and metered
    feature use are checked too, and any one of them being recent keeps the
    user's workflows running.
    """
    if await conversation_repository.has_activity_since(user_id, cutoff):
        return False
    # Sum, not truthiness: a pure-automation day writes a usage_daily row with
    # cost but count 0, and a dict holding only zero-count rows is still truthy
    # — which read as "active" and kept automation-only users unsweepable.
    counts = await usage_daily_repository.counts_since(user_id, cutoff.strftime("%Y-%m-%d"))
    return sum(counts.values()) == 0


async def find_dormancy_candidates(
    *, threshold: timedelta = DORMANCY_THRESHOLD, max_users: int | None = None
) -> tuple[datetime, list[DormantUserWorkflows]]:
    """Dormant users that still own at least one activated workflow, with the
    cutoff the cohort was resolved against.

    ``find_dormant_since`` is the pre-filter, not the verdict: a user dormant on
    every signal is necessarily dormant on ``last_active_at`` too, so it returns
    a superset that ``_is_really_dormant`` then narrows.

    ``max_users`` stops after that many candidates. Pausing unregisters each
    workflow's Composio triggers, so the first run over a long-standing backlog
    is a burst of third-party calls — the bound lets an operator drain it in
    batches. Unbounded by default: the daily cron only ever sees newly dormant
    users once the backlog is cleared.

    Raises ``ValueError`` for a non-positive ``threshold``: a zero threshold puts
    the cutoff at the current instant, so every prior activity timestamp falls
    before it and EVERY user reads as dormant. The guard sits here rather than
    only in the CLI so no caller can reach the pause loop with it.
    """
    if threshold <= timedelta(0):
        raise ValueError(f"dormancy threshold must be positive, got {threshold!r}")

    cutoff: datetime = datetime.now(UTC) - threshold
    candidates: list[DormantUserWorkflows] = []

    for user in await user_repository.find_dormant_since(cutoff):
        if max_users is not None and len(candidates) >= max_users:
            break
        workflows: list[WorkflowDocument] = await workflow_repository.find_activated_for_user(
            user.id
        )
        if not workflows or not await _is_really_dormant(user.id, cutoff):
            continue
        candidates.append(
            DormantUserWorkflows(
                user_id=user.id,
                last_active_at=user.last_active_at,
                workflow_ids=[w.id for w in workflows],
            )
        )
    return cutoff, candidates


async def sweep_dormant_workflows(
    *,
    threshold: timedelta = DORMANCY_THRESHOLD,
    dry_run: bool = False,
    max_users: int | None = None,
) -> DormancySweepResult:
    """Pause every activated workflow owned by a user dormant for ``threshold``.

    ``dry_run`` resolves the same cohort and reports it without writing anything.
    ``max_users`` bounds how many dormant users one run processes. A single
    workflow that fails to pause (e.g. Composio unregistration errors) is counted
    and skipped rather than aborting the sweep for every other user. Raises
    ``ValueError`` for a non-positive ``threshold`` (see ``find_dormancy_candidates``).
    """
    cutoff, candidates = await find_dormancy_candidates(threshold=threshold, max_users=max_users)
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
        cutoff=cutoff,
        dormant_users=len(candidates),
        workflows_paused=paused,
        failures=failures,
        candidates=candidates,
    )


async def resume_dormancy_paused_workflows(user_id: str) -> int:
    """Re-activate the workflows this sweep paused for ``user_id``. Returns the count
    resumed. A workflow whose integrations are no longer connected cannot be
    re-activated — it is left paused and logged rather than failing the others."""
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
