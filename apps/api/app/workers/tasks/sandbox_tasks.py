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
from app.db.mongodb.collections import e2b_sandboxes_collection
from app.services.sandbox import mark_sandbox_dead
from shared.py.wide_events import log, wide_task


async def sweep_idle_sandboxes(ctx: dict[str, Any]) -> str:
    """Evict sandboxes whose last_used_at is older than the eviction window."""
    async with wide_task("sweep_idle_sandboxes"):
        cutoff = datetime.now(UTC) - timedelta(days=settings.E2B_SANDBOX_EVICT_DAYS)
        cursor = e2b_sandboxes_collection.find(
            {
                "last_used_at": {"$lt": cutoff},
                "state": {"$ne": "dead"},
            },
            projection={"user_id": 1},
        )
        evicted = 0
        async for doc in cursor:
            user_id = doc.get("user_id")
            if not user_id:
                continue
            try:
                await mark_sandbox_dead(user_id)
                evicted += 1
            except Exception as e:
                log.warning(f"Failed to mark sandbox dead for {user_id}: {e}")
        log.set(evicted=evicted)
        return f"Evicted {evicted} idle sandboxes (cutoff={cutoff.isoformat()})"
