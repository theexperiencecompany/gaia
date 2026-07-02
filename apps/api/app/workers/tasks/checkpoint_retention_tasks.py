"""ARQ task that garbage-collects LangGraph Postgres checkpoints.

`prune_checkpoint_versions`: nightly. Two phases against the
`checkpoints` / `checkpoint_writes` / `checkpoint_blobs` tables written by
`AsyncPostgresSaver`:

1. **Orphan sweep** — a thread whose owning conversation no longer exists in
   Mongo is deleted whole (`checkpointer.adelete_thread`). This is the backstop
   for the best-effort thread cleanup in `conversation_service.delete_conversation`
   (a delete that failed while Postgres was unreachable, or a bot conversation
   abandoned without an explicit delete).

2. **Version prune** — LangGraph writes one checkpoint per superstep per thread
   forever, so a long-lived thread accumulates thousands of rows. This prunes
   the superseded ancestor checkpoints of each thread's head.

   DeltaChannel constraint (see app/override/langgraph_bigtool/utils.py): the
   `messages` channel stores only a per-step delta in most checkpoints, with a
   full snapshot every MESSAGES_SNAPSHOT_FREQUENCY updates. Reconstructing the
   head's state walks the parent chain back to the nearest checkpoint whose
   `messages` blob is a real snapshot and replays the deltas after it (see
   `BaseCheckpointSaver.aget_delta_channel_history`). Dropping any checkpoint
   between the head and that snapshot would silently reconstruct the channel as
   empty. So the prune keeps the contiguous parent chain from the head back to
   (and including) the nearest snapshot, and deletes only the strictly-older
   ancestors of that snapshot. Legacy threads written before DeltaChannel store
   a full snapshot at every checkpoint, so the head is itself the snapshot and
   all its ancestors are prunable — this is where the big reclaim comes from.

   Threads with pending writes on the head (an in-flight or interrupted run)
   are skipped so a resuming run never loses ancestor rows it depends on.
"""

from __future__ import annotations

import re
from typing import Any

from app.constants.general import (
    CHECKPOINT_EMPTY_BLOB_TYPE,
    CHECKPOINT_MESSAGES_CHANNEL,
    CHECKPOINT_ORPHAN_SWEEP_MAX_THREADS,
    CHECKPOINT_PRUNE_MAX_THREADS_PER_RUN,
    CHECKPOINT_PRUNE_MIN_CHECKPOINTS,
)
from app.constants.log_tags import LogTag
from app.db.mongodb.collections import conversations_collection
from shared.py.wide_events import log, wide_task

# A conversation_id is normally a uuid; derived thread ids embed it verbatim
# (`executor_<conv>`, `<integration>_executor_<conv>_<runhex>`, `workflow_<conv>`,
# ...). We extract every uuid substring as a candidate owning-conversation.
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def _thread_is_orphan(
    thread_id: str, live_all: set[str], live_uuid: set[str], live_non_uuid: list[str]
) -> bool:
    """True if no live conversation owns this thread.

    Never returns True for a thread whose owning conversation is live: the
    conversation_id is always a substring of its derived thread ids, so a uuid
    conversation is caught by the candidate-uuid intersection and a non-uuid one
    by the substring scan. Extra uuids in the thread (e.g. a uuid integration
    id) only make the test more conservative (fewer deletions), never less safe.
    """
    candidates = set(_UUID_RE.findall(thread_id))
    if candidates & live_uuid:
        return False
    if thread_id in live_all:
        return False
    return not any(conv in thread_id for conv in live_non_uuid)


def _prune_ids_for_chain(
    checkpoint_rows: list[tuple[str, str | None, bool]],
    head_has_pending_writes: bool,
) -> list[str]:
    """Return the checkpoint ids safe to delete for one (thread, ns).

    `checkpoint_rows` is `(checkpoint_id, parent_checkpoint_id, has_msg_snapshot)`.
    Returns the strict ancestors of the nearest `messages` snapshot on the head's
    parent chain — everything older than the seed the head reconstructs from.
    Returns [] when the thread is in-flight, has no snapshot on its chain (a
    fresh DeltaChannel thread below the first snapshot must replay from root), or
    has nothing prunable.
    """
    if head_has_pending_writes or len(checkpoint_rows) < CHECKPOINT_PRUNE_MIN_CHECKPOINTS:
        return []

    parent_of: dict[str, str | None] = {}
    has_snapshot: dict[str, bool] = {}
    for checkpoint_id, parent_id, has_snap in checkpoint_rows:
        parent_of[checkpoint_id] = parent_id
        has_snapshot[checkpoint_id] = has_snap

    # Head = latest checkpoint. uuid6 ids sort lexicographically by time, which
    # matches how the saver selects the latest checkpoint for a bare thread_id.
    head = max(parent_of)

    chain: list[str] = []
    cursor: str | None = head
    seen: set[str] = set()
    while cursor is not None and cursor in parent_of and cursor not in seen:
        seen.add(cursor)
        chain.append(cursor)
        cursor = parent_of[cursor]

    snapshot_idx = next((i for i, cid in enumerate(chain) if has_snapshot[cid]), None)
    if snapshot_idx is None:
        return []
    return chain[snapshot_idx + 1 :]


async def _prune_thread_versions(cur: Any, thread_id: str, ns: str, prune_ids: list[str]) -> dict:
    """Delete superseded ancestor checkpoints + their writes + orphaned blobs."""
    await cur.execute(
        "DELETE FROM checkpoint_writes WHERE thread_id = %s AND checkpoint_ns = %s "
        "AND checkpoint_id = ANY(%s)",
        (thread_id, ns, prune_ids),
    )
    writes_deleted = cur.rowcount
    await cur.execute(
        "DELETE FROM checkpoints WHERE thread_id = %s AND checkpoint_ns = %s "
        "AND checkpoint_id = ANY(%s)",
        (thread_id, ns, prune_ids),
    )
    checkpoints_deleted = cur.rowcount
    # A blob is keyed by (channel, version) and shared by every checkpoint that
    # references that version, so it is safe to drop only once no surviving
    # checkpoint's channel_versions points at it. Run after the checkpoint delete
    # above so the NOT EXISTS sees survivors only.
    await cur.execute(
        "DELETE FROM checkpoint_blobs b WHERE b.thread_id = %s AND b.checkpoint_ns = %s "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM checkpoints c"
        "  WHERE c.thread_id = b.thread_id AND c.checkpoint_ns = b.checkpoint_ns"
        "    AND c.checkpoint->'channel_versions'->>b.channel = b.version"
        ") RETURNING octet_length(blob)",
        (thread_id, ns),
    )
    blob_rows = await cur.fetchall()
    blobs_deleted = len(blob_rows)
    bytes_freed = sum(row[0] or 0 for row in blob_rows)
    return {
        "checkpoints": checkpoints_deleted,
        "writes": writes_deleted,
        "blobs": blobs_deleted,
        "bytes": bytes_freed,
    }


async def sweep_orphan_threads(pool: Any, checkpointer: Any) -> dict:
    """Delete every checkpoint thread whose conversation is gone from Mongo."""
    live_ids = await conversations_collection.distinct("conversation_id")
    live_all = {str(c) for c in live_ids if c}
    live_uuid = {c for c in live_all if _UUID_RE.fullmatch(c)}
    live_non_uuid = [c for c in live_all if c not in live_uuid]

    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT DISTINCT thread_id FROM checkpoints")
        thread_ids = [row[0] for row in await cur.fetchall()]

    orphans = [
        tid for tid in thread_ids if _thread_is_orphan(tid, live_all, live_uuid, live_non_uuid)
    ][:CHECKPOINT_ORPHAN_SWEEP_MAX_THREADS]

    checkpoints_deleted = 0
    if orphans:
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT count(*) FROM checkpoints WHERE thread_id = ANY(%s)", (orphans,)
            )
            checkpoints_deleted = (await cur.fetchone())[0]

    for tid in orphans:
        await checkpointer.adelete_thread(tid)

    return {
        "threads_total": len(thread_ids),
        "orphan_threads_deleted": len(orphans),
        "orphan_checkpoints_deleted": checkpoints_deleted,
    }


async def prune_thread_versions(pool: Any) -> dict:
    """Prune superseded checkpoint versions across the busiest threads."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT thread_id, checkpoint_ns, count(*) AS c FROM checkpoints "
            "GROUP BY thread_id, checkpoint_ns HAVING count(*) >= %s "
            "ORDER BY c DESC LIMIT %s",
            (CHECKPOINT_PRUNE_MIN_CHECKPOINTS, CHECKPOINT_PRUNE_MAX_THREADS_PER_RUN),
        )
        candidates = [(row[0], row[1]) for row in await cur.fetchall()]
        candidate_tids = [tid for tid, _ in candidates]

        totals = {
            "threads_scanned": len(candidates),
            "threads_pruned": 0,
            "threads_skipped_inflight": 0,
            "checkpoints_deleted": 0,
            "writes_deleted": 0,
            "blobs_deleted": 0,
            "bytes_estimate": 0,
        }
        if not candidate_tids:
            return totals

        await cur.execute(
            "SELECT DISTINCT thread_id, checkpoint_ns, checkpoint_id FROM checkpoint_writes "
            "WHERE thread_id = ANY(%s)",
            (candidate_tids,),
        )
        writes_by_checkpoint = {(r[0], r[1], r[2]) for r in await cur.fetchall()}

        await cur.execute(
            "SELECT c.thread_id, c.checkpoint_ns, c.checkpoint_id, c.parent_checkpoint_id, "
            "(b.type IS NOT NULL AND b.type <> %s) AS has_snapshot "
            "FROM checkpoints c "
            "LEFT JOIN checkpoint_blobs b "
            "  ON b.thread_id = c.thread_id AND b.checkpoint_ns = c.checkpoint_ns "
            " AND b.channel = %s "
            " AND b.version = c.checkpoint->'channel_versions'->>%s "
            "WHERE c.thread_id = ANY(%s)",
            (
                CHECKPOINT_EMPTY_BLOB_TYPE,
                CHECKPOINT_MESSAGES_CHANNEL,
                CHECKPOINT_MESSAGES_CHANNEL,
                candidate_tids,
            ),
        )
        rows_by_thread: dict[tuple[str, str], list[tuple[str, str | None, bool]]] = {}
        for tid, ns, cid, parent, has_snap in await cur.fetchall():
            rows_by_thread.setdefault((tid, ns), []).append((cid, parent, has_snap))

        for tid, ns in candidates:
            rows = rows_by_thread.get((tid, ns), [])
            if not rows:
                continue
            head = max(cid for cid, _, _ in rows)
            head_inflight = (tid, ns, head) in writes_by_checkpoint
            prune_ids = _prune_ids_for_chain(rows, head_inflight)
            if not prune_ids:
                if head_inflight:
                    totals["threads_skipped_inflight"] += 1
                continue
            result = await _prune_thread_versions(cur, tid, ns, prune_ids)
            totals["threads_pruned"] += 1
            totals["checkpoints_deleted"] += result["checkpoints"]
            totals["writes_deleted"] += result["writes"]
            totals["blobs_deleted"] += result["blobs"]
            totals["bytes_estimate"] += result["bytes"]

        return totals


async def prune_checkpoint_versions(_ctx: dict[str, Any]) -> str:
    """Nightly: sweep orphaned threads, then prune superseded checkpoint versions."""
    from app.agents.core.graph_builder.checkpointer_manager import get_checkpointer_manager

    async with wide_task("prune_checkpoint_versions"):
        manager = await get_checkpointer_manager()
        pool = manager.pool
        checkpointer = manager.get_checkpointer()

        orphan = await sweep_orphan_threads(pool, checkpointer)
        prune = await prune_thread_versions(pool)

        summary = {**orphan, **prune}
        log.set(checkpoint_retention=summary)
        log.info(f"{LogTag.WORKER} checkpoint retention swept + pruned", **summary)
        return (
            f"orphans={orphan['orphan_threads_deleted']} "
            f"pruned_threads={prune['threads_pruned']} "
            f"checkpoints_deleted={orphan['orphan_checkpoints_deleted'] + prune['checkpoints_deleted']} "
            f"bytes_estimate={prune['bytes_estimate']}"
        )
