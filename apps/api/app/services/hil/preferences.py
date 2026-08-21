"""Per-user HIL preferences, read through the user repository's entity cache."""

from app.db.repositories.users import user_repository
from app.models.hil_models import HILMode, HILPreferences
from app.services.analytics_service import AnalyticsEvents, capture_event


async def get_hil_preferences(user_id: str) -> HILPreferences:
    """Return a user's HIL preferences (defaults when unset or the user is gone)."""
    user = await user_repository.get(user_id)
    return HILPreferences(**((user.hil_preferences if user else None) or {}))


async def update_hil_preferences(
    user_id: str,
    *,
    mode: HILMode | None = None,
    tool_overrides: dict[str, bool] | None = None,
) -> HILPreferences:
    """Apply a partial update to a user's HIL preferences."""
    await user_repository.set_hil_preference_fields(
        user_id, mode=mode, tool_overrides=tool_overrides
    )
    prefs = await get_hil_preferences(user_id)

    # A mode change is the user-facing milestone; per-tool changes flow through
    # set_tool_override, which captures its own event.
    if mode is not None:
        capture_event(
            user_id,
            AnalyticsEvents.SETTINGS_PREFERENCES_CHANGED,
            {"setting": "hil_approvals", "mode": mode},
        )
    return prefs


async def set_tool_override(user_id: str, tool_name: str, ask: bool | None) -> HILPreferences:
    """Set (``ask`` = True/False) or clear (``ask`` = None) one tool's override."""
    await user_repository.set_hil_tool_override(user_id, tool_name, ask)
    capture_event(
        user_id,
        AnalyticsEvents.SETTINGS_PREFERENCES_CHANGED,
        {
            "setting": "tool_approval",
            "tool_name": tool_name,
            "require_approval": ask is True,
        },
    )
    return await get_hil_preferences(user_id)
