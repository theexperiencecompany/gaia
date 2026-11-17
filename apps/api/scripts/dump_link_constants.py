"""Print the share-link constants the usercontent Worker, the CLI and the self-host Caddyfile mirror.

`mise links:constants` writes them to apps/usercontent-worker/src/ and
packages/cli/src/lib/ as link-constants.generated.json and checks the
Caddyfile's routes; CI's link-constants check fails when any of them drifts.
"""

import json
from typing import TypedDict

from app.constants.http import API_V1_PREFIX
from app.constants.short_links import (
    CONTENT_ID_ALPHABET,
    CONTENT_ID_LENGTH,
    SHORTLINK_WEB_ROUTE,
    THUMBNAIL_PATH,
)
from app.utils.loggable_path import LINK_CONTENT_ROUTE_PREFIX


class LinkConstants(TypedDict):
    contentRoute: str
    contentIdAlphabet: str
    contentIdLength: int
    thumbnailPath: str
    shortLinkWebRoute: str


def link_constants() -> LinkConstants:
    return {
        "contentRoute": f"{API_V1_PREFIX}{LINK_CONTENT_ROUTE_PREFIX}",
        "contentIdAlphabet": CONTENT_ID_ALPHABET,
        "contentIdLength": CONTENT_ID_LENGTH,
        "thumbnailPath": THUMBNAIL_PATH,
        "shortLinkWebRoute": SHORTLINK_WEB_ROUTE,
    }


if __name__ == "__main__":
    print(json.dumps(link_constants(), indent=2))
