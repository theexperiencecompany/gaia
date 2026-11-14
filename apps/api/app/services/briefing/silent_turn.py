"""One silent background agent turn: the briefing runs voice through it, as does the day-zero hello."""

from uuid import uuid4

from app.agents.core.agent import AgentRunOptions, call_agent_silent
from app.models.message_models import MessageDict, MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser
from app.services.briefing.context import UserClock


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


async def run_briefing_turn(
    user: AuthenticatedUser, clock: UserClock, prompt: str, conversation_key: str
) -> str:
    """One silent agent turn on a fresh per-run thread, in the user's timezone."""
    # Fresh thread per RUN, not per day: a same-day retry (or rerun) on a shared
    # thread would resume the failed attempt's polluted state via the
    # checkpointer, and stale turns would masquerade as today's context.
    return await run_silent_turn(
        user.with_timezone(clock.tz.key),
        prompt,
        conversation_id=(
            f"briefing-{conversation_key}-{user.user_id}-{clock.date_str}-{uuid4().hex[:6]}"
        ),
        source="briefing",
    )
