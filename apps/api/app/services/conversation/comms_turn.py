"""The production turn of a comms attempt: its run config and the system prompt, context and clock around its inputs."""

from typing import cast

from langgraph.constants import CONF

from app.agents.core.messages import MessageScope, build_turn_context
from app.agents.llm.lane import AgentRole
from app.constants.chat import ConversationSource
from app.db.repositories.conversations import conversation_repository
from app.helpers.agent_helpers import (
    AgentIdentity,
    AgentLane,
    AgentTurn,
    build_agent_config,
)
from app.models.agent_config import AgentConfigurable, StepTurnRef
from app.models.agent_models import agent_user_context
from app.models.conversation_log_models import Batch, StepClaim, UserMessage
from app.services.conversation.comms_runner import CommsTurn
from app.services.delivery.presence import read_presence
from app.utils.auth_utils import require_owner
from app.utils.user_preferences_utils import onboarding_preferences

_COMMS_AGENT = "comms_agent"


async def build_comms_turn(claim: StepClaim, batch: Batch) -> CommsTurn:
    """Build the config and turn context of an attempt on batch, the way a live chat turn builds them."""
    user = await require_owner(claim.user_id)
    said = [logged.entry for logged in batch.waking if isinstance(logged.entry, UserMessage)]
    texts = [message.text for message in said]
    query = "\n\n".join(texts)
    source = _source(said)
    presence = await read_presence(claim.user_id)
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
            active_todo_id=todo_id,
            execution_mode="interactive",
            source=source,
            user_messages=texts,
            user_request=query,
            user_preferences=user_preferences,
            writing_style=writing_style,
            presence=presence,
        ),
    )
    configurable = cast(AgentConfigurable, config[CONF])
    configurable["conversation_step"] = step_turn_ref(claim, batch)
    return CommsTurn(
        config=config,
        opening=[*context.chain, *(m for m in (context.presence,) if m is not None)],
        closing=[context.clock],
        state={
            "query": query,
            "intent": query,
            "memory_user_id": claim.user_id,
            "conversation_id": claim.conversation_id,
            "integration_usernames": {},
            **({"active_todo_id": todo_id} if todo_id else {}),
        },
    )


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
            logged.entry.id for logged in batch.waking if isinstance(logged.entry, UserMessage)
        ],
    }
