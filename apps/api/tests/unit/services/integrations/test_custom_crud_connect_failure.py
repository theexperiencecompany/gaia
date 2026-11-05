"""A custom MCP server that fails to connect is answered to its owner and warned on the server."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.models.integration_models import CreateCustomIntegrationRequest
from app.services.integrations.custom_crud import create_and_connect_custom_integration

INTEGRATION_ID = "custom-mcp-1"
REFUSED = "Connection refused by https://mcp.example.com"


def _integration() -> MagicMock:
    integration = MagicMock()
    integration.integration_id = INTEGRATION_ID
    return integration


@pytest.mark.parametrize(
    ("bearer_token", "probe", "connect", "error_type"),
    [
        ("secret", None, ConnectionError(REFUSED), "ConnectionError"),
        (None, {"error": REFUSED}, None, None),
        (None, {"requires_auth": False}, ConnectionError(REFUSED), "ConnectionError"),
    ],
    ids=["bearer-connect", "probe", "no-auth-connect"],
)
async def test_a_failed_connect_is_answered_and_warned_with_the_servers_error(
    bearer_token: str | None,
    probe: dict[str, object] | None,
    connect: Exception | None,
    error_type: str | None,
) -> None:
    mcp_client = MagicMock()
    mcp_client.probe_connection = AsyncMock(return_value=probe)
    mcp_client.connect = AsyncMock(side_effect=connect)
    request = CreateCustomIntegrationRequest(
        name="Mine", server_url="https://mcp.example.com", bearer_token=bearer_token
    )
    module = "app.services.integrations.custom_crud"
    with (
        patch(f"{module}._fetch_icon_safely", AsyncMock(return_value=None)),
        patch(f"{module}.create_custom_integration", AsyncMock(return_value=_integration())),
        patch(
            f"{module}._get_integration", AsyncMock(return_value=_integration())
        ) as get_integration,
        patch(f"{module}.MCPTokenStore", MagicMock(return_value=AsyncMock())),
        patch(f"{module}.log") as log,
    ):
        _, result = await create_and_connect_custom_integration("user-1", request, mcp_client)

    assert result == {"status": "failed", "error": REFUSED}
    log.error.assert_not_called()
    log.warning.assert_called_once_with(
        f"{LogTag.INTEGRATION} Custom integration connect failed",
        error=REFUSED,
        error_type=error_type,
        integration_id=INTEGRATION_ID,
    )
    log.set.assert_any_call(integration={"id": INTEGRATION_ID, "status": "error"})
    if bearer_token:
        get_integration.assert_awaited_once_with(INTEGRATION_ID)
