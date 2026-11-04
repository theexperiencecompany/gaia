"""Per-user HIL preferences, read through the user repository's entity cache."""

from collections.abc import Iterable
from http import HTTPStatus

from app.db.repositories.users import user_repository
from app.models.hil_models import HILMode, HILPreferences
from app.services.analytics_service import capture
from app.services.hil.tool_key import parse_hil_tool_key
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import SettingsPreferencesChanged


class MalformedToolKeyError(AppError):
    """Raised (422) when a preference rule is keyed by a malformed server-scoped tool key."""

    def __init__(self, key: str) -> None:
        super().__init__(
            message="Malformed tool key",
            why="A server-scoped key reads mcp:<integration_id>:<tool name>.",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            meta={"key": key},
        )


def _require_well_formed(keys: Iterable[str]) -> None:
    """Refuse a key every later read of the preferences would raise on."""
    for key in keys:
        try:
            parse_hil_tool_key(key)
        except ValueError as e:
            raise MalformedToolKeyError(key) from e


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
    _require_well_formed([*(tool_overrides or {}), *(never_auto_tools or [])])
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
    _require_well_formed([tool_name])
    await user_repository.set_hil_tool_override(user_id, tool_name, ask)
    capture(
        UserId(user_id),
        SettingsPreferencesChanged(
            setting="tool_approval", tool_name=tool_name, require_approval=ask is True
        ),
    )
    return await get_hil_preferences(user_id)
