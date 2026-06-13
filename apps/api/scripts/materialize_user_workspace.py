#!/usr/bin/env python3
"""Materialize a user's FS workspace from the built-in skills library.

Usable in dev (run inside the api container against the local JuiceFS
mount) and in prod (same script, same JuiceFS — just pass the real user_id
and the integrations they have connected).

Layout written:

    /workspace/users/<uid>/INDEX.md
    /workspace/users/<uid>/sessions/GUIDE.md
    /workspace/users/<uid>/integrations/GUIDE.md
    /workspace/users/<uid>/integrations/<id>/agent/skills/<slug>/skill.md
    /workspace/users/<uid>/skills/<slug>/skill.md          (executor target)

Connected integrations are normally read from Mongo
(``user_integrations`` collection where status == "connected"); pass
``--connected gmail,googlecalendar`` to override for testing.

Examples:
    # Materialize using Mongo as source of truth (default)
    uv run python scripts/materialize_user_workspace.py 69f6395dc7480ea81ec94f4e

    # Force a specific connected set (no Mongo lookup)
    uv run python scripts/materialize_user_workspace.py <uid> \\
        --connected gmail,googlecalendar,todoist

    # Materialize for every user that has at least one connected integration
    uv run python scripts/materialize_user_workspace.py --all-users
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterable
import sys

from app.agents.workspace.skill_loader import (
    integration_subagent_ids,
    skills_by_subagent,
)
from app.services.storage import (
    JuiceFSUnavailable,
    provision_user_workspace,
)


async def _connected_for(user_id: str) -> set[str]:
    """Connected integration ids from Mongo (status == "connected")."""
    from app.services.integrations.user_integrations import get_connected_integration_ids

    return await get_connected_integration_ids(user_id)


async def _materialize_one(user_id: str, connected_override: set[str] | None) -> None:
    connected = (
        connected_override if connected_override is not None else await _connected_for(user_id)
    )
    # User-level provisioning lays down the system-file symlinks (INDEX/GUIDE)
    # + the full SKILL.md catalog in one hash-gated pass. Soft-fails when the
    # JuiceFS mount is missing.
    try:
        await provision_user_workspace(user_id, connected)
    except JuiceFSUnavailable:
        print(f"[skip] {user_id}: JuiceFS mount unavailable", file=sys.stderr)
        return
    grouped = skills_by_subagent()
    per_iid = {iid: len(grouped.get(iid, [])) for iid in connected if iid in grouped}
    exec_count = len(grouped.get("executor", []))
    print(
        f"[ok] {user_id}: connected={sorted(connected)} "
        f"per_integration_skills={per_iid} executor_skills={exec_count}"
    )


async def _all_users() -> Iterable[str]:
    """Every user that owns at least one connected integration in Mongo."""
    from app.db.mongodb.collections import user_integrations_collection

    return {
        doc["user_id"]
        async for doc in user_integrations_collection.find({"status": "connected"}, {"user_id": 1})
        if doc.get("user_id")
    }


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_id", nargs="?", help="Target user id")
    parser.add_argument(
        "--connected",
        help="Comma-separated integration ids to materialize (default: read from Mongo).",
    )
    parser.add_argument(
        "--all-users",
        action="store_true",
        help="Materialize for every user with at least one connected integration.",
    )
    parser.add_argument(
        "--list-targets",
        action="store_true",
        help="Print the integrations the SKILL.md library targets and exit.",
    )
    args = parser.parse_args()

    if args.list_targets:
        for iid in integration_subagent_ids():
            print(iid)
        return

    connected_override: set[str] | None = None
    if args.connected:
        connected_override = {p.strip() for p in args.connected.split(",") if p.strip()}

    if args.all_users:
        users = await _all_users()
        for uid in sorted(users):
            await _materialize_one(uid, connected_override)
        return

    if not args.user_id:
        parser.error("user_id is required unless --all-users or --list-targets is set")
    await _materialize_one(args.user_id, connected_override)


if __name__ == "__main__":
    asyncio.run(_main())
