"""Per-user HIL preferences with a short Redis cache."""

from bson import ObjectId

from app.constants.cache import HIL_PREFS_CACHE_PREFIX, HIL_PREFS_CACHE_TTL
from app.db.mongodb.collections import users_collection
from app.db.redis import delete_cache, get_cache, set_cache
from app.models.hil_models import HILMode, HILPreferences

# Where preferences live on the user document.
_PREFS_FIELD = "hil_preferences"
_MODE_PATH = f"{_PREFS_FIELD}.mode"
_TOOL_OVERRIDES_PATH = f"{_PREFS_FIELD}.tool_overrides"


def _cache_key(user_id: str) -> str:
    return f"{HIL_PREFS_CACHE_PREFIX}{user_id}"


async def get_hil_preferences(user_id: str) -> HILPreferences:
    """Return a user's HIL preferences, reading through a short Redis cache."""
    cached = await get_cache(_cache_key(user_id))
    if cached is not None:
        return HILPreferences(**cached)

    user_doc = await users_collection.find_one({"_id": ObjectId(user_id)}, {_PREFS_FIELD: 1})
    raw = (user_doc or {}).get(_PREFS_FIELD) or {}
    prefs = HILPreferences(**raw)
    await set_cache(_cache_key(user_id), prefs.model_dump(), ttl=HIL_PREFS_CACHE_TTL)
    return prefs


async def update_hil_preferences(
    user_id: str,
    *,
    mode: HILMode | None = None,
    tool_overrides: dict[str, bool] | None = None,
) -> HILPreferences:
    """Apply a partial update to a user's HIL preferences and invalidate the cache."""
    updates: dict[str, object] = {}
    if mode is not None:
        updates[_MODE_PATH] = mode
    if tool_overrides is not None:
        updates[_TOOL_OVERRIDES_PATH] = tool_overrides
    if updates:
        await users_collection.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
        await delete_cache(_cache_key(user_id))
    return await get_hil_preferences(user_id)


async def set_tool_override(user_id: str, tool_name: str, ask: bool | None) -> HILPreferences:
    """Set (``ask`` = True/False) or clear (``ask`` = None) one tool's override.

    Touches only this tool's key, so toggling several tools at once (each switch on the
    integration panel fires its own request) cannot lose an override: a read-modify-write
    of the whole map would have each request overwrite the others' keys with the snapshot
    it read before they landed.

    ``$setField`` in an aggregation-pipeline update rather than a dotted ``$set`` path
    because MCP tool names can contain dots (e.g. ``server.action``), which Mongo would
    split into a nested subdocument, diverging from the flat map the read path expects.
    """
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        [
            {
                "$set": {
                    _TOOL_OVERRIDES_PATH: {
                        "$setField": {
                            "field": {"$literal": tool_name},
                            "input": {"$ifNull": [f"${_TOOL_OVERRIDES_PATH}", {}]},
                            "value": "$$REMOVE" if ask is None else ask,
                        }
                    }
                }
            }
        ],
    )
    await delete_cache(_cache_key(user_id))
    return await get_hil_preferences(user_id)
