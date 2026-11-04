from unittest.mock import AsyncMock, patch

from app.models.integration_models import IntegrationToolsRecord
from app.services.integrations.user_integrations import connected_tool_records

_MOD = "app.services.integrations.user_integrations"


class TestConnectedToolRecords:
    async def test_returns_the_stored_lists_of_exactly_the_connected_integrations(self) -> None:
        records = [IntegrationToolsRecord(integration_id="posthog", tools=[])]
        tools_by_ids = AsyncMock(return_value=records)
        connected = AsyncMock(return_value={"posthog"})

        with (
            patch(f"{_MOD}.get_connected_integration_ids", new=connected),
            patch(f"{_MOD}.integration_repository.tools_by_ids", new=tools_by_ids),
        ):
            result = await connected_tool_records("user1")

        assert result == records
        connected.assert_awaited_once_with("user1")
        tools_by_ids.assert_awaited_once_with({"posthog"})

    async def test_reads_nothing_when_the_user_is_connected_to_nothing(self) -> None:
        tools_by_ids = AsyncMock()

        with (
            patch(f"{_MOD}.get_connected_integration_ids", new=AsyncMock(return_value=set())),
            patch(f"{_MOD}.integration_repository.tools_by_ids", new=tools_by_ids),
        ):
            result = await connected_tool_records("user1")

        assert result == []
        tools_by_ids.assert_not_awaited()
