"""Drop a workflow conversation's LangGraph checkpoint threads before a run.

A workflow reuses ONE conversation forever, so every fire resumes the same
checkpoint threads and replays all previous runs out of Postgres — one
production workflow carried 1.39 MB of message state across three threads and
~83k input tokens per LLM call. What those threads silently provided (what the
previous run did) is supplied instead by the recorded trace in
:mod:`app.services.workflow.run_trace`, so they can be dropped before each run.

Distinct from ``conversation_service._delete_checkpoint_threads``, which deletes
everything containing the conversation id because the conversation itself is
going away. A live reset must be conservative: only the threads this
conversation demonstrably owns (anchored suffix, never a substring), and never
one with pending writes on its head — that is an in-flight run whose rows would
vanish underneath it.
"""

from app.agents.core.graph_builder.checkpointer_manager import get_checkpointer_manager
from app.constants.general import EXECUTOR_THREAD_PREFIX
from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from shared.py.wide_events import log


async def reset_workflow_threads(conversation_id: str) -> int:
    """Delete every checkpoint thread this workflow conversation owns; return the count.

    Never raises: a failed reset degrades to "this run replays its history",
    which must not fail the workflow.
    """
    try:
        if not await conversation_repository.is_workflow_execution(conversation_id):
            log.warning(
                f"{LogTag.WORKER} Thread reset skipped — not a workflow conversation",
                conversation_id=conversation_id,
            )
            return 0

        manager = await get_checkpointer_manager()
        pool = manager.pool
        if pool is None:
            log.warning(
                f"{LogTag.WORKER} Thread reset skipped — no checkpointer pool",
                conversation_id=conversation_id,
            )
            return 0
        checkpointer = manager.get_checkpointer()

        # The conversation's own thread, the executor's, and each handoff
        # subagent's `<namespace>_executor_<conv>`. Compared with `right()`
        # rather than LIKE: the ids are full of underscores, and a LIKE pattern
        # would need them escaped to keep `_` from matching any character.
        executor_thread = f"{EXECUTOR_THREAD_PREFIX}{conversation_id}"
        suffix = f"_{executor_thread}"
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT DISTINCT thread_id FROM checkpoints "
                "WHERE thread_id IN (%s, %s) OR right(thread_id, %s) = %s",
                (conversation_id, executor_thread, len(suffix), suffix),
            )
            thread_ids = [row[0] for row in await cur.fetchall()]
            if not thread_ids:
                return 0

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

        log.set_ns(
            "workflow",
            threads_reset=len(deletable),
            threads_skipped_inflight=len(inflight),
        )
        return len(deletable)

    except Exception as e:
        log.warning(
            f"{LogTag.WORKER} Workflow thread reset failed — run will replay its history",
            conversation_id=conversation_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return 0
