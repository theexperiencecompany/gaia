"""Dedupe/supersession decisions for newly extracted facts.

Per fact: nearest existing memories from Chroma decide the cheap cases
(near-identical → DUPLICATE without an LLM; nothing close → NEW). Only the
ambiguous middle band goes to one batched reconcile LLM call.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.constants.memory import (
    DUPLICATE_SIMILARITY_THRESHOLD,
    RECONCILE_CANDIDATES,
    RECONCILE_SIMILARITY_THRESHOLD,
    ReconcileOutcome,
)
from app.memory import chroma_store, pg_store
from app.memory.extraction import SimilarMemory, reconcile_facts
from app.memory.schemas import ExtractedFact


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
    results: list[ReconciledFact | None] = [None] * len(facts)
    ambiguous: list[tuple[int, list[tuple[str, float]]]] = []

    for index, (fact, embedding) in enumerate(zip(facts, embeddings)):
        similar = await chroma_store.query_similar(
            user_id, embedding, n=RECONCILE_CANDIDATES, only_latest=True
        )
        if similar and similar[0][1] >= DUPLICATE_SIMILARITY_THRESHOLD:
            results[index] = ReconciledFact(
                fact=fact,
                embedding=embedding,
                outcome=ReconcileOutcome.DUPLICATE,
                target_memory_id=similar[0][0],
            )
        elif similar and similar[0][1] >= RECONCILE_SIMILARITY_THRESHOLD:
            ambiguous.append((index, similar))
        else:
            results[index] = ReconciledFact(
                fact=fact, embedding=embedding, outcome=ReconcileOutcome.NEW
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
    """One batched LLM call over all facts that have close-but-not-identical matches."""
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

    pairs: list[tuple[ExtractedFact, list[SimilarMemory]]] = []
    allowed_ids_per_pair: list[set[str]] = []
    for index, similar in ambiguous:
        candidates: list[SimilarMemory] = []
        for memory_id, similarity in similar:
            row = candidate_rows.get(memory_id)
            if row is None or similarity < RECONCILE_SIMILARITY_THRESHOLD:
                continue
            candidates.append(
                SimilarMemory(
                    id=memory_id,
                    content=row.content,
                    age_days=max((now - row.created_at).days, 0),
                )
            )
        pairs.append((facts[index], candidates))
        allowed_ids_per_pair.append({candidate.id for candidate in candidates})

    batch = await reconcile_facts(pairs)

    decided: dict[int, ReconciledFact] = {}
    for pair_index, decision in enumerate(batch.decisions):
        fact_index = ambiguous[pair_index][0]
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
