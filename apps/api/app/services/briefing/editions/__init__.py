"""GAIA-branded HTML editions of a briefing payload.

Each edition is a pure ``payload -> full HTML document`` renderer. The HTML is
self-contained (embedded fonts, one inline stylesheet, no external requests) so
it can be rasterized to an image by a headless browser, hosted, and shown in the
briefing email + in-app. The ``gaia`` edition is a dark, single-accent editorial
hero in GAIA's design language.
"""

from app.services.briefing.editions.gaia import render_edition

__all__ = ["render_edition"]
