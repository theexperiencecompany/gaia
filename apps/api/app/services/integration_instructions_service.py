"""Per-integration custom instructions — MongoDB-backed source of truth.

Mirrors the skills-registry pattern: a Redis-cached read (``get_all_instructions``)
with event-driven invalidation on write (``upsert_instructions``). The content
is the single source of truth; the VFS projection at
``integrations/<id>/agent/instructions.md`` and the subagent dynamic-context
block are both derived from it.

Both the user (via REST) and the agent (via the ``update_integration_instructions``
tool) write through ``upsert_instructions`` — there is no other write path, so the
cache and the materialized projection stay consistent.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib

from app.constants.cache import (
    INTEGRATION_INSTRUCTIONS_CACHE_KEY,
    INTEGRATION_INSTRUCTIONS_CACHE_TTL,
)
from app.db.mongodb.collections import integration_instructions_collection
from app.decorators.caching import Cacheable, CacheInvalidator
from app.models.integration_instructions_models import (
    MAX_INSTRUCTIONS_CHARS,
    InstructionsEditor,
    IntegrationInstructions,
)
from shared.py.wide_events import log

_INSTRUCTIONS_INVALIDATION_PATTERNS = [INTEGRATION_INSTRUCTIONS_CACHE_KEY]


@Cacheable(key_pattern=INTEGRATION_INSTRUCTIONS_CACHE_KEY, ttl=INTEGRATION_INSTRUCTIONS_CACHE_TTL)
async def get_all_instructions(user_id: str) -> dict[str, str]:
    """Return ``{integration_id: content}`` for every non-empty instruction.

    Cached per user (invalidated on write). Drives both the materialized VFS
    projection and the per-turn subagent context injection, so it must stay a
    cheap, single read.
    """
    cursor = integration_instructions_collection.find(
        {"user_id": user_id, "content": {"$ne": ""}},
        {"integration_id": 1, "content": 1, "_id": 0},
    )
    docs = await cursor.to_list(length=None)
    return {d["integration_id"]: d["content"] for d in docs if d.get("content")}


async def get_instructions(user_id: str, integration_id: str) -> str | None:
    """Return the markdown for one integration, or ``None`` if unset/empty."""
    return (await get_all_instructions(user_id)).get(integration_id)


async def get_instructions_record(
    user_id: str, integration_id: str
) -> IntegrationInstructions | None:
    """Return the full instructions record (content + audit fields), or ``None``.

    Uncached single read — used by the UI editor on open, where the freshest
    ``updated_by`` / ``updated_at`` matter for the audit line.
    """
    doc = await integration_instructions_collection.find_one(
        {"user_id": user_id, "integration_id": integration_id}
    )
    if not doc:
        return None
    return IntegrationInstructions(
        id=str(doc["_id"]),
        user_id=doc["user_id"],
        integration_id=doc["integration_id"],
        content=doc.get("content", ""),
        updated_by=InstructionsEditor(doc.get("updated_by", InstructionsEditor.USER.value)),
        updated_at=doc.get("updated_at") or datetime.now(UTC),
    )


@CacheInvalidator(key_patterns=_INSTRUCTIONS_INVALIDATION_PATTERNS)
async def upsert_instructions(
    user_id: str,
    integration_id: str,
    content: str,
    updated_by: InstructionsEditor = InstructionsEditor.USER,
) -> IntegrationInstructions:
    """Create or replace one integration's instructions (full-content write).

    Truncates to ``MAX_INSTRUCTIONS_CHARS`` so a runaway agent write can't bloat
    every subsequent context window. Whitespace-only content is stored as ""
    (i.e. cleared) so it never surfaces as a noisy, empty instructions block.
    Invalidates the per-user cache; the VFS projection re-syncs on the next
    session bootstrap via the staleness gate.
    """
    log.set(
        user_id=user_id,
        integration={"id": integration_id, "op": "upsert_instructions"},
        updated_by=updated_by.value,
    )
    truncated = content[:MAX_INSTRUCTIONS_CHARS]
    trimmed = truncated if truncated.strip() else ""
    now = datetime.now(UTC)
    await integration_instructions_collection.update_one(
        {"user_id": user_id, "integration_id": integration_id},
        {
            "$set": {
                "content": trimmed,
                "updated_by": updated_by.value,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    return IntegrationInstructions(
        user_id=user_id,
        integration_id=integration_id,
        content=trimmed,
        updated_by=updated_by,
        updated_at=now,
    )


def instructions_signature(instructions: dict[str, str]) -> str:
    """Stable hash over all of a user's instructions for the staleness gate.

    The session bootstrap compares this against an on-disk marker to decide
    whether the VFS projection needs rewriting — same mechanism as the skills
    library hash.
    """
    digest = hashlib.sha256()
    for integration_id in sorted(instructions):
        digest.update(integration_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(instructions[integration_id].encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:32]
