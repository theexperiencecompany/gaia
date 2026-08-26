"""Fold a bot DM's legacy session row onto its canonical session key.

One DM can end up under two session keys. The first split was the literal
``:dm`` suffix workflow delivery used to write; the second is Discord and
Slack, whose DM *channel* ids differ from the user id, so an inbound DM keyed
``platform:<user>:<dm-channel>`` while backend-originated delivery keyed
``platform:<user>:<user>``. Either way the user's chat forks into a second
conversation carrying none of the history.

This module owns the resolution — which row survives, which conversation the
canonical key points at — and is shared by the offline migration
(``app.scripts.merge_legacy_dm_bot_sessions``) and the lazy per-user merge the
chat path runs when a bot flags an inbound message as a DM. The lazy path
exists because a Discord or Slack DM-channel key is indistinguishable from a
guild/channel key server-side: only at claim time, when the bot says "this is
a DM" and names the channel, are both keys known.

Message histories are NOT merged — the losing conversation stays in Mongo,
unreferenced by any session; only which conversation the next message
continues changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.db.repositories.bot_sessions import bot_session_repository
from app.models.bot_models import BotSessionDocument


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


def dm_channel_of(canonical_key: str) -> str:
    """The canonical key's channel component — everything after the last colon.

    ``build_session_key`` lays the key out as ``platform:user:channel``, so the
    channel is the final segment. No maxsplit: taking ``[-1]`` makes every split
    bound produce the same answer, and a bound that changes nothing reads as if
    it were load-bearing.
    """
    return canonical_key.split(":")[-1]


def plan_merge(
    legacy: BotSessionDocument, canonical: BotSessionDocument | None, canonical_key: str
) -> SessionMerge | None:
    """What to do with one legacy row, or ``None`` when it is not actionable."""
    if not (legacy.session_key and legacy.platform and legacy.platform_user_id):
        return None
    if not legacy.conversation_id:
        return None
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


async def apply_merge(merge: SessionMerge) -> bool:
    """Write one planned merge. False when the row moved between plan and write."""
    if merge.action is MergeAction.RENAME:
        return await bot_session_repository.rename_session_key(
            session_key=merge.legacy_key,
            new_session_key=merge.canonical_key,
            channel_id=dm_channel_of(merge.canonical_key),
        )
    if merge.action is MergeAction.REPOINT:
        await bot_session_repository.repoint_conversation(
            session_key=merge.canonical_key,
            conversation_id=merge.surviving_conversation_id,
        )
    return await bot_session_repository.delete_by_session_key(merge.legacy_key) > 0
