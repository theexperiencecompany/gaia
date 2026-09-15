"""Background subagent coroutine for non-blocking handoff execution.

Spawned by handoff(background=True) via asyncio.create_task(). Runs the
subagent graph, appends the final result to the conversation's durable
results bucket (Redis — it must survive the executor's approval pause), and
decrements the in-process pending counter.

The executor calls wait_for_subagents() to block until all background
subagents complete or park, collect their results, and — when any parked on a
HIL approval — pause the executor once for the whole batch.
"""

from dataclasses import dataclass
import time

from app.agents.core.background.bg_results import append_bg_subagent_result
from app.agents.core.background.executor_queue import enqueue_collection_run, is_executor_busy
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.background.session import (
    decrement_pending_subagents,
    release_bg_integration,
)
from app.agents.core.subagents.call_record import append_call_record
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    execute_subagent_stream,
)
from app.constants.log_tags import LogTag
from app.models.agent_models import AgentConfigurable
from app.services.hil.approvals_store import stamp_subagent_resume
from app.utils.agent_utils import (
    IntegrationMetadata,
    SubagentStartDetails,
    format_subagent_end_event,
    format_subagent_start_event,
)
from shared.py.wide_events import get_trace_id, log, wide_task


@dataclass(frozen=True)
class BackgroundHandoff:
    """How a background subagent run presents itself and what it releases on exit.

    Icon/name metadata for tool events, the subagent and integration ids, the
    display triple for start/end cards, and whether successful calls are
    recorded (workflow runs only).
    """

    integration_metadata: IntegrationMetadata | None = None
    subagent_id: str | None = None
    display_name: str | None = None
    tool_category: str | None = None
    icon_url: str | None = None
    integration_id: str | None = None
    record_calls: bool = False


async def run_subagent_background(
    ctx: SubagentExecutionContext,
    stream_id: str,
    handoff: BackgroundHandoff | None = None,
) -> None:
    """Run a provider subagent in the background and store its result.

    Designed for asyncio.create_task(). Never raises — exceptions are caught
    and stored as the result text. A HIL pause stamps the approval record and
    exits; wait_for_subagents rediscovers it durably and resumes on decision.
    """
    handoff = handoff or BackgroundHandoff()
    integration_metadata, subagent_id, integration_id = (
        handoff.integration_metadata,
        handoff.subagent_id,
        handoff.integration_id,
    )
    display_name, tool_category, icon_url = (
        handoff.display_name,
        handoff.tool_category,
        handoff.icon_url,
    )
    record_calls = handoff.record_calls

    conversation_id = str(ctx.configurable.get("conversation_id", ""))
    # This task outlives the spawning executor turn, so it needs its own
    # wide-event boundary or every log.set() is silently discarded.
    # get_trace_id() correlates this event with the run that dispatched it.
    async with wide_task(
        "subagent_run",
        trace_id=get_trace_id() or None,
        agent_name=ctx.agent_name,
        conversation_id=conversation_id,
        stream_id=stream_id,
        subagent_id=subagent_id,
        integration_id=integration_id,
    ):
        try:
            writer = make_redis_stream_writer(stream_id)

            if subagent_id:
                writer(
                    {
                        "subagent_start": format_subagent_start_event(
                            subagent_name=display_name or ctx.agent_name,
                            agent_type="handoff",
                            subagent_id=subagent_id,
                            details=SubagentStartDetails(
                                icon_url=icon_url, tool_category=tool_category
                            ),
                        )
                    }
                )

            start_time = time.monotonic()
            outcome = await execute_subagent_stream(
                ctx=ctx,
                stream_writer=writer,
                integration_metadata=integration_metadata,
                subagent_id=subagent_id,
            )
            if outcome.paused:
                await _park(ctx, outcome.interrupt or {}, stream_id)
                return
            result = (
                append_call_record(outcome.text, outcome.run_messages)
                if record_calls
                else outcome.text
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)

            if subagent_id:
                writer(
                    {
                        "subagent_end": format_subagent_end_event(
                            subagent_id=subagent_id,
                            duration_ms=duration_ms,
                        )
                    }
                )
            log.info(
                f"{LogTag.AGENT} Background subagent completed",
                agent_name=ctx.agent_name,
                stream_id=stream_id,
            )
            await append_bg_subagent_result(conversation_id, ctx.agent_name, result)
        except Exception as e:
            log.error(
                f"{LogTag.AGENT} Background subagent failed",
                agent_name=ctx.agent_name,
                stream_id=stream_id,
                error=str(e),
            )
            await _append_error_result(conversation_id, ctx.agent_name, e)
        finally:
            if integration_id:
                release_bg_integration(stream_id, integration_id)
            # Decrement AFTER appending the result (or stamping the park) so any
            # wait_for_subagents that wakes on the count change sees this subagent's
            # terminal state.
            decrement_pending_subagents(stream_id)
            await _wake_if_executor_rested(conversation_id, ctx.configurable)


async def _wake_if_executor_rested(conversation_id: str, configurable: AgentConfigurable) -> None:
    """Queue a collection turn when this landing has no live executor to collect it.

    Busy executor -> it will collect itself; headless run -> nothing to wake
    (results have no live audience). Best-effort: a wake failure must not
    crash the task — the marker TTL and the next landing retry it.
    """
    if not conversation_id or str(configurable.get("execution_mode") or "") == "background":
        return
    try:
        if not await is_executor_busy(conversation_id):
            await enqueue_collection_run(conversation_id, configurable)
    except Exception as e:  # create_task coroutine must not raise
        log.error(
            f"{LogTag.AGENT} Could not queue collection wake-up",
            conversation_id=conversation_id,
            error=str(e),
        )


async def _park(
    ctx: SubagentExecutionContext, interrupt: dict[str, object], stream_id: str
) -> None:
    """Record a HIL-paused subagent durably so the join can resume it later.

    No result is appended — the subagent's real result is collected by the join
    after the user's decision resumes its checkpointed thread.
    """
    approval_id = str(interrupt.get("approval_id", ""))
    thread_id = str(ctx.configurable.get("thread_id", ""))
    if not approval_id or not thread_id:
        # Unresumable pause: without the id pair nothing can ever collect this
        # subagent. Surface it as an error result rather than stranding silently.
        raise RuntimeError(
            f"Background subagent {ctx.agent_name} paused on approval but the pause "
            f"is unresumable (approval_id={approval_id!r}, thread_id={thread_id!r})"
        )
    await stamp_subagent_resume(
        approval_id,
        subagent_thread_id=thread_id,
        subagent_agent_name=ctx.agent_name,
    )
    log.info(
        f"{LogTag.HIL} Background subagent parked on approval",
        agent_name=ctx.agent_name,
        approval_id=approval_id,
        subagent_thread_id=thread_id,
        stream_id=stream_id,
    )


async def _append_error_result(conversation_id: str, agent_name: str, error: Exception) -> None:
    """Best-effort error result; never let a Redis failure escape the task."""
    try:
        await append_bg_subagent_result(
            conversation_id, agent_name, f"Error from {agent_name}: {error!s}"
        )
    except Exception as redis_error:  # create_task coroutine must not raise
        log.error(
            f"{LogTag.AGENT} Could not store bg subagent error result",
            agent_name=agent_name,
            error=str(redis_error),
        )
