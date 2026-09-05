"""BriefingService — the daily/weekly run pipeline.

Deterministic curation and context-gathering happen here; the agent only turns
the gathered context into one structured ``BriefingPayload`` (forced via prompt
contract, validated on the way out — invalid output fails the run loudly and
stores nothing). Persistence precedes delivery so the dashboard never misses a
brief that reached a channel.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import re
from typing import cast
from uuid import uuid4

from app.agents.core.agent import AgentRunOptions, call_agent_silent
from app.agents.prompts.briefing_prompts import (
    VoicePromptBlocks,
    build_briefing_voice_prompt,
    build_overnight_work_prompt,
    build_weekly_digest_prompt,
)
from app.constants.briefing import (
    BOOTSTRAP_GRACE_DAYS,
    BRIEFING_KIND_DAILY,
    BRIEFING_KIND_WEEKLY,
    MINUTES_SAVED_PER_GAIA_TODO,
    WEEKLY_GENERATION_TIMEOUT_SECONDS,
    hue_for_day,
)
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.constants.todos import FACET_DELIVERABLE, PROPOSAL_TTL_HOURS, facet_from_doc
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.users import user_repository
from app.models.briefing_models import BriefingKind, BriefingModel, BriefingPayload
from app.models.message_models import MessageDict, MessageRequestWithHistory
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    ChannelConfig,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
    RedirectConfig,
)
from app.models.todo_models import ExecutionStatus, TodoDocument
from app.models.user_models import AuthenticatedUser
from app.services.briefing import chat_sync, context, delivery_channels, dormancy
from app.services.briefing.badges import check_and_award_badges
from app.services.briefing.context import UserClock
from app.services.briefing.edition_rotation import choose_edition_family
from app.services.briefing.editions import rotation_families
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
    run = await call_agent_silent(
        request=request,
        conversation_id=conversation_id,
        user=cast(AuthenticatedUser, user_data),
        options=AgentRunOptions(
            trigger_context={"execution_mode": "background"},
            source="briefing",
        ),
    )
    return run.message


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


def _group_by_serves(docs: list[TodoDocument]) -> str:
    """GAIA completions grouped by the goal they served, each with a deliverable
    snippet so the digest voices specifics instead of bare titles."""
    groups: dict[str, list[TodoDocument]] = {}
    for d in docs[:15]:
        key = (d.serves or "").strip() or "unfiled"
        groups.setdefault(key, []).append(d)
    lines: list[str] = []
    for serves, items in groups.items():
        lines.append(f"{serves}:")
        for d in items:
            snippet = _canvas_snippet(
                facet_from_doc(d.model_dump(), FACET_DELIVERABLE, allow_canvas_fallback=True)
            )
            title = d.title or "untitled"
            lines.append(f"  - {title}" + (f": {snippet}" if snippet else ""))
    return "\n".join(lines)


def _format_week(completed: context.CompletedWork) -> str:
    gaia_n, user_n = len(completed.gaia), len(completed.user)
    lines = [f"GAIA completed {gaia_n} todo(s); you completed {user_n}."]
    if completed.gaia:
        lines.append(
            "GAIA shipped, grouped by the goal it served:\n" + _group_by_serves(completed.gaia)
        )
    if completed.user:
        lines.append(
            "You finished:\n" + "\n".join(f"- {d.title or 'untitled'}" for d in completed.user[:15])
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


_ARTIFACT_PREVIEW_CHARS = 240
# Bookkeeping sections excluded when sizing the DELIVERABLE: a one-line decision
# behind a long research trail must not read as "massive", so these log/scratch
# sections don't count toward link-worthiness.
_BOILERPLATE_SECTIONS = ("activity log", "timeline", "learnings", "context", "system log")


@dataclass
class _ArtifactFact:
    """What the voice pass balances per item: a concrete summary it always voices,
    an always-available link, the deliverable size as a HINT (not a verdict — a
    long research trail behind a one-line decision is not a thing to open), and
    whether it needs action. The pass summarises everything and links only what's
    genuinely a deliverable-to-open or awaiting action.
    """

    snippet: str
    link: str
    chars: int
    action: bool


def _canvas_snippet(canvas: str) -> str:
    """A short, header-free preview of a canvas for the voice pass to draw
    concrete specifics from (names, counts) — never shown to the user verbatim."""
    lines = [
        ln.strip()
        for ln in canvas.splitlines()
        if ln.strip() and not ln.lstrip().startswith(("#", "<!--", "|", "---"))
    ]
    return " ".join(lines)[:_ARTIFACT_PREVIEW_CHARS].rstrip()


def _deliverable_size(canvas: str) -> int:
    """Chars of actual deliverable content — the canvas minus its bookkeeping
    sections — so "massive" tracks the thing the user would open, not the
    research/logs behind a small stated result."""
    kept: list[str] = []
    skipping = False
    for line in canvas.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            skipping = any(heading.startswith(b) for b in _BOILERPLATE_SECTIONS)
        elif not skipping and stripped and not stripped.startswith("<!--"):
            kept.append(stripped)
    return len(" ".join(kept))


async def _gather_artifacts(lanes: list[context.GoalLane]) -> dict[str, _ArtifactFact]:
    """Per lane item: a concrete summary, a minted heygaia.link, and the two
    signals the voice pass balances on — is the deliverable big, does it need
    action. The pass always summarises; it appends the link only for big or
    actionable items, never a bare link and never one for a small stated result.
    Minting is idempotent per target, so re-running the brief reuses the slug.
    An item whose mint fails carries an empty link and is still briefed.
    """
    out: dict[str, _ArtifactFact] = {}
    for lane in lanes:
        action_ids = {d.id for d in [*lane.staged, *lane.needs_you]}
        for doc in [
            *lane.completed,
            *lane.staged,
            *lane.running,
            *lane.needs_you,
            *lane.failed,
        ]:
            todo_id = doc.id
            if todo_id in out:
                continue
            # The briefing summarises and links the DELIVERABLE facet — the
            # send-ready output — not GAIA's private working notes. Fields are
            # projected in context.gather_goal_lanes, so no extra read here.
            allow_canvas_fallback = doc.execution_status == ExecutionStatus.PROPOSED
            deliverable = facet_from_doc(
                doc.model_dump(), FACET_DELIVERABLE, allow_canvas_fallback=allow_canvas_fallback
            )
            out[todo_id] = _ArtifactFact(
                snippet=_canvas_snippet(deliverable),
                link="",
                chars=_deliverable_size(deliverable),
                action=todo_id in action_ids,
            )
    return out


def _platform_parts(payload: BriefingPayload) -> list[str]:
    """Chat-platform bubbles for this payload.

    The voice pass decides how many bubbles and where they break; this only
    filters blanks. The weekly digest emits no bubbles, so it falls back to its
    single message.
    """
    return [b for b in payload.bubbles if b.strip()] or (
        [payload.message] if payload.message else []
    )


async def _deliver(
    user_id: str,
    user: dict,
    briefing: BriefingModel,
    payload: BriefingPayload,
    notification_kind: str,
) -> list[str]:
    """Fan out the briefing via the notification orchestrator (in-app + platforms).

    Channels are resolved to a single chat platform (per the user's priority) plus
    in-app and email, then passed explicitly — which suppresses the orchestrator's
    all-platforms auto-inject so one brief never triple-delivers. ``metadata.kind``
    selects the email template and ``content.rich_content`` carries the full
    payload the email adapter renders — both are the delivery contract the channels
    layer keys off (without them email falls back to the plain template).
    """
    platform_parts = _platform_parts(payload)
    resolved = await delivery_channels.resolve_briefing_channels(user_id, user)
    record = await notification_service.create_notification(
        NotificationRequest(
            user_id=user_id,
            source=NotificationSourceEnum.BACKGROUND_JOB,
            type=NotificationType.INFO,
            priority=2,
            channels=[ChannelConfig(channel_type=channel) for channel in resolved],
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
                "platform_parts": platform_parts,
                "briefing_id": briefing.id,
                "date": briefing.date,
            },
        )
    )
    channels = [c.channel_type for c in getattr(record, "channels", [])] if record else []
    return channels or ["inapp"]


def _expires_within_a_day(created_at: datetime | None, now: datetime) -> bool:
    """True when a staged proposal's PROPOSAL_TTL expiry falls within 24h of now."""
    if created_at is None:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at + timedelta(hours=PROPOSAL_TTL_HOURS) - now <= timedelta(hours=24)


def _lane_items(lane: context.GoalLane) -> list[dict]:
    """Code-built items for one goal lane. Truth by construction."""
    now = datetime.now(UTC)
    items: list[dict] = []
    for d in lane.completed:
        items.append(
            {
                "text": f"Done overnight: {d.title}",
                "todo_id": d.id,
                "kind": "lookback",
            }
        )
    for d in lane.staged:
        expiry = " (expires within a day)" if _expires_within_a_day(d.created_at, now) else ""
        items.append(
            {
                "text": f"Staged and ready: {d.title}{expiry} — a reply releases it.",
                "todo_id": d.id,
                "kind": "proposal",
            }
        )
    for d in lane.running:
        items.append({"text": f"In progress: {d.title}", "todo_id": d.id, "kind": "gaia"})
    for d in lane.failed:
        cause = d.error_message or "unknown cause"
        items.append(
            {
                "text": f"Failed: {d.title} — {cause}",
                "todo_id": d.id,
                "kind": "note",
            }
        )
    for d in lane.needs_you:
        items.append({"text": f"Needs you: {d.title}", "todo_id": d.id, "kind": "you"})
    return items


_ROMAN = ["I", "II", "III", "IV", "V", "VI"]


def _fact_line(item: dict, art: _ArtifactFact | None) -> str:
    line = f"- {item['text']}"
    if art:
        if art.snippet:
            line += f" | summary: {art.snippet}"
        line += f" | artifact holds ~{art.chars} chars"
        if art.action:
            line += " | awaiting your action"
        if art.link:
            line += f" | link: {art.link}"
    return line


def _build_facts(
    lanes: list[context.GoalLane],
    curation_note: str,
    artifacts: dict[str, _ArtifactFact],
    user_todos_note: str,
) -> tuple[list[dict], list[dict], str]:
    """Assemble sections + stats deterministically from lane state.

    Returns (sections, stats, facts_block) — the model voices the facts_block but
    the rendered sections come from here, so the brief cannot lie. Each fact hands
    the model a concrete ``summary`` to voice, whether the deliverable is big and
    whether it needs action, and the link — the model summarises every item and
    only appends the link for big/actionable ones. The dashboard item carries the
    link only when it earns one (same rule), never for a small stated result.
    """
    sections: list[dict] = []
    for i, lane in enumerate(lanes):
        items = _lane_items(lane)
        for it in items:
            art = artifacts.get(it.get("todo_id", ""))
            if art and art.link:
                it["link"] = art.link
        if items:
            sections.append(
                {
                    "numeral": _ROMAN[min(i, len(_ROMAN) - 1)],
                    "title": lane.title.upper(),
                    "items": items,
                }
            )
    staged_total = sum(len(lane.staged) for lane in lanes)
    done_total = sum(len(lane.completed) for lane in lanes)
    stats: list[dict] = []
    if done_total:
        stats.append({"value": str(done_total), "label": "done overnight"})
    if staged_total:
        stats.append({"value": str(staged_total), "label": "awaiting your word"})

    fact_lines: list[str] = [curation_note]
    for sec in sections:
        fact_lines.append(f"[{sec['title']}]")
        for it in sec["items"]:
            fact_lines.append(_fact_line(it, artifacts.get(it.get("todo_id", ""))))
    if not sections:
        fact_lines.append(
            "No goal lanes exist and no background work ran. Do not claim anything "
            "ran, finished, or is pending beyond what is stated here."
        )
    fact_lines.append(user_todos_note)
    return sections, stats, "\n".join(fact_lines)


_VOICE_KEYS = ("headline", "lede", "caption", "mood", "bubbles")


def _parse_voice(raw: str) -> dict:
    """Extract the voice-only JSON (headline/lede/caption/mood/bubbles)."""
    candidates = _JSON_FENCE.findall(raw) or [raw]
    for block in candidates:
        block = block.strip()
        if not block:
            continue
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(data, dict)
            and all(k in data for k in _VOICE_KEYS)
            and isinstance(data["bubbles"], list)
        ):
            return data
    raise BriefingGenerationError(
        f"No valid voice JSON in agent output (first 300 chars): {raw[:300]!r}"
    )


def _bootstrap_should_skip(user: dict, has_goal: bool) -> bool:
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
        await user_repository.clear_briefing_bootstrap(user_id)


async def run_overnight_work(user_id: str) -> None:
    """GAIA's night shift: work the user's goals so the morning brief reports results.

    Runs hours before the briefing. The agent does internal work inline and via
    immediately-executing queued todos (research, lists, drafts, documents) and
    stages outward-facing sends as proposals; the approval rule is enforced by
    the ``create_tracked_todo`` contract exactly as in any other run. Silent by
    design: no payload, no notification; the 8am briefing narrates what exists.
    """
    log.set(component="briefing", operation="run_overnight_work", user_id=user_id)
    user = await get_user_by_id(user_id)
    if not user:
        raise BriefingGenerationError(f"Cannot run overnight work for unknown user {user_id}")
    user["user_id"] = user_id
    clock = context.resolve_clock(user.get("timezone"))

    # Dormant loop: only the daily run mutates dormancy state, but the night
    # shift must not burn an LLM run for a paused user — unless a reactivation
    # signal already arrived (then tonight's work resumes immediately).
    dstate = dormancy.state_from_user(user)
    if dstate.dormant_since and not await dormancy.reactivation_signal_since(
        user_id, dstate.dormant_since
    ):
        log.info("briefing.overnight_dormant_skip", user_id=user_id)
        return

    lanes = await context.gather_goal_lanes(user_id, context.day_start_utc(clock, days_ago=1))
    if not lanes:
        # No confirmed goal lanes: the night shift has nothing legitimate to
        # advance (goal creation always goes through the user, never overnight).
        log.info("briefing.overnight_no_goal_skip", user_id=user_id)
        return
    strikes = await get_rejection_strikes_summary(user_id)
    replies_block = await chat_sync.format_replies_block(
        user_id, context.day_start_utc(clock, days_ago=1)
    )

    prompt = build_overnight_work_prompt(
        date_local=clock.date_str,
        goal_block=context.format_goal_lanes_block(lanes),
        todos_block=await context.format_todos_block(user_id),
        strikes_block=strikes,
        replies_block=replies_block,
    )
    # Reuse the silent-run plumbing; the run's value is its side effects (todos,
    # canvases, drafts), so the text result is only logged.
    result = await _run_silent(user, clock, prompt, conversation_key="overnight")
    log.info("briefing.overnight_complete", user_id=user_id, result_preview=result[:200])


async def _wake_or_skip(user_id: str, user: dict) -> dormancy.DormancyState | None:
    """Dormant loop: wake on a reactivation signal (goal created, user active,
    any message), otherwise None means skip before any LLM cost. The daily run
    is the only writer of dormancy state."""
    dstate = dormancy.state_from_user(user)
    if not dstate.dormant_since:
        return dstate
    if await dormancy.reactivation_signal_since(user_id, dstate.dormant_since):
        await dormancy.clear_dormancy(user_id)
        log.info("briefing.dormancy_cleared", user_id=user_id)
        return dormancy.DormancyState(idle_days=0, date=None, dormant_since=None)
    log.info("briefing.dormant_skip", user_id=user_id)
    return None


def _user_todos_note(open_count: int, open_titles: list[str]) -> str:
    if not open_count:
        return "The user's own todo list is empty."
    first_few = f" (first few: {'; '.join(open_titles)})" if open_titles else ""
    return (
        f"The user's own open todo list holds {open_count} item(s){first_few}"
        ". Only a count of 0 may be voiced as a clear or empty list."
    )


def _daily_payload(
    clock: UserClock, voice: dict, sections: list[dict], stats: list[dict], is_winback: bool
) -> BriefingPayload:
    return BriefingPayload.model_validate(
        {
            "kicker": "THE MORNING BRIEF",
            "date": clock.date_str,
            "headline": voice["headline"],
            "lede": voice["lede"],
            "stats": stats,
            "sections": sections,
            "mood": "winback" if is_winback else voice["mood"],
            "caption": voice["caption"],
            "hue": hue_for_day(clock.day_of_year),
            "bubbles": voice["bubbles"],
            # Single-string rendering for the in-app body / email fallback.
            "message": "\n\n".join(voice["bubbles"]),
        }
    )


async def _publish_daily(
    user_id: str, user: dict, clock: UserClock, payload: BriefingPayload
) -> BriefingModel:
    briefing = await briefing_repository.upsert_briefing(
        user_id, clock.date_str, BRIEFING_KIND_DAILY, payload
    )
    channels = await _deliver(user_id, user, briefing, payload, NOTIFICATION_KIND_BRIEFING_DAILY)
    await briefing_repository.set_delivered_channels(
        user_id, clock.date_str, BRIEFING_KIND_DAILY, channels
    )
    # The bot's conversation must contain the brief it "sent", so replies like
    # "yeah send them" land with real context instead of a cold thread.
    await chat_sync.persist_delivered_brief(user_id, user, _platform_parts(payload), channels)
    await _clear_bootstrap(user_id, user)
    return briefing


async def run_daily_briefing(user_id: str) -> None:
    """Curate, look back, plan, and deliver one daily briefing for the user."""
    log.set(component="briefing", operation="run_daily_briefing", user_id=user_id)
    user = await get_user_by_id(user_id)
    if not user:
        raise BriefingGenerationError(f"Cannot brief unknown user {user_id}")
    user["user_id"] = user_id
    clock = context.resolve_clock(user.get("timezone"))

    dstate = await _wake_or_skip(user_id, user)
    if dstate is None:
        return

    goal_block, has_goal = await context.format_goal_block(user_id, user)
    if _bootstrap_should_skip(user, has_goal):
        log.info("briefing.bootstrap_pending_skip", user_id=user_id)
        return

    # 1. Deterministic curation before anything new is planned.
    expired = await expire_stale_proposals(user_id)

    # 2. Gather the world the agent must see.
    yesterday = await context.get_yesterday_payload(user_id, before_date=clock.date_str)
    since = context.day_start_utc(clock, days_ago=1)
    lookback_block = await context.format_lookback_block(user_id, yesterday, since)
    strikes_block = await get_rejection_strikes_summary(user_id)
    winback = await context.compute_winback_state(user_id)
    streak = await activity.compute_streak(user_id, clock.tz)
    is_first = not await briefing_repository.has_daily_briefing(user_id)

    # Gone-quiet backoff: a winback already went out and the user is still silent.
    if winback.should_back_off:
        log.info("briefing.winback_backoff", user_id=user_id, unacknowledged=winback.unacknowledged)
        return

    badge_labels = await check_and_award_badges(user_id, clock, streak)

    # Facts are assembled by code from lane state; the model only voices them.
    lanes = await context.gather_goal_lanes(user_id, since)
    artifacts = await _gather_artifacts(lanes)
    open_count, open_titles = await context.user_open_todo_summary(user_id)
    sections, stats, facts_block = _build_facts(
        lanes, _format_curation(expired), artifacts, _user_todos_note(open_count, open_titles)
    )

    # Idle ladder: nothing to advance (no lanes, no goal knowledge) escalates
    # from the goal question to a plain warning to one goodbye, then dormancy.
    idle = not lanes and not has_goal
    idle_days = await dormancy.record_idle_day(user_id, dstate, idle, clock.date_str)
    wind_down = dormancy.wind_down_stage(idle_days) if idle else None

    prompt = build_briefing_voice_prompt(
        date_local=clock.date_str,
        blocks=VoicePromptBlocks(
            facts=facts_block,
            goal=goal_block,
            lookback=lookback_block,
            replies=await chat_sync.format_replies_block(user_id, since),
            strikes=strikes_block or "No blocked proposal kinds.",
            awards=_format_awards(badge_labels),
        ),
        winback=winback.is_winback and wind_down is None,
        is_first_briefing=is_first,
        wind_down=wind_down,
    )
    voice = _parse_voice(
        await _run_silent(user, clock, prompt, conversation_key=BRIEFING_KIND_DAILY)
    )
    payload = _daily_payload(clock, voice, sections, stats, winback.is_winback)

    # Daily editions rotate the template library too ("daily fun docs") —
    # independent per-kind state, assigned only after generation succeeds and
    # persisted forever with the payload.
    payload.template_family = await choose_edition_family(
        user_id, kind=BRIEFING_KIND_DAILY, families=rotation_families()
    )
    briefing = await _publish_daily(user_id, user, clock, payload)

    # The goodbye went out — pause the loop until a reactivation signal.
    if wind_down == dormancy.WIND_DOWN_FINAL:
        await dormancy.enter_dormancy(user_id)
        log.info("briefing.dormancy_entered", user_id=user_id, idle_days=idle_days)

    track(
        user_id,
        "briefing_sent",
        {"kind": BRIEFING_KIND_DAILY, "briefing_id": briefing.id, "mood": payload.mood},
    )
    log.info("briefing.sent", user_id=user_id, kind=BRIEFING_KIND_DAILY, mood=payload.mood)


async def run_weekly_digest(user_id: str) -> None:
    """Zoom out on the week: completed work by assignee, hours saved, streak."""
    log.set(component="briefing", operation="run_weekly_digest", user_id=user_id)
    user = await get_user_by_id(user_id)
    if not user:
        raise BriefingGenerationError(f"Cannot brief unknown user {user_id}")
    user["user_id"] = user_id
    clock = context.resolve_clock(user.get("timezone"))

    # A dormant loop has nothing to zoom out on; the daily run owns reactivation.
    dstate = dormancy.state_from_user(user)
    if dstate.dormant_since and not await dormancy.reactivation_signal_since(
        user_id, dstate.dormant_since
    ):
        log.info("briefing.weekly_dormant_skip", user_id=user_id)
        return

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

    # Bounded: a stalled agent run must fail the cron loudly, not hang the
    # worker slot (observed live 2026-08-07).
    async with asyncio.timeout(WEEKLY_GENERATION_TIMEOUT_SECONDS):
        payload = await _generate_payload(user, clock, prompt, BRIEFING_KIND_WEEKLY)
    payload.hue = hue_for_day(clock.day_of_year)
    # Rotation advances only after generation succeeds, so a failed run does
    # not burn this week's slot in the shuffled cycle.
    payload.template_family = await choose_edition_family(
        user_id, kind=BRIEFING_KIND_WEEKLY, families=rotation_families()
    )

    briefing = await briefing_repository.upsert_briefing(
        user_id, clock.date_str, BRIEFING_KIND_WEEKLY, payload
    )
    channels = await _deliver(user_id, user, briefing, payload, NOTIFICATION_KIND_BRIEFING_WEEKLY)
    await briefing_repository.set_delivered_channels(
        user_id, clock.date_str, BRIEFING_KIND_WEEKLY, channels
    )
    await chat_sync.persist_delivered_brief(user_id, user, _platform_parts(payload), channels)

    track(
        user_id,
        "briefing_sent",
        {"kind": BRIEFING_KIND_WEEKLY, "briefing_id": briefing.id, "mood": payload.mood},
    )
    log.info("briefing.sent", user_id=user_id, kind=BRIEFING_KIND_WEEKLY)
