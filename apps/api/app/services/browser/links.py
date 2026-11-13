"""The public base URL for the browser links a user is handed.

Recaps and step screenshots are served by the browser link router and sent to
a user as links, so they share one base: this service's host and the router's
prefix. Kept in one place because a link built from the wrong base is only
discovered by a user clicking it.
"""

from __future__ import annotations

from app.config.settings import settings
from app.constants.browser import BROWSER_ROUTE_PREFIX
from app.constants.http import API_V1_PREFIX


def browser_link_base() -> str:
    """Return the base a browser link is built on, without a trailing slash."""
    return f"{settings.HOST.rstrip('/')}{API_V1_PREFIX}{BROWSER_ROUTE_PREFIX}"
