"""Resume a background subagent parked on an approval, from the decision that answers it.

The decision can land in any process, hours later and after a restart, so the run
is rebuilt from the recipe the HIL gate filed on the record — by the spawner that
built it — and resumed on its own checkpointed thread.
"""

from typing import cast

from app.agents.core.background.running_registry import RunningSubagents
from app.agents.core.graph_manager import GraphManager
from app.agents.core.subagents.delegation import Delegation, resume_background
from app.agents.middleware.subagent import spawner_of
from app.models.agent_models import SubagentKind, SubagentResumeItem
from app.models.hil_models import HILApprovalRecord


class SubagentResumeError(RuntimeError):
    """The parked subagent could not be rebuilt, so its decision cannot resume it."""


async def resume_parked_subagent(record: HILApprovalRecord) -> bool:
    """Resume the subagent parked on this decided record; False when its thread is taken.

    A taken thread is the run still live (its own park resumes it once it exits) or a
    resume already running, which re-reads every decided record at its gates.
    """
    # Equivalent under mutation: holds_thread reads the thread's own key, never the conversation's.
    registry = RunningSubagents(record.conversation_id)  # pragma: no mutate
    if record.subagent_thread_id and await registry.holds_thread(record.subagent_thread_id):
        return False
    # Correct by construction: the gate files a SubagentResumeItem and nothing else.
    item = cast(SubagentResumeItem, record.subagent_resume)
    return await resume_background(await _rebuild(item), record.resume_payload())


async def _rebuild(item: SubagentResumeItem) -> Delegation:
    # Only spawn_subagent parks today; a recipe of any other kind is a retired
    # delegation tool whose subagent can no longer be built.
    if item["kind"] != SubagentKind.SPAWN:
        raise SubagentResumeError(f"no builder for a parked {item['kind']!r} subagent")
    spawner = spawner_of(await GraphManager.get_graph("executor_agent"))
    return await spawner.build_delegation(
        task=item["task"],
        context=item["context"],
        parent_configurable=item["parent_configurable"],
        tool_call_id=item["tool_call_id"],
        inherited_tool_names=item["inherited_tool_names"],
    )
