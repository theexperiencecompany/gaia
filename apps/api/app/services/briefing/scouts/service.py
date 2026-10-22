"""Run every connected integration's scout for a brief, and learn the ones that need it.

Each scout replays its frozen calls with no model. A replay that fails, a result whose
shape moved, or a changed tool list relearns that scout once; one scout failing is a
typed skipped result and an error on the wide event, never a failed brief.
"""

from datetime import UTC, datetime

from app.constants.user_activity import ActivityStatus
from app.db.repositories.scouts import scouts_repository
from app.models.scout_models import (
    ScoutDocument,
    ScoutOutcome,
    ScoutResult,
    ScoutSkipReason,
    ScoutStatus,
)
from app.models.user_models import UserDocument
from app.services.briefing.scouts.learn import learn_scout
from app.services.briefing.scouts.spend import may_learn, tallied_learn
from app.services.briefing.scouts.tools import (
    ScoutIntegration,
    ScoutTools,
    scout_integrations,
    scout_tools,
)
from app.services.briefing.scouts.watch import FrozenWatch, watch
from app.services.user_activity.status import activity_status_of
from app.services.workflow.playbook.evaluator import PlaybookUser
from app.utils.errors import AppError
from app.utils.timezone import Timezone
from shared.py.wide_events import log


def _playbook_user(user: UserDocument) -> PlaybookUser:
    return PlaybookUser(
        email=user.email or "",
        name=user.name or "",
        timezone=user.timezone or Timezone.utc().value,
    )


async def _learn(
    user: UserDocument,
    integration: ScoutIntegration,
    tools: ScoutTools,
    stale: ScoutDocument | None,
) -> ScoutResult:
    """Learn the scout once; a learn whose calls would not freeze drops the stale scout."""
    if not await may_learn(user.id):
        return ScoutResult(
            integration_id=integration.integration_id,
            outcome=ScoutOutcome.SKIPPED,
            skip_reason=ScoutSkipReason.BUDGET,
        )
    async with tallied_learn(user.id):
        learned = await learn_scout(_playbook_user(user), user.id, integration, tools)
    if learned.scout is not None:
        await scouts_repository.replace(learned.scout)
    elif stale is not None:
        await scouts_repository.delete_for(user.id, integration.integration_id)
    nothing = learned.scout is not None and learned.scout.status is ScoutStatus.NOTHING_TO_WATCH
    return ScoutResult(
        integration_id=integration.integration_id,
        outcome=ScoutOutcome.NOTHING_TO_WATCH if nothing else ScoutOutcome.LEARNED,
        signals=learned.signals,
    )


async def _run_scout(user: UserDocument, integration: ScoutIntegration) -> ScoutResult:
    tools = await scout_tools(user.id, integration.integration_id)
    scout = await scouts_repository.find_for(user.id, integration.integration_id)
    if scout is None or scout.tool_fingerprint != tools.fingerprint:
        return await _learn(user, integration, tools, scout)
    if scout.status is ScoutStatus.NOTHING_TO_WATCH:
        return ScoutResult(
            integration_id=integration.integration_id, outcome=ScoutOutcome.NOTHING_TO_WATCH
        )
    if scout.playbook is None:
        return await _learn(user, integration, tools, scout)
    try:
        signals = await watch(
            _playbook_user(user),
            user.id,
            FrozenWatch(integration, scout.playbook, scout.sources),
            tools.read_only,
            datetime.now(UTC),
        )
    except AppError as exc:
        log.warning(
            "briefing.scout_relearn",
            integration_id=integration.integration_id,
            reason=str(exc),
            error_type=type(exc).__name__,
        )
        return await _learn(user, integration, tools, scout)
    return ScoutResult(
        integration_id=integration.integration_id, outcome=ScoutOutcome.REPLAYED, signals=signals
    )


async def _scout_turn(user: UserDocument, integration: ScoutIntegration) -> ScoutResult:
    """Run one scout; any failure is that scout's skipped result, never the brief's."""
    try:
        return await _run_scout(user, integration)
    except Exception as exc:
        # Broad on purpose: an app being down, a bad report or a timeout must cost the
        # brief this one app's signals only. The error still lands on the wide event.
        log.error(
            "briefing.scout_failed",
            integration_id=integration.integration_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return ScoutResult(
            integration_id=integration.integration_id,
            outcome=ScoutOutcome.SKIPPED,
            skip_reason=ScoutSkipReason.FAILED,
            error=f"{type(exc).__name__}: {exc}",
        )


async def run_scouts(user: UserDocument) -> list[ScoutResult]:
    """Run the scout of every connected integration the brief does not cover elsewhere."""
    if await activity_status_of(user.id) is ActivityStatus.DORMANT:
        log.set_ns("scouts", skipped="dormant")
        return []
    results = [
        await _scout_turn(user, integration) for integration in await scout_integrations(user.id)
    ]
    log.set_ns(
        "scouts",
        outcomes={r.integration_id: r.outcome.value for r in results},
        signal_count=sum(len(r.signals) for r in results),
    )
    return results


async def learn_connected_integration(
    user: UserDocument, integration_id: str
) -> ScoutResult | None:
    """Scout an integration the user just connected; None when it is not one a scout watches."""
    integration = next(
        (i for i in await scout_integrations(user.id) if i.integration_id == integration_id),
        None,
    )
    if integration is None:
        return None
    return await _run_scout(user, integration)
