#!/usr/bin/env python3
"""Remove what a retired built-in integration leaves behind.

Deleting an integration from OAUTH_INTEGRATIONS (browserbase, PR #876) does not
touch the data written while it existed:

- user_integrations rows, which keep listing it as connected;
- a tools-only stub in integrations, written by store_tools, holding only
  {integration_id, tools}. Resolving the id no longer finds a catalog entry, so
  it falls through to that stub, which fails strict Integration validation.

For each retired id this deletes both, then busts the per-user integration caches
and the global MCP tool roll-up so nothing keeps serving the old state. Only a
tools-only stub is ever deleted from integrations: a full Integration document
with the same id is left alone. An id still in OAUTH_INTEGRATIONS, or still backed by a full integration
document, is refused before anything is read or deleted.

The dry run also lists every tools-only stub whose id is not in OAUTH_INTEGRATIONS
at all, with the user rows pointing at it, so every retirement leftover shows up in
one report. That listing is report-only; only the ids named on the command line are
deleted.

Idempotent: a second run finds nothing. Dry run by default; nothing is deleted
without ``--apply``.

Usage::

    cd apps/api
    uv run python -m app.scripts.purge_retired_integrations                  # report only
    uv run python -m app.scripts.purge_retired_integrations --apply
    uv run python -m app.scripts.purge_retired_integrations --retired-ids a b --apply
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from app.config.oauth_config import get_integration_by_id
from app.db.repositories.integrations import integration_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.services.integrations.user_integrations import invalidate_user_integration_caches
from app.services.mcp.mcp_tools_service import invalidate_mcp_tools_cache

DEFAULT_RETIRED_IDS = ["browserbase"]


@dataclass(frozen=True)
class RetiredIntegration:
    """What one retired id still has in the database."""

    integration_id: str
    user_ids: list[str]
    has_stub: bool


@dataclass(frozen=True)
class OrphanStub:
    """A tools-only stub whose id is no longer in OAUTH_INTEGRATIONS."""

    integration_id: str
    user_count: int


async def require_retired(integration_ids: Sequence[str]) -> None:
    """Refuse an id that is still live, since deleting its user rows would disconnect users.

    Live means still in OAUTH_INTEGRATIONS, or still backed by a full integration document.
    """
    in_catalog = [i for i in integration_ids if get_integration_by_id(i) is not None]
    if in_catalog:
        raise ValueError(f"still in OAUTH_INTEGRATIONS, not retired: {', '.join(in_catalog)}")
    documented = await integration_repository.full_document_ids(list(integration_ids))
    if documented:
        raise ValueError(
            f"still have a full integration document, not retired: {', '.join(documented)}"
        )


async def plan_retired(integration_id: str) -> RetiredIntegration:
    """Read the rows and stub that a retired id left behind."""
    return RetiredIntegration(
        integration_id=integration_id,
        user_ids=await user_integration_repository.user_ids_with_integration(integration_id),
        has_stub=integration_id in await integration_repository.tools_stub_ids(),
    )


async def find_orphan_stubs() -> list[OrphanStub]:
    """Every tools-only stub whose id is not in OAUTH_INTEGRATIONS, with its user-row count."""
    orphans: list[OrphanStub] = []
    for integration_id in sorted(await integration_repository.tools_stub_ids()):
        if get_integration_by_id(integration_id) is not None:
            continue
        user_ids = await user_integration_repository.user_ids_with_integration(integration_id)
        orphans.append(OrphanStub(integration_id, len(user_ids)))
    return orphans


async def purge(plan: RetiredIntegration) -> tuple[int, bool]:
    """Delete the plan's rows and stub, bust the caches they fed; return (rows, stub deleted)."""
    rows = 0
    for user_id in plan.user_ids:
        rows += await user_integration_repository.delete_for_user(user_id, plan.integration_id)
        await invalidate_user_integration_caches(user_id)
    stub_deleted = await integration_repository.delete_tools_stub(plan.integration_id)
    if stub_deleted:
        await invalidate_mcp_tools_cache()
    return rows, stub_deleted


async def _run(args: argparse.Namespace) -> None:
    await require_retired(args.retired_ids)

    for integration_id in args.retired_ids:
        plan = await plan_retired(integration_id)
        print(
            f"{integration_id}: {len(plan.user_ids)} user row(s), "
            f"tools-only stub: {'yes' if plan.has_stub else 'no'}"
        )
        if args.apply:
            rows, stub_deleted = await purge(plan)
            print(f"  deleted {rows} user row(s), stub deleted: {'yes' if stub_deleted else 'no'}")

    orphans = await find_orphan_stubs()
    print(f"\ntools-only stubs outside OAUTH_INTEGRATIONS: {len(orphans)}")
    for orphan in orphans:
        print(f"  {orphan.integration_id}: {orphan.user_count} user row(s)")

    if not args.apply:
        print("\ndry run: nothing deleted. Re-run with --apply.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Delete; default is report-only.")
    parser.add_argument(
        "--retired-ids",
        nargs="+",
        default=DEFAULT_RETIRED_IDS,
        metavar="ID",
        help="Integration ids removed from OAUTH_INTEGRATIONS (default: %(default)s).",
    )
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
