"""Hybrid recall — the zero-LLM read path (plan F3, target <150ms P95).

``recall`` fuses dense ANN (Chroma) and weighted FTS (Postgres) with RRF,
cross-encoder reranks the fused candidates, blends recency and importance
boosts, and optionally expands one hop through the entity graph.

Episode journal lines are deliberately NOT fused into ``recall``: they are
activity logs, not atomic facts, and surfacing them as pseudo-memories would
pollute the contract (no lineage, no category, no importance). Tools that
want "when did I last talk about X" use ``recall_episodes`` instead, which
combines verbatim entry matching over the last 14 days with semantic search
over day summaries.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, date as date_type, datetime, timedelta
import hashlib
import math
import re
import time
from typing import Any

from app.constants.memory import (
    ANN_CANDIDATES,
    CONFIDENT_COSINE,
    CONFIDENT_RERANK_LOGIT,
    DEFAULT_EPISODE_RECALL_LIMIT,
    DEFAULT_RECALL_LIMIT,
    EPISODE_ENTRY_CANDIDATES,
    EPISODE_SEARCH_DAYS,
    EPISODE_SEARCH_MIN_TOKEN_LENGTH,
    FTS_CANDIDATES,
    GRAPH_EXPANSION_MAX_SIBLINGS,
    GRAPH_EXPANSION_SOURCE_RESULTS,
    IMPORTANCE_BOOST_BASE,
    IMPORTANCE_BOOST_WEIGHT,
    MAX_WEAK_RESULTS,
    MEMORY_SEARCH_CACHE_PATTERN,
    MEMORY_SEARCH_CACHE_TTL,
    RECENCY_BOOST_DECAY_DAYS,
    RECENCY_BOOST_WEIGHT,
    RELEVANCE_DROPOFF_RATIO,
    RERANK_BLEND_WEIGHT,
    RERANK_CANDIDATES,
    RRF_K,
    MemoryKind,
)
from app.db.redis import delete_cache
from app.decorators.caching import Cacheable
from app.memory import chroma_store, pg_store
from app.memory.embeddings import embed_query, rerank
from app.memory.mappers import row_to_entry
from app.models.memory_db_models import MemoryRecord
from app.models.memory_models import MemoryEntry, MemorySearchResult
from shared.py.wide_events import log

_SECONDS_PER_DAY = 86_400.0
_TOKEN_PATTERN = re.compile(r"[a-z0-9']+")


@dataclass
class EpisodeHit:
    """One journal match: a verbatim entry line or a semantic day summary."""

    date: date_type
    text: str
    time: str | None = None
    score: float | None = None


def _recall_cache_key(_func_name: str, *args: Any, **kwargs: Any) -> str:
    """Cache key for ``recall``: user:{id}:memories:{digest}.

    The ``user:{user_id}:memories:*`` prefix must match
    ``MEMORY_SEARCH_CACHE_PATTERN`` — every ingestion invalidates that
    pattern. All non-user parameters are digested so calls that differ in
    any knob (limit, folder, kinds, expansion) never collide.

    ``user_id``/``query`` are read positionally or by keyword so callers may
    use either calling convention without breaking key generation.
    """
    user_id = args[0] if args else kwargs["user_id"]
    query = args[1] if len(args) > 1 else kwargs["query"]
    limit = kwargs.get("limit", DEFAULT_RECALL_LIMIT)
    category_prefix = kwargs.get("category_prefix")
    kinds = kwargs.get("kinds")
    include_graph_expansion = kwargs.get("include_graph_expansion", True)

    kinds_part = ",".join(sorted(kind.value for kind in kinds)) if kinds else ""
    payload = f"{query}|{limit}|{category_prefix}|{kinds_part}|{include_graph_expansion}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"user:{user_id}:memories:{digest}"


async def invalidate_recall_cache(user_id: str) -> None:
    """Drop every cached recall result for a user (called on ingestion)."""
    await delete_cache(MEMORY_SEARCH_CACHE_PATTERN.format(user_id=user_id))


@Cacheable(
    key_generator=_recall_cache_key,
    ttl=MEMORY_SEARCH_CACHE_TTL,
    model=MemorySearchResult,
)
async def recall(
    user_id: str,
    query: str,
    *,
    limit: int = DEFAULT_RECALL_LIMIT,
    category_prefix: str | None = None,
    kinds: list[MemoryKind] | None = None,
    include_graph_expansion: bool = True,
) -> MemorySearchResult:
    """Hybrid memory search: ANN + FTS -> RRF -> rerank -> boosts -> graph hop."""
    timings: dict[str, int] = {}
    started = time.perf_counter()

    ann_hits, fts_hits = await asyncio.gather(
        _ann_search(user_id, query, timings),
        _fts_search(user_id, query, timings),
    )

    stage = time.perf_counter()
    fused_ids = _rrf_fuse(
        [memory_id for memory_id, _ in ann_hits], [str(row.id) for row, _ in fts_hits]
    )
    timings["fusion_ms"] = _elapsed_ms(stage)

    stage = time.perf_counter()
    candidates = await _hydrate_candidates(
        user_id, fused_ids, fts_hits, category_prefix=category_prefix, kinds=kinds
    )
    if include_graph_expansion and candidates:
        candidates = await _with_graph_siblings(user_id, candidates, kinds=kinds)
    timings["hydrate_ms"] = _elapsed_ms(stage)

    stage = time.perf_counter()
    # Rerank the combined base+sibling pool together so siblings compete on real
    # query relevance, not a fixed score; the dropoff then cuts the weak tail.
    ann_similarity = {memory_id: similarity for memory_id, similarity in ann_hits}
    fts_ids = {str(row.id) for row, _ in fts_hits}
    scored = await _rerank_and_boost(
        query,
        candidates[:RERANK_CANDIDATES],
        ann_similarity=ann_similarity,
        fts_ids=fts_ids,
    )
    timings["rerank_ms"] = _elapsed_ms(stage)

    kept = _cap_weak_results(scored)[:limit]
    entries = await _build_entries(kept)
    entries = _drop_below_relevance(entries)

    timings["total_ms"] = _elapsed_ms(started)
    log.info(
        "memory_recall_completed",
        memory={
            "operation": "recall",
            "user_id": user_id,
            "query": query,
            "ann_hits": len(ann_hits),
            "fts_hits": len(fts_hits),
            "candidates": len(candidates),
            "results": len(entries),
            **timings,
        },
    )
    return MemorySearchResult(memories=entries, total_count=len(entries))


async def recall_episodes(
    user_id: str,
    query: str,
    limit: int = DEFAULT_EPISODE_RECALL_LIMIT,
) -> list[EpisodeHit]:
    """Search the journal: verbatim recent entries first, then day summaries.

    Entry hits (token ILIKE over the last ``EPISODE_SEARCH_DAYS`` days) are
    exact evidence of recent activity, so they outrank semantic summary hits,
    which extend coverage to any past day whose rollover summary matches.
    """
    tokens = _tokenize(query)
    since = datetime.now(UTC).date() - timedelta(days=EPISODE_SEARCH_DAYS)
    entry_rows, summary_hits = await asyncio.gather(
        pg_store.search_episode_entries(
            user_id, tokens, since=since, limit=EPISODE_ENTRY_CANDIDATES
        ),
        _episode_summary_search(user_id, query, limit),
    )

    hits = [
        EpisodeHit(date=date, text=entry.get("text", ""), time=entry.get("time"))
        for date, entry in entry_rows
    ]
    seen_dates = {hit.date for hit in hits}
    hits.extend(hit for hit in summary_hits if hit.date not in seen_dates)
    return hits[:limit]


async def _ann_search(user_id: str, query: str, timings: dict[str, int]) -> list[tuple[str, float]]:
    """Embed the query and run dense ANN over the user's latest memories."""
    stage = time.perf_counter()
    embedding = await embed_query(query)
    timings["embed_ms"] = _elapsed_ms(stage)

    stage = time.perf_counter()
    hits = await chroma_store.query_similar(user_id, embedding, ANN_CANDIDATES, only_latest=True)
    timings["ann_ms"] = _elapsed_ms(stage)
    return hits


async def _fts_search(
    user_id: str, query: str, timings: dict[str, int]
) -> list[tuple[MemoryRecord, float]]:
    """Weighted Postgres FTS over live memories."""
    stage = time.perf_counter()
    hits = await pg_store.fts_search(user_id, query, FTS_CANDIDATES)
    timings["fts_ms"] = _elapsed_ms(stage)
    return hits


def _rrf_fuse(*ranked_lists: list[str]) -> list[str]:
    """Reciprocal-rank fusion across ranked id lists, best fused score first."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    return sorted(scores, key=lambda item_id: scores[item_id], reverse=True)


async def _hydrate_candidates(
    user_id: str,
    fused_ids: list[str],
    fts_hits: list[tuple[MemoryRecord, float]],
    *,
    category_prefix: str | None,
    kinds: list[MemoryKind] | None,
) -> list[MemoryRecord]:
    """Resolve fused ids to rows (reusing FTS rows) and apply read-time filters.

    The read-time filter re-checks ``is_latest`` / ``is_forgotten`` /
    ``forget_after`` on the hydrated rows because Chroma metadata can lag
    Postgres by one flag update.
    """
    rows_by_id: dict[str, MemoryRecord] = {str(row.id): row for row, _ in fts_hits}
    missing = [memory_id for memory_id in fused_ids if memory_id not in rows_by_id]
    for row in await pg_store.get_memories_by_ids(user_id, missing):
        rows_by_id[str(row.id)] = row

    now = datetime.now(UTC)
    kind_values = {kind.value for kind in kinds} if kinds else None
    candidates: list[MemoryRecord] = []
    for memory_id in fused_ids:
        row = rows_by_id.get(memory_id)
        if row is None or not row.is_latest or row.is_forgotten:
            continue
        if row.forget_after is not None and row.forget_after <= now:
            continue
        if kind_values and row.kind not in kind_values:
            continue
        if category_prefix and not _in_category(row.category_path, category_prefix):
            continue
        candidates.append(row)
    return candidates


@dataclass
class _ScoredCandidate:
    """A candidate with its blended score and absolute-confidence verdict."""

    row: MemoryRecord
    score: float
    confident: bool


async def _rerank_and_boost(
    query: str,
    candidates: list[MemoryRecord],
    *,
    ann_similarity: dict[str, float],
    fts_ids: set[str],
) -> list[_ScoredCandidate]:
    """Blend cross-encoder relevance with retrieval rank, then apply boosts.

    The two signals are complementary and either alone fails on real queries:
    the cross-encoder misjudges some implicit pairs ("book a vet appointment"
    vs the dog fact) that dense retrieval ranks highly, and retrieval misses
    paraphrases the cross-encoder nails.

        base  = RERANK_BLEND_WEIGHT * rerank_norm
              + (1 - RERANK_BLEND_WEIGHT) * retrieval_norm
        final = base * recency_boost * importance_boost

    The retrieval signal is the candidate's normalized dense cosine (its real
    closeness), not its rank position — rank exaggerates hair-thin gaps when
    cosines cluster. FTS-only candidates (no cosine) fall back to their fused
    rank position. Each candidate also gets an absolute-confidence verdict
    (strong cosine, strong raw logit, or a keyword anchor) used to cap weak
    results downstream.
    """
    if not candidates:
        return []
    raw_scores = await rerank(query, [row.content for row in candidates])
    rerank_norm = _min_max_normalize(raw_scores)
    total = len(candidates)
    rank_fallback = [1.0 - (index / total) for index in range(total)]
    cosines = [ann_similarity.get(str(row.id)) for row in candidates]
    known = [value for value in cosines if value is not None]
    low, high = (min(known), max(known)) if known else (0.0, 0.0)
    span = (high - low) or 1.0
    retrieval_norm = [
        ((cosine - low) / span) if cosine is not None else rank_fallback[index]
        for index, cosine in enumerate(cosines)
    ]
    now = datetime.now(UTC)

    scored = [
        _ScoredCandidate(
            row=row,
            score=(RERANK_BLEND_WEIGHT * rr + (1.0 - RERANK_BLEND_WEIGHT) * rn)
            * _recency_boost(row, now)
            * _importance_boost(row),
            confident=(
                ann_similarity.get(str(row.id), 0.0) >= CONFIDENT_COSINE
                or raw >= CONFIDENT_RERANK_LOGIT
                or str(row.id) in fts_ids
            ),
        )
        for row, rr, rn, raw in zip(candidates, rerank_norm, retrieval_norm, raw_scores)
    ]
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def _cap_weak_results(scored: list[_ScoredCandidate]) -> list[tuple[MemoryRecord, float]]:
    """Keep all confident results but at most MAX_WEAK_RESULTS unproven ones.

    An unanswerable query produces only weak candidates, so it returns a couple
    of semi-related items at most instead of a full page of noise; a real
    query keeps its confident cluster untouched.
    """
    kept: list[tuple[MemoryRecord, float]] = []
    weak_kept = 0
    for item in scored:
        if not item.confident:
            if weak_kept >= MAX_WEAK_RESULTS:
                continue
            weak_kept += 1
        kept.append((item.row, item.score))
    return kept


def _min_max_normalize(scores: list[float]) -> list[float]:
    """Squash cross-encoder logits to [0, 1]; a degenerate range maps to 1.0."""
    low, high = min(scores), max(scores)
    if math.isclose(low, high):
        return [1.0] * len(scores)
    return [(score - low) / (high - low) for score in scores]


def _recency_boost(row: MemoryRecord, now: datetime) -> float:
    """Exponentially decayed bonus for recently mentioned memories."""
    mentioned = row.mentioned_at or row.created_at
    age_days = max((now - mentioned).total_seconds() / _SECONDS_PER_DAY, 0.0)
    return 1.0 + RECENCY_BOOST_WEIGHT * math.exp(-age_days / RECENCY_BOOST_DECAY_DAYS)


def _importance_boost(row: MemoryRecord) -> float:
    """Linear bonus for memories the extractor judged important."""
    return IMPORTANCE_BOOST_BASE + IMPORTANCE_BOOST_WEIGHT * row.importance


async def _with_graph_siblings(
    user_id: str,
    candidates: list[MemoryRecord],
    *,
    kinds: list[MemoryKind] | None,
) -> list[MemoryRecord]:
    """Add 1-hop entity siblings to the candidate pool (before reranking).

    The top ``GRAPH_EXPANSION_SOURCE_RESULTS`` candidates supply source
    entities; their other memories join the pool so the reranker scores them on
    real query relevance. A genuinely related sibling (another fact about the
    same person) ranks high and survives; an incidental one (the user's
    hometown, pulled in only because they co-occur on a fact) ranks low and is
    dropped. Siblings pass the ``kinds`` filter; crossing category boundaries is
    the point, so ``category_prefix`` is not applied here.
    """
    source_ids = [row.id for row in candidates[:GRAPH_EXPANSION_SOURCE_RESULTS]]
    entities_by_memory = await pg_store.get_entities_for_memories(source_ids)
    entity_ids = list(
        {entity.id for entities in entities_by_memory.values() for entity in entities}
    )
    if not entity_ids:
        return candidates
    siblings = await pg_store.get_memories_for_entities(
        user_id,
        entity_ids,
        exclude_memory_ids=[row.id for row in candidates],
        limit=GRAPH_EXPANSION_MAX_SIBLINGS,
        kinds=[kind.value for kind in kinds] if kinds else None,
    )
    return candidates + siblings


async def _build_entries(scored: list[tuple[MemoryRecord, float]]) -> list[MemoryEntry]:
    """Map reranked (record, score) pairs to API entries with their entities."""
    entities_by_memory = await pg_store.get_entities_for_memories([row.id for row, _ in scored])
    return [
        row_to_entry(row, entities_by_memory.get(row.id, []), relevance_score=round(score, 4))
        for row, score in scored
    ]


async def _episode_summary_search(user_id: str, query: str, limit: int) -> list[EpisodeHit]:
    """Semantic search over embedded day summaries."""
    embedding = await embed_query(query)
    hits = await chroma_store.query_episodes(user_id, embedding, limit)
    results: list[EpisodeHit] = []
    for episode_id, similarity in hits:
        episode_date = _episode_id_to_date(episode_id)
        if episode_date is None:
            continue
        episode = await pg_store.get_episode(user_id, episode_date)
        if episode is not None and episode.summary:
            results.append(
                EpisodeHit(date=episode_date, text=episode.summary, score=round(similarity, 4))
            )
    return results


def _episode_id_to_date(episode_id: str) -> date_type | None:
    """Parse the date out of a ``{user_id}:{YYYY-MM-DD}`` episode vector id."""
    try:
        return date_type.fromisoformat(episode_id.rsplit(":", 1)[-1])
    except ValueError:
        return None


def _tokenize(query: str) -> list[str]:
    """Lowercase alphanumeric tokens long enough to be meaningful."""
    return [
        token
        for token in _TOKEN_PATTERN.findall(query.lower())
        if len(token) >= EPISODE_SEARCH_MIN_TOKEN_LENGTH
    ]


def _drop_below_relevance(entries: list[MemoryEntry]) -> list[MemoryEntry]:
    """Trim the weak-match tail (and low-score graph siblings) below the cliff.

    Hybrid recall produces a sharp relevance cliff — a few strong matches, then
    a long tail of faintly-related facts. Injecting that tail into every prompt
    is noise: a query about a gift for the user's partner does not need their
    GitHub bio or hometown. Keep only results scoring at least
    ``RELEVANCE_DROPOFF_RATIO`` of the best hit (always keeps the top result).
    """
    if not entries:
        return entries
    top = entries[0].relevance_score or 0.0
    if top <= 0:
        return entries
    floor = top * RELEVANCE_DROPOFF_RATIO
    return [entry for entry in entries if (entry.relevance_score or 0.0) >= floor]


def _in_category(category_path: str, prefix: str) -> bool:
    """Whether a folder path sits at or under the given prefix."""
    return category_path == prefix or category_path.startswith(f"{prefix}/")


def _elapsed_ms(since: float) -> int:
    """Milliseconds elapsed since a perf_counter() reading."""
    return int((time.perf_counter() - since) * 1000)
