"""The production turn of a comms attempt: its run config and the system prompt, context and clock around its inputs."""

from typing import Literal, cast

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.constants import CONF

from app.agents.core.background.todo_run_delivery import write_up_note
from app.agents.core.messages import MessageScope, build_turn_context
from app.agents.llm.lane import AgentRole
from app.agents.prompts.comms_prompts import PLATFORM_DELIVERY_NOTE
from app.constants.chat import ConversationSource
from app.constants.conversation import WORKFLOW_RUN_REQUEST
from app.db.repositories.conversations import conversation_repository
from app.helpers.agent_helpers import (
    AgentIdentity,
    AgentLane,
    AgentTurn,
    background_authorization,
    build_agent_config,
)
from app.models.agent_config import AgentConfigurable, StepTurnRef
from app.models.agent_models import agent_user_context
from app.models.conversation_log_models import (
    Batch,
    StepClaim,
    UserMessage,
    WorkFinished,
    WorkflowFired,
    WorkflowRun,
)
from app.services.chat.workspace import schedule_last_active_touch
from app.services.conversation.comms_runner import CommsTurn
from app.services.conversation.reply_analytics import spoken_context
from app.services.conversation.runtime import runtime_ports
from app.services.conversation.todo_wake import todo_runs_reported
from app.services.delivery.presence import presence_before
from app.utils.auth_utils import require_owner
from app.utils.user_preferences_utils import onboarding_preferences
from shared.py.analytics.catalog.agents import AgentRunStarted
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.context import AnalyticsContext

_COMMS_AGENT = "comms_agent"


async def build_comms_turn(claim: StepClaim, batch: Batch) -> CommsTurn:
    """Build the config and turn context of an attempt on batch, the way a live chat turn builds them."""
    user = await require_owner(claim.user_id)
    said = [logged.entry for logged in batch.waking if isinstance(logged.entry, UserMessage)]
    fired = _workflow_run(batch)
    texts = [message.text for message in said]
    query = WORKFLOW_RUN_REQUEST.format(title=fired.workflow.title) if fired else "\n\n".join(texts)
    mode: Literal["interactive", "background"] = "interactive"
    if fired is not None:
        user, mode = user.with_timezone(fired.timezone), "background"
    source = _source(said)
    pinned = next((message for message in reversed(said) if message.selected_tool), None)
    presence = await presence_before(claim.user_id, said[-1] if said else None)
    if said:
        schedule_last_active_touch(claim.user_id, claim.conversation_id)
    todo_id = await conversation_repository.get_todo_id(
        claim.conversation_id, user_id=claim.user_id
    )
    context = await build_turn_context(
        query,
        MessageScope(
            user_id=claim.user_id,
            user_name=user.name,
            user_dict=user,
            conversation_id=claim.conversation_id,
            source=source,
            active_todo_id=todo_id,
            execution_mode=mode,
            presence=presence,
            opens_thread=batch.start == 1,
        ),
    )
    user_preferences, writing_style = onboarding_preferences(user.onboarding)
    config = await build_agent_config(
        identity=AgentIdentity(
            conversation_id=claim.conversation_id,
            user=agent_user_context(user),
            agent_name=_COMMS_AGENT,
        ),
        lane=AgentLane(role=AgentRole.COMMS),
        turn=AgentTurn(
            selected_tool=pinned.selected_tool if pinned else None,
            tool_category=pinned.tool_category if pinned else None,
            active_todo_id=todo_id,
            execution_mode=mode,
            source=source,
            user_messages=_workflow_authorization(fired) if fired else texts,
            user_request=query,
            user_preferences=user_preferences,
            writing_style=writing_style,
            workflow_id=fired.workflow.id if fired else None,
            presence=presence,
        ),
    )
    configurable = cast(AgentConfigurable, config[CONF])
    configurable["conversation_step"] = step_turn_ref(claim, batch)
    if fired is not None:
        _stamp_workflow_run(configurable, fired)
    return CommsTurn(
        config=config,
        opening=[*context.chain, *(m for m in (context.presence,) if m is not None)],
        closing=[*await _delivery_note(claim, batch), context.clock],
        analytics=_analytics(said, fired),
        run_started=AgentRunStarted(
            agent="comms",
            mode=mode,
            conversation_id=claim.conversation_id,
            trigger_type=fired.trigger.type if fired else None,
            source=source,
        ),
        state={
            "query": query,
            "intent": query,
            "memory_user_id": claim.user_id,
            "conversation_id": claim.conversation_id,
            "integration_usernames": {},
            **({"active_todo_id": todo_id} if todo_id else {}),
        },
    )


async def _delivery_note(claim: StepClaim, batch: Batch) -> list[AnyMessage]:
    """Tell a reply that reports a todo's run how to write it up, and one that reports a workflow's work that it is read as plain text."""
    if not any(isinstance(logged.entry, WorkFinished) for logged in batch.waking):
        return []
    reported = await todo_runs_reported(
        runtime_ports().log, claim.conversation_id, claim.user_id, batch
    )
    if reported:
        return [HumanMessage(content=await write_up_note(run)) for _work, run in reported]
    if not await conversation_repository.is_workflow_execution(claim.conversation_id):
        return []
    return [HumanMessage(content=PLATFORM_DELIVERY_NOTE)]


def _workflow_run(batch: Batch) -> WorkflowRun | None:
    """Return the workflow run a batch answers; a fire is always batched alone."""
    first = batch.waking[0].entry
    return first.run if isinstance(first, WorkflowFired) else None


def _workflow_authorization(run: WorkflowRun) -> list[str]:
    """Return what authorizes the run's gated calls: its workflow's own title and description."""
    return background_authorization(
        [],
        execution_mode="background",
        workflow_title=run.workflow.title,
        workflow_description=run.workflow.description,
    )


def _stamp_workflow_run(configurable: AgentConfigurable, run: WorkflowRun) -> None:
    """Carry the fire onto the run: its record, its reservation, and how its result is delivered.

    The executor inherits all of it; its tool calls land in the run record keyed by the execution id.
    """
    configurable["stream_id"] = run.execution_id
    configurable["workflow_id"] = run.workflow.id
    configurable["workflow_title"] = run.workflow.title
    configurable["workflow_notify_on_completion"] = run.trigger.workflow_notify_on_completion
    configurable["playbook_fallback"] = run.trigger.playbook_fallback
    configurable["executor_lock_reservation"] = run.reservation


#: Work that finished, or an integration the work waited on, wakes comms with no one asking.
_UNPROMPTED = AnalyticsContext(
    attribution=Attribution(actor=Actor.AGENT, trigger=Trigger.SYSTEM, surface=EntrySurface.WORKER)
)


def _analytics(said: list[UserMessage], fired: WorkflowRun | None) -> AnalyticsContext:
    """Return who caused the attempt: the user who spoke last, the workflow's fire, else the work itself."""
    if said:
        return spoken_context(said[-1])
    if fired is not None:
        return AnalyticsContext(attribution=fired.attribution)
    return _UNPROMPTED


def _source(said: list[UserMessage]) -> str:
    """Answer on the surface of the newest message; work with no message behind it answers in the background."""
    return said[-1].surface.value if said else ConversationSource.BACKGROUND.value


def step_turn_ref(claim: StepClaim, batch: Batch) -> StepTurnRef:
    """Return what the attempt's run and the work it dispatches carry of the attempt."""
    return {
        "epoch": claim.epoch,
        "batch_start": batch.start,
        "cause_through": batch.end,
        "answers": [
            logged.entry.id
            for logged in batch.waking
            if isinstance(logged.entry, UserMessage | WorkflowFired)
        ],
    }
