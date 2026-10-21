"""Product analytics: the event catalog, the identities events belong to, and the PostHog client.

Event names, owning surfaces and property shapes live only in
shared.py.analytics.catalog; every emitter on every surface is typed from it.
"""

from shared.py.analytics.client import (
    Dedupe,
    PostHogAnalytics,
    PostHogCapture,
    check_capture,
    prepare_capture,
)
from shared.py.analytics.identity import AnalyticsId, PlatformIdentity, UserId, is_user_id

__all__ = [
    "AnalyticsId",
    "Dedupe",
    "PlatformIdentity",
    "PostHogAnalytics",
    "PostHogCapture",
    "UserId",
    "is_user_id",
    "check_capture",
    "prepare_capture",
]
