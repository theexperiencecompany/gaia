"""Nightly sweep that retires expired memories.

``forget_after`` used to be a read-time filter only. Nothing ever wrote the
expiry back, so an expired row stayed in the folder tree, in the free-plan
live count, in the ``/workspace/memory`` projection and in the rendered
agenda — visible everywhere except recall. This task is what makes an expiry
actually happen, and repairs the derived state of the users it touched.
"""

from typing import Any

from app.constants.log_tags import LogTag
from app.memory import chroma_store, pg_store
from app.memory.cap_counter import set_cached_live_count
from app.memory.consolidation import render_agenda_document
from app.memory.context import invalidate_user_memory_caches
from shared.py.wide_events import log


async def sweep_expired_memories(_ctx: dict[str, Any]) -> str:
    """Forget every past-due memory, then repair each affected user's views."""
    # Legacy agenda rows predate the task shelf-life and carry no expiry, so
    # they'd sit in the always-injected agenda forever. Stamped before the
    # sweep so an already-overdue one is retired in this same run.
    backfilled = await pg_store.backfill_agenda_expiry()
    if backfilled:
        log.info(f"{LogTag.WORKER} legacy agenda rows stamped", backfilled=backfilled)
    swept = await pg_store.sweep_expired_memories()
    # Postgres flipping is_forgotten is not enough: the vector keeps
    # is_latest=True/is_forgotten=False in Chroma, so reconciliation would
    # still match the retired row and drop identical restatements as
    # DUPLICATE. Retire the same rows' Chroma flags in the same run.
    for row in swept:
        await chroma_store.set_memory_flags(row.memory_id, is_latest=False, is_forgotten=True)
    affected = sorted({row.user_id for row in swept})

    for user_id in affected:
        # The counter is optimistic and only ever adjusted at mutation sites,
        # so a sweep it did not see leaves it over-counting until its TTL.
        await set_cached_live_count(user_id, await pg_store.count_live_memories(user_id))
        # agenda.md is rendered from rows: an expired item stays on the page
        # (and in every prompt) until something re-renders it.
        await render_agenda_document(user_id)
        await invalidate_user_memory_caches(user_id)

    summary = {"memories_expired": len(swept), "users_repaired": len(affected)}
    log.set(memory_sweep=summary)
    log.info(f"{LogTag.WORKER} expired memories swept", **summary)
    return f"expired={len(swept)} users={len(affected)}"
