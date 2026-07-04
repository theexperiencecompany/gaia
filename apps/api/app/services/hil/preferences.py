"""Per-user HIL preferences with a short Redis cache."""

from bson import ObjectId

from app.constants.cache import HIL_PREFS_CACHE_PREFIX, HIL_PREFS_CACHE_TTL
from app.db.mongodb.collections import users_collection
from app.db.redis import delete_cache, get_cache, set_cache
from app.models.hil_models import HILPreferences


def _cache_key(user_id: str) -> str:
    return f"{HIL_PREFS_CACHE_PREFIX}{user_id}"


async def get_hil_preferences(user_id: str) -> HILPreferences:
    cached = await get_cache(_cache_key(user_id))
    if cached is not None:
        return HILPreferences(**cached)

    user_doc = await users_collection.find_one(
        {"_id": ObjectId(user_id)}, {"hil_preferences": 1}
    )
    prefs = HILPreferences(**((user_doc or {}).get("hil_preferences") or {}))
    await set_cache(_cache_key(user_id), prefs.model_dump(), ttl=HIL_PREFS_CACHE_TTL)
    return prefs


async def update_hil_preferences(
    user_id: str,
    *,
    enabled: bool | None = None,
    always_allowed_tools: list[str] | None = None,
) -> HILPreferences:
    updates: dict[str, object] = {}
    if enabled is not None:
        updates["hil_preferences.enabled"] = enabled
    if always_allowed_tools is not None:
        updates["hil_preferences.always_allowed_tools"] = always_allowed_tools
    if updates:
        await users_collection.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
        await delete_cache(_cache_key(user_id))
    return await get_hil_preferences(user_id)


async def add_always_allowed_tool(user_id: str, tool_name: str) -> None:
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$addToSet": {"hil_preferences.always_allowed_tools": tool_name}},
    )
    await delete_cache(_cache_key(user_id))
