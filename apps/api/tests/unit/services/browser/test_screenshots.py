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
# _r2_configured
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestR2Configured:
    def test_all_set_is_configured(self, monkeypatch):
        monkeypatch.setattr(shots.settings, "CLOUDFLARE_ACCOUNT_ID", "acct")
        monkeypatch.setattr(shots.settings, "R2_ACCESS_KEY_ID", "key")
        monkeypatch.setattr(shots.settings, "R2_SECRET_ACCESS_KEY", "secret")
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
        assert shots._r2_configured() is True

    @pytest.mark.parametrize(
        "field",
        ["CLOUDFLARE_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_PUBLIC_BASE_URL"],
    )
    def test_any_missing_is_not_configured(self, monkeypatch, field):
        vals = {
            "CLOUDFLARE_ACCOUNT_ID": "acct",
            "R2_ACCESS_KEY_ID": "key",
            "R2_SECRET_ACCESS_KEY": "secret",
            "R2_PUBLIC_BASE_URL": "https://cdn.example.com",
        }
        for k, v in vals.items():
            monkeypatch.setattr(shots.settings, k, v)
        monkeypatch.setattr(shots.settings, field, None)
        assert shots._r2_configured() is False

    @pytest.mark.parametrize(
        "field",
        ["CLOUDFLARE_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_PUBLIC_BASE_URL"],
    )
    def test_any_empty_string_is_not_configured(self, monkeypatch, field):
        vals = {
            "CLOUDFLARE_ACCOUNT_ID": "acct",
            "R2_ACCESS_KEY_ID": "key",
            "R2_SECRET_ACCESS_KEY": "secret",
            "R2_PUBLIC_BASE_URL": "https://cdn.example.com",
        }
        for k, v in vals.items():
            monkeypatch.setattr(shots.settings, k, v)
        monkeypatch.setattr(shots.settings, field, "")
        assert shots._r2_configured() is False

    def test_all_missing(self, monkeypatch):
        monkeypatch.setattr(shots.settings, "CLOUDFLARE_ACCOUNT_ID", None)
        monkeypatch.setattr(shots.settings, "R2_ACCESS_KEY_ID", None)
        monkeypatch.setattr(shots.settings, "R2_SECRET_ACCESS_KEY", None)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", None)
        assert shots._r2_configured() is False


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

    def test_lru_cache_returns_same_object(self, monkeypatch):
        monkeypatch.setattr(shots.settings, "CLOUDFLARE_ACCOUNT_ID", "acct")
        monkeypatch.setattr(shots.settings, "R2_ACCESS_KEY_ID", "k")
        monkeypatch.setattr(shots.settings, "R2_SECRET_ACCESS_KEY", "s")
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
        # boto3.client returns a *different* mock on each call, so this only
        # proves caching (rather than trivially passing because the mock's
        # return_value happened to be identical either way).
        first_client = MagicMock()
        second_client = MagicMock()
        with patch.object(
            shots.boto3, "client", side_effect=[first_client, second_client]
        ) as mock_boto:
            a = shots._r2_client()
            b = shots._r2_client()
            assert a is first_client
            assert b is first_client
            mock_boto.assert_called_once()

    def test_lru_cache_maxsize_is_one(self):
        # The decorator argument itself, independent of any call behaviour.
        assert shots._r2_client.cache_info().maxsize == 1


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
        monkeypatch.setattr(shots, "_r2_configured", lambda: False)

        result = await shots.publish_step_screenshot(b"pngbytes", "conv1", 1)

        assert result is not None
        assert result.startswith("https://browser.test/shots/")
        assert result.endswith("/1.png")
        assert (local_backend / "conv1" / "step_1.png").read_bytes() == b"pngbytes"

    async def test_success_returns_public_url(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
        monkeypatch.setattr(shots.settings, "R2_BUCKET", "b")
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

    async def test_strips_trailing_slash_from_base_url(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com///")
        with patch.object(shots.asyncio, "to_thread", AsyncMock(return_value=None)):
            result = await shots.publish_step_screenshot(b"x", "c1", 0)
        assert result == "https://cdn.example.com/browser_steps/c1/step_0.png"

    async def test_strips_single_trailing_slash(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com/")
        with patch.object(shots.asyncio, "to_thread", AsyncMock(return_value=None)):
            result = await shots.publish_step_screenshot(b"x", "c1", 1)
        assert result == "https://cdn.example.com/browser_steps/c1/step_1.png"

    async def test_rstrip_only_strips_slash_not_other_trailing_chars(self, monkeypatch):
        # Pins the exact character set passed to rstrip(): it must strip "/"
        # only. A base URL ending in a non-slash character right before the
        # slash(es) must keep that character intact.
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.comX/")
        with patch.object(shots.asyncio, "to_thread", AsyncMock(return_value=None)):
            result = await shots.publish_step_screenshot(b"x", "c1", 1)
        assert result == "https://cdn.example.comX/browser_steps/c1/step_1.png"

    async def test_falsy_public_base_url_yields_empty_base_not_a_placeholder(self, monkeypatch):
        # Pins `settings.R2_PUBLIC_BASE_URL or ""` to the empty string, not some
        # other default. `_r2_configured` is mocked independently so this exercises
        # the line's own fallback, not `_r2_configured` preventing it in practice.
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", None)
        with patch.object(shots.asyncio, "to_thread", AsyncMock(return_value=None)):
            result = await shots.publish_step_screenshot(b"x", "c1", 1)
        assert result == "/browser_steps/c1/step_1.png"

    async def test_no_trailing_slash_unchanged(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
        with patch.object(shots.asyncio, "to_thread", AsyncMock(return_value=None)):
            result = await shots.publish_step_screenshot(b"x", "c1", 1)
        assert result == "https://cdn.example.com/browser_steps/c1/step_1.png"

    async def test_key_uses_conversation_id_and_index(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
        mock_to_thread = AsyncMock(return_value=None)
        with patch.object(shots.asyncio, "to_thread", mock_to_thread):
            await shots.publish_step_screenshot(b"x", "my-conv", 42)
        assert mock_to_thread.call_args[0][2] == "browser_steps/my-conv/step_42.png"

    async def test_upload_failure_falls_back_to_disk_and_logs(self, monkeypatch, local_backend):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
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

    async def test_upload_generic_exception_still_yields_a_url(self, monkeypatch, local_backend):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
        failing = MagicMock()
        failing.put_object.side_effect = ValueError("bad")
        with (
            patch.object(shots, "_r2_client", return_value=failing),
            patch.object(shots.log, "warning") as mock_warn,
        ):
            result = await shots.publish_step_screenshot(b"x", "c1", 1)

        assert result is not None
        assert not result.startswith("https://cdn.example.com")
        assert mock_warn.call_args[1]["error_type"] == "ValueError"

    async def test_upload_exception_logs_correct_error_type(self, monkeypatch, local_backend):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")

        class CustomError(Exception):
            pass

        failing = MagicMock()
        failing.put_object.side_effect = CustomError("oops")
        with (
            patch.object(shots, "_r2_client", return_value=failing),
            patch.object(shots.log, "warning") as mock_warn,
        ):
            await shots.publish_step_screenshot(b"x", "c1", 1)
        assert mock_warn.call_args[1]["error_type"] == "CustomError"

    async def test_a_failed_local_write_returns_none_so_the_caller_can_inline(
        self, monkeypatch, tmp_path
    ):
        # The caller degrades to a data URL on None; failing the run instead
        # would lose the whole task over a progress thumbnail.
        blocker = tmp_path / "blocked"
        blocker.write_bytes(b"not a directory")
        monkeypatch.setattr(shots, "_r2_configured", lambda: False)
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

        monkeypatch.setattr(shots, "_r2_configured", lambda: False)
        monkeypatch.setattr(shot_store, "redis_cache", _BrokenCache())

        with pytest.raises(RuntimeError):
            await shots.publish_step_screenshot(b"x", "c1", 1)

    async def test_prefers_the_bucket_over_disk_when_configured(self, monkeypatch, local_backend):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
        monkeypatch.setattr(shots.settings, "R2_BUCKET", "b")
        client = MagicMock()
        with patch.object(shots, "_r2_client", return_value=client):
            result = await shots.publish_step_screenshot(b"pngbytes", "c1", 1)

        assert result == "https://cdn.example.com/browser_steps/c1/step_1.png"
        client.put_object.assert_called_once()
        # Nothing should have been written locally when the bucket accepted it.
        assert not (local_backend / "c1").exists()

    async def test_calls_to_thread_with_put(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
        mock_to_thread = AsyncMock(return_value=None)
        with patch.object(shots.asyncio, "to_thread", mock_to_thread):
            await shots.publish_step_screenshot(b"abc", "conv", 5)
        mock_to_thread.assert_awaited_once_with(shots._put, b"abc", "browser_steps/conv/step_5.png")

    async def test_not_configured_never_reaches_the_bucket(self, monkeypatch, local_backend):
        monkeypatch.setattr(shots, "_r2_configured", lambda: False)
        client = MagicMock()
        with patch.object(shots, "_r2_client", return_value=client):
            await shots.publish_step_screenshot(b"x", "c1", 1)
        client.put_object.assert_not_called()
