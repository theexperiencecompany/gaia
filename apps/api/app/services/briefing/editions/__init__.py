"""Print-quality HTML editions of a briefing payload.

Each edition is a pure ``payload -> full HTML document`` renderer. The HTML is
self-contained (system fonts, one inline stylesheet, no external requests) so it
can be rasterized to a PNG by a headless browser and emailed. The broadsheet
edition is the flagship: a designed newspaper front page, not an AI dashboard.
"""

from app.services.briefing.editions.broadsheet import render_edition

__all__ = ["render_edition"]
