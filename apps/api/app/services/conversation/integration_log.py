"""An integration the user must connect, as conversation log entries: the need, and the connect that continues the work.

The connect wakes the step, which carries on with the waiting work; no client sends a
stand-in "I just connected X" message.
"""

from datetime import UTC, datetime

from app.constants.conversation import INTEGRATION_NEED_WINDOW
from app.db.repositories.conversation_log import conversation_log_repository
from app.models.agent_config import StepTurnRef
from app.models.conversation_log_models import IntegrationConnected, IntegrationNeeded
from app.services.conversation.log import accept
from app.services.conversation.runtime import runtime_ports


async def record_integration_needed(
    step: StepTurnRef,
    conversation_id: str,
    user_id: str,
    integration_id: str,
    integration_name: str,
) -> None:
    """Log that the step attempt's work waits on the user connecting integration_id; once per attempt."""
    entry = IntegrationNeeded(
        id=f"integration:{integration_id}:{step['epoch']}:{step['cause_through']}",
        integration_id=integration_id,
        integration_name=integration_name,
    )
    await accept(runtime_ports(), conversation_id, user_id, entry)


async def continue_after_connect(user_id: str, integration_id: str) -> int:
    """Wake every step-run conversation whose work waits on integration_id; return how many were woken."""
    since = datetime.now(UTC) - INTEGRATION_NEED_WINDOW
    found = await conversation_log_repository.list_integration_entries(
        user_id=user_id, integration_id=integration_id, since=since
    )
    answered = {
        logged.entry.needed_id
        for _conversation_id, logged in found
        if isinstance(logged.entry, IntegrationConnected)
    }
    open_needs = [
        (conversation_id, logged.entry)
        for conversation_id, logged in found
        if isinstance(logged.entry, IntegrationNeeded) and logged.entry.id not in answered
    ]
    ports = runtime_ports()
    for conversation_id, need in open_needs:
        connected = IntegrationConnected(
            id=f"{need.id}:connected",
            integration_id=need.integration_id,
            integration_name=need.integration_name,
            needed_id=need.id,
        )
        await accept(ports, conversation_id, user_id, connected)
    return len(open_needs)
