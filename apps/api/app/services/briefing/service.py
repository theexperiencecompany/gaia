"""BriefingService: the daily/weekly run pipeline.

The agent only turns gathered context into one BriefingPayload; invalid output fails
the run loudly and stores nothing. Persistence precedes delivery so the dashboard
never misses a brief that reached a channel.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import random
import re
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.agents.core.agent import AgentRunOptions, call_agent_silent
from app.agents.core.background.platform_chat import PlatformImage, post_to_platform_chat
from app.agents.prompts.briefing_prompts import (
    VoicePromptBlocks,
    build_briefing_voice_prompt,
    build_weekly_digest_prompt,
    reader_line,
    voice_correction_note,
)
from app.constants.briefing import (
    BOOTSTRAP_GRACE_DAYS,
    BRIEFING_KIND_DAILY,
    BRIEFING_KIND_WEEKLY,
    DAILY_KICKER,
    MAX_BRIEF_ITEMS,
    MAX_VOICE_ATTEMPTS,
    POSTAL_FAMILY,
    RECENT_OPENINGS_SHOWN,
    WEEKLY_FAMILY,
    WEEKLY_GENERATION_TIMEOUT_SECONDS,
    WEEKLY_KICKER,
    BriefingBag,
    BriefingRunOutcome,
    hue_for_day,
)
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
    NotificationChannel,
    ProactiveMessageClass,
)
from app.constants.user_activity import ActivityStatus
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.pending_brief_items import pending_brief_items_repository
from app.db.repositories.users import user_repository
from app.models.brief_models import PendingBriefItemDocument
from app.models.briefing_models import (
    BRIEFING_ITEM_STATES,
    BriefingEvent,
    BriefingItem,
    BriefingItemKind,
    BriefingKind,
    BriefingModel,
    BriefingMood,
    BriefingPayload,
    BriefingSection,
    BriefingStat,
    BriefingTallies,
)
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
    RedirectConfig,
)
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser, ShuffleBag, UserDocument
from app.services.analytics_service import capture
from app.services.briefing import chat_sync, context, dormancy
from app.services.briefing.context import UserClock
from app.services.briefing.edition_email import HostedEditionImage, host_edition_image
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.editions.stamps import hosted_stamp_weights
from app.services.briefing.message import brief_message, brief_path, chat_text, full_brief_url
from app.services.briefing.schedule import describe_briefing_schedule
from app.services.briefing.shuffle_bag import draw
from app.services.briefing.voice_check import (
    VoicedCounts,
    message_contradictions,
    voice_contradictions,
)
from app.services.delivery.chat_channel import ChatChannel, resolve_chat_channel
from app.services.integrations.user_integrations import get_connected_integrations_named
from app.services.notification_service import notification_service
from app.services.outbound_delivery import OutboundResult
from app.services.user_activity.status import activity_status_of
from app.utils.auth_utils import build_user_context
from app.utils.email_utils import own_first_name, own_name
from app.utils.notification.channel_preferences import normalize_channel_preferences
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingSent
from shared.py.wide_events import log

# Extracts a ```json fenced block (or a bare object) from the agent's final text.
_JSON_FENCE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)


def json_blocks(raw: str) -> list[str]:
    """Return the non-empty JSON candidates in an agent's reply: its fenced blocks, else the reply."""
    return [block.strip() for block in _JSON_FENCE.findall(raw) or [raw] if block.strip()]


class BriefingGenerationError(Exception):
    """The agent did not produce a valid BriefingPayload — the run failed."""


def _parse_payload(raw: str) -> BriefingPayload:
    """Extract and validate the single BriefingPayload from the agent output.

    call_agent_silent swallows its errors into a plain string, which fails validation
    here, so no partial briefing is stored.
    """
    for block in json_blocks(raw):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "headline" in data:
            payload = BriefingPayload.model_validate(data)
            item_count = sum(len(section.items) for section in payload.sections)
            if item_count > MAX_BRIEF_ITEMS:
                raise BriefingGenerationError(
                    f"BriefingPayload has {item_count} items; a brief holds at most "
                    f"{MAX_BRIEF_ITEMS}"
                )
            if not payload.message:
                raise BriefingGenerationError("BriefingPayload has no message to deliver")
            return payload
    raise BriefingGenerationError(
        f"No valid BriefingPayload in agent output (first 300 chars): {raw[:300]!r}"
    )


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


async def _run_silent(
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


async def _generate_payload(
    user: AuthenticatedUser, clock: UserClock, prompt: str, kind: BriefingKind
) -> BriefingPayload:
    return _parse_payload(await _run_silent(user, clock, prompt, conversation_key=kind))


def _gaia_shipped_lines(docs: list[TodoDocument]) -> str:
    """List GAIA completions, each with a canvas snippet.

    The snippet lets the digest voice specifics instead of bare titles.
    """
    lines: list[str] = []
    for d in docs[:15]:
        snippet = _canvas_snippet(d.canvas_content or "")
        title = d.title or "untitled"
        lines.append(f"- {title}" + (f": {snippet}" if snippet else ""))
    return "\n".join(lines)


def _format_week(completed: context.CompletedWork) -> str:
    gaia_n, user_n = len(completed.gaia), len(completed.user)
    lines = [f"GAIA completed {gaia_n} todo(s); you completed {user_n}."]
    if completed.gaia:
        lines.append("GAIA shipped:\n" + _gaia_shipped_lines(completed.gaia))
    if completed.user:
        lines.append(
            "You finished:\n" + "\n".join(f"- {d.title or 'untitled'}" for d in completed.user[:15])
        )
    return "\n\n".join(lines)


_ARTIFACT_PREVIEW_CHARS = 240
# Bookkeeping sections excluded when sizing the DELIVERABLE: a one-line decision
# behind a long research trail must not read as "massive", so these log/scratch
# sections don't count toward its size.
_BOILERPLATE_SECTIONS = ("activity log", "timeline", "learnings", "context", "system log")


@dataclass
class _ArtifactFact:
    """What the voice pass balances per item.

    A concrete summary it always voices, the deliverable size as a HINT (not a verdict —
    a long research trail behind a one-line decision is not a thing to open), and
    whether it is waiting on the user.
    """

    snippet: str
    chars: int
    action: bool


def _canvas_snippet(canvas: str) -> str:
    """Return a short, header-free preview of a canvas for the voice pass.

    The pass draws concrete specifics from it (names, counts); it is never shown to the
    user verbatim.
    """
    lines = [
        ln.strip()
        for ln in canvas.splitlines()
        if ln.strip() and not ln.lstrip().startswith(("#", "<!--", "|", "---"))
    ]
    return " ".join(lines)[:_ARTIFACT_PREVIEW_CHARS].rstrip()


def _deliverable_size(canvas: str) -> int:
    """Count chars of actual deliverable content: the canvas minus its bookkeeping sections.

    That way "massive" tracks the thing the user would open, not the research/logs behind
    a small stated result.
    """
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


def _gather_artifacts(work: context.TrackedWork) -> dict[str, _ArtifactFact]:
    """Build, per tracked item, a concrete summary and the two signals the voice pass uses.

    The signals are whether the deliverable is big and whether it is waiting on the user.
    """
    out: dict[str, _ArtifactFact] = {}
    blocked_ids = {d.id for d in work.blocked}
    for doc in [*work.completed, *work.running, *work.blocked, *work.failed]:
        todo_id = doc.id
        if todo_id in out:
            continue
        canvas = doc.canvas_content or ""
        out[todo_id] = _ArtifactFact(
            snippet=_canvas_snippet(canvas),
            chars=_deliverable_size(canvas),
            action=todo_id in blocked_ids,
        )
    return out


def _wants_email(user: UserDocument) -> bool:
    """Email goes out when the user left it on and has an address on file."""
    prefs = normalize_channel_preferences(user.notification_channel_prefs)
    return prefs[NotificationChannel.EMAIL] and bool((user.email or "").strip())


async def _post_to_chat(
    user: UserDocument, channel: ChatChannel, text: str, image_url: str, kind: BriefingKind
) -> OutboundResult:
    """Post the edition image captioned with text's first bubble, the rest after it, into the DM.

    A reply there lands with the brief in context.
    """
    return await post_to_platform_chat(
        user=build_user_context(user, auth_provider=None),
        channel=channel,
        text=text,
        origin=f"{kind} brief",
        message_class=ProactiveMessageClass.ROUTINE,
        image=PlatformImage(url=image_url, filename=f"gaia-{kind}-brief.jpg"),
    )


async def _deliver(
    user: UserDocument,
    briefing: BriefingModel,
    payload: BriefingPayload,
    notification_kind: str,
    *,
    image: HostedEditionImage,
    push: bool,
) -> list[str]:
    """Deliver one brief in-app and, when pushed, to email and the user's chat.

    The orchestrator gets only in-app (plus email when wanted), never the chat platform:
    that message is the edition photo, posted through post_to_platform_chat.
    """
    kind: BriefingKind = briefing.kind
    message = brief_message(payload)
    channel = await resolve_chat_channel(user.id) if push else None
    channels = [NotificationChannel.INAPP] + (
        [NotificationChannel.EMAIL] if push and _wants_email(user) else []
    )
    record = await notification_service.create_notification(
        NotificationRequest(
            user_id=user.id,
            source=NotificationSourceEnum.BACKGROUND_JOB,
            priority=2,
            channels=[ChannelConfig(channel_type=c) for c in channels],
            content=NotificationContent(
                title=payload.headline,
                body=message,
                rich_content=payload.model_dump(),
                actions=[
                    NotificationAction(
                        type=ActionType.REDIRECT,
                        label="Open briefing",
                        style=ActionStyle.PRIMARY,
                        config=ActionConfig(
                            redirect=RedirectConfig(
                                url=brief_path(briefing.id),
                                open_in_new_tab=False,
                                close_notification=True,
                            )
                        ),
                    )
                ],
            ),
            metadata={
                "kind": notification_kind,
                "briefing_id": briefing.id,
                "date": briefing.date,
                "edition_image_url": image.display_url,
            },
        )
    )
    delivered = [c.channel_type for c in record.channels if c.reached_user]
    if channel:
        text = chat_text(payload, full_brief_url(briefing.id))
        result = await _post_to_chat(user, channel, text, image.chat_url, kind)
        if result is OutboundResult.PUBLISHED:
            delivered.append(channel.source.value)
    return delivered


# Display casing: every surface shows these as written; an edition that sets its
# section heads in capitals does so in its own CSS.
_NEEDS_YOU_SECTION_TITLE = "Needs you"
_HELD_SECTION_TITLE = "While you were away"
_WORK_SECTION_TITLE = "GAIA's work"
_SECTION_NUMERALS = ("I", "II", "III")


def _subject_key(doc: TodoDocument) -> str:
    """Return what makes todos one thing to the user: a shared parent, else the same title."""
    return f"parent:{doc.parent_todo_id}" if doc.parent_todo_id else _same_text_key(doc.title)


def _work_items(docs: list[TodoDocument], kind: BriefingItemKind) -> list[BriefingItem]:
    """One item per subject, counting the todos it stands for, in first-seen order."""
    items: dict[str, BriefingItem] = {}
    for doc in docs:
        key = _subject_key(doc)
        if key in items:
            items[key].count += 1
        else:
            items[key] = BriefingItem(text=doc.title, todo_id=doc.id, kind=kind)
    return list(items.values())


def _held_text(doc: PendingBriefItemDocument) -> str:
    """One line for a held result: where it came from and its report's first line."""
    first_line = next((line.strip() for line in doc.text.splitlines() if line.strip()), "")
    return f"{doc.workflow_title}: {first_line}"


def _same_text_key(text: str) -> str:
    return " ".join(text.split()).casefold()  # pragma: no mutate — spaced joins stay injective


@dataclass
class _Sections:
    """The brief's code-built sections and what building them decided.

    carried_ids are the held items this brief accounts for, cleared once it has gone out.
    """

    sections: list[BriefingSection]
    left_out: int
    carried_ids: list[str]


def _work_sections(work: context.TrackedWork, held: list[PendingBriefItemDocument]) -> _Sections:
    """Code-built sections for GAIA's tracked work and held results.

    Order: needs-you (blocked, then failed), held results, then GAIA's own work, capped
    at MAX_BRIEF_ITEMS. A held result already in the brief still counts as carried; one
    the cap leaves out waits for the next brief.
    """
    needs_you = _work_items(work.blocked, "you") + _work_items(work.failed, "failed")
    gaia_work = _work_items(work.completed, "lookback") + _work_items(work.running, "gaia")
    seen = {_same_text_key(item.text) for item in needs_you + gaia_work}
    held_items: list[BriefingItem] = []
    held_ids: list[str] = []
    duplicate_ids: list[str] = []
    for doc in held:
        text = _held_text(doc)
        if _same_text_key(text) in seen:
            duplicate_ids.append(doc.id)
            continue
        seen.add(_same_text_key(text))
        held_items.append(BriefingItem(text=text))
        held_ids.append(doc.id)

    kept_needs_you = needs_you[:MAX_BRIEF_ITEMS]
    kept_held = held_items[: MAX_BRIEF_ITEMS - len(kept_needs_you)]
    kept_work = gaia_work[: MAX_BRIEF_ITEMS - len(kept_needs_you) - len(kept_held)]
    filled = [
        (title, items)
        for title, items in (
            (_NEEDS_YOU_SECTION_TITLE, kept_needs_you),
            (_HELD_SECTION_TITLE, kept_held),
            (_WORK_SECTION_TITLE, kept_work),
        )
        if items
    ]
    kept_total = len(kept_needs_you) + len(kept_held) + len(kept_work)
    return _Sections(
        sections=[
            BriefingSection(numeral=_SECTION_NUMERALS[i], title=title, items=items)
            for i, (title, items) in enumerate(filled)
        ],
        left_out=len(needs_you) + len(held_items) + len(gaia_work) - kept_total,
        carried_ids=held_ids[: len(kept_held)] + duplicate_ids,
    )


def _fact_line(item: BriefingItem, art: _ArtifactFact | None) -> str:
    line = f"- {BRIEFING_ITEM_STATES[item.kind]}: {item.text}"
    if item.count > 1:
        line += f" | {item.count} requests, one item"
    if art:
        if art.snippet:
            line += f" | summary: {art.snippet}"
        line += f" | artifact holds ~{art.chars} chars"
        if art.action:
            line += " | waiting on you"
    return line


@dataclass
class _Facts:
    """The brief's sections and stats, the facts block the model voices, and held items.

    The held items are the ones the brief carries.
    """

    sections: list[BriefingSection]
    stats: list[BriefingStat]
    counts: VoicedCounts
    block: str
    carried_ids: list[str]


def _work_stats(work: context.TrackedWork) -> list[BriefingStat]:
    """Build the stat row: one figure per non-empty tracked-work state, counted by subject."""
    figures = (
        (work.completed, "done since yesterday"),
        (work.running, "in progress"),
        (work.blocked, "waiting on you"),
    )
    return [
        BriefingStat(value=str(len({_subject_key(d) for d in docs})), label=label)
        for docs, label in figures
        if docs
    ]


def _build_facts(
    work: context.TrackedWork,
    held: list[PendingBriefItemDocument],
    artifacts: dict[str, _ArtifactFact],
    open_todos: int,
    notes: str,
) -> _Facts:
    """Assemble sections + stats deterministically from tracked-work state and held results.

    The rendered sections come from here so the brief cannot lie. Each fact gives the
    model a summary and whether it is big or waiting on the user.
    """
    built = _work_sections(work, held)
    sections, left_out = built.sections, built.left_out
    items = [it for sec in sections for it in sec.items]
    counts = VoicedCounts(
        waiting_on_you=sum(1 for it in items if it.kind in ("you", "failed")),
        done=sum(1 for it in items if it.kind == "lookback"),
        in_progress=sum(1 for it in items if it.kind == "gaia"),
        while_away=sum(1 for it in items if it.kind == "note"),
        open_todos=open_todos,
    )
    voiced = " · ".join(f"{label}: {n}" for label, n in counts.shown())
    fact_lines: list[str] = [f"[COUNTS] {voiced}"] if voiced else []
    for sec in sections:
        fact_lines.append(f"[{sec.title}]")
        for it in sec.items:
            art = artifacts.get(it.todo_id) if it.todo_id else None
            fact_lines.append(_fact_line(it, art))
    if left_out:
        fact_lines.append(
            f"{left_out} lower-priority item(s) are not in this brief; they are in the app."
        )
    if not sections:
        fact_lines.append(
            "GAIA has no tracked work and no background work ran. Do not claim anything "
            "ran, finished, or is pending beyond what is stated here."
        )
    fact_lines.append(notes)
    return _Facts(sections, _work_stats(work), counts, "\n".join(fact_lines), built.carried_ids)


class _Voice(BaseModel):
    """The voice-only JSON the daily run's agent writes over the code-built facts."""

    headline: str
    lede: str
    caption: str
    mood: BriefingMood
    message: str


def _parse_voice(raw: str) -> _Voice:
    """Extract the voice-only JSON (headline/lede/caption/mood/message)."""
    for block in json_blocks(raw):
        try:
            return _Voice.model_validate_json(block)
        except ValidationError:
            continue
    raise BriefingGenerationError(
        f"No valid voice JSON in agent output (first 300 chars): {raw[:300]!r}"
    )


def _bootstrap_should_skip(user: UserDocument, has_goal: bool) -> bool:
    """Existing-user rollout gate: hold the first briefing until a goal is known.

    Returns True to skip this run entirely. Once a goal memory arrives OR the
    grace window elapses, the run proceeds (best-effort, re-asking on grace).
    """
    marker = user.briefing_bootstrap
    if marker is None or not marker.pending:
        return False
    if has_goal:
        return False  # goal arrived — proceed and clear the marker after sending
    since = marker.since if marker.since.tzinfo else marker.since.replace(tzinfo=UTC)
    # Inside the interview grace window: hold. Past it: a best-effort briefing.
    return datetime.now(UTC) - since < timedelta(days=BOOTSTRAP_GRACE_DAYS)


async def _clear_bootstrap(user: UserDocument) -> None:
    if user.briefing_bootstrap is not None:
        await user_repository.clear_briefing_bootstrap(user.id)


async def _wake_or_skip(user: UserDocument) -> dormancy.DormancyState | None:
    """Wake a dormant loop on a reactivation signal (user active, any message).

    Otherwise None means skip before any LLM cost. The daily run is the only writer of
    dormancy state.
    """
    dstate = dormancy.state_from_user(user)
    if not dstate.dormant_since:
        return dstate
    if await dormancy.latest_activity_since(user.id, dstate.dormant_since) is not None:
        await dormancy.clear_dormancy(user.id)
        log.info("briefing.dormancy_cleared", user_id=user.id)
        return dormancy.DormancyState(idle_days=0, date=None, dormant_since=None)
    log.info("briefing.dormant_skip", user_id=user.id)
    return None


async def _setup_block(user: UserDocument, *, first_week: bool, offer_lighter: bool) -> str:
    """Return the account facts a first-week tip or a lighter-cadence offer may cite."""
    lines: list[str] = []
    if offer_lighter:
        lines.append(f"Their briefs now: {describe_briefing_schedule(user)}.")
    if first_week:
        apps = [app["name"] for app in await get_connected_integrations_named(user.id)]
        lines.append(f"Apps they've connected: {', '.join(apps) if apps else 'none yet'}.")
    return "\n".join(lines)


def _calendar_note(events: list[BriefingEvent]) -> str:
    if not events:
        return "The user's calendar has nothing today (or no calendar is connected)."
    lines = [f"- {e.start or 'all day'}: {e.title}" for e in events]
    return "Today's calendar (user-local 24h times):\n" + "\n".join(lines)


@dataclass(frozen=True)
class _BagDraw:
    """Today's member of one shuffle bag and the state that continues its pass."""

    bag: BriefingBag
    member: str
    next_state: ShuffleBag


def _draw_from_bag(user: UserDocument, bag: BriefingBag, weights: Mapping[str, int]) -> _BagDraw:
    """Draw today's member from one of the user's shuffle bags, off the loaded user.

    Nothing is persisted here: _publish saves the draw only once the brief went out,
    so a failed run does not burn a member of the pass.
    """
    state = (user.briefing_shuffle_bags or {}).get(bag)
    member, next_state = draw(state, weights, random.SystemRandom())
    return _BagDraw(bag=bag, member=member, next_state=next_state)


async def _persist_draws(user_id: str, draws: list[_BagDraw]) -> None:
    for bag_draw in draws:
        await user_repository.set_briefing_bag(user_id, bag_draw.bag, bag_draw.next_state)
        log.info(
            "briefing.bag_drawn", user_id=user_id, bag=bag_draw.bag.value, member=bag_draw.member
        )


def _assign_edition(user: UserDocument, payload: BriefingPayload, family: str) -> list[_BagDraw]:
    """Record the edition family on the payload, and for Air Mail its stamp.

    Returns the stamp draw, persisted once the brief is delivered.
    """
    payload.template_family = family
    if family != POSTAL_FAMILY:
        return []
    stamp = _draw_from_bag(user, BriefingBag.STAMP_CITY, hosted_stamp_weights())
    payload.stamp_city = stamp.member
    return [stamp]


def _user_todos_note(open_count: int, open_titles: list[str]) -> str:
    if not open_count:
        return "The user's own todo list is empty."
    first_few = f" (first few: {'; '.join(open_titles)})" if open_titles else ""
    return (
        f"The user's own open todos{first_few} are counted in [COUNTS]"
        "; never voice that list as clear or empty."
    )


async def _recent_openings(user_id: str) -> list[str]:
    """Return the opening line of each recent daily brief's message, newest first."""
    recent = await briefing_repository.list_recent(
        user_id, limit=RECENT_OPENINGS_SHOWN, kind=BRIEFING_KIND_DAILY
    )
    messages = [brief.payload.message for brief in recent if brief.payload.message]
    return [next(line.strip() for line in m.splitlines() if line.strip()) for m in messages]


@dataclass(frozen=True)
class _ProseRules:
    """What the written brief is checked against.

    context is everything else the model was shown; require_coverage holds the message
    to every needs-you item and event (a winback or wind-down note is exempt).
    """

    counts: VoicedCounts
    context: str
    require_coverage: bool


def _prose_problems(payload: BriefingPayload, rules: _ProseRules) -> list[str]:
    return voice_contradictions(
        payload.headline, payload.lede, payload, rules.counts, context=rules.context
    ) + message_contradictions(
        brief_message(payload),
        payload,
        rules.counts,
        context=rules.context,
        require_coverage=rules.require_coverage,
    )


async def _voice_checked_against_items(
    user: AuthenticatedUser,
    clock: UserClock,
    prompt: str,
    rules: _ProseRules,
    build: Callable[[_Voice], BriefingPayload],
) -> BriefingPayload:
    """Voice the brief, then check its headline, lede and message against its final items.

    A contradiction is sent back to the model once with the problems named; a second
    one fails the run before anything is stored or sent.
    """
    problems: list[str] = []  # pragma: no mutate — any falsy init; the first pass reassigns it
    for _ in range(MAX_VOICE_ATTEMPTS):
        attempt_prompt = f"{prompt}\n\n{voice_correction_note(problems)}" if problems else prompt
        payload = build(
            _parse_voice(
                await _run_silent(user, clock, attempt_prompt, conversation_key=BRIEFING_KIND_DAILY)
            )
        )
        problems = _prose_problems(payload, rules)
        if not problems:
            return payload
        log.warning("briefing.voice_contradicted_items", problems=problems)
    raise BriefingGenerationError(f"The brief's prose contradicts its items: {'; '.join(problems)}")


def _daily_payload(
    clock: UserClock,
    voice: _Voice,
    sections: list[BriefingSection],
    stats: list[BriefingStat],
    is_winback: bool,
) -> BriefingPayload:
    return BriefingPayload(
        kicker=DAILY_KICKER,
        date=clock.date_str,
        headline=voice.headline,
        lede=voice.lede,
        stats=stats,
        sections=sections,
        mood="winback" if is_winback else voice.mood,
        caption=voice.caption,
        hue=hue_for_day(clock.day_of_year),
        generated_at=clock.now_local.strftime("%-I:%M %p"),
        message=voice.message,
    )


def _is_empty_day(payload: BriefingPayload) -> bool:
    """Nothing needs the user, nothing is on their calendar and nothing ran overnight."""
    return not payload.calendar and not any(section.items for section in payload.sections)


@dataclass(frozen=True)
class _Edition:
    """The edition family a brief renders in, and the bag draws spent choosing it."""

    family: str
    draws: list[_BagDraw]


_NOTIFICATION_KINDS: dict[BriefingKind, str] = {
    BRIEFING_KIND_DAILY: NOTIFICATION_KIND_BRIEFING_DAILY,
    BRIEFING_KIND_WEEKLY: NOTIFICATION_KIND_BRIEFING_WEEKLY,
}


async def _publish(
    user: UserDocument,
    clock: UserClock,
    kind: BriefingKind,
    payload: BriefingPayload,
    edition: _Edition,
    *,
    push: bool,
) -> BriefingModel:
    """Draw the edition, render and store the brief, deliver it and report where it went.

    The edition is rendered and hosted first, so a render failure stores and sends
    nothing; the one image serves the in-app page, the email and the chat post. A brief
    that is not pushed (push=False) goes in-app only and spends no shuffle-bag draw;
    otherwise the draws (the family's and the stamp's) persist after delivery.
    """
    family = edition.family
    draws = [*edition.draws, *_assign_edition(user, payload, family)]
    payload.recipient_name = own_name(user.name, user.email)
    # A fresh random key per render: the hosted URL reaches emails and public links.
    image = await host_edition_image(payload, render_key=uuid4().hex)
    briefing = await briefing_repository.upsert_briefing(
        user.id, clock.date_str, kind, payload, edition_image_url=image.display_url
    )
    channels = await _deliver(
        user, briefing, payload, _NOTIFICATION_KINDS[kind], image=image, push=push
    )
    await briefing_repository.set_delivered_channels(user.id, clock.date_str, kind, channels)
    if push:
        await _persist_draws(user.id, draws)
    capture(
        UserId(user.id),
        BriefingSent(
            kind=kind,
            family=family,
            mood=payload.mood,
            item_count=sum(len(s.items) for s in payload.sections),
            channel_count=len(channels),
        ),
    )
    log.info("briefing.sent", user_id=user.id, kind=kind, channels=channels, pushed=push)
    return briefing


async def _already_delivered(user_id: str, clock: UserClock, kind: BriefingKind) -> bool:
    """One brief per user, local date and kind: a second run that day sends nothing."""
    if await briefing_repository.was_delivered(user_id, clock.date_str, kind):
        log.info("briefing.already_delivered_skip", user_id=user_id, kind=kind)
        return True
    return False


async def run_daily_briefing(user_id: str) -> BriefingRunOutcome:
    """Look back, plan, and deliver one daily briefing for the user; return how it ended."""
    log.set(component="briefing", operation="run_daily_briefing", user_id=user_id)
    user = await user_repository.get(user_id)
    if user is None:
        raise BriefingGenerationError(f"Cannot brief unknown user {user_id}")
    clock = context.resolve_clock(user.timezone)
    if await _already_delivered(user_id, clock, BRIEFING_KIND_DAILY):
        return BriefingRunOutcome.ALREADY_DELIVERED

    dstate = await _wake_or_skip(user)
    if dstate is None:
        return BriefingRunOutcome.DORMANT

    goal_block, has_goal = await context.format_goal_block(user_id, user)
    if _bootstrap_should_skip(user, has_goal):
        log.info("briefing.bootstrap_pending_skip", user_id=user_id)
        return BriefingRunOutcome.BOOTSTRAP_PENDING

    # Gather the world the agent must see.
    yesterday = await context.get_yesterday_payload(user_id, before_date=clock.date_str)
    since = context.day_start_utc(clock, days_ago=1)
    lookback_block = await context.format_lookback_block(user_id, yesterday, since)
    winback = await context.compute_winback_state(user)
    is_first = not await briefing_repository.has_daily_briefing(user_id)

    # Gone-quiet backoff: a winback already went out and the user is still silent.
    if winback.should_back_off:
        log.info("briefing.winback_backoff", user_id=user_id, unacknowledged=winback.unacknowledged)
        return BriefingRunOutcome.WINBACK_BACKOFF

    # Facts are assembled by code from tracked-work state; the model only voices them.
    work = await context.gather_tracked_work(user_id, since)
    artifacts = _gather_artifacts(work)
    open_count, open_titles = await context.user_open_todo_summary(user_id)
    calendar = await context.gather_calendar(user_id, clock, days=1)
    completed = await context.gather_completed_since(user_id, since)
    held = await pending_brief_items_repository.list_for_user(user_id, sort=[("created_at", 1)])
    facts = _build_facts(
        work,
        held,
        artifacts,
        open_count,
        _user_todos_note(open_count, open_titles) + "\n" + _calendar_note(calendar),
    )

    # Idle ladder: nothing to report (no tracked work, no held results, no goal
    # knowledge) escalates from the goal question to a plain warning to one
    # goodbye, then dormancy. A new account's first week never climbs it.
    first_week = dormancy.in_first_week(user, datetime.now(UTC))
    idle = work.is_empty and not held and not has_goal and not first_week
    idle_days = await dormancy.record_idle_day(user_id, dstate, idle, clock.date_str)
    wind_down = dormancy.wind_down_stage(idle_days) if idle else None
    # A user who stopped coming back is offered fewer briefs, never silently dropped.
    offer_lighter = await activity_status_of(user_id) == ActivityStatus.IDLE

    blocks = VoicePromptBlocks(
        reader=reader_line(own_first_name(user.name, user.email)),
        facts=facts.block,
        goal=goal_block,
        lookback=lookback_block,
        replies=await chat_sync.format_replies_block(user_id, since),
        setup=await _setup_block(user, first_week=first_week, offer_lighter=offer_lighter),
    )
    prompt = build_briefing_voice_prompt(
        date_local=clock.date_str,
        blocks=blocks,
        winback=winback.is_winback and wind_down is None,
        is_first_briefing=is_first,
        recent_openings=await _recent_openings(user_id),
        wind_down=wind_down,
        first_week=first_week,
        offer_lighter_cadence=offer_lighter,
    )
    tallies = BriefingTallies(done_by_you=len(completed.user), done_by_gaia=len(completed.gaia))
    payload = await _voice_checked_against_items(
        build_user_context(user, auth_provider=None),
        clock,
        prompt,
        _ProseRules(
            counts=facts.counts,
            context=blocks.context,
            require_coverage=not winback.is_winback and wind_down is None,
        ),
        lambda voice: _daily_payload(
            clock, voice, facts.sections, facts.stats, winback.is_winback
        ).model_copy(update={"calendar": calendar, "tallies": tallies}),
    )
    family = _draw_from_bag(user, BriefingBag.EDITION_FAMILY, DAILY_FAMILY_WEIGHTS)
    await _publish(
        user,
        clock,
        BRIEFING_KIND_DAILY,
        payload,
        _Edition(family=family.member, draws=[family]),
        # The idle ladder's goal question, warning and goodbye are messages in
        # their own right, so they push even on an otherwise empty day.
        push=not _is_empty_day(payload) or wind_down is not None or winback.is_winback,
    )
    if facts.carried_ids:
        await pending_brief_items_repository.consume(user_id, facts.carried_ids)
    await _clear_bootstrap(user)

    # The goodbye went out — pause the loop until a reactivation signal.
    if wind_down == dormancy.WIND_DOWN_FINAL:
        await dormancy.enter_dormancy(user_id)
        log.info("briefing.dormancy_entered", user_id=user_id, idle_days=idle_days)
    return BriefingRunOutcome.SENT


async def run_weekly_digest(user_id: str) -> BriefingRunOutcome:
    """Zoom out on the week: completed work, GAIA's and the user's; return how it ended."""
    log.set(component="briefing", operation="run_weekly_digest", user_id=user_id)
    user = await user_repository.get(user_id)
    if user is None:
        raise BriefingGenerationError(f"Cannot brief unknown user {user_id}")
    clock = context.resolve_clock(user.timezone)
    if await _already_delivered(user_id, clock, BRIEFING_KIND_WEEKLY):
        return BriefingRunOutcome.ALREADY_DELIVERED

    # A dormant loop has nothing to zoom out on; the daily run owns reactivation.
    dstate = dormancy.state_from_user(user)
    if (
        dstate.dormant_since
        and await dormancy.latest_activity_since(user.id, dstate.dormant_since) is None
    ):
        log.info("briefing.weekly_dormant_skip", user_id=user_id)
        return BriefingRunOutcome.DORMANT

    # One window for the prose and the tallies: this week, Monday to now.
    completed = await context.gather_completed_since(user_id, context.week_start_utc(clock))
    week = await context.gather_week(user_id, clock, completed)

    prompt = build_weekly_digest_prompt(
        date_local=clock.date_str,
        week_summary_block=_format_week(completed),
    )

    # Bounded: a stalled agent run must fail the cron loudly, not hang the
    # worker slot (observed live 2026-08-07).
    async with asyncio.timeout(WEEKLY_GENERATION_TIMEOUT_SECONDS):
        payload = await _generate_payload(
            build_user_context(user, auth_provider=None), clock, prompt, BRIEFING_KIND_WEEKLY
        )
    payload.kicker = WEEKLY_KICKER
    payload.date = clock.date_str
    payload.hue = hue_for_day(clock.day_of_year)
    payload.generated_at = clock.now_local.strftime("%-I:%M %p")
    payload.week = week
    payload.tallies = BriefingTallies(
        done_by_you=sum(d.you for d in week.days), done_by_gaia=sum(d.gaia for d in week.days)
    )
    await _publish(
        user,
        clock,
        BRIEFING_KIND_WEEKLY,
        payload,
        _Edition(family=WEEKLY_FAMILY, draws=[]),
        push=True,
    )
    return BriefingRunOutcome.SENT
