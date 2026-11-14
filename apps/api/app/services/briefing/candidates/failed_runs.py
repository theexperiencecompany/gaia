"""Workflow runs that failed since the last brief, as candidates the user may want to retry."""

from datetime import datetime

from app.constants.briefing import (
    BRIEFING_RHYTHM_WORKFLOW_KEYS,
    GAIA_APP_NAME,
    GAIA_SOURCE,
    BriefAction,
)
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_candidate_models import BriefCandidate, CandidateKind

# Failed runs the brief reads, newest first; one broken workflow failing hourly is one item.
_FAILED_RUNS_LIMIT = 20


async def failed_run_candidates(user_id: str, since: datetime) -> list[BriefCandidate]:
    """Return one candidate per workflow whose runs failed since, naming its latest error."""
    briefing_workflows = await workflow_repository.find_system_workflows(
        user_id, BRIEFING_RHYTHM_WORKFLOW_KEYS
    )
    failed = await workflow_executions_repository.list_since(
        user_id,
        since,
        exclude_workflow_ids=[w.id for w in briefing_workflows],
        limit=_FAILED_RUNS_LIMIT,
        status="failed",
    )
    latest = {run.workflow_id: run for run in reversed(failed)}
    if not latest:
        return []
    titles = {
        w.id: w.title for w in await workflow_repository.find_by_ids_for_user(list(latest), user_id)
    }
    runs = sorted(latest.values(), key=lambda run: run.started_at, reverse=True)
    return [
        BriefCandidate(
            source=GAIA_SOURCE,
            app=GAIA_APP_NAME,
            kind=CandidateKind.NEEDS_YOU,
            state="failed",
            title=f"{titles[run.workflow_id]} failed",
            detail=run.error_message,
            action=BriefAction.RETRY,
        )
        for run in runs
        if run.workflow_id in titles
    ]
