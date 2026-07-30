"""ARQ cron task: resolve expired HIL approvals and re-dispatch crashed resumes."""

from typing import Any

from app.services.hil.resolution import sweep_approvals
from shared.py.wide_events import log, wide_task


async def sweep_hil_approvals(ctx: dict[str, Any]) -> str:
    """Every-minute sweep. See ``sweep_approvals`` for the two passes."""
    async with wide_task("sweep_hil_approvals", job_id=ctx.get("job_id")):
        counts = await sweep_approvals()
        log.set(expired_count=counts["expired"], redispatched_count=counts["redispatched"])
        return f"expired={counts['expired']} redispatched={counts['redispatched']}"
