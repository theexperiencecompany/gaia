"""Hot-path core context — the memory injected into every system prompt.

``get_core_context`` is a single Redis hit on the steady state (plan F1,
sub-5ms budget). On a miss it assembles the user's core documents plus
today's and yesterday's journal lines from Postgres and re-caches. Every
ingestion (and any core-document write) invalidates the key, so the TTL is
only a backstop.
"""

import asyncio
from datetime import UTC, date as date_type, datetime, timedelta

from app.constants.memory import (
    CORE_CONTEXT_CACHE_KEY,
    CORE_CONTEXT_CACHE_TTL,
    RECENT_ACTIVITY_ENTRY_CAP,
    MemoryDocType,
)
from app.db.redis import delete_cache, get_cache, set_cache
from app.memory import pg_store
from app.memory.retrieval import invalidate_recall_cache
from app.models.memory_db_models import MemoryEpisode

_DOC_SECTIONS: list[tuple[MemoryDocType, str]] = [
    (MemoryDocType.USER_MD, "## About the user"),
    (MemoryDocType.MEMORY_MD, "## Assistant conventions"),
    (MemoryDocType.AGENDA_MD, "## Current agenda"),
]
_RECENT_ACTIVITY_HEADING = "## Recent activity"


def _strip_leading_h1(content: str) -> str:
    """Drop a leading '# Title' line from a document so the section heading added
    by get_core_context is the only H1/H2 marker at the top of each block.

    Example: "# About the user\n## Identity\n- ..." becomes "## Identity\n- ...".
    Lines that do not start with a single '#' followed by a space are left alone.
    """
    first_newline = content.find("\n")
    first_line = content[:first_newline] if first_newline != -1 else content
    rest = content[first_newline + 1 :] if first_newline != -1 else ""
    if first_line.startswith("# ") and not first_line.startswith("## "):
        return rest.lstrip("\n")
    return content


async def get_core_context(user_id: str) -> str:
    """Assembled always-injected memory context, cached in Redis.

    Empty documents and empty journal days are omitted; a user with no
    memory at all gets "".
    """
    cache_key = CORE_CONTEXT_CACHE_KEY.format(user_id=user_id)
    cached = await get_cache(cache_key)
    if isinstance(cached, str):
        return cached

    today = datetime.now(UTC).date()
    documents, episodes = await asyncio.gather(
        pg_store.get_documents(user_id),
        pg_store.get_episodes_range(user_id, today - timedelta(days=1), today),
    )

    documents_by_type = {document.doc_type: document for document in documents}
    sections: list[str] = []
    for doc_type, heading in _DOC_SECTIONS:
        document = documents_by_type.get(doc_type.value)
        if document is not None and document.content.strip():
            sections.append(f"{heading}\n{_strip_leading_h1(document.content.strip())}")

    recent_activity = _format_recent_activity(episodes, today)
    if recent_activity:
        sections.append(f"{_RECENT_ACTIVITY_HEADING}\n{recent_activity}")

    context = "\n\n".join(sections)
    await set_cache(cache_key, context, ttl=CORE_CONTEXT_CACHE_TTL)
    return context


async def invalidate_core_context(user_id: str) -> None:
    """Drop the cached core context (call after ingestion or document writes)."""
    await delete_cache(CORE_CONTEXT_CACHE_KEY.format(user_id=user_id))


async def invalidate_user_memory_caches(user_id: str) -> None:
    """Drop everything memory-cached for a user: recall results + core context.

    The single invalidation point every memory mutation (ingestion, edits,
    forgets, wipes) goes through.
    """
    await invalidate_recall_cache(user_id)
    await invalidate_core_context(user_id)


def _format_recent_activity(episodes: list[MemoryEpisode], today: date_type) -> str:
    """Compact journal rendering, bounded so it never dumps a whole day.

    A past day collapses to its one-line rollover summary. Today (not yet
    summarized) shows only its most recent ``RECENT_ACTIVITY_ENTRY_CAP``
    entries — enough for continuity without the prompt growing all day. The
    full journal stays available via ``search_journal``.
    """
    blocks: list[str] = []
    for episode in episodes:
        label = "Today" if episode.date == today else "Yesterday"
        if episode.date != today and episode.summary:
            blocks.append(f"### {label} ({episode.date.isoformat()})\n{episode.summary.strip()}")
            continue
        if not episode.entries:
            continue
        recent = episode.entries[-RECENT_ACTIVITY_ENTRY_CAP:]
        lines = [f"- {entry.get('time', '')} {entry.get('text', '')}".rstrip() for entry in recent]
        more = len(episode.entries) - len(recent)
        if more > 0:
            lines.insert(0, f"- (+{more} earlier entries today)")
        blocks.append(f"### {label} ({episode.date.isoformat()})\n" + "\n".join(lines))
    return "\n".join(blocks)
