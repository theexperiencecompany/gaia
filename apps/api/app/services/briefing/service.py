"""BriefingService: the daily/weekly run pipeline.

The agent only turns gathered context into one BriefingPayload; invalid output fails
the run loudly and stores nothing. Persistence precedes delivery so the dashboard
never misses a brief that reached a channel.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import random
import re
from uuid import uuid4

from pydantic import BaseModel

from app.agents.core.agent import AgentRunOptions, call_agent_silent
from app.agents.core.background.platform_chat import PlatformImage, post_to_platform_chat
from app.agents.prompts.briefing_prompts import (
    VoicePromptBlocks,
    VoiceSituation,
    build_briefing_voice_prompt,
    build_weekly_digest_prompt,
    reader_line,
    voice_correction_note,
    voice_unreadable_note,
)
from app.constants.briefing import (
    BOOTSTRAP_GRACE_DAYS,
    BRIEFING_KIND_DAILY,
    BRIEFING_KIND_WEEKLY,
    DAILY_KICKER,
    DAILY_SECTION_ORDER,
    GAIA_APP_NAME,
    MAX_BRIEF_ITEMS,
    MAX_VOICE_ATTEMPTS,
    POSTAL_FAMILY,
    RECENT_OPENINGS_SHOWN,
    SECTION_NUMERALS,
    SECTION_TITLES,
    WEEKLY_FAMILY,
    WEEKLY_GENERATION_TIMEOUT_SECONDS,
    WEEKLY_KICKER,
    BriefingBag,
    BriefingRunOutcome,
    SectionKey,
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
from app.db.repositories.signal_memory import signal_memory_repository
from app.db.repositories.users import user_repository
from app.models.brief_candidate_models import BriefCandidate
from app.models.briefing_models import (
    BRIEFING_ITEM_STATES,
    NEEDS_YOU_ITEM_KINDS,
    BriefingEvent,
    BriefingItem,
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
from app.models.scout_models import RememberedSignal, Signal
from app.models.short_link_models import ShortLinkTargetType
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser, ShuffleBag, UserDocument
from app.services.analytics_service import capture
from app.services.briefing import chat_sync, context, dormancy
from app.services.briefing.candidates.judge import BriefSelection, CandidatePool, select_candidates
from app.services.briefing.candidates.pool import CandidateSources, gather_candidates
from app.services.briefing.candidates.subjects import subject_key
from app.services.briefing.context import UserClock
from app.services.briefing.conversation import post_brief_message
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.editions.stamps import hosted_stamp_weights
from app.services.briefing.link_tokens import LINK_TOKEN_RE, link_token, link_token_problems
from app.services.briefing.message import (
    brief_message,
    brief_path,
    chat_text,
    delivered_message,
)
from app.services.briefing.postmarks import new_stamp
from app.services.briefing.schedule import describe_briefing_schedule
from app.services.briefing.scouts.facts import signals_block
from app.services.briefing.scouts.service import scout_signals
from app.services.briefing.shuffle_bag import draw
from app.services.briefing.store import StoredBrief, store_brief
from app.services.briefing.view import briefing_card, briefing_view
from app.services.briefing.voice_check import (
    VoicedCounts,
    message_char_limit,
    message_contradictions,
    voice_contradictions,
    voiced_signals,
)
from app.services.canvas_markdown import deliverable_size
from app.services.delivery.chat_channel import ChatChannel, resolve_proactive_target
from app.services.integrations.user_integrations import (
    ConnectedIntegration,
    get_connected_integrations_named,
)
from app.services.notification_service import notification_service
from app.services.outbound_delivery import OutboundResult
from app.services.short_link_service import optional_short_link
from app.services.user_activity.status import activity_status_of
from app.utils.auth_utils import build_user_context
from app.utils.markdown_utils import decode_json_blocks, model_from_reply
from app.utils.notification.channel_preferences import normalize_channel_preferences
from app.utils.timezone import Timezone
from app.utils.user_display import display_first_name, display_name
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingSent
from shared.py.wide_events import log


class BriefingGenerationError(Exception):
    """The agent did not produce a valid BriefingPayload — the run failed."""


class VoiceUnreadableError(BriefingGenerationError):
    """The daily run's reply held no voice JSON; problems name why, never its text."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(f"No valid voice JSON in agent output: {'; '.join(problems)}")
        self.problems = problems


def _parse_payload(raw: str, family: str) -> BriefingPayload:
    """Extract and validate the single BriefingPayload from the agent output, in the family.

    call_agent_silent swallows its errors into a plain string, which fails validation
    here, so no partial briefing is stored.
    """
    for data in decode_json_blocks(raw).values:
        if isinstance(data, dict) and "headline" in data:
            payload = BriefingPayload.model_validate({**data, "template_family": family})
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
    user: AuthenticatedUser, clock: UserClock, prompt: str, kind: BriefingKind, family: str
) -> BriefingPayload:
    return _parse_payload(await _run_silent(user, clock, prompt, conversation_key=kind), family)


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


@dataclass
class _ArtifactFact:
    """What the voice pass balances per item.

    A concrete summary it always voices, the deliverable size as a HINT (not a verdict —
    a long research trail behind a one-line decision is not a thing to open), and whether
    it is waiting on the user. The pass summarises everything and links only what's
    genuinely a deliverable-to-open or waiting on the user.
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


def _gather_artifacts(work: context.TrackedWork) -> dict[str, _ArtifactFact]:
    """Build, per tracked item, a summary and the voice pass's two signals.

    The signals are whether the deliverable is big and whether it waits on the user.
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
            chars=deliverable_size(canvas),
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
    stored: StoredBrief,
    payload: BriefingPayload,
    notification_kind: str,
    *,
    push: bool,
) -> list[str]:
    """Deliver one brief in-app and, when pushed, to email and the user's chat.

    The orchestrator gets only in-app (plus email when wanted), never the chat platform:
    that message is the edition photo, posted through post_to_platform_chat.
    """
    kind: BriefingKind = stored.briefing.kind
    message = delivered_message(payload)
    target = await resolve_proactive_target(user.id) if push else None
    channel = target if isinstance(target, ChatChannel) else None
    card = briefing_card(briefing_view(stored.briefing))
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
                                url=brief_path(stored.briefing.id),
                                open_in_new_tab=False,
                                close_notification=True,
                            )
                        ),
                    )
                ],
            ),
            metadata={
                **card.model_dump(exclude={"kind"}),
                "kind": notification_kind,
                "brief_url": stored.link,
            },
        )
    )
    await post_brief_message(user.id, message, card)
    delivered = [c.channel_type for c in record.channels if c.reached_user]
    if channel:
        text = chat_text(payload, stored.link)
        result = await _post_to_chat(user, channel, text, stored.image.chat_url, kind)
        if result is OutboundResult.PUBLISHED:
            delivered.append(channel.source.value)
    return delivered


@dataclass(frozen=True)
class _Chosen:
    """The brief's sections, each item beside the candidate it came from, in the same order."""

    sections: list[BriefingSection]
    picked: list[list[BriefCandidate]]


def _chosen(selection: BriefSelection, pool: CandidatePool) -> _Chosen:
    """Lay the judge's selection out as the brief's sections, in reading order, empty ones left out."""
    filled = [
        (key, selection.sections[key]) for key in DAILY_SECTION_ORDER if selection.sections.get(key)
    ]
    return _Chosen(
        sections=[
            BriefingSection(
                numeral=SECTION_NUMERALS[n],
                title=SECTION_TITLES[key],
                key=key,
                items=[selection.items[i] for i in ids],
                more=selection.more.get(key, 0),
            )
            for n, (key, ids) in enumerate(filled)
        ],
        picked=[[pool[i] for i in ids] for _, ids in filled],
    )


def _carried_ids(
    selection: BriefSelection, pool: CandidatePool, duplicates: list[str]
) -> list[str]:
    """Return the held results this brief accounts for: kept, dropped by the judge, or said twice.

    A held result the section caps left out waits for the next brief.
    """
    accounted = [i for ids in selection.sections.values() for i in ids] + selection.dropped
    return [held for i in accounted if (held := pool[i].held_id) is not None] + duplicates


def _chosen_signals(chosen: _Chosen, remembered: list[RememberedSignal]) -> list[RememberedSignal]:
    """Return the app signals the judge kept, with their memory, for the writer's apps block."""
    kept = {
        (c.signal.integration_id, c.signal.external_id)
        for picked in chosen.picked
        for c in picked
        if c.signal is not None
    }
    return [r for r in remembered if (r.signal.integration_id, r.signal.external_id) in kept]


def _fact_line(item: BriefingItem, detail: str | None = None) -> str:
    line = f"- {BRIEFING_ITEM_STATES[item.kind]}: {item.text}"
    if item.app and item.app != GAIA_APP_NAME:
        line += f" | in {item.app}"
    if detail:
        line += f" | detail: {detail}"
    if item.count > 1:
        line += f" | {item.count} requests, one item"
    return line


def _work_fact_line(item: BriefingItem, art: _ArtifactFact, token: str | None) -> str:
    line = _fact_line(item)
    if art.snippet:
        line += f" | summary: {art.snippet}"
    line += f" | artifact holds ~{art.chars} chars"
    if art.action:
        line += " | waiting on you"
    return line if token is None else f"{line} | link: {token}"


@dataclass
class _Facts:
    """The brief's sections and stats, and the facts block the model voices."""

    sections: list[BriefingSection]
    stats: list[BriefingStat]
    counts: VoicedCounts
    block: str
    # Link-token number -> the todo it stands for, resolved by _link_voiced_items.
    link_targets: dict[int, str]


def _work_stats(work: context.TrackedWork) -> list[BriefingStat]:
    """Build the stat row: one figure per non-empty tracked-work state, counted by subject."""
    figures = (
        (work.completed, "done since yesterday"),
        (work.running, "in progress"),
        (work.blocked, "waiting on you"),
    )
    return [
        BriefingStat(value=str(len({subject_key(d) for d in docs})), label=label)
        for docs, label in figures
        if docs
    ]


def _build_facts(
    chosen: _Chosen,
    work: context.TrackedWork,
    artifacts: dict[str, _ArtifactFact],
    open_todos: int,
    notes: str,
) -> _Facts:
    """Assemble the facts block the model voices from the chosen sections.

    The rendered sections come from the selection so the brief cannot lie. Each todo fact
    gives the model a summary, whether it is big or waiting on the user, and a link token
    that becomes the item's heygaia.link only if the voice pass writes it into the message.
    App signals are voiced from their own block, with what earlier briefs said of them.
    """
    link_targets: dict[int, str] = {}
    items = [it for sec in chosen.sections for it in sec.items]
    counts = VoicedCounts(
        waiting_on_you=sum(1 for it in items if it.kind in NEEDS_YOU_ITEM_KINDS),
        done=sum(1 for it in items if it.kind == "lookback"),
        in_progress=sum(1 for it in items if it.kind == "gaia"),
        while_away=sum(1 for it in items if it.kind == "note"),
        open_todos=open_todos,
    )
    voiced = " · ".join(f"{label}: {n}" for label, n in counts.shown())
    fact_lines: list[str] = [f"[COUNTS] {voiced}"] if voiced else []
    for sec, picked in zip(chosen.sections, chosen.picked, strict=True):
        fact_lines.append(f"[{sec.title}]")
        for it, candidate in zip(sec.items, picked, strict=True):
            if candidate.signal is not None:
                continue
            if it.todo_id is None:
                fact_lines.append(_fact_line(it, candidate.detail))
                continue
            art = artifacts[it.todo_id]
            token = None
            if art.chars:  # an empty deliverable has nothing to open, so nothing to link
                token = link_token(len(link_targets))
                link_targets[len(link_targets)] = it.todo_id
            fact_lines.append(_work_fact_line(it, art, token))
    if not chosen.sections:
        fact_lines.append(
            "GAIA has no tracked work and no background work ran. Do not claim anything "
            "ran, finished, or is pending beyond what is stated here."
        )
    fact_lines.append(notes)
    return _Facts(chosen.sections, _work_stats(work), counts, "\n".join(fact_lines), link_targets)


async def _link_voiced_items(
    user_id: str, payload: BriefingPayload, link_targets: dict[int, str]
) -> None:
    """Turn each link token the voice pass wrote into a markdown link on its phrase.

    Only a linked item is minted and carries the link on the stored brief, so a
    forwarded brief exposes exactly what it links. An item is linked once: a repeat,
    or an item whose sharing is off, leaves just its phrase.
    """
    message = brief_message(payload)
    used = {int(m.group(2)) for m in LINK_TOKEN_RE.finditer(message)}
    urls: dict[int, str] = {}
    for index in sorted(used & link_targets.keys()):
        url = await optional_short_link(
            user_id, ShortLinkTargetType.TODO_DELIVERABLE, link_targets[index]
        )
        if url is not None:
            urls[index] = url
    linked = {link_targets[index]: url for index, url in urls.items()}
    for section in payload.sections:
        for item in section.items:
            if item.todo_id in linked:
                item.link = linked[item.todo_id]
    linked_once: set[int] = set()

    def phrase_link(match: re.Match[str]) -> str:
        phrase, index = match.group(1), int(match.group(2))
        url = urls.get(index)
        if url is None or index in linked_once:
            return phrase
        linked_once.add(index)
        return f"[{phrase}]({url})"

    payload.message = LINK_TOKEN_RE.sub(phrase_link, message)


class _Voice(BaseModel):
    """The voice-only JSON the daily run's agent writes over the code-built facts."""

    headline: str
    lede: str
    caption: str
    mood: BriefingMood
    message: str


def _parse_voice(raw: str) -> _Voice:
    """Extract the voice-only JSON (headline/lede/caption/mood/message)."""
    parsed = model_from_reply(raw, _Voice)
    if isinstance(parsed, _Voice):
        return parsed
    log.warning("briefing.voice_unreadable", raw_length=len(raw), problems=parsed)
    raise VoiceUnreadableError(parsed)


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
        connected: list[ConnectedIntegration] = await get_connected_integrations_named(user.id)
        apps = [integration["name"] for integration in connected]
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


def _draw_stamp(user: UserDocument, payload: BriefingPayload) -> list[_BagDraw]:
    """Record an Air Mail brief's stamp city on its payload.

    Returns the stamp draw, persisted once the brief is delivered.
    """
    if payload.template_family != POSTAL_FAMILY:
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
    to every needs-you item and event (a winback or wind-down note is exempt); link_ids
    are the link tokens the facts offered.
    """

    counts: VoicedCounts
    context: str
    require_coverage: bool
    signals: list[Signal]
    link_ids: frozenset[int]


def _prose_problems(payload: BriefingPayload, rules: _ProseRules) -> list[str]:
    message = brief_message(payload)
    return (
        voice_contradictions(
            payload.headline,
            payload.lede,
            payload,
            rules.counts,
            context=rules.context,
            signals=rules.signals,
        )
        + message_contradictions(
            message,
            payload,
            rules.counts,
            context=rules.context,
            require_coverage=rules.require_coverage,
            signals=rules.signals,
        )
        + link_token_problems(message, rules.link_ids)
    )


async def _voice_checked_against_items(
    user: AuthenticatedUser,
    clock: UserClock,
    prompt: str,
    rules: _ProseRules,
    build: Callable[[_Voice], BriefingPayload],
) -> BriefingPayload:
    """Voice the brief, then check its headline, lede and message against its final items.

    An unreadable reply or a contradiction is sent back to the model once with the problems
    named; a second failure fails the run before anything is stored or sent.
    """
    note = ""
    failure = BriefingGenerationError("the brief was never voiced")
    for _ in range(MAX_VOICE_ATTEMPTS):
        attempt_prompt = f"{prompt}\n\n{note}" if note else prompt
        raw = await _run_silent(user, clock, attempt_prompt, conversation_key=BRIEFING_KIND_DAILY)
        try:
            payload = build(_parse_voice(raw))
        except VoiceUnreadableError as exc:
            failure, note = exc, voice_unreadable_note(exc.problems)
            continue
        problems = _prose_problems(payload, rules)
        if not problems:
            return payload
        log.warning("briefing.voice_contradicted_items", problems=problems)
        failure = BriefingGenerationError(
            f"The brief's prose contradicts its items: {'; '.join(problems)}"
        )
        note = voice_correction_note(problems)
    raise failure


def _daily_payload(
    clock: UserClock,
    voice: _Voice,
    sections: list[BriefingSection],
    stats: list[BriefingStat],
    is_winback: bool,
    family: str,
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
        template_family=family,
    )


def _is_empty_day(payload: BriefingPayload, signals: list[Signal]) -> bool:
    """Nothing needs the user, in GAIA or their apps, and nothing is on their calendar."""
    return (
        not signals
        and not payload.calendar
        and not any(section.items for section in payload.sections)
    )


@dataclass(frozen=True)
class _Push:
    """Whether a brief goes beyond in-app, and how many app signals it carried."""

    push: bool
    signal_count: int = 0


_NOTIFICATION_KINDS: dict[BriefingKind, str] = {
    BRIEFING_KIND_DAILY: NOTIFICATION_KIND_BRIEFING_DAILY,
    BRIEFING_KIND_WEEKLY: NOTIFICATION_KIND_BRIEFING_WEEKLY,
}


def _section_count(payload: BriefingPayload, key: SectionKey) -> int:
    return sum(len(s.items) for s in payload.sections if s.key is key)


async def _publish(
    user: UserDocument,
    clock: UserClock,
    kind: BriefingKind,
    payload: BriefingPayload,
    draws: list[_BagDraw],
    sending: _Push,
) -> BriefingModel:
    """Draw the stamp, render and store the brief, deliver it and report where it went.

    store_brief mints the link the edition encodes, then renders and stores it, so a
    render failure stores and sends nothing; the one image serves the in-app page, the email and the chat post. A brief
    that is not pushed (sending.push False) goes in-app only and spends no shuffle-bag draw;
    otherwise the draws (the family's and the stamp's) persist after delivery.
    """
    push = sending.push
    spent = [*draws, *_draw_stamp(user, payload)]
    if payload.stamp_city is not None:
        payload.new_stamp = await new_stamp(user.id, payload.stamp_city)
    payload.recipient_name = display_name(user)
    stored = await store_brief(user.id, clock.date_str, kind, payload)
    channels = await _deliver(user, stored, payload, _NOTIFICATION_KINDS[kind], push=push)
    await briefing_repository.set_delivered_channels(user.id, clock.date_str, kind, channels)
    if push:
        await _persist_draws(user.id, spent)
    capture(
        UserId(user.id),
        BriefingSent(
            kind=kind,
            family=payload.template_family,
            mood=payload.mood,
            item_count=sum(len(s.items) for s in payload.sections),
            channel_count=len(channels),
            signal_count=sending.signal_count,
            stamp_collected=payload.new_stamp is not None,
            lead_count=_section_count(payload, SectionKey.LEAD),
            needs_you_count=_section_count(payload, SectionKey.NEEDS_YOU),
            updates_count=_section_count(payload, SectionKey.UPDATES),
            gaia_did_count=_section_count(payload, SectionKey.GAIA_DID),
            source_count=len(payload.sources_read),
        ),
    )
    log.info("briefing.sent", user_id=user.id, kind=kind, channels=channels, pushed=push)
    return stored.briefing


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
    seen_at = datetime.now(UTC)
    scouts = await scout_signals(user, seen_at)
    gathered = await gather_candidates(
        user_id, clock, since, seen_at, CandidateSources(work, held, scouts, calendar)
    )
    selection = await select_candidates(
        user_id, gathered.pool, scouts.criteria, seen_at, user.timezone or Timezone.utc().value
    )
    log.set_ns(
        "brief_selection",
        candidates=len(gathered.pool),
        kept={key.value: len(ids) for key, ids in selection.sections.items()},
        dropped=len(selection.dropped),
        more={key.value: count for key, count in selection.more.items()},
    )
    chosen = _chosen(selection, gathered.pool)
    remembered = _chosen_signals(chosen, scouts.remembered)
    signals = [item.signal for item in remembered]
    facts = _build_facts(
        chosen,
        work,
        artifacts,
        open_count,
        _user_todos_note(open_count, open_titles) + "\n" + _calendar_note(calendar),
    )

    # Idle ladder: nothing to report (no candidate beyond the calendar, no goal
    # knowledge) escalates from the goal question to a plain warning to one
    # goodbye, then dormancy. A new account's first week never climbs it.
    ladder = await dormancy.climb_idle_ladder(
        user, dstate, clock.date_str, has_news=gathered.has_news, has_goal=has_goal
    )
    # A user who stopped coming back is offered fewer briefs, never silently dropped.
    offer_lighter = await activity_status_of(user_id) == ActivityStatus.IDLE

    blocks = VoicePromptBlocks(
        reader=reader_line(display_first_name(user)),
        facts=facts.block,
        goal=goal_block,
        lookback=lookback_block,
        replies=await chat_sync.format_replies_block(user_id, since),
        setup=await _setup_block(user, first_week=ladder.first_week, offer_lighter=offer_lighter),
        signals=signals_block(remembered, seen_at),
    )
    prompt = build_briefing_voice_prompt(
        date_local=clock.date_str,
        blocks=blocks,
        situation=VoiceSituation(
            winback=winback.is_winback and ladder.wind_down is None,
            is_first_briefing=is_first,
            wind_down=ladder.wind_down,
            first_week=ladder.first_week,
            offer_lighter_cadence=offer_lighter,
        ),
        recent_openings=await _recent_openings(user_id),
        max_message_chars=message_char_limit(len(signals)),
    )
    tallies = BriefingTallies(done_by_you=len(completed.user), done_by_gaia=len(completed.gaia))
    family = _draw_from_bag(user, BriefingBag.EDITION_FAMILY, DAILY_FAMILY_WEIGHTS)
    payload = await _voice_checked_against_items(
        build_user_context(user, auth_provider=None),
        clock,
        prompt,
        _ProseRules(
            counts=facts.counts,
            context=blocks.context,
            require_coverage=not winback.is_winback and ladder.wind_down is None,
            signals=signals,
            link_ids=frozenset(facts.link_targets),
        ),
        lambda voice: _daily_payload(
            clock, voice, facts.sections, facts.stats, winback.is_winback, family.member
        ).model_copy(
            update={
                "calendar": calendar,
                "tallies": tallies,
                "sources_read": gathered.sources_read,
                "sources_unavailable": gathered.sources_unavailable,
            }
        ),
    )
    await _link_voiced_items(user_id, payload, facts.link_targets)
    await _publish(
        user,
        clock,
        BRIEFING_KIND_DAILY,
        payload,
        [family],
        # The idle ladder's goal question, warning and goodbye are messages in
        # their own right, so they push even on an otherwise empty day.
        _Push(
            push=not _is_empty_day(payload, signals)
            or ladder.wind_down is not None
            or winback.is_winback,
            signal_count=len(signals),
        ),
    )
    await signal_memory_repository.mark_shown(
        user_id, voiced_signals(payload.message, signals), datetime.now(UTC)
    )
    carried = _carried_ids(selection, gathered.pool, gathered.duplicate_held_ids)
    if carried:
        await pending_brief_items_repository.consume(user_id, carried)
    await _clear_bootstrap(user)
    await dormancy.leave_idle_ladder(user_id, ladder)
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
            build_user_context(user, auth_provider=None),
            clock,
            prompt,
            BRIEFING_KIND_WEEKLY,
            WEEKLY_FAMILY,
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
        [],
        _Push(push=True),
    )
    return BriefingRunOutcome.SENT
