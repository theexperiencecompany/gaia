"""A brief's edition lives in the deployment's private blob store and is served only by a signed URL.

Real seams: a local-volume blob store on disk, the PNG and JPG encoders and the edition route.
Faked seams: the Chromium render and the briefings repository.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

from httpx import AsyncClient
from itsdangerous import URLSafeSerializer
from PIL import Image, JpegImagePlugin
import pytest
from tests.briefing_factories import make_briefing_payload
from tests.factories import make_user_id
import time_machine

from app.config.settings import settings
from app.constants.briefing import (
    EDITION_DELIVERY_MAX_WIDTH_PX,
    EDITION_JPG_BACKGROUND,
    EDITION_JPG_QUALITY,
    EDITION_URL_TTL_DAYS,
    BriefingKind,
    EditionFamily,
    EditionVariant,
)
from app.constants.http import API_V1_PREFIX
from app.constants.notifications import NotificationKind
from app.db.repositories.briefings import briefing_repository
from app.models.brief_document_models import BriefDelivery, BriefingModel
from app.services.briefing import edition_email, store
from app.services.briefing.edition_image import delete_edition, edition_url
from app.services.briefing.view import briefing_view
from app.services.render.image import RenderedImage

USER_ID = make_user_id()
_DATE = "2026-10-14"
_BRIEF_ID = "brief_0123456789ab"
_NOW = datetime(2026, 10, 14, 7, 0, tzinfo=UTC)
_PLAN = BriefDelivery(push=True, notification_kind=NotificationKind.BRIEFING_DAILY)
_BRIEF = make_briefing_payload(date=_DATE, template_family=EditionFamily.POSTAL, stamp_city="paris")


def _png(width: int, height: int) -> bytes:
    """Draw a transparent desk around an opaque sheet, as a desk family renders."""
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    image.paste((240, 236, 228, 255), (width // 8, height // 8, width * 7 // 8, height * 7 // 8))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, BriefingModel]:
    """Run as a self-hosted deployment: blobs on a local volume, the brief's documents in memory."""
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "LOCAL_FILE_STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "INSTANCE_SECRET", "s" * 48)
    monkeypatch.setattr("app.services.blob_store._is_mountpoint", lambda _p: True)
    monkeypatch.setattr(
        edition_email,
        "render_html_to_image",
        AsyncMock(return_value=RenderedImage(image=_png(1620, 2400), fold=0.3)),
    )
    docs: dict[str, BriefingModel] = {}

    async def upsert(brief: BriefingModel) -> BriefingModel:
        docs[brief.id] = brief
        return brief

    async def owner_of_edition(key: str) -> str | None:
        owners = [
            d.user_id for d in docs.values() if d.edition is not None and d.edition.key == key
        ]
        return owners[0] if owners else None

    monkeypatch.setattr(briefing_repository, "briefing_id_for", AsyncMock(return_value=_BRIEF_ID))
    monkeypatch.setattr(briefing_repository, "upsert_briefing", upsert)
    monkeypatch.setattr(briefing_repository, "owner_of_edition", owner_of_edition)
    monkeypatch.setattr(store, "attach_link", AsyncMock(return_value=None))
    return docs


def _striped_rgb_png(width: int, height: int) -> bytes:
    """Draw an opaque render with no alpha channel and one-pixel stripes that resampling filters blur differently."""
    image = Image.new("RGB", (width, height), (255, 255, 255))
    for x in range(0, width, 3):
        image.paste((10, 20, 30), (x, 0, x + 1, height))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _quantization_at(quality: int) -> dict[int, list[int]]:
    out = io.BytesIO()
    Image.new("RGB", (8, 8)).save(out, format="JPEG", quality=quality)
    with Image.open(out) as reference:
        assert isinstance(reference, JpegImagePlugin.JpegImageFile)
        return reference.quantization


def _path(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}"


@time_machine.travel(_NOW, tick=False)
async def test_a_self_hosted_brief_is_stored_privately_and_served_by_its_signed_url(
    world: dict[str, BriefingModel], client: AsyncClient
) -> None:
    stored = await store.store_brief(USER_ID, _DATE, BriefingKind.DAILY, _BRIEF, _PLAN)
    edition = (await briefing_view(stored)).card.edition

    assert edition is not None
    app_image = await client.get(_path(edition.image_url))
    assert stored.edition is not None
    chat_url = await edition_url(stored.edition.key, EditionVariant.JPG, _NOW)
    chat_image = await client.get(_path(chat_url))

    assert (app_image.status_code, app_image.headers["content-type"]) == (200, "image/png")
    assert chat_image.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(app_image.content)) as png:
        assert (png.format, png.width, png.mode) == ("PNG", EDITION_DELIVERY_MAX_WIDTH_PX, "RGBA")
    with Image.open(io.BytesIO(chat_image.content)) as jpg:
        assert (jpg.format, jpg.mode) == ("JPEG", "RGB")
        assert isinstance(jpg, JpegImagePlugin.JpegImageFile)
        assert jpg.quantization == _quantization_at(EDITION_JPG_QUALITY)
        # a mail client paints a progressive image as it arrives
        assert jpg.info.get("progressive") == 1
        desk = jpg.getpixel((0, 0))
    assert isinstance(desk, tuple)
    assert all(abs(c - b) <= 2 for c, b in zip(desk, EDITION_JPG_BACKGROUND, strict=True))
    assert USER_ID not in edition.image_url
    assert _BRIEF_ID not in edition.image_url


@time_machine.travel(_NOW, tick=False)
async def test_a_rerun_overwrites_the_one_image_its_brief_has(
    world: dict[str, BriefingModel], tmp_path: Path
) -> None:
    first = await store.store_brief(USER_ID, _DATE, BriefingKind.DAILY, _BRIEF, _PLAN)
    second = await store.store_brief(USER_ID, _DATE, BriefingKind.DAILY, _BRIEF, _PLAN)

    assert first.edition is not None and second.edition is not None
    key = first.edition.key
    assert second.edition.key == key
    assert sorted(p.name for p in (tmp_path / USER_ID).iterdir()) == [
        f"brief-edition-{key}.jpg",
        f"brief-edition-{key}.png",
    ]


@time_machine.travel(_NOW, tick=False)
async def test_a_url_serves_nothing_once_tampered_retargeted_expired_or_deleted(
    world: dict[str, BriefingModel], client: AsyncClient
) -> None:
    stored = await store.store_brief(USER_ID, _DATE, BriefingKind.DAILY, _BRIEF, _PLAN)
    edition = (await briefing_view(stored)).card.edition
    assert edition is not None
    url = _path(edition.image_url)

    tampered = await client.get(url[:-2] + ("AA" if not url.endswith("AA") else "BB"))
    retargeted = await client.get(url.replace("/png?", "/jpg?"))
    with time_machine.travel(_NOW + timedelta(days=EDITION_URL_TTL_DAYS + 2), tick=False):
        expired = await client.get(url)
    assert stored.edition is not None
    await delete_edition(USER_ID, stored.edition.key)
    deleted = await client.get(url)

    assert [r.status_code for r in (tampered, retargeted, expired, deleted)] == [404] * 4


@time_machine.travel(_NOW, tick=False)
async def test_an_opaque_render_is_stored_with_alpha_and_lanczos_downscaled(
    world: dict[str, BriefingModel], client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    render = _striped_rgb_png(1620, 900)
    monkeypatch.setattr(
        edition_email,
        "render_html_to_image",
        AsyncMock(return_value=RenderedImage(image=render, fold=0.3)),
    )
    stored = await store.store_brief(USER_ID, _DATE, BriefingKind.DAILY, _BRIEF, _PLAN)
    assert stored.edition is not None
    response = await client.get(
        _path(await edition_url(stored.edition.key, EditionVariant.PNG, _NOW))
    )

    with Image.open(io.BytesIO(render)) as source:
        expected = source.convert("RGBA")
    expected.thumbnail((EDITION_DELIVERY_MAX_WIDTH_PX, expected.height), Image.Resampling.LANCZOS)
    with Image.open(io.BytesIO(response.content)) as png:
        assert png.mode == "RGBA"
        assert png.tobytes() == expected.tobytes()


@time_machine.travel(_NOW, tick=False)
async def test_a_url_stops_loading_at_the_exact_second_it_expires(
    world: dict[str, BriefingModel], client: AsyncClient
) -> None:
    stored = await store.store_brief(USER_ID, _DATE, BriefingKind.DAILY, _BRIEF, _PLAN)
    assert stored.edition is not None
    url = _path(await edition_url(stored.edition.key, EditionVariant.PNG, _NOW))
    expiry_day = (_NOW + timedelta(days=EDITION_URL_TTL_DAYS)).date() + timedelta(days=1)
    expires_at = datetime(expiry_day.year, expiry_day.month, expiry_day.day, tzinfo=UTC)

    with time_machine.travel(expires_at - timedelta(seconds=1), tick=False):
        last_second = await client.get(url)
    with time_machine.travel(expires_at, tick=False):
        at_expiry = await client.get(url)

    assert (last_second.status_code, at_expiry.status_code) == (200, 404)


@pytest.mark.parametrize("salt", [None, "itsdangerous"])
@time_machine.travel(_NOW, tick=False)
async def test_a_token_signed_with_the_secret_but_not_the_edition_salt_serves_nothing(
    world: dict[str, BriefingModel], client: AsyncClient, salt: str | None
) -> None:
    stored = await store.store_brief(USER_ID, _DATE, BriefingKind.DAILY, _BRIEF, _PLAN)
    assert stored.edition is not None
    key = stored.edition.key
    far = int((_NOW + timedelta(days=EDITION_URL_TTL_DAYS)).timestamp())
    unsalted = URLSafeSerializer(settings.INSTANCE_SECRET, salt=salt).dumps([key, "png", far])

    response = await client.get(f"{API_V1_PREFIX}/briefings/editions/{key}/png?t={unsalted}")

    assert response.status_code == 404
