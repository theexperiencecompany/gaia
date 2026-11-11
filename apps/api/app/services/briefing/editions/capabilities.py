"""Which composed blocks each edition family can draw, taken from the founder-reviewed gallery's leave-outs.

A family that cannot draw a block in its own idiom does not draw it at all: a letterpress menu
has no honest place for a plotted chart, a letter tells rather than charts, a typewriter
states figures but does not plot a line, and the weekly review looks back, so the daily
lead and its quote are not its to print.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import get_args

from app.constants.briefing import POSTAL_FAMILY, WEEKLY_FAMILY
from app.models.brief_composition_models import BriefBlock, BriefBlockKind, ChartBlock, ChartKind


@dataclass(frozen=True)
class EditionCapabilities:
    """The block kinds a family draws, and for a chart, the chart kinds it can plot."""

    blocks: frozenset[BriefBlockKind]
    charts: frozenset[ChartKind]

    def draws(self, block: BriefBlock) -> bool:
        """Say whether the family can draw the block in its own idiom."""
        if isinstance(block, ChartBlock):
            return block.chart in self.charts
        return block.kind in self.blocks


_EVERY_BLOCK: frozenset[BriefBlockKind] = frozenset(get_args(BriefBlockKind)) - {"chart"}
_EVERY_CHART = frozenset(ChartKind)
_DRAWS_EVERYTHING = EditionCapabilities(blocks=_EVERY_BLOCK, charts=_EVERY_CHART)

_LEAVE_OUTS: dict[str, EditionCapabilities] = {
    "menu": EditionCapabilities(blocks=_EVERY_BLOCK - {"progress"}, charts=frozenset()),
    POSTAL_FAMILY: EditionCapabilities(blocks=_EVERY_BLOCK, charts=frozenset()),
    "memo": EditionCapabilities(
        blocks=_EVERY_BLOCK, charts=frozenset({ChartKind.BAR, ChartKind.STACKED_BAR})
    ),
    WEEKLY_FAMILY: EditionCapabilities(
        blocks=_EVERY_BLOCK - {"lead", "quote"}, charts=_EVERY_CHART
    ),
}


def edition_capabilities(family: str) -> EditionCapabilities:
    """Return what the family draws; every family not leaving something out draws every block."""
    return _LEAVE_OUTS.get(family, _DRAWS_EVERYTHING)


def families_drawing(families: Iterable[str], blocks: list[BriefBlock]) -> frozenset[str]:
    """Return the families that can draw every one of the blocks."""
    return frozenset(
        f for f in families if all(edition_capabilities(f).draws(block) for block in blocks)
    )


def split_drawable(
    family: str, blocks: list[BriefBlock]
) -> tuple[list[BriefBlock], list[BriefBlock]]:
    """Split the blocks, in order, into those the family draws and those left to the brief's page."""
    capabilities = edition_capabilities(family)
    drawn = [block for block in blocks if capabilities.draws(block)]
    undrawn = [block for block in blocks if not capabilities.draws(block)]
    return drawn, undrawn
