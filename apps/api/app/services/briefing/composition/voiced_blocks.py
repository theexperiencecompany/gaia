"""Say the composition's charts, quotes, progress and notes to the voice, so its message agrees with them."""

from collections.abc import Mapping, Sequence

from app.models.brief_composition_models import (
    BriefBlock,
    ChartBlock,
    NoteBlock,
    ProgressBlock,
    QuoteBlock,
)
from app.services.briefing.slots import SeriesField, series_figures

BLOCKS_HEADER = "[ALSO IN THE BRIEF]"


def _line(block: BriefBlock) -> str | None:
    if isinstance(block, ChartBlock):
        ids = ", ".join(s.id for s in block.series)
        return f"- a chart, {block.title} (series {ids}): {block.takeaway}"
    if isinstance(block, QuoteBlock):
        quote = block.quote
        return f'- {quote.author}\'s words, from {quote.app}: "{quote.text}"'
    if isinstance(block, ProgressBlock):
        goal = block.goal
        return f'- progress on "{goal.statement}": {goal.done} linked todo(s) finished, {goal.open} open'
    if isinstance(block, NoteBlock):
        return f"- a note: {block.text}"
    return None


def voiced_block_lines(blocks: Sequence[BriefBlock]) -> list[str]:
    """Return the facts lines for every block besides the item sections; empty when there are none."""
    lines = [line for block in blocks if (line := _line(block)) is not None]
    return [BLOCKS_HEADER, *lines] if lines else []


def charted_figures(blocks: Sequence[BriefBlock]) -> dict[str, Mapping[SeriesField, str]]:
    """Return the figures of every series a chart draws, which the voice's series slots may render."""
    return {
        series.id: series_figures(series)
        for block in blocks
        if isinstance(block, ChartBlock)
        for series in block.series
    }


def block_words(blocks: Sequence[BriefBlock]) -> list[str]:
    """Return the words and figures the blocks besides the item sections show, which prose may quote."""
    words: list[str] = []
    for block in blocks:
        if isinstance(block, ChartBlock):
            words += [block.title, block.takeaway]
        elif isinstance(block, QuoteBlock):
            words.append(block.quote.text)
        elif isinstance(block, ProgressBlock):
            words += [block.goal.statement, str(block.goal.done), str(block.goal.open)]
        elif isinstance(block, NoteBlock):
            words.append(block.text)
    return words
