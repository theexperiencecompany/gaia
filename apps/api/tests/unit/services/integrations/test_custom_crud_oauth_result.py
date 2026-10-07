"""Regression tests for custom_crud._build_oauth_result log level.

A user-added custom MCP server whose external OAuth server rejects our Dynamic
Client Registration (e.g. 400 "redirect_uri host not in the allowed list") is a
remote-server policy, not a GAIA fault. The failure is already returned to the
user as a failed connection they can retry, so it must be logged at WARNING —
logging it at ERROR forwards it to Sentry (app/config/sentry.py sink forwards
ERROR+) and pages it as a High bug, which is the noise this guards against.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.integrations.custom_crud import _build_oauth_result

INTEGRATION_ID = "89d43eae-d6b4-4bfa-aa9a-90b971af8c03"


@pytest.mark.asyncio
async def test_build_oauth_result_logs_dcr_rejection_as_warning_not_error():
    """A remote DCR rejection is surfaced to the user and logged at WARNING only."""
    mcp_client = MagicMock()
    mcp_client.build_oauth_auth_url = AsyncMock(
        side_effect=ValueError(
            "Dynamic Client Registration failed: Registration failed: 400 "
            '{"error":"invalid_request","error_description":"Invalid redirect_uri: '
            "redirect_uri host 'api.heygaia.io' is not in the allowed list\"}"
        )
    )

    with patch("app.services.integrations.custom_crud.log") as mock_log:
        result = await _build_oauth_result(mcp_client, INTEGRATION_ID)

    # The failure is surfaced to the caller, not swallowed.
    assert result["status"] == "failed"
    assert "discovery failed" in result["error"]

    # It must NOT reach Sentry as an ERROR — warn instead.
    mock_log.error.assert_not_called()
    mock_log.warning.assert_called_once()
    _, kwargs = mock_log.warning.call_args
    assert kwargs["integration_id"] == INTEGRATION_ID
    assert kwargs["error_type"] == "ValueError"
