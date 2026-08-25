"""Nightly sweep that retires expired memories.

``forget_after`` used to be a read-time filter only. Nothing ever wrote the
expiry back, so an expired row stayed in the folder tree, in the free-plan
live count, in the ``/workspace/memory`` projection and in the rendered
agenda — visible everywhere except recall. This task is what makes an expiry
actually happen, and repairs the derived state of the users it touched.
"""

from typing import Any

from app.constants.log_tags import LogTag
from app.memory import pg_store
from app.memory.cap_counter import set_cached_live_count
from app.memory.consolidation import render_agenda_document
from app.memory.context import invalidate_user_memory_caches
from shared.py.wide_events import log


async def sweep_expired_memories(_ctx: dict[str, Any]) -> str:
    """Forget every past-due memory, then repair each affected user's views."""
    owners = await pg_store.sweep_expired_memories()
    affected = sorted(set(owners))

    for user_id in affected:
        # The counter is optimistic and only ever adjusted at mutation sites,
        # so a sweep it did not see leaves it over-counting until its TTL.
        await set_cached_live_count(user_id, await pg_store.count_live_memories(user_id))
        # agenda.md is rendered from rows: an expired item stays on the page
        # (and in every prompt) until something re-renders it.
        await render_agenda_document(user_id)
        await invalidate_user_memory_caches(user_id)

    summary = {"memories_expired": len(owners), "users_repaired": len(affected)}
    log.set(memory_sweep=summary)
    log.info(f"{LogTag.WORKER} expired memories swept", **summary)
    return f"expired={len(owners)} users={len(affected)}"
