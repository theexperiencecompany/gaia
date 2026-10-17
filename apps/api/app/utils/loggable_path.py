"""The request path as logs may record it, with heygaia.link slugs masked.

Kept free of settings: the exception handlers import it, and the embedding
sidecar boots them without API secrets.
"""

import re

from fastapi import Request

SHORT_LINK_ROUTE_PREFIX = "/l"
SHORT_LINK_UNSHARE_PATH = "/unshare"

# Matched on the raw URL path, not the routed template, so a request refused
# before its route runs (405, rate limit, auth) is masked too.
_SHORT_LINK_SLUG = re.compile(
    rf"^(/api/v1{SHORT_LINK_ROUTE_PREFIX}/)"
    rf"(?!{SHORT_LINK_UNSHARE_PATH.lstrip('/')}(?:/|$))[^/]+"
)


def loggable_request_path(request: Request) -> str:
    """Return the request path as logs may record it.

    A heygaia.link slug is a working capability, so /api/v1/l/<slug> is logged
    as /api/v1/l/{slug} instead of the live link.
    """
    return _SHORT_LINK_SLUG.sub(r"\1{slug}", request.url.path)
