"""The weekly digest: zoom out on the week since Monday and the week ahead.

It runs the daily's machinery over the week: the same producers and memory, the same
voice checks against every recent brief, and the same quiet note when the week held nothing.
"""

import asyncio
from datetime import UTC, datetime

from app.agents.prompts.briefing_prompts import (
    VoicePromptBlocks,
    build_weekly_voice_prompt,
)
from app.constants.briefing import (
    BRIEFING_KIND_WEEKLY,
    GAIA_SOURCE,
    RECENT_BRIEFS_RECALLED,
    UNNAMED_READER,
    WEEK_AHEAD_SPAN,
    WEEKLY_FAMILY,
    WEEKLY_GENERATION_TIMEOUT_SECONDS,
    WEEKLY_KICKER,
    BriefingRunOutcome,
)
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.users import user_repository
from app.models.brief_pool_models import DataSeries, SeriesShape
from app.models.briefing_models import BriefingEvent, BriefingModel, BriefingTallies
from app.models.user_models import UserDocument
from app.services.briefing import context, dormancy
from app.services.briefing.artifacts import gather_artifacts
from app.services.briefing.candidates.memory import mark_placed_shown
from app.services.briefing.candidates.pool import (
    CandidateSources,
    gather_candidates,
)
from app.services.briefing.composition.compose import compose_brief
from app.services.briefing.editions.capabilities import split_drawable
from app.services.briefing.errors import BriefingGenerationError
from app.services.briefing.fact_pool.pool import FactPool, PoolContext, PoolReads, build_fact_pool
from app.services.briefing.fact_pool.window import week_window
from app.services.briefing.facts import (
    WEEK_AHEAD,
    FactSources,
    WeekRecap,
    build_facts,
    user_todos_note,
)
from app.services.briefing.lifecycle import (
    already_delivered,
)
from app.services.briefing.metrics import counted_run
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
from app.services.briefing.scouts.facts import signals_block
from app.services.briefing.scouts.service import scout_signals
from app.services.briefing.sections import (
    chosen_signals,
    event_ids,
    lay_out,
    log_composition,
    sources_shown,
)
from app.services.hil.utils import untrusted_fence
from app.utils.user_display import display_first_name
from shared.py.wide_events import log

#: What the week in numbers counts: GAIA's own work and the mail its desk handled.
_RECAP_SOURCES = frozenset({GAIA_SOURCE, GMAIL_INTEGRATION_ID})


def _recap_series(series: list[DataSeries]) -> list[DataSeries]:
    """Return the week's day-by-day counts of GAIA's work and its mail desk, each with a total."""
    return [s for s in series if s.shape is SeriesShape.TIME_SERIES and s.source in _RECAP_SOURCES]


def _is_empty_week(pool: FactPool) -> bool:
    """Say whether the week holds nothing to recap: nothing done, due, waiting, found or ahead.

    Undated todos of their own are backlog, never a week's news; a goal whose work moved or
    sat stuck all week is the recap's first answer.
    """
    return all(c.backlog for c in pool.items.values()) and not any(
        goal.done or goal.stalled for goal in pool.goals
    )


async def _send_quiet_week(
    user: UserDocument,
    clock: context.UserClock,
    briefs: list[BriefingModel],
    reads: tuple[list[BriefingEvent] | context.CalendarUnread, int],
    pool: FactPool,
) -> None:
    """Send the week's quiet note, the daily's quiet path: reads are the week ahead and overdue."""
    ahead, overdue = reads
    gap = ahead.gap if isinstance(ahead, context.CalendarUnread) else None
    unread = pool.context.unread
    facts = await quiet_facts(user.id, BRIEFING_KIND_WEEKLY, briefs, (gap, overdue, unread))
    await publish_quiet_note(
        user,
        clock,
        BRIEFING_KIND_WEEKLY,
        quiet_note(clock, BRIEFING_KIND_WEEKLY, facts),
        PoolCounts.of(pool),
    )


async def run_weekly_digest(user_id: str) -> BriefingRunOutcome:
    """Zoom out on the week since Monday and the week ahead; return how it ended."""
    log.set(component="briefing", operation="run_weekly_digest", user_id=user_id)
    return await counted_run(BRIEFING_KIND_WEEKLY, _weekly(user_id))


async def _weekly(user_id: str) -> BriefingRunOutcome:
    user = await user_repository.get(user_id)
    if user is None:
        raise BriefingGenerationError(f"Cannot brief unknown user {user_id}")
    clock = context.resolve_clock(user.timezone)
    if await already_delivered(user_id, clock, BRIEFING_KIND_WEEKLY):
        return BriefingRunOutcome.ALREADY_DELIVERED

    # A dormant loop has nothing to zoom out on; the daily run owns reactivation.
    dstate = dormancy.state_from_user(user)
    if (
        dstate.dormant_since
        and await dormancy.latest_activity_since(user.id, dstate.dormant_since) is None
    ):
        log.info("briefing.weekly_dormant_skip", user_id=user_id)
        return BriefingRunOutcome.DORMANT

    # One window for the candidates, the prose and the tallies: this week, Monday to now.
    since = context.week_start_utc(clock)
    work = await context.gather_tracked_work(user_id, since)
    completed = await context.gather_completed_since(user_id, since)
    ahead = await context.gather_calendar(user_id, clock, days=WEEK_AHEAD.days, days_ahead=1)
    ahead_events: list[BriefingEvent] = ahead if isinstance(ahead, list) else []
    week = context.count_week(clock, completed, ahead)
    todos = await context.count_own_todos(user_id, clock)
    seen_at = datetime.now(UTC)
    scouts = await scout_signals(user, seen_at)
    gathered = await gather_candidates(
        user_id,
        clock,
        since,
        seen_at,
        CandidateSources(
            work,
            scouts,
            ahead_events,
            ahead_days=WEEK_AHEAD.days + 1,
            user_done=completed.user,
        ),
    )
    briefs = await briefing_repository.list_recent(user_id, limit=RECENT_BRIEFS_RECALLED)
    recent = recent_lines(briefs)
    goals = await context.stated_goals(user_id, user)
    goal_block, _ = context.format_goal_block(goals)
    window = week_window(clock)
    past = await context.read_calendar(user_id, window.start, window.end)
    pool = await build_fact_pool(
        user_id,
        window,
        PoolReads(
            items=gathered.pool,
            signals=[r.signal for r in scouts.remembered],
            calendar=past if isinstance(past, list) else [],
            goals=goals,
            criteria=scouts.criteria,
        ),
        PoolContext(
            reader=display_first_name(user) or UNNAMED_READER,
            clock=clock,
            calendar=len(ahead_events) if isinstance(ahead, list) else ahead.gap,
            calendar_span=WEEK_AHEAD_SPAN,
            done_since=since,
            recent_openings=recent.openings,
            unread=gathered.sources_unavailable,
        ),
        seen_at,
    )
    if _is_empty_week(pool):
        await _send_quiet_week(user, clock, briefs, (ahead, todos.overdue), pool)
        return BriefingRunOutcome.SENT
    composed = await compose_brief(user_id, pool, BRIEFING_KIND_WEEKLY)
    laid = lay_out(composed.rendered, pool)
    log_composition(pool, laid)
    remembered = chosen_signals(laid.chosen, scouts.remembered)
    facts = build_facts(
        laid.chosen,
        FactSources(
            artifacts=gather_artifacts(work),
            open_todos=todos.open,
            calendar=ahead,
            event_ids=event_ids(gathered.pool),
            span=WEEK_AHEAD,
            todos_note=user_todos_note(todos.open, todos.overdue, work.open_subjects.total),
            blocks=laid.blocks,
            overdue_todos=todos.overdue,
            open_tracked=work.open_subjects.total,
            unread=gathered.sources_unavailable,
            recap=WeekRecap(series=_recap_series(pool.series), goals=pool.goals),
        ),
        clock,
    )
    blocks = VoicePromptBlocks(
        reader=reader_block(user),
        facts=facts.block,
        goal=goal_block,
        signals=signals_block(remembered, clock),
    )
    # Bounded: a stalled agent run must fail the cron loudly, not hang the
    # worker slot (observed live 2026-08-07).
    async with asyncio.timeout(WEEKLY_GENERATION_TIMEOUT_SECONDS):
        voice, draft = await written_brief(
            user_id,
            build_weekly_voice_prompt(
                date_local=clock.date_str, blocks=blocks, recent=recent, fence=untrusted_fence()
            ),
            Writing(
                values=facts.values,
                lead=facts.lead,
                recent=recent,
                grounds=f"{facts.block}\n{blocks.signals}",
            ),
        )
    links = await links_in(user_id, voice.message, facts)
    drawn, undrawn = split_drawable(WEEKLY_FAMILY, laid.blocks)
    payload = voiced_payload(
        clock,
        Prose(voice, draft, links),
        facts,
        kicker=WEEKLY_KICKER,
        mood="weekly",
        family=WEEKLY_FAMILY,
    ).model_copy(
        update={
            "week": week,
            "tallies": BriefingTallies(
                done_by_you=sum(d.you for d in week.days),
                done_by_gaia=sum(d.gaia for d in week.days),
            ),
            "sources_read": sources_shown(laid, gathered.pool),
            "sources_unavailable": gathered.sources_unavailable,
            "blocks": drawn,
            "undrawn": undrawn,
            "uncomposed": laid.uncomposed,
        }
    )
    await publish_brief(
        user,
        clock,
        BRIEFING_KIND_WEEKLY,
        payload,
        [],
        Push(push=True, signal_count=len(remembered), pool=PoolCounts.of(pool)),
    )
    await mark_placed_shown(
        user_id, [c for picked in laid.chosen.picked for _, c in picked], datetime.now(UTC)
    )
    return BriefingRunOutcome.SENT
