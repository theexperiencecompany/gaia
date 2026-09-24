"""Tests for app.services.browser.screenshots — R2 upload, config, boto3 client.

The publisher prefers the bucket and falls back to the local backend, so the
local fixtures below run the real shot_store against the test's own directory
rather than mocking the fallback away.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


class _FakeRedisCache:
    """Enough of redis_cache for the local backend's one-code-per-run mapping."""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    async def set(self, key: str, value: object, ttl: int = 3600, model: object = None) -> bool:
        self.values[key] = value
        return True

    async def get(self, key: str, model: object = None) -> object:
        return self.values.get(key)


@pytest.fixture
def r2(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every R2 setting present, so frames go to the bucket."""
    for name, value in _R2_SETTINGS.items():
        monkeypatch.setattr(shots.settings, name, value)
    monkeypatch.setattr(shots.settings, "R2_BUCKET", "b")


@pytest.fixture
def no_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    """No object store configured, so frames stay on this host."""
    monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", None)


def _frame_fields(event: dict[str, object]) -> dict[str, object]:
    """Return the publisher's own fields in the browser namespace; the disk store adds its own beside them."""
    browser = event["browser"]
    assert isinstance(browser, dict)
    return {k: v for k, v in browser.items() if k.startswith("screenshot_")}


def _fake_clock(monkeypatch: pytest.MonkeyPatch, *readings: float) -> None:
    ticks = iter(readings)
    monkeypatch.setattr(shots, "perf_counter", lambda: next(ticks))


@pytest.fixture
def local_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the disk backend at this test's directory and give it a code store."""
    root = tmp_path / "shots"
    monkeypatch.setattr(shot_store, "SHOT_ROOT", root)
    monkeypatch.setattr(shot_store, "redis_cache", _FakeRedisCache())
    monkeypatch.setattr(
        "app.services.browser.links.settings.BROWSER_LIVE_VIEW_BASE_URL", "https://browser.test"
    )
    return root


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
    def test_put_calls_put_object_with_correct_args(self, monkeypatch):
        monkeypatch.setattr(shots.settings, "R2_BUCKET", "my-bucket")
        fake_client = MagicMock()
        with patch.object(shots, "_r2_client", return_value=fake_client):
            shots._put(b"pngbytes", "browser_steps/c1/step_1.png")
            fake_client.put_object.assert_called_once_with(
                Bucket="my-bucket",
                Key="browser_steps/c1/step_1.png",
                Body=b"pngbytes",
                ContentType="image/png",
            )


# ---------------------------------------------------------------------------
# publish_step_screenshot — success / failure / not-configured
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPublishStepScreenshot:
    async def test_falls_back_to_disk_when_not_configured(self, monkeypatch, local_backend):
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", None)

        result = await shots.publish_step_screenshot(b"pngbytes", "conv1", 1)

        assert result is not None
        assert result.startswith("https://browser.test/shots/")
        assert result.endswith("/1.png")
        assert (local_backend / "conv1" / "step_1.png").read_bytes() == b"pngbytes"

    async def test_success_returns_public_url(self, monkeypatch):
        for name, value in _R2_SETTINGS.items():
            monkeypatch.setattr(shots.settings, name, value)
        mock_to_thread = AsyncMock(return_value=None)
        with patch.object(shots.asyncio, "to_thread", mock_to_thread):
            result = await shots.publish_step_screenshot(b"pngdata", "conv-abc", 3)
        assert result == "https://cdn.example.com/browser_steps/conv-abc/step_3.png"
        mock_to_thread.assert_awaited_once()
        args, _ = mock_to_thread.call_args
        # First arg is the callable (_put), then png and key
        assert args[0] is shots._put
        assert args[1] == b"pngdata"
        assert args[2] == "browser_steps/conv-abc/step_3.png"

    async def test_upload_failure_falls_back_to_disk_and_logs(self, monkeypatch, local_backend):
        for name, value in _R2_SETTINGS.items():
            monkeypatch.setattr(shots.settings, name, value)
        failing = MagicMock()
        failing.put_object.side_effect = RuntimeError("boom")
        with (
            patch.object(shots, "_r2_client", return_value=failing),
            patch.object(shots.log, "warning") as mock_warn,
        ):
            result = await shots.publish_step_screenshot(b"pngbytes", "c1", 1)

        assert result is not None
        assert result.startswith("https://browser.test/shots/")
        assert (local_backend / "c1" / "step_1.png").read_bytes() == b"pngbytes"
        mock_warn.assert_called_once()
        # Exact message (not a loose substring check — a mutated literal that
        # merely gets padded would still contain any substring we look for).
        call_args = mock_warn.call_args
        assert (
            call_args[0][0]
            == f"{shots.LogTag.BROWSER} Browser screenshot upload failed; storing it locally instead"
        )
        assert call_args[1].get("error_type") == "RuntimeError"

    async def test_a_failed_local_write_returns_none_so_the_caller_can_inline(
        self, monkeypatch, tmp_path
    ):
        # The caller degrades to a data URL on None; failing the run instead
        # would lose the whole task over a progress thumbnail.
        blocker = tmp_path / "blocked"
        blocker.write_bytes(b"not a directory")
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", None)
        monkeypatch.setattr(shot_store, "SHOT_ROOT", blocker)
        monkeypatch.setattr(shot_store, "redis_cache", _FakeRedisCache())

        with patch.object(shots.log, "warning") as mock_warn:
            result = await shots.publish_step_screenshot(b"x", "c1", 1)

        assert result is None
        mock_warn.assert_called_once()
        assert (
            mock_warn.call_args[0][0]
            == f"{shots.LogTag.BROWSER} Browser screenshot could not be stored; using inline fallback"
        )
        assert mock_warn.call_args[1]["error_type"] == "NotADirectoryError"

    async def test_a_non_storage_failure_is_not_swallowed(self, monkeypatch, local_backend):
        # Only a failed write degrades to the inline fallback; anything else is a
        # real fault and must reach the caller rather than look like a full disk.
        class _BrokenCache(_FakeRedisCache):
            async def get(self, key: str, model: object = None) -> object:
                raise RuntimeError("redis is down")

        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", None)
        monkeypatch.setattr(shot_store, "redis_cache", _BrokenCache())

        with pytest.raises(RuntimeError):
            await shots.publish_step_screenshot(b"x", "c1", 1)

    async def test_prefers_the_bucket_over_disk_when_configured(self, monkeypatch, local_backend):
        for name, value in _R2_SETTINGS.items():
            monkeypatch.setattr(shots.settings, name, value)
        client = MagicMock()
        with patch.object(shots, "_r2_client", return_value=client):
            result = await shots.publish_step_screenshot(b"pngbytes", "c1", 1)

        assert result == "https://cdn.example.com/browser_steps/c1/step_1.png"
        client.put_object.assert_called_once()
        # Nothing should have been written locally when the bucket accepted it.
        assert not (local_backend / "c1").exists()

    async def test_not_configured_never_reaches_the_bucket(self, monkeypatch, local_backend):
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", None)
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
                await shots.publish_step_screenshot(b"pngbytes", "c1", 4)

        assert _frame_fields(event) == {
            "screenshot_step_index": 4,
            "screenshot_backend": "r2",
            "screenshot_bytes": 8,
            "screenshot_upload_ms": 750,
            "screenshot_published": True,
        }

    async def test_a_frame_kept_on_disk_records_the_local_backend(
        self, no_r2, monkeypatch, local_backend
    ):
        _fake_clock(monkeypatch, 1.0, 1.25)
        async with captured_wide_event() as event:
            await shots.publish_step_screenshot(b"abc", "c1", 2)

        assert _frame_fields(event) == {
            "screenshot_step_index": 2,
            "screenshot_backend": "local",
            "screenshot_bytes": 3,
            "screenshot_upload_ms": 250,
            "screenshot_published": True,
        }

    async def test_a_failed_upload_records_the_fallback_and_the_frame_size(
        self, r2, monkeypatch, local_backend
    ):
        _fake_clock(monkeypatch, 5.0, 5.5)
        failing = MagicMock()
        failing.put_object.side_effect = RuntimeError("boom")
        with patch.object(shots, "_r2_client", return_value=failing):
            async with captured_wide_event() as event:
                await shots.publish_step_screenshot(b"pngbytes", "c1", 6)

        assert _frame_fields(event) == {
            "screenshot_step_index": 6,
            "screenshot_backend": "local_fallback",
            "screenshot_bytes": 8,
            "screenshot_upload_ms": 500,
            "screenshot_published": True,
        }
        (warning,) = event["warnings"]
        assert warning["size_bytes"] == 8

    async def test_a_frame_no_backend_could_keep_is_recorded_as_unpublished(
        self, no_r2, monkeypatch, tmp_path
    ):
        blocker = tmp_path / "blocked"
        blocker.write_bytes(b"not a directory")
        monkeypatch.setattr(shot_store, "SHOT_ROOT", blocker)
        monkeypatch.setattr(shot_store, "redis_cache", _FakeRedisCache())

        async with captured_wide_event() as event:
            await shots.publish_step_screenshot(b"abcd", "c1", 1)

        assert event["browser"]["screenshot_published"] is False
        (warning,) = event["warnings"]
        assert warning["size_bytes"] == 4

    async def test_a_bucket_that_is_down_and_a_disk_that_is_full_is_unpublished(
        self, r2, monkeypatch, tmp_path
    ):
        blocker = tmp_path / "blocked"
        blocker.write_bytes(b"not a directory")
        monkeypatch.setattr(shot_store, "SHOT_ROOT", blocker)
        monkeypatch.setattr(shot_store, "redis_cache", _FakeRedisCache())
        failing = MagicMock()
        failing.put_object.side_effect = RuntimeError("boom")
        with patch.object(shots, "_r2_client", return_value=failing):
            async with captured_wide_event() as event:
                result = await shots.publish_step_screenshot(b"x", "c1", 1)

        assert result is None
        assert event["browser"]["screenshot_backend"] == "local_fallback"
        assert event["browser"]["screenshot_published"] is False
