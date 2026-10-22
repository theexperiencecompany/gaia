"""Day-zero hello: GAIA's first text after a user links a chat platform.

Enqueued from PlatformLinkService.link_account on a brand-new chat link. One silent
agent turn writes a short greeting, posted into the platform DM through
post_to_platform_chat. Fires once per user, ever.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4

from app.agents.core.background.platform_chat import post_to_platform_chat
from app.agents.prompts.briefing_prompts import build_day_zero_hello_prompt
from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.notifications import ProactiveMessageClass
from app.db.repositories.users import user_repository
from app.models.chat_models import ConversationSource
from app.services.analytics_service import capture
from app.services.briefing import context
from app.services.briefing.service import json_blocks, run_silent_turn
from app.services.delivery.chat_channel import pick_chat_channel
from app.services.outbound_delivery import OutboundResult
from app.services.platform_link_service import linked_platforms_of
from app.utils.auth_utils import build_user_context
from app.utils.user_display import display_first_name
from app.workers.task_envelope import ArqJobContext
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingDayZeroHelloSent
from shared.py.wide_events import UserContext, log, wide_task

# Only greet accounts young enough that a first hello still makes sense; an old
# account linking a platform for the first time is not a day-zero moment.
DAY_ZERO_MAX_ACCOUNT_AGE_DAYS = 14

# Extracts a ```json fenced block (or a bare array) from the agent's final text.


class DayZeroHelloError(Exception):
    """The agent did not produce a valid bubble array — the run failed."""


def _parse_bubbles(raw: str) -> list[str]:
    """Extract the JSON array of chat bubbles from the agent output (fail loud)."""
    for block in json_blocks(raw):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list) and all(isinstance(b, str) for b in data):
            bubbles = [b.strip() for b in data if b.strip()]
            if bubbles:
                return bubbles
    raise DayZeroHelloError(
        f"No valid bubble array in agent output (first 300 chars): {raw[:300]!r}"
    )


async def send_day_zero_hello(ctx: ArqJobContext, user_id: str, platform: str) -> str:
    """Send GAIA's first hello to a freshly-linked chat platform, once per user.

    Guards (all must hold): no prior day_zero_hello flag, account created within
    DAY_ZERO_MAX_ACCOUNT_AGE_DAYS, and the platform is still linked. A failing guard is a
    normal skip; only a real broker failure raises.
    """
    async with wide_task("send_day_zero_hello", user=UserContext(id=user_id)):
        log.set(platform=platform)
        source = ConversationSource.coerce(platform)
        if source is None:
            log.set(skipped="unsupported_platform")
            return f"skip {user_id}: unsupported platform {platform}"

        user = await user_repository.get(user_id)
        if user is None:
            log.set(skipped="unknown_user")
            return f"skip {user_id}: unknown user"

        if user.day_zero_hello is not None:
            log.set(skipped="already_sent")
            return f"skip {user_id}: day-zero hello already sent"

        created_at = user.created_at
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        account_too_old = created_at is None or datetime.now(UTC) - created_at > timedelta(
            days=DAY_ZERO_MAX_ACCOUNT_AGE_DAYS
        )
        if account_too_old:
            log.set(skipped="account_too_old")
            return f"skip {user_id}: account older than {DAY_ZERO_MAX_ACCOUNT_AGE_DAYS} days"

        # The platform just linked, regardless of priority or preferences: the
        # hello greets the account the user connected.
        channel = pick_chat_channel([source.value], linked_platforms_of(user), {})
        if channel is None:
            log.set(skipped="not_linked")
            return f"skip {user_id}: {platform} not linked"

        goal_block, has_goal = await context.format_goal_block(user_id, user)
        prompt = build_day_zero_hello_prompt(
            first_name=display_first_name(user) or "there",
            goal_block=goal_block,
            has_goal=has_goal,
        )
        auth_user = build_user_context(user, auth_provider=None)
        reply = await run_silent_turn(
            auth_user,
            prompt,
            conversation_id=f"dayzero-{user_id}-{uuid4().hex[:6]}",
            source="day_zero_hello",
        )
        bubbles = _parse_bubbles(reply)

        result = await post_to_platform_chat(
            user=auth_user,
            channel=channel,
            text=NEW_MESSAGE_BREAKER.join(bubbles),
            origin="day-zero hello",
            message_class=ProactiveMessageClass.USER_TRIGGERED,
        )
        if result is not OutboundResult.PUBLISHED:
            # Nothing landed, so leave the once-ever flag unset: a later relink can
            # still greet them. A broker failure is a real error worth retrying.
            if result is OutboundResult.FAILED:
                raise DayZeroHelloError(
                    f"day-zero hello publish failed for {user_id} on {platform}"
                )
            log.set(skipped="publish_skipped")
            return f"skip {user_id}: publish skipped ({platform})"

        await user_repository.mark_day_zero_hello_sent(user_id, platform)
        capture(UserId(user_id), BriefingDayZeroHelloSent(platform=platform, has_goal=has_goal))
        log.set(bubbles=len(bubbles), has_goal=has_goal)
        return f"sent day-zero hello to {user_id} on {platform}"
