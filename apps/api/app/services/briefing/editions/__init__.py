"""GAIA-branded HTML editions of a briefing payload.

Each edition is a pure payload-to-HTML renderer, self-contained so a headless
browser can rasterize it. This package is also the registry of template families:
a daily brief draws its family from the user's shuffle bag (DAILY_FAMILY_WEIGHTS),
the weekly recap is always WEEKLY_FAMILY, and a persisted template_family selects
the renderer forever so the archive re-renders identically. Payloads with none
render as the classic gaia edition.
"""

from dataclasses import dataclass
from typing import Protocol

from app.constants.briefing import POSTAL_FAMILY, WEEKLY_FAMILY
from app.models.briefing_models import BriefingPayload
from app.services.briefing.editions._shared import CANVAS_PX, EXPLORER_CANVAS_PX
from app.services.briefing.editions.explorer_render import (
    explorer_family_ids,
    render_explorer_edition,
)
from app.services.briefing.editions.gaia import render_edition

# The classic dark-editorial family (render_edition) — the renderer for legacy
# payloads that carry no family. Not in the registry: it is the default.
FAMILY_EDITION = "edition"


class EditionRenderer(Protocol):
    """The signature every edition renderer shares (render_edition's)."""

    def __call__(
        self,
        payload: BriefingPayload,
        *,
        edition_no: int,
        generated_local: str,
        tz_label: str = "",
    ) -> str: ...


def _make_explorer_renderer(family: str) -> EditionRenderer:
    """Close over one explorer family id and return a render_edition-shaped callable."""

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
    for family in sorted({FAMILY_EDITION, *EXPLORER_RENDERER} - {WEEKLY_FAMILY})
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


# Families whose paper lies on a background; their image is trimmed to the paper.
_ON_A_DESK = frozenset(
    {"boardingpass", "invoice", "librarycard", "memo", "menu", POSTAL_FAMILY, "receipt"}
)
DESK_MARGIN_PX = 16
_EXPLORER_ROOT = "#root > article"
_CLASSIC_FRAME = EditionFrame(
    width=CANVAS_PX, device_scale_factor=2, clip_selector=".brief", trim_margin_px=None
)
_EXPLORER_SCALE = 3


def edition_frame(family: str | None) -> EditionFrame:
    """Return how the family's page is rasterized and cropped."""
    if family is None or family not in EXPLORER_RENDERER:
        return _CLASSIC_FRAME
    return EditionFrame(
        width=EXPLORER_CANVAS_PX,
        device_scale_factor=_EXPLORER_SCALE,
        clip_selector=_EXPLORER_ROOT,
        trim_margin_px=DESK_MARGIN_PX if family in _ON_A_DESK else None,
    )


def renderer_for(family: str | None) -> EditionRenderer | None:
    """Return the registered renderer for the family.

    Returns None for the classic edition, unknown names, and legacy payloads; callers
    fall back to render_edition so every payload always renders.
    """
    if family is None or family == FAMILY_EDITION:
        return None
    return EXPLORER_RENDERER.get(family)


__all__ = [
    "DAILY_FAMILY_WEIGHTS",
    "EXPLORER_RENDERER",
    "FAMILY_EDITION",
    "POSTAL_FAMILY",
    "WEEKLY_FAMILY",
    "render_edition",
    "render_explorer_edition",
    "EditionFrame",
    "edition_frame",
    "renderer_for",
]
