"""Workflow runs that failed since the last brief, as candidates the user may want to retry.

A workflow whose latest finished run succeeded after its failures recovered: it needs
nothing, and its item says how often it failed before it did.
"""

from datetime import datetime
from itertools import groupby

from app.constants.briefing import (
    BRIEFING_RHYTHM_WORKFLOW_KEYS,
    GAIA_APP_NAME,
    GAIA_SOURCE,
    BriefAction,
)
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_candidate_models import (
    BriefCandidate,
    CandidateOrigin,
    GaiaRef,
    GaiaRefKind,
)
from app.models.brief_item_models import ItemState
from app.models.workflow_execution_models import WorkflowExecutionDocument

# Runs the brief reads, newest first, enough for a workflow running hourly all day.
_RUNS_READ = 200
_FINISHED = frozenset({"success", "failed"})


def _candidate(title: str, runs: list[WorkflowExecutionDocument]) -> BriefCandidate | None:
    """Say how one workflow's runs since went: still failing, recovered, or None with no failure."""
    failures = [r for r in runs if r.status == "failed"]
    if not failures:
        return None
    times = f"failed {len(failures)} time(s) since the last brief"
    latest = next(r for r in runs if r.status in _FINISHED)
    workflow = GaiaRef(kind=GaiaRefKind.WORKFLOW, id=latest.workflow_id)
    if latest.status == "success":
        return BriefCandidate(
            origin=CandidateOrigin.FAILED_RUN,
            source=GAIA_SOURCE,
            app=GAIA_APP_NAME,
            seen_as=workflow,
            state=ItemState.NOTE,
            title=f"{title} recovered",
            detail=f"{times}, then its latest run succeeded",
        )
    return BriefCandidate(
        origin=CandidateOrigin.FAILED_RUN,
        source=GAIA_SOURCE,
        app=GAIA_APP_NAME,
        seen_as=workflow,
        state=ItemState.FAILED,
        title=f"{title} failed",
        detail=" | ".join(part for part in (failures[0].error_message, times) if part),
        action=BriefAction.RETRY,
    )


async def failed_run_candidates(user_id: str, since: datetime) -> list[BriefCandidate]:
    """Return one candidate per workflow whose runs failed since, newest first, saying whether it recovered."""
    briefing_workflows = await workflow_repository.find_system_workflows(
        user_id, BRIEFING_RHYTHM_WORKFLOW_KEYS
    )
    runs = await workflow_executions_repository.list_since(
        user_id,
        since,
        exclude_workflow_ids=[w.id for w in briefing_workflows],
        limit=_RUNS_READ,
    )
    failing = list(dict.fromkeys(r.workflow_id for r in runs if r.status == "failed"))
    if not failing:
        return []
    titles = {
        w.id: w.title for w in await workflow_repository.find_by_ids_for_user(failing, user_id)
    }
    by_workflow = {
        workflow_id: list(group)
        for workflow_id, group in groupby(
            sorted(runs, key=lambda r: (r.workflow_id, -r.started_at.timestamp())),
            key=lambda r: r.workflow_id,
        )
        if workflow_id in titles
    }
    newest_first = sorted(by_workflow.values(), key=lambda g: g[0].started_at, reverse=True)
    return [c for group in newest_first if (c := _candidate(titles[group[0].workflow_id], group))]
