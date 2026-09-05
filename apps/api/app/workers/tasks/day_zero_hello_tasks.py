"""Day-zero hello: GAIA's first text after a user links a chat platform.

Enqueued from ``PlatformLinkService.link_account`` on a brand-new chat link. One
silent agent turn writes a short, goal-grounded greeting; it is delivered to that
one platform and mirrored into its bot conversation so the user's reply lands
with context. Guarded to fire once per user, ever.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import re
from typing import cast
from uuid import uuid4

from app.agents.core.agent import AgentRunOptions, call_agent_silent
from app.agents.prompts.briefing_prompts import build_day_zero_hello_prompt
from app.db.repositories.users import user_repository
from app.models.chat_models import ConversationSource
from app.models.message_models import MessageDict, MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser
from app.services.briefing import chat_sync, context
from app.services.outbound_delivery import OutboundResult, publish_outbound_message
from app.services.platform_link_service import PlatformLinkService
from app.services.user_service import get_user_by_id
from app.utils.analytics import track
from shared.py.wide_events import UserContext, log, wide_task

# Only greet accounts young enough that a first hello still makes sense; an old
# account linking a platform for the first time is not a day-zero moment.
DAY_ZERO_MAX_ACCOUNT_AGE_DAYS = 14

# Extracts a ```json fenced block (or a bare array) from the agent's final text.
_JSON_FENCE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)


class DayZeroHelloError(Exception):
    """The agent did not produce a valid bubble array — the run failed."""


def _parse_bubbles(raw: str) -> list[str]:
    """Extract the JSON array of chat bubbles from the agent output (fail loud)."""
    candidates = _JSON_FENCE.findall(raw) or [raw]
    for block in candidates:
        block = block.strip()
        if not block:
            continue
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


async def _run_silent(user: dict, prompt: str) -> str:
    """One silent agent turn on a fresh thread; returns the final text.

    Mirrors the briefing service's silent-run plumbing.
    """
    request = MessageRequestWithHistory(
        message=prompt,
        messages=[MessageDict(role="user", content=prompt)],
        fileIds=[],
        fileData=[],
        selectedTool=None,
        selectedWorkflow=None,
    )
    user_data = {
        "user_id": user["user_id"],
        "name": user.get("name"),
        "email": user.get("email"),
        "timezone": user.get("timezone"),
    }
    conversation_id = f"dayzero-{user['user_id']}-{uuid4().hex[:6]}"
    run = await call_agent_silent(
        request=request,
        conversation_id=conversation_id,
        user=cast(AuthenticatedUser, user_data),
        options=AgentRunOptions(
            trigger_context={"execution_mode": "background"},
            source="day_zero_hello",
        ),
    )
    return run.message


def _first_name(user: dict) -> str:
    name = (user.get("name") or "").strip()
    return name.split()[0] if name else "there"


async def send_day_zero_hello(ctx: dict, user_id: str, platform: str) -> str:
    """Send GAIA's first hello to a freshly-linked chat platform, once per user.

    Guards (all must hold): no prior ``day_zero_hello`` flag, account created
    within ``DAY_ZERO_MAX_ACCOUNT_AGE_DAYS``, and the platform is still linked.
    A guard failing is a normal skip; only a real broker failure raises.
    """
    async with wide_task("send_day_zero_hello", user=UserContext(id=user_id)):
        log.set(platform=platform)
        source = ConversationSource.coerce(platform)
        if source is None:
            log.set(skipped="unsupported_platform")
            return f"skip {user_id}: unsupported platform {platform}"

        user = await get_user_by_id(user_id)
        if not user:
            log.set(skipped="unknown_user")
            return f"skip {user_id}: unknown user"
        user["user_id"] = user_id

        if user.get("day_zero_hello"):
            log.set(skipped="already_sent")
            return f"skip {user_id}: day-zero hello already sent"

        created_at = user.get("created_at")
        account_too_old = created_at is None or datetime.now(UTC) - created_at > timedelta(
            days=DAY_ZERO_MAX_ACCOUNT_AGE_DAYS
        )
        if account_too_old:
            log.set(skipped="account_too_old")
            return f"skip {user_id}: account older than {DAY_ZERO_MAX_ACCOUNT_AGE_DAYS} days"

        linked = await PlatformLinkService.get_linked_platforms(user_id)
        if platform not in linked:
            log.set(skipped="not_linked")
            return f"skip {user_id}: {platform} not linked"

        goal_block, has_goal = await context.format_goal_block(user_id, user)
        prompt = build_day_zero_hello_prompt(
            first_name=_first_name(user), goal_block=goal_block, has_goal=has_goal
        )
        bubbles = _parse_bubbles(await _run_silent(user, prompt))

        result = await publish_outbound_message(source, user_id, bubbles)
        if result is not OutboundResult.PUBLISHED:
            # Nothing landed, so leave the once-ever flag unset: a later relink can
            # still greet them. A broker failure is a real error worth retrying.
            if result is OutboundResult.FAILED:
                raise DayZeroHelloError(
                    f"day-zero hello publish failed for {user_id} on {platform}"
                )
            log.set(skipped="publish_skipped")
            return f"skip {user_id}: publish skipped ({platform})"

        await chat_sync.persist_bot_message(user_id, user, platform, bubbles)
        await user_repository.mark_day_zero_hello_sent(user_id, platform)
        track(user_id, "day_zero_hello_sent", {"platform": platform, "has_goal": has_goal})
        log.set(bubbles=len(bubbles), has_goal=has_goal)
        return f"sent day-zero hello to {user_id} on {platform}"
