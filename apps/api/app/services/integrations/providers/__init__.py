"""Integration transports, registered once at import.

Importing this package is what makes a transport reachable; the dispatch looks
providers up by ``managed_by`` and never names them individually.
"""

from app.services.integrations.providers.base import (
    ConnectContext,
    IntegrationProvider,
    get_provider,
    register_provider,
)
from app.services.integrations.providers.cli_provider import CliIntegrationProvider
from app.services.integrations.providers.oauth_providers import (
    ComposioIntegrationProvider,
    McpIntegrationProvider,
    SelfIntegrationProvider,
)

for _provider in (
    McpIntegrationProvider(),
    ComposioIntegrationProvider(),
    SelfIntegrationProvider(),
    CliIntegrationProvider(),
):
    register_provider(_provider)

__all__ = [
    "CliIntegrationProvider",
    "ComposioIntegrationProvider",
    "ConnectContext",
    "IntegrationProvider",
    "McpIntegrationProvider",
    "SelfIntegrationProvider",
    "get_provider",
    "register_provider",
]
