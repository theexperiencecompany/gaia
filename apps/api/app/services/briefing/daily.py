"""The daily brief: look back since yesterday, choose what matters, voice it and publish it."""

from datetime import UTC, datetime

from app.agents.prompts.briefing_prompts import (
    VoicePromptBlocks,
    VoiceSituation,
    build_briefing_voice_prompt,
    reader_line,
)
from app.constants.briefing import (
    BRIEFING_KIND_DAILY,
    DAILY_KICKER,
    RECENT_OPENINGS_SHOWN,
    SECTION_TITLES,
    BriefingBag,
    BriefingRunOutcome,
)
from app.constants.user_activity import ActivityStatus
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.pending_brief_items import pending_brief_items_repository
from app.db.repositories.signal_memory import signal_memory_repository
from app.db.repositories.users import user_repository
from app.models.briefing_models import (
    BriefingPayload,
    BriefingTallies,
)
from app.models.scout_models import Signal
from app.models.user_models import UserDocument
from app.services.briefing import chat_sync, context, dormancy
from app.services.briefing.artifacts import gather_artifacts
from app.services.briefing.candidates.judge import select_candidates
from app.services.briefing.candidates.pool import (
    CandidateSources,
    gather_candidates,
)
from app.services.briefing.edition_draws import draw_from_bag
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.errors import BriefingGenerationError
from app.services.briefing.facts import (
    TODAY,
    FactSources,
    build_facts,
    user_todos_note,
    work_stats,
)
from app.services.briefing.lifecycle import (
    already_delivered,
    bootstrap_should_skip,
    clear_bootstrap,
    wake_or_skip,
)
from app.services.briefing.prose import Prose, Writing, links_in, voiced_payload, written_brief
from app.services.briefing.publish import Edition, Push, publish_brief
from app.services.briefing.schedule import describe_briefing_schedule
from app.services.briefing.scouts.facts import signals_block
from app.services.briefing.scouts.service import scout_signals
from app.services.briefing.sections import (
    carried_ids,
    chosen_sections,
    chosen_signals,
    event_ids,
    log_selection,
)
from app.services.briefing.slots import (
    referenced_facts,
)
from app.services.integrations.user_integrations import (
    ConnectedIntegration,
    get_connected_integrations_named,
)
from app.services.user_activity.status import activity_status_of
from app.utils.auth_utils import build_user_context
from app.utils.timezone import Timezone
from app.utils.user_display import display_first_name
from shared.py.wide_events import log


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


async def _recent_openings(user_id: str) -> list[str]:
    """Return the opening line of each recent daily brief's message, newest first."""
    recent = await briefing_repository.list_recent(
        user_id, limit=RECENT_OPENINGS_SHOWN, kind=BRIEFING_KIND_DAILY
    )
    messages = [brief.payload.message for brief in recent if brief.payload.message]
    return [next(line.strip() for line in m.splitlines() if line.strip()) for m in messages]


def _is_empty_day(payload: BriefingPayload, signals: list[Signal]) -> bool:
    """Nothing needs the user, in GAIA or their apps, and nothing is on their calendar."""
    return (
        not signals
        and not payload.calendar
        and not any(section.items for section in payload.sections)
    )


async def run_daily_briefing(user_id: str) -> BriefingRunOutcome:
    """Look back, plan, and deliver one daily briefing for the user; return how it ended."""
    log.set(component="briefing", operation="run_daily_briefing", user_id=user_id)
    user = await user_repository.get(user_id)
    if user is None:
        raise BriefingGenerationError(f"Cannot brief unknown user {user_id}")
    clock = context.resolve_clock(user.timezone)
    if await already_delivered(user_id, clock, BRIEFING_KIND_DAILY):
        return BriefingRunOutcome.ALREADY_DELIVERED

    dstate = await wake_or_skip(user)
    if dstate is None:
        return BriefingRunOutcome.DORMANT

    goal_block, has_goal = await context.format_goal_block(user_id, user)
    if bootstrap_should_skip(user, has_goal):
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
    artifacts = gather_artifacts(work)
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
        user_id,
        gathered.pool,
        scouts.criteria,
        seen_at,
        user.timezone or Timezone.utc().value,
        kind=BRIEFING_KIND_DAILY,
    )
    log_selection(len(gathered.pool), selection)
    chosen = chosen_sections(selection, gathered.pool, SECTION_TITLES)
    remembered = chosen_signals(chosen, scouts.remembered)
    signals = [item.signal for _, item in remembered]
    facts = build_facts(
        chosen,
        FactSources(
            artifacts=artifacts,
            open_todos=open_count,
            calendar=calendar,
            event_ids=event_ids(gathered.pool),
            span=TODAY,
            todos_note=user_todos_note(open_count, open_titles),
        ),
        clock,
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
    )
    voice, draft = await written_brief(
        build_user_context(user, auth_provider=None),
        clock,
        prompt,
        Writing(
            values=facts.values,
            context=blocks.context,
            must_mention=frozenset()
            if winback.is_winback or ladder.wind_down is not None
            else facts.must_mention,
            kind=BRIEFING_KIND_DAILY,
        ),
    )
    links = await links_in(user_id, voice.message, facts)
    payload = voiced_payload(
        clock,
        Prose(voice, draft, links),
        facts,
        kicker=DAILY_KICKER,
        mood="winback" if winback.is_winback else draft.mood,
    ).model_copy(
        update={
            "stats": work_stats(work),
            "calendar": calendar,
            "tallies": BriefingTallies(
                done_by_you=len(completed.user), done_by_gaia=len(completed.gaia)
            ),
            "sources_read": gathered.sources_read,
            "sources_unavailable": gathered.sources_unavailable,
        }
    )
    family = draw_from_bag(user, BriefingBag.EDITION_FAMILY, DAILY_FAMILY_WEIGHTS)
    await publish_brief(
        user,
        clock,
        BRIEFING_KIND_DAILY,
        payload,
        Edition(family=family.member, draws=[family]),
        # The idle ladder's goal question, warning and goodbye are messages in
        # their own right, so they push even on an otherwise empty day.
        Push(
            push=not _is_empty_day(payload, signals)
            or ladder.wind_down is not None
            or winback.is_winback,
            signal_count=len(signals),
        ),
    )
    spoken = referenced_facts(voice.message)
    await signal_memory_repository.mark_shown(
        user_id, [item.signal for i, item in remembered if i in spoken], datetime.now(UTC)
    )
    carried = carried_ids(selection, gathered.pool, gathered.duplicate_held_ids)
    if carried:
        await pending_brief_items_repository.consume(user_id, carried)
    await clear_bootstrap(user)
    await dormancy.leave_idle_ladder(user_id, ladder)
    return BriefingRunOutcome.SENT
