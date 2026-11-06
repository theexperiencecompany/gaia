#!/usr/bin/env python3
"""Put the Inbox desk's system gate on every open desk whose mail watch never had one.

A desk opened before the gate shipped runs on every new mail it watches. One opened or
re-provisioned since gets the gate itself. A gate the user turned off is left off.

Dry run by default. Nothing is written without ``--apply``. Safe to repeat: a desk
it gated has a gate, so a second run finds nothing left to do.

Usage::

    cd apps/api
    uv run python -m app.scripts.gate_inbox_desks            # report only
    uv run python -m app.scripts.gate_inbox_desks --apply
"""

from __future__ import annotations

import argparse
import asyncio

from app.db.repositories.todos import todo_repository
from app.services.todos.external_ref_watch import gate_watches, ungated_watches
from app.services.todos.inbox_desk import INBOX_DESK_REF


async def _run(args: argparse.Namespace) -> None:
    desks = await todo_repository.list_open_by_external_ref_all_users(INBOX_DESK_REF)
    due = [desk for desk in desks if ungated_watches(INBOX_DESK_REF, desk.trigger_subscriptions)]
    print(f"open Inbox desks: {len(desks)}")
    print(f"desks whose mail watch has no gate: {len(due)}")
    for desk in due:
        print(f"  desk {desk.id} of user {desk.user_id}")
    print()
    if not args.apply:
        print("dry run: nothing written. Re-run with --apply to gate them.")
        return
    gated = 0
    for desk in due:
        if await gate_watches(desk.id, desk.user_id, INBOX_DESK_REF, desk.trigger_subscriptions):
            gated += 1
    print(f"gated {gated} desk(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the gates")
    asyncio.run(_run(parser.parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
