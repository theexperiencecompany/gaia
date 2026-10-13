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

from itsdangerous import URLSafeTimedSerializer
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

    def test_http_host_refused_in_production(
        self, _secret: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # In prod the token would reach Composio in cleartext over http (CWE-319).
        monkeypatch.setattr(settings, "ENV", "production")
        monkeypatch.setattr(settings, "HOST", "http://api.example.com")
        host = tmp_path / "a.txt"
        host.write_bytes(b"x")
        with (
            patch(f"{MODULE}.resolve_user_file_sync", return_value=host),
            pytest.raises(AppError, match="HTTPS") as exc,
        ):
            mint_share_url(user_id="u1", workspace_path="a.txt")
        assert exc.value.status_code == 503
        # The error carries actionable operator guidance (why + fix), not a bare message.
        assert exc.value.why
        assert exc.value.fix

    def test_https_host_allowed_in_production(
        self, _secret: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(settings, "ENV", "production")
        monkeypatch.setattr(settings, "HOST", "https://api.example.com")
        host = tmp_path / "a.txt"
        host.write_bytes(b"x")
        with patch(f"{MODULE}.resolve_user_file_sync", return_value=host):
            url = mint_share_url(user_id="u1", workspace_path="a.txt")
        assert url.startswith("https://api.example.com/api/v1/files/s/")

    def test_http_localhost_allowed_in_development(
        self, _secret: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Local dev serves the grant over http://localhost; no secret leaves the box.
        monkeypatch.setattr(settings, "ENV", "development")
        monkeypatch.setattr(settings, "HOST", "http://localhost:8000")
        host = tmp_path / "a.txt"
        host.write_bytes(b"x")
        with patch(f"{MODULE}.resolve_user_file_sync", return_value=host):
            url = mint_share_url(user_id="u1", workspace_path="a.txt")
        assert url.startswith("http://localhost:8000/api/v1/files/s/")

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

    def test_a_secret_of_exactly_the_minimum_length_is_accepted(
        self, _secret: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # 32 is the floor, not the first rejected length — an off-by-one here
        # takes file sharing down for anyone who set exactly 32 characters.
        monkeypatch.setattr(settings, "SHARE_GRANT_SECRET", "a" * 32)

        assert _mint_url(tmp_path)

    def test_a_secret_one_character_short_is_refused(
        self, _secret: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(settings, "SHARE_GRANT_SECRET", "a" * 31)
        with pytest.raises(AppError):
            _mint_url(tmp_path)

    def test_the_unconfigured_error_names_the_setting_and_how_to_set_it(
        self, _secret: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # This one lands in an operator's log, not a user's screen: the why/fix
        # are the whole remediation, so an empty pair leaves them guessing.
        monkeypatch.setattr(settings, "SHARE_GRANT_SECRET", None)
        with pytest.raises(AppError) as exc:
            _mint_url(tmp_path)

        assert exc.value.message == "File sharing is not configured."
        assert exc.value.why == (
            "The share signing secret (SHARE_GRANT_SECRET) is missing or too short."
        )
        assert exc.value.fix == "Set SHARE_GRANT_SECRET to 32+ random characters and retry."

    def test_grants_are_signed_in_their_own_namespace(self, _secret: None) -> None:
        # The salt keeps a signature minted here from validating anywhere else
        # that signs with the same secret, and vice versa.
        assert _serializer().salt == b"file-share-grant"

    def test_same_file_mints_distinct_tokens(self, _secret: None, tmp_path: Path) -> None:
        assert _mint_url(tmp_path) != _mint_url(tmp_path)  # nonce per grant

    def test_a_zero_second_lifetime_is_refused_like_a_negative_one(
        self, _secret: None, tmp_path: Path
    ) -> None:
        # A grant that expires the instant it is minted is never redeemable, so
        # it must fail at the call site rather than 404 later at fetch time.
        with pytest.raises(AppError):
            _mint_url(tmp_path, ttl_seconds=0)

    def test_the_shortest_positive_lifetime_still_mints(
        self, _secret: None, tmp_path: Path
    ) -> None:
        assert _mint_url(tmp_path, ttl_seconds=1)

    def test_the_invalid_lifetime_error_says_what_to_do_about_it(
        self, _secret: None, tmp_path: Path
    ) -> None:
        # AppError's why/fix are rendered to whoever hit this, so they are the
        # product here, not decoration; the status is what the client branches on.
        with pytest.raises(AppError) as exc:
            _mint_url(tmp_path, ttl_seconds=0)

        assert exc.value.status_code == 400
        assert exc.value.message == "Invalid share lifetime."
        assert exc.value.why == "ttl_seconds must be positive."
        assert exc.value.fix == "Pass a positive ttl_seconds and retry."

    def test_an_unconfigured_secret_reads_as_unavailable_not_bad_input(
        self, _secret: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # 503: the caller sent nothing wrong, the server is missing config.
        monkeypatch.setattr(settings, "SHARE_GRANT_SECRET", None)
        with pytest.raises(AppError) as exc:
            _mint_url(tmp_path)

        assert exc.value.status_code == 503

    def test_the_grant_records_the_tool_that_asked_for_it(
        self, _secret: None, tmp_path: Path
    ) -> None:
        # The signed payload is the audit trail for a bearer that bypasses auth:
        # without the attribution nothing says which tool call minted it.
        url = _mint_url(tmp_path, tool="OUTLOOK_SEND_EMAIL", toolkit="outlook")
        payload = ShareGrantPayload.model_validate(_serializer().loads(_token_of(url)))

        assert (payload.tool, payload.toolkit) == ("OUTLOOK_SEND_EMAIL", "outlook")

    def test_an_unguessable_extension_falls_back_to_a_binary_mimetype(
        self, _secret: None, tmp_path: Path
    ) -> None:
        # The grant's mimetype is what the fetch serves; an empty one would make
        # the download unusable to whatever asked for it.
        url = _mint_url(tmp_path, filename="notes.qqq")
        payload = ShareGrantPayload.model_validate(_serializer().loads(_token_of(url)))

        assert payload.mimetype == "application/octet-stream"


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

    async def test_a_token_signed_for_another_purpose_is_rejected(
        self, _secret: None, tmp_path: Path
    ) -> None:
        # The salt is domain separation: another signer holding the same secret
        # (any other itsdangerous use in this app) must not mint file grants.
        url = _mint_url(tmp_path)
        payload = _serializer().loads(_token_of(url))
        unsalted = URLSafeTimedSerializer(settings.SHARE_GRANT_SECRET).dumps(payload)

        assert await redeem_share_grant(unsalted) is None

    async def test_the_grants_byte_cap_reaches_the_reader(
        self, _secret: None, tmp_path: Path
    ) -> None:
        # The cap is per-grant and signed into the token; reading without it
        # would serve a file the grant never authorised in full.
        url = _mint_url(tmp_path, max_bytes=1234)
        with patch(f"{MODULE}.read_user_file_bytes", return_value=b"x") as reader:
            await redeem_share_grant(_token_of(url))

        assert reader.call_args.kwargs == {"max_bytes": 1234}

    async def test_a_grant_is_still_valid_at_its_expiry_instant(
        self, _secret: None, tmp_path: Path
    ) -> None:
        url = _mint_url(tmp_path)
        payload = ShareGrantPayload.model_validate(_serializer().loads(_token_of(url)))
        with (
            patch(f"{MODULE}.time.time", return_value=payload.expires_at),
            patch(f"{MODULE}.read_user_file_bytes", return_value=b"x"),
        ):
            assert await redeem_share_grant(_token_of(url)) is not None

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
