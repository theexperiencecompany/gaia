#!/usr/bin/env python3
"""Retire bot sessions that outlived the link between their platform account and a GAIA user.

Unlinking used to leave a platform account's sessions in place, so the next GAIA
user that account linked to continued the previous user's conversation id, and
with it the previous user's LangGraph thread. Unlinking now deletes them; this
retires the rows left by unlinks before that. Per session, one verdict:

- **unlinked** — no GAIA user holds the platform account; the next link inherits it.
- **ownerless** — no user holds the conversation, so the next message recreates it
  under the old id, on whatever agent thread that id still names.
- **foreign** — the linked user does not own the conversation and another user does.
- **shared** — the linked user and another user both hold it: the leak already
  happened. Retiring stops new messages joining it; the conversations and their
  threads are left for a human to review.

A retired session costs nothing but continuity: the account's next message
starts a fresh conversation. No conversation or thread is deleted.

Usage::

    cd apps/api
    uv run python -m app.scripts.retire_unlinked_bot_sessions          # dry run
    uv run python -m app.scripts.retire_unlinked_bot_sessions --apply  # commit
"""

from __future__ import annotations

import argparse
import asyncio
from enum import StrEnum
from typing import NamedTuple

from app.db.repositories.bot_sessions import bot_session_repository
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.users import user_repository
from app.models.bot_models import BotSessionDocument


class Verdict(StrEnum):
    UNLINKED = "unlinked"
    OWNERLESS = "ownerless"
    FOREIGN = "foreign"
    SHARED = "shared"


class Retirement(NamedTuple):
    session: BotSessionDocument
    verdict: Verdict


def judge(linked_user_id: str | None, owner_ids: set[str]) -> Verdict | None:
    """Return why a session must go, or None when it belongs to the user its account links to."""
    if linked_user_id is None:
        return Verdict.UNLINKED
    if not owner_ids:
        return Verdict.OWNERLESS
    if owner_ids == {linked_user_id}:
        return None
    return Verdict.SHARED if linked_user_id in owner_ids else Verdict.FOREIGN


async def _plan(platform: str | None) -> list[Retirement]:
    retirements: list[Retirement] = []
    for session in await bot_session_repository.list_sessions(platform=platform):
        linked = await user_repository.get_by_platform_id(
            session.platform, session.platform_user_id
        )
        owners = await conversation_repository.owner_ids(session.conversation_id)
        verdict = judge(linked.id if linked else None, owners)
        if verdict is not None:
            retirements.append(Retirement(session, verdict))
    return retirements


async def _run(args: argparse.Namespace) -> int:
    retirements = await _plan(args.platform)
    for r in retirements:
        print(f"  [{r.verdict}] {r.session.session_key} -> {r.session.conversation_id}")
    counts = {v: sum(r.verdict is v for r in retirements) for v in Verdict}
    print("Summary: " + ", ".join(f"{n} {v}" for v, n in counts.items()))
    if counts[Verdict.SHARED]:
        print(
            "SHARED conversations already mix two users' agent threads; review them by hand "
            "(this script does not touch conversations or threads)."
        )

    if not args.apply:
        print("Dry run only. Re-run with --apply to commit.")
        return 0

    retired = 0
    for r in retirements:
        retired += await bot_session_repository.delete_by_session_key(r.session.session_key)
    print(f"Retired {retired}/{len(retirements)} session(s).")
    return 0 if retired == len(retirements) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist (otherwise dry run).")
    parser.add_argument("--platform", help="Restrict to one platform.")
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
