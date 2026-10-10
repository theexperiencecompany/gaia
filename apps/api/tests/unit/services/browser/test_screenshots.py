"""Tests for app.services.browser.screenshots — R2 upload, config, boto3 client.

The publisher prefers the bucket and falls back to Redis, so the fallback
fixtures below run the real shot_store against a per-test fakeredis rather
than mocking the fallback away.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
from PIL import Image
import pytest

from app.constants.browser import BROWSER_STEP_PHOTO_QUALITY
from app.services.browser import screenshots as shots, shot_store
from tests.helpers import captured_wide_event

_R2_SETTINGS = {
    "CLOUDFLARE_ACCOUNT_ID": "acct",
    "R2_ACCESS_KEY_ID": "key",
    "R2_SECRET_ACCESS_KEY": "secret",
    "R2_PUBLIC_BASE_URL": "https://cdn.example.com",
}


@pytest.fixture(autouse=True)
def _clear_r2_client_cache():
    # _r2_client is @lru_cache(maxsize=1); isolation between tests matters.
    shots._r2_client.cache_clear()
    yield
    shots._r2_client.cache_clear()


@pytest.fixture
def r2(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every R2 setting present, so frames go to the bucket."""
    for name, value in _R2_SETTINGS.items():
        monkeypatch.setattr(shots.settings, name, value)
    monkeypatch.setattr(shots.settings, "R2_BUCKET", "b")


@pytest.fixture
def no_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    """No object store configured, so frames go to Redis."""
    monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", None)


def _frame_fields(event: dict[str, object]) -> dict[str, object]:
    """Return the publisher's own fields in the browser namespace; the Redis store adds its own beside them."""
    browser = event["browser"]
    assert isinstance(browser, dict)
    return {k: v for k, v in browser.items() if k.startswith("screenshot_")}


def _fake_clock(monkeypatch: pytest.MonkeyPatch, *readings: float) -> None:
    ticks = iter(readings)
    monkeypatch.setattr(shots, "perf_counter", lambda: next(ticks))


@pytest.fixture
def redis_backend(
    monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> fakeredis.aioredis.FakeRedis:
    """Give the Redis backend a per-test store and a link base."""
    monkeypatch.setattr(
        "app.services.browser.links.settings.BROWSER_LIVE_VIEW_BASE_URL", "https://browser.test"
    )
    return fake_redis


@pytest.fixture
def no_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis down: the cache takes no write."""
    monkeypatch.setattr(shot_store.redis_cache, "redis", None)


async def _read_back(url: str, index: int) -> bytes | None:
    code = url.split("/shots/")[1].split("/")[0]
    return await shot_store.read_step_screenshot(code, index)


# ---------------------------------------------------------------------------
# _r2_public_base
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestR2PublicBase:
    def test_all_set_gives_the_public_base(self, r2):
        assert shots._r2_public_base() == "https://cdn.example.com"

    @pytest.mark.parametrize("field", list(_R2_SETTINGS))
    def test_any_missing_means_no_bucket(self, r2, monkeypatch, field):
        monkeypatch.setattr(shots.settings, field, None)
        assert shots._r2_public_base() is None

    def test_a_trailing_slash_on_the_base_never_doubles_in_a_frame_url(self, r2, monkeypatch):
        # A path-prefixed public base; only the slash after it goes, never the path's own tail.
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com/GAIA-X/")
        assert shots._r2_public_base() == "https://cdn.example.com/GAIA-X"


# ---------------------------------------------------------------------------
# _r2_client
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestR2Client:
    def test_creates_boto3_client_with_correct_args(self, monkeypatch):
        monkeypatch.setattr(shots.settings, "CLOUDFLARE_ACCOUNT_ID", "acct123")
        monkeypatch.setattr(shots.settings, "R2_ACCESS_KEY_ID", "akid")
        monkeypatch.setattr(shots.settings, "R2_SECRET_ACCESS_KEY", "s3cr3t")
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")

        mock_client = MagicMock()
        with patch.object(shots.boto3, "client", return_value=mock_client) as mock_boto:
            result = shots._r2_client()
            assert result is mock_client
            mock_boto.assert_called_once()
            # The service name is passed positionally — must be exactly "s3".
            assert mock_boto.call_args[0] == ("s3",)
            kwargs = mock_boto.call_args[1]
            assert kwargs["endpoint_url"] == "https://acct123.r2.cloudflarestorage.com"
            assert kwargs["aws_access_key_id"] == "akid"
            assert kwargs["aws_secret_access_key"] == "s3cr3t"
            assert kwargs["region_name"] == "auto"
            # Verify boto Config values are wired through
            cfg = kwargs["config"]
            assert cfg.signature_version == "s3v4"
            assert cfg.connect_timeout == shots._UPLOAD_TIMEOUT_SECONDS
            assert cfg.read_timeout == shots._UPLOAD_TIMEOUT_SECONDS
            assert cfg.retries == {"max_attempts": 1}


# ---------------------------------------------------------------------------
# _put
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPut:
    def test_put_stores_the_frame_as_a_jpeg(self, monkeypatch):
        monkeypatch.setattr(shots.settings, "R2_BUCKET", "my-bucket")
        fake_client = MagicMock()
        with patch.object(shots, "_r2_client", return_value=fake_client):
            shots._put(b"jpegbytes", "browser_steps/c1/step_1.jpg")
            fake_client.put_object.assert_called_once_with(
                Bucket="my-bucket",
                Key="browser_steps/c1/step_1.jpg",
                Body=b"jpegbytes",
                ContentType="image/jpeg",
            )


# ---------------------------------------------------------------------------
# publish_step_screenshot — success / failure / not-configured
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPublishStepScreenshot:
    async def test_falls_back_to_redis_when_not_configured(self, no_r2, redis_backend):
        result = await shots.publish_step_screenshot(b"jpegbytes", "conv1", 1)

        assert result is not None
        assert result.startswith("https://browser.test/shots/")
        assert result.endswith("/1.jpg")
        assert await _read_back(result, 1) == b"jpegbytes"

    async def test_success_returns_public_url(self, monkeypatch):
        for name, value in _R2_SETTINGS.items():
            monkeypatch.setattr(shots.settings, name, value)
        mock_to_thread = AsyncMock(return_value=None)
        with patch.object(shots.asyncio, "to_thread", mock_to_thread):
            result = await shots.publish_step_screenshot(b"jpegdata", "conv-abc", 3)
        assert result == "https://cdn.example.com/browser_steps/conv-abc/step_3.jpg"
        mock_to_thread.assert_awaited_once()
        args, _ = mock_to_thread.call_args
        assert args == (shots._put, b"jpegdata", "browser_steps/conv-abc/step_3.jpg")

    async def test_upload_failure_falls_back_to_redis_and_logs(self, r2, redis_backend):
        failing = MagicMock()
        failing.put_object.side_effect = RuntimeError("boom")
        with (
            patch.object(shots, "_r2_client", return_value=failing),
            patch.object(shots.log, "warning") as mock_warn,
        ):
            result = await shots.publish_step_screenshot(b"jpegbytes", "c1", 1)

        assert result is not None
        assert await _read_back(result, 1) == b"jpegbytes"
        mock_warn.assert_called_once()
        assert "upload failed" in mock_warn.call_args[0][0]
        assert mock_warn.call_args[1].get("error_type") == "RuntimeError"

    async def test_a_photo_taken_as_a_png_is_served_as_a_jpeg_of_the_same_page(
        self, no_r2, redis_backend
    ):
        # With an alpha channel, as a page photo can carry one; a JPEG cannot.
        png = BytesIO()
        Image.new("RGBA", (8, 4), (200, 30, 30, 255)).save(png, format="PNG")
        expected = BytesIO()
        Image.new("RGB", (8, 4), (200, 30, 30)).save(
            expected, format="JPEG", quality=BROWSER_STEP_PHOTO_QUALITY
        )

        url = await shots.publish_step_screenshot(png.getvalue(), "c1", 1)

        assert url is not None
        # The same JPEG, at the same quality, as every other step photo.
        assert await _read_back(url, 1) == expected.getvalue()

    async def test_a_frame_redis_did_not_take_returns_none_and_no_photo(self, no_r2, no_redis):
        assert await shots.publish_step_screenshot(b"x", "c1", 1) is None

    async def test_prefers_the_bucket_over_redis_when_configured(self, r2, redis_backend):
        client = MagicMock()
        with patch.object(shots, "_r2_client", return_value=client):
            result = await shots.publish_step_screenshot(b"jpegbytes", "c1", 1)

        assert result == "https://cdn.example.com/browser_steps/c1/step_1.jpg"
        client.put_object.assert_called_once()
        assert await redis_backend.keys() == []

    async def test_not_configured_never_reaches_the_bucket(self, no_r2, redis_backend):
        client = MagicMock()
        with patch.object(shots, "_r2_client", return_value=client):
            await shots.publish_step_screenshot(b"x", "c1", 1)
        client.put_object.assert_not_called()


# ---------------------------------------------------------------------------
# What each publish leaves on the wide event
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPublishedFrameOnTheWideEvent:
    async def test_a_bucket_upload_records_its_backend_size_and_time(self, r2, monkeypatch):
        _fake_clock(monkeypatch, 10.0, 10.75)
        with patch.object(shots, "_r2_client", return_value=MagicMock()):
            async with captured_wide_event() as event:
                await shots.publish_step_screenshot(b"jpegbyte", "c1", 4)

        assert _frame_fields(event) == {
            "screenshot_step_index": 4,
            "screenshot_backend": "r2",
            "screenshot_bytes": 8,
            "screenshot_upload_ms": 750,
            "screenshot_published": True,
        }

    async def test_a_frame_kept_in_redis_records_the_redis_backend(
        self, no_r2, monkeypatch, redis_backend
    ):
        _fake_clock(monkeypatch, 1.0, 1.25)
        async with captured_wide_event() as event:
            await shots.publish_step_screenshot(b"abc", "c1", 2)

        assert _frame_fields(event) == {
            "screenshot_step_index": 2,
            "screenshot_backend": "redis",
            "screenshot_bytes": 3,
            "screenshot_upload_ms": 250,
            "screenshot_published": True,
        }

    async def test_a_failed_upload_records_the_fallback_and_the_frame_size(
        self, r2, monkeypatch, redis_backend
    ):
        _fake_clock(monkeypatch, 5.0, 5.5)
        failing = MagicMock()
        failing.put_object.side_effect = RuntimeError("boom")
        with patch.object(shots, "_r2_client", return_value=failing):
            async with captured_wide_event() as event:
                await shots.publish_step_screenshot(b"jpegbyte", "c1", 6)

        assert _frame_fields(event) == {
            "screenshot_step_index": 6,
            "screenshot_backend": "redis_fallback",
            "screenshot_bytes": 8,
            "screenshot_upload_ms": 500,
            "screenshot_published": True,
        }
        (warning,) = event["warnings"]
        assert warning["size_bytes"] == 8

    async def test_a_bucket_that_is_down_and_redis_that_is_down_is_unpublished(self, r2, no_redis):
        failing = MagicMock()
        failing.put_object.side_effect = RuntimeError("boom")
        with patch.object(shots, "_r2_client", return_value=failing):
            async with captured_wide_event() as event:
                result = await shots.publish_step_screenshot(b"x", "c1", 1)

        assert result is None
        assert event["browser"]["screenshot_backend"] == "redis_fallback"
        assert event["browser"]["screenshot_published"] is False
