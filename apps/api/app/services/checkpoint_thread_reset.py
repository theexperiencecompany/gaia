"""Drop the LangGraph checkpoint threads a long-lived conversation owns, before a run.

A conversation reused across runs (a workflow's, a tracked todo's chat) would
otherwise resume the same threads and replay every previous run out of Postgres.
What a run needs of the previous ones is supplied from durable records instead
(the workflow's run trace, the todo's canvas and activity), so the threads are
disposable.

Distinct from conversation_service._delete_checkpoint_threads, which deletes
everything containing the conversation id because the conversation itself is
going away. A live reset must be conservative: only the threads this
conversation demonstrably owns (anchored suffix, never a substring), and never
one with pending writes on its head — that is an in-flight run whose rows would
vanish underneath it.
"""

from typing import NamedTuple

from app.agents.core.graph_builder.checkpointer_manager import get_checkpointer_manager
from app.constants.general import EXECUTOR_THREAD_PREFIX


class ThreadReset(NamedTuple):
    """How many owned threads one reset deleted, and how many it spared as in flight."""

    reset: int
    skipped_inflight: int


async def reset_conversation_threads(
    conversation_id: str, *, keep_conversation_thread: bool = False
) -> ThreadReset | None:
    """Delete the checkpoint threads this conversation owns; None when there is no checkpointer pool.

    Owned threads are the conversation's own (comms) thread, the executor's, and each
    handoff subagent's executor thread. keep_conversation_thread spares the comms
    thread, for a chat whose memory of its own exchange must survive while the
    execution under it starts over. Raises on a checkpointer failure.
    """
    manager = await get_checkpointer_manager()
    pool = manager.pool
    if pool is None:
        return None
    checkpointer = manager.get_checkpointer()

    # Compared with `right()` not LIKE: the ids are full of underscores that LIKE
    # would need escaped.
    executor_thread = f"{EXECUTOR_THREAD_PREFIX}{conversation_id}"
    suffix = f"_{executor_thread}"
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT DISTINCT thread_id FROM checkpoints "
            "WHERE thread_id IN (%s, %s) OR right(thread_id, %s) = %s",
            (conversation_id, executor_thread, len(suffix), suffix),
        )
        thread_ids = [
            row[0]
            for row in await cur.fetchall()
            if not (keep_conversation_thread and row[0] == conversation_id)
        ]
        if not thread_ids:
            return ThreadReset(reset=0, skipped_inflight=0)

        # Same condition the nightly prune applies: a write parked on a
        # thread's head checkpoint is an in-flight or interrupted run.
        await cur.execute(
            "SELECT DISTINCT w.thread_id FROM checkpoint_writes w "
            "WHERE w.thread_id = ANY(%s) AND w.checkpoint_id = ("
            "  SELECT max(c.checkpoint_id) FROM checkpoints c"
            "  WHERE c.thread_id = w.thread_id AND c.checkpoint_ns = w.checkpoint_ns"
            ")",
            (thread_ids,),
        )
        inflight = {row[0] for row in await cur.fetchall()}

    deletable = [tid for tid in thread_ids if tid not in inflight]
    for thread_id in deletable:
        await checkpointer.adelete_thread(thread_id)
    return ThreadReset(reset=len(deletable), skipped_inflight=len(inflight))
