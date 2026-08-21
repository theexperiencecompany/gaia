"""Tests for app.services.browser.screenshots — R2 upload, config, boto3 client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.browser import screenshots as shots


@pytest.fixture(autouse=True)
def _clear_r2_client_cache():
    # _r2_client is @lru_cache(maxsize=1); isolation between tests matters.
    shots._r2_client.cache_clear()
    yield
    shots._r2_client.cache_clear()


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
# upload_step_screenshot — success / failure / not-configured
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadStepScreenshot:
    async def test_returns_none_when_not_configured(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: False)
        result = await shots.upload_step_screenshot(b"png", "conv1", 1)
        assert result is None

    async def test_success_returns_public_url(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
        monkeypatch.setattr(shots.settings, "R2_BUCKET", "b")
        mock_to_thread = AsyncMock(return_value=None)
        with patch.object(shots.asyncio, "to_thread", mock_to_thread):
            result = await shots.upload_step_screenshot(b"pngdata", "conv-abc", 3)
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
            result = await shots.upload_step_screenshot(b"x", "c1", 0)
        assert result == "https://cdn.example.com/browser_steps/c1/step_0.png"

    async def test_strips_single_trailing_slash(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com/")
        with patch.object(shots.asyncio, "to_thread", AsyncMock(return_value=None)):
            result = await shots.upload_step_screenshot(b"x", "c1", 1)
        assert result == "https://cdn.example.com/browser_steps/c1/step_1.png"

    async def test_rstrip_only_strips_slash_not_other_trailing_chars(self, monkeypatch):
        # Pins the exact character set passed to rstrip(): it must strip "/"
        # only. A base URL ending in a non-slash character right before the
        # slash(es) must keep that character intact.
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.comX/")
        with patch.object(shots.asyncio, "to_thread", AsyncMock(return_value=None)):
            result = await shots.upload_step_screenshot(b"x", "c1", 1)
        assert result == "https://cdn.example.comX/browser_steps/c1/step_1.png"

    async def test_falsy_public_base_url_yields_empty_base_not_a_placeholder(self, monkeypatch):
        # Pins the exact fallback value in `settings.R2_PUBLIC_BASE_URL or ""`:
        # it must be the empty string, not some other default. _r2_configured is
        # mocked independently here so this exercises the line's own fallback
        # rather than relying on _r2_configured to ever prevent it in practice.
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", None)
        with patch.object(shots.asyncio, "to_thread", AsyncMock(return_value=None)):
            result = await shots.upload_step_screenshot(b"x", "c1", 1)
        assert result == "/browser_steps/c1/step_1.png"

    async def test_no_trailing_slash_unchanged(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
        with patch.object(shots.asyncio, "to_thread", AsyncMock(return_value=None)):
            result = await shots.upload_step_screenshot(b"x", "c1", 1)
        assert result == "https://cdn.example.com/browser_steps/c1/step_1.png"

    async def test_key_uses_conversation_id_and_index(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
        mock_to_thread = AsyncMock(return_value=None)
        with patch.object(shots.asyncio, "to_thread", mock_to_thread):
            await shots.upload_step_screenshot(b"x", "my-conv", 42)
        assert mock_to_thread.call_args[0][2] == "browser_steps/my-conv/step_42.png"

    async def test_upload_failure_returns_none_and_logs(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
        with (
            patch.object(shots.asyncio, "to_thread", AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(shots.log, "warning") as mock_warn,
        ):
            result = await shots.upload_step_screenshot(b"x", "c1", 1)
        assert result is None
        mock_warn.assert_called_once()
        # Exact message (not a loose substring check — a mutated literal that
        # merely gets padded would still contain any substring we look for).
        call_args = mock_warn.call_args
        assert (
            call_args[0][0]
            == f"{shots.LogTag.BROWSER} Browser screenshot upload failed; using inline fallback"
        )
        assert call_args[1].get("error_type") == "RuntimeError"

    async def test_upload_generic_exception_returns_none(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
        with (
            patch.object(shots.asyncio, "to_thread", AsyncMock(side_effect=ValueError("bad"))),
            patch.object(shots.log, "warning") as mock_warn,
        ):
            result = await shots.upload_step_screenshot(b"x", "c1", 1)
        assert result is None
        assert mock_warn.call_args[1]["error_type"] == "ValueError"

    async def test_upload_exception_logs_correct_error_type(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")

        class CustomError(Exception):
            pass

        with (
            patch.object(shots.asyncio, "to_thread", AsyncMock(side_effect=CustomError("oops"))),
            patch.object(shots.log, "warning") as mock_warn,
        ):
            await shots.upload_step_screenshot(b"x", "c1", 1)
        assert mock_warn.call_args[1]["error_type"] == "CustomError"

    async def test_calls_to_thread_with_put(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: True)
        monkeypatch.setattr(shots.settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
        mock_to_thread = AsyncMock(return_value=None)
        with patch.object(shots.asyncio, "to_thread", mock_to_thread):
            await shots.upload_step_screenshot(b"abc", "conv", 5)
        mock_to_thread.assert_awaited_once_with(shots._put, b"abc", "browser_steps/conv/step_5.png")

    async def test_not_configured_does_not_call_to_thread(self, monkeypatch):
        monkeypatch.setattr(shots, "_r2_configured", lambda: False)
        mock_to_thread = AsyncMock()
        with patch.object(shots.asyncio, "to_thread", mock_to_thread):
            await shots.upload_step_screenshot(b"x", "c1", 1)
        mock_to_thread.assert_not_called()
