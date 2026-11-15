"""The daily brief: look back since the last one, choose what matters, voice it and publish it."""

from dataclasses import replace
from datetime import UTC, datetime

from app.agents.prompts.briefing_prompts import (
    VoicePromptBlocks,
    VoiceSituation,
    build_briefing_voice_prompt,
)
from app.constants.briefing import (
    BRIEFING_KIND_DAILY,
    DAILY_KICKER,
    RECENT_BRIEFS_RECALLED,
    TODAY_SPAN,
    UNNAMED_READER,
    BriefForm,
    BriefingRunOutcome,
)
from app.constants.integrations import GOOGLE_CALENDAR_INTEGRATION_ID
from app.constants.user_activity import ActivityStatus
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.pending_brief_items import pending_brief_items_repository
from app.db.repositories.users import user_repository
from app.models.brief_composition_models import ChartBlock, QuoteBlock
from app.models.briefing_models import (
    BriefingEvent,
    BriefingModel,
    BriefingPayload,
    BriefingTallies,
    UnreadSource,
)
from app.models.calendar_models import GoogleCalendarEventResource
from app.models.scout_models import ScoutSkipReason
from app.models.user_models import UserDocument
from app.services.briefing import chat_sync, context, dormancy
from app.services.briefing.artifacts import gather_artifacts
from app.services.briefing.candidates.app_names import integration_name
from app.services.briefing.candidates.memory import mark_placed_shown
from app.services.briefing.candidates.pool import (
    CandidateSources,
    GatheredCandidates,
    gather_candidates,
)
from app.services.briefing.composition.compose import compose_brief
from app.services.briefing.edition_draws import draw_edition
from app.services.briefing.errors import BriefingGenerationError
from app.services.briefing.fact_pool.pool import FactPool, PoolContext, PoolReads, build_fact_pool
from app.services.briefing.fact_pool.window import SeriesWindow, daily_window
from app.services.briefing.facts import (
    TODAY,
    FactSources,
    build_facts,
    user_todos_note,
    work_stats,
)
from app.services.briefing.held import held_items
from app.services.briefing.lifecycle import (
    already_delivered,
    bootstrap_should_skip,
    clear_bootstrap,
    wake_or_skip,
)
from app.services.briefing.prose import (
    Prose,
    Writing,
    links_in,
    reader_block,
    recent_lines,
    voiced_payload,
    written_brief,
)
from app.services.briefing.publish import (
    PoolCounts,
    Push,
    publish_brief,
    publish_quiet_note,
    quiet_facts,
    quiet_note,
)
from app.services.briefing.schedule import describe_briefing_schedule
from app.services.briefing.scouts.facts import signals_block
from app.services.briefing.scouts.service import ScoutSignals, scout_signals
from app.services.briefing.sections import (
    Laid,
    carried_ids,
    chosen_signals,
    event_ids,
    lay_out,
    log_composition,
    sources_shown,
)
from app.services.briefing.slots import figures_in
from app.services.integrations.user_integrations import (
    ConnectedIntegration,
    get_connected_integrations_named,
)
from app.services.user_activity.status import activity_status_of
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


def _is_empty_day(payload: BriefingPayload) -> bool:
    """Say whether the composition placed nothing and the user's calendar is empty."""
    return not payload.blocks and not payload.calendar


def _last_daily_was_quiet(briefs: list[BriefingModel]) -> bool:
    """Say whether the latest daily brief, of the recent ones newest first, was a quiet note."""
    last = next((b for b in briefs if b.kind == BRIEFING_KIND_DAILY), None)
    return last is not None and last.payload.form is BriefForm.QUIET_NOTE


def _is_quiet_day(laid: Laid, events: list[BriefingEvent], ladder: dormancy.IdleLadder) -> bool:
    """Say whether today gets the quiet note: no event, nothing the ladder says, and nothing new placed.

    What an earlier brief already showed as it stands is no reason for an edition, nor a
    stalled goal's progress or a note about it; a chart or a quote shows something that moved.
    """
    told = all(c.is_repeat for picked in laid.chosen.picked for _, c in picked)
    shows_movement = any(isinstance(b, ChartBlock | QuoteBlock) for b in laid.blocks)
    return (
        told
        and not shows_movement
        and not events
        and ladder.wind_down is None
        and ladder.goal_question is dormancy.GoalQuestion.ASKED
    )


async def _composed_day(
    user: UserDocument,
    window: SeriesWindow,
    gathered: GatheredCandidates,
    scouts: ScoutSignals,
    reads: tuple[list[context.StatedGoal], list[GoogleCalendarEventResource]],
    pool_context: PoolContext,
) -> tuple[FactPool, Laid]:
    """Build today's fact pool over the week ending today, compose the brief over it and lay it out."""
    goals, calendar = reads
    pool = await build_fact_pool(
        user.id,
        window,
        PoolReads(
            items=gathered.pool,
            signals=[r.signal for r in scouts.remembered],
            calendar=calendar,
            goals=goals,
            criteria=scouts.criteria,
        ),
        pool_context,
        datetime.now(UTC),
    )
    composed = await compose_brief(user.id, pool, BRIEFING_KIND_DAILY)
    laid = lay_out(composed.rendered, pool)
    log_composition(pool, laid)
    return pool, laid


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

    goals = await context.stated_goals(user_id, user)
    goal_block, has_goal = context.format_goal_block(goals)
    if bootstrap_should_skip(user, has_goal):
        log.info("briefing.bootstrap_pending_skip", user_id=user_id)
        return BriefingRunOutcome.BOOTSTRAP_PENDING

    # Gather the world the agent must see.
    last = await context.last_brief(user_id, clock)
    since = context.lookback_since(clock, last)
    lookback_block = await context.format_lookback_block(user_id, last, since, clock)
    winback = await context.compute_winback_state(user)
    is_first = not await briefing_repository.has_daily_briefing(user_id)

    # Gone-quiet backoff: a winback already went out and the user is still silent.
    if winback.should_back_off:
        log.info("briefing.winback_backoff", user_id=user_id, unacknowledged=winback.unacknowledged)
        return BriefingRunOutcome.WINBACK_BACKOFF

    # Facts are assembled by code from tracked-work state; the model composes and voices them.
    work = await context.gather_tracked_work(user_id, since)
    artifacts = gather_artifacts(work)
    todos = await context.count_own_todos(user_id, clock)
    window = daily_window(clock)
    day = await context.read_day_calendar(user_id, clock, window.start, window.end)
    completed = await context.gather_completed_since(user_id, since)
    held = await held_items(user_id)
    seen_at = datetime.now(UTC)
    scouts = await scout_signals(user, seen_at)
    gathered = await gather_candidates(
        user_id, clock, since, seen_at, CandidateSources(work, scouts, day.events, held=held)
    )
    briefs = await briefing_repository.list_recent(user_id, limit=RECENT_BRIEFS_RECALLED)
    recent = recent_lines(briefs)
    pool, laid = await _composed_day(
        user,
        window,
        gathered,
        scouts,
        (goals, day.week),
        PoolContext(
            reader=display_first_name(user) or UNNAMED_READER,
            clock=clock,
            calendar=day.tally,
            calendar_span=TODAY_SPAN,
            done_since=since,
            recent_openings=recent.openings,
            unread=gathered.sources_unavailable,
        ),
    )
    remembered = chosen_signals(laid.chosen, scouts.remembered)
    facts = build_facts(
        laid.chosen,
        FactSources(
            artifacts=artifacts,
            open_todos=todos.open,
            calendar=day.today,
            event_ids=event_ids(gathered.pool),
            span=TODAY,
            todos_note=user_todos_note(todos.open, todos.overdue, work.open_subjects.total),
            blocks=laid.blocks,
            overdue_todos=todos.overdue,
            open_tracked=work.open_subjects.total,
            unread=gathered.sources_unavailable,
        ),
        clock,
    )

    # Idle ladder: nothing to report and no goal (or an ignored goal question) escalates
    # to a plain warning, one goodbye, then dormancy; the ladder also says whether today
    # asks about the goal. A new account's first week never climbs it.
    ladder = await dormancy.climb_idle_ladder(
        user, dstate, clock.date_str, has_news=gathered.has_news, has_goal=has_goal
    )
    if not winback.is_winback and not is_first and _is_quiet_day(laid, day.events, ladder):
        return await _quiet_day(user, clock, (day, todos.overdue), (gathered, pool, ladder), briefs)

    # A user who stopped coming back is offered fewer briefs, never silently dropped.
    offer_lighter = await activity_status_of(user_id) == ActivityStatus.IDLE

    blocks = VoicePromptBlocks(
        reader=reader_block(user),
        facts=facts.block,
        goal=goal_block,
        lookback=lookback_block,
        replies=await chat_sync.format_replies_block(user_id, since),
        setup=await _setup_block(user, first_week=ladder.first_week, offer_lighter=offer_lighter),
        signals=signals_block(remembered, clock),
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
            goal_asked_recently=ladder.goal_question is dormancy.GoalQuestion.ASKED,
        ),
        recent=recent,
    )
    voice, draft = await written_brief(
        user_id,
        prompt,
        Writing(
            # What was done since the last brief is the user's own record, quotable as it stands.
            values=replace(facts.values, quoted=facts.values.quoted | figures_in([lookback_block])),
            lead=None if winback.is_winback or ladder.wind_down is not None else facts.lead,
            recent=recent,
            grounds=f"{facts.block}\n{blocks.signals}",
        ),
    )
    links = await links_in(user_id, voice.message, facts)
    edition = draw_edition(user, laid.blocks)
    payload = voiced_payload(
        clock,
        Prose(voice, draft, links),
        facts,
        kicker=DAILY_KICKER,
        mood="winback" if winback.is_winback else draft.mood,
        family=edition.family.member,
    ).model_copy(
        update={
            "stats": work_stats(work),
            "calendar": day.events,
            "tallies": BriefingTallies(
                done_by_you=len(completed.user), done_by_gaia=len(completed.gaia)
            ),
            "sources_read": sources_shown(laid, gathered.pool),
            "sources_unavailable": [*gathered.sources_unavailable, *_calendar_unread(day.today)],
            "blocks": edition.drawn,
            "undrawn": edition.undrawn,
            "uncomposed": laid.uncomposed,
        }
    )
    await publish_brief(
        user,
        clock,
        BRIEFING_KIND_DAILY,
        payload,
        [edition.family],
        # The idle ladder's goal question, warning and goodbye are messages in
        # their own right, so they push even on an otherwise empty day.
        Push(
            push=not _is_empty_day(payload) or ladder.wind_down is not None or winback.is_winback,
            signal_count=len(remembered),
            pool=PoolCounts.of(pool),
        ),
    )
    await mark_placed_shown(
        user_id, [c for picked in laid.chosen.picked for _, c in picked], datetime.now(UTC)
    )
    await _settle(user, ladder, gathered)
    return BriefingRunOutcome.SENT


async def _quiet_day(
    user: UserDocument,
    clock: context.UserClock,
    reads: tuple[context.DayCalendar, int],
    run: tuple[GatheredCandidates, FactPool, dormancy.IdleLadder],
    briefs: list[BriefingModel],
) -> BriefingRunOutcome:
    """Send the quiet note, or nothing when the last daily already was one: until something real happens."""
    day, overdue = reads
    gathered, pool, ladder = run
    if _last_daily_was_quiet(briefs):
        # Nothing is shown: no question went out, and the held results wait for the next brief.
        log.info("briefing.quiet_day_silent", user_id=user.id)
        return BriefingRunOutcome.SILENT
    gap = day.today.gap if isinstance(day.today, context.CalendarUnread) else None
    facts = await quiet_facts(
        user.id, BRIEFING_KIND_DAILY, briefs, (gap, overdue, gathered.sources_unavailable)
    )
    await publish_quiet_note(
        user,
        clock,
        BRIEFING_KIND_DAILY,
        quiet_note(clock, BRIEFING_KIND_DAILY, facts),
        PoolCounts.of(pool),
    )
    await _settle(user, ladder, gathered)
    return BriefingRunOutcome.SENT


async def _settle(
    user: UserDocument, ladder: dormancy.IdleLadder, gathered: GatheredCandidates
) -> None:
    """Close a sent run: clear the held results it accounted for, the bootstrap and the ladder's rung."""
    carried = carried_ids(gathered.pool, gathered.duplicate_held_ids)
    if carried:
        await pending_brief_items_repository.consume(user.id, carried)
    await clear_bootstrap(user)
    await dormancy.leave_idle_ladder(user.id, ladder)


def _calendar_unread(
    calendar: list[BriefingEvent] | context.CalendarUnread,
) -> list[UnreadSource]:
    """Name the calendar as a source the brief could not read, when a connected one did not answer."""
    if (
        isinstance(calendar, context.CalendarUnread)
        and calendar.gap is context.CalendarGap.UNAVAILABLE
    ):
        return [
            UnreadSource(
                app=integration_name(GOOGLE_CALENDAR_INTEGRATION_ID), reason=ScoutSkipReason.FAILED
            )
        ]
    return []
