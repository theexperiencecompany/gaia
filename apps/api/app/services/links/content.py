"""Publish a shared file as an immutable snapshot, and sign the tokens that load it.

A snapshot is the file's bytes as they were when the link was minted (or the
agent rewrote the file), stored under a random content_id that is also its
origin on the content domain. The type it is served as comes from the bytes,
not the name: a declared type the magic bytes disagree with is a download.
"""

import asyncio
import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import io
import re
import secrets
from urllib.parse import urlsplit

import filetype
from PIL import Image, UnidentifiedImageError
import pymupdf

from app.agents.workspace.paths import is_inlineable_content_type
from app.config.settings import settings
from app.constants.files import BlobKind
from app.constants.short_links import (
    CONTENT_HMAC_DOMAIN,
    CONTENT_ID_ALPHABET,
    CONTENT_ID_LENGTH,
    CONTENT_TOKEN_TTL_SECONDS,
    EXECUTABLE_EXTENSIONS,
    MAX_HTML_SNAPSHOT_BYTES,
    MAX_PUBLISHED_BYTES_PER_DAY,
    MAX_SNAPSHOT_BYTES,
    MAX_STORED_SNAPSHOT_BYTES,
    MAX_SVG_SNAPSHOT_BYTES,
    PUBLISHED_BYTES_KEY,
    PUBLISHED_BYTES_TTL_SECONDS,
    REPEAT_ABUSE_TAKEDOWNS,
    THUMBNAIL_MAX_BYTES,
    THUMBNAIL_PATH,
    THUMBNAIL_SIZE,
)
from app.db.redis import redis_cache
from app.db.repositories.short_links import short_link_repository
from app.models.short_link_models import (
    LinkAccess,
    LinkContent,
    LinkSnapshot,
    PublishRejection,
    RenderMode,
    ShortLink,
    ShortLinkTargetType,
)
from app.services.analytics_service import analytics_day_start, capture
from app.services.blob_store import link_content_store
from app.services.links.access import at_most
from app.services.links.spec import SnapshotSource
from app.services.links.web_risk import flagged_urls
from shared.py.analytics import UserId
from shared.py.analytics.catalog.short_links import (
    ShortLinkContentPublished,
    ShortLinkPublishRejected,
)
from shared.py.wide_events import log

_DOWNLOAD_MIME = "application/octet-stream"

# Declared types served as themselves once the bytes agree; anything else is TEXT or a download.
_RENDER_BY_MIME: dict[str, RenderMode] = {
    "text/html": RenderMode.FRAME_ACTIVE,
    "application/xhtml+xml": RenderMode.FRAME_ACTIVE,
    "image/png": RenderMode.IMAGE,
    "image/jpeg": RenderMode.IMAGE,
    "image/gif": RenderMode.IMAGE,
    "image/webp": RenderMode.IMAGE,
    "image/avif": RenderMode.IMAGE,
    "image/svg+xml": RenderMode.IMAGE_SVG,
    "application/pdf": RenderMode.PDF,
    "video/mp4": RenderMode.MEDIA,
    "video/webm": RenderMode.MEDIA,
    "audio/mpeg": RenderMode.MEDIA,
    "audio/ogg": RenderMode.MEDIA,
    "audio/wav": RenderMode.MEDIA,
    "audio/x-wav": RenderMode.MEDIA,
}
# Types whose bytes are text: they must decode as UTF-8 and carry no binary signature.
_TEXTUAL_RENDERS = frozenset({RenderMode.FRAME_ACTIVE, RenderMode.IMAGE_SVG, RenderMode.TEXT})
# What filetype reports for a matching binary: webm and wav sniff under another name.
_MAGIC_ALIASES: dict[str, frozenset[str]] = {
    "video/webm": frozenset({"video/webm", "video/x-matroska"}),
    "audio/wav": frozenset({"audio/x-wav", "audio/wav"}),
    "audio/x-wav": frozenset({"audio/x-wav", "audio/wav"}),
    "audio/ogg": frozenset({"audio/ogg", "video/ogg"}),
}
_SIZE_CAPS: dict[RenderMode, int] = {
    RenderMode.FRAME_ACTIVE: MAX_HTML_SNAPSHOT_BYTES,
    RenderMode.IMAGE_SVG: MAX_SVG_SNAPSHOT_BYTES,
}
_ABSOLUTE_URL = re.compile(rb"""https?://[^\s"'<>()]+""", re.IGNORECASE)
_SENSITIVE_INPUT = re.compile(
    rb"""<input\b[^>]*\btype\s*=\s*["']?password|autocomplete\s*=\s*["']?cc-""", re.IGNORECASE
)
_SIZE_BUCKETS = ((100 * 1024, "lt_100kb"), (1024 * 1024, "lt_1mb"), (10 * 1024 * 1024, "lt_10mb"))


@dataclass(frozen=True, slots=True)
class ServedType:
    mime: str
    render: RenderMode


def new_content_id() -> str:
    return "".join(secrets.choice(CONTENT_ID_ALPHABET) for _ in range(CONTENT_ID_LENGTH))


def _is_text(data: bytes) -> bool:
    if filetype.guess_mime(data) is not None:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def served_type(declared_mime: str, data: bytes) -> ServedType:
    """Decide what the bytes are served as: the declared type when the bytes agree, else a download."""
    render = _RENDER_BY_MIME.get(declared_mime)
    if render is None and is_inlineable_content_type(declared_mime):
        render = RenderMode.TEXT
    if render is None:
        return ServedType(_DOWNLOAD_MIME, RenderMode.DOWNLOAD)
    if render in _TEXTUAL_RENDERS:
        agrees = _is_text(data)
    else:
        sniffed = filetype.guess_mime(data)
        agrees = sniffed in _MAGIC_ALIASES.get(declared_mime, frozenset({declared_mime}))
    if not agrees:
        return ServedType(_DOWNLOAD_MIME, RenderMode.DOWNLOAD)
    return ServedType(declared_mime, render)


def _extension(filename: str) -> str:
    _, dot, ext = filename.rpartition(".")
    return ext.lower() if dot else ""


async def _restriction(
    owner_id: str, filename: str, data: bytes, render: RenderMode
) -> tuple[LinkAccess, PublishRejection] | None:
    """Return the widest level these bytes may be served at, when something narrows it."""
    if _extension(filename) in EXECUTABLE_EXTENSIONS:
        return LinkAccess.OWNER, PublishRejection.RESTRICTED_TYPE
    if render not in (RenderMode.FRAME_ACTIVE, RenderMode.IMAGE_SVG):
        return None
    if render is RenderMode.FRAME_ACTIVE and _SENSITIVE_INPUT.search(data):
        return LinkAccess.PEOPLE, PublishRejection.RESTRICTED_TYPE
    if (
        render is RenderMode.FRAME_ACTIVE
        and await short_link_repository.count_takedowns(owner_id) >= REPEAT_ABUSE_TAKEDOWNS
    ):
        return LinkAccess.PEOPLE, PublishRejection.RESTRICTED_TYPE
    urls = sorted({match.decode(errors="replace") for match in _ABSOLUTE_URL.findall(data)})
    if urls and await flagged_urls(urls):
        return LinkAccess.PEOPLE, PublishRejection.UNSAFE_URL
    return None


def _jpeg(image: Image.Image) -> bytes | None:
    """Fit image into the preview card and encode it under the size cap; None when it cannot fit."""
    card = image.convert("RGB")
    card.thumbnail(THUMBNAIL_SIZE)
    canvas = Image.new("RGB", THUMBNAIL_SIZE, (24, 24, 27))
    canvas.paste(
        card, ((THUMBNAIL_SIZE[0] - card.width) // 2, (THUMBNAIL_SIZE[1] - card.height) // 2)
    )
    for quality in (85, 70, 55):
        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=quality, optimize=True)
        if out.tell() <= THUMBNAIL_MAX_BYTES:
            return out.getvalue()
    return None


def _thumbnail(render: RenderMode, data: bytes) -> bytes | None:
    """Render the preview image of a raster or a PDF's first page; other types get the generated card."""
    try:
        if render is RenderMode.IMAGE:
            with Image.open(io.BytesIO(data)) as image:
                return _jpeg(image)
        if render is RenderMode.PDF:
            with pymupdf.open(stream=data, filetype="pdf") as document:
                if document.page_count == 0:
                    return None
                pixmap = document[0].get_pixmap(dpi=96)
                return _jpeg(Image.open(io.BytesIO(pixmap.tobytes("png"))))
    except (UnidentifiedImageError, pymupdf.FileDataError, OSError, ValueError) as exc:
        # A broken file still shares; only its preview image is lost.
        log.warning(
            "short_link.thumbnail_failed", render=render.value, error_type=type(exc).__name__
        )
    return None


def _size_bucket(size: int) -> str:
    return next((name for limit, name in _SIZE_BUCKETS if size < limit), "gte_10mb")


async def _within_quota(owner_id: str, size: int) -> bool:
    if not settings.deployment.enforces_usage_limits:
        return True
    if (
        await short_link_repository.stored_snapshot_bytes(owner_id) + size
        > MAX_STORED_SNAPSHOT_BYTES
    ):
        return False
    day = analytics_day_start(datetime.now(UTC)).date().isoformat()
    key = PUBLISHED_BYTES_KEY.format(user_id=owner_id, day=day)
    published = await redis_cache.client.incr(key, size)
    await redis_cache.client.expire(key, PUBLISHED_BYTES_TTL_SECONDS)
    return published <= MAX_PUBLISHED_BYTES_PER_DAY


def _rejected(
    owner_id: str,
    target_type: ShortLinkTargetType,
    source: SnapshotSource,
    kind: ServedType,
    reason: PublishRejection,
) -> LinkSnapshot:
    capture(
        UserId(owner_id),
        ShortLinkPublishRejected(target_type=target_type.value, reason=reason.value),
    )
    return LinkSnapshot(
        filename=source.filename,
        mime=kind.mime,
        size_bytes=source.size_bytes,
        render=kind.render,
        content_id=None,
        rejected=reason,
    )


def _object_key(content_id: str) -> str:
    return f"link_{content_id}"


def _thumbnail_key(content_id: str) -> str:
    return f"link_{content_id}_thumb"


async def publish(
    owner_id: str, target_type: ShortLinkTargetType, source: SnapshotSource
) -> LinkSnapshot:
    """Store source as a new snapshot and describe it; a capped or over-quota file is described, not stored."""
    data = source.data
    if data is None:
        unread = ServedType(_DOWNLOAD_MIME, RenderMode.DOWNLOAD)
        return _rejected(owner_id, target_type, source, unread, PublishRejection.TOO_LARGE)
    kind = served_type(source.declared_mime, data)
    size = len(data)
    if size > min(MAX_SNAPSHOT_BYTES, _SIZE_CAPS.get(kind.render, MAX_SNAPSHOT_BYTES)):
        return _rejected(owner_id, target_type, source, kind, PublishRejection.TOO_LARGE)
    if not await _within_quota(owner_id, size):
        return _rejected(owner_id, target_type, source, kind, PublishRejection.QUOTA)
    restriction = await _restriction(owner_id, source.filename, data, kind.render)
    content_id = new_content_id()
    store = link_content_store()
    await store.put(
        owner_id,
        _object_key(content_id),
        data,
        resource_type="raw",
        kind=BlobKind.LINK_SNAPSHOT,
        content_type=kind.mime,
    )
    thumbnail = await asyncio.to_thread(_thumbnail, kind.render, data)
    if thumbnail is not None:
        await store.put(
            owner_id,
            _thumbnail_key(content_id),
            thumbnail,
            resource_type="image",
            kind=BlobKind.LINK_SNAPSHOT,
            content_type="image/jpeg",
        )
    capture(
        UserId(owner_id),
        ShortLinkContentPublished(
            target_type=target_type.value,
            render_mode=kind.render.value,
            size_bucket=_size_bucket(size),
        ),
    )
    if restriction is not None:
        capture(
            UserId(owner_id),
            ShortLinkPublishRejected(target_type=target_type.value, reason=restriction[1].value),
        )
    return LinkSnapshot(
        filename=source.filename,
        mime=kind.mime,
        size_bytes=size,
        render=kind.render,
        content_id=content_id,
        digest=hashlib.sha256(data).hexdigest(),
        has_thumbnail=thumbnail is not None,
        max_access=restriction[0] if restriction else LinkAccess.PUBLIC,
        restricted_by=restriction[1] if restriction else None,
    )


def unchanged(snapshot: LinkSnapshot | None, source: SnapshotSource) -> bool:
    """Whether source is byte-for-byte the snapshot already published."""
    return (
        snapshot is not None
        and snapshot.digest is not None
        and source.data is not None
        and hashlib.sha256(source.data).hexdigest() == snapshot.digest
    )


async def delete_snapshot(owner_id: str, snapshot: LinkSnapshot) -> None:
    """Remove a snapshot's bytes and preview image from the store."""
    if snapshot.content_id is None:
        return
    store = link_content_store()
    await store.delete(owner_id, _object_key(snapshot.content_id))
    if snapshot.has_thumbnail:
        await store.delete(owner_id, _thumbnail_key(snapshot.content_id))


async def read_snapshot(owner_id: str, content_id: str) -> bytes:
    return await link_content_store().read(owner_id, _object_key(content_id), "")


async def read_thumbnail(owner_id: str, content_id: str) -> bytes:
    return await link_content_store().read(owner_id, _thumbnail_key(content_id), "")


def active_link_content() -> bool:
    """Whether this deployment has a content origin, so HTML runs and files frame in place."""
    return bool(settings.LINK_CONTENT_URL_TEMPLATE and settings.LINK_CONTENT_SIGNING_KEY)


# Without a content origin only text renders in place; HTML shows as its source.
_WITHOUT_ORIGIN: dict[RenderMode, RenderMode] = {RenderMode.FRAME_ACTIVE: RenderMode.TEXT}


def presented_render(snapshot: LinkSnapshot) -> RenderMode:
    """How the page shows a snapshot on this deployment."""
    if active_link_content() or snapshot.render is RenderMode.TEXT:
        return snapshot.render
    return _WITHOUT_ORIGIN.get(snapshot.render, RenderMode.DOWNLOAD)


def servable(snapshot: LinkSnapshot | None, access: LinkAccess) -> bool:
    """Whether a link at access may serve the snapshot's bytes at all."""
    return (
        snapshot is not None
        and snapshot.content_id is not None
        and at_most(access, snapshot.max_access)
    )


def framed_content(snapshot: LinkSnapshot | None, access: LinkAccess) -> LinkContent | None:
    """Return what the page loads from the content origin; None when it renders the view alone."""
    if snapshot is None or snapshot.content_id is None or not servable(snapshot, access):
        return None
    render = presented_render(snapshot)
    if render in (RenderMode.TEXT, RenderMode.DOWNLOAD):
        return None
    return LinkContent(
        content_id=snapshot.content_id,
        mime=snapshot.mime,
        size_bytes=snapshot.size_bytes,
        render=render,
    )


def content_origin_base(content_id: str) -> str:
    template = settings.LINK_CONTENT_URL_TEMPLATE
    if template is None:
        raise RuntimeError("LINK_CONTENT_URL_TEMPLATE is unset; check active_link_content() first")
    return template.format(content_id=content_id).rstrip("/")


def content_origin_host(content_id: str) -> str:
    return urlsplit(content_origin_base(content_id)).netloc.lower()


def thumbnail_url(content_id: str) -> str:
    return f"{content_origin_base(content_id)}/{THUMBNAIL_PATH}"


def _link_version(link: ShortLink) -> str:
    """Name the link as a token binds to it: slug and last change, so rotating or narrowing voids old tokens."""
    changed = link.updated_at or link.created_at
    return f"{link.slug}:{int(changed.timestamp() * 1000)}"


def _signature(content_id: str, link: ShortLink, expires: int) -> str:
    key = settings.LINK_CONTENT_SIGNING_KEY
    if key is None:
        raise RuntimeError("LINK_CONTENT_SIGNING_KEY is unset; check active_link_content() first")
    message = f"{CONTENT_HMAC_DOMAIN}:{content_id}:{_link_version(link)}:{expires}".encode()
    digest = hmac.new(key.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def issue_content_url(link: ShortLink, content_id: str, now: datetime) -> tuple[str, datetime]:
    """Sign a URL that loads content_id through link from its origin until the returned time."""
    expires_at = now + timedelta(seconds=CONTENT_TOKEN_TTL_SECONDS)
    expires = int(expires_at.timestamp())
    token = f"{expires}.{_signature(content_id, link, expires)}"
    return f"{content_origin_base(content_id)}/?t={token}", expires_at


def token_valid(link: ShortLink, content_id: str, token: str, now: datetime) -> bool:
    """Whether token was signed for content_id through link as it is now, and has not expired."""
    expires_text, _, signature = token.partition(".")
    if not expires_text.isdigit() or int(expires_text) <= now.timestamp():
        return False
    return hmac.compare_digest(signature, _signature(content_id, link, int(expires_text)))
