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
from dataclasses import dataclass
from enum import StrEnum

from app.db.repositories.bot_sessions import (
    LEGACY_DM_SESSION_KEY_SUFFIX,
    bot_session_repository,
)
from app.models.bot_models import BotSessionDocument
from app.services.bot_service import BotService
from shared.py.wide_events import log


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


def last_used(session: BotSessionDocument) -> str:
    """The row's recency marker for the newer-wins comparison.

    ``updated_at``/``created_at`` are both written by ``datetime.now(UTC).isoformat()``
    (see ``BotSessionsRepository.claim_session``), so the strings share one format
    and one offset — lexicographic order is chronological order. A row missing
    both sorts oldest, which is the safe way for an unstamped row to lose.
    """
    return session.updated_at or session.created_at or ""


def canonical_key_for(session: BotSessionDocument) -> str:
    """The key this session's DM belongs under today.

    Derived through ``BotService.build_session_key`` rather than a format restated
    here, so the migration can never disagree with the code that will do the next
    lookup.
    """
    return BotService.build_session_key(session.platform, session.platform_user_id, None)


def plan_merge(
    legacy: BotSessionDocument, canonical: BotSessionDocument | None
) -> SessionMerge | None:
    """What to do with one legacy ``:dm`` row, or ``None`` when it is not actionable."""
    if not (legacy.session_key and legacy.platform and legacy.platform_user_id):
        return None
    if not legacy.conversation_id:
        return None

    canonical_key = canonical_key_for(legacy)
    if canonical_key == legacy.session_key:
        return None

    if canonical is None:
        return SessionMerge(
            legacy_key=legacy.session_key,
            canonical_key=canonical_key,
            action=MergeAction.RENAME,
            surviving_conversation_id=legacy.conversation_id,
            orphaned_conversation_id=None,
            reason="no session on the canonical key; the legacy row keeps its conversation",
        )

    if last_used(legacy) > last_used(canonical):
        return SessionMerge(
            legacy_key=legacy.session_key,
            canonical_key=canonical_key,
            action=MergeAction.REPOINT,
            surviving_conversation_id=legacy.conversation_id,
            orphaned_conversation_id=canonical.conversation_id,
            reason="the legacy session was used more recently",
        )

    return SessionMerge(
        legacy_key=legacy.session_key,
        canonical_key=canonical_key,
        action=MergeAction.DROP,
        surviving_conversation_id=canonical.conversation_id,
        orphaned_conversation_id=legacy.conversation_id,
        reason="the canonical session was used more recently",
    )


def dm_channel_of(canonical_key: str) -> str:
    """The canonical key's channel component — everything after the last colon.

    ``build_session_key`` lays the key out as ``platform:user:channel``, so the
    channel is the final segment. No maxsplit: taking ``[-1]`` makes every split
    bound produce the same answer, and a bound that changes nothing reads as if
    it were load-bearing.
    """
    return canonical_key.split(":")[-1]


async def _build_merges(legacy_sessions: list[BotSessionDocument]) -> list[SessionMerge]:
    merges: list[SessionMerge] = []
    for legacy in legacy_sessions:
        canonical = await bot_session_repository.get_by_session_key(canonical_key_for(legacy))
        merge = plan_merge(legacy, canonical)
        if merge is None:
            print(f"  SKIP {legacy.session_key!r}: incomplete row, left untouched")
            continue
        merges.append(merge)
    return merges


async def _apply_merges(merges: list[SessionMerge]) -> int:
    """Write the planned merges. Returns the number that actually landed."""
    applied = 0
    for merge in merges:
        if merge.action is MergeAction.RENAME:
            landed = await bot_session_repository.rename_session_key(
                session_key=merge.legacy_key,
                new_session_key=merge.canonical_key,
                channel_id=dm_channel_of(merge.canonical_key),
            )
        else:
            if merge.action is MergeAction.REPOINT:
                await bot_session_repository.repoint_conversation(
                    session_key=merge.canonical_key,
                    conversation_id=merge.surviving_conversation_id,
                )
            landed = await bot_session_repository.delete_by_session_key(merge.legacy_key) > 0

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
