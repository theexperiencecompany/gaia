"""The headers a link's bytes are served with, by render mode, on the content origin and as a download.

The content origin (a per-snapshot host such as <content_id>.u.heygaia.link) is
cross-site from GAIA's app and carries no cookie, so active HTML can run there
without reaching anything of the viewer's. The CSP sandbox still gives every
document an opaque origin; frame-ancestors pins framing to the app; HTML is only
ever served into an iframe, so the content domain is never a landing page.
"""

from urllib.parse import quote

from fastapi.responses import RedirectResponse, Response

from app.config.settings import settings
from app.models.short_link_models import LinkSnapshot, RenderMode

_SHARED_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=(), hid=(), "
        "bluetooth=(), clipboard-read=(), display-capture=()"
    ),
    "X-Robots-Tag": "noindex, nofollow",
}
SNAPSHOT_CACHE_CONTROL = "private, max-age=600"
THUMBNAIL_CACHE_CONTROL = "public, max-age=3600"
_INERT_CSP = "default-src 'none'; sandbox"
_DOWNLOAD_MIME = "application/octet-stream"
# Scripts, styles and fonts from any CDN (agent reports draw charts), but no way to send
# anything anywhere: no fetch/XHR/WebSocket/beacon, no form post, no nested frame or worker.
_FRAME_ACTIVE_CSP = (
    "sandbox allow-scripts allow-forms allow-modals allow-popups "
    "allow-popups-to-escape-sandbox allow-downloads; "
    "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' https:; "
    "style-src 'unsafe-inline' https:; img-src data: blob: https:; font-src data: https:; "
    "media-src data: blob: https:; connect-src 'none'; form-action 'none'; base-uri 'none'; "
    "frame-src 'none'; worker-src 'none'; frame-ancestors {app_origin}"
)
# Browsers refuse to render a PDF in a sandboxed document, so its isolation is the origin alone.
_PDF_CSP = "default-src 'none'; object-src 'self'; frame-ancestors {app_origin}"
_SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox"


def _attachment(filename: str) -> str:
    return f"attachment; filename*=UTF-8''{quote(filename, safe='')}"


def _response(
    body: bytes, media_type: str, csp: str, disposition: str, cache_control: str
) -> Response:
    return Response(
        body,
        media_type=media_type,
        headers={
            **_SHARED_HEADERS,
            "Content-Security-Policy": csp,
            "Content-Disposition": disposition,
            "Cache-Control": cache_control,
        },
    )


def snapshot_response(
    body: bytes, snapshot: LinkSnapshot, fetch_dest: str | None, link_url: str
) -> Response:
    """Serve a snapshot's bytes on the content origin, as its render mode and the requesting element allow.

    HTML anywhere but an iframe goes back to the link page; SVG anywhere but an
    <img> downloads, so neither ever runs as a top-level document.
    """
    app_origin = settings.FRONTEND_URL
    match snapshot.render:
        case RenderMode.FRAME_ACTIVE:
            if fetch_dest != "iframe":
                return RedirectResponse(link_url, status_code=302)
            csp = _FRAME_ACTIVE_CSP.format(app_origin=app_origin)
            return _response(
                body, f"{snapshot.mime}; charset=utf-8", csp, "inline", SNAPSHOT_CACHE_CONTROL
            )
        case RenderMode.IMAGE_SVG:
            disposition = "inline" if fetch_dest == "image" else _attachment(snapshot.filename)
            return _response(body, snapshot.mime, _SVG_CSP, disposition, SNAPSHOT_CACHE_CONTROL)
        case RenderMode.PDF:
            csp = _PDF_CSP.format(app_origin=app_origin)
            return _response(body, snapshot.mime, csp, "inline", SNAPSHOT_CACHE_CONTROL)
        case RenderMode.TEXT:
            return _response(
                body, "text/plain; charset=utf-8", _INERT_CSP, "inline", SNAPSHOT_CACHE_CONTROL
            )
        case RenderMode.IMAGE | RenderMode.MEDIA:
            return _response(body, snapshot.mime, _INERT_CSP, "inline", SNAPSHOT_CACHE_CONTROL)
        case RenderMode.DOWNLOAD:
            return download_response(body, snapshot)


def download_response(body: bytes, snapshot: LinkSnapshot) -> Response:
    """Serve a snapshot as a file to save, never rendered: safe from any origin, the app's included."""
    return _response(
        body, _DOWNLOAD_MIME, _INERT_CSP, _attachment(snapshot.filename), "private, no-store"
    )


def thumbnail_response(body: bytes) -> Response:
    return _response(body, "image/jpeg", _INERT_CSP, "inline", THUMBNAIL_CACHE_CONTROL)
