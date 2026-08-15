"""Postgres → VFS glue for ``/workspace/memory/``.

The Postgres side: core documents, the last 30 days of journal episodes,
and live facts grouped by category folder (see ``app.memory.pg_store``).

The VFS side: :mod:`app.memory.projection`.

The shared orchestration (mount check, hash gate, fire-and-forget
scheduler, structured logging) lives in
:mod:`app.services._vfs_scheduler`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.agents.workspace.system_docs import MEMORY_GUIDE_MD
from app.constants.memory import (
    MEMORY_DOC_FILENAMES,
    PROJECTION_JOURNAL_DAYS,
    MemoryDocType,
)
from app.memory import pg_store
from app.memory.projection import (
    FACTS_DIRNAME,
    JOURNAL_DIRNAME,
    MemoryFileProjection,
    materialize_memory,
    memory_marker_path,
    per_doc_signature,
    render_facts_page,
    render_journal_page,
)
from app.services._vfs_scheduler import make_scheduler, run_hashed_sync
from app.services.storage.metrics import FsOps


async def sync_user_memory_fs(user_id: str) -> int:
    """Materialize the user's memory projection to JuiceFS.

    Returns the number of file bodies rewritten. ``0`` means either the
    mount is missing (native dev) or the on-disk catalog signature
    already matched Postgres — both are no-ops from the caller's POV.
    """
    return await run_hashed_sync(
        user_id,
        fs_op=FsOps.SYNC_MEMORY_VFS,
        fetch_fn=_fetch_projections,
        per_doc_sig_fn=per_doc_signature,
        materialize_fn=materialize_memory,
        guide_md=MEMORY_GUIDE_MD,
        catalog_marker_path_fn=memory_marker_path,
        log_name="memory_vfs",
    )


# Fire-and-forget wrapper for the memory write paths (ingestion, document
# rewrites, edits, forgets). See the docstring on :func:`make_scheduler`.
schedule_memory_vfs_sync = make_scheduler(sync_user_memory_fs, log_name="memory_vfs")


async def _fetch_projections(user_id: str) -> list[MemoryFileProjection]:
    """Pull everything the on-disk view shows from Postgres, as flat files."""
    today = datetime.now(UTC).date()
    documents, episodes, memories = await asyncio.gather(
        pg_store.get_documents(user_id),
        pg_store.get_episodes_range(
            user_id, today - timedelta(days=PROJECTION_JOURNAL_DAYS - 1), today
        ),
        pg_store.get_all_live_memories(user_id),
    )

    projections: list[MemoryFileProjection] = []

    for document in documents:
        doc_type = MemoryDocType(document.doc_type)
        projections.append(
            {
                "id": f"doc:{document.doc_type}",
                "path": MEMORY_DOC_FILENAMES[doc_type],
                "content": document.content.rstrip() + "\n",
            }
        )

    for episode in episodes:
        if not episode.entries and not episode.summary:
            continue
        day = episode.date.isoformat()
        projections.append(
            {
                "id": f"journal:{day}",
                "path": f"{JOURNAL_DIRNAME}/{day}.md",
                "content": render_journal_page(episode.date, episode.entries, episode.summary),
            }
        )

    facts_by_category: dict[str, list[tuple[str, str, float]]] = {}
    for memory in memories:
        facts_by_category.setdefault(memory.category_path, []).append(
            (str(memory.id), memory.content, memory.importance)
        )
    for category_path, facts in facts_by_category.items():
        projections.append(
            {
                "id": f"facts:{category_path}",
                "path": f"{FACTS_DIRNAME}/{category_path}.md",
                "content": render_facts_page(category_path, facts),
            }
        )

    return projections
