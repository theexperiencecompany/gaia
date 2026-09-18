"""The public base URL fronting the browser's own routes.

Live view, recap and step screenshots are all served by the root-mounted browser
router and all handed to a user as a link, so they share one base: the friendly
vhost when one is configured, else this service's own host. Kept in one place
because a link built from the wrong base is only discovered by a user clicking it.
"""

from __future__ import annotations

from app.config.settings import settings


def browser_link_base() -> str:
    """Return the base a browser link is built on, without a trailing slash."""
    base: str = settings.BROWSER_LIVE_VIEW_BASE_URL or settings.HOST
    return base.rstrip("/")
