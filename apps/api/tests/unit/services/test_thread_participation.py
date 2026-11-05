"""Whether the user wrote in a Gmail thread, read at Composio's proxy boundary."""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.mail.thread_participation import user_wrote_in_thread
from app.utils.errors import AppError
from tests.integration_account_factories import (
    make_integration_account,
    make_integration_record,
    provider_account_id,
)

pytestmark = pytest.mark.unit

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
_MOD = "app.services.mail.thread_participation"


@pytest.fixture
def composio() -> Iterator[SimpleNamespace]:
    client = MagicMock()
    record = make_integration_record(
        make_integration_account("ca_1"), make_integration_account("ca_2"), user_id=USER_ID
    )
    with (
        patch("app.services.composio.proxy_client._get_composio", return_value=client),
        patch(f"{_MOD}.get_account_record", AsyncMock(return_value=record)),
    ):
        yield SimpleNamespace(proxy=client.tools.proxy)


def _thread(*labels: list[str]) -> SimpleNamespace:
    messages = [{"id": f"m{i}", "labelIds": ids} for i, ids in enumerate(labels, start=1)]
    return SimpleNamespace(status=200, data={"id": "t1", "messages": messages}, headers={})


async def _wrote(message_id: str = "m3", account_id: str | None = "ca_2") -> bool:
    return await user_wrote_in_thread(USER_ID, "t1", message_id=message_id, account_id=account_id)


async def test_a_thread_with_a_message_the_user_sent_is_one_they_wrote_in(
    composio: SimpleNamespace,
) -> None:
    composio.proxy.return_value = _thread(["INBOX"], ["SENT"], ["INBOX", "UNREAD"])

    assert await _wrote() is True


async def test_a_thread_of_only_incoming_reports_is_not(composio: SimpleNamespace) -> None:
    composio.proxy.return_value = _thread(["INBOX"], ["INBOX"], ["INBOX", "UNREAD"])

    assert await _wrote() is False


async def test_the_message_that_fired_never_counts_for_itself(composio: SimpleNamespace) -> None:
    # The user's own message to a thread of reports, mailed back into the inbox.
    composio.proxy.return_value = _thread(["INBOX"], ["INBOX"], ["SENT", "INBOX"])

    assert await _wrote(message_id="m3") is False


async def test_it_reads_the_account_the_event_arrived_on(composio: SimpleNamespace) -> None:
    composio.proxy.return_value = _thread(["INBOX"])

    await _wrote(account_id="ca_2")

    kwargs = composio.proxy.call_args.kwargs
    assert kwargs["connected_account_id"] == provider_account_id("ca_2")
    assert kwargs["endpoint"].endswith("/users/me/threads/t1")
    assert {"name": "format", "type": "query", "value": "minimal"} in kwargs["parameters"]


async def test_an_account_the_user_no_longer_has_raises(composio: SimpleNamespace) -> None:
    with pytest.raises(LookupError, match="ca_gone"):
        await _wrote(account_id="ca_gone")

    composio.proxy.assert_not_called()


async def test_a_gmail_error_raises_rather_than_reading_as_no(composio: SimpleNamespace) -> None:
    composio.proxy.return_value = SimpleNamespace(status=404, data={"error": "x"}, headers={})

    with pytest.raises(AppError):
        await _wrote()
