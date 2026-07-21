"""ARQ tasks that maintain per-user E2B sandboxes + JuiceFS metadata.

Currently:
- `sweep_idle_sandboxes`: hourly. Marks sandboxes whose `last_used_at` is older
  than the eviction threshold as dead and drops them from the in-process pool
  so the next request creates a fresh one. The underlying E2B sandbox is left
  to E2B's own paused-TTL to reclaim (default 30 days), which keeps the FS
  available if the user comes back inside the window.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.db.repositories.e2b_sandboxes import e2b_sandbox_repository
from app.services.sandbox import mark_sandbox_dead
from shared.py.wide_events import SandboxContext, log, wide_task


async def sweep_idle_sandboxes(_ctx: dict[str, Any]) -> str:
    """Evict sandboxes whose last_used_at is older than the eviction window."""
    async with wide_task("sweep_idle_sandboxes"):
        cutoff = datetime.now(UTC) - timedelta(days=settings.E2B_SANDBOX_EVICT_DAYS)
        idle_user_ids = await e2b_sandbox_repository.find_idle_user_ids(cutoff=cutoff)
        evicted = 0
        for user_id in idle_user_ids:
            try:
                await mark_sandbox_dead(user_id)
                evicted += 1
            except Exception as e:
                log.warning(f"{LogTag.SANDBOX} failed to mark dead user={user_id}: {e}")
        log.set(sandbox=SandboxContext(operation="sweep", evicted_count=evicted))
        log.info(f"{LogTag.SANDBOX} sweep evicted {evicted} idle sandboxes")
        return f"Evicted {evicted} idle sandboxes (cutoff={cutoff.isoformat()})"
