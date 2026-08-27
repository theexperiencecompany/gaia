"""Dev-only direct agent invocation.

Runs the executor agent or any single subagent directly, skipping the comms
front door, so tests and coding agents can exercise one layer in isolation
instead of always driving the full comms → executor → handoff chain. Reuses
the exact production preparation paths (``prepare_executor_execution``,
``prepare_subagent_execution``) so a direct run can never drift from what the
real hand-off does. Mounted only in development behind the auth bypass — see
``create_app``. Under ``GAIA_SIM_MODE`` the graphs already resolve to the
scripted LLM stub, so directive-bearing tasks run deterministically.
"""

from typing import cast
from uuid import uuid4

from app.agents.core.subagents.handoff_tools import prepare_subagent_execution
from app.agents.core.subagents.registry import all_subagents
from app.agents.core.subagents.subagent_runner import (
    SubagentOutcome,
    execute_subagent_stream,
    prepare_executor_execution,
)
from app.agents.llm.lane import AgentRole
from app.constants.log_tags import LogTag
from app.helpers.agent_helpers import build_agent_config
from app.models.agent_models import AgentConfigurable, AgentUserContext
from app.schemas.dev_schemas import DevAgentRunResponse, DevSubagentInfo
from app.services.dev_service import require_dev_user
from app.utils.errors import create_error
from app.utils.user_preferences_utils import onboarding_preferences
from shared.py.wide_events import log


def list_dev_subagents() -> list[DevSubagentInfo]:
    """Every registered subagent, with the ids accepted by the direct-run endpoint."""
    return [
        DevSubagentInfo(
            id=sa.id,
            name=sa.name,
            short_name=sa.short_name,
            agent_name=sa.config.agent_name,
        )
        for sa in all_subagents()
    ]


async def _dev_base_configurable(
    email: str, conversation_id: str | None, agent_name: str
) -> tuple[AgentConfigurable, str, str]:
    """Resolve the dev user and build the parent configurable a direct run needs.

    Returns (configurable, user_id, conversation_id). The conversation_id is
    minted when absent; passing the same one across calls reuses the derived
    agent thread, so multi-turn behavior is testable.
    """
    user_doc = await require_dev_user(email)
    user_id = user_doc.id
    cid = conversation_id or str(uuid4())
    user: AgentUserContext = {
        "user_id": user_id,
        "email": user_doc.email,
        "name": user_doc.name,
    }
    user_preferences, writing_style = onboarding_preferences(user_doc.onboarding)
    config = await build_agent_config(
        conversation_id=cid,
        user=user,
        agent_name=agent_name,
        # A direct dev run is top-level, so it resolves its own lane. Before
        # this it resolved none at all, which is why the dev harness quietly
        # ran a different model than real chat.
        role=AgentRole.EXECUTOR,
        user_preferences=user_preferences,
        writing_style=writing_style,
    )
    return cast(AgentConfigurable, config["configurable"]), user_id, cid


def _reject_pause(outcome: SubagentOutcome, agent_name: str) -> None:
    """Fail loud when a direct run parks on a HIL approval.

    A direct run has no stream and therefore no approval channel to answer the
    interrupt on, so ``outcome.text`` is meaningless — returning it would hand
    back an empty message as if it were the agent's answer.
    """
    if outcome.paused:
        raise create_error(
            message=f"{agent_name} paused for approval",
            why="A direct run has no approval channel to resume the HIL interrupt on",
            fix="Drive the run through the chat endpoint, or use a task that gates no tools",
            status_code=409,
        )


async def run_executor_direct(
    email: str, task: str, conversation_id: str | None = None
) -> DevAgentRunResponse:
    """Run the executor agent directly with a task, returning its final message."""
    configurable, user_id, cid = await _dev_base_configurable(
        email, conversation_id, "executor_agent"
    )
    ctx, error = await prepare_executor_execution(task=task, configurable=configurable)
    if ctx is None:
        raise create_error(
            message="Executor agent unavailable",
            why=error or "prepare_executor_execution returned no context",
            status_code=503,
        )
    outcome = await execute_subagent_stream(ctx)
    _reject_pause(outcome, ctx.agent_name)
    log.info(
        f"{LogTag.DEV} ran executor directly",
        email=email,
        user_id=user_id,
        conversation_id=cid,
        response_length=len(outcome.text),
    )
    return DevAgentRunResponse(
        user_id=user_id,
        conversation_id=cid,
        thread_id=ctx.configurable.get("thread_id", ""),
        agent=ctx.agent_name,
        message=outcome.text,
    )


async def run_subagent_direct(
    email: str, subagent_id: str, task: str, conversation_id: str | None = None
) -> DevAgentRunResponse:
    """Run one subagent directly with a task, returning its final message."""
    configurable, user_id, cid = await _dev_base_configurable(email, conversation_id, "dev_direct")
    ctx, integration_metadata, error = await prepare_subagent_execution(
        subagent_id=subagent_id,
        task=task,
        configurable=configurable,
    )
    if ctx is None:
        raise create_error(
            message=f"Cannot run subagent {subagent_id!r}",
            why=error or "prepare_subagent_execution returned no context",
            fix="GET /api/v1/dev/subagents lists the runnable ids",
            status_code=400,
        )
    outcome = await execute_subagent_stream(ctx, integration_metadata=integration_metadata)
    _reject_pause(outcome, ctx.agent_name)
    log.info(
        f"{LogTag.DEV} ran subagent directly",
        email=email,
        user_id=user_id,
        subagent=ctx.agent_name,
        conversation_id=cid,
        response_length=len(outcome.text),
    )
    return DevAgentRunResponse(
        user_id=user_id,
        conversation_id=cid,
        thread_id=ctx.configurable.get("thread_id", ""),
        agent=ctx.agent_name,
        message=outcome.text,
    )
