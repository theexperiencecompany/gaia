"""GAIA-branded HTML editions of a briefing payload.

Each edition is a pure payload-to-HTML renderer, self-contained so a headless
browser can rasterize it. This package is also the registry of template families:
a daily brief draws its family from the user's shuffle bag (DAILY_FAMILY_WEIGHTS),
the weekly recap is always WEEKLY_FAMILY, and a persisted template_family selects
the renderer forever so the archive re-renders identically.
"""

from dataclasses import dataclass
from typing import Protocol

from app.constants.briefing import (
    DESK_FAMILIES,
    DESK_SHADOW_BLEED_PX,
    POSTAL_FAMILY,
    WEEKLY_FAMILY,
)
from app.models.briefing_models import BriefingPayload
from app.services.briefing.editions.explorer_render import (
    EXPLORER_CANVAS_PX,
    explorer_family_ids,
    render_explorer_edition,
)


class EditionRenderer(Protocol):
    """The signature every edition renderer shares."""

    def __call__(
        self,
        payload: BriefingPayload,
        *,
        edition_no: int,
        generated_local: str,
        tz_label: str = "",
    ) -> str: ...


def _make_explorer_renderer(family: str) -> EditionRenderer:
    """Close over one explorer family id and return an EditionRenderer."""

    def _render(
        payload: BriefingPayload,
        *,
        edition_no: int,
        generated_local: str,
        tz_label: str = "",
    ) -> str:
        return render_explorer_edition(
            payload,
            family=family,
            skin_seed=f"{payload.date}:{family}",
            edition_no=edition_no,
            generated_local=generated_local,
            tz_label=tz_label,
        )

    return _render


# Every vendored explorer template family (app/services/briefing/editions/explorer/),
# each wired to render_explorer_edition via a closure over its family id.
EXPLORER_RENDERER: dict[str, EditionRenderer] = {
    family: _make_explorer_renderer(family) for family in explorer_family_ids()
}


# How many times each daily family appears in one pass of a user's shuffle bag
# (app/services/briefing/shuffle_bag.py): every daily family once, Air Mail twice.
DAILY_FAMILY_WEIGHTS: dict[str, int] = {
    family: 2 if family == POSTAL_FAMILY else 1
    for family in sorted(set(EXPLORER_RENDERER) - {WEEKLY_FAMILY})
}


@dataclass(frozen=True)
class EditionFrame:
    """How a family's page is rasterized: its canvas, pixel density and crop."""

    width: int
    device_scale_factor: int
    #: The page's root element; the capture is exactly its box.
    clip_selector: str
    #: For paper laid on a background (desk, counter, table): the even margin of
    #: background, in CSS px, kept around the paper and its shadow. None for a
    #: full-bleed page, whose root element is the paper.
    trim_margin_px: int | None
    #: Room captured around the root so a desk family's shadow is never cut at its box.
    clip_bleed_px: int

    @property
    def transparent_desk(self) -> bool:
        """Whether the desk is left out of the raster, so the paper lies on whatever surface shows it."""
        return self.trim_margin_px is not None


DESK_MARGIN_PX = 16
_EXPLORER_ROOT = "#root > article"
_EXPLORER_SCALE = 3


def edition_frame(family: str) -> EditionFrame:
    """Return how the family's page is rasterized and cropped."""
    on_a_desk = family in DESK_FAMILIES
    bleed = DESK_SHADOW_BLEED_PX if on_a_desk else 0
    return EditionFrame(
        width=EXPLORER_CANVAS_PX + 2 * bleed,
        device_scale_factor=_EXPLORER_SCALE,
        clip_selector=_EXPLORER_ROOT,
        trim_margin_px=DESK_MARGIN_PX if on_a_desk else None,
        clip_bleed_px=bleed,
    )


__all__ = [
    "DAILY_FAMILY_WEIGHTS",
    "EXPLORER_RENDERER",
    "POSTAL_FAMILY",
    "WEEKLY_FAMILY",
    "render_explorer_edition",
    "EditionFrame",
    "edition_frame",
]
