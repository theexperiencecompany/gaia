"""The settings surface for "where GAIA texts you first"."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

API = "/api/v1"
USER_ID = "507f1f77bcf86cd799439011"
MODULE = "app.api.v1.endpoints.user"


@pytest.mark.unit
class TestGetChatChannelPriority:
    async def test_returns_the_resolved_order(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{MODULE}.get_chat_channel_priority",
                new_callable=AsyncMock,
                return_value=["slack", "telegram"],
            ) as read,
            patch(f"{MODULE}.log") as log,
        ):
            resp = await client.get(f"{API}/user/chat-channel-priority")
        assert resp.status_code == 200
        assert resp.json() == {"priority": ["slack", "telegram"]}
        read.assert_awaited_once_with(USER_ID)
        log.set.assert_any_call(user={"id": USER_ID}, operation="read_chat_channel_priority")


@pytest.mark.unit
class TestUpdateChatChannelPriority:
    async def test_persists_and_echoes_the_order(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.set_chat_channel_priority", new_callable=AsyncMock) as save,
            patch(f"{MODULE}.log") as log,
        ):
            resp = await client.patch(
                f"{API}/user/chat-channel-priority",
                json={"priority": ["discord", "telegram"]},
            )
        assert resp.status_code == 200
        assert resp.json() == {"priority": ["discord", "telegram"]}
        save.assert_awaited_once_with(USER_ID, ["discord", "telegram"])
        log.set.assert_any_call(user={"id": USER_ID}, operation="update_chat_channel_priority")
        log.audit.assert_called_once_with(
            "chat channel priority updated", actor=USER_ID, priority=["discord", "telegram"]
        )

    async def test_rejects_an_unknown_platform(self, client: AsyncClient) -> None:
        resp = await client.patch(
            f"{API}/user/chat-channel-priority",
            json={"priority": ["sms", "telegram", "carrier-pigeon", "sms"]},
        )
        assert resp.status_code == 422
        # The schema's closed set does the rejecting, so the envelope points at
        # the first offending entry and names what would have been accepted.
        body = resp.json()
        assert body["code"] == "validation_error"
        assert body["errors"][0]["loc"] == ["body", "priority", 0]
        assert body["errors"][0]["type"] == "literal_error"
        assert (
            "'whatsapp', 'telegram', 'discord', 'slack' or 'imessage'" in body["errors"][0]["msg"]
        )

    async def test_rejects_a_non_bot_platform(self, client: AsyncClient) -> None:
        resp = await client.patch(f"{API}/user/chat-channel-priority", json={"priority": ["web"]})
        assert resp.status_code == 422

    async def test_rejects_an_empty_order(self, client: AsyncClient) -> None:
        resp = await client.patch(f"{API}/user/chat-channel-priority", json={"priority": []})
        assert resp.status_code == 422

    async def test_collapses_duplicates(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.user.set_chat_channel_priority",
            new_callable=AsyncMock,
        ) as save:
            resp = await client.patch(
                f"{API}/user/chat-channel-priority",
                json={"priority": ["telegram", "slack", "telegram"]},
            )
        assert resp.status_code == 200
        assert resp.json() == {"priority": ["telegram", "slack"]}
        assert save.await_args.args[1] == ["telegram", "slack"]
