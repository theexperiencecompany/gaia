"""GAIA-branded HTML editions of a briefing payload.

Each edition is a pure ``payload -> full HTML document`` renderer. The HTML is
self-contained (embedded fonts, one inline stylesheet, no external requests) so
it can be rasterized to an image by a headless browser, hosted, and shown in the
briefing email + in-app. The ``gaia`` edition is a dark, single-accent editorial
hero in GAIA's design language.

This package is also the registry of **weekly template families** the
shuffled-cycle rotation picks from (see ``edition_rotation``): the classic
``gaia`` edition renders every daily brief and is the weekly fallback; each
additional family is its own module here, registered in
``WEEKLY_FAMILY_RENDERERS``. A weekly payload's persisted ``template_family``
selects the renderer forever — the archive re-renders identically.
"""

from collections.abc import Callable

from app.services.briefing.editions.gaia import render_edition

# The classic dark-editorial family (render_edition) — the daily brief's look
# and the weekly fallback. Not in the registry: it is the default renderer.
FAMILY_EDITION = "edition"

# family name -> render_edition-shaped renderer (payload, *, edition_no,
# generated_local, tz_label) -> str. Additional weekly families register here.
WEEKLY_FAMILY_RENDERERS: dict[str, Callable[..., str]] = {}


def weekly_families() -> list[str]:
    """The rotation-eligible family names, stable order."""
    return sorted({FAMILY_EDITION, *WEEKLY_FAMILY_RENDERERS})


def renderer_for(family: str | None) -> Callable[..., str] | None:
    """The registered renderer for ``family``, or None for the classic edition,
    unknown names, and legacy payloads — callers fall back to
    ``render_edition`` so every payload always renders."""
    if family is None or family == FAMILY_EDITION:
        return None
    return WEEKLY_FAMILY_RENDERERS.get(family)


__all__ = [
    "FAMILY_EDITION",
    "WEEKLY_FAMILY_RENDERERS",
    "render_edition",
    "renderer_for",
    "weekly_families",
]
