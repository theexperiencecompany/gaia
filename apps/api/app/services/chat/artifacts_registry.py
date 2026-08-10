"""Conversation-level artifact registry — the single source of truth for a
conversation's agent-written files.

Each artifact is stored once on the conversation's ``artifacts[]`` array, keyed
by ``path`` (upsert-by-path), so the same file never lands in two places and an
edit updates the one record everywhere. Reads are Redis-cached so a chat turn
reads the registry once instead of re-scanning the costly JuiceFS dir; every
write busts that cache. ``$currentDate {updatedAt}`` on each write is what makes
the frontend's batch-sync staleness check refetch the conversation afterwards.
"""

from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict, cast

from app.constants.artifacts import ARTIFACT_ELEMENT_FIELDS
from app.constants.cache import CONV_ARTIFACTS_CACHE_PATTERN, ONE_DAY_TTL
from app.db.repositories.conversations import conversation_repository
from app.decorators.caching import Cacheable, CacheInvalidator


class ArtifactRegistryEntry(TypedDict):
    """One element of ``ConversationDocument.artifacts``.

    This module owns the element shape (see the comment on that field): the
    conversation document stores it as a raw dict and mirrors it verbatim to the
    client. ``mtime`` is a Unix timestamp, matching what every publisher in
    :mod:`app.services.artifact_events` stamps. ``body`` is present only for
    small textual artifacts inlined at write time.
    """

    path: str
    size_bytes: int | None
    mtime: float | None
    content_type: str | None
    updated_at: str
    body: NotRequired[str]


class ArtifactRegistryPatch(TypedDict, total=False):
    """The subset of an entry a re-emit rewrites — every key optional so a
    body-less watcher event never clears an inlined body."""

    size_bytes: int | None
    mtime: float | None
    content_type: str | None
    updated_at: str
    body: str


@CacheInvalidator(key_patterns=[CONV_ARTIFACTS_CACHE_PATTERN])
async def upsert_conversation_artifact(user_id: str, conv_id: str, payload: dict[str, Any]) -> None:
    """Upsert one artifact onto the conversation registry, keyed by ``path``.

    ``body`` is written only when the payload carries one, so a body-less watcher
    re-emit never wipes an inline preview saved by an earlier tool-sourced write.

    ``payload`` is the raw artifact event; its wire contract is owned by
    :mod:`app.services.artifact_events`, so it stays an untyped dict here rather
    than gaining a rival shape (Type Safety item 14).
    """
    now_iso = datetime.now(UTC).isoformat()
    path = payload["path"]

    fields: ArtifactRegistryPatch = {
        "size_bytes": payload.get("size_bytes"),
        "mtime": payload.get("mtime"),
        "content_type": payload.get("content_type"),
        "updated_at": now_iso,
    }
    if payload.get("body") is not None:
        fields["body"] = payload["body"]

    if await conversation_repository.update_artifact(
        conv_id, user_id=user_id, path=path, fields=fields
    ):
        return

    # No existing element — push a new one.
    element: dict[str, Any] = {key: payload.get(key) for key in ARTIFACT_ELEMENT_FIELDS}
    element["updated_at"] = now_iso
    if payload.get("body") is not None:
        element["body"] = payload["body"]
    await conversation_repository.push_artifact(
        conv_id, user_id=user_id, path=path, element=element
    )


@CacheInvalidator(key_patterns=[CONV_ARTIFACTS_CACHE_PATTERN])
async def remove_conversation_artifact(user_id: str, conv_id: str, path: str) -> None:
    """Remove an artifact from the conversation registry by ``path``."""
    await conversation_repository.remove_artifact(conv_id, user_id=user_id, path=path)


@Cacheable(key_pattern=CONV_ARTIFACTS_CACHE_PATTERN, ttl=ONE_DAY_TTL, namespace="api")
async def get_conversation_artifacts(user_id: str, conv_id: str) -> list[ArtifactRegistryEntry]:
    """Return the conversation's artifact registry (Redis-cached).

    The repository hands back the raw stored elements; they are exactly what the
    two writers above put there, so this narrows rather than re-validates.
    """
    rows = await conversation_repository.list_artifacts(conv_id, user_id=user_id)
    return cast(list[ArtifactRegistryEntry], rows)
