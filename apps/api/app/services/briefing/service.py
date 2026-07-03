"""BriefingService — the daily/weekly run pipeline.

Deterministic curation and context-gathering happen here; the agent only turns
the gathered context into one structured ``BriefingPayload`` (forced via prompt
contract, validated on the way out — invalid output fails the run loudly and
stores nothing). Persistence precedes delivery so the dashboard never misses a
brief that reached a channel.
"""

from datetime import UTC, datetime, timedelta
import json
import re
from uuid import uuid4

from bson import ObjectId

from app.agents.prompts.briefing_prompts import (
    build_daily_briefing_prompt,
    build_overnight_work_prompt,
    build_weekly_digest_prompt,
)
from app.constants.briefing import (
    BOOTSTRAP_GRACE_DAYS,
    BRIEFING_KIND_DAILY,
    BRIEFING_KIND_WEEKLY,
    MINUTES_SAVED_PER_GAIA_TODO,
    hue_for_day,
)
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.constants.todos import MAX_PENDING_PROPOSALS, gaia_assigned_filter
from app.db.mongodb.collections import todos_collection, users_collection
from app.models.briefing_models import BriefingKind, BriefingModel, BriefingPayload
from app.models.message_models import MessageDict, MessageRequestWithHistory
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
    RedirectConfig,
)
from app.models.todo_models import ExecutionStatus
from app.services.briefing import context, repository
from app.services.briefing.badges import check_and_award_badges
from app.services.briefing.context import UserClock
from app.services.notification_service import notification_service
from app.services.todos import activity
from app.services.todos.gaia_todo_lifecycle import (
    expire_stale_proposals,
    get_rejection_strikes_summary,
)
from app.services.user_service import get_user_by_id
from app.utils.analytics import track
from shared.py.wide_events import log

# Extracts a ```json fenced block (or a bare object) from the agent's final text.
_JSON_FENCE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)

# Marker on the user doc while the existing-user bootstrap interview is pending.
BOOTSTRAP_FIELD = "briefing_bootstrap"


class BriefingGenerationError(Exception):
    """The agent did not produce a valid BriefingPayload — the run failed."""


def _parse_payload(raw: str) -> BriefingPayload:
    """Extract and validate the single BriefingPayload from the agent output.

    ``call_agent_silent`` swallows its own errors into a plain string, so a failed
    run lands here and fails validation — which is exactly the loud failure we
    want (no partial briefing is stored).
    """
    candidates = _JSON_FENCE.findall(raw) or [raw]
    for block in candidates:
        block = block.strip()
        if not block:
            continue
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "headline" in data:
            return BriefingPayload.model_validate(data)
    raise BriefingGenerationError(
        f"No valid BriefingPayload in agent output (first 300 chars): {raw[:300]!r}"
    )


async def _run_silent(user: dict, clock: UserClock, prompt: str, conversation_key: str) -> str:
    """One silent agent turn on a fresh per-day thread; returns the final text."""
    # Inline import breaks the agent<->workflow import cycle (same pattern the
    # worker uses for call_agent_silent).
    from app.agents.core.agent import call_agent_silent

    # construct_langchain_messages reads the human turn from `messages`
    # (`message` alone is not consulted when no workflow/tool is selected).
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
        "timezone": clock.tz.key,
    }
    # Fresh thread per RUN, not per day: a same-day retry (or rerun) on a shared
    # thread would resume the failed attempt's polluted state via the
    # checkpointer, and stale turns would masquerade as today's context.
    conversation_id = (
        f"briefing-{conversation_key}-{user['user_id']}-{clock.date_str}-{uuid4().hex[:6]}"
    )
    message, _ = await call_agent_silent(
        request=request,
        conversation_id=conversation_id,
        user=user_data,
        trigger_context={"execution_mode": "background"},
        source="briefing",
    )
    return message


async def _generate_payload(
    user: dict, clock: UserClock, prompt: str, kind: BriefingKind
) -> BriefingPayload:
    return _parse_payload(await _run_silent(user, clock, prompt, conversation_key=kind))


def _format_curation(expired_titles: list[str]) -> str:
    if not expired_titles:
        return "Nothing needed clearing — the list was already tidy."
    joined = "; ".join(expired_titles)
    return f"Expired {len(expired_titles)} stale proposal(s) the user never acted on: {joined}."


def _format_awards(badge_labels: list[str]) -> str:
    if not badge_labels:
        return ""
    return (
        "\n## BADGES EARNED THIS RUN (mention them warmly, once)\n" + ", ".join(badge_labels) + "\n"
    )


def _format_week(completed: context.CompletedWork) -> str:
    gaia_n, user_n = len(completed.gaia), len(completed.user)
    lines = [f"GAIA completed {gaia_n} todo(s); you completed {user_n}."]
    if completed.gaia:
        lines.append(
            "GAIA shipped:\n"
            + "\n".join(f"- {d.get('title', 'untitled')}" for d in completed.gaia[:15])
        )
    if completed.user:
        lines.append(
            "You finished:\n"
            + "\n".join(f"- {d.get('title', 'untitled')}" for d in completed.user[:15])
        )
    return "\n\n".join(lines)


def _delivery_body(payload: BriefingPayload) -> str:
    top: list[str] = []
    for section in payload.sections:
        for item in section.items:
            top.append(item.text)
            if len(top) >= 3:
                break
        if len(top) >= 3:
            break
    parts = [payload.lede]
    if top:
        parts.append("\n".join(f"- {t}" for t in top))
    return "\n\n".join(parts)


async def _pending_proposal_actions(user_id: str) -> list[dict[str, str]]:
    """Approve/Dismiss button pairs for the user's pending proposals (top 3).

    callback_data matches the Telegram callback contract
    (``todo_approve:<id>`` / ``todo_dismiss:<id>``) handled by the bot adapter.
    """
    query = {
        "user_id": user_id,
        "execution_status": ExecutionStatus.PROPOSED.value,
        **gaia_assigned_filter(),
    }
    actions: list[dict[str, str]] = []
    async for doc in todos_collection.find(query, {"title": 1}).limit(MAX_PENDING_PROPOSALS):
        title = doc.get("title", "proposal")
        short = title if len(title) <= 24 else f"{title[:23]}…"
        todo_id = str(doc["_id"])
        actions.append({"label": f"Approve: {short}", "callback_data": f"todo_approve:{todo_id}"})
        actions.append({"label": f"Dismiss: {short}", "callback_data": f"todo_dismiss:{todo_id}"})
    return actions


async def _deliver(
    user_id: str, briefing: BriefingModel, payload: BriefingPayload, notification_kind: str
) -> list[str]:
    """Fan out the briefing via the notification orchestrator (in-app + platforms).

    ``metadata.kind`` selects the email template and ``content.rich_content``
    carries the full payload the email adapter renders — both are the delivery
    contract the channels layer keys off (without them email falls back to the
    plain template). ``metadata.todo_actions`` renders as native Approve/Dismiss
    buttons on platforms that support them (Telegram inline keyboards) so the
    morning tap works from bed.
    """
    todo_actions = await _pending_proposal_actions(user_id)
    record = await notification_service.create_notification(
        NotificationRequest(
            user_id=user_id,
            source=NotificationSourceEnum.BACKGROUND_JOB,
            type=NotificationType.INFO,
            priority=2,
            content=NotificationContent(
                title=payload.headline,
                body=_delivery_body(payload),
                rich_content=payload.model_dump(),
                actions=[
                    NotificationAction(
                        type=ActionType.REDIRECT,
                        label="Open briefing",
                        style=ActionStyle.PRIMARY,
                        config=ActionConfig(
                            redirect=RedirectConfig(
                                url="/dashboard",
                                open_in_new_tab=False,
                                close_notification=True,
                            )
                        ),
                    )
                ],
            ),
            metadata={
                "kind": notification_kind,
                "todo_actions": todo_actions,
                "platform_text": payload.message,
                "briefing_id": briefing.id,
                "date": briefing.date,
            },
        )
    )
    channels = [c.channel_type for c in getattr(record, "channels", [])] if record else []
    return channels or ["inapp"]


def _bootstrap_should_skip(user: dict, clock: UserClock, has_goal: bool) -> bool:
    """Existing-user rollout gate: hold the first briefing until a goal is known.

    Returns True to skip this run entirely. Once a goal memory arrives OR the
    grace window elapses, the run proceeds (best-effort, re-asking on grace).
    """
    marker = user.get(BOOTSTRAP_FIELD)
    if not marker or not marker.get("pending"):
        return False
    if has_goal:
        return False  # goal arrived — proceed and clear the marker after sending
    since = marker.get("since")
    if isinstance(since, datetime):
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
        if datetime.now(UTC) - since < timedelta(days=BOOTSTRAP_GRACE_DAYS):
            return True  # still inside the interview grace window
    return False  # grace elapsed — fall through to a best-effort briefing


async def _clear_bootstrap(user_id: str, user: dict) -> None:
    if user.get(BOOTSTRAP_FIELD):
        await users_collection.update_one(
            {"_id": ObjectId(user_id)}, {"$unset": {BOOTSTRAP_FIELD: ""}}
        )


async def run_overnight_work(user_id: str) -> None:
    """GAIA's night shift: work the user's goals so the morning brief reports results.

    Runs hours before the briefing. The agent does internal work inline and via
    immediately-executing queued todos (research, lists, drafts, documents) and
    stages outward-facing sends as proposals; the approval rule is enforced by
    the ``create_tracked_todo`` contract exactly as in any other run. Silent by
    design: no payload, no notification; the 8am briefing narrates what exists.
    """
    log.set(service="briefing", operation="run_overnight_work", user_id=user_id)
    user = await get_user_by_id(user_id)
    if not user:
        raise BriefingGenerationError(f"Cannot run overnight work for unknown user {user_id}")
    user["user_id"] = user_id
    clock = context.resolve_clock(user.get("timezone"))

    goal_block, has_goal = await context.format_goal_block(user_id, user)
    if not has_goal:
        log.info("briefing.overnight_no_goal_skip", user_id=user_id)
        return
    strikes = await get_rejection_strikes_summary(user_id)
    todos_block = await context.format_todos_block(user_id)

    prompt = build_overnight_work_prompt(
        date_local=clock.date_str,
        goal_block=goal_block,
        todos_block=todos_block,
        strikes_block=strikes,
    )
    # Reuse the silent-run plumbing; the run's value is its side effects (todos,
    # canvases, drafts), so the text result is only logged.
    result = await _run_silent(user, clock, prompt, conversation_key="overnight")
    log.info("briefing.overnight_complete", user_id=user_id, result_preview=result[:200])


async def run_daily_briefing(user_id: str) -> None:
    """Curate, look back, plan, and deliver one daily briefing for the user."""
    log.set(service="briefing", operation="run_daily_briefing", user_id=user_id)
    user = await get_user_by_id(user_id)
    if not user:
        raise BriefingGenerationError(f"Cannot brief unknown user {user_id}")
    user["user_id"] = user_id
    clock = context.resolve_clock(user.get("timezone"))

    goal_block, has_goal = await context.format_goal_block(user_id, user)
    if _bootstrap_should_skip(user, clock, has_goal):
        log.info("briefing.bootstrap_pending_skip", user_id=user_id)
        return

    # 1. Deterministic curation before anything new is planned.
    expired = await expire_stale_proposals(user_id)

    # 2. Gather the world the agent must see.
    yesterday = await context.get_yesterday_payload(user_id, before_date=clock.date_str)
    since = context.day_start_utc(clock, days_ago=1)
    lookback_block = await context.format_lookback_block(user_id, yesterday, since)
    todos_block = await context.format_todos_block(user_id)
    strikes_block = await get_rejection_strikes_summary(user_id)
    winback = await context.compute_winback_state(user_id)
    streak = await activity.compute_streak(user_id, clock.tz)
    is_first = not await repository.has_daily_briefing(user_id)

    # Gone-quiet backoff: a winback already went out and the user is still silent.
    if winback.should_back_off:
        log.info("briefing.winback_backoff", user_id=user_id, unacknowledged=winback.unacknowledged)
        return

    badge_labels = await check_and_award_badges(user_id, clock, streak)

    prompt = build_daily_briefing_prompt(
        date_local=clock.date_str,
        goal_block=goal_block,
        curation_block=_format_curation(expired),
        lookback_block=lookback_block,
        todos_block=todos_block,
        strikes_block=strikes_block or "No blocked proposal kinds.",
        awards_block=_format_awards(badge_labels),
        winback=winback.is_winback,
        is_first_briefing=is_first,
    )

    payload = await _generate_payload(user, clock, prompt, BRIEFING_KIND_DAILY)
    payload.hue = hue_for_day(clock.day_of_year)
    if winback.is_winback:
        payload.mood = "winback"

    briefing = await repository.upsert_briefing(
        user_id, clock.date_str, BRIEFING_KIND_DAILY, payload
    )
    channels = await _deliver(user_id, briefing, payload, NOTIFICATION_KIND_BRIEFING_DAILY)
    await repository.set_delivered_channels(user_id, clock.date_str, BRIEFING_KIND_DAILY, channels)
    await _clear_bootstrap(user_id, user)

    track(
        user_id,
        "briefing_sent",
        {"kind": BRIEFING_KIND_DAILY, "briefing_id": briefing.id, "mood": payload.mood},
    )
    log.info("briefing.sent", user_id=user_id, kind=BRIEFING_KIND_DAILY, mood=payload.mood)


async def run_weekly_digest(user_id: str) -> None:
    """Zoom out on the week: completed work by assignee, hours saved, streak."""
    log.set(service="briefing", operation="run_weekly_digest", user_id=user_id)
    user = await get_user_by_id(user_id)
    if not user:
        raise BriefingGenerationError(f"Cannot brief unknown user {user_id}")
    user["user_id"] = user_id
    clock = context.resolve_clock(user.get("timezone"))

    since = context.day_start_utc(clock, days_ago=7)
    completed = await context.gather_completed_since(user_id, since)
    hours_saved = round(len(completed.gaia) * MINUTES_SAVED_PER_GAIA_TODO / 60)
    streak = await activity.compute_streak(user_id, clock.tz)
    badge_labels = await check_and_award_badges(user_id, clock, streak)

    prompt = build_weekly_digest_prompt(
        date_local=clock.date_str,
        week_summary_block=_format_week(completed),
        hours_saved=hours_saved,
        streak_days=streak,
        awards_block=_format_awards(badge_labels),
    )

    payload = await _generate_payload(user, clock, prompt, BRIEFING_KIND_WEEKLY)
    payload.hue = hue_for_day(clock.day_of_year)

    briefing = await repository.upsert_briefing(
        user_id, clock.date_str, BRIEFING_KIND_WEEKLY, payload
    )
    channels = await _deliver(user_id, briefing, payload, NOTIFICATION_KIND_BRIEFING_WEEKLY)
    await repository.set_delivered_channels(user_id, clock.date_str, BRIEFING_KIND_WEEKLY, channels)

    track(
        user_id,
        "briefing_sent",
        {"kind": BRIEFING_KIND_WEEKLY, "briefing_id": briefing.id, "mood": payload.mood},
    )
    log.info("briefing.sent", user_id=user_id, kind=BRIEFING_KIND_WEEKLY)
