"""Run every connected integration's scout for a brief, and learn the ones that need it.

Scouts are a Pro feature. Each scout replays its frozen calls with no model; every row
they return is then judged, across all apps in one call, by the criteria each scout
learned. A replay that fails, a result whose shape moved, or a changed tool list
relearns that scout once; a learn that fails waits out a backoff. One scout failing is a
typed skipped result and an error on the wide event, never a failed brief.
"""

from datetime import UTC, datetime

from app.constants.scouts import SCOUT_RELEARN_BACKOFF
from app.constants.user_activity import ActivityStatus
from app.db.repositories.scouts import scouts_repository
from app.models.payment_models import PlanType
from app.models.scout_models import (
    RememberedSignal,
    ScoutDocument,
    ScoutOutcome,
    ScoutResult,
    ScoutSkipReason,
    ScoutStatus,
)
from app.models.user_models import UserDocument
from app.services.briefing.scouts.judge import judge_replayed
from app.services.briefing.scouts.learn import learn_scout
from app.services.briefing.scouts.memory import remember
from app.services.briefing.scouts.spend import may_learn
from app.services.briefing.scouts.tools import (
    ScoutIntegration,
    ScoutTools,
    scout_integrations,
    scout_tools,
)
from app.services.briefing.scouts.watch import FrozenWatch, watch
from app.services.mcp.mcp_client import MCPIntegrationNotFoundError
from app.services.payments.payment_service import payment_service
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


def _skipped(integration: ScoutIntegration, reason: ScoutSkipReason) -> ScoutResult:
    return ScoutResult(
        integration_id=integration.integration_id,
        outcome=ScoutOutcome.SKIPPED,
        skip_reason=reason,
    )


async def _record_failed_learn(
    user_id: str, tools: ScoutTools, stale: ScoutDocument | None, now: datetime
) -> None:
    """Store a learn that froze nothing as a scout waiting out its backoff before the next."""
    streak = (
        stale.failed_learns
        if stale is not None
        and stale.status is ScoutStatus.LEARN_FAILED
        and stale.tool_fingerprint == tools.fingerprint
        else 0
    ) + 1
    wait = SCOUT_RELEARN_BACKOFF[min(streak, len(SCOUT_RELEARN_BACKOFF)) - 1]
    await scouts_repository.replace(
        ScoutDocument(
            user_id=user_id,
            integration_id=tools.integration_id,
            status=ScoutStatus.LEARN_FAILED,
            tool_fingerprint=tools.fingerprint,
            learned_at=now,
            failed_learns=streak,
            next_learn_at=now + wait,
        )
    )


async def _learn(
    user: UserDocument,
    integration: ScoutIntegration,
    tools: ScoutTools,
    stale: ScoutDocument | None,
) -> ScoutResult:
    """Learn the scout once; a learn that freezes nothing, or raises, starts or extends a backoff."""
    if not await may_learn(user.id):
        return _skipped(integration, ScoutSkipReason.BUDGET)
    now = datetime.now(UTC)
    try:
        learned = await learn_scout(_playbook_user(user), user.id, integration, tools)
    except Exception:
        await _record_failed_learn(user.id, tools, stale, now)
        raise
    if learned.scout is None:
        await _record_failed_learn(user.id, tools, stale, now)
    else:
        await scouts_repository.replace(learned.scout)
    nothing = learned.scout is not None and learned.scout.status is ScoutStatus.NOTHING_TO_WATCH
    return ScoutResult(
        integration_id=integration.integration_id,
        outcome=ScoutOutcome.NOTHING_TO_WATCH if nothing else ScoutOutcome.LEARNED,
        signals=learned.signals,
    )


async def _replay(
    user: UserDocument, integration: ScoutIntegration, tools: ScoutTools, scout: ScoutDocument
) -> ScoutResult:
    """Replay a watching scout; a failed replay or a moved result shape relearns it once.

    A scout frozen with no criteria (before they existed) relearns: its rows cannot be judged.
    """
    if scout.playbook is None or not scout.criteria.strip():
        return await _learn(user, integration, tools, scout)
    try:
        signals = await watch(
            _playbook_user(user),
            user.id,
            FrozenWatch(integration, scout.playbook, scout.sources),
            tools.read_only,
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
        integration_id=integration.integration_id,
        outcome=ScoutOutcome.REPLAYED,
        signals=signals,
        criteria=scout.criteria,
    )


async def _run_scout(user: UserDocument, integration: ScoutIntegration) -> ScoutResult:
    try:
        tools = await scout_tools(user.id, integration.integration_id)
    except MCPIntegrationNotFoundError:
        # A stale connection record: nothing to scout until the integration changes.
        log.info("briefing.scout_unknown_integration", integration_id=integration.integration_id)
        return _skipped(integration, ScoutSkipReason.UNKNOWN_INTEGRATION)
    if not tools.read_only:
        return _skipped(integration, ScoutSkipReason.NO_READ_ONLY_TOOLS)
    scout = await scouts_repository.find_for(user.id, integration.integration_id)
    if scout is None or scout.tool_fingerprint != tools.fingerprint:
        return await _learn(user, integration, tools, scout)
    if scout.status is ScoutStatus.NOTHING_TO_WATCH:
        return ScoutResult(
            integration_id=integration.integration_id, outcome=ScoutOutcome.NOTHING_TO_WATCH
        )
    if scout.status is ScoutStatus.LEARN_FAILED:
        if scout.next_learn_at is not None and datetime.now(UTC) < scout.next_learn_at:
            return _skipped(integration, ScoutSkipReason.BACKOFF)
        return await _learn(user, integration, tools, scout)
    return await _replay(user, integration, tools, scout)


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


async def _scouts_skipped(user_id: str) -> str | None:
    """Why this user's brief runs no scouts at all, or None when it does."""
    if await payment_service.get_cached_plan_type(user_id) is PlanType.FREE:
        return "free_plan"
    if await activity_status_of(user_id) is ActivityStatus.DORMANT:
        return "dormant"
    return None


async def run_scouts(user: UserDocument) -> list[ScoutResult]:
    """Run the scout of every connected integration the brief does not cover elsewhere."""
    skipped = await _scouts_skipped(user.id)
    if skipped is not None:
        log.set_ns("scouts", skipped=skipped)
        return []
    results = [
        await _scout_turn(user, integration) for integration in await scout_integrations(user.id)
    ]
    log.set_ns(
        "scouts",
        outcomes={r.integration_id: r.outcome.value for r in results},
        skip_reasons={r.integration_id: r.skip_reason.value for r in results if r.skip_reason},
        signal_count=sum(len(r.signals) for r in results),
    )
    return results


async def scout_signals(user: UserDocument, now: datetime) -> list[RememberedSignal]:
    """Run the scouts, pair their signals with memory, and judge every replayed one.

    A judge that fails costs the brief today's replayed signals, never the brief.
    """
    results = await run_scouts(user)
    remembered = await remember(user.id, [s for r in results for s in r.signals], now)
    try:
        judged = await judge_replayed(
            user.id, results, remembered, now, user.timezone or Timezone.utc().value
        )
    except Exception as exc:
        # Broad on purpose, as in _scout_turn: the judge is one model call over app items.
        log.error("briefing.signal_judge_failed", error=str(exc), error_type=type(exc).__name__)
        replayed = {r.integration_id for r in results if r.outcome is ScoutOutcome.REPLAYED}
        return [item for item in remembered if item.signal.integration_id not in replayed]
    log.set_ns("scouts", judged_out=len(remembered) - len(judged))
    return judged


async def learn_connected_integration(
    user: UserDocument, integration_id: str
) -> ScoutResult | None:
    """Scout an integration the user just connected; None when no scout watches it."""
    if await _scouts_skipped(user.id) is not None:
        return None
    integration = next(
        (i for i in await scout_integrations(user.id) if i.integration_id == integration_id),
        None,
    )
    if integration is None:
        return None
    return await _run_scout(user, integration)
