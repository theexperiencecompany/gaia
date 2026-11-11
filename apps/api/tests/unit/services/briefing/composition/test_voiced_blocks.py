"""The voice is told every non-item block as the brief shows it, and may quote only what those blocks carry."""

from app.models.brief_composition_models import (
    ChartBlock,
    ChartKind,
    NoteBlock,
    ProgressBlock,
    QuoteBlock,
)
from app.models.brief_pool_models import (
    DataSeries,
    GoalOrigin,
    GoalState,
    QuoteSpan,
    SeriesPoint,
    SeriesShape,
)
from app.services.briefing.composition.voiced_blocks import (
    BLOCKS_HEADER,
    block_words,
    charted_figures,
    voiced_block_lines,
)
from app.services.briefing.slots import SeriesField


def _series(series_id: str, ys: list[float]) -> DataSeries:
    return DataSeries(
        id=series_id,
        label=series_id,
        unit="hours",
        source="gaia",
        app="GAIA",
        shape=SeriesShape.TIME_SERIES,
        points=[SeriesPoint(x=f"2026-11-{5 + n:02d}", y=y) for n, y in enumerate(ys)],
    )


CHART = ChartBlock(
    chart=ChartKind.STACKED_BAR,
    title="This week",
    takeaway="Thursday was heaviest.",
    series=[_series("meetings", [2, 1, 4]), _series("focus", [3, 3, 1])],
)
QUOTE = QuoteBlock(
    quote=QuoteSpan(
        id="q1",
        text="Can you confirm by Friday?",
        author="Maya",
        source="gmail",
        app="Gmail",
        item_id=1,
    )
)
PROGRESS = ProgressBlock(
    goal=GoalState(id="g1", statement="Ship v3", origin=GoalOrigin.MEMORY, done=2, open=7)
)
NOTE = NoteBlock(text="A light day.")


def test_each_kind_of_block_is_told_to_the_voice_under_one_header() -> None:
    assert voiced_block_lines([CHART, QUOTE, PROGRESS, NOTE]) == [
        BLOCKS_HEADER,
        "- a chart, This week (series meetings, focus): Thursday was heaviest.",
        '- Maya\'s words, from Gmail: "Can you confirm by Friday?"',
        '- progress on "Ship v3": 2 linked todo(s) finished, 7 open',
        "- a note: A light day.",
    ]


def test_no_blocks_beyond_the_items_tell_the_voice_nothing() -> None:
    assert voiced_block_lines([]) == []


def test_the_figures_of_every_charted_series_are_offered_by_id() -> None:
    figures = charted_figures([NOTE, CHART])

    assert list(figures) == ["meetings", "focus"]
    assert figures["meetings"][SeriesField.TOTAL] == "7"
    assert figures["meetings"][SeriesField.PEAK] == "4"
    assert figures["focus"][SeriesField.LATEST] == "1"


def test_the_words_the_prose_may_quote_come_from_every_kind_of_block() -> None:
    assert block_words([NOTE, CHART, QUOTE, PROGRESS]) == [
        "A light day.",
        "This week",
        "Thursday was heaviest.",
        "Can you confirm by Friday?",
        "Ship v3",
        "2",
        "7",
    ]
