"""The proxy logs the route shape of an endpoint, never the owner's email in a calendar id."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.composio.proxy_client import ProxyRequest, proxy_request_sync

CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/jane.doe%40example.com/events/evt1"
MASKED_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/evt1"


def _request(endpoint: str) -> ProxyRequest:
    return ProxyRequest(user_id="u1", toolkit="GOOGLECALENDAR", endpoint=endpoint, method="GET")


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        (CALENDAR_URL, MASKED_URL),
        (
            "https://www.googleapis.com/calendar/v3/calendars/primary/events?x=1",
            "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events?x=1",
        ),
        ("https://gmail.googleapis.com/gmail/v1/users/me/threads/abc", None),
    ],
)
def test_loggable_endpoint_masks_only_the_calendar_id(endpoint: str, expected: str | None) -> None:
    assert _request(endpoint).loggable_endpoint == (expected or endpoint)


def test_the_wide_event_never_carries_the_calendar_id_but_the_call_does() -> None:
    composio = MagicMock()
    composio.tools.proxy.return_value = MagicMock(status=200, data={}, headers={})
    with (
        patch("app.services.composio.proxy_client._get_composio", return_value=composio),
        patch(
            "app.services.composio.proxy_client.scoped_connected_account_id", return_value="ca_1"
        ),
        patch("app.services.composio.proxy_client.log") as mock_log,
    ):
        proxy_request_sync(_request(CALENDAR_URL))

    assert mock_log.set.call_args.kwargs["composio_proxy"]["endpoint"] == MASKED_URL
    assert composio.tools.proxy.call_args.kwargs["endpoint"] == CALENDAR_URL
