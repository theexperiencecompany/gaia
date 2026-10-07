"""ARQ tasks that maintain per-user E2B sandboxes + JuiceFS metadata.

Currently:
- sweep_idle_sandboxes: hourly. Marks sandboxes whose last_used_at is older
  than the eviction threshold as dead and drops them from the in-process pool
  so the next request creates a fresh one. The underlying E2B sandbox is left
  to E2B's own paused-TTL to reclaim (default 30 days), which keeps the FS
  available if the user comes back inside the window. AGENT_LAB users are
  exempt while the flag is on (their keep-warm refresh keeps last_used_at
  fresh anyway; the exemption covers a missed cron run).
- refresh_lab_sandboxes: every 10 minutes, over agent-lab sandboxes. A live
  run's sandbox is saved and, near E2B's lifetime cap, renewed with a pause
  and resume; any other, including a run past SANDBOX_LAB_MAX_RUN_SECONDS
  (one notification per cap window), is paused once idle.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, cast

from arq.connections import ArqRedis

from app.config.settings import settings
from app.constants.execute import (
    SANDBOX_LAB_KEEP_WARM_CONCURRENCY,
    SANDBOX_LAB_MAX_RUN_SECONDS,
    SANDBOX_LAB_RENEW_WHEN_SECONDS_LEFT,
)
from app.constants.log_tags import LogTag
from app.db.repositories.e2b_sandboxes import e2b_sandbox_repository
from app.db.repositories.todos import todo_repository
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.models.todo_models import TodoDocument
from app.services.agent_lab.agents_saves import save_agents_home
from app.services.agent_lab.lab_runs import SANDBOX_RUN_TRIGGER, run_cap_status
from app.services.agent_lab.sandbox_events import SandboxEventKind, report_sandbox_event
from app.services.feature_flags import is_agent_lab_enabled
from app.services.notification_service import notification_service
from app.services.sandbox import (
    acquire_sandbox,
    mark_sandbox_dead,
    pause_idle_sandbox,
    renew_sandbox,
)
from shared.py.wide_events import SandboxContext, log


async def sweep_idle_sandboxes(_ctx: dict[str, Any]) -> str:
    """Evict sandboxes whose last_used_at is older than the eviction window."""
    cutoff = datetime.now(UTC) - timedelta(days=settings.E2B_SANDBOX_EVICT_DAYS)
    idle_user_ids = await e2b_sandbox_repository.find_idle_user_ids(cutoff=cutoff)
    evicted = 0
    skipped_lab = 0
    for user_id in idle_user_ids:
        try:
            if await is_agent_lab_enabled(user_id):
                skipped_lab += 1
                continue
            await mark_sandbox_dead(user_id)
            evicted += 1
        except Exception as e:
            log.warning(
                f"{LogTag.SANDBOX} failed to mark sandbox dead",
                user_id=user_id,
                error_type=type(e).__name__,
                error=str(e),
            )
    log.set(sandbox=SandboxContext(operation="sweep", evicted_count=evicted))
    log.info(
        f"{LogTag.SANDBOX} sweep evicted idle sandboxes",
        evicted_count=evicted,
        skipped_lab_count=skipped_lab,
    )
    return f"Evicted {evicted} idle sandboxes (cutoff={cutoff.isoformat()})"


class LabTickOutcome(StrEnum):
    """What one keep-warm tick did with one user's agent-lab sandbox."""

    KEPT = "kept"
    PAUSED = "paused"
    LEFT = "left"
    FAILED = "failed"


async def refresh_lab_sandboxes(ctx: dict[str, Any]) -> str:
    """Keep agent-lab sandboxes with a live run warm and saved; pause the rest once idle.

    Candidates come from the template recorded in Mongo, so regular users cost
    no flag evaluation; users are handled concurrently, so one slow save never
    pushes another past its renew margin.
    """
    template_id = settings.E2B_AGENT_LAB_TEMPLATE_ID
    if not template_id:
        return "Agent-lab template not configured; nothing to keep warm"
    user_ids = await e2b_sandbox_repository.find_live_user_ids_on_template(template_id)
    slots = asyncio.Semaphore(SANDBOX_LAB_KEEP_WARM_CONCURRENCY)

    async def tick(user_id: str) -> LabTickOutcome:
        async with slots:
            return await _tick_lab_sandbox(ctx, user_id)

    outcomes = Counter(await asyncio.gather(*(tick(user_id) for user_id in user_ids)))
    log.set(
        sandbox=SandboxContext(
            operation="lab_refresh", evicted_count=outcomes[LabTickOutcome.PAUSED]
        )
    )
    log.info(
        f"{LogTag.SANDBOX} refreshed lab sandboxes",
        **{f"{outcome.value}_count": outcomes[outcome] for outcome in LabTickOutcome},
    )
    return (
        f"Kept {outcomes[LabTickOutcome.KEPT]} lab sandboxes warm, "
        f"paused {outcomes[LabTickOutcome.PAUSED]} idle, "
        f"{outcomes[LabTickOutcome.FAILED]} failed"
    )


async def _tick_lab_sandbox(ctx: dict[str, Any], user_id: str) -> LabTickOutcome:
    """Keep a live run's sandbox warm; otherwise pause it once idle. A failure only logs."""
    try:
        status = run_cap_status(await _lab_run_todos(user_id))
        if status.capped_todo_ids:
            await _notify_lab_cap_hit(ctx, user_id, status.capped_todo_ids)
        if status.live and await is_agent_lab_enabled(user_id):
            await _keep_lab_sandbox(user_id)
            return LabTickOutcome.KEPT
        return LabTickOutcome.PAUSED if await pause_idle_sandbox(user_id) else LabTickOutcome.LEFT
    except Exception as e:
        log.warning(
            f"{LogTag.SANDBOX} failed to refresh lab sandbox",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return LabTickOutcome.FAILED


async def _keep_lab_sandbox(user_id: str) -> None:
    """Save the agents' home, then renew the sandbox when E2B's lifetime cap is near."""
    async with acquire_sandbox(user_id) as sbx:
        info = await sbx.get_info()
        seconds_left = (info.end_at - datetime.now(UTC)).total_seconds()
        await save_agents_home(user_id, sbx)
    if seconds_left > SANDBOX_LAB_RENEW_WHEN_SECONDS_LEFT:
        return
    await renew_sandbox(user_id)
    await report_sandbox_event(
        user_id,
        SandboxEventKind.RENEWED,
        f"paused and resumed to restart its lifetime ({int(seconds_left // 60)} min were left); "
        "running agents carried on",
    )


def _lab_cap_notified_key(user_id: str) -> str:
    """Redis key throttling the cap-hit notification to one per cap window."""
    return f"lab:cap_notified:{user_id}"


async def _lab_run_todos(user_id: str) -> list[TodoDocument]:
    """Open todos subscribed to at least one sandbox run."""
    return await todo_repository.find_active_by_user_and_trigger(user_id, SANDBOX_RUN_TRIGGER)


async def _notify_lab_cap_hit(ctx: dict[str, Any], user_id: str, todo_ids: list[str]) -> None:
    """One in-app notification per cap window that keep-warm stopped; delivery failure never costs the tick."""
    pool = cast(ArqRedis | None, ctx.get("redis"))
    if pool is not None:
        try:
            if await pool.exists(_lab_cap_notified_key(user_id)):
                return
        except Exception as e:
            log.warning(
                f"{LogTag.SANDBOX} lab cap dedup check failed; notifying anyway",
                user_id=user_id,
                error_type=type(e).__name__,
                error=str(e),
            )
    cap_hours = SANDBOX_LAB_MAX_RUN_SECONDS // 3600
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                type=NotificationType.WARNING,
                content=NotificationContent(
                    title=f"Agent lab run hit the {cap_hours}-hour cap",
                    body=(
                        f"GAIA stopped keeping its sandbox warm after {cap_hours} hours, "
                        "so the sandbox will pause when idle. Start a fresh run to continue."
                    ),
                ),
                metadata={
                    "cap_seconds": SANDBOX_LAB_MAX_RUN_SECONDS,
                    "todo_ids": todo_ids,
                },
            )
        )
    except Exception as notify_exc:
        log.warning(
            f"{LogTag.SANDBOX} lab cap notification failed",
            user_id=user_id,
            error_type=type(notify_exc).__name__,
            error=str(notify_exc),
        )
        return
    if pool is not None:
        try:
            await pool.set(_lab_cap_notified_key(user_id), "1", ex=SANDBOX_LAB_MAX_RUN_SECONDS)
        except Exception as e:
            log.warning(
                f"{LogTag.SANDBOX} lab cap dedup stamp failed",
                user_id=user_id,
                error_type=type(e).__name__,
                error=str(e),
            )
