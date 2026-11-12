"""Publishing a shared file: what its bytes are served as, what narrows who may see them, and the tokens that load them."""

from datetime import UTC, datetime, timedelta
import io
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image
import pymupdf
import pytest

from app.config.settings import settings
from app.constants.short_links import (
    CONTENT_TOKEN_TTL_SECONDS,
    MAX_HTML_SNAPSHOT_BYTES,
    MAX_PUBLISHED_BYTES_PER_DAY,
    MAX_SNAPSHOT_BYTES,
    MAX_SVG_SNAPSHOT_BYTES,
    THUMBNAIL_MAX_BYTES,
)
from app.models.short_link_models import (
    LinkAccess,
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


PNG = _png()
PDF = _pdf()


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
def store(tmp_path: Path):
    """Publish into a real local-volume store on disk."""
    volume = LocalVolumeBlobStore(tmp_path)
    with (
        patch("app.services.blob_store._is_mountpoint", return_value=True),
        patch.object(content, "link_content_store", return_value=volume),
    ):
        yield volume


@pytest.fixture
def no_takedowns():
    with patch.object(
        content.short_link_repository, "count_takedowns", AsyncMock(return_value=0)
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
        monkeypatch.setattr(content, "_within_quota", AsyncMock(return_value=False))
        snapshot = await publish(OWNER, SESSION, _source("a.md", "text/markdown", b"x"))
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

    @pytest.mark.parametrize("filename", ["setup.exe", "App.DMG", "run.ps1", "tool.jar"])
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


class TestQuota:
    @pytest.fixture(autouse=True)
    def enforced(self, monkeypatch: pytest.MonkeyPatch, fake_redis: object) -> None:
        monkeypatch.setattr(settings, "DEV_UNLIMITED_RATE_LIMITS", False)
        monkeypatch.setattr(settings, "ENV", "production")
        monkeypatch.setattr(
            content.short_link_repository, "stored_snapshot_bytes", AsyncMock(return_value=0)
        )

    async def test_a_day_admits_up_to_its_published_bytes(self) -> None:
        assert await content._within_quota(OWNER, MAX_PUBLISHED_BYTES_PER_DAY)
        assert not await content._within_quota(OWNER, 1)

    async def test_stored_bytes_count_against_the_total(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            content.short_link_repository,
            "stored_snapshot_bytes",
            AsyncMock(return_value=2 * 1024 * 1024 * 1024),
        )
        assert not await content._within_quota(OWNER, 1)


@pytest.fixture
def origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings, "LINK_CONTENT_URL_TEMPLATE", "https://{content_id}.u.heygaia.test"
    )
    monkeypatch.setattr(settings, "LINK_CONTENT_SIGNING_KEY", "k" * 32)


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


def _snapshot(render: RenderMode, **overrides: object) -> content.LinkSnapshot:
    data: dict[str, object] = {
        "filename": "f",
        "mime": "text/html",
        "size_bytes": 3,
        "render": render,
        "content_id": CID,
    }
    data.update(overrides)
    return content.LinkSnapshot.model_validate(data)


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

    def test_a_link_wider_than_its_bytes_allow_frames_nothing(self, origin: None) -> None:
        restricted = _snapshot(RenderMode.FRAME_ACTIVE, max_access=LinkAccess.PEOPLE)
        assert framed_content(restricted, LinkAccess.UNLISTED) is None
        assert framed_content(restricted, LinkAccess.PEOPLE) is not None
