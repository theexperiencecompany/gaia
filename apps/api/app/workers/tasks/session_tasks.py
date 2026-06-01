"""ARQ tasks that garbage-collect inactive on-disk chat sessions.

`prune_inactive_sessions`: daily. Scans the host JuiceFS mount for
`sessions/{conv}/.meta.json` whose `last_active` is older than
`SESSION_RETENTION_DAYS` and recursively deletes the session dir. This is the
backstop for the best-effort cleanup in `conversation_service.delete_conversation`
(a session whose conversation was deleted while JuiceFS was unreachable, or a
conversation that was abandoned without an explicit delete).
"""

from __future__ import annotations

from typing import Any

from app.config.settings import settings
from app.services.storage import (
    delete_session_dir,
    flush_fs_metrics,
    list_stale_sessions,
)
from shared.py.wide_events import log, wide_task


async def prune_inactive_sessions(ctx: dict[str, Any]) -> str:
    """Delete session dirs inactive past SESSION_RETENTION_DAYS."""
    async with wide_task("prune_inactive_sessions"):
        cutoff_days = settings.SESSION_RETENTION_DAYS
        limit = settings.SESSION_PRUNE_BATCH_LIMIT
        stale = await list_stale_sessions(cutoff_days, limit=limit)
        pruned = 0
        for user_id, conv_id in stale:
            try:
                await delete_session_dir(user_id, conv_id)
                pruned += 1
            except Exception as e:
                log.warning(
                    "[prune] failed",
                    user_id=user_id,
                    conv=conv_id,
                    error=str(e),
                )
        fs_metrics = flush_fs_metrics()
        log.set(
            stale_count=len(stale),
            pruned=pruned,
            **({"fs": fs_metrics} if fs_metrics else {}),
        )
        return f"pruned {pruned}/{len(stale)} sessions (cutoff={cutoff_days}d)"
