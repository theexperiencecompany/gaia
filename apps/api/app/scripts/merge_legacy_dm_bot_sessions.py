#!/usr/bin/env python3
"""Fold legacy ``:dm`` bot sessions onto the canonical DM session key.

``BotService.build_session_key`` used to key a channel-less session as the
literal ``"dm"``, so one Telegram DM lived under two keys at once —
``telegram:<id>:<id>`` written by the inbound chat (Telegram sends the private
chat id, which IS the user id) and ``telegram:<id>:dm`` written by workflow
platform delivery, which has no channel. The user's chat silently forked into a
second conversation with none of the history. The key derivation is fixed; this
retires the rows the old format left behind so no lookup can resurrect them.

Per legacy row, one of three actions against the canonical key:

- **rename** — nothing sits on the canonical key, so the legacy row moves onto
  it and keeps its conversation. Nothing is lost.
- **repoint** — both rows exist and the LEGACY one was used more recently, so the
  canonical row is repointed at the legacy conversation and the legacy row is
  dropped.
- **drop** — both rows exist and the canonical one was used more recently, so the
  legacy row is simply dropped.

Message histories are NOT merged — deliberately out of scope. The losing
conversation stays in Mongo, just unreferenced by any session; only which
conversation the platform's next message continues changes.

Idempotent: it leaves no ``:dm`` row behind, so a second run finds nothing.

Usage::

    cd apps/api
    uv run python -m app.scripts.merge_legacy_dm_bot_sessions          # dry run
    uv run python -m app.scripts.merge_legacy_dm_bot_sessions --apply  # commit

Flags::

    --apply             Persist changes to MongoDB (otherwise dry run only).
    --platform <name>   Restrict to one platform.
"""

from __future__ import annotations

import argparse
import asyncio

from app.db.repositories.bot_sessions import (
    LEGACY_DM_SESSION_KEY_SUFFIX,
    bot_session_repository,
)
from app.models.bot_models import BotSessionDocument
from app.services.bot_service import BotService
from app.services.bot_session_merge import (
    MergeAction,
    SessionMerge,
    apply_merge,
    plan_merge,
)
from shared.py.wide_events import log


def canonical_key_for(session: BotSessionDocument) -> str:
    """The key this session's DM belongs under today.

    Derived through ``BotService.build_session_key`` rather than a format restated
    here, so the migration can never disagree with the code that will do the next
    lookup.
    """
    return BotService.build_session_key(session.platform, session.platform_user_id, None)


async def _build_merges(legacy_sessions: list[BotSessionDocument]) -> list[SessionMerge]:
    merges: list[SessionMerge] = []
    for legacy in legacy_sessions:
        canonical_key = canonical_key_for(legacy)
        canonical = await bot_session_repository.get_by_session_key(canonical_key)
        merge = plan_merge(legacy, canonical, canonical_key)
        if merge is None:
            print(f"  SKIP {legacy.session_key!r}: incomplete row, left untouched")
            continue
        merges.append(merge)
    return merges


async def _apply_merges(merges: list[SessionMerge]) -> int:
    """Write the planned merges. Returns the number that actually landed."""
    applied = 0
    for merge in merges:
        landed = await apply_merge(merge)
        if not landed:
            # Someone else moved the row between the plan and the write. Say so
            # rather than counting it — a silent miss leaves a fork in place.
            print(f"  WARN: {merge.action.value} of {merge.legacy_key} matched nothing")
            continue

        applied += 1
        log.info(
            "merged legacy dm bot session",
            action=merge.action.value,
            legacy_key=merge.legacy_key,
            canonical_key=merge.canonical_key,
            surviving_conversation_id=merge.surviving_conversation_id,
            orphaned_conversation_id=merge.orphaned_conversation_id,
        )
    return applied


def _print_plan(merges: list[SessionMerge]) -> None:
    for merge in merges:
        print(f"  [{merge.action.value}] {merge.legacy_key} -> {merge.canonical_key}")
        print(f"      keeps conversation {merge.surviving_conversation_id}")
        if merge.orphaned_conversation_id:
            print(
                f"      leaves conversation {merge.orphaned_conversation_id} unreferenced "
                "(history NOT merged)"
            )
        print(f"      because {merge.reason}")


async def _run(args: argparse.Namespace) -> int:
    legacy_sessions = await bot_session_repository.list_legacy_dm_sessions(platform=args.platform)
    print(f"Found {len(legacy_sessions)} legacy '{LEGACY_DM_SESSION_KEY_SUFFIX}' bot session(s).")
    if not legacy_sessions:
        return 0

    print()
    print("=" * 78)
    print("Plan (DRY RUN)" if not args.apply else "Plan")
    print("=" * 78)
    merges = await _build_merges(legacy_sessions)
    _print_plan(merges)

    counts = {action: sum(m.action is action for m in merges) for action in MergeAction}
    print()
    print("=" * 78)
    print(
        f"Summary: {len(merges)} session(s) — "
        + ", ".join(f"{count} {action.value}" for action, count in counts.items())
    )
    print("=" * 78)

    if not args.apply:
        print()
        print("Dry run only. Re-run with --apply to commit.")
        return 0

    applied = await _apply_merges(merges)
    print()
    print(f"Applied {applied}/{len(merges)} merges.")
    return 0 if applied == len(merges) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes (otherwise dry run only).",
    )
    parser.add_argument(
        "--platform",
        default=None,
        help="Restrict to this platform (e.g. telegram).",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
