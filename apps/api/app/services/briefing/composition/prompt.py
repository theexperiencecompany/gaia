"""Fill the composition prompt from the pool, the page budget and the day's context."""

from app.agents.prompts.brief_composition_prompts import (
    COMPOSITION_EXAMPLES,
    COMPOSITION_PROMPT,
    DAILY_FRAME,
    WEEKLY_FRAME,
)
from app.constants.briefing import (
    BRIEF_CHART_TITLE_MAX_CHARS,
    BRIEF_HEADING_MAX_CHARS,
    BRIEF_ITEM_DETAIL_MAX_CHARS,
    BRIEF_ITEM_TITLE_MAX_CHARS,
    BRIEF_NOTE_MAX_CHARS,
    BRIEF_OFFER_MAX_CHARS,
    BRIEF_TAKEAWAY_MAX_CHARS,
    BRIEFING_KIND_DAILY,
    BRIEFING_KIND_WEEKLY,
    MAX_BAR_CATEGORIES,
    MAX_BRIEF_BLOCKS,
    MAX_BRIEF_CHARTS,
    MAX_BRIEF_ITEMS,
    MAX_ITEMS_PER_BLOCK,
    MIN_TREND_POINTS,
    BriefAction,
    BriefOutcome,
)
from app.models.briefing_models import BriefingKind
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.fact_pool.render import context_block

_FRAMES: dict[BriefingKind, str] = {
    BRIEFING_KIND_DAILY: DAILY_FRAME,
    BRIEFING_KIND_WEEKLY: WEEKLY_FRAME,
}


def composition_prompt(pool: FactPool, kind: BriefingKind, facts: str) -> str:
    """Return the prompt that composes the kind of brief over the pool, laid out as facts."""
    context = pool.context
    return COMPOSITION_PROMPT.format(
        frame=_FRAMES[kind].format(reader=context.reader, today=context.today.isoformat()),
        reader=context.reader,
        criteria="\n".join(f"- {app}: {text}" for app, text in pool.criteria.items())
        or "- (no app wrote criteria)",
        context=context_block(context),
        pool=facts,
        examples=COMPOSITION_EXAMPLES,
        offer_max=BRIEF_OFFER_MAX_CHARS,
        items_per_block=MAX_ITEMS_PER_BLOCK,
        heading_max=BRIEF_HEADING_MAX_CHARS,
        actions=", ".join(BriefAction),
        outcomes=", ".join(BriefOutcome),
        title_max=BRIEF_ITEM_TITLE_MAX_CHARS,
        detail_max=BRIEF_ITEM_DETAIL_MAX_CHARS,
        chart_title_max=BRIEF_CHART_TITLE_MAX_CHARS,
        takeaway_max=BRIEF_TAKEAWAY_MAX_CHARS,
        note_max=BRIEF_NOTE_MAX_CHARS,
        min_trend=MIN_TREND_POINTS,
        max_bars=MAX_BAR_CATEGORIES,
        max_blocks=MAX_BRIEF_BLOCKS,
        max_items=MAX_BRIEF_ITEMS,
        max_charts=MAX_BRIEF_CHARTS,
    )
