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
    WEEKLY_FAMILY,
    WEEKLY_GENERATION_TIMEOUT_SECONDS,
    WEEKLY_KICKER,
    WEEKLY_SECTION_TITLES,
    BriefingRunOutcome,
)
from app.db.repositories.users import user_repository
from app.models.briefing_models import (
    BriefingTallies,
)
from app.services.briefing import context, dormancy
from app.services.briefing.artifacts import gather_artifacts
from app.services.briefing.candidates.judge import select_candidates
from app.services.briefing.candidates.pool import (
    gather_week_candidates,
)
from app.services.briefing.errors import BriefingGenerationError
from app.services.briefing.facts import (
    WEEK_AHEAD,
    FactSources,
    build_facts,
)
from app.services.briefing.lifecycle import (
    already_delivered,
)
from app.services.briefing.prose import Prose, Writing, links_in, voiced_payload, written_brief
from app.services.briefing.publish import Push, publish_brief
from app.services.briefing.sections import (
    chosen_sections,
    event_ids,
    log_selection,
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
    gathered = await gather_week_candidates(user_id, since, completed, week.ahead)
    selection = await select_candidates(
        user_id,
        gathered.pool,
        {},
        seen_at,
        user.timezone or Timezone.utc().value,
        kind=BRIEFING_KIND_WEEKLY,
    )
    log_selection(len(gathered.pool), selection)
    facts = build_facts(
        chosen_sections(selection, gathered.pool, WEEKLY_SECTION_TITLES),
        FactSources(
            artifacts=gather_artifacts(
                context.TrackedWork(completed=[*completed.gaia, *completed.user])
            ),
            open_todos=0,
            calendar=week.ahead,
            event_ids=event_ids(gathered.pool),
            span=WEEK_AHEAD,
            todos_note=None,
        ),
        clock,
    )
    goal_block, _ = await context.format_goal_block(user_id, user)
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
                context=blocks.context,
                must_mention=facts.must_mention,
                kind=BRIEFING_KIND_WEEKLY,
            ),
        )
    links = await links_in(user_id, voice.message, facts)
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
        }
    )
    await publish_brief(
        user,
        clock,
        BRIEFING_KIND_WEEKLY,
        payload,
        [],
        Push(push=True),
    )
    return BriefingRunOutcome.SENT
