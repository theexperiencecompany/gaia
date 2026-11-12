"""Publishing a shared file: what its bytes are served as, what narrows who may see them, and the tokens that load them."""

import base64
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import io
from pathlib import Path
import random
from unittest.mock import AsyncMock, call, patch
import wave

import fakeredis.aioredis
from PIL import Image
import pymupdf
import pytest
import time_machine

from app.config.settings import settings
from app.constants.files import BlobKind
from app.constants.short_links import (
    CONTENT_TOKEN_TTL_SECONDS,
    MAX_HTML_SNAPSHOT_BYTES,
    MAX_PUBLISHED_BYTES_PER_DAY,
    MAX_SNAPSHOT_BYTES,
    MAX_STORED_SNAPSHOT_BYTES,
    MAX_SVG_SNAPSHOT_BYTES,
    PUBLISHED_BYTES_TTL_SECONDS,
    THUMBNAIL_MAX_BYTES,
    THUMBNAIL_SIZE,
)
from app.models.short_link_models import (
    LinkAccess,
    LinkSnapshot,
    PublishRejection,
    RenderMode,
    ShortLink,
    ShortLinkTargetType,
)
from app.services.blob_store import LocalVolumeBlobStore
from app.services.links import content
from app.services.links.content import (
    ServedType,
    framed_content,
    issue_content_url,
    presented_render,
    publish,
    served_type,
    token_valid,
    unchanged,
)
from app.services.links.spec import SnapshotSource
from shared.py.analytics import UserId
from shared.py.analytics.catalog.short_links import (
    ShortLinkContentPublished,
    ShortLinkPublishRejected,
)
from tests.helpers import captured_wide_event

OWNER = "507f1f77bcf86cd799439011"
SESSION = ShortLinkTargetType.SESSION_ARTIFACT
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 20), (200, 10, 10)).save(out, format="PNG")
    return out.getvalue()


def _pdf() -> bytes:
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Quarterly report")
        return document.tobytes()


def _wav() -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 80)
    return out.getvalue()


def _pdf_page(width: float, height: float) -> bytes:
    with pymupdf.open() as document:
        document.new_page(width=width, height=height)
        return document.tobytes()


PNG = _png()
PDF = _pdf()
WAV = _wav()
# zinc-900, the preview card's background
CARD_BACKGROUND = (24, 24, 27)


class TestServedType:
    @pytest.mark.parametrize(
        ("declared", "data", "expected"),
        [
            ("text/html", b"<h1>Report</h1><script>chart()</script>", RenderMode.FRAME_ACTIVE),
            ("image/png", PNG, RenderMode.IMAGE),
            ("application/pdf", PDF, RenderMode.PDF),
            ("image/svg+xml", b"<svg xmlns='http://www.w3.org/2000/svg'/>", RenderMode.IMAGE_SVG),
            ("text/markdown", b"# Notes", RenderMode.TEXT),
            ("application/json", b'{"a": 1}', RenderMode.TEXT),
            ("text/x-python", "print('héllo')".encode(), RenderMode.TEXT),
            # filetype names a WAV audio/x-wav; either spelling is the same bytes.
            ("audio/wav", WAV, RenderMode.MEDIA),
            ("audio/x-wav", WAV, RenderMode.MEDIA),
        ],
    )
    def test_bytes_that_agree_with_their_type_are_served_as_it(
        self, declared: str, data: bytes, expected: RenderMode
    ) -> None:
        assert served_type(declared, data) == ServedType(declared, expected)

    @pytest.mark.parametrize(
        ("declared", "data"),
        [
            # A PNG renamed .html must never run as a page.
            ("text/html", PNG),
            ("image/svg+xml", PDF),
            # A PDF renamed .png, and a text file renamed .pdf.
            ("image/png", PDF),
            ("application/pdf", b"not a pdf at all"),
            ("text/plain", b"\xff\xfe\x00 not utf-8"),
            ("application/x-msdownload", b"MZ\x90\x00"),
            ("application/octet-stream", b"anything"),
        ],
    )
    def test_anything_else_is_a_download(self, declared: str, data: bytes) -> None:
        assert served_type(declared, data) == ServedType(
            "application/octet-stream", RenderMode.DOWNLOAD
        )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[LocalVolumeBlobStore]:
    """Publish into a real local-volume store on disk."""
    volume = LocalVolumeBlobStore(tmp_path)
    with (
        patch("app.services.blob_store._is_mountpoint", return_value=True),
        patch.object(content, "link_content_store", return_value=volume),
    ):
        yield volume


@pytest.fixture
def no_takedowns() -> Iterator[AsyncMock]:
    with patch(
        "app.services.links.content.short_link_repository.count_takedowns",
        AsyncMock(return_value=0),
    ) as count:
        yield count


@pytest.fixture
def unlimited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(content, "_within_quota", AsyncMock(return_value=True))


def _source(
    filename: str, mime: str, data: bytes | None, size: int | None = None
) -> SnapshotSource:
    return SnapshotSource(
        filename=filename,
        declared_mime=mime,
        size_bytes=size if size is not None else len(data or b""),
        data=data,
    )


class TestPublish:
    async def test_stores_the_bytes_under_a_fresh_content_id(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        snapshot = await publish(OWNER, SESSION, _source("notes.md", "text/markdown", b"# Hi"))

        assert snapshot.content_id is not None
        assert len(snapshot.content_id) == 26
        assert set(snapshot.content_id) <= set("abcdefghijklmnopqrstuvwxyz234567")
        assert await content.read_snapshot(OWNER, snapshot.content_id) == b"# Hi"
        assert snapshot.render is RenderMode.TEXT
        assert snapshot.max_access is LinkAccess.PUBLIC
        assert snapshot.restricted_by is None

    async def test_two_publishes_of_one_file_are_two_origins(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        first = await publish(OWNER, SESSION, _source("a.md", "text/markdown", b"x"))
        second = await publish(OWNER, SESSION, _source("a.md", "text/markdown", b"x"))
        assert first.content_id != second.content_id

    @pytest.mark.parametrize(
        ("mime", "size"),
        [
            ("text/markdown", MAX_SNAPSHOT_BYTES + 1),
            ("text/html", MAX_HTML_SNAPSHOT_BYTES + 1),
            ("image/svg+xml", MAX_SVG_SNAPSHOT_BYTES + 1),
        ],
    )
    async def test_a_file_over_its_cap_is_described_not_stored(
        self,
        store: LocalVolumeBlobStore,
        no_takedowns: AsyncMock,
        unlimited: None,
        mime: str,
        size: int,
    ) -> None:
        data = b"a" * size
        snapshot = await publish(OWNER, SESSION, _source("big", mime, data))
        assert snapshot.content_id is None
        assert snapshot.rejected is PublishRejection.TOO_LARGE
        assert snapshot.size_bytes == size

    async def test_a_file_at_the_html_cap_is_stored(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        snapshot = await publish(
            OWNER, SESSION, _source("r.html", "text/html", b"a" * MAX_HTML_SNAPSHOT_BYTES)
        )
        assert snapshot.content_id is not None

    async def test_an_unread_oversized_file_is_described(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        source = _source("video.mov", "video/quicktime", None, size=MAX_SNAPSHOT_BYTES * 4)
        snapshot = await publish(OWNER, SESSION, source)
        assert snapshot.content_id is None
        assert snapshot.rejected is PublishRejection.TOO_LARGE
        assert snapshot.size_bytes == MAX_SNAPSHOT_BYTES * 4

    async def test_over_quota_is_described_not_stored(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        quota = AsyncMock(return_value=False)
        monkeypatch.setattr(content, "_within_quota", quota)
        snapshot = await publish(OWNER, SESSION, _source("a.md", "text/markdown", b"xyz"))
        quota.assert_awaited_once_with(OWNER, 3)
        assert snapshot.content_id is None
        assert snapshot.rejected is PublishRejection.QUOTA

    @pytest.mark.parametrize(
        "html",
        [
            b"<form><input type='password' name='p'></form>",
            b'<input name="card" autocomplete="cc-number">',
        ],
    )
    async def test_html_asking_for_secrets_opens_only_for_specific_people(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None, html: bytes
    ) -> None:
        snapshot = await publish(OWNER, SESSION, _source("login.html", "text/html", html))
        assert snapshot.content_id is not None
        assert snapshot.max_access is LinkAccess.PEOPLE
        assert snapshot.restricted_by is PublishRejection.RESTRICTED_TYPE

    @pytest.mark.parametrize(
        "filename", ["setup.exe", "App.DMG", "run.ps1", "tool.jar", "notes.v2.exe"]
    )
    async def test_installers_open_only_for_their_owner(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None, filename: str
    ) -> None:
        snapshot = await publish(
            OWNER, SESSION, _source(filename, "application/octet-stream", b"MZ\x90")
        )
        assert snapshot.max_access is LinkAccess.OWNER
        assert snapshot.render is RenderMode.DOWNLOAD

    async def test_an_owner_with_repeated_takedowns_shares_html_only_with_people(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        no_takedowns.return_value = 2
        snapshot = await publish(OWNER, SESSION, _source("r.html", "text/html", b"<p>hi</p>"))
        no_takedowns.assert_awaited_once_with(OWNER)
        assert snapshot.max_access is LinkAccess.PEOPLE

    async def test_one_takedown_does_not_narrow_html(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        no_takedowns.return_value = 1
        snapshot = await publish(OWNER, SESSION, _source("r.html", "text/html", b"<p>hi</p>"))
        assert snapshot.max_access is LinkAccess.PUBLIC

    async def test_html_naming_a_flagged_url_opens_only_for_people(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        html = b"<a href='http://testsafebrowsing.appspot.com/s/phishing.html'>x</a>"
        with patch.object(content, "flagged_urls", AsyncMock(return_value=True)) as flagged:
            snapshot = await publish(OWNER, SESSION, _source("r.html", "text/html", html))
        flagged.assert_awaited_once_with(["http://testsafebrowsing.appspot.com/s/phishing.html"])
        assert snapshot.max_access is LinkAccess.PEOPLE
        assert snapshot.restricted_by is PublishRejection.UNSAFE_URL

    async def test_a_png_gets_a_preview_card_under_the_size_cap(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        snapshot = await publish(OWNER, SESSION, _source("chart.png", "image/png", PNG))
        assert snapshot.has_thumbnail
        assert snapshot.content_id is not None
        thumb = await content.read_thumbnail(OWNER, snapshot.content_id)
        assert len(thumb) <= THUMBNAIL_MAX_BYTES
        with Image.open(io.BytesIO(thumb)) as image:
            assert image.format == "JPEG"
            assert image.size == (1200, 630)

    async def test_a_pdf_previews_its_first_page(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        snapshot = await publish(OWNER, SESSION, _source("deck.pdf", "application/pdf", PDF))
        assert snapshot.render is RenderMode.PDF
        assert snapshot.has_thumbnail

    async def test_html_is_never_rendered_for_a_preview(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        snapshot = await publish(OWNER, SESSION, _source("r.html", "text/html", b"<p>hi</p>"))
        assert not snapshot.has_thumbnail

    async def test_unchanged_bytes_are_recognised_by_digest(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        snapshot = await publish(OWNER, SESSION, _source("a.md", "text/markdown", b"one"))
        assert unchanged(snapshot, _source("a.md", "text/markdown", b"one"))
        assert not unchanged(snapshot, _source("a.md", "text/markdown", b"two"))
        assert not unchanged(snapshot, _source("a.md", "text/markdown", None, size=3))

    async def test_a_publish_stores_the_bytes_and_preview_and_records_it(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        with (
            patch.object(store, "put", wraps=store.put) as put,
            patch.object(content, "capture") as capture,
        ):
            snapshot = await publish(OWNER, SESSION, _source("chart.png", "image/png", PNG))

        assert snapshot.content_id is not None
        thumb = await content.read_thumbnail(OWNER, snapshot.content_id)
        assert put.await_args_list == [
            call(
                OWNER,
                f"link_{snapshot.content_id}",
                PNG,
                resource_type="raw",
                kind=BlobKind.LINK_SNAPSHOT,
                content_type="image/png",
            ),
            call(
                OWNER,
                f"link_{snapshot.content_id}_thumb",
                thumb,
                resource_type="image",
                kind=BlobKind.LINK_SNAPSHOT,
                content_type="image/jpeg",
            ),
        ]
        capture.assert_called_once_with(
            UserId(OWNER),
            ShortLinkContentPublished(
                target_type=SESSION.value, render_mode="image", size_bucket="lt_100kb"
            ),
        )

    async def test_a_narrowed_publish_records_why(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        with patch.object(content, "capture") as capture:
            await publish(OWNER, SESSION, _source("setup.exe", "application/octet-stream", b"MZ"))
        assert capture.call_args_list == [
            call(
                UserId(OWNER),
                ShortLinkContentPublished(
                    target_type=SESSION.value, render_mode="download", size_bucket="lt_100kb"
                ),
            ),
            call(
                UserId(OWNER),
                ShortLinkPublishRejected(target_type=SESSION.value, reason="restricted_type"),
            ),
        ]

    async def test_a_rejected_publish_records_why_and_stores_nothing(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        source = _source("video.mov", "video/quicktime", None, size=MAX_SNAPSHOT_BYTES * 4)
        with (
            patch.object(store, "put", wraps=store.put) as put,
            patch.object(content, "capture") as capture,
        ):
            snapshot = await publish(OWNER, SESSION, source)
        put.assert_not_awaited()
        capture.assert_called_once_with(
            UserId(OWNER),
            ShortLinkPublishRejected(target_type=SESSION.value, reason="too_large"),
        )
        assert snapshot == LinkSnapshot(
            filename="video.mov",
            mime="application/octet-stream",
            size_bytes=MAX_SNAPSHOT_BYTES * 4,
            render=RenderMode.DOWNLOAD,
            content_id=None,
            rejected=PublishRejection.TOO_LARGE,
            published_at=snapshot.published_at,
        )

    async def test_reads_name_the_snapshot_and_its_preview(
        self, store: LocalVolumeBlobStore, no_takedowns: AsyncMock, unlimited: None
    ) -> None:
        snapshot = await publish(OWNER, SESSION, _source("chart.png", "image/png", PNG))
        assert snapshot.content_id is not None
        with patch.object(store, "read", wraps=store.read) as read:
            assert await content.read_snapshot(OWNER, snapshot.content_id) == PNG
            await content.read_thumbnail(OWNER, snapshot.content_id)
        assert read.await_args_list == [
            call(OWNER, f"link_{snapshot.content_id}", ""),
            call(OWNER, f"link_{snapshot.content_id}_thumb", ""),
        ]

    @pytest.mark.usefixtures("store", "no_takedowns", "unlimited")
    @pytest.mark.parametrize(
        ("source", "render", "error_type"),
        [
            (_source("chart.png", "image/png", PNG[:40]), "image", "UnidentifiedImageError"),
            (
                _source("deck.pdf", "application/pdf", b"%PDF-1.7 truncated"),
                "pdf",
                "FileDataError",
            ),
        ],
    )
    async def test_a_broken_file_shares_without_a_preview(
        self, source: SnapshotSource, render: str, error_type: str
    ) -> None:
        async with captured_wide_event() as event:
            snapshot = await publish(OWNER, SESSION, source)
        assert snapshot.content_id is not None
        assert not snapshot.has_thumbnail
        assert event["warnings"] == [
            {"msg": "short_link.thumbnail_failed", "render": render, "error_type": error_type}
        ]


@pytest.mark.parametrize(
    ("filename", "extension"),
    [("setup.EXE", "exe"), ("archive.tar.gz", "gz"), ("Makefile", ""), ("exe", "")],
)
def test_the_extension_is_what_follows_the_last_dot(filename: str, extension: str) -> None:
    assert content._extension(filename) == extension


@pytest.mark.parametrize(
    ("size", "bucket"),
    [
        (0, "lt_100kb"),
        (100 * 1024 - 1, "lt_100kb"),
        (100 * 1024, "lt_1mb"),
        (1024 * 1024, "lt_10mb"),
        (10 * 1024 * 1024 - 1, "lt_10mb"),
        (10 * 1024 * 1024, "gte_10mb"),
    ],
)
def test_sizes_fall_in_their_analytics_bucket(size: int, bucket: str) -> None:
    assert content._size_bucket(size) == bucket


def _decoded(jpeg: bytes) -> Image.Image:
    with Image.open(io.BytesIO(jpeg)) as image:
        assert image.format == "JPEG"
        assert image.size == THUMBNAIL_SIZE
        return image.convert("RGB")


def _encoded(card: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    card.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def _noise() -> Image.Image:
    return Image.frombytes("RGB", THUMBNAIL_SIZE, random.Random(0).randbytes(1200 * 630 * 3))


def _near(pixel: object, colour: tuple[int, int, int]) -> bool:
    assert isinstance(pixel, tuple)
    return all(abs(a - b) <= 8 for a, b in zip(pixel, colour, strict=True))


class TestPreviewCard:
    def test_a_small_image_sits_centred_on_the_card_background(self) -> None:
        jpeg = content._jpeg(Image.new("RGB", (400, 200), (200, 10, 10)))
        assert jpeg is not None
        card = _decoded(jpeg)
        flat = Image.new("RGB", THUMBNAIL_SIZE, CARD_BACKGROUND)
        background = _decoded(_encoded(flat, 85)).getpixel((0, 0))
        assert card.getpixel((0, 0)) == background
        assert card.getpixel((1199, 629)) == background
        # the image spans x 400-800, y 215-415
        for inside in ((410, 225), (790, 405), (600, 315)):
            assert _near(card.getpixel(inside), (200, 10, 10))
        for outside in ((380, 315), (820, 315), (600, 195), (600, 435)):
            assert _near(card.getpixel(outside), CARD_BACKGROUND)

    def test_an_image_is_flattened_to_rgb_before_it_is_scaled(self) -> None:
        # Scaling RGBA premultiplies alpha, which would blacken fully transparent colour.
        jpeg = content._jpeg(Image.new("RGBA", (2400, 1260), (200, 10, 10, 0)))
        assert jpeg is not None
        assert _near(_decoded(jpeg).getpixel((600, 315)), (200, 10, 10))

    def test_the_card_steps_down_in_quality_until_it_fits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        noise = _noise()
        monkeypatch.setattr(content, "THUMBNAIL_MAX_BYTES", 10 * 1024 * 1024)
        sizes: list[int] = []
        for quality in (85, 70, 55):
            jpeg = content._jpeg(noise)
            assert jpeg == _encoded(noise, quality)
            sizes.append(len(jpeg))
            # A cap of exactly this size still admits it; one byte less forces the next step.
            monkeypatch.setattr(content, "THUMBNAIL_MAX_BYTES", len(jpeg))
            assert content._jpeg(noise) == jpeg
            monkeypatch.setattr(content, "THUMBNAIL_MAX_BYTES", len(jpeg) - 1)
        assert content._jpeg(noise) is None
        assert sizes == sorted(sizes, reverse=True)

    @pytest.mark.parametrize(
        ("page", "rendered"),
        [
            ((20000.0, 20000.0), (630, 630)),
            ((20000.0, 5000.0), (1200, 300)),
            ((300.0, 157.5), (1200, 630)),
        ],
    )
    def test_a_pdf_page_renders_at_the_card_size_whatever_its_own(
        self, page: tuple[float, float], rendered: tuple[int, int]
    ) -> None:
        with patch.object(content, "_jpeg", wraps=content._jpeg) as jpeg:
            thumbnail = content._thumbnail(RenderMode.PDF, _pdf_page(*page))
        assert thumbnail is not None
        assert len(thumbnail) <= THUMBNAIL_MAX_BYTES
        _decoded(thumbnail)
        assert jpeg.call_args.args[0].size == rendered

    def test_a_pdf_previews_its_first_page_only(self) -> None:
        with pymupdf.open() as document:
            document.new_page(width=600, height=315)
            document.new_page(width=315, height=600)
            data = document.tobytes()
        with patch.object(content, "_jpeg", wraps=content._jpeg) as jpeg:
            content._thumbnail(RenderMode.PDF, data)
        assert jpeg.call_args.args[0].size == (1200, 630)


_STORED_BYTES = "app.services.links.content.short_link_repository.stored_snapshot_bytes"


class TestQuota:
    @pytest.fixture(autouse=True)
    def enforced(self, monkeypatch: pytest.MonkeyPatch, fake_redis: object) -> None:
        monkeypatch.setattr(settings, "DEV_UNLIMITED_RATE_LIMITS", False)
        monkeypatch.setattr(settings, "ENV", "production")
        monkeypatch.setattr(_STORED_BYTES, AsyncMock(return_value=0))

    async def test_a_day_admits_up_to_its_published_bytes(self) -> None:
        assert await content._within_quota(OWNER, MAX_PUBLISHED_BYTES_PER_DAY)
        assert not await content._within_quota(OWNER, 1)

    async def test_stored_bytes_count_against_the_total(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stored = AsyncMock(return_value=MAX_STORED_SNAPSHOT_BYTES - 10)
        monkeypatch.setattr(_STORED_BYTES, stored)
        assert await content._within_quota(OWNER, 10)
        assert not await content._within_quota(OWNER, 11)
        stored.assert_awaited_with(OWNER)

    async def test_the_day_is_counted_under_its_own_key_until_it_lapses(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        # 20:00 UTC is already the next analytics day in IST.
        with time_machine.travel(datetime(2026, 11, 12, 20, 0, tzinfo=UTC), tick=False):
            assert await content._within_quota(OWNER, 5)
            assert await content._within_quota(OWNER, 7)
            key = f"link_content:published_bytes:{OWNER}:2026-11-13"
            assert await fake_redis.keys("*") == [key]
            assert await fake_redis.get(key) == "12"
            assert await fake_redis.ttl(key) == PUBLISHED_BYTES_TTL_SECONDS

    async def test_a_deployment_without_usage_limits_admits_anything(
        self, monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        monkeypatch.setattr(settings, "ENV", "selfhost")
        monkeypatch.setattr(_STORED_BYTES, AsyncMock(return_value=MAX_STORED_SNAPSHOT_BYTES))
        assert await content._within_quota(OWNER, MAX_PUBLISHED_BYTES_PER_DAY + 1)
        assert await fake_redis.keys("*") == []


CID = "abcdefghijklmnopqrstuvwxyz"
LINK = ShortLink(
    slug="abcdefghijk",
    user_id=OWNER,
    target_type=SESSION,
    target_id="conv-1/r.html",
    created_at=NOW - timedelta(days=1),
)


class TestContentTokens:
    def test_a_fresh_url_carries_a_token_for_its_own_origin(self, origin: None) -> None:
        url, expires_at = issue_content_url(LINK, CID, NOW)
        assert url.startswith(f"https://{CID}.u.heygaia.test?t=")
        assert expires_at == NOW + timedelta(seconds=CONTENT_TOKEN_TTL_SECONDS)
        token = url.split("?t=", 1)[1]
        assert token_valid(LINK, CID, token, NOW + timedelta(seconds=CONTENT_TOKEN_TTL_SECONDS - 1))

    def test_the_token_signs_the_snapshot_link_version_and_expiry(self, origin: None) -> None:
        link = LINK.model_copy(update={"updated_at": datetime(2026, 11, 12, 9, 30, 0, 123000, UTC)})
        url, _ = issue_content_url(link, CID, NOW)
        expires = int(NOW.timestamp()) + CONTENT_TOKEN_TTL_SECONDS
        message = f"link-content:{CID}:abcdefghijk:1794475800123:{expires}".encode()
        digest = hmac.new(b"k" * 32, message, hashlib.sha256).digest()
        signature = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        assert url == f"https://{CID}.u.heygaia.test?t={expires}.{signature}"

    def test_a_trailing_slash_on_the_origin_template_is_dropped(
        self, origin: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            settings, "LINK_CONTENT_URL_TEMPLATE", "https://{content_id}.U.HEYGAIA.BOX/"
        )
        assert content.thumbnail_url(CID) == f"https://{CID}.U.HEYGAIA.BOX/thumb.jpg"
        assert content.content_origin_host(CID) == f"{CID}.u.heygaia.box"

    def test_no_url_is_issued_without_an_origin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "LINK_CONTENT_URL_TEMPLATE", None)
        with pytest.raises(RuntimeError) as raised:
            content.thumbnail_url(CID)
        assert str(raised.value) == (
            "LINK_CONTENT_URL_TEMPLATE is unset; check active_link_content() first"
        )

    def test_no_token_is_signed_without_a_key(
        self, origin: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "LINK_CONTENT_SIGNING_KEY", None)
        with pytest.raises(RuntimeError) as raised:
            issue_content_url(LINK, CID, NOW)
        assert str(raised.value) == (
            "LINK_CONTENT_SIGNING_KEY is unset; check active_link_content() first"
        )

    def test_a_token_dies_at_its_expiry(self, origin: None) -> None:
        token = issue_content_url(LINK, CID, NOW)[0].split("?t=", 1)[1]
        assert not token_valid(LINK, CID, token, NOW + timedelta(seconds=CONTENT_TOKEN_TTL_SECONDS))

    def test_a_token_opens_no_other_snapshot(self, origin: None) -> None:
        token = issue_content_url(LINK, CID, NOW)[0].split("?t=", 1)[1]
        assert not token_valid(LINK, "b" * 26, token, NOW)

    @pytest.mark.parametrize("token", ["", "garbage", "9999999999.", "9999999999.forged"])
    def test_a_forged_token_opens_nothing(self, origin: None, token: str) -> None:
        assert not token_valid(LINK, CID, token, NOW)

    def test_extending_the_expiry_breaks_the_signature(self, origin: None) -> None:
        token = issue_content_url(LINK, CID, NOW)[0].split("?t=", 1)[1]
        expires, _, signature = token.partition(".")
        assert not token_valid(LINK, CID, f"{int(expires) + 3600}.{signature}", NOW)

    def test_changing_the_link_voids_its_tokens(self, origin: None) -> None:
        token = issue_content_url(LINK, CID, NOW)[0].split("?t=", 1)[1]
        narrowed = LINK.model_copy(update={"updated_at": NOW})
        rotated = LINK.model_copy(update={"slug": "zyxwvutsrqp"})
        assert not token_valid(narrowed, CID, token, NOW)
        assert not token_valid(rotated, CID, token, NOW)

    def test_a_rotated_key_kills_old_tokens(
        self, origin: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = issue_content_url(LINK, CID, NOW)[0].split("?t=", 1)[1]
        monkeypatch.setattr(settings, "LINK_CONTENT_SIGNING_KEY", "j" * 32)
        assert not token_valid(LINK, CID, token, NOW)


def _snapshot(render: RenderMode, **overrides: object) -> LinkSnapshot:
    data: dict[str, object] = {
        "filename": "f",
        "mime": "text/html",
        "size_bytes": 3,
        "render": render,
        "content_id": CID,
    }
    data.update(overrides)
    return LinkSnapshot.model_validate(data)


class TestPresentation:
    @pytest.mark.parametrize(
        ("render", "without_origin"),
        [
            (RenderMode.FRAME_ACTIVE, RenderMode.TEXT),
            (RenderMode.TEXT, RenderMode.TEXT),
            (RenderMode.IMAGE, RenderMode.DOWNLOAD),
            (RenderMode.IMAGE_SVG, RenderMode.DOWNLOAD),
            (RenderMode.PDF, RenderMode.DOWNLOAD),
            (RenderMode.MEDIA, RenderMode.DOWNLOAD),
            (RenderMode.DOWNLOAD, RenderMode.DOWNLOAD),
        ],
    )
    def test_without_a_content_origin_only_text_renders_in_place(
        self, monkeypatch: pytest.MonkeyPatch, render: RenderMode, without_origin: RenderMode
    ) -> None:
        monkeypatch.setattr(settings, "LINK_CONTENT_URL_TEMPLATE", None)
        assert presented_render(_snapshot(render)) is without_origin

    def test_an_origin_without_a_signing_key_is_no_origin(
        self, origin: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "LINK_CONTENT_SIGNING_KEY", None)
        assert presented_render(_snapshot(RenderMode.FRAME_ACTIVE)) is RenderMode.TEXT

    def test_with_a_content_origin_every_mode_renders_as_published(self, origin: None) -> None:
        assert all(presented_render(_snapshot(render)) is render for render in RenderMode)

    @pytest.mark.parametrize("render", [RenderMode.FRAME_ACTIVE, RenderMode.PDF, RenderMode.IMAGE])
    def test_framed_content_names_the_snapshot(self, origin: None, render: RenderMode) -> None:
        framed = framed_content(_snapshot(render), LinkAccess.UNLISTED)
        assert framed is not None
        assert framed.content_id == CID
        assert framed.render is render

    @pytest.mark.parametrize("render", [RenderMode.TEXT, RenderMode.DOWNLOAD])
    def test_text_and_downloads_are_never_framed(self, origin: None, render: RenderMode) -> None:
        assert framed_content(_snapshot(render), LinkAccess.UNLISTED) is None

    def test_nothing_is_framed_without_stored_bytes(self, origin: None) -> None:
        assert framed_content(None, LinkAccess.UNLISTED) is None
        unstored = _snapshot(RenderMode.FRAME_ACTIVE, content_id=None)
        assert framed_content(unstored, LinkAccess.UNLISTED) is None

    def test_a_link_wider_than_its_bytes_allow_frames_nothing(self, origin: None) -> None:
        restricted = _snapshot(RenderMode.FRAME_ACTIVE, max_access=LinkAccess.PEOPLE)
        assert framed_content(restricted, LinkAccess.UNLISTED) is None
        assert framed_content(restricted, LinkAccess.PEOPLE) is not None
