"""Keep a brief's edition image in the deployment's private blob store, and sign the URLs that load it.

Each brief's edition has one opaque key, derived from its id, so a re-render overwrites the same
blobs and erasure finds them. Every surface (the app, the email, the chat post, a shared link)
loads it through a signed, expiring URL on the API's own edition route that names neither the
brief nor the user.
"""

import asyncio
from datetime import datetime, timedelta
import hashlib
import hmac
import io
import math

from itsdangerous import BadSignature, URLSafeSerializer
from PIL import Image
from pydantic import TypeAdapter

from app.config.settings import settings
from app.constants.briefing import (
    EDITION_DELIVERY_MAX_WIDTH_PX,
    EDITION_JPG_BACKGROUND,
    EDITION_JPG_QUALITY,
    EDITION_KEY_CHARS,
    EDITION_URL_SALT,
    EDITION_URL_TTL_DAYS,
    EditionVariant,
)
from app.constants.files import BlobKind
from app.constants.http import API_V1_PREFIX
from app.db.repositories.briefings import briefing_repository
from app.services.blob_store import link_content_store
from app.services.runtime.secrets_store import get_instance_secret

#: The media type each variant is stored and served as.
EDITION_CONTENT_TYPES: dict[EditionVariant, str] = {
    EditionVariant.PNG: "image/png",
    EditionVariant.JPG: "image/jpeg",
}
_DAY_SECONDS = 86_400
#: What a URL's token signs: the edition key, the variant and when it stops loading (epoch seconds).
_SIGNED = TypeAdapter(tuple[str, EditionVariant, int])


def _blob(key: str, variant: EditionVariant) -> str:
    return f"brief-edition-{key}.{variant.value}"


async def edition_key(briefing_id: str) -> str:
    """Return the brief's edition key: unguessable, and the same for every render of the brief."""
    secret = await get_instance_secret()
    digest = hmac.new(secret.encode(), f"{EDITION_URL_SALT}:{briefing_id}".encode(), hashlib.sha256)
    return digest.hexdigest()[:EDITION_KEY_CHARS]


def _encoded(png: bytes) -> dict[EditionVariant, bytes]:
    """Cap the render at the delivery width and encode each variant from it."""
    with Image.open(io.BytesIO(png)) as rendered:
        image = rendered.convert("RGBA")
    image.thumbnail((EDITION_DELIVERY_MAX_WIDTH_PX, image.height), Image.Resampling.LANCZOS)
    lossless = io.BytesIO()
    image.save(
        lossless,
        format="PNG",  # pragma: no mutate — Pillow upper-cases format
    )
    flattened = Image.new("RGB", image.size, EDITION_JPG_BACKGROUND)
    flattened.paste(image, mask=image.getchannel("A"))
    compact = io.BytesIO()
    flattened.save(
        compact,
        format="JPEG",  # pragma: no mutate — Pillow upper-cases format
        quality=EDITION_JPG_QUALITY,
        # a mail client paints a progressive image as it arrives, not once it has all landed
        progressive=True,
    )
    return {EditionVariant.PNG: lossless.getvalue(), EditionVariant.JPG: compact.getvalue()}


async def store_edition(owner_id: str, briefing_id: str, png: bytes) -> str:
    """Store the brief's rendered edition as every variant over its last render; return its key."""
    key = await edition_key(briefing_id)
    encoded = await asyncio.to_thread(_encoded, png)
    store = link_content_store()
    for variant, content in encoded.items():
        await store.put(  # pragma: no mutate — every served store discards resource_type
            owner_id,
            _blob(key, variant),
            content,
            resource_type="image",  # pragma: no mutate — every served store discards it
            kind=BlobKind.GENERATED_IMAGE,
            content_type=EDITION_CONTENT_TYPES[variant],
        )
    return key


async def delete_edition(owner_id: str, key: str) -> None:
    """Delete every variant of an edition; erasure calls this with each brief's edition key."""
    store = link_content_store()
    for variant in EditionVariant:
        await store.delete(owner_id, _blob(key, variant))


async def _signer() -> URLSafeSerializer:
    return URLSafeSerializer(await get_instance_secret(), salt=EDITION_URL_SALT)


def _expiry(now: datetime) -> int:
    """Return when a URL issued now stops loading, rounded up to a day so a day's URLs are one."""
    deadline = (now + timedelta(days=EDITION_URL_TTL_DAYS)).timestamp()
    return math.ceil(deadline / _DAY_SECONDS) * _DAY_SECONDS


async def edition_url(key: str, variant: EditionVariant, now: datetime) -> str:
    """Sign the URL that loads one variant of an edition for EDITION_URL_TTL_DAYS."""
    token = (await _signer()).dumps([key, variant.value, _expiry(now)])
    return f"{settings.HOST}{API_V1_PREFIX}/briefings/editions/{key}/{variant.value}?t={token}"


async def signed_edition(
    key: str, variant: EditionVariant, token: str, now: datetime
) -> bytes | None:
    """Return the variant's bytes when token signs this edition and variant and has not expired."""
    try:
        signed_key, signed_variant, expires = _SIGNED.validate_python(
            (await _signer()).loads(token)
        )
    except BadSignature:
        return None
    if (signed_key, signed_variant) != (key, variant) or expires <= now.timestamp():
        return None
    owner_id = await briefing_repository.owner_of_edition(key)
    if owner_id is None:
        return None
    try:
        return await link_content_store().read(  # pragma: no mutate — served stores discard url
            owner_id,
            _blob(key, variant),
            "",  # pragma: no mutate — served stores read by key and discard the url
        )
    except FileNotFoundError:
        return None
