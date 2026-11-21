"""Day-zero hello: GAIA's first text after a user links a chat platform.

Enqueued from PlatformLinkService.link_account on a brand-new chat link. One structured
model call writes a short greeting, posted into the platform DM through
post_to_platform_chat. Fires once per user, ever.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from app.agents.core.background.platform_chat import ProactiveMessage, post_to_platform_chat
from app.agents.llm.client import ainvoke_structured, metered_config
from app.agents.prompts.briefing_prompts import build_day_zero_hello_prompt
from app.constants.notifications import ProactiveMessageClass
from app.constants.platform_links import DAY_ZERO_HELLO_TASK
from app.db.repositories.briefing_state import briefing_state_repository
from app.db.repositories.users import user_repository
from app.models.chat_models import ConversationSource
from app.services.analytics_service import capture
from app.services.briefing.clock import resolve_clock
from app.services.briefing.goals import format_goal_block, stated_goals
from app.services.briefing.run_times import next_brief_lands, user_brief_slots
from app.services.delivery.chat_channel import channel_for
from app.services.outbound_delivery import OutboundResult
from app.utils.auth_utils import build_user_context
from app.utils.timezone import as_utc
from app.utils.user_display import display_first_name
from app.workers.task_envelope import ArqJobContext
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingDayZeroHelloSent
from shared.py.conversation_wire import NEW_MESSAGE_BREAKER
from shared.py.wide_events import UserContext, log, wide_task

# Only greet accounts young enough that a first hello still makes sense; an old
# account linking a platform for the first time is not a day-zero moment.
DAY_ZERO_MAX_ACCOUNT_AGE_DAYS = 14


class HelloBubbles(BaseModel):
    """The model's hello: one or two chat bubbles, in send order."""

    bubbles: list[str] = Field(min_length=1, max_length=2)


async def send_day_zero_hello(ctx: ArqJobContext, user_id: str, platform: str) -> str:
    """Send GAIA's first hello to a freshly-linked chat platform, once per user.

    Guards (all must hold): no prior day_zero_hello flag, account created within
    DAY_ZERO_MAX_ACCOUNT_AGE_DAYS, and the platform is still linked. A failing guard is a
    normal skip.
    """
    async with wide_task(DAY_ZERO_HELLO_TASK, user=UserContext(id=user_id)):
        log.set(platform=platform)
        source = ConversationSource.coerce(platform)
        if source is None:
            log.set(skipped="unsupported_platform")
            return f"skip {user_id}: unsupported platform {platform}"

        user = await user_repository.get(user_id)
        if user is None:
            log.set(skipped="unknown_user")
            return f"skip {user_id}: unknown user"

        state = await briefing_state_repository.state_for(user_id)
        if state.day_zero_hello is not None:
            log.set(skipped="already_sent")
            return f"skip {user_id}: day-zero hello already sent"

        created_at = as_utc(user.created_at)
        account_too_old = created_at is None or datetime.now(UTC) - created_at > timedelta(
            days=DAY_ZERO_MAX_ACCOUNT_AGE_DAYS
        )
        if account_too_old:
            log.set(skipped="account_too_old")
            return f"skip {user_id}: account older than {DAY_ZERO_MAX_ACCOUNT_AGE_DAYS} days"

        # The hello greets the account the user just connected, whatever their order says.
        channel = channel_for(user, source)
        if channel is None:
            log.set(skipped="not_linked")
            return f"skip {user_id}: {platform} not linked"

        goals = await stated_goals(user_id)
        has_goal = bool(goals)
        prompt = build_day_zero_hello_prompt(
            first_name=display_first_name(user) or "there",
            goal_block=format_goal_block(goals),
            has_goal=has_goal,
            first_brief=next_brief_lands(
                user_brief_slots(user, state.schedule),
                resolve_clock(user.timezone).now_local,
            ),
        )
        auth_user = build_user_context(user, auth_provider=None)
        hello = await ainvoke_structured(
            HelloBubbles, prompt, label=DAY_ZERO_HELLO_TASK, config=metered_config(user_id)
        )
        bubbles = [bubble.strip() for bubble in hello.bubbles if bubble.strip()]

        result = await post_to_platform_chat(
            user=auth_user,
            channel=channel,
            message=ProactiveMessage(
                notice_id=f"day-zero-hello:{user_id}",
                text=NEW_MESSAGE_BREAKER.join(bubbles),
                origin="day-zero hello",
                message_class=ProactiveMessageClass.USER_TRIGGERED,
            ),
        )
        if result is not OutboundResult.PUBLISHED:
            # Nothing landed, so leave the once-ever flag unset: a later relink can still greet them.
            log.set(skipped="publish_skipped")
            return f"skip {user_id}: publish skipped ({platform})"

        await briefing_state_repository.mark_day_zero_hello_sent(user_id, platform)
        capture(UserId(user_id), BriefingDayZeroHelloSent(platform=platform, has_goal=has_goal))
        log.set(bubbles=len(bubbles), has_goal=has_goal)
        return f"sent day-zero hello to {user_id} on {platform}"
