"""Rewrite bare-name HIL rules on MCP tools to their server-scoped key; --apply writes.

HIL now keys an MCP tool's approval override and never-auto rule as
``mcp:<integration_id>:<mcp_server_name>`` (app/services/hil/tool_key.py), so a
rule stored under the bare tool name no longer applies. For each user, a bare
name that matches exactly one of their connected MCP integrations' stored server
tool names is rewritten to that integration's key. A name matching several is
reported and left for the user to set again. A registry tool name, an already
scoped key and a name no connected server has are left alone.

Dry run by default: prints every rewrite and every ambiguous name. ``--apply``
first copies each affected user's ``hil_preferences`` to a timestamped backup
collection, then writes through the user repository so its cache is evicted.

    cd apps/api && uv run python scripts/migrate_hil_overrides_to_scoped_keys.py [--apply]
"""

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.config.oauth_config import get_integration_by_id
from app.core.provider_registration import register_lazy_providers
from app.db.mongodb.collections import get_async_collection
from app.db.repositories.user_integrations import user_integration_repository
from app.db.repositories.users import user_repository
from app.models.hil_models import HILPreferences
from app.services.hil.tool_key import MCPToolIdentity, hil_tool_key, parse_hil_tool_key

USERS_COLLECTION = "users"
BACKUP_COLLECTION_PREFIX = "users_backup_hil_scoped_keys_"
_RULES_FILTER = {
    "$or": [
        {"hil_preferences.tool_overrides": {"$exists": True, "$ne": {}}},
        {"hil_preferences.never_auto_tools": {"$exists": True, "$ne": []}},
    ]
}


@dataclass(frozen=True)
class KeyPlan:
    """One user's bare keys to rewrite (bare -> scoped), and the ones several servers share."""

    rewrites: dict[str, str]
    ambiguous: dict[str, list[str]]


def plan_keys(
    keys: Iterable[str],
    server_names: Mapping[str, frozenset[str]],
    registry_names: frozenset[str],
) -> KeyPlan:
    """Plan the rewrite of one user's rule keys against their connected MCP servers' tool names."""
    plan = KeyPlan(rewrites={}, ambiguous={})
    for key in dict.fromkeys(keys):
        if key in registry_names or parse_hil_tool_key(key) is not None:
            continue
        owners = sorted(iid for iid, names in server_names.items() if key in names)
        if len(owners) == 1:
            identity = MCPToolIdentity(integration_id=owners[0], server_name=key)
            plan.rewrites[key] = hil_tool_key(key, identity)
        elif owners:
            plan.ambiguous[key] = owners
    return plan


def migrated_rules(prefs: HILPreferences, plan: KeyPlan) -> tuple[dict[str, bool], list[str]]:
    """The user's overrides and never-auto list with the plan applied; a scoped rule already set wins."""
    overrides = {key: ask for key, ask in prefs.tool_overrides.items() if key not in plan.rewrites}
    for bare, scoped in plan.rewrites.items():
        if bare in prefs.tool_overrides:
            overrides.setdefault(scoped, prefs.tool_overrides[bare])
    never_auto = list(dict.fromkeys(plan.rewrites.get(key, key) for key in prefs.never_auto_tools))
    return overrides, never_auto


def _is_mcp_integration(integration_id: str) -> bool:
    """Platform integrations declare it; anything not in the platform config is a custom MCP."""
    platform = get_integration_by_id(integration_id)
    return platform is None or platform.managed_by == "mcp"


async def _connected_server_names(user_id: str) -> dict[str, frozenset[str]]:
    records = await user_integration_repository.tools_for_connected(user_id)
    return {
        record.integration_id: frozenset(tool.name for tool in record.tools)
        for record in records
        if _is_mcp_integration(record.integration_id)
    }


def _registry_names(registry: ToolRegistry, keys: Iterable[str]) -> frozenset[str]:
    return frozenset(key for key in keys if registry.get_tool_meta(key) is not None)


async def main(apply: bool) -> None:
    register_lazy_providers("main_app")
    registry = await get_tool_registry()

    planned: list[tuple[dict[str, object], HILPreferences, KeyPlan]] = []
    async for doc in get_async_collection(USERS_COLLECTION).find(
        _RULES_FILTER, {"_id": 1, "hil_preferences": 1}
    ):
        user_id = str(doc["_id"])
        prefs = HILPreferences(**doc["hil_preferences"])
        keys = [*prefs.tool_overrides, *prefs.never_auto_tools]
        plan = plan_keys(
            keys, await _connected_server_names(user_id), _registry_names(registry, keys)
        )
        for bare, servers in plan.ambiguous.items():
            print(f"  AMBIGUOUS user {user_id}: {bare} is on {', '.join(servers)}; left alone")
        for bare, scoped in plan.rewrites.items():
            print(f"  REWRITE   user {user_id}: {bare} -> {scoped}")
        if plan.rewrites:
            planned.append((doc, prefs, plan))

    print(f"users with rules to rewrite: {len(planned)}")
    if not apply:
        print("dry run: pass --apply to write them")
        return
    if not planned:
        return

    backup_name = f"{BACKUP_COLLECTION_PREFIX}{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    inserted = await get_async_collection(backup_name).insert_many([doc for doc, _, _ in planned])
    if len(inserted.inserted_ids) != len(planned):
        raise SystemExit(
            f"backup wrote {len(inserted.inserted_ids)} of {len(planned)} users to "
            f"{backup_name}; nothing was rewritten"
        )
    print(f"backed up {len(planned)} users' hil_preferences to {backup_name}")

    for doc, prefs, plan in planned:
        overrides, never_auto = migrated_rules(prefs, plan)
        await user_repository.set_hil_preference_fields(
            str(doc["_id"]), tool_overrides=overrides, never_auto_tools=never_auto
        )
    print(f"rewrote {len(planned)} users")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
