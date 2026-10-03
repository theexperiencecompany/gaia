"""ARQ tasks that maintain per-user E2B sandboxes + JuiceFS metadata.

Currently:
- sweep_idle_sandboxes: hourly. Marks sandboxes whose last_used_at is older
  than the eviction threshold as dead and drops them from the in-process pool
  so the next request creates a fresh one. The underlying E2B sandbox is left
  to E2B's own paused-TTL to reclaim (default 30 days), which keeps the FS
  available if the user comes back inside the window. AGENT_LAB users are
  exempt while the flag is on (their keep-warm refresh keeps last_used_at
  fresh anyway; the exemption covers a missed cron run).
- refresh_lab_sandboxes: every 30 minutes. Re-acquires flagged users'
  sandboxes so the E2B kill timer never lapses, which also re-stages the
  sandbox bridge token after a pause/resume cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.db.repositories.e2b_sandboxes import e2b_sandbox_repository
from app.services.feature_flags import is_agent_lab_enabled
from app.services.sandbox import acquire_sandbox, mark_sandbox_dead
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


async def refresh_lab_sandboxes(_ctx: dict[str, Any]) -> str:
    """Re-acquire flagged users' sandboxes so the E2B kill timer never lapses."""
    user_ids = await e2b_sandbox_repository.find_live_user_ids()
    refreshed = 0
    for user_id in user_ids:
        try:
            if not await is_agent_lab_enabled(user_id):
                continue
            # Re-acquire refreshes the kill timer (connect carries a full
            # lifetime), touches last_used_at, and re-stages the bridge token.
            async with acquire_sandbox(user_id):
                pass
            refreshed += 1
        except Exception as e:
            log.warning(
                f"{LogTag.SANDBOX} failed to refresh lab sandbox",
                user_id=user_id,
                error_type=type(e).__name__,
                error=str(e),
            )
    log.set(sandbox=SandboxContext(operation="lab_refresh", evicted_count=refreshed))
    log.info(f"{LogTag.SANDBOX} refreshed lab sandboxes", refreshed_count=refreshed)
    return f"Refreshed {refreshed} lab sandboxes"
