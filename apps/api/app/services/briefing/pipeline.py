"""One brief run, daily or weekly: read the world once, compose and voice it, draw its edition, publish it.

Everything that differs by kind is on its BriefKindSpec (windows, quiet rule, edition, masthead)
or its Standing (where the reader stands); the run itself is one pipeline.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from app.agents.prompts.briefing_prompts import RecentLines
from app.constants.briefing import (
    GAIA_SOURCE,
    RECENT_BRIEFS_RECALLED,
    UNNAMED_READER,
    BriefingKind,
    BriefingRunOutcome,
)
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.users import user_repository
from app.models.brief_pool_models import DataSeries, SeriesShape
from app.models.briefing_models import BriefingModel, BriefingTallies
from app.models.user_models import UserDocument
from app.services.briefing.artifacts import gather_artifacts
from app.services.briefing.calendar_read import CalendarRead, read_calendar
from app.services.briefing.candidates.memory import mark_placed_shown
from app.services.briefing.candidates.pool import (
    CandidateSources,
    GatheredCandidates,
    gather_candidates,
)
from app.services.briefing.clock import DayWindow, UserClock, resolve_clock
from app.services.briefing.composition.compose import compose_brief
from app.services.briefing.edition_draws import draw_edition
from app.services.briefing.errors import BriefingGenerationError
from app.services.briefing.fact_pool.pool import FactPool, PoolContext, PoolReads, build_fact_pool
from app.services.briefing.facts import (
    Facts,
    FactSources,
    WeekRecap,
    build_facts,
    user_todos_note,
    work_stats,
)
from app.services.briefing.held import held_items
from app.services.briefing.kinds import KIND_SPECS, BriefKindSpec
from app.services.briefing.lifecycle import already_delivered
from app.services.briefing.metrics import counted_run
from app.services.briefing.payload import PayloadParts, edition_payload
from app.services.briefing.postmarks import new_stamp
from app.services.briefing.prose import Prose, links_in, recent_lines, written_brief
from app.services.briefing.publish import PoolCounts, Sending, finish_started_delivery, publish
from app.services.briefing.quiet_note import QuietFacts, continued, last_was_quiet, quiet_note
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
from app.services.briefing.standing import Standing, VoiceInputs
from app.services.briefing.work import BriefReads, OwnTodos, TrackedWork, count_week, read_work
from app.utils.user_display import display_first_name, display_name
from shared.py.wide_events import log

#: What a digest's week in numbers counts: GAIA's own work and the mail its desk handled.
_RECAP_SOURCES = frozenset({GAIA_SOURCE, GMAIL_INTEGRATION_ID})


@dataclass(frozen=True)
class RunReads:
    """Everything one run read, once, before anything is composed."""

    reads: BriefReads
    work: TrackedWork
    todos: OwnTodos
    calendar: CalendarRead
    #: The local days the series and goals cover.
    window: DayWindow
    scouts: ScoutSignals
    gathered: GatheredCandidates
    #: The recent briefs, newest first, every kind.
    briefs: list[BriefingModel]
    recent: RecentLines


@dataclass(frozen=True)
class Run:
    """One run's settled inputs: who, on whose clock, which kind, where the reader stands, what it read."""

    user: UserDocument
    clock: UserClock
    spec: BriefKindSpec
    standing: Standing
    reads: RunReads


async def run_brief(user_id: str, kind: BriefingKind) -> BriefingRunOutcome:
    """Run one brief of kind for the user; return how it ended."""
    log.set(component="briefing", operation="run_brief", user_id=user_id)
    log.set_ns("briefing", kind=kind)
    return await counted_run(kind, _run(user_id, KIND_SPECS[kind]))


async def _run(user_id: str, spec: BriefKindSpec) -> BriefingRunOutcome:
    user = await user_repository.get(user_id)
    if user is None:
        raise BriefingGenerationError(f"Cannot brief unknown user {user_id}")
    clock = resolve_clock(user.timezone)
    if await already_delivered(user_id, clock, spec.kind):
        return BriefingRunOutcome.ALREADY_DELIVERED
    if await finish_started_delivery(user, clock, spec.kind):
        return BriefingRunOutcome.SENT
    stood = await spec.stand(user, clock)
    if isinstance(stood, BriefingRunOutcome):
        return stood
    reads = await _read(user, clock, spec, stood)
    run = Run(user, clock, spec, await stood.climbed(reads.gathered), reads)
    pool = await _pool(run)
    if run.standing.quiet_before_composing(pool):
        return await _quiet(run, pool)
    composed = await compose_brief(user_id, pool, spec)
    laid = lay_out(composed.rendered, pool)
    log_composition(pool, laid)
    if run.standing.quiet_after_composing(laid, reads.calendar):
        return await _quiet(run, pool)
    await _publish_edition(run, pool, laid)
    await mark_placed_shown(
        user_id, [c for picked in laid.chosen.picked for _, c in picked], datetime.now(UTC)
    )
    await run.standing.settle()
    return BriefingRunOutcome.SENT


async def _read(
    user: UserDocument, clock: UserClock, spec: BriefKindSpec, standing: Standing
) -> RunReads:
    """Read what the brief reports, each store once: work, calendar, scouts and candidates."""
    since = standing.since
    window = spec.series_window(clock)
    span = spec.span.window(clock)
    reads = await read_work(user.id, min(since, window.start))
    work = reads.tracked_work(since)
    calendar = await read_calendar(user.id, window, span)
    seen_at = datetime.now(UTC)
    scouts = await scout_signals(user, seen_at)
    gathered = await gather_candidates(
        user.id,
        clock,
        since,
        seen_at,
        CandidateSources(
            work,
            scouts,
            calendar.events,
            # The held results wait for the daily brief, which a digest never carries.
            held=[] if spec.recaps_week else await held_items(user.id),
            due_before=span.end,
            user_done=reads.completed.since(since).user if spec.recaps_week else [],
        ),
    )
    briefs = await briefing_repository.list_recent(user.id, limit=RECENT_BRIEFS_RECALLED)
    return RunReads(
        reads=reads,
        work=work,
        todos=reads.own_todos(clock),
        calendar=calendar,
        window=window,
        scouts=scouts,
        gathered=gathered,
        briefs=briefs,
        recent=recent_lines(briefs),
    )


async def _pool(run: Run) -> FactPool:
    reads = run.reads
    return await build_fact_pool(
        run.user.id,
        reads.window,
        PoolReads(
            items=reads.gathered.pool,
            signals=[r.signal for r in reads.scouts.remembered],
            calendar=reads.calendar.raw,
            goals=run.standing.goals,
            criteria=reads.scouts.criteria,
            work=reads.reads,
        ),
        PoolContext(
            reader=display_first_name(run.user) or UNNAMED_READER,
            clock=run.clock,
            calendar=reads.calendar.tally,
            calendar_span=run.spec.span.words,
            done_since=run.standing.since,
            recent_openings=reads.recent.openings,
            unread=reads.gathered.sources_unavailable,
        ),
        datetime.now(UTC),
    )


def _carried(gathered: GatheredCandidates) -> list[str]:
    return carried_ids(gathered.pool, gathered.duplicate_held_ids)


async def _quiet(run: Run, pool: FactPool) -> BriefingRunOutcome:
    """Send the quiet note; after a quiet note, a kind that does not repeat it stays silent."""
    reads, spec = run.reads, run.spec
    if not spec.repeats_quiet_note and last_was_quiet(reads.briefs, spec.kind):
        # Nothing is shown: no question went out, and the held results wait for the next brief.
        log.info("briefing.quiet_day_silent", user_id=run.user.id)
        return BriefingRunOutcome.SILENT
    facts = await continued(
        run.user.id,
        spec.kind,
        reads.briefs,
        QuietFacts(
            calendar=reads.calendar.gap,
            overdue=reads.todos.overdue,
            unread=reads.gathered.sources_unavailable,
        ),
    )
    await publish(
        run.user,
        run.clock,
        spec,
        quiet_note(run.clock, spec, facts),
        Sending(push=True, pool=PoolCounts.of(pool), held_ids=_carried(reads.gathered)),
    )
    await run.standing.settle()
    return BriefingRunOutcome.SENT


def _recap_series(series: list[DataSeries]) -> list[DataSeries]:
    """Return the week's day-by-day counts of GAIA's work and its mail desk, each with a total."""
    return [s for s in series if s.shape is SeriesShape.TIME_SERIES and s.source in _RECAP_SOURCES]


def _facts(run: Run, pool: FactPool, laid: Laid) -> Facts:
    reads, spec = run.reads, run.spec
    work, todos = reads.work, reads.todos
    return build_facts(
        laid.chosen,
        FactSources(
            artifacts=gather_artifacts(work),
            open_todos=todos.open,
            calendar=reads.calendar,
            event_ids=event_ids(reads.gathered.pool),
            span=spec.span,
            todos_note=user_todos_note(todos.open, todos.overdue, work.open_subjects.total),
            blocks=laid.blocks,
            overdue_todos=todos.overdue,
            open_tracked=work.open_subjects.total,
            unread=reads.gathered.sources_unavailable,
            recap=WeekRecap(series=_recap_series(pool.series), goals=pool.goals)
            if spec.recaps_week
            else None,
        ),
        run.clock,
    )


async def _publish_edition(run: Run, pool: FactPool, laid: Laid) -> None:
    """Voice the brief over its facts, draw its edition, build its payload once and publish it."""
    user, clock, spec, standing, reads = run.user, run.clock, run.spec, run.standing, run.reads
    facts = _facts(run, pool, laid)
    remembered = chosen_signals(laid.chosen, reads.scouts.remembered)
    voicing = await standing.voice(
        VoiceInputs(
            user=user,
            clock=clock,
            reads=reads.reads,
            facts=facts,
            signals=signals_block(remembered, clock),
            recent=reads.recent,
        )
    )
    # Bounded: a stalled model call must fail the cron loudly, not hang the worker slot
    # (observed live 2026-08-07).
    async with asyncio.timeout(spec.voice_timeout_seconds):
        voice, draft = await written_brief(user.id, voicing.prompt, voicing.writing)
    links = await links_in(user.id, voice.message, facts)
    edition = draw_edition(user, laid.blocks, spec.fixed_family)
    completed = reads.reads.completed.since(standing.since)
    payload = edition_payload(
        PayloadParts(
            clock=clock,
            kicker=spec.kicker,
            prose=Prose(voice, draft, links),
            facts=facts,
            mood=standing.mood(draft),
            edition=edition,
            new_stamp=await new_stamp(user.id, edition.stamp_city) if edition.stamp_city else None,
            recipient_name=display_name(user),
            tallies=BriefingTallies(
                done_by_you=len(completed.user), done_by_gaia=len(completed.gaia)
            ),
            sources_read=sources_shown(laid, reads.gathered.pool),
            sources_unavailable=[*reads.gathered.sources_unavailable, *reads.calendar.unread],
            uncomposed=laid.uncomposed,
            stats=[] if spec.recaps_week else work_stats(reads.work),
            calendar=[] if spec.recaps_week else reads.calendar.events,
            week=count_week(clock, completed, reads.calendar.events) if spec.recaps_week else None,
        )
    )
    await publish(
        user,
        clock,
        spec,
        payload,
        Sending(
            push=standing.pushes(payload),
            pool=PoolCounts.of(pool),
            signal_count=len(remembered),
            held_ids=_carried(reads.gathered),
            draws=edition.draws,
        ),
    )
