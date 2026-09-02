"""Creating an integration from a description of what should back it.

Importing this package registers every author; ``create_integration`` is the
only entry point callers need.
"""

from app.services.integrations.authoring.base import (
    AuthoredIntegration,
    CliBlueprint,
    IntegrationAuthor,
    IntegrationBlueprint,
    McpBlueprint,
    get_author,
    register_author,
)
from app.services.integrations.authoring.cli_author import CliIntegrationAuthor
from app.services.integrations.authoring.mcp_author import McpIntegrationAuthor


async def create_integration(user_id: str, blueprint: IntegrationBlueprint) -> AuthoredIntegration:
    """Create the integration described by ``blueprint``.

    Raises ``ValueError`` for a blueprint kind nothing can author, so a caller
    that grows a new kind fails loudly rather than silently creating nothing.
    """
    author = get_author(blueprint.kind)
    if author is None:
        raise ValueError(f"No author registered for integration kind {blueprint.kind!r}")
    return await author.create(user_id, blueprint)


__all__ = [
    "AuthoredIntegration",
    "CliBlueprint",
    "CliIntegrationAuthor",
    "IntegrationAuthor",
    "IntegrationBlueprint",
    "McpBlueprint",
    "McpIntegrationAuthor",
    "create_integration",
    "get_author",
    "register_author",
]
