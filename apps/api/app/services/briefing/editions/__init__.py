"""GAIA-branded HTML editions of a briefing payload.

Each edition is a pure ``payload -> full HTML document`` renderer. The HTML is
self-contained (embedded fonts, one inline stylesheet, no external requests) so
it can be rasterized to an image by a headless browser, hosted, and shown in the
briefing email + in-app. The ``gaia`` edition is a dark, single-accent editorial
hero in GAIA's design language.

This package is also the registry of template families and the weekday
schedule that picks one (``EDITION_SCHEDULE``): each day of the user's week has
one fixed family, and within it the skin varies deterministically by date. The
classic ``gaia`` edition is the renderer for payloads with no family (legacy
rows); a payload's persisted ``template_family`` selects the renderer forever,
so the archive re-renders identically.
"""

from collections.abc import Callable
from datetime import date

from app.services.briefing.editions.explorer_render import (
    explorer_family_ids,
    render_explorer_edition,
)
from app.services.briefing.editions.gaia import render_edition

# The classic dark-editorial family (render_edition) — the renderer for legacy
# payloads that carry no family. Not in the registry: it is the default.
FAMILY_EDITION = "edition"

# One family per day of the user's week (Monday = 0, as ``date.weekday()``).
# Every other vendored family stays registered — renderable for archived
# payloads — but is never scheduled.
EDITION_SCHEDULE: dict[int, str] = {
    0: "memo",
    1: "swiss",
    2: "postal",
    3: "broadsheet",
    4: "playbill",
    5: "receipt",
    6: "weekly",
}


def _make_explorer_renderer(family: str) -> Callable[..., str]:
    """Close over one explorer family id, returning a render_edition-shaped
    callable (payload, *, edition_no, generated_local, tz_label) -> str."""

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


def family_for_date(iso_date: str) -> str:
    """The scheduled family for a user-local ``YYYY-MM-DD`` date."""
    return EDITION_SCHEDULE[date.fromisoformat(iso_date).weekday()]


def renderer_for(family: str | None) -> Callable[..., str] | None:
    """The registered renderer for ``family``, or None for the classic edition,
    unknown names, and legacy payloads — callers fall back to
    ``render_edition`` so every payload always renders."""
    if family is None or family == FAMILY_EDITION:
        return None
    return EXPLORER_RENDERER.get(family)


__all__ = [
    "EDITION_SCHEDULE",
    "EXPLORER_RENDERER",
    "FAMILY_EDITION",
    "family_for_date",
    "render_edition",
    "render_explorer_edition",
    "renderer_for",
]
