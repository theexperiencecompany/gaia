from app.agents.core.graph_builder.checkpointer_manager import get_checkpointer_manager
from app.constants.llm import CHECKPOINT_KEEP_LATEST
from app.constants.log_tags import LogTag
from shared.py.wide_events import log, wide_task


async def prune_langgraph_checkpoints(ctx) -> str:
    """
    Prune old LangGraph checkpoints, keeping only CHECKPOINT_KEEP_LATEST per thread.

    Deletes checkpoint_writes, checkpoint_blobs, and checkpoint rows for every
    checkpoint beyond the newest CHECKPOINT_KEEP_LATEST per (thread_id, checkpoint_ns).
    Thread history is never deleted by age — that is a user-data decision, not
    an infrastructure one. The message trimming node keeps per-checkpoint size
    bounded; this job keeps the number of historical snapshots bounded.
    """
    async with wide_task("prune_langgraph_checkpoints"):
        checkpointer_manager = await get_checkpointer_manager()
        if not checkpointer_manager:
            return "Skipped: checkpointer manager unavailable"

        pool = checkpointer_manager.pool
        writes_deleted = 0
        blobs_deleted = 0
        checkpoints_deleted = 0

        async with pool.connection() as conn:
            # Delete checkpoint_writes for all but the latest N checkpoints per thread.
            # These intermediate writes are already baked into the full checkpoint
            # snapshot and are not needed for graph resumption.
            result = await conn.execute(
                """
                WITH ranked AS (
                  SELECT thread_id, checkpoint_ns, checkpoint_id,
                         ROW_NUMBER() OVER (
                           PARTITION BY thread_id, checkpoint_ns
                           ORDER BY (checkpoint->>'ts') DESC NULLS LAST
                         ) AS rn
                  FROM checkpoints
                ),
                old_ids AS (
                  SELECT thread_id, checkpoint_ns, checkpoint_id
                  FROM ranked WHERE rn > $1
                )
                DELETE FROM checkpoint_writes cw
                USING old_ids o
                WHERE cw.thread_id = o.thread_id
                  AND cw.checkpoint_ns = o.checkpoint_ns
                  AND cw.checkpoint_id = o.checkpoint_id
                """,
                [CHECKPOINT_KEEP_LATEST],
            )
            writes_deleted = result.rowcount or 0

            # Delete checkpoint_blobs not referenced by the CHECKPOINT_KEEP_LATEST
            # newest checkpoints. The checkpoint->channel_versions JSONB maps each
            # channel to the exact blob version that checkpoint requires — we keep
            # only those exact (channel, version) pairs.
            result = await conn.execute(
                """
                WITH ranked AS (
                  SELECT thread_id, checkpoint_ns, checkpoint_id, checkpoint,
                         ROW_NUMBER() OVER (
                           PARTITION BY thread_id, checkpoint_ns
                           ORDER BY (checkpoint->>'ts') DESC NULLS LAST
                         ) AS rn
                  FROM checkpoints
                ),
                kept AS (
                  SELECT thread_id, checkpoint_ns, checkpoint
                  FROM ranked WHERE rn <= $1
                ),
                kept_versions AS (
                  SELECT k.thread_id, k.checkpoint_ns,
                         kv.key AS channel, kv.value AS version
                  FROM kept k,
                       jsonb_each_text(k.checkpoint->'channel_versions') AS kv(key, value)
                )
                DELETE FROM checkpoint_blobs cb
                WHERE NOT EXISTS (
                  SELECT 1 FROM kept_versions kv
                  WHERE kv.thread_id = cb.thread_id
                    AND kv.checkpoint_ns = cb.checkpoint_ns
                    AND kv.channel = cb.channel
                    AND kv.version = cb.version
                )
                """,
                [CHECKPOINT_KEEP_LATEST],
            )
            blobs_deleted = result.rowcount or 0

            # Delete old checkpoint rows.
            result = await conn.execute(
                """
                WITH ranked AS (
                  SELECT thread_id, checkpoint_ns, checkpoint_id,
                         ROW_NUMBER() OVER (
                           PARTITION BY thread_id, checkpoint_ns
                           ORDER BY (checkpoint->>'ts') DESC NULLS LAST
                         ) AS rn
                  FROM checkpoints
                )
                DELETE FROM checkpoints c
                USING ranked r
                WHERE c.thread_id = r.thread_id
                  AND c.checkpoint_ns = r.checkpoint_ns
                  AND c.checkpoint_id = r.checkpoint_id
                  AND r.rn > $1
                """,
                [CHECKPOINT_KEEP_LATEST],
            )
            checkpoints_deleted = result.rowcount or 0

        summary = (
            f"Pruned: {checkpoints_deleted} old checkpoints, "
            f"{blobs_deleted} old blobs, "
            f"{writes_deleted} old writes"
        )
        log.info(f"{LogTag.WORKER} {summary}")
        return summary
