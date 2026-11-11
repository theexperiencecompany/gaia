"""One silent background agent turn on a thread GAIA names: the day-zero hello runs through it."""

from app.agents.core.agent import AgentRunOptions, call_agent_silent
from app.models.message_models import MessageDict, MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser


async def run_silent_turn(
    user: AuthenticatedUser, prompt: str, *, conversation_id: str, source: str
) -> str:
    """Run one silent background agent turn on the given thread; return its final text."""
    # construct_langchain_messages reads the human turn from `messages`
    # (`message` alone is not consulted when no workflow/tool is selected).
    request = MessageRequestWithHistory(
        message=prompt,
        messages=[MessageDict(role="user", content=prompt)],
    )
    run = await call_agent_silent(
        request=request,
        conversation_id=conversation_id,
        user=user,
        options=AgentRunOptions(trigger_context={"execution_mode": "background"}, source=source),
    )
    return run.message
