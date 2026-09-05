"""Executor tools to observe and control its own running subagents.

The executor is the only tier that knows which subagents are live and which one a
mid-run steer belongs to, so it owns routing. These three tools are how it acts:
list what is running, steer one by id, or cancel one by id. A steer the user
sends always lands in the executor's own inbox first (see ``executor_channel``);
the executor then decides — with these tools — whether it is for a subagent, for
which one, or for itself.

Bound only to the executor. Never to comms (which does not run subagents) or to a
subagent (which must not steer a peer).
"""

from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.background.running_registry import RunningSubagents
from app.agents.core.background.subagent_channel import SubagentCancel, SubagentInbox
from app.models.agent_models import RunningSubagent, agent_configurable

_NOT_RUNNING = (
    "No running subagent with id {id!r}. It may have already finished — call "
    "list_running_subagents to see what is live."
)


async def _resolve(config: RunnableConfig, subagent_id: str) -> RunningSubagent | None:
    conversation_id = str(agent_configurable(config).get("conversation_id", ""))
    return await RunningSubagents(conversation_id).get(subagent_id)


@tool
async def list_running_subagents(config: RunnableConfig) -> str:
    """List the subagents currently running for this conversation.

    Use this before steering or cancelling, to get the id of the subagent you
    mean. Returns each running subagent's id, its integration, and what it is
    working on.
    """
    conversation_id = str(agent_configurable(config).get("conversation_id", ""))
    running = await RunningSubagents(conversation_id).list()
    if not running:
        return "No subagents are currently running."
    return "\n".join(f"- {s.subagent_id} ({s.integration_id}): {s.task_summary}" for s in running)


@tool
async def message_subagent(config: RunnableConfig, subagent_id: str, message: str) -> str:
    """Steer a specific running subagent with a new instruction or hint.

    Delivers ``message`` to that subagent's mailbox; it picks it up on its next
    reasoning step and folds it into the work it is already doing. Use it to add a
    constraint or hint the subagent needs (e.g. a date range for a search). Get
    ``subagent_id`` from list_running_subagents.
    """
    subagent = await _resolve(config, subagent_id)
    if subagent is None:
        return _NOT_RUNNING.format(id=subagent_id)
    await SubagentInbox(subagent.subagent_thread_id).append(str(uuid4()), message)
    return f"Steer delivered to the {subagent.integration_id} subagent ({subagent_id})."


@tool
async def cancel_subagent(config: RunnableConfig, subagent_id: str) -> str:
    """Stop a specific running subagent.

    Asks that one subagent to stop at its next step and return what it has; the
    executor and any other running subagents are unaffected. Use it when a
    subagent is doing the wrong thing or is no longer needed. Get ``subagent_id``
    from list_running_subagents.
    """
    subagent = await _resolve(config, subagent_id)
    if subagent is None:
        return _NOT_RUNNING.format(id=subagent_id)
    await SubagentCancel(subagent.subagent_thread_id).request()
    return f"Cancel requested for the {subagent.integration_id} subagent ({subagent_id})."
