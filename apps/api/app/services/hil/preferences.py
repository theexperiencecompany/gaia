"""Per-user HIL preferences with a short Redis cache."""

from bson import ObjectId

from app.constants.cache import HIL_PREFS_CACHE_PREFIX, HIL_PREFS_CACHE_TTL
from app.db.mongodb.collections import users_collection
from app.db.redis import delete_cache, get_cache, set_cache
from app.models.hil_models import HILPreferences


def _cache_key(user_id: str) -> str:
    return f"{HIL_PREFS_CACHE_PREFIX}{user_id}"


async def get_hil_preferences(user_id: str) -> HILPreferences:
    """Return a user's HIL preferences, reading through a short Redis cache."""
    cached = await get_cache(_cache_key(user_id))
    if cached is not None:
        return HILPreferences(**cached)

    user_doc = await users_collection.find_one({"_id": ObjectId(user_id)}, {"hil_preferences": 1})
    raw = (user_doc or {}).get("hil_preferences") or {}
    # Legacy self-heal: fold a pre-override ``always_allowed_tools`` allow-list into
    # the ``tool_overrides`` map (each becomes "never ask"). HIL is unlaunched, so
    # this only ever touches dev docs; extra keys are ignored by the model.
    if "tool_overrides" not in raw and "always_allowed_tools" in raw:
        raw = {**raw, "tool_overrides": dict.fromkeys(raw["always_allowed_tools"] or [], False)}
    prefs = HILPreferences(**raw)
    await set_cache(_cache_key(user_id), prefs.model_dump(), ttl=HIL_PREFS_CACHE_TTL)
    return prefs


async def update_hil_preferences(
    user_id: str,
    *,
    enabled: bool | None = None,
    tool_overrides: dict[str, bool] | None = None,
) -> HILPreferences:
    """Apply a partial update to a user's HIL preferences and invalidate the cache."""
    updates: dict[str, object] = {}
    if enabled is not None:
        updates["hil_preferences.enabled"] = enabled
    if tool_overrides is not None:
        updates["hil_preferences.tool_overrides"] = tool_overrides
    if updates:
        await users_collection.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
        await delete_cache(_cache_key(user_id))
    return await get_hil_preferences(user_id)


async def set_tool_override(user_id: str, tool_name: str, ask: bool | None) -> None:
    """Set (``ask`` = True/False) or clear (``ask`` = None) one tool's override.

    Writes the whole ``tool_overrides`` map rather than a dotted field path: MCP
    tool names can contain dots (e.g. ``server.action``), which Mongo would split
    into a nested subdocument on a dotted ``$set`` path, diverging from the flat
    map the read path expects.
    """
    prefs = await get_hil_preferences(user_id)
    overrides = dict(prefs.tool_overrides)
    if ask is None:
        overrides.pop(tool_name, None)
    else:
        overrides[tool_name] = ask
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"hil_preferences.tool_overrides": overrides}},
    )
    await delete_cache(_cache_key(user_id))
