"""Single-purpose file-share downloads (token-gated, no session).

Composio fetches these URLs server-side during tool execution, so the route
carries no auth dependency — the unguessable token IS the credential (the path
is in the auth middleware's exclude list for the same reason as the HMAC-signed
unsubscribe link). All failures read as one uniform 404: tampered, expired,
missing, oversize, and unknown tokens are indistinguishable on the wire.

The token rides in the query string while the filename stays in the path: our
request logger records paths (never query), and Composio's own error sanitizer
redacts query strings — so neither side's logs retain the bearer. Composio's
fetcher derives the attachment name from the path basename, which keeps working.
"""

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.services.share_service import redeem_share_grant
from shared.py.wide_events import log

router = APIRouter()


def _download_headers(filename: str) -> dict[str, str]:
    """Force download semantics: a token link must never render as a page.

    An attacker-minted HTML/SVG/JS file opened in a browser would otherwise
    execute in the API origin (stored XSS with ambient session authority), so
    the response is download-only, unsniffable, and uncacheable. The filename
    is server-side (never the URL segment) and stripped to header-safe chars.
    """
    safe = re.sub(r'["\r\n]', "", filename).encode("latin-1", "ignore").decode("latin-1")
    return {
        "Content-Disposition": f'attachment; filename="{safe or "download"}"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store, max-age=0",
    }


# Both spellings route to the same handler: the trailing-slash variant exists
# so Starlette never 307-redirects (which would echo the bearer token into a
# Location header) — include_router drops a router-level redirect_slashes flag.
@router.get("/files/s/{filename}", include_in_schema=False)
@router.get("/files/s/{filename}/", include_in_schema=False)
async def download_shared_file(filename: str, token: str = "") -> Response:
    """Serve one granted file's bytes. ``filename`` is cosmetic (Composio's
    fetcher derives the attachment name from the URL basename); resolution uses
    only the token, so a swapped segment cannot reach another file. The served
    filename — and the download header — always come from the signed grant, not
    the URL. ``token`` defaults to "" (instead of required) so a missing key
    reads as the same uniform 404 rather than a distinguishing 422."""
    log.set(share={"operation": "redeem"})
    result = await redeem_share_grant(token)
    if result is None:
        log.set_ns("share", redeemed=False)
        raise HTTPException(status_code=404, detail="Not found")
    content, filename, mimetype = result
    log.set_ns("share", redeemed=True, byte_count=len(content))
    return Response(content=content, media_type=mimetype, headers=_download_headers(filename))
