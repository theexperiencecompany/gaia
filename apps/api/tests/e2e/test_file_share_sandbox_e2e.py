"""Files as the user experiences them: attach, share, run — each link works.

Unit tests prove each half with the other mocked (share mint with the FS
patched out, sandbox auth with dispatch patched out, upload validation apart
from the network call). Nothing proved the joins that actually break: a minted
share URL the redeem path cannot read back, a sandbox token whose budget
counters never accumulate across calls because each test faked the counts, an
upload that passes validation but fails the only call that matters.

Real: upload validation, the itsdangerous mint→redeem roundtrip, sandbox
token crypto + budget enforcement + dispatch + audit. Doubled: Cloudinary
(network), the JuiceFS bytes (tmp files), the sandbox tool body.
"""

from __future__ import annotations

from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import fakeredis.aioredis
from fastapi import HTTPException
import pytest

from app.agents.tools.execute.dispatch import ToolExecutionResult
from app.api.v1.endpoints.sandbox_execute import SandboxExecuteRequest, sandbox_execute
from app.config.settings import settings
from app.constants.execute import SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN
from app.services.sandbox import execute_token
from app.services.sandbox.execute_token import mint_execute_token
from app.services.share_service import mint_share_url, redeem_share_grant
from app.services.upload_service import upload_file_to_cloudinary
from app.utils.errors import AppError

pytestmark = pytest.mark.e2e

SHARE_MODULE = "app.services.share_service"
SANDBOX_MODULE = "app.api.v1.endpoints.sandbox_execute"
UPLOAD_MODULE = "app.services.upload_service"
TOKEN_SECRET = "e2e-share-secret-0123456789abcdef0123456789"
EXEC_SECRET = "e2e-sandbox-secret-0123456789abcdef0123456789abcdef"


@pytest.fixture
def _share_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SHARE_GRANT_SECRET", TOKEN_SECRET)


@pytest.fixture
def _exec_secret() -> None:
    with patch.object(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", EXEC_SECRET):
        yield


@pytest.fixture
def _frozen_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    minute = 29_000_000
    monkeypatch.setattr(
        "app.services.sandbox.token_budget.time", SimpleNamespace(time=lambda: minute * 60 + 30)
    )


def _token_of(url: str) -> str:
    return parse_qs(urlsplit(url).query)["token"][0]


class TestUploadValidatesBeforeTouchingTheNetwork:
    def test_neither_source_nor_path_is_400_without_uploading(self) -> None:
        with patch(f"{UPLOAD_MODULE}.cloudinary.uploader.upload") as upload:
            with pytest.raises(HTTPException) as err:
                upload_file_to_cloudinary(public_id="a")
        assert err.value.status_code == 400
        upload.assert_not_called()

    def test_both_sources_is_400_without_uploading(self, tmp_path: Path) -> None:
        host = tmp_path / "a.bin"
        host.write_bytes(b"x")
        with patch(f"{UPLOAD_MODULE}.cloudinary.uploader.upload") as upload:
            with pytest.raises(HTTPException) as err:
                upload_file_to_cloudinary(public_id="a", file_data=b"x", file_path=str(host))
        assert err.value.status_code == 400
        upload.assert_not_called()

    def test_missing_file_path_is_404_without_uploading(self) -> None:
        with patch(f"{UPLOAD_MODULE}.cloudinary.uploader.upload") as upload:
            with pytest.raises(HTTPException) as err:
                upload_file_to_cloudinary(public_id="a", file_path="/no/such/file.bin")
        assert err.value.status_code == 404
        upload.assert_not_called()

    def test_bytes_reach_cloudinary_and_return_the_secure_url(self) -> None:
        with patch(
            f"{UPLOAD_MODULE}.cloudinary.uploader.upload",
            return_value={"secure_url": "https://cdn.example/a"},
        ) as upload:
            url = upload_file_to_cloudinary(public_id="a", file_data=b"bytes")
        assert url == "https://cdn.example/a"
        assert upload.call_args.kwargs["public_id"] == "a"


class TestShareMintRedeemRoundtrip:
    def test_minted_url_redeems_to_the_same_bytes(
        self, _share_secret: None, tmp_path: Path
    ) -> None:
        host = tmp_path / "report.pdf"
        host.write_bytes(b"%PDF-1.4 composition")
        with patch(f"{SHARE_MODULE}.resolve_user_file_sync", return_value=host):
            url = mint_share_url(user_id="u1", workspace_path="report.pdf")
        assert url.startswith(f"{settings.HOST}/api/v1/files/s/report.pdf?token=")
        assert len(_token_of(url)) > 32

    async def test_redeem_reads_back_with_the_signed_cap(
        self, _share_secret: None, tmp_path: Path
    ) -> None:
        host = tmp_path / "report.pdf"
        host.write_bytes(b"%PDF-1.4 composition")
        with patch(f"{SHARE_MODULE}.resolve_user_file_sync", return_value=host):
            url = mint_share_url(user_id="u1", workspace_path="report.pdf", max_bytes=64)
        with patch(
            f"{SHARE_MODULE}.read_user_file_bytes", AsyncMock(return_value=b"%PDF-1.4 composition")
        ) as reader:
            result = await redeem_share_grant(_token_of(url))

        assert result is not None
        body, filename, mimetype = result
        assert body == b"%PDF-1.4 composition"
        assert filename == "report.pdf"
        assert reader.call_args.kwargs == {"max_bytes": 64}

    async def test_two_mints_differ_and_tampered_token_is_none(
        self, _share_secret: None, tmp_path: Path
    ) -> None:
        host = tmp_path / "a.txt"
        host.write_bytes(b"x")
        with patch(f"{SHARE_MODULE}.resolve_user_file_sync", return_value=host):
            first = mint_share_url(user_id="u1", workspace_path="a.txt")
            second = mint_share_url(user_id="u1", workspace_path="a.txt")
        assert _token_of(first) != _token_of(second)  # nonce, not a counter
        assert await redeem_share_grant(_token_of(first) + "tampered") is None

    async def test_expired_grant_is_none(
        self, _share_secret: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        host = tmp_path / "a.txt"
        host.write_bytes(b"x")
        with patch(f"{SHARE_MODULE}.resolve_user_file_sync", return_value=host):
            url = mint_share_url(user_id="u1", workspace_path="a.txt", ttl_seconds=60)
        token = _token_of(url)
        with (
            patch(f"{SHARE_MODULE}.read_user_file_bytes", AsyncMock(return_value=b"x")),
            patch(f"{SHARE_MODULE}.time.time", return_value=time.time() + 3600),
        ):
            assert await redeem_share_grant(token) is None


class TestSandboxTokenBudgetChain:
    def _payload(self) -> SandboxExecuteRequest:
        return SandboxExecuteRequest(tool_name="GMAIL_FETCH_EMAILS", data={"max_results": 3})

    def _ok_dispatch(self) -> AsyncMock:
        return AsyncMock(
            return_value=ToolExecutionResult(ok=True, resolved_name="GMAIL_FETCH_EMAILS", output=[])
        )

    async def test_calls_accumulate_until_the_budget_429s(
        self,
        _exec_secret: None,
        _frozen_minute: None,
        fake_redis: fakeredis.aioredis.FakeRedis,
    ) -> None:
        """Unit tests faked the counts; here a key mismatch between increment and limit would show."""
        token = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=600)
        auth = f"Bearer {token}"

        with patch(f"{SANDBOX_MODULE}.dispatch_tool", new=self._ok_dispatch()):
            response = await sandbox_execute(self._payload(), authorization=auth)
            assert response.ok is True
            # The increment really landed — the next call does not start from zero.
            assert await fake_redis.get("sandbox_execute:calls:run-1") == "1"

            await fake_redis.set(
                "sandbox_execute:calls:run-1", SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN - 1
            )
            response = await sandbox_execute(self._payload(), authorization=auth)
            assert response.ok is True
            with pytest.raises(AppError) as err:
                await sandbox_execute(self._payload(), authorization=auth)
        assert err.value.status_code == 429

    async def test_budget_is_per_run(
        self,
        _exec_secret: None,
        _frozen_minute: None,
        fake_redis: fakeredis.aioredis.FakeRedis,
    ) -> None:
        good = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=600)
        other = mint_execute_token("u1", "run-2", scoped_tool_names=None, ttl_seconds=600)
        await fake_redis.set("sandbox_execute:calls:run-1", SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN)
        with patch(f"{SANDBOX_MODULE}.dispatch_tool", new=self._ok_dispatch()):
            with pytest.raises(AppError) as err:
                await sandbox_execute(self._payload(), authorization=f"Bearer {good}")
            assert err.value.status_code == 429
            response = await sandbox_execute(self._payload(), authorization=f"Bearer {other}")
        assert response.ok is True

    async def test_no_token_never_dispatches_and_is_401(
        self, _exec_secret: None, _frozen_minute: None
    ) -> None:
        with patch(f"{SANDBOX_MODULE}.dispatch_tool", new=AsyncMock()) as dispatch:
            with pytest.raises(AppError) as err:
                await sandbox_execute(self._payload(), authorization="")
        assert err.value.status_code == 401
        dispatch.assert_not_awaited()

    async def test_every_dispatched_call_is_audited(
        self,
        _exec_secret: None,
        _frozen_minute: None,
        fake_redis: fakeredis.aioredis.FakeRedis,
    ) -> None:
        token = mint_execute_token("u1", "run-9", scoped_tool_names=None, ttl_seconds=600)
        with (
            patch(f"{SANDBOX_MODULE}.dispatch_tool", new=self._ok_dispatch()),
            patch(f"{SANDBOX_MODULE}.log") as mocked_log,
        ):
            await sandbox_execute(self._payload(), authorization=f"Bearer {token}")
        audit_kwargs = mocked_log.audit.call_args.kwargs
        assert audit_kwargs["actor"] == "u1"
        assert audit_kwargs["tool"] == "GMAIL_FETCH_EMAILS"
        assert audit_kwargs["run_id"] == "run-9"
