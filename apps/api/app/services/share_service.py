"""Single-purpose share links for files Composio must fetch itself.

Some Composio tools take a file as a path/URL string (Outlook send/draft,
Slack uploads) that Composio fetches during execution — but it cannot read
sandbox ``/workspace/...`` paths (auto-upload is off), so a workspace-local
value would fail downstream. Minting a grant URL here gives Composio something
fetchable: an unguessable, minutes-lived, single-file bearer on our own API
that serves the bytes directly (Composio's fetcher refuses redirects, so no
302-to-CDN hop is possible).

``mint_share_url`` is sync on purpose: hook functions (the only mint callers)
run in Composio's synchronous modifier chain and cannot await. Everything it
touches synchronously is fast (path containment stat check + HMAC sign); the
redeem side is async because it reads file bytes.
"""

import mimetypes
import time
from urllib.parse import quote
import uuid

from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import ValidationError

from app.config.settings import settings
from app.constants.files import (
    SHARE_GRANT_MAX_BYTES,
    SHARE_GRANT_MAX_TTL_SECONDS,
    SHARE_GRANT_TTL_SECONDS,
)
from app.models.share_models import ShareGrantPayload
from app.services.storage.juicefs import (
    JuiceFSUnavailable,
    read_user_file_bytes,
    resolve_user_file_sync,
    to_workspace_relative_path,
)
from app.utils.errors import AppError
from shared.py.wide_events import log

_SALT = "file-share-grant"


def _configured_secret() -> str | None:
    """The share signing secret, or None if it is unset or too short to use."""
    secret: object = settings.SHARE_GRANT_SECRET
    return secret if isinstance(secret, str) and len(secret) >= 32 else None


def _require_secret() -> str:
    secret = _configured_secret()
    if secret is None:
        raise AppError(
            message="File sharing is not configured.",
            why="The share signing secret (SHARE_GRANT_SECRET) is missing or too short.",
            fix="Set SHARE_GRANT_SECRET to 32+ random characters and retry.",
            status_code=503,
        )
    return secret


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_require_secret(), salt=_SALT)


def mint_share_url(
    *,
    user_id: str,
    workspace_path: str,
    max_bytes: int = SHARE_GRANT_MAX_BYTES,
    ttl_seconds: int = SHARE_GRANT_TTL_SECONDS,
    tool: str | None = None,
    toolkit: str | None = None,
) -> str:
    """Mint a minutes-lived bearer URL for one workspace file.

    Fails fast: a missing/unreadable file raises here (so the caller aborts
    before the tool runs) rather than minting a link that 404s at fetch time.
    The token rides in the query string (not the path) so request logs and
    Composio's error sanitizer — which redacts query strings — never retain it.
    """
    if ttl_seconds <= 0:
        raise AppError(
            message="Invalid share lifetime.",
            why="ttl_seconds must be positive.",
            fix="Pass a positive ttl_seconds and retry.",
            status_code=400,
        )
    rel = to_workspace_relative_path(workspace_path)
    host_path = resolve_user_file_sync(user_id, rel)
    payload = ShareGrantPayload(
        user_id=user_id,
        workspace_rel_path=rel,
        filename=host_path.name,
        mimetype=mimetypes.guess_type(host_path.name)[0] or "application/octet-stream",
        max_bytes=max_bytes,
        expires_at=time.time() + min(ttl_seconds, SHARE_GRANT_MAX_TTL_SECONDS),
        nonce=uuid.uuid4().hex,
        tool=tool,
        toolkit=toolkit,
    )
    token = _serializer().dumps(payload.model_dump())
    # `safe=''` is defence in depth: the filename is a Path.name, so a path
    # separator cannot reach here in the first place.
    return f"{settings.HOST}/api/v1/files/s/{quote(payload.filename, safe='')}?token={token}"  # pragma: no mutate -- quote() sees a Path.name, which holds no separator


async def redeem_share_grant(token: str) -> tuple[bytes, str, str] | None:
    """Validate a bearer token and read the granted file.

    Returns ``(content, filename, mimetype)``, or None for every failure mode
    (tampered, expired, missing, oversized, mount unavailable) — the route maps
    all of them to one uniform 404 so failures give no oracle.
    """
    # Misconfiguration is one of the failure modes, not an exception out of the
    # route: a secret too short to sign with would otherwise surface as a 503 and
    # tell a prober the difference between "bad token" and "server misconfigured".
    if _configured_secret() is None:
        return None
    try:
        payload = ShareGrantPayload.model_validate(_serializer().loads(token))
    except (BadSignature, ValidationError):
        log.debug("Share grant rejected: bad signature or shape")
        return None
    if payload.expires_at < time.time():
        log.debug("Share grant rejected: expired")
        return None
    try:
        content = await read_user_file_bytes(
            payload.user_id, payload.workspace_rel_path, max_bytes=payload.max_bytes
        )
    except (FileNotFoundError, ValueError, JuiceFSUnavailable, OSError):
        return None
    return content, payload.filename, payload.mimetype
