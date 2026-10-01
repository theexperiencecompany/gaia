"""Hybrid recall — the zero-LLM read path (plan F3, target <150ms P95).

recall fuses dense ANN (Chroma) and weighted FTS (Postgres) with RRF,
cross-encoder reranks the fused candidates, blends recency and importance
boosts, and optionally expands one hop through the entity graph.

Episode journal lines are deliberately NOT fused into recall: they are
activity logs, not atomic facts, and surfacing them as pseudo-memories would
pollute the contract (no lineage, no category, no importance). Tools that
want "when did I last talk about X" use recall_episodes instead, which
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

import httpx

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
    TRANSCRIPT_RECALL_LIMIT,
    MemoryKind,
    MemoryRelationType,
)
from app.db.redis import delete_cache
from app.decorators.caching import Cacheable
from app.memory import chroma_store, pg_store
from app.memory.embeddings import embed_query, rerank
from app.memory.mappers import row_to_entry
from app.memory.pg_store.episodes import entry_text
from app.memory.user_time import local_today
from app.models.memory_db_models import MemoryRecord
from app.models.memory_models import MemoryEntry, MemorySearchResult
from shared.py.wide_events import MemoryContext, UserContext, log

_SECONDS_PER_DAY = 86_400.0
_TOKEN_PATTERN = re.compile(r"[a-z0-9']+")


@dataclass
class EpisodeHit:
    """One journal match: a verbatim entry line or a semantic day summary."""

    date: date_type
    text: str
    time: str | None = None
    score: float | None = None


def _recall_cache_key(
    _func_name: str,
    user_id: str,
    query: str,
    *,
    limit: int = DEFAULT_RECALL_LIMIT,
    category_prefix: str | None = None,
    kinds: list[MemoryKind] | None = None,
    include_graph_expansion: bool = True,
) -> str:
    """Build the cache key for recall: user:{id}:memories:{digest}.

    The prefix must match MEMORY_SEARCH_CACHE_PATTERN, invalidated on every
    ingestion. All non-user parameters are digested so calls differing in
    any knob never collide.
    """
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
    timings["hydrate_ms"] = _elapsed_ms(stage)

    stage = time.perf_counter()
    siblings = (
        await _graph_siblings(user_id, candidates, kinds=kinds)
        if include_graph_expansion and candidates
        else []
    )
    # The rerank budget caps the BASE pool only (capping the combined pool would
    # drop siblings once base fills the budget) and never below the caller's
    # limit, so a 20-result search is not truncated; chat asks for 8 and keeps it.
    candidates = candidates[: max(RERANK_CANDIDATES, limit)] + siblings
    timings["siblings_ms"] = _elapsed_ms(stage)

    stage = time.perf_counter()
    # Rerank the combined base+sibling pool together so siblings compete on real
    # query relevance, not a fixed score; the dropoff then cuts the weak tail.
    ann_similarity = dict(ann_hits)
    fts_ids = {str(row.id) for row, _ in fts_hits}
    scored = await _rerank_and_boost(
        query, candidates, ann_similarity=ann_similarity, fts_ids=fts_ids
    )
    timings["rerank_ms"] = _elapsed_ms(stage)

    kept = _cap_weak_results(_drop_below_relevance(scored))[:limit]
    stage = time.perf_counter()
    entries = await _build_entries(kept)
    timings["build_ms"] = _elapsed_ms(stage)

    timings["total_ms"] = _elapsed_ms(started)
    log.set(
        user=UserContext(id=user_id),
        memory=MemoryContext(
            operation="recall",
            query=query,
            result_count=len(entries),
            ann_hits=len(ann_hits),
            fts_hits=len(fts_hits),
            candidate_count=len(candidates),
            success=True,
            timings={key: float(value) for key, value in timings.items()},
        ),
    )
    return MemorySearchResult(memories=entries, total_count=len(entries))


async def recall_episodes(
    user_id: str,
    query: str,
    limit: int = DEFAULT_EPISODE_RECALL_LIMIT,
) -> list[EpisodeHit]:
    """Search the journal: verbatim recent entries first, then day summaries.

    Entry hits (token ILIKE over the last EPISODE_SEARCH_DAYS days) are
    exact evidence of recent activity, so they outrank semantic summary hits,
    which extend coverage to any past day whose rollover summary matches.
    """
    tokens = _tokenize(query)
    # Journal days are keyed by the user's LOCAL date (user_time.py); a UTC
    # anchor started the window a day early/late at timezone edges and could
    # exclude the newest local day entirely.
    since = await local_today(user_id) - timedelta(days=EPISODE_SEARCH_DAYS)
    entry_rows, summary_hits = await asyncio.gather(
        pg_store.search_episode_entries(
            user_id, tokens, since=since, limit=EPISODE_ENTRY_CANDIDATES
        ),
        _episode_summary_search(user_id, query, limit),
    )

    hits = [_episode_hit(date, entry) for date, entry in entry_rows]
    seen_dates = {hit.date for hit in hits}
    hits.extend(hit for hit in summary_hits if hit.date not in seen_dates)
    return hits[:limit]


def _episode_hit(date: date_type, entry: pg_store.EpisodeEntry) -> EpisodeHit:
    """Return one journal match carrying its date; old rows can lack a time."""
    return EpisodeHit(date=date, text=entry_text(entry), time=entry.get("time"))


async def _embed_query_interactive(query: str) -> list[float] | None:
    """Embed a recall query, or None when the sidecar failed fast.

    Recall runs on the user's turn, so a slow or overloaded embedding sidecar
    degrades to the FTS leg alone (None here) instead of holding or failing the
    turn: a degraded order beats no memories. Mirrors _rerank_scores.
    """
    try:
        return await embed_query(query, interactive=True)
    except (httpx.HTTPError, TimeoutError) as exc:
        log.warning(
            "memory_embed_query_skipped",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return None


async def _ann_search(user_id: str, query: str, timings: dict[str, int]) -> list[tuple[str, float]]:
    """Embed the query and run dense ANN over the user's latest memories.

    Returns no ANN hits when the embedding sidecar failed fast, so recall
    degrades to FTS-only rather than failing the turn.
    """
    stage = time.perf_counter()
    embedding = await _embed_query_interactive(query)
    timings["embed_ms"] = _elapsed_ms(stage)
    if embedding is None:
        return []

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

    The read-time filter re-checks is_latest / is_forgotten /
    forget_after on the hydrated rows because Chroma metadata can lag
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
    """A candidate with its blended relevance, boosted score, and confidence verdict.

    base is the blended pre-boost relevance and decides ordering together
    with the boosts folded into score; relevance is the cross-encoder's
    calibrated (sigmoid) verdict alone and decides survival against the
    relevance dropoff — the blend's cosine leg is proportional to the pool's
    best cosine, which floors every candidate high and cannot tell an
    incidental graph sibling from a real answer the way the absolute
    cross-encoder signal can.
    """

    row: MemoryRecord
    base: float
    relevance: float
    score: float
    confident: bool


async def _rerank_and_boost(
    query: str,
    candidates: list[MemoryRecord],
    *,
    ann_similarity: dict[str, float],
    fts_ids: set[str],
) -> list[_ScoredCandidate]:
    """Blend cross-encoder relevance with retrieval rank (base), then apply recency/importance boosts.

    Both normalizations are absolute-preserving (sigmoid logit; cosine over
    the pool's best), not min-max, so a hair-thin gap doesn't get stretched
    past the relevance dropoff. Each candidate also gets a confidence verdict
    (strong cosine/logit or a keyword anchor) used to cap weak results downstream.
    """
    if not candidates:
        return []
    raw_scores = await _rerank_scores(query, [row.content for row in candidates])
    total = len(candidates)
    rank_fallback = [1.0 - (index / total) for index in range(total)]
    cosines = [ann_similarity.get(str(row.id)) for row in candidates]
    known = [value for value in cosines if value is not None]
    top_cosine = max(known) if known else 0.0  # pragma: no mutate — dead else: never read
    retrieval_norm = [
        ((cosine / top_cosine) if top_cosine > 0 else 0.0)
        if cosine is not None
        else rank_fallback[index]
        for index, cosine in enumerate(cosines)
    ]
    now = datetime.now(UTC)

    scored: list[_ScoredCandidate] = []
    for index, row in enumerate(candidates):
        retrieval_score = retrieval_norm[index]
        if raw_scores is not None:
            raw = raw_scores[index]
            relevance = _sigmoid(raw)
            base = RERANK_BLEND_WEIGHT * relevance + (1.0 - RERANK_BLEND_WEIGHT) * retrieval_score
            rerank_confident = raw >= CONFIDENT_RERANK_LOGIT
        else:
            # Sidecar failed fast on this turn: rank by dense+FTS retrieval alone
            # rather than block the turn. A degraded order beats no memories.
            relevance = retrieval_score
            base = retrieval_score
            rerank_confident = False
        scored.append(
            _ScoredCandidate(
                row=row,
                base=base,
                relevance=relevance,
                score=base * _recency_boost(row, now) * _importance_boost(row),
                confident=(
                    ann_similarity.get(str(row.id), 0.0) >= CONFIDENT_COSINE
                    or rerank_confident
                    or str(row.id) in fts_ids
                ),
            )
        )
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


async def _rerank_scores(query: str, documents: list[str]) -> list[float] | None:
    """Cross-encoder scores for recall, or None when the sidecar failed fast.

    Recall runs on the user's turn, so a slow or overloaded sidecar degrades to
    retrieval-order ranking (None here) instead of holding the turn.
    """
    try:
        return await rerank(query, documents, interactive=True)
    except (httpx.HTTPError, TimeoutError) as exc:
        log.warning(
            "memory_rerank_skipped",
            error=str(exc),
            error_type=type(exc).__name__,
            document_count=len(documents),
        )
        return None


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


def _sigmoid(logit: float) -> float:
    """Calibrated 0-1 relevance from a cross-encoder logit (numerically stable)."""
    if logit >= 0:  # pragma: no mutate — at 0 both branches yield exactly 0.5
        return 1.0 / (1.0 + math.exp(-logit))
    exp_logit = math.exp(logit)
    return exp_logit / (1.0 + exp_logit)


def _recency_boost(row: MemoryRecord, now: datetime) -> float:
    """Exponentially decayed bonus for recently mentioned memories."""
    mentioned = row.mentioned_at or row.created_at
    age_days = max((now - mentioned).total_seconds() / _SECONDS_PER_DAY, 0.0)
    return 1.0 + RECENCY_BOOST_WEIGHT * math.exp(-age_days / RECENCY_BOOST_DECAY_DAYS)


def _importance_boost(row: MemoryRecord) -> float:
    """Linear bonus for memories the extractor judged important."""
    return IMPORTANCE_BOOST_BASE + IMPORTANCE_BOOST_WEIGHT * row.importance


async def _graph_siblings(
    user_id: str,
    candidates: list[MemoryRecord],
    *,
    kinds: list[MemoryKind] | None,
) -> list[MemoryRecord]:
    """1-hop entity siblings for the candidate pool, excluding the pool itself.

    The top GRAPH_EXPANSION_SOURCE_RESULTS candidates supply source entities;
    their other memories join the pool so the reranker scores them on real
    query relevance. Siblings pass the kinds filter, but not category_prefix,
    since crossing category boundaries is the point.
    """
    source_ids = [row.id for row in candidates[:GRAPH_EXPANSION_SOURCE_RESULTS]]
    entities_by_memory = await pg_store.get_entities_for_memories(source_ids)
    entity_ids = list(
        {entity.id for entities in entities_by_memory.values() for entity in entities}
    )
    if not entity_ids:
        return []
    return await pg_store.get_memories_for_entities(
        user_id,
        entity_ids,
        exclude_memory_ids=[row.id for row in candidates],
        limit=GRAPH_EXPANSION_MAX_SIBLINGS,
        kinds=[kind.value for kind in kinds] if kinds else None,
    )


async def _build_entries(scored: list[tuple[MemoryRecord, float]]) -> list[MemoryEntry]:
    """Map reranked (record, score) pairs to API entries with their entities.

    A superseded entry also carries its parent's content (previous_content),
    unless that parent is forgotten or expired — deleted content must never
    ride back into the prompt via its successor.
    """
    parent_ids = [
        str(row.parent_id)
        for row, _ in scored
        if row.parent_id is not None and row.relation_type == MemoryRelationType.UPDATES.value
    ]
    parents: dict[str, MemoryRecord] = {}
    if parent_ids:
        user_id = scored[0][0].user_id
        now = datetime.now(UTC)
        # Independent lookups: gather them into one round instead of two.
        entities_by_memory, parent_rows = await asyncio.gather(
            pg_store.get_entities_for_memories([row.id for row, _ in scored]),
            pg_store.get_memories_by_ids(user_id, parent_ids),
        )
        parents = {
            str(parent.id): parent
            for parent in parent_rows
            if not parent.is_forgotten
            and (parent.forget_after is None or parent.forget_after > now)
        }
    else:
        entities_by_memory = await pg_store.get_entities_for_memories([row.id for row, _ in scored])
    entries = []
    for row, score in scored:
        entry = row_to_entry(
            row, entities_by_memory.get(row.id, []), relevance_score=round(score, 4)
        )
        parent = parents.get(str(row.parent_id)) if row.parent_id else None
        if parent is not None:
            entry.previous_content = parent.content
        entries.append(entry)
    return entries


async def recall_transcripts(
    user_id: str,
    query: str,
    limit: int = TRANSCRIPT_RECALL_LIMIT,
) -> list[tuple[str, str, float]]:
    """Search raw conversation chunks: (date, chunk_text, similarity), best first.

    The verbatim tier behind recall: when the user references an exact
    detail from a past conversation ("that list you gave me", "the move you
    suggested"), the compressed fact store may not hold it but the transcript
    chunk does.
    """
    embedding = await _embed_query_interactive(query)
    if embedding is None:
        return []
    return await chroma_store.query_conversation_chunks(user_id, embedding, limit)


async def _episode_summary_search(user_id: str, query: str, limit: int) -> list[EpisodeHit]:
    """Semantic search over embedded day summaries."""
    embedding = await _embed_query_interactive(query)
    if embedding is None:
        return []
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
    """Parse the date out of a {user_id}:{YYYY-MM-DD} episode vector id."""
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


def _drop_below_relevance(scored: list[_ScoredCandidate]) -> list[_ScoredCandidate]:
    """Trim the weak-match tail (and low-score graph siblings) below the relevance cliff.

    Survives on the CROSS-ENCODER's calibrated relevance, not the blended or
    boosted score: the blend's cosine leg floors every candidate high
    (measured: an off-topic sibling kept 72% blended base at 9% relevance).
    A CONFIDENT candidate is never dropped regardless of relevance.
    """
    if not scored:
        return scored
    top = max(item.relevance for item in scored)
    if top <= 0:
        return scored
    floor = top * RELEVANCE_DROPOFF_RATIO
    return [item for item in scored if item.confident or item.relevance >= floor]


def _in_category(category_path: str, prefix: str) -> bool:
    """Whether a folder path sits at or under the given prefix."""
    return category_path == prefix or category_path.startswith(f"{prefix}/")


def _elapsed_ms(since: float) -> int:
    """Milliseconds elapsed since a perf_counter() reading."""
    return int((time.perf_counter() - since) * 1000)
