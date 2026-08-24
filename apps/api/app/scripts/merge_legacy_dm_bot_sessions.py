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
    --platform <name>   Restrict to one platform (repeatable).
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.db.mongodb.collections import get_async_collection
from app.services.bot_service import BotService
from shared.py.wide_events import log

BOT_SESSIONS_COLLECTION = "bot_sessions"

#: The suffix the old ``channel_id or "dm"`` derivation produced for a DM. Only
#: that derivation ever wrote it — no platform names a channel "dm".
LEGACY_DM_SUFFIX = ":dm"


class MergeAction(StrEnum):
    RENAME = "rename"
    REPOINT = "repoint"
    DROP = "drop"


@dataclass(frozen=True, slots=True)
class SessionMerge:
    """One legacy row's resolution, decided before anything is written."""

    legacy_key: str
    canonical_key: str
    action: MergeAction
    #: The conversation the canonical key points at once this is applied.
    surviving_conversation_id: str
    #: The conversation left unreferenced, or ``None`` when nothing is displaced.
    orphaned_conversation_id: str | None
    reason: str


def last_used(row: Mapping[str, Any]) -> str:
    """The row's recency marker for the newer-wins comparison.

    ``updated_at``/``created_at`` are both written by ``datetime.now(UTC).isoformat()``
    (see ``BotSessionsRepository.claim_session``), so the strings share one format
    and one offset — lexicographic order is chronological order. A row missing
    both sorts oldest, which is the safe way for an unstamped row to lose.
    """
    return str(row.get("updated_at") or row.get("created_at") or "")


def plan_merge(
    legacy: Mapping[str, Any], canonical: Mapping[str, Any] | None
) -> SessionMerge | None:
    """What to do with one legacy ``:dm`` row, or ``None`` when it is not actionable.

    The canonical key comes from ``BotService.build_session_key`` rather than a
    format restated here, so the script can never disagree with the code that
    will do the next lookup.
    """
    legacy_key = str(legacy.get("session_key") or "")
    platform = str(legacy.get("platform") or "")
    platform_user_id = str(legacy.get("platform_user_id") or "")
    legacy_conversation_id = str(legacy.get("conversation_id") or "")
    if not (legacy_key and platform and platform_user_id and legacy_conversation_id):
        return None

    canonical_key = BotService.build_session_key(platform, platform_user_id, None)
    if canonical_key == legacy_key:
        return None

    if canonical is None:
        return SessionMerge(
            legacy_key=legacy_key,
            canonical_key=canonical_key,
            action=MergeAction.RENAME,
            surviving_conversation_id=legacy_conversation_id,
            orphaned_conversation_id=None,
            reason="no session on the canonical key; the legacy row keeps its conversation",
        )

    canonical_conversation_id = str(canonical.get("conversation_id") or "")
    if last_used(legacy) > last_used(canonical):
        return SessionMerge(
            legacy_key=legacy_key,
            canonical_key=canonical_key,
            action=MergeAction.REPOINT,
            surviving_conversation_id=legacy_conversation_id,
            orphaned_conversation_id=canonical_conversation_id,
            reason="the legacy session was used more recently",
        )

    return SessionMerge(
        legacy_key=legacy_key,
        canonical_key=canonical_key,
        action=MergeAction.DROP,
        surviving_conversation_id=canonical_conversation_id,
        orphaned_conversation_id=legacy_conversation_id,
        reason="the canonical session was used more recently",
    )


def _dm_channel_of(session_key: str) -> str:
    """The canonical key's channel component — the platform user id."""
    return session_key.rsplit(":", 1)[-1]


async def _load_legacy_rows(platforms: set[str]) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"session_key": {"$regex": f"{LEGACY_DM_SUFFIX}$"}}
    if platforms:
        query["platform"] = {"$in": sorted(platforms)}
    cursor = get_async_collection(BOT_SESSIONS_COLLECTION).find(query)
    return [row async for row in cursor]


async def _build_merges(legacy_rows: list[dict[str, Any]]) -> list[SessionMerge]:
    collection = get_async_collection(BOT_SESSIONS_COLLECTION)
    merges: list[SessionMerge] = []
    for legacy in legacy_rows:
        platform = str(legacy.get("platform") or "")
        platform_user_id = str(legacy.get("platform_user_id") or "")
        canonical: dict[str, Any] | None = None
        if platform and platform_user_id:
            canonical_key = BotService.build_session_key(platform, platform_user_id, None)
            canonical = await collection.find_one({"session_key": canonical_key})
        merge = plan_merge(legacy, canonical)
        if merge is None:
            print(f"  SKIP {legacy.get('session_key')!r}: incomplete row, left untouched")
            continue
        merges.append(merge)
    return merges


async def _apply_merges(merges: list[SessionMerge]) -> int:
    """Write the planned merges. Returns the number applied."""
    collection = get_async_collection(BOT_SESSIONS_COLLECTION)
    applied = 0
    for merge in merges:
        if merge.action is MergeAction.RENAME:
            await collection.update_one(
                {"session_key": merge.legacy_key},
                {
                    "$set": {
                        "session_key": merge.canonical_key,
                        "channel_id": _dm_channel_of(merge.canonical_key),
                    }
                },
            )
        else:
            if merge.action is MergeAction.REPOINT:
                await collection.update_one(
                    {"session_key": merge.canonical_key},
                    {"$set": {"conversation_id": merge.surviving_conversation_id}},
                )
            await collection.delete_one({"session_key": merge.legacy_key})

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
    legacy_rows = await _load_legacy_rows(set(args.platform or []))
    print(f"Found {len(legacy_rows)} legacy '{LEGACY_DM_SUFFIX}' bot session(s).")
    if not legacy_rows:
        return 0

    print()
    print("=" * 78)
    print("Plan (DRY RUN)" if not args.apply else "Plan")
    print("=" * 78)
    merges = await _build_merges(legacy_rows)
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
    print(f"Applied {applied}/{len(merges)} merges. No '{LEGACY_DM_SUFFIX}' session remains.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes (otherwise dry run only).",
    )
    parser.add_argument(
        "--platform",
        action="append",
        help="Restrict to this platform (repeatable).",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
