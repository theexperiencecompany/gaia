"""Print the share-link constants the web app, the usercontent Worker, the CLI and the Caddyfile use.

`mise links:constants` writes them to apps/usercontent-worker/src/ and
packages/cli/src/lib/ as link-constants.generated.json and to the web's
short-links feature as link-constants.generated.ts, and checks the Caddyfile's
routes; CI's link-constants check fails when any of them drifts.
"""

import json
from typing import TypedDict

from tests import offline_env  # noqa: F401 -- must run before any app import

from app.constants.http import API_V1_PREFIX
from app.constants.short_links import (
    CONTENT_ID_ALPHABET,
    CONTENT_ID_LENGTH,
    SHORTLINK_WEB_ROUTE,
    THUMBNAIL_PATH,
    UNFURL_BOT_USER_AGENT_MARKERS,
)
from app.models.short_link_models import MAX_GRANTEES, LinkAccess, LinkDenial
from app.services.links.access import ACCESS_WIDEST_FIRST, OWNER_STILL_OPENS
from app.services.links.errors import LINK_PAGE_COPY
from app.utils.loggable_path import LINK_CONTENT_ROUTE_PREFIX


class LinkConstants(TypedDict):
    contentRoute: str
    contentIdAlphabet: str
    contentIdLength: int
    thumbnailPath: str
    shortLinkWebRoute: str
    maxGrantees: int
    accessWidestFirst: list[LinkAccess]
    ownerStillOpens: list[LinkDenial]
    unfurlBotUserAgentMarkers: list[str]
    pageCopy: dict[str, str]


def link_constants() -> LinkConstants:
    return {
        "contentRoute": f"{API_V1_PREFIX}{LINK_CONTENT_ROUTE_PREFIX}",
        "contentIdAlphabet": CONTENT_ID_ALPHABET,
        "contentIdLength": CONTENT_ID_LENGTH,
        "thumbnailPath": THUMBNAIL_PATH,
        "shortLinkWebRoute": SHORTLINK_WEB_ROUTE,
        "maxGrantees": MAX_GRANTEES,
        "accessWidestFirst": list(ACCESS_WIDEST_FIRST),
        "ownerStillOpens": sorted(OWNER_STILL_OPENS),
        "unfurlBotUserAgentMarkers": list(UNFURL_BOT_USER_AGENT_MARKERS),
        "pageCopy": LINK_PAGE_COPY,
    }


if __name__ == "__main__":
    print(json.dumps(link_constants(), indent=2))
