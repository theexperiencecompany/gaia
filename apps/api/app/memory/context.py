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
    CORE_CONTEXT_SECTION_MAX_CHARS,
    CORE_CONTEXT_TRUNC_MARKER,
    MemoryDocType,
)
from app.db.redis import delete_cache, get_cache, set_cache
from app.memory import pg_store
from app.memory.retrieval import invalidate_recall_cache
from app.models.memory_db_models import MemoryEpisode
from shared.py.wide_events import log

# Public because get_core_context joins the sections into one string and
# message_helpers has to find the boundaries again to split the volatile
# agenda/journal out of the cacheable documents. One definition, so a copy
# edit here cannot silently stop that split from matching.
AGENDA_HEADING = "## Current agenda"
RECENT_ACTIVITY_HEADING = "## Recent activity"

_DOC_SECTIONS: list[tuple[MemoryDocType, str]] = [
    (MemoryDocType.USER_MD, "## About the user"),
    (MemoryDocType.MEMORY_MD, "## Assistant conventions"),
    (MemoryDocType.AGENDA_MD, AGENDA_HEADING),
]


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


def _bounded(body: str, doc_type: MemoryDocType) -> str:
    """Clip one document to its own share of the always-injected block.

    Each document is bounded separately rather than the joined block being
    head/tail-cut as a whole. A single cut over everything meant an oversized
    agenda (production: 4,886 characters) ate the journal that followed it —
    the section that overran was never the one that paid for it. The write
    path caps these documents too; this is the read-side backstop for a
    document written before the cap existed.
    """
    limit = CORE_CONTEXT_SECTION_MAX_CHARS.get(doc_type)
    if limit is None or len(body) <= limit:
        return body
    log.warning(
        "memory_core_context_section_clipped",
        error_type="core_context_section_over_budget",
        doc_type=doc_type.value,
        chars=len(body),
        limit=limit,
    )
    return body[:limit] + CORE_CONTEXT_TRUNC_MARKER


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
            body = _bounded(_strip_leading_h1(document.content.strip()), doc_type)
            sections.append(f"{heading}\n{body}")

    recent_activity = _format_recent_activity(episodes, today)
    if recent_activity:
        sections.append(f"{RECENT_ACTIVITY_HEADING}\n{recent_activity}")

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

    A past day collapses to its one-line rollover summary. Today emits its
    NEWEST entries only — the real recency value — with a static no-number
    note when older ones are dropped. The old anchored-at-day-start window
    kept only old entries while the newest churned in every turn, and its
    "+N more entries today" counter changed N every turn; both sat inside the
    volatile tail where every changed byte costs prompt-cache hit rate. The
    static note keeps the emitted bytes identical between entry additions.
    The full journal stays available via ``search_journal``.
    """
    blocks: list[str] = []
    for episode in episodes:
        label = "Today" if episode.date == today else "Yesterday"
        if episode.date != today and episode.summary:
            blocks.append(f"### {label} ({episode.date.isoformat()})\n{episode.summary.strip()}")
            continue
        if not episode.entries:
            continue
        # Emit the NEWEST entries (last-2) — not an anchored-at-start window
        # (which held only old entries and churned the newest in every turn)
        # and no numbered counter (N changed every turn). The omitted-note is
        # byte-identical across turns, so the emitted bytes only change when
        # a new entry lands.
        recent = episode.entries[-2:] if len(episode.entries) > 2 else episode.entries
        lines = [f"- {entry.get('time', '')} {entry.get('text', '')}".rstrip() for entry in recent]
        if len(episode.entries) > 2:
            lines.append("- (earlier entries omitted)")
        blocks.append(f"### {label} ({episode.date.isoformat()})\n" + "\n".join(lines))
    return "\n".join(blocks)
