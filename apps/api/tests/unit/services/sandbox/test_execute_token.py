"""Sandbox execute tokens — the ONLY auth on the code-mode callback route.

A forgeable/eternal token would let arbitrary sandbox code run any tool as any
user, so tamper, expiry and unconfigured-secret all fail loud.
"""

from unittest.mock import patch

import pytest

from app.constants.execute import SANDBOX_EXECUTE_TOKEN_SECRET_MIN_CHARS
from app.services.sandbox import execute_token
from app.services.sandbox.execute_token import mint_execute_token, verify_execute_token
from app.utils.errors import AppError

SECRET = "unit-test-secret-0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _secret():
    with patch.object(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET):
        yield


@pytest.mark.unit
class TestExecuteToken:
    def test_round_trip_preserves_claims(self) -> None:
        token = mint_execute_token(
            "u1", "run-9", stream_id="s7", scoped_tool_names=None, ttl_seconds=60
        )
        claims = verify_execute_token(token)
        assert claims.user_id == "u1"
        assert claims.run_id == "run-9"
        assert claims.stream_id == "s7"

    def test_tampered_signature_is_rejected(self) -> None:
        token = mint_execute_token("u1", "run-9", scoped_tool_names=None, ttl_seconds=60)
        payload, _, signature = token.partition(".")
        flipped = ("0" if signature[0] != "0" else "1") + signature[1:]
        with pytest.raises(AppError) as err:
            verify_execute_token(f"{payload}.{flipped}")
        assert err.value.status_code == 401
        # The sandbox client relays this envelope to the agent as the reason and the remedy.
        assert (err.value.message, err.value.why, err.value.fix) == (
            "Invalid sandbox execute token",
            "signature mismatch, malformed payload, or expired",
            "Re-run the bash command; each run mints a fresh short-lived token",
        )

    def test_tampered_payload_is_rejected(self) -> None:
        token = mint_execute_token("u1", "run-9", scoped_tool_names=None, ttl_seconds=60)
        other = mint_execute_token("attacker", "run-9", scoped_tool_names=None, ttl_seconds=60)
        spliced = other.partition(".")[0] + "." + token.partition(".")[2]
        with pytest.raises(AppError):
            verify_execute_token(spliced)

    def test_expired_token_is_rejected(self) -> None:
        token = mint_execute_token("u1", "run-9", scoped_tool_names=None, ttl_seconds=-1)
        with pytest.raises(AppError) as err:
            verify_execute_token(token)
        assert err.value.status_code == 401

    def test_a_token_is_valid_through_its_expiry_second_and_not_after(self) -> None:
        with patch.object(execute_token, "_epoch_now", return_value=1_000):
            token = mint_execute_token("u1", "run-9", scoped_tool_names=None, ttl_seconds=60)
        with patch.object(execute_token, "_epoch_now", return_value=1_060):
            assert verify_execute_token(token).exp == 1_060
        with (
            patch.object(execute_token, "_epoch_now", return_value=1_061),
            pytest.raises(AppError) as err,
        ):
            verify_execute_token(token)
        assert err.value.status_code == 401

    def test_garbage_is_rejected(self) -> None:
        with pytest.raises(AppError):
            verify_execute_token("not-a-token")

    def test_unset_secret_refuses_to_mint(self) -> None:
        with (
            patch.object(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", None),
            pytest.raises(AppError) as err,
        ):
            mint_execute_token("u1", "run-9", scoped_tool_names=None, ttl_seconds=60)
        assert err.value.status_code == 503
        assert (err.value.message, err.value.why, err.value.fix) == (
            "Sandbox execute tokens are not configured",
            "SANDBOX_EXECUTE_TOKEN_SECRET is unset",
            f"Set SANDBOX_EXECUTE_TOKEN_SECRET (min {SANDBOX_EXECUTE_TOKEN_SECRET_MIN_CHARS} chars)"
            " to enable code mode",
        )
