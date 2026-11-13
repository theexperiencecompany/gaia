"""What the crash capture hands PostHog, tested against the helper directly."""

from unittest.mock import MagicMock, patch

import pytest
from starlette.requests import Request

from app.core.unhandled_errors import capture_unhandled_exception
from app.models.user_models import AuthenticatedUser

pytestmark = pytest.mark.unit

PROVIDERS = "app.core.unhandled_errors.providers"


def _request(user: AuthenticatedUser | None) -> Request:
    request = Request({"type": "http", "method": "GET", "path": "/boom", "headers": []})
    if user is not None:
        request.state.user = user
    return request


def _posthog(available: bool) -> tuple[MagicMock, MagicMock]:
    client = MagicMock()
    providers = MagicMock()
    # Key-sensitive: the client lives under exactly one registry key.
    providers.is_available.side_effect = lambda key: available and key == "posthog"
    providers.get.side_effect = lambda key: client if available and key == "posthog" else None
    return providers, client


def test_a_crash_is_attributed_to_the_user_on_the_request() -> None:
    providers, client = _posthog(available=True)
    exc = RuntimeError("db down")

    with patch(PROVIDERS, providers):
        capture_unhandled_exception(_request(AuthenticatedUser(user_id="u1")), exc)

    client.capture_exception.assert_called_once_with(exc, distinct_id="u1")


def test_an_anonymous_crash_is_captured_without_an_id() -> None:
    providers, client = _posthog(available=True)
    exc = RuntimeError("db down")

    with patch(PROVIDERS, providers):
        capture_unhandled_exception(_request(None), exc)

    client.capture_exception.assert_called_once_with(exc)


def test_a_user_without_an_id_is_captured_as_anonymous() -> None:
    """An empty id would file every such crash under one bogus profile."""
    providers, client = _posthog(available=True)
    exc = RuntimeError("db down")

    with patch(PROVIDERS, providers):
        capture_unhandled_exception(_request(AuthenticatedUser(user_id="")), exc)

    client.capture_exception.assert_called_once_with(exc)


def test_no_registered_client_means_no_capture_and_no_error() -> None:
    providers, client = _posthog(available=False)

    with patch(PROVIDERS, providers):
        capture_unhandled_exception(_request(AuthenticatedUser(user_id="u1")), RuntimeError("x"))

    client.capture_exception.assert_not_called()
    providers.get.assert_not_called()
