#!/usr/bin/env python3
"""One-time, idempotent backfill: arm Gmail's sent-mail trigger for users who connected before it existed.

A new Gmail connection gets GMAIL_EMAIL_SENT_TRIGGER from handle_subscribe_trigger;
this runs that same call for every ACTIVE Gmail account under GAIA's auth config
whose active trigger instances do not already include it, so a re-run is a no-op.

Run from the api directory (or /app inside the container):

    python scripts/backfill_gmail_sent_trigger.py --dry-run
    python scripts/backfill_gmail_sent_trigger.py --execute

--dry-run  Report the users who would get the trigger. Default.
--execute  Actually create the trigger instances. Required to write anything.
--limit N  Only list the first N users in the report (the totals stay complete).
"""

import argparse
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Final

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.oauth_config import get_integration_by_id
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.triggers import GMAIL_EMAIL_SENT_COMPOSIO_SLUG
from app.models.trigger_config import TriggerConfig
from app.services.composio.composio_service import (
    ComposioService,
    get_composio_service,
    init_composio_service,
)

_PAGE_SIZE: Final = 100
_ACTIVE: Final = "ACTIVE"


@dataclass
class BackfillResult:
    dry_run: bool
    pending_user_ids: list[str]
    already_armed: int
    armed_user_ids: list[str] = field(default_factory=list)
    #: handle_subscribe_trigger answered None — Composio refused the create.
    failed_user_ids: list[str] = field(default_factory=list)


def _gmail_sent_target() -> tuple[str, TriggerConfig]:
    """Return GAIA's Gmail auth config id and the sent-mail trigger connect arms."""
    gmail = get_integration_by_id(GMAIL_INTEGRATION_ID)
    if gmail is None or gmail.composio_config is None:
        raise RuntimeError("The Gmail integration has no Composio config to backfill against")
    for trigger in gmail.associated_triggers:
        if trigger.slug == GMAIL_EMAIL_SENT_COMPOSIO_SLUG:
            return gmail.composio_config.auth_config_id, trigger
    raise RuntimeError(f"{GMAIL_EMAIL_SENT_COMPOSIO_SLUG} is not in the Gmail trigger catalog")


async def _active_account_user_ids(service: ComposioService, auth_config_id: str) -> set[str]:
    user_ids: set[str] = set()
    cursor: str | None = None
    while True:
        page = await asyncio.to_thread(
            service.composio.connected_accounts.list,
            auth_config_ids=[auth_config_id],
            statuses=[_ACTIVE],
            cursor=cursor,
            limit=_PAGE_SIZE,
        )
        user_ids.update(account.user_id for account in page.items)
        cursor = page.next_cursor
        if not cursor:
            return user_ids


async def _armed_user_ids(service: ComposioService, auth_config_id: str) -> set[str]:
    user_ids: set[str] = set()
    cursor: str | None = None
    while True:
        page = await asyncio.to_thread(
            service.composio.triggers.list_active,
            trigger_names=[GMAIL_EMAIL_SENT_COMPOSIO_SLUG],
            auth_config_ids=[auth_config_id],
            cursor=cursor,
            limit=_PAGE_SIZE,
        )
        user_ids.update(instance.user_id for instance in page.items)
        cursor = page.next_cursor
        if not cursor:
            return user_ids


async def run_backfill(service: ComposioService, *, dry_run: bool) -> BackfillResult:
    auth_config_id, trigger = _gmail_sent_target()
    active = await _active_account_user_ids(service, auth_config_id)
    armed = await _armed_user_ids(service, auth_config_id)
    result = BackfillResult(
        dry_run=dry_run,
        pending_user_ids=sorted(active - armed),
        already_armed=len(active & armed),
    )
    if dry_run:
        return result

    for user_id in result.pending_user_ids:
        created = await service.handle_subscribe_trigger(user_id, [trigger])
        if created is None:
            result.failed_user_ids.append(user_id)
        else:
            result.armed_user_ids.append(user_id)
    return result


def _render(result: BackfillResult, limit: int) -> None:
    print(f"\n{'DRY RUN — nothing was written' if result.dry_run else 'EXECUTED'}")
    print(f"already armed:        {result.already_armed}")
    print(f"missing the trigger:  {len(result.pending_user_ids)}")
    if not result.dry_run:
        print(f"armed now:            {len(result.armed_user_ids)}")
        print(f"failed (re-run me):   {len(result.failed_user_ids)}")
        for user_id in result.failed_user_ids:
            print(f"  {user_id}")

    for user_id in result.pending_user_ids[:limit]:
        print(f"  {user_id}")
    if len(result.pending_user_ids) > limit:
        print(f"... and {len(result.pending_user_ids) - limit} more (raise --limit to see them)")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Mutually exclusive so an ambiguous `--execute --dry-run` fails loud instead
    # of guessing whether to create triggers on other people's accounts.
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="actually create the triggers")
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    parser.add_argument("--limit", type=int, default=25, help="users to list in the report")
    args = parser.parse_args()

    init_composio_service()
    result = await run_backfill(get_composio_service(), dry_run=not args.execute)
    _render(result, args.limit)

    if not args.execute:
        print("\nRe-run with --execute to create these triggers.")


if __name__ == "__main__":
    asyncio.run(main())
