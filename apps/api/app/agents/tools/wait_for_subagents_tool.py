"""Tool for the executor to wait for background subagents and collect results.

When the executor dispatches subagents with handoff(background=True), it can
continue with other work and then call wait_for_subagents() to block until all
background subagents have finished — or parked on a HIL approval.

This tool is also the HIL **approval barrier**: subagents that hit a gated
(destructive) tool park their own checkpointed graph thread and record the
approval durably. This join rediscovers them from those records, resumes the
decided ones, and pauses the executor ONCE for everything still pending — one
review moment per burst of parallel work, however many actions are in it. It
loops (pause → decision → resume → collect → maybe pause again) until the whole
batch is resolved, then returns every subagent's result together.

Everything the loop needs crosses the executor's pause durably: approval
records in Mongo, subagent checkpoints in Postgres, results in Redis (keyed by
conversation — stream ids change on resume). The in-process session counter is
only the fast path for live tasks in the current invocation.
"""

import asyncio
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.types import StreamWriter, interrupt

from app.agents.core.background.bg_results import (
    append_bg_subagent_result,
    drain_bg_subagent_results,
)
from app.agents.core.background.executor_queue import clear_collection_marker
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.background.session import get_pending_subagents
from app.agents.core.subagents.handoff_tools import resume_parked_subagent
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.hil import HIL_BATCH_INTERRUPT_TYPE
from app.constants.log_tags import LogTag
from app.models.agent_models import AgentConfigurable, agent_configurable
from app.models.hil_models import HILApprovalRecord
from app.services.hil.approvals_store import (
    list_parked_subagents_for_conversation,
    mark_resumed,
    mark_subagent_collected,
    stamp_subagent_resume,
)
from shared.py.wide_events import log


@tool
async def wait_for_subagents(
    config: RunnableConfig,
    # NOSONAR python:S7483 — `timeout` is part of this tool's LLM-facing input
    # schema (the model chooses how long to wait); it is not an internal call
    # timeout that an asyncio.timeout() context manager could replace.
    timeout: Annotated[  # NOSONAR python:S7483
        int,
        "Maximum seconds to wait for all background subagents. Default 120.",
    ] = 120,
) -> str:
    """Wait for all pending background subagents to complete and return their results.

    Call this after dispatching subagents with handoff(background=True) and
    after finishing any parallel work that doesn't depend on their results.

    If any subagent needs the user's approval for an action, this pauses until
    the user decides and then finishes those subagents accordingly.

    Returns all subagent results concatenated, ready for you to summarize.
    Returns immediately if no background subagents are pending.
    """
    configurable = agent_configurable(config)
    stream_id = str(configurable.get("stream_id") or "")
    conversation_id = str(configurable.get("conversation_id") or "")

    if not stream_id:
        return "No active stream — cannot wait for subagents."

    if conversation_id:
        # This join IS the collection a queued wake-up would have provided —
        # clear the dedup marker so later landings can queue a fresh one.
        await clear_collection_marker(conversation_id)

    await _poll_live_tasks(stream_id, timeout)

    if conversation_id:
        await _resolve_parked_batch(conversation_id, configurable, stream_id)
        results = await drain_bg_subagent_results(conversation_id)
    else:
        results = []

    if not results:
        return "No background subagent results to collect."

    log.info(
        f"{LogTag.TOOL} wait_for_subagents: collected results",
        result_count=len(results),
        stream_id=stream_id,
    )
    return "".join(
        wrap_agent_payload(AgentTag.SUBAGENT_RESULT, item["message"], agent=item["agent"])
        for item in results
    )


async def _poll_live_tasks(stream_id: str, timeout: int) -> None:
    """Poll the in-process counter until every live background task lands.

    Tasks append their result (or stamp their park) BEFORE decrementing, so a
    count of zero guarantees each task's terminal state is visible. After an
    executor resume there are no live tasks and this returns immediately —
    recovery is driven by the durable records instead.
    """
    pending = get_pending_subagents(stream_id)
    if pending == 0:
        return
    log.info(
        f"{LogTag.TOOL} wait_for_subagents: waiting for subagents",
        pending_count=pending,
        stream_id=stream_id,
    )
    deadline = asyncio.get_running_loop().time() + timeout
    while get_pending_subagents(stream_id) > 0:
        if asyncio.get_running_loop().time() >= deadline:
            log.warning(f"{LogTag.TOOL} wait_for_subagents: timed out", timeout_seconds=timeout)
            break
        await asyncio.sleep(0.1)


async def _resolve_parked_batch(
    conversation_id: str, configurable: AgentConfigurable, stream_id: str
) -> None:
    """Drive every HIL-parked subagent to completion, pausing the executor as needed.

    Each round: resume subagents whose approvals are decided; if any approvals are
    still pending, ``interrupt()`` once with the whole batch (the executor
    checkpoints and exits; a decision re-dispatches it and this node re-runs from
    the top, idempotently). A resumed subagent may park again on its next gated
    action — the loop carries it into the next round.
    """
    writer = make_redis_stream_writer(stream_id)
    while True:
        parked = await list_parked_subagents_for_conversation(conversation_id)
        if not parked:
            return

        decided = [record for record in parked if record.status.settled]
        for record in decided:
            await _collect_subagent(record, configurable, writer, conversation_id)
        if decided:
            # Statuses may have changed while collecting (or a resumed subagent
            # re-parked) — re-query before deciding whether to pause.
            continue

        pending = [record for record in parked if not record.status.settled]
        log.info(
            f"{LogTag.HIL} wait_for_subagents pausing executor for approvals",
            approval_count=len(pending),
            conversation_id=conversation_id,
        )
        # One interrupt per batch — the resume VALUE is irrelevant (decisions are
        # read durably from the records on the replay); the pause itself is the point.
        interrupt(
            {
                "type": HIL_BATCH_INTERRUPT_TYPE,
                "approval_ids": [record.approval_id for record in pending],
                "approvals": [
                    {
                        "approval_id": record.approval_id,
                        "summary": record.summary,
                        "integration_name": record.integration_name,
                        "tool_name": record.tool_name,
                    }
                    for record in pending
                ],
            }
        )


async def _collect_subagent(
    record: HILApprovalRecord,
    configurable: AgentConfigurable,
    writer: StreamWriter,
    conversation_id: str,
) -> None:
    """Resume one decided subagent and store its outcome.

    Collection is stamped BEFORE the resume runs: LangGraph replays the thread's
    approved action on resume, so if this process dies mid-resume, a re-run must
    not drive the thread again (re-sending the email). The cost of crashing after
    the stamp is one missing result string; the cost of stamping late is a
    duplicated irreversible action. The sweep's loud-expiry covers the former.
    """
    await mark_subagent_collected(record.approval_id)
    # Also stamp resumed_at: this decision has now reached a run. Without it the
    # sweep's decided-unresumed pass would re-dispatch this approval forever.
    await mark_resumed(record.approval_id)
    agent_name = record.subagent_agent_name or "subagent"
    try:
        outcome = await resume_parked_subagent(record, configurable, writer)
    except Exception as e:  # one subagent's failure must not strand the batch
        log.error(
            f"{LogTag.HIL} Failed to resume parked subagent",
            approval_id=record.approval_id,
            agent_name=agent_name,
            error=str(e),
        )
        await append_bg_subagent_result(
            conversation_id, agent_name, f"Error resuming {agent_name}: {e!s}"
        )
        return

    if outcome.paused:
        # Parked again on its next gated action: stamp the NEW approval so the
        # next round of the barrier picks it up.
        new_approval_id = str((outcome.interrupt or {}).get("approval_id", ""))
        if new_approval_id and record.subagent_thread_id:
            await stamp_subagent_resume(
                new_approval_id,
                subagent_thread_id=record.subagent_thread_id,
                subagent_agent_name=agent_name,
            )
        else:
            log.error(
                f"{LogTag.HIL} Re-parked subagent pause is unresumable; recording error",
                approval_id=record.approval_id,
                agent_name=agent_name,
            )
            await append_bg_subagent_result(
                conversation_id,
                agent_name,
                f"Error: {agent_name} paused again but the pause was malformed.",
            )
        return

    await append_bg_subagent_result(conversation_id, agent_name, outcome.text)


tools = [wait_for_subagents]
