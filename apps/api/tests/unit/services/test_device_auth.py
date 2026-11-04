"""Unit tests for app.services.device.device_auth — the device connect JWT."""

import time

import pytest

from app.constants.auth import JWT_ALGORITHM
from app.constants.device_bridge import DEVICE_TOKEN_AUDIENCE, DEVICE_TOKEN_EXPIRY_MINUTES
from app.services.device import device_auth
from app.services.device.device_auth import create_device_token, verify_device_token
from tests.helpers import (
    JOSE_AGENT_DEVICE_SECRET,
    JOSE_MINTED_DEVICE_TOKEN,
    forge_jwt,
    hostile_jwts,
    read_jwt,
)

_SECRET = "device-test-secret-" + "x" * 24  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device_auth, "_SECRET", _SECRET)


def _claims(**overrides: object) -> dict[str, object]:
    return {
        "sub": "u-1",
        "device_id": "d-1",
        "aud": DEVICE_TOKEN_AUDIENCE,
        "role": "device",
        "exp": int(time.time()) + 600,
        **overrides,
    }


def test_a_minted_token_verifies_to_its_device_and_user() -> None:
    token, _ = create_device_token("d-1", "u-1")
    assert verify_device_token(token) == {"user_id": "u-1", "device_id": "d-1"}


def test_a_minted_token_carries_its_audience_role_and_lifetime() -> None:
    token, expires_in = create_device_token("d-1", "u-1")
    header, claims = read_jwt(token)
    assert header == {"alg": JWT_ALGORITHM, "typ": "JWT"}
    assert claims["aud"] == DEVICE_TOKEN_AUDIENCE
    assert claims["role"] == "device"
    assert claims["exp"] - claims["iat"] == expires_in == DEVICE_TOKEN_EXPIRY_MINUTES * 60


def test_a_token_minted_by_python_jose_still_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device_auth, "_SECRET", JOSE_AGENT_DEVICE_SECRET)
    assert verify_device_token(JOSE_MINTED_DEVICE_TOKEN) == {
        "user_id": "u-jose",
        "device_id": "dev-jose",
    }


@pytest.mark.parametrize("kind", sorted(hostile_jwts({}, "s")))
def test_a_hostile_token_is_rejected(kind: str) -> None:
    assert verify_device_token(hostile_jwts(_claims(), _SECRET)[kind]) is None


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param(_claims(aud="somewhere-else"), id="wrong-audience"),
        pytest.param(_claims(aud=["somewhere-else"]), id="wrong-audience-list"),
        pytest.param(_claims(role="agent"), id="agent-role"),
        pytest.param(_claims(device_id=None), id="no-device-id"),
        pytest.param({k: v for k, v in _claims().items() if k != "sub"}, id="no-subject"),
        pytest.param({k: v for k, v in _claims().items() if k != "aud"}, id="no-audience"),
    ],
)
def test_a_signed_token_that_is_not_a_device_token_is_rejected(claims: dict[str, object]) -> None:
    assert verify_device_token(forge_jwt(claims, _SECRET)) is None


def test_an_audience_list_naming_the_bridge_verifies() -> None:
    token = forge_jwt(_claims(aud=["other", DEVICE_TOKEN_AUDIENCE]), _SECRET)
    assert verify_device_token(token) == {"user_id": "u-1", "device_id": "d-1"}
