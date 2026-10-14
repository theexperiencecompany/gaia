"""GAIA-branded HTML editions of a briefing payload.

Each edition is a pure payload-to-HTML renderer, self-contained so a headless
browser can rasterize it. This package is also the registry of template families:
a daily brief draws its family from the user's shuffle bag (DAILY_FAMILY_WEIGHTS),
the weekly recap is always WEEKLY_FAMILY, and a persisted template_family selects
the renderer forever so the archive re-renders identically. Payloads with none
render as the classic gaia edition.
"""

from collections.abc import Callable

from app.constants.briefing import POSTAL_FAMILY, WEEKLY_FAMILY
from app.services.briefing.editions.explorer_render import (
    explorer_family_ids,
    render_explorer_edition,
)
from app.services.briefing.editions.gaia import render_edition

# The classic dark-editorial family (render_edition) — the renderer for legacy
# payloads that carry no family. Not in the registry: it is the default.
FAMILY_EDITION = "edition"


def _make_explorer_renderer(family: str) -> Callable[..., str]:
    """Close over one explorer family id and return a render_edition-shaped callable.

    Signature: (payload, *, edition_no, generated_local, tz_label) -> str.
    """

    def _render(
        payload: dict,
        *,
        edition_no: int,
        generated_local: str,
        tz_label: str = "",
    ) -> str:
        return render_explorer_edition(
            payload,
            family=family,
            skin_seed=f"{payload.get('date', '')}:{family}",
            edition_no=edition_no,
            generated_local=generated_local,
            tz_label=tz_label,
        )

    return _render


# Every vendored explorer template family (app/services/briefing/editions/explorer/),
# each wired to render_explorer_edition via a closure over its family id.
EXPLORER_RENDERER: dict[str, Callable[..., str]] = {
    family: _make_explorer_renderer(family) for family in explorer_family_ids()
}


# How many times each daily family appears in one pass of a user's shuffle bag
# (app/services/briefing/shuffle_bag.py): every daily family once, Air Mail twice.
DAILY_FAMILY_WEIGHTS: dict[str, int] = {
    family: 2 if family == POSTAL_FAMILY else 1
    for family in sorted({FAMILY_EDITION, *EXPLORER_RENDERER} - {WEEKLY_FAMILY})
}


# The "paper" of each family that draws one on a background (desk, wall,
# envelope scene); the chat image is cropped to it. Every other family is
# full-bleed and crops to its own root element.
_PAPER_SELECTORS: dict[str, str] = {
    "boardingpass": ".t-boardingpass__pass",
    "librarycard": ".t-librarycard__card",
    "memo": ".t-memo__sheet",
    "playbill": ".pb-bill",
    POSTAL_FAMILY: ".t-postal__scene",
    "receipt": ".t-receipt__tape",
}
_FULL_BLEED_SELECTOR = "#root > article"
_CLASSIC_SELECTOR = ".brief"


def paper_selector(family: str | None) -> str:
    """Return the element a cropped edition image is cut to, for the family."""
    if family in _PAPER_SELECTORS:
        return _PAPER_SELECTORS[family]
    return _FULL_BLEED_SELECTOR if family in EXPLORER_RENDERER else _CLASSIC_SELECTOR


def renderer_for(family: str | None) -> Callable[..., str] | None:
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
    "paper_selector",
    "renderer_for",
]
