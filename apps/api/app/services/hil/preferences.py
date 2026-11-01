"""Per-user HIL preferences, read through the user repository's entity cache."""

import asyncio

from app.agents.tools.core.registry import get_tool_registry
from app.db.repositories.users import user_repository
from app.models.hil_models import HILMode, HILPreferences
from app.schemas.hil_schemas import HILToolKeyLabel
from app.services.analytics_service import capture
from app.services.hil.tool_key import parse_hil_tool_key
from app.services.integrations.integration_resolver import IntegrationResolver
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import SettingsPreferencesChanged


async def get_hil_preferences(user_id: str) -> HILPreferences:
    """Return a user's HIL preferences (defaults when unset or the user is gone)."""
    user = await user_repository.get(user_id)
    return HILPreferences(**((user.hil_preferences if user else None) or {}))


async def update_hil_preferences(
    user_id: str,
    *,
    mode: HILMode | None = None,
    tool_overrides: dict[str, bool] | None = None,
    never_auto_tools: list[str] | None = None,
) -> HILPreferences:
    """Apply a partial update to a user's HIL preferences."""
    await user_repository.set_hil_preference_fields(
        user_id, mode=mode, tool_overrides=tool_overrides, never_auto_tools=never_auto_tools
    )
    prefs = await get_hil_preferences(user_id)

    # A mode change is the user-facing milestone; per-tool changes flow through
    # set_tool_override, which captures its own event.
    if mode is not None:
        capture(UserId(user_id), SettingsPreferencesChanged(setting="hil_approvals", mode=mode))
    return prefs


async def set_tool_override(user_id: str, tool_name: str, ask: bool | None) -> HILPreferences:
    """Set (ask = True/False) or clear (ask = None) one tool's override."""
    await user_repository.set_hil_tool_override(user_id, tool_name, ask)
    capture(
        UserId(user_id),
        SettingsPreferencesChanged(
            setting="tool_approval", tool_name=tool_name, require_approval=ask is True
        ),
    )
    return await get_hil_preferences(user_id)


async def tool_key_labels(prefs: HILPreferences) -> dict[str, HILToolKeyLabel]:
    """Label every key the user has a rule on with its integration and tool name."""
    keys = {*prefs.tool_overrides, *prefs.never_auto_tools}
    mcp_tools = {key: parse_hil_tool_key(key) for key in keys}
    integration_ids = sorted({tool.integration_id for tool in mcp_tools.values() if tool})
    resolved = await asyncio.gather(*map(IntegrationResolver.resolve, integration_ids))
    integration_names = {
        integration_id: integration.name if integration else None
        for integration_id, integration in zip(integration_ids, resolved, strict=True)
    }
    registry = await get_tool_registry()
    labels: dict[str, HILToolKeyLabel] = {}
    for key, mcp_tool in mcp_tools.items():
        if mcp_tool is not None:
            labels[key] = HILToolKeyLabel(
                integration_name=integration_names[mcp_tool.integration_id],
                tool_name=mcp_tool.server_name,
            )
            continue
        category = registry.get_category(registry.get_category_of_tool(key))
        labels[key] = HILToolKeyLabel(
            integration_name=category.integration_name if category else None, tool_name=key
        )
    return labels
