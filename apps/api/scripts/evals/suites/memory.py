"""Memory suite — ports the 45-scenario accuracy benchmark into the harness.

Reuses scripts.memory_benchmark wholesale instead of reimplementing it:
- dataset.SCENARIOS   — the 45 scenarios / 52 probes (10 weakness categories)
- runner.run_scenario — fresh UUID user per case, ingestion at injected day
  offsets (``_retain_at``), probes via memory_engine.recall, teardown
- runner._score_probe — the benchmark's own substring verdicts, re-applied in
  score() so the stored run is independently re-judged
- bootstrap — in-process Postgres/Chroma/Redis patch (no API server),
  replicated here because the benchmark's copy references a removed
  chroma_store attribute (see _bootstrap_dbs)

LLM lane: the memory write path (extraction / reconcile / episode summary)
always calls ``ainvoke_structured`` -> ``client.get_default_llm``, which is
hardcoded to Gemini. The harness pins the ``custom_llm`` lane per case via
``pin_settings`` instead, so this suite swaps that seam for the pinned
provider (see _patch_default_llm_to_pinned_provider).

Scoring is the benchmark's deterministic substring checks — no LLM judge, so
Opik finalize adds no judge cost.
"""

from __future__ import annotations

import asyncio

from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.runner import Suite, register_suite
from scripts.evals.core.types import Case, CaseRun

_BOOTSTRAPPED = False
_LLM_PATCHED = False


async def _bootstrap_dbs() -> None:
    """In-process Postgres/Chroma/Redis patch (mirrors memory_benchmark._bootstrap).

    The engine's accessors sit behind a lazy-provider registry that only
    initialises inside a live FastAPI app; monkeypatching them directly lets
    the suite run without the API server. Replicated here (not imported)
    because the benchmark's copy still clears the pre-refactor
    ``chroma_store._collections`` attribute, which no longer exists — the
    collection cache is now per event loop (``_loop_collections`` /
    ``_loop_locks``) and is what must be cleared so lookups re-bind to the
    patched client.
    """

    import chromadb
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config.settings import settings
    from app.constants.memory import (
        CHROMA_MEMORIES_COLLECTION,
        CHROMA_MEMORY_EPISODES_COLLECTION,
    )
    from app.db.chroma.chromadb import ChromaClient
    import app.db.postgresql as postgresql_module
    from app.db.redis import redis_cache
    from app.memory import chroma_store

    assert settings.POSTGRES_URL, "POSTGRES_URL must be set"
    url, connect_args = postgresql_module._adapt_url_for_asyncpg(settings.POSTGRES_URL)
    engine = create_async_engine(url, poolclass=NullPool, connect_args=connect_args)

    async with engine.begin() as conn:
        await conn.run_sync(postgresql_module.Base.metadata.create_all)

    async def _get_engine():
        await asyncio.sleep(0)
        return engine

    postgresql_module.get_postgresql_engine = _get_engine
    print("  [bootstrap] Postgres engine ready", flush=True)

    chroma_client = await chromadb.AsyncHttpClient(
        host=settings.CHROMADB_HOST, port=settings.CHROMADB_PORT
    )
    for name in (CHROMA_MEMORIES_COLLECTION, CHROMA_MEMORY_EPISODES_COLLECTION):
        await chroma_client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})

    async def _get_client(*_args: object, **_kwargs: object):
        await asyncio.sleep(0)
        return chroma_client

    ChromaClient.get_client = _get_client
    chroma_store._loop_collections.clear()
    chroma_store._loop_locks.clear()
    print("  [bootstrap] ChromaDB client ready", flush=True)

    from redis.asyncio import Redis

    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    await redis_client.ping()
    redis_cache.redis = redis_client
    print("  [bootstrap] Redis client ready", flush=True)

    from app.memory.embeddings import _embed_sync, _rerank_sync

    print("  [bootstrap] Warming fastembed models (first run downloads ONNX) ...", flush=True)
    _embed_sync(["warmup"])
    _rerank_sync("warmup", ["warmup document"])
    print("  [bootstrap] fastembed models ready", flush=True)


def _patch_default_llm_to_pinned_provider() -> None:
    """Route the default-model seam (memory's only LLM entry) to the pinned lane.

    ``ainvoke_structured`` builds its model via ``client.get_default_llm``,
    hardcoded to Gemini. The harness instead pins the ``custom_llm`` provider
    (DEV_LLM_* settings) before each transport call, so this factory swaps the
    seam: every memory LLM call lands on the pinned provider. The lazy
    registry caches the instance, and ``pin_settings`` resets it on rotation,
    so the build always reflects the active provider.
    """

    from langchain_core.language_models.chat_models import BaseChatModel

    import app.agents.llm.client as llm_client
    from app.agents.llm.exceptions import LLMNotConfiguredError
    from app.constants.llm import DEFAULT_LLM_TEMPERATURE
    from app.core.lazy_loader import providers

    def pinned_default_llm(*, temperature: float = DEFAULT_LLM_TEMPERATURE) -> BaseChatModel:
        del temperature  # the custom lane is built at the default temperature
        custom = providers.get("custom_llm")
        if custom is None:
            raise LLMNotConfiguredError(
                "custom_llm not available — DEV_LLM_BASE_URL / DEV_LLM_API_KEY / DEV_LLM_MODEL must be set"
            )
        return custom

    llm_client.get_default_llm = pinned_default_llm


def _patch_structured_output_for_pinned_lane() -> None:
    """Swap the memory module's structured-output seam to json-object mode.

    ``with_structured_output`` defaults to the function-calling method
    (``tool_choice``) on OpenAI-wire clients; the opencode-go lane runs in
    "thinking mode" and rejects ``tool_choice`` — and also
    ``response_format: json_schema`` — with a 400, so extraction would
    silently degrade to empty batches. Plain ``response_format:
    json_object`` is accepted, but requires the prompt to mention json and
    does not carry the schema, so this seam appends the schema as a system
    message and parses the content back into it. The app-level fix belongs
    in ``client.ainvoke_structured`` (lane-aware method choice); this patch
    targets the memory module's import-time binding, its only consumer here.
    """

    import json as json_module

    from langchain_core.messages import SystemMessage
    from langchain_core.output_parsers import JsonOutputParser

    from app.agents.llm.client import ainvoke_llm, get_default_llm
    from app.constants.llm import DEFAULT_LLM_TEMPERATURE, LLM_INVOKE_TIMEOUT_SECONDS
    import app.memory.extraction as extraction_mod

    async def json_object_ainvoke_structured(
        schema,
        prompt,
        *,
        label: str,
        temperature: float = DEFAULT_LLM_TEMPERATURE,
        config=None,
        timeout: float | None = LLM_INVOKE_TIMEOUT_SECONDS,
    ):
        schema_hint = SystemMessage(
            content=(
                "Reply with a single JSON object that conforms exactly to this JSON "
                f"schema, no markdown fences and no commentary:\n{json_module.dumps(schema.model_json_schema())}"
            )
        )
        messages = [*prompt, schema_hint] if isinstance(prompt, list) else [schema_hint, prompt]
        invoke_config = {
            **(config or {}),
            "configurable": {
                **(config or {}).get("configurable", {}),
                "model_kwargs": {"response_format": {"type": "json_object"}},
            },
        }
        message = await ainvoke_llm(
            get_default_llm(temperature=temperature),
            messages,
            config=invoke_config,
            label=label,
            timeout=timeout,
        )
        content = message.content
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return schema.model_validate(JsonOutputParser().parse(str(content)))

    extraction_mod.ainvoke_structured = json_object_ainvoke_structured


async def _ensure_ready(tracker: EvalCostTracker) -> None:
    """One-time process bootstrap: DB providers, LLM pin, token metering."""
    global _BOOTSTRAPPED, _LLM_PATCHED
    if not _BOOTSTRAPPED:
        await _bootstrap_dbs()
        _BOOTSTRAPPED = True
    if not _LLM_PATCHED:
        from app.agents.llm.client import register_llm_providers

        register_llm_providers()
        _patch_default_llm_to_pinned_provider()
        _patch_structured_output_for_pinned_lane()
        _LLM_PATCHED = True
    import app.memory.extraction as extraction_mod

    extraction_mod._SILENT_CONFIG = {**extraction_mod._SILENT_CONFIG, "callbacks": [tracker]}


@register_suite("memory")
class MemorySuite(Suite):
    name = "memory"
    project = "gaia-memory"
    label = "Memory"

    def __init__(self, cfg) -> None:
        del cfg
        self._scenarios: dict[str, dict] | None = None

    def _scenario(self, case_id: str) -> dict:
        if self._scenarios is None:
            from scripts.memory_benchmark.dataset import SCENARIOS

            self._scenarios = {scenario["id"]: scenario for scenario in SCENARIOS}
        return self._scenarios[case_id]

    def load_cases(self, cfg) -> list[Case]:
        del cfg
        from scripts.memory_benchmark.dataset import SCENARIOS

        cases: list[Case] = []
        for scenario in SCENARIOS:
            description = " | ".join(probe["description"] for probe in scenario["probes"])
            cases.append(
                Case(
                    id=scenario["id"],
                    ticket=(
                        f"{len(scenario['turns'])} turns, {len(scenario['probes'])} probes — {description}"
                    ),
                    prompt=f"[{scenario['category']}] {description}",
                    expected={
                        "category": scenario["category"],
                        "score": {"gates": ["probes"]},
                    },
                    tags=[scenario["category"]],
                )
            )
        return cases

    def transport(self, case: Case, cfg, tracker: EvalCostTracker, provider):
        return self._run(case, cfg, tracker, provider)

    async def _run(self, case: Case, cfg, tracker: EvalCostTracker, provider) -> CaseRun:
        del cfg
        await _ensure_ready(tracker)
        scenario = self._scenario(case.id)
        from scripts.memory_benchmark.runner import run_scenario

        tokens_in_before = tracker.total_input
        tokens_out_before = tracker.total_output
        results = await run_scenario(scenario)
        tokens_in = tracker.total_input - tokens_in_before
        tokens_out = tracker.total_output - tokens_out_before

        probes: list[dict] = []
        for result in results:
            probes.append(
                {
                    "query": result["probe"],
                    "description": result["description"],
                    "passed": result["passed"],
                    "recalled_text": result["recalled_text"],
                    "must_contain": result["must_contain"],
                    "must_not_contain": result["must_not_contain"],
                    "is_negative": result["is_negative"],
                }
            )

        messages = [
            {"role": turn["role"], "content": turn["content"]} for turn in scenario["turns"]
        ]
        for probe in probes:
            messages.append({"role": "user", "content": probe["query"]})
            messages.append({"role": "assistant", "content": probe["recalled_text"]})

        passed = sum(1 for probe in probes if probe["passed"])
        return CaseRun(
            case_id=case.id,
            provider=provider.name,
            model=provider.model,
            messages=messages,
            tool_calls=[],
            end_state={"probes": probes},
            text=f"{passed}/{len(probes)} probes passed",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        from scripts.memory_benchmark.runner import _score_probe

        probes = (run.end_state or {}).get("probes", [])
        scores: dict[str, float] = {}
        for index, probe in enumerate(probes, start=1):
            passed, _, _ = _score_probe(probe["recalled_text"], probe)
            scores[f"{case.id}_p{index}"] = 1.0 if passed else 0.0
        if scores:
            scores["probes"] = sum(scores.values()) / len(scores)
        return scores

    def finalize_scorers(self, cfg) -> list:
        del cfg
        # Memory verdicts are the benchmark's deterministic substring checks,
        # already applied at runtime and journaled per probe. An LLM judge
        # would add cost without information, so Opik finalize stays free.
        return []
