"""Trash routes against the Composio envelope, which has no top-level message id.

The routes used to read msg["id"] off it and returned 500 on every call.
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.models.mail_models import GmailToolResult

MAIL_BASE = "/api/v1"

pytestmark = [
    pytest.mark.usefixtures("_bypass_integration_check"),
]


class TestTrashRoutesAgainstTheComposioEnvelope:
    @pytest.mark.regression
    @pytest.mark.parametrize(
        ("path", "tool_name", "field"),
        [
            ("/gmail/trash", "GMAIL_TRASH_MESSAGE", "trashed"),
            ("/gmail/untrash", "GMAIL_UNTRASH_MESSAGE", "restored"),
        ],
    )
    async def test_a_successful_envelope_reports_the_requested_ids(
        self, path: str, tool_name: str, field: str, client: AsyncClient
    ):
        envelope = GmailToolResult(successful=True, data={"labelIds": ["TRASH"]})
        with patch(
            "app.services.mail.mail_service.invoke_gmail_tool",
            new_callable=AsyncMock,
            return_value=envelope,
        ) as invoke:
            response = await client.post(
                f"{MAIL_BASE}{path}", json={"message_ids": ["msg-1", "msg-2"]}
            )

        assert response.status_code == 200, response.text
        assert response.json()["success"] is True
        assert response.json()[field] == ["msg-1", "msg-2"]
        assert [c.args[1] for c in invoke.await_args_list] == [tool_name, tool_name]
