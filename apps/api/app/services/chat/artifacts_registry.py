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
from typing import Any

from app.constants.artifacts import ARTIFACT_ELEMENT_FIELDS
from app.constants.cache import CONV_ARTIFACTS_CACHE_PATTERN, ONE_DAY_TTL
from app.db.repositories.conversations import conversation_repository
from app.decorators.caching import Cacheable, CacheInvalidator


@CacheInvalidator(key_patterns=[CONV_ARTIFACTS_CACHE_PATTERN])
async def upsert_conversation_artifact(user_id: str, conv_id: str, payload: dict[str, Any]) -> None:
    """Upsert one artifact onto the conversation registry, keyed by ``path``.

    ``body`` is written only when the payload carries one, so a body-less watcher
    re-emit never wipes an inline preview saved by an earlier tool-sourced write.
    """
    now_iso = datetime.now(UTC).isoformat()
    path = payload["path"]

    fields: dict[str, Any] = {
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
async def get_conversation_artifacts(user_id: str, conv_id: str) -> list[dict[str, Any]]:
    """Return the conversation's artifact registry (Redis-cached)."""
    return await conversation_repository.list_artifacts(conv_id, user_id=user_id)
