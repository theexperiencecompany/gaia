"""The weekly digest: zoom out on the week since Monday and the week ahead."""

import asyncio
from datetime import UTC, datetime

from app.agents.prompts.briefing_prompts import (
    VoicePromptBlocks,
    build_weekly_voice_prompt,
    reader_line,
)
from app.constants.briefing import (
    BRIEFING_KIND_WEEKLY,
    UNNAMED_READER,
    WEEK_AHEAD_SPAN,
    WEEKLY_FAMILY,
    WEEKLY_GENERATION_TIMEOUT_SECONDS,
    WEEKLY_KICKER,
    BriefingRunOutcome,
)
from app.db.repositories.users import user_repository
from app.models.briefing_models import (
    BriefingTallies,
)
from app.services.briefing import context, dormancy
from app.services.briefing.artifacts import gather_artifacts
from app.services.briefing.candidates.pool import (
    gather_week_candidates,
)
from app.services.briefing.composition.compose import compose_brief
from app.services.briefing.editions.capabilities import split_drawable
from app.services.briefing.errors import BriefingGenerationError
from app.services.briefing.fact_pool.pool import PoolContext, PoolReads, build_fact_pool
from app.services.briefing.fact_pool.window import week_window
from app.services.briefing.facts import (
    WEEK_AHEAD,
    FactSources,
    build_facts,
)
from app.services.briefing.lifecycle import (
    already_delivered,
)
from app.services.briefing.prose import Prose, Writing, links_in, voiced_payload, written_brief
from app.services.briefing.publish import PoolCounts, Push, publish_brief
from app.services.briefing.sections import (
    event_ids,
    lay_out,
    log_composition,
)
from app.utils.auth_utils import build_user_context
from app.utils.timezone import Timezone
from app.utils.user_display import display_first_name
from shared.py.wide_events import log


async def run_weekly_digest(user_id: str) -> BriefingRunOutcome:
    """Zoom out on the week since Monday and the week ahead; return how it ended."""
    log.set(component="briefing", operation="run_weekly_digest", user_id=user_id)
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
    completed = await context.gather_completed_since(user_id, since)
    week = await context.gather_week(user_id, clock, completed)
    seen_at = datetime.now(UTC)
    gathered = await gather_week_candidates(user_id, clock, since, completed, week.ahead)
    goals = await context.stated_goals(user_id, user)
    goal_block, _ = context.format_goal_block(goals)
    window = week_window(clock)
    pool = await build_fact_pool(
        user_id,
        window,
        PoolReads(
            items=gathered.pool,
            signals=[],
            calendar=await context.read_calendar(user_id, window.start, window.end),
            goals=goals,
            criteria={},
        ),
        PoolContext(
            reader=display_first_name(user) or UNNAMED_READER,
            timezone=user.timezone or Timezone.utc().value,
            today=clock.now_local.date(),
            calendar_events=len(week.ahead),
            calendar_span=WEEK_AHEAD_SPAN,
            recent_openings=[],
        ),
        seen_at,
    )
    composed = await compose_brief(user_id, pool, BRIEFING_KIND_WEEKLY)
    laid = lay_out(composed.rendered, pool)
    log_composition(pool, laid)
    facts = build_facts(
        laid.chosen,
        FactSources(
            artifacts=gather_artifacts(
                context.TrackedWork(completed=[*completed.gaia, *completed.user])
            ),
            open_todos=0,
            calendar=week.ahead,
            event_ids=event_ids(gathered.pool),
            span=WEEK_AHEAD,
            todos_note=None,
            blocks=laid.blocks,
        ),
        clock,
    )
    blocks = VoicePromptBlocks(
        reader=reader_line(display_first_name(user)),
        facts=facts.block,
        goal=goal_block,
        lookback="",
        replies="",
    )
    # Bounded: a stalled agent run must fail the cron loudly, not hang the
    # worker slot (observed live 2026-08-07).
    async with asyncio.timeout(WEEKLY_GENERATION_TIMEOUT_SECONDS):
        voice, draft = await written_brief(
            build_user_context(user, auth_provider=None),
            clock,
            build_weekly_voice_prompt(date_local=clock.date_str, blocks=blocks),
            Writing(
                values=facts.values,
                lead=facts.lead,
                kind=BRIEFING_KIND_WEEKLY,
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
            "sources_read": gathered.sources_read,
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
        Push(push=True, pool=PoolCounts.of(pool)),
    )
    return BriefingRunOutcome.SENT
