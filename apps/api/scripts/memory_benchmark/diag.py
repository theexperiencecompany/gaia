"""Diagnose the 4 failing memory scenarios: what got STORED vs what recall RETURNS.

Usage: uv run --group backend python scripts/memory_benchmark/diag.py
Prints, per scenario: the stored memories after retain (proves extraction),
then the raw recall pipeline stages (ANN hits, FTS hits, fused, rerank scores,
post-dropoff entries) for each probe.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid

sys.path.insert(0, ".")

from datetime import timedelta

from app.memory.engine import memory_engine
from scripts.memory_benchmark.dataset import SCENARIOS
from scripts.memory_benchmark.runner import BASE_DATE, _retain_at

TARGETS = {
    "tr_02_recent_vs_old",
    "tr_04_subscription_expiry",
    "cu_04_relationship_status",
    "dr_04_three_addresses",
}


async def _diag_recall(user_id: str, query: str) -> None:
    import app.memory.retrieval as ret

    started = time.perf_counter()
    ann_hits, fts_hits = await asyncio.gather(
        ret._ann_search(user_id, query, {}),
        ret._fts_search(user_id, query, {}),
    )
    print(f"    ANN hits: {[(str(m)[:8], round(s, 3)) for m, s in ann_hits[:5]]}")
    print(f"    FTS hits: {[(str(i.id)[:8], round(s, 3)) for i, s in fts_hits[:5]]}")
    if ann_hits:
        from app.memory import pg_store as _pg

        rows = await _pg.get_memories_by_ids(user_id, [str(m) for m, _ in ann_hits])
        print(
            f"    pg rows for ANN ids: {[(str(r.id)[:8], r.is_latest, r.is_forgotten, r.forget_after) for r in rows]}"
        )
        recent = await _pg.get_recent_facts(user_id, limit=50)
        print(f"    pg recent facts: {len(recent)}")
    fused = ret._rrf_fuse([mid for mid, _ in ann_hits], [str(i.id) for i, _ in fts_hits])
    print(f"    fused ids: {[f[:8] for f in fused[:6]]}")
    candidates = await ret._hydrate_candidates(
        user_id, fused, fts_hits, category_prefix=None, kinds=None
    )
    print(f"    candidates: {len(candidates)} -> {[str(c.id)[:8] for c in candidates[:6]]}")
    scored = await ret._rerank_and_boost(
        query, candidates, ann_similarity=dict(ann_hits), fts_ids={str(r.id) for r, _ in fts_hits}
    )
    for c in scored[:6]:
        print(
            f"    rerank {str(c.row.id)[:8]} -> {round(c.score, 4)} confident={c.confident} | {c.row.content[:70]!r}"
        )
    kept = ret._cap_weak_results(scored)
    entries = await ret._build_entries(kept)
    entries = ret._drop_below_relevance(entries)
    print(f"    final entries ({len(entries)}):")
    for e in entries:
        print(f"      {e.relevance_score} | {e.content[:80]!r}")
    print(f"    recall total: {time.perf_counter() - started:.2f}s")


async def main() -> None:
    from app.agents.llm.client import register_llm_providers
    from app.core.lazy_loader import providers
    from app.core.provider_registration import register_lazy_providers

    register_lazy_providers("diag")
    await providers.initialize_auto_providers(strict=False)
    register_llm_providers()
    from scripts.evals.suites.memory import _patch_default_llm_to_pinned_provider

    _patch_default_llm_to_pinned_provider()

    # Freeze the read-path clock at the benchmark base date, same as the suite
    # runner does — dated facts (forget_after) would otherwise look forgotten
    # against the wall clock.
    import app.memory.management as management_mod
    import app.memory.pg_store.memories as memories_mod
    import app.memory.retrieval as retrieval_mod
    from scripts.memory_benchmark.runner import _make_fake_datetime

    _read_clock_modules = (retrieval_mod, management_mod, memories_mod)
    _original_datetimes = {mod: mod.datetime for mod in _read_clock_modules}
    fake_now = _make_fake_datetime(BASE_DATE)
    for mod in _read_clock_modules:
        mod.datetime = fake_now

    try:
        for scenario in SCENARIOS:
            if scenario["id"] not in TARGETS:
                continue
            user_id = str(uuid.uuid4())
            print(f"\n{'=' * 70}\n{scenario['id']} ({scenario['category']})")
            try:
                offset: int | None = None
                session: list[dict[str, str]] = []
                for turn in scenario["turns"]:
                    off = turn.get("day_offset", 0)
                    if offset is not None and off != offset:
                        await _retain_at(user_id, session, BASE_DATE + timedelta(days=offset))
                        session = []
                    offset = off
                    session.append({"role": turn["role"], "content": turn["content"]})
                if session:
                    await _retain_at(user_id, session, BASE_DATE + timedelta(days=offset or 0))

                stored = await memory_engine.list_memories(user_id, page=1, page_size=50)
                print(f"  STORED ({len(stored.memories)}):")
                for m in stored.memories:
                    print(
                        f"    {m.id[:8]} | {m.content[:90]!r} | kind={m.kind} cat={m.category_path}"
                    )
            except Exception as exc:
                print(f"  RETAIN FAILED: {type(exc).__name__}: {exc}")
            for probe in scenario["probes"]:
                print(f"  PROBE: {probe['query']!r}")
                try:
                    await _diag_recall(user_id, probe["query"])
                except Exception as exc:
                    import traceback

                    traceback.print_exc()
                    print(f"    RECALL FAILED: {type(exc).__name__}: {exc}")
            await memory_engine.delete_all(user_id=user_id)
    finally:
        for mod in _read_clock_modules:
            mod.datetime = _original_datetimes[mod]


if __name__ == "__main__":
    asyncio.run(main())
