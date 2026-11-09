"""Terminal-auth classification: exact signals read from an exception's HTTP response."""

from unittest.mock import patch

import pytest

from app.services.mcp.mcp_errors import _extract_response_signal, is_terminal_auth_failure
from shared.py.wide_events import log


class _Response:
    def __init__(self, status_code: int, body: object) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> object:
        return self._body


class _NoStatusResponse:
    def json(self) -> object:
        return {"error": "Invalid_Grant"}


class _NoJsonResponse:
    status_code = 500


class _HttpError(Exception):
    def __init__(self, message: str, response: object) -> None:
        super().__init__(message)
        self.response = response


@pytest.mark.unit
class TestExtractResponseSignal:
    def test_response_without_status_code_yields_none_status(self) -> None:
        error = _HttpError("boom", _NoStatusResponse())

        assert _extract_response_signal(error) == (None, "invalid_grant")

    def test_json_method_is_read_by_name(self) -> None:
        error = _HttpError("boom", _Response(400, {"error": "invalid_token"}))

        assert _extract_response_signal(error) == (400, "invalid_token")

    def test_response_without_json_is_not_a_parse_failure(self) -> None:
        error = _HttpError("boom", _NoJsonResponse())

        with patch.object(log, "debug") as debug:
            assert _extract_response_signal(error) == (500, None)

        debug.assert_not_called()


@pytest.mark.unit
class TestIsTerminalAuthFailure:
    def test_403_after_refresh_is_terminal(self) -> None:
        error = _HttpError("forbidden", _Response(403, {}))

        assert is_terminal_auth_failure(error, refresh_attempted=True) is True

    def test_404_after_refresh_is_not_terminal(self) -> None:
        error = _HttpError("not found", _Response(404, {}))

        assert is_terminal_auth_failure(error, refresh_attempted=True) is False

    @pytest.mark.parametrize("message", ["invalid_grant", "got 401 back"])
    def test_message_text_is_ignored_when_a_response_is_attached(self, message: str) -> None:
        error = _HttpError(message, _Response(500, {}))

        assert is_terminal_auth_failure(error, refresh_attempted=True) is False
