"""Product analytics: the event catalog, the identities events belong to, and the PostHog client.

Event names, owning surfaces and property shapes live only in
shared.py.analytics.catalog; every emitter on every surface is typed from it.
"""

from shared.py.analytics.client import PostHogAnalytics, check_capture, posthog_properties
from shared.py.analytics.identity import AnalyticsId, PlatformIdentity, UserId

__all__ = [
    "AnalyticsId",
    "PlatformIdentity",
    "PostHogAnalytics",
    "UserId",
    "check_capture",
    "posthog_properties",
]
