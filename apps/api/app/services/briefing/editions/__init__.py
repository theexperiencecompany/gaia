"""GAIA-branded HTML editions of a briefing payload.

Each edition is a pure ``payload -> full HTML document`` renderer. The HTML is
self-contained (embedded fonts, one inline stylesheet, no external requests) so
it can be rasterized to an image by a headless browser, hosted, and shown in the
briefing email + in-app. The ``gaia`` edition is a dark, single-accent editorial
hero in GAIA's design language.

This package is also the registry of **weekly template families** the
shuffled-cycle rotation picks from (see ``edition_rotation``): the classic
``gaia`` edition renders every daily brief and is the weekly fallback; every
other family comes from the vendored explorer set (``editions/explorer/``,
wired up in ``EXPLORER_RENDERER``). A weekly payload's persisted
``template_family`` selects the renderer forever — the archive re-renders
identically.
"""

from collections.abc import Callable

from app.services.briefing.editions.explorer_render import (
    explorer_family_ids,
    render_explorer_edition,
)
from app.services.briefing.editions.gaia import render_edition

# The classic dark-editorial family (render_edition) — the daily brief's look
# and the weekly fallback. Not in the registry: it is the default renderer.
FAMILY_EDITION = "edition"

# Vendored explorer families excluded from the rotation pool (real-data rule:
# a family that fabricates or silently drops content is never rotation-eligible):
# - "weekly" (tpl-novel-e.js): renders hardcoded demo aggregates, needs a real
#   weekly-aggregate adapter.
# - "dayline"/"flightplan": position items on a real time axis and drop items
#   with no clock time; re-admit once the briefing prompt reliably emits time
#   prefixes on calendar-anchored items (verified via the persona harness).
# - "metromap" (tpl-novel-a.js): fixed-position SVG stations sized for the
#   founder fixture's 2-3-word station names overflow/clip the canvas once
#   fed real full-sentence item text (see explorer/README.md); needs a
#   content-aware layout, not a content swap.
EXPLORER_EXCLUDED_FAMILIES = {"weekly", "dayline", "flightplan", "metromap"}


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


# The vendored explorer template families (app/services/briefing/editions/explorer/),
# minus EXPLORER_EXCLUDED_FAMILIES, each wired to render_explorer_edition via a
# closure over its family id.
EXPLORER_FAMILIES: list[str] = [
    family for family in explorer_family_ids() if family not in EXPLORER_EXCLUDED_FAMILIES
]
EXPLORER_RENDERER: dict[str, Callable[..., str]] = {
    family: _make_explorer_renderer(family) for family in EXPLORER_FAMILIES
}


def rotation_families() -> list[str]:
    """The rotation-eligible family names, stable order — one pool shared by
    the daily and weekly kinds (each kind keeps independent rotation state)."""
    return sorted({FAMILY_EDITION, *EXPLORER_FAMILIES})


def renderer_for(family: str | None) -> Callable[..., str] | None:
    """The registered renderer for ``family``, or None for the classic edition,
    unknown names, and legacy payloads — callers fall back to
    ``render_edition`` so every payload always renders."""
    if family is None or family == FAMILY_EDITION:
        return None
    return EXPLORER_RENDERER.get(family)


__all__ = [
    "EXPLORER_EXCLUDED_FAMILIES",
    "EXPLORER_FAMILIES",
    "EXPLORER_RENDERER",
    "FAMILY_EDITION",
    "render_edition",
    "render_explorer_edition",
    "renderer_for",
    "rotation_families",
]
