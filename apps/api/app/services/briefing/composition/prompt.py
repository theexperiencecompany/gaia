"""Fill the composition prompt from the pool, the page budget and the day's context."""

from app.agents.prompts.brief_composition_prompts import COMPOSITION_EXAMPLES, COMPOSITION_PROMPT
from app.agents.prompts.briefing_prompts import UNTRUSTED_DATA_NOTE
from app.constants.briefing import (
    BRIEF_CHART_TITLE_MAX_CHARS,
    BRIEF_HEADING_MAX_CHARS,
    BRIEF_ITEM_DETAIL_MAX_CHARS,
    BRIEF_ITEM_TITLE_MAX_CHARS,
    BRIEF_NOTE_MAX_CHARS,
    BRIEF_TAKEAWAY_MAX_CHARS,
    MAX_BAR_CATEGORIES,
    MAX_BRIEF_BLOCKS,
    MAX_BRIEF_CHARTS,
    MAX_BRIEF_ITEMS,
    MAX_ITEMS_PER_BLOCK,
    MIN_TREND_POINTS,
    BriefAction,
    BriefOutcome,
)
from app.models.brief_slot_models import (
    FACT_PLACEHOLDER,
    SERIES_PLACEHOLDER,
    FactField,
    SeriesField,
    SlotKind,
    value_slot_text,
)
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.fact_pool.render import context_block
from app.services.hil.utils import untrusted_fence


def composition_prompt(pool: FactPool, frame: str, facts: str) -> str:
    """Return the prompt that composes a brief over the pool, laid out as facts, in its kind's frame.

    The pool and the scouts' criteria are read from the user's apps, so both sit inside a fence.
    """
    context = pool.context
    fence = untrusted_fence()
    return COMPOSITION_PROMPT.format(
        untrusted=UNTRUSTED_DATA_NOTE.format(fence=fence),
        fence=fence,
        frame=frame.format(reader=context.reader, today=context.clock.date_str),
        reader=context.reader,
        criteria="\n".join(f"- {app}: {text}" for app, text in pool.criteria.items())
        or "- (no app wrote criteria)",
        context=context_block(context),
        pool=facts,
        examples=COMPOSITION_EXAMPLES,
        fact_slot=value_slot_text(SlotKind.FACT, FACT_PLACEHOLDER),
        fact_time_slot=value_slot_text(SlotKind.FACT, FACT_PLACEHOLDER, FactField.TIME.value),
        series_slot=value_slot_text(SlotKind.SERIES, SERIES_PLACEHOLDER, "FIELD"),
        series_fields=", ".join(SeriesField),
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
