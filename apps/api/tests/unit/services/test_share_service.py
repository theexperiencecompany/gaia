"""Unit tests for single-purpose file-share grants (share_service).

Mint is sync (hook context cannot await); redeem is async (reads bytes).
The signing secret is monkeypatched per test — the hermetic fence blanks real
credentials. A short secret fails like a blank one: 32+ chars required.
"""

from pathlib import Path
import time
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

from app.config.settings import settings
from app.constants.files import SHARE_GRANT_MAX_TTL_SECONDS
from app.models.share_models import ShareGrantPayload
from app.services.share_service import _serializer, mint_share_url, redeem_share_grant
from app.services.storage.juicefs import JuiceFSUnavailable
from app.utils.errors import AppError

MODULE = "app.services.share_service"


@pytest.fixture
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SHARE_GRANT_SECRET", "test-only-share-secret-0123456789abcdef")


def _mint_url(tmp_path: Path, filename: str = "report.pdf", **kwargs: Any) -> str:
    host = tmp_path / filename
    host.write_bytes(b"%PDF-1.4 x")
    with patch(f"{MODULE}.resolve_user_file_sync", return_value=host):
        return mint_share_url(user_id="u1", workspace_path=filename, **kwargs)


def _token_of(url: str) -> str:
    # Token rides in the query string (never the logged path); the filename
    # stays in the path for Composio's basename derivation.
    return parse_qs(urlsplit(url).query)["token"][0]


class TestMintShareUrl:
    def test_mints_absolute_url_with_token_and_filename(
        self, _secret: None, tmp_path: Path
    ) -> None:
        host = tmp_path / "report.pdf"
        host.write_bytes(b"%PDF-1.4 x")
        with patch(f"{MODULE}.resolve_user_file_sync", return_value=host) as res:
            url = mint_share_url(
                user_id="u1",
                workspace_path="/workspace/sessions/c/report.pdf",
                tool="OUTLOOK_SEND_EMAIL",
                toolkit="outlook",
            )
        assert res.call_args.args == ("u1", "sessions/c/report.pdf")
        assert url.startswith(f"{settings.HOST}/api/v1/files/s/report.pdf?token=")
        assert len(_token_of(url)) > 32  # signed payload, not a guessable id

    def test_missing_file_raises_before_minting(self, _secret: None) -> None:
        with (
            patch(
                f"{MODULE}.resolve_user_file_sync",
                side_effect=FileNotFoundError("gone"),
            ),
            pytest.raises(FileNotFoundError),
        ):
            mint_share_url(user_id="u1", workspace_path="/workspace/gone.pdf")

    def test_blank_secret_fails_loud(
        self, _secret: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(settings, "SHARE_GRANT_SECRET", None)
        host = tmp_path / "a.txt"
        host.write_bytes(b"x")
        with (
            patch(f"{MODULE}.resolve_user_file_sync", return_value=host),
            pytest.raises(AppError, match="not configured"),
        ):
            mint_share_url(user_id="u1", workspace_path="a.txt")

    def test_short_secret_fails_like_blank(
        self, _secret: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(settings, "SHARE_GRANT_SECRET", "too-short")
        host = tmp_path / "a.txt"
        host.write_bytes(b"x")
        with (
            patch(f"{MODULE}.resolve_user_file_sync", return_value=host),
            pytest.raises(AppError, match="not configured"),
        ):
            mint_share_url(user_id="u1", workspace_path="a.txt")

    def test_same_file_mints_distinct_tokens(self, _secret: None, tmp_path: Path) -> None:
        assert _mint_url(tmp_path) != _mint_url(tmp_path)  # nonce per grant


class TestRedeemShareGrant:
    async def test_round_trip_returns_bytes_name_mimetype(
        self, _secret: None, tmp_path: Path
    ) -> None:
        url = _mint_url(tmp_path)
        with patch(f"{MODULE}.read_user_file_bytes", return_value=b"%PDF-1.4 x") as reader:
            result = await redeem_share_grant(_token_of(url))
        assert result == (b"%PDF-1.4 x", "report.pdf", "application/pdf")
        assert reader.call_args.args == ("u1", "report.pdf")

    async def test_tampered_token_is_none(self, _secret: None, tmp_path: Path) -> None:
        token = _token_of(_mint_url(tmp_path))
        assert await redeem_share_grant(token[:-2] + "AA") is None

    async def test_nonpositive_ttl_raises_at_mint(self, _secret: None, tmp_path: Path) -> None:
        host = tmp_path / "a.txt"
        host.write_bytes(b"x")
        with (
            patch(f"{MODULE}.resolve_user_file_sync", return_value=host),
            pytest.raises(AppError, match="lifetime"),
        ):
            mint_share_url(user_id="u1", workspace_path="a.txt", ttl_seconds=-1)

    async def test_huge_ttl_clamps_to_max(self, _secret: None, tmp_path: Path) -> None:
        host = tmp_path / "a.txt"
        host.write_bytes(b"x")
        with patch(f"{MODULE}.resolve_user_file_sync", return_value=host):
            url = mint_share_url(user_id="u1", workspace_path="a.txt", ttl_seconds=10**9)
        payload = ShareGrantPayload.model_validate(_serializer().loads(_token_of(url)))
        assert payload.expires_at - time.time() <= SHARE_GRANT_MAX_TTL_SECONDS
        assert payload.expires_at - time.time() > SHARE_GRANT_MAX_TTL_SECONDS - 60

    async def test_expired_grant_is_none(self, _secret: None, tmp_path: Path) -> None:
        # Crafted past-expiry payload (mint itself now refuses ttl<=0).
        payload = ShareGrantPayload(
            user_id="u1",
            workspace_rel_path="a.txt",
            filename="a.txt",
            mimetype="text/plain",
            max_bytes=10,
            expires_at=time.time() - 1,
            nonce="expired-nonce",
        )
        assert await redeem_share_grant(_serializer().dumps(payload.model_dump())) is None

    async def test_blank_secret_redeem_is_closed(
        self, _secret: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        token = _token_of(_mint_url(tmp_path))
        monkeypatch.setattr(settings, "SHARE_GRANT_SECRET", None)
        assert await redeem_share_grant(token) is None

    async def test_short_secret_redeem_is_closed_not_a_503(
        self, _secret: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # A secret too short to sign with is a misconfiguration, not an oracle:
        # raising out of the route would let a prober tell it apart from a bad
        # token, breaking the uniform-404 contract every other failure keeps.
        token = _token_of(_mint_url(tmp_path))
        monkeypatch.setattr(settings, "SHARE_GRANT_SECRET", "too-short")
        assert await redeem_share_grant(token) is None

    async def test_missing_file_at_fetch_is_none(self, _secret: None, tmp_path: Path) -> None:
        token = _token_of(_mint_url(tmp_path))
        with patch(f"{MODULE}.read_user_file_bytes", side_effect=FileNotFoundError("gone")):
            assert await redeem_share_grant(token) is None

    async def test_oversize_at_fetch_is_none(self, _secret: None, tmp_path: Path) -> None:
        token = _token_of(_mint_url(tmp_path))
        with patch(f"{MODULE}.read_user_file_bytes", side_effect=ValueError("too big")):
            assert await redeem_share_grant(token) is None

    async def test_unavailable_mount_is_none(self, _secret: None, tmp_path: Path) -> None:
        token = _token_of(_mint_url(tmp_path))
        with patch(
            f"{MODULE}.read_user_file_bytes",
            side_effect=JuiceFSUnavailable("no mount"),
        ):
            assert await redeem_share_grant(token) is None

    async def test_unreadable_file_is_none_not_500(self, _secret: None, tmp_path: Path) -> None:
        token = _token_of(_mint_url(tmp_path))
        with patch(f"{MODULE}.read_user_file_bytes", side_effect=OSError("EIO")):
            assert await redeem_share_grant(token) is None
