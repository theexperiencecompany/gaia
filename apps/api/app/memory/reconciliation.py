"""Dedupe/supersession decisions for newly extracted facts.

Per fact: the nearest existing memories from Chroma split the work. A fact
with no neighbor above the reconcile threshold is NEW (no LLM). A fact whose
nearest neighbor is byte-identical text is a DUPLICATE (no LLM). Everything
else — including near-identical facts that differ only in a value (a changed
date, place, or number) — goes to one batched reconcile LLM call, which is
the only thing allowed to decide UPDATES vs EXTENDS vs DUPLICATE. Similarity
alone never auto-drops a fact, so an update is never silently lost.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import re

from app.constants.memory import (
    DUPLICATE_SIMILARITY_THRESHOLD,
    RECONCILE_CANDIDATES,
    RECONCILE_SIMILARITY_THRESHOLD,
    ReconcileOutcome,
)
from app.memory import chroma_store, pg_store
from app.memory.extraction import SimilarMemory, reconcile_facts
from app.memory.schemas import ExtractedFact

_WHITESPACE = re.compile(r"\s+")


def _normalize(content: str) -> str:
    """Casefold, collapse whitespace, and strip outer punctuation for matching."""
    return _WHITESPACE.sub(" ", content.strip().casefold()).strip(" .!?,;:")


@dataclass
class ReconciledFact:
    """An extracted fact with its verdict against the existing store."""

    fact: ExtractedFact
    embedding: list[float]
    outcome: ReconcileOutcome
    target_memory_id: str | None = None


async def reconcile(
    user_id: str,
    facts: list[ExtractedFact],
    embeddings: list[list[float]],
) -> list[ReconciledFact]:
    """Decide NEW/UPDATES/EXTENDS/DUPLICATE for each fact, in input order."""
    if not facts:
        return []

    # One concurrent Chroma scatter rather than N serial roundtrips.
    similar_lists = await asyncio.gather(
        *(
            chroma_store.query_similar(user_id, embedding, n=RECONCILE_CANDIDATES, only_latest=True)
            for embedding in embeddings
        )
    )

    results: list[ReconciledFact | None] = [None] * len(facts)
    ambiguous: list[tuple[int, list[tuple[str, float]]]] = []
    for index, similar in enumerate(similar_lists):
        if similar and similar[0][1] >= RECONCILE_SIMILARITY_THRESHOLD:
            ambiguous.append((index, similar))
        else:
            results[index] = ReconciledFact(
                fact=facts[index], embedding=embeddings[index], outcome=ReconcileOutcome.NEW
            )

    if ambiguous:
        decided = await _reconcile_ambiguous(user_id, facts, embeddings, ambiguous)
        for index, reconciled in decided.items():
            results[index] = reconciled

    return [reconciled for reconciled in results if reconciled is not None]


async def _reconcile_ambiguous(
    user_id: str,
    facts: list[ExtractedFact],
    embeddings: list[list[float]],
    ambiguous: list[tuple[int, list[tuple[str, float]]]],
) -> dict[int, ReconciledFact]:
    """Resolve the close-match band: exact-text duplicates cheaply, the rest via one LLM call."""
    candidate_ids = list(
        {
            memory_id
            for _, similar in ambiguous
            for memory_id, similarity in similar
            if similarity >= RECONCILE_SIMILARITY_THRESHOLD
        }
    )
    candidate_rows = {
        str(row.id): row for row in await pg_store.get_memories_by_ids(user_id, candidate_ids)
    }
    now = datetime.now(UTC)

    decided: dict[int, ReconciledFact] = {}
    pairs: list[tuple[ExtractedFact, list[SimilarMemory]]] = []
    llm_fact_indexes: list[int] = []
    allowed_ids_per_pair: list[set[str]] = []

    for index, similar in ambiguous:
        candidates: list[SimilarMemory] = []
        exact_target: str | None = None
        normalized_fact = _normalize(facts[index].content)
        for memory_id, similarity in similar:
            row = candidate_rows.get(memory_id)
            if row is None or similarity < RECONCILE_SIMILARITY_THRESHOLD:
                continue
            # Byte-identical text at high similarity collapses without the LLM.
            if (
                exact_target is None
                and similarity >= DUPLICATE_SIMILARITY_THRESHOLD
                and _normalize(row.content) == normalized_fact
            ):
                exact_target = memory_id
            candidates.append(
                SimilarMemory(
                    id=memory_id,
                    content=row.content,
                    age_days=max((now - row.created_at).days, 0),
                )
            )

        if exact_target is not None:
            decided[index] = ReconciledFact(
                fact=facts[index],
                embedding=embeddings[index],
                outcome=ReconcileOutcome.DUPLICATE,
                target_memory_id=exact_target,
            )
            continue

        pairs.append((facts[index], candidates))
        llm_fact_indexes.append(index)
        allowed_ids_per_pair.append({candidate.id for candidate in candidates})

    if not pairs:
        return decided

    batch = await reconcile_facts(pairs)
    for pair_index, decision in enumerate(batch.decisions):
        fact_index = llm_fact_indexes[pair_index]
        outcome = decision.decision
        target = decision.target_memory_id
        # An LLM target outside the candidate set is hallucinated — fall back to NEW.
        if outcome is not ReconcileOutcome.NEW and target not in allowed_ids_per_pair[pair_index]:
            outcome, target = ReconcileOutcome.NEW, None
        decided[fact_index] = ReconciledFact(
            fact=facts[fact_index],
            embedding=embeddings[fact_index],
            outcome=outcome,
            target_memory_id=target,
        )
    return decided
