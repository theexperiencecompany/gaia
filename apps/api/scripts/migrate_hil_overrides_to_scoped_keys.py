"""Rewrite bare-name HIL rules on MCP tools to their server-scoped key; --apply writes.

HIL now keys an MCP tool's approval override and never-auto rule as
``mcp:<integration_id>:<mcp_server_name>`` (app/services/hil/tool_key.py), so a
rule stored under the bare tool name no longer applies. For each user, a bare
name that matches exactly one of their connected MCP integrations' stored server
tool names is rewritten to that integration's key. A name matching several is
reported and left for the user to set again. A name a stored list only holds as
master's rename (``posthog_execute`` for ``execute``) is reported and left alone:
the server's own name is not known from it, and a key built from the rename is
one the gate never reads. A registry tool from a no-auth
platform MCP (deepwiki, ...) keeps its server identity, so its bare name moves to
its scoped key too. Any other registry tool name, an already scoped key and a
name no connected server has are left alone. Run restore_mcp_server_tool_names.py
first so those lists hold the server's own names.

Dry run by default: prints every rewrite and every ambiguous name. ``--apply``
first copies each affected user's ``hil_preferences`` to a timestamped backup
collection, then writes through the user repository so its cache is evicted.

    cd apps/api && uv run python scripts/migrate_hil_overrides_to_scoped_keys.py [--apply]
"""

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.config.oauth_config import get_integration_by_id
from app.core.provider_registration import register_lazy_providers
from app.db.mongodb.collections import get_async_collection
from app.db.repositories.users import user_repository
from app.models.hil_models import HILPreferences
from app.services.hil.tool_key import (
    MCPToolIdentity,
    hil_tool_key,
    mcp_tool_identity,
    parse_hil_tool_key,
)
from app.services.integrations.user_integrations import connected_tool_records
from app.services.mcp.tool_naming import master_rename

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
    """One user's bare keys to rewrite (bare -> scoped), the ones several servers share, and the ones only master's rename names."""

    rewrites: dict[str, str]
    ambiguous: dict[str, list[str]]
    unverified: dict[str, list[str]] = field(default_factory=dict)


def plan_keys(
    keys: Iterable[str],
    server_names: Mapping[str, frozenset[str]],
    registry_keys: Mapping[str, str],
    master_renamed: Mapping[str, frozenset[str]] | None = None,
) -> KeyPlan:
    """Plan the rewrite of one user's rule keys.

    registry_keys maps a registry tool name to its gate key; master_renamed maps an
    integration to the stored names that are master's renames, not the server's.
    """
    plan = KeyPlan(rewrites={}, ambiguous={})
    for key in dict.fromkeys(keys):
        if key in registry_keys:
            if registry_keys[key] != key:
                plan.rewrites[key] = registry_keys[key]
            continue
        if parse_hil_tool_key(key) is not None:
            continue
        owners = sorted(iid for iid, names in server_names.items() if key in names)
        renamed_on = sorted(iid for iid, names in (master_renamed or {}).items() if key in names)
        if renamed_on:
            plan.unverified[key] = renamed_on
        elif len(owners) == 1:
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


async def _connected_tool_names(
    user_id: str,
) -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """The user's connected MCP integrations' stored names: (the server's own, master's renames)."""
    server_names: dict[str, frozenset[str]] = {}
    master_renamed: dict[str, frozenset[str]] = {}
    for record in await connected_tool_records(user_id):
        if not _is_mcp_integration(record.integration_id):
            continue
        renamed = {tool.name for tool in record.tools if master_rename(tool) is not None}
        server_names[record.integration_id] = frozenset(
            tool.name for tool in record.tools if tool.name not in renamed
        )
        if renamed:
            master_renamed[record.integration_id] = frozenset(renamed)
    return server_names, master_renamed


def _registry_keys(registry: ToolRegistry, keys: Iterable[str]) -> dict[str, str]:
    return {
        key: hil_tool_key(key, mcp_tool_identity(meta.tool))
        for key in keys
        if (meta := registry.get_tool_meta(key)) is not None
    }


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
        server_names, master_renamed = await _connected_tool_names(user_id)
        plan = plan_keys(keys, server_names, _registry_keys(registry, keys), master_renamed)
        for bare, servers in plan.ambiguous.items():
            print(f"  AMBIGUOUS user {user_id}: {bare} is on {', '.join(servers)}; left alone")
        for bare, servers in plan.unverified.items():
            print(
                f"  UNVERIFIED user {user_id}: {bare} is master's rename on {', '.join(servers)}; "
                "left alone (run restore_mcp_server_tool_names.py --apply, then this again)"
            )
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
