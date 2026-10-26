"""verify_turnstile_token against a mocked Cloudflare siteverify (the only seam faked)."""

from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.config.settings import settings
from app.constants.email import SUPPORT_EMAIL
from app.constants.turnstile import TURNSTILE_SITEVERIFY_URL
from app.services.turnstile_service import verify_turnstile_token
from app.utils.errors import AppError

# Cloudflare's documented always-pass test secret; the response itself is mocked.
TEST_SECRET = "1x0000000000000000000000000000000AA"


def _assert_unavailable(err: AppError, cause: str) -> None:
    """Assert the 503 a visitor sees is fixed text, not the failure message."""
    assert err.status_code == 503
    assert err.code == "turnstile_unavailable"
    assert err.message == "We could not check that you are human right now"
    assert err.why == "The verification service is unavailable"
    assert err.fix == f"Try again in a minute, or email {SUPPORT_EMAIL}"
    assert err.meta == {"cause": cause}


@pytest.fixture
def secret(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", TEST_SECRET)
    return TEST_SECRET


@respx.mock
async def test_a_confirmed_token_passes_and_sends_the_secret_token_and_remoteip(
    secret: str,
) -> None:
    route = respx.post(TURNSTILE_SITEVERIFY_URL).mock(
        return_value=httpx.Response(200, json={"success": True, "error-codes": []})
    )

    await verify_turnstile_token("tok-123", "203.0.113.7")

    sent = parse_qs(route.calls.last.request.content.decode())
    assert sent == {"secret": [secret], "response": ["tok-123"], "remoteip": ["203.0.113.7"]}


@respx.mock
async def test_a_rejected_token_is_a_400_with_the_verification_code(secret: str) -> None:
    respx.post(TURNSTILE_SITEVERIFY_URL).mock(
        return_value=httpx.Response(
            200, json={"success": False, "error-codes": ["invalid-input-response"]}
        )
    )

    with pytest.raises(AppError) as excinfo:
        await verify_turnstile_token("forged", "203.0.113.7")

    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "turnstile_verification_failed"
    assert excinfo.value.meta == {"error_codes": ["invalid-input-response"]}


@respx.mock
async def test_a_missing_secret_refuses_with_503_without_calling_cloudflare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", None)
    route = respx.post(TURNSTILE_SITEVERIFY_URL)

    with (
        patch("app.services.turnstile_service.log") as mock_log,
        pytest.raises(AppError) as excinfo,
    ):
        await verify_turnstile_token("tok-123", "203.0.113.7")

    _assert_unavailable(excinfo.value, "TURNSTILE_SECRET_KEY is unset")
    mock_log.error.assert_called_once()
    assert not route.called


@pytest.mark.parametrize(
    "outcome",
    [
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("down"),
        httpx.Response(500, text="oops"),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"unexpected": True}),
    ],
    ids=["timeout", "connect-error", "5xx", "non-json", "no-success-field"],
)
@respx.mock
async def test_a_siteverify_failure_refuses_with_503_never_accepts(
    secret: str, outcome: Exception | httpx.Response
) -> None:
    route = respx.post(TURNSTILE_SITEVERIFY_URL)
    if isinstance(outcome, Exception):
        route.mock(side_effect=outcome)
    else:
        route.mock(return_value=outcome)

    with (
        patch("app.services.turnstile_service.log") as mock_log,
        pytest.raises(AppError) as excinfo,
    ):
        await verify_turnstile_token("tok-123", None)

    cause = excinfo.value.meta["cause"]
    assert cause.startswith("siteverify failed: ")
    _assert_unavailable(excinfo.value, cause)
    mock_log.error.assert_called_once()


@respx.mock
async def test_no_remote_ip_omits_remoteip(secret: str) -> None:
    route = respx.post(TURNSTILE_SITEVERIFY_URL).mock(
        return_value=httpx.Response(200, json={"success": True})
    )

    await verify_turnstile_token("tok-123", None)

    assert "remoteip" not in parse_qs(route.calls.last.request.content.decode())
