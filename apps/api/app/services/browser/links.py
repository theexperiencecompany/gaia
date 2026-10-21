"""The public base URL for the browser links a user is handed.

Recaps and step screenshots are served by the root-mounted browser router and
sent to a user as links, so they share one base: the friendly vhost when one is
configured, else this service's own host. Kept in one place because a link built
from the wrong base is only discovered by a user clicking it.
"""

from __future__ import annotations

from app.config.settings import settings


def browser_link_base() -> str:
    """Return the base a browser link is built on, without a trailing slash."""
    base: str = settings.BROWSER_LIVE_VIEW_BASE_URL or settings.HOST
    return base.rstrip("/")
