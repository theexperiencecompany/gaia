"""Drop a workflow conversation's LangGraph checkpoint threads before a run.

A workflow reuses ONE conversation forever, so every fire resumes the same
checkpoint threads and replays all previous runs out of Postgres — one
production workflow carried 1.39 MB of message state across three threads and
~83k input tokens per LLM call. What those threads silently provided (what the
previous run did) is supplied instead by the recorded trace in
:mod:app.services.workflow.run_trace, so they can be dropped before each run
(see :mod:app.services.checkpoint_thread_reset for which threads, and why).
"""

from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from app.services.checkpoint_thread_reset import reset_conversation_threads
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

        result = await reset_conversation_threads(conversation_id)
        if result is None:
            log.warning(
                f"{LogTag.WORKER} Thread reset skipped — no checkpointer pool",
                conversation_id=conversation_id,
            )
            return 0

        log.set_ns(
            "workflow",
            threads_reset=result.reset,
            threads_skipped_inflight=result.skipped_inflight,
        )
        return result.reset

    except Exception as e:
        log.warning(
            f"{LogTag.WORKER} Workflow thread reset failed — run will replay its history",
            conversation_id=conversation_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return 0
