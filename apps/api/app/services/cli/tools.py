"""Which integrations are CLI-backed, wherever they were defined.

An integration is CLI-backed when it carries a :class:`CliConfig`: platform
ones declare it in ``oauth_config``, user-created ones carry it on their Mongo
document. Both answer the same two questions the tool builder needs — which
executable is this, and what is the product called — so callers resolve through
here instead of reading two catalogs and branching on where the integration was
defined. ``cli_config`` (not ``managed_by``) is the discriminator, matching the
rest of this subsystem: the connect provider and the resolver both key off the
spec being present, so a document that has one always behaves as a CLI.

Whether a *user* may reach the tool is a separate question and deliberately not
answered here. The tool is user-agnostic by construction — it resolves the
sandbox and the credentials from the run's user at call time — so one tool
serves everyone, and the only per-user fact left is the connection status the
connect flow records.
"""

from dataclasses import dataclass

from app.constants.cli_integrations import cli_tool_name
from app.models.cli_config import CliConfig
from app.services.integrations.integration_resolver import IntegrationResolver


@dataclass(frozen=True, slots=True)
class CliIntegration:
    """A CLI-backed integration: everything needed to build and name its tool."""

    id: str
    name: str
    config: CliConfig
    # Platform integrations are curated and their ids are unique, so their tool
    # keeps the clean name; custom ones are per-user documents sharing one
    # process-global registry and need disambiguating.
    is_platform: bool

    @property
    def tool_name(self) -> str:
        """The registry name of this integration's tool."""
        return cli_tool_name(self.config.command, self.id, is_platform=self.is_platform)


async def resolve_cli_integration(integration_id: str) -> CliIntegration | None:
    """The CLI integration behind ``integration_id``, platform or custom.

    ``None`` means "not CLI-backed" — an MCP server, a Composio toolkit, or no
    such integration — which is what lets a caller dispatch on transport
    without knowing which catalog the integration came from.
    """
    resolved = await IntegrationResolver.resolve(integration_id)
    if resolved is None or resolved.cli_config is None:
        return None
    return CliIntegration(
        id=resolved.integration_id,
        name=resolved.name,
        config=resolved.cli_config,
        is_platform=resolved.source == "platform",
    )
