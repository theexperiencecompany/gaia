"""The request path as logs may record it, with heygaia.link slugs and content ids masked.

Kept free of settings: the exception handlers import it, and the embedding
sidecar boots them without API secrets.
"""

import re

from fastapi import Request

SHORT_LINK_ROUTE_PREFIX = "/l"
SHORT_LINK_UNSHARE_PATH = "/unshare"
SHORT_LINK_SHARE_STATE_PATH = "/state"
LINK_CONTENT_ROUTE_PREFIX = "/usercontent"

# The owner's routes under the prefix; every other first segment is a slug.
_OWNER_SEGMENTS = "|".join(
    path.lstrip("/") for path in (SHORT_LINK_UNSHARE_PATH, SHORT_LINK_SHARE_STATE_PATH)
)

# Matched on the raw URL path, not the routed template, so a request refused
# before its route runs (405, rate limit, auth) is masked too.
_SHORT_LINK_SLUG = re.compile(
    rf"^(/api/v1{SHORT_LINK_ROUTE_PREFIX}/)(?!(?:{_OWNER_SEGMENTS})(?:/|$))[^/]+"
)
_CONTENT_ID = re.compile(rf"^(/api/v1{LINK_CONTENT_ROUTE_PREFIX}/)[^/]+")


def loggable_request_path(request: Request) -> str:
    """Return the request path as logs may record it.

    A heygaia.link slug is a working capability, so /api/v1/l/<slug> is logged
    as /api/v1/l/{slug} instead of the live link; a snapshot's content id, which
    serves its preview image with no token, is masked the same way.
    """
    path = _SHORT_LINK_SLUG.sub(r"\1{slug}", request.url.path)
    return _CONTENT_ID.sub(r"\1{content_id}", path)
