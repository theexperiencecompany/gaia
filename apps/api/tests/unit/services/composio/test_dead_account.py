"""Which Composio failures mean the connected account is gone."""

import pytest

from app.constants.error_codes import INTEGRATION_NOT_CONNECTED
from app.services.composio.dead_account import ConnectedAccountGoneError, is_dead_account_error
from app.utils.errors import AppError
from tests.factories import make_composio_not_found

DEAD_ACCOUNT_BODY = {
    "error": {
        "error_code": 1810,
        "name": "ActionExecute_ConnectedAccountNotFound",
        "message": "No connected account found for user and toolkit GMAIL",
    }
}
# What tools.proxy raises for an account id Composio no longer holds.
PROXY_DEAD_ACCOUNT_BODY = {
    "error": {
        "message": 'Connected account "ca_gone" not found',
        "code": 606,
        "slug": "ConnectedAccount_ResourceNotFound",
        "status": 404,
    }
}


class TestDeadAccountClassifier:
    """A false positive here marks a healthy account expired, so it keys on the structured error, not a bare 404."""

    def test_structured_error_code_is_recognized(self) -> None:
        assert is_dead_account_error(make_composio_not_found(DEAD_ACCOUNT_BODY, "boom")) is True

    def test_structured_error_name_is_recognized_without_the_code(self) -> None:
        body = {"error": {"name": "ActionExecute_ConnectedAccountNotFound"}}
        assert is_dead_account_error(make_composio_not_found(body, "boom")) is True

    def test_the_proxys_missing_account_slug_is_recognised(self) -> None:
        """The proxy path reports a dead account under a different code; seen live against Composio."""
        assert (
            is_dead_account_error(make_composio_not_found(PROXY_DEAD_ACCOUNT_BODY, "boom")) is True
        )

    def test_message_is_the_fallback_when_the_body_is_not_json(self) -> None:
        error = make_composio_not_found(None, "Composio error 1810: no active connected account")
        assert is_dead_account_error(error) is True

    def test_an_unrelated_404_is_not_a_dead_account(self) -> None:
        body = {"error": {"error_code": 1404, "name": "ToolNotFound", "slug": "Tool_NotFound"}}
        assert is_dead_account_error(make_composio_not_found(body, "Tool not found")) is False

    @pytest.mark.parametrize(
        "detail",
        [
            {"error_code": 1810},
            {"code": 1810},
            {"name": "ActionExecute_ConnectedAccountNotFound"},
            {"type": "ActionExecute_ConnectedAccountNotFound"},
            {"slug": "ConnectedAccount_ResourceNotFound"},
        ],
        ids=["error_code", "code", "name", "type", "slug"],
    )
    def test_every_spelling_of_the_code_and_the_name_is_recognised(
        self, detail: dict[str, object]
    ) -> None:
        """Composio's error envelope is not versioned; the message here carries no marker."""
        assert is_dead_account_error(make_composio_not_found({"error": detail}, "boom")) is True

    def test_a_dead_account_message_is_recognised_whatever_its_casing(self) -> None:
        error = make_composio_not_found(None, "No Active Connected Account for GMAIL")
        assert is_dead_account_error(error) is True


class TestConnectedAccountGoneError:
    def test_it_is_a_reconnect_error_the_web_already_handles(self) -> None:
        error = ConnectedAccountGoneError("GMAIL", "Connected account not found")

        assert isinstance(error, AppError)
        assert (error.status_code, error.code, error.public, error.fix) == (
            403,
            INTEGRATION_NOT_CONNECTED,
            {"toolkit": "GMAIL"},
            "Reconnect the GMAIL account",
        )
        assert error.message == "The GMAIL connected account no longer exists"
