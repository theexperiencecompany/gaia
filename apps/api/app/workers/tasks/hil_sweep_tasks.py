"""ARQ cron task: resolve expired HIL approvals and re-dispatch crashed resumes."""

from typing import Any

from app.services.hil.resolution import sweep_approvals


async def sweep_hil_approvals(ctx: dict[str, Any]) -> str:
    """Every-minute sweep. See ``sweep_approvals`` for the two passes."""
    counts = await sweep_approvals()
    return f"expired={counts['expired']} redispatched={counts['redispatched']}"
