"""Run every connected integration's scout for a brief, and learn the ones that need it.

Scouts are a Pro feature. Each scout replays its frozen calls with no model; every row
they return is then judged with the rest of the brief's candidates by the criteria each
scout learned. A result whose shape moved or a changed tool list relearns that scout once;
an app that does not answer keeps its scout until it has failed several briefs in a row. A
learn that fails waits out a backoff and never discards a working scout. One scout
failing is a typed skipped result and an error on the wide event, never a failed brief.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from app.constants.integrations import IntegrationStatus
from app.constants.scouts import (
    SCOUT_CONCURRENCY,
    SCOUT_RELEARN_BACKOFF,
    SCOUT_REPLAY_FAILURES_BEFORE_RELEARN,
    SCOUT_TIME_CAP,
    SCOUT_TURN_TIMEOUT,
    SCOUTS_REFRESHED_KEY,
    SCOUTS_REFRESHED_TTL,
)
from app.constants.user_activity import ActivityStatus
from app.db.redis import AsyncRedisCommands
from app.db.repositories.scouts import scouts_repository
from app.decorators.entitlements import is_paid
from app.models.scout_models import (
    RefreshedScouts,
    RememberedSignal,
    ScoutDocument,
    ScoutOutcome,
    ScoutResult,
    ScoutSkipReason,
    ScoutStatus,
)
from app.models.user_models import UserDocument
from app.services.briefing.scouts.learn import learn_scout
from app.services.briefing.scouts.memory import remember
from app.services.briefing.scouts.metrics import record_scout_turn
from app.services.briefing.scouts.redis_client import scouts_redis
from app.services.briefing.scouts.spend import reserve_learn
from app.services.briefing.scouts.tools import (
    ScoutIntegration,
    ScoutTools,
    scout_integrations,
    scout_tools,
)
from app.services.briefing.scouts.watch import FrozenWatch, ScoutSourceFailed, watch
from app.services.mcp.mcp_errors import MCP_SIGNED_OUT_ERRORS, MCPIntegrationNotFoundError
from app.services.user_activity.status import activity_status_of
from app.services.workflow.playbook.evaluator import PlaceholderError, PlaybookUser
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
        app=integration.name,
        outcome=ScoutOutcome.SKIPPED,
        skip_reason=reason,
    )


async def _record_failed_learn(
    user_id: str, tools: ScoutTools, stale: ScoutDocument | None, now: datetime
) -> None:
    """Back off the next learn; a working scout keeps its frozen calls, any other waits failed."""
    same = stale if stale is not None and stale.tool_fingerprint == tools.fingerprint else None
    streak = (same.failed_learns if same is not None else 0) + 1
    wait = SCOUT_RELEARN_BACKOFF[min(streak, len(SCOUT_RELEARN_BACKOFF)) - 1]
    if same is not None and same.status is ScoutStatus.WATCHING:
        await scouts_repository.replace(
            same.model_copy(update={"failed_learns": streak, "next_learn_at": now + wait})
        )
        return
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
    stale: ScoutDocument | None = None,
) -> ScoutResult:
    """Learn the scout once; a learn that freezes nothing, or raises, starts or extends a backoff."""
    spend = await reserve_learn(user.id)
    if spend is None:
        return _skipped(integration, ScoutSkipReason.BUDGET)
    now = datetime.now(UTC)
    try:
        learned = await learn_scout(_playbook_user(user), user.id, integration, tools, spend)
    except Exception:
        await _record_failed_learn(user.id, tools, stale, now)
        raise
    finally:
        await spend.release()
    if learned.scout is None:
        await _record_failed_learn(user.id, tools, stale, now)
    else:
        await scouts_repository.replace(learned.scout)
    nothing = learned.scout is not None and learned.scout.status is ScoutStatus.NOTHING_TO_WATCH
    return ScoutResult(
        integration_id=integration.integration_id,
        app=integration.name,
        outcome=ScoutOutcome.NOTHING_TO_WATCH if nothing else ScoutOutcome.LEARNED,
        signals=learned.signals,
        criteria=learned.scout.criteria if learned.scout is not None else None,
    )


async def _relearn(
    user: UserDocument, integration: ScoutIntegration, tools: ScoutTools, scout: ScoutDocument
) -> ScoutResult:
    """Learn a stored scout again, unless its last failed learn is still backing off."""
    if scout.next_learn_at is not None and datetime.now(UTC) < scout.next_learn_at:
        return _skipped(integration, ScoutSkipReason.BACKOFF)
    return await _learn(user, integration, tools, scout)


async def _source_failed(
    user: UserDocument,
    integration: ScoutIntegration,
    tools: ScoutTools,
    scout: ScoutDocument,
    exc: ScoutSourceFailed,
) -> ScoutResult:
    """Keep the scout through an app that did not answer; relearn once it has failed for briefs."""
    scout = scout.model_copy(update={"failed_replays": scout.failed_replays + 1})
    await scouts_repository.replace(scout)
    log.warning(
        "briefing.scout_source_failed",
        integration_id=integration.integration_id,
        failed_replays=scout.failed_replays,
        reason=exc.why,
    )
    if scout.failed_replays >= SCOUT_REPLAY_FAILURES_BEFORE_RELEARN:
        return await _relearn(user, integration, tools, scout)
    return ScoutResult(
        integration_id=integration.integration_id,
        app=integration.name,
        outcome=ScoutOutcome.SKIPPED,
        skip_reason=ScoutSkipReason.SOURCE_FAILED,
        error=exc.why,
    )


async def _replay(
    user: UserDocument, integration: ScoutIntegration, tools: ScoutTools, scout: ScoutDocument
) -> ScoutResult:
    """Replay a watching scout; a moved result shape relearns it, an app that fails keeps it."""
    if scout.playbook is None:
        raise ValueError("only a watching scout replays, and it always holds its playbook")
    try:
        signals = await watch(
            _playbook_user(user),
            user.id,
            FrozenWatch(integration, scout.playbook, scout.sources),
            tools.read_only,
        )
    except ScoutSourceFailed as exc:
        return await _source_failed(user, integration, tools, scout, exc)
    except PlaceholderError as exc:
        log.warning(
            "briefing.scout_relearn",
            integration_id=integration.integration_id,
            reason=str(exc),
            error_type=type(exc).__name__,
        )
        return await _relearn(user, integration, tools, scout)
    cleared = scout.model_copy(
        update={"failed_replays": 0, "failed_learns": 0, "next_learn_at": None}
    )
    if cleared != scout:
        await scouts_repository.replace(cleared)
    return ScoutResult(
        integration_id=integration.integration_id,
        app=integration.name,
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
    result = await _scouted(user, integration, tools)
    return result.model_copy(update={"can_write": tools.total > len(tools.read_only)})


async def _scouted(
    user: UserDocument, integration: ScoutIntegration, tools: ScoutTools
) -> ScoutResult:
    """Learn, relearn or replay the integration's scout, by what it last froze."""
    scout = await scouts_repository.find_for(user.id, integration.integration_id)
    if scout is None or scout.tool_fingerprint != tools.fingerprint:
        return await _learn(user, integration, tools)
    if scout.status is ScoutStatus.NOTHING_TO_WATCH:
        return ScoutResult(
            integration_id=integration.integration_id,
            app=integration.name,
            outcome=ScoutOutcome.NOTHING_TO_WATCH,
        )
    if scout.status is ScoutStatus.LEARN_FAILED:
        return await _relearn(user, integration, tools, scout)
    return await _replay(user, integration, tools, scout)


async def _scout_turn(
    user: UserDocument, integration: ScoutIntegration, cap_at: float
) -> ScoutResult:
    """Run one scout until its own timeout or the brief's cap_at (loop time), whichever is first.

    Any failure is that scout's skipped result, never the brief's. A dead sign-in is its own
    reason, so the brief can ask for the reconnect that fixes it; a scout the cap stops is too.
    """
    if integration.status == IntegrationStatus.EXPIRED:
        return _skipped(integration, ScoutSkipReason.SIGNED_OUT)
    now = asyncio.get_running_loop().time()
    # At cap_at == now the deadline below expires at once: the same skip either way.
    if cap_at <= now:  # pragma: no mutate -- equivalent at equality, see above
        return _skipped(integration, ScoutSkipReason.OUT_OF_TIME)
    turn_ends = now + SCOUT_TURN_TIMEOUT.total_seconds()
    deadline = asyncio.timeout_at(min(turn_ends, cap_at))
    try:
        async with deadline:
            return await _run_scout(user, integration)
    except MCP_SIGNED_OUT_ERRORS:
        return _skipped(integration, ScoutSkipReason.SIGNED_OUT)
    except Exception as exc:
        # At cap_at == turn_ends both deadlines are one instant; either reading is right.
        if deadline.expired() and cap_at < turn_ends:  # pragma: no mutate -- equivalent at equality
            log.warning("briefing.scout_out_of_time", integration_id=integration.integration_id)
            return _skipped(integration, ScoutSkipReason.OUT_OF_TIME)
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
            app=integration.name,
            outcome=ScoutOutcome.SKIPPED,
            skip_reason=ScoutSkipReason.FAILED,
            error=f"{type(exc).__name__}: {exc}",
        )


async def _scouts_skipped(user_id: str) -> ScoutSkipReason | None:
    """Why this user's brief runs no scouts at all, or None when it does."""
    if not await is_paid(user_id):
        return ScoutSkipReason.FREE_PLAN
    if await activity_status_of(user_id) is ActivityStatus.DORMANT:
        return ScoutSkipReason.DORMANT
    return None


async def run_scouts(user: UserDocument) -> list[ScoutResult]:
    """Run the scout of every connected integration the brief does not cover elsewhere, a few at once."""
    skipped = await _scouts_skipped(user.id)
    if skipped is not None:
        log.set_ns("scouts", skipped=skipped.value)
        return []
    slots = asyncio.Semaphore(SCOUT_CONCURRENCY)
    cap_at = asyncio.get_running_loop().time() + SCOUT_TIME_CAP.total_seconds()

    async def turn(integration: ScoutIntegration) -> ScoutResult:
        # The turn's own timeout starts once it holds a slot; the brief's cap runs throughout.
        async with slots:
            return await _scout_turn(user, integration, cap_at)

    results = list(await asyncio.gather(*(turn(i) for i in await scout_integrations(user.id))))
    for result in results:
        record_scout_turn(result)
    log.set_ns(
        "scouts",
        outcomes={r.integration_id: r.outcome.value for r in results},
        skip_reasons={r.integration_id: r.skip_reason.value for r in results if r.skip_reason},
        signal_count=sum(len(r.signals) for r in results),
    )
    return results


@dataclass(frozen=True)
class ScoutSignals:
    """What the scouts read for one brief: every signal with its memory, and how each app went.

    criteria maps an app's name to how its scout tells what needs the user, for the rows
    its replay returned; the brief's selection judge reads them by it.
    """

    remembered: list[RememberedSignal]
    criteria: dict[str, str]
    results: list[ScoutResult]


def _refreshed() -> AsyncRedisCommands:
    return scouts_redis(
        message="refreshed scout results cannot be kept or taken",
        why="Redis is unavailable, so a brief cannot take the results refreshed ahead of it",
        fix="restore Redis; the brief runs its scouts itself meanwhile",
    )


async def refresh_scouts(user: UserDocument) -> None:
    """Run the user's scouts ahead of their brief and keep the results for it to take."""
    fetched_at = datetime.now(UTC)
    results = await run_scouts(user)
    await _refreshed().setex(
        SCOUTS_REFRESHED_KEY.format(user_id=user.id),
        int(SCOUTS_REFRESHED_TTL.total_seconds()),
        RefreshedScouts(results=results, fetched_at=fetched_at).model_dump_json(),
    )


async def scout_signals(user: UserDocument, now: datetime) -> ScoutSignals:
    """Take the scouts' refreshed results, or run them now, and pair every signal with its memory.

    Refreshed results are taken once: a second brief the same hour runs the scouts again.
    """
    kept = await _refreshed().getdel(SCOUTS_REFRESHED_KEY.format(user_id=user.id))
    log.set_ns("scouts", refreshed_ahead=kept is not None)
    refreshed = RefreshedScouts.model_validate_json(kept) if kept is not None else None
    results = refreshed.results if refreshed is not None else await run_scouts(user)
    seen = refreshed.fetched_at if refreshed is not None else now
    remembered = await remember(user.id, [s for r in results for s in r.signals], seen)
    criteria = {r.app: r.criteria.line() for r in results if r.criteria is not None}
    return ScoutSignals(remembered=remembered, criteria=criteria, results=results)


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
