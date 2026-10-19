"""Live, opt-in: every account-identity tool exists at its toolkit's pinned version.

GAIA's Composio client pins toolkit versions, so a profile tool added upstream after
the pin 404s at connect time and the account falls back to a numbered label.
Needs COMPOSIO_KEY; read-only (tool schema lookups, no account).
"""

from composio import Composio
import pytest

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.config.settings import settings

_IDENTITY_TOOLS = [
    pytest.param(integration.composio_config.toolkit_version, tool.tool, id=tool.tool)
    for integration in OAUTH_INTEGRATIONS
    if integration.metadata_config and integration.composio_config
    for tool in integration.metadata_config.tools
]


@pytest.mark.skipif(not settings.COMPOSIO_KEY, reason="COMPOSIO_KEY is not set")
@pytest.mark.parametrize(("toolkit_version", "slug"), _IDENTITY_TOOLS)
def test_an_identity_tool_runs_at_the_pinned_toolkit_version(
    toolkit_version: str | None, slug: str
) -> None:
    client = Composio(api_key=settings.COMPOSIO_KEY).client

    tool = client.tools.retrieve(slug, toolkit_versions=toolkit_version or "latest")

    # fetch_account_identity calls every identity tool with no arguments.
    assert not tool.input_parameters.get("required")
