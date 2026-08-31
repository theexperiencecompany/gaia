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
from collections.abc import Awaitable
from typing import ClassVar, TypedDict, TypeVar, cast
from urllib.parse import urlsplit

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.gates import SELF_SCORED, ExtraGates, validate_gates
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import Suite, register_suite
from scripts.evals.core.types import Case, CaseRun

#: The memory module's structured-output seam is generic over the schema it is
#: handed and returns an instance of exactly that model.
SchemaT = TypeVar("SchemaT", bound=BaseModel)


class Turn(TypedDict):
    role: str
    content: str
    day_offset: int


class Probe(TypedDict):
    query: str
    must_contain: list[str]
    must_not_contain: list[str]
    description: str
    is_negative: bool


class Scenario(TypedDict):
    """One ``memory_benchmark.dataset`` entry, as this suite consumes it.

    The benchmark declares ``SCENARIOS: list[dict]``, which checks nothing. This
    names the keys the suite actually reads so a dataset change that drops one
    is a type error here rather than a ``KeyError`` mid-run.
    """

    id: str
    category: str
    turns: list[Turn]
    probes: list[Probe]


class ProbeResult(TypedDict):
    """One probe's outcome, as ``memory_benchmark.runner.run_scenario`` returns it."""

    probe: str
    description: str
    passed: bool
    recalled_text: str
    must_contain: list[str]
    must_not_contain: list[str]
    is_negative: bool


_BOOTSTRAPPED = False
_LLM_PATCHED = False


#: Hosts a memory-suite run is allowed to create schema in and write 45
#: scenarios' worth of rows to. Anything else is someone's real data.
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "host.docker.internal")


def _is_local(target: str) -> bool:
    host = urlsplit(target if "//" in target else f"//{target}").hostname or target
    return host in _LOCAL_HOSTS


def _refuse_non_development_target(env: str, postgres_url: str, chroma_host: str) -> None:
    """Refuse to bootstrap against anything but a local development stack.

    ``_bootstrap_dbs`` runs ``Base.metadata.create_all`` and creates Chroma
    collections, and the suite then writes memory rows for 45 scenarios. Pointed
    at a staging or production environment by a stale shell, it would do all of
    that to real user data — silently, because none of those calls fail on a
    healthy database.
    """
    if env == "development" and _is_local(postgres_url) and _is_local(chroma_host):
        return
    raise RuntimeError(
        "memory suite refuses to bootstrap a non-development target — it creates "
        f"schema and writes scenario data. ENV={env!r}, postgres host="
        f"{urlsplit(postgres_url).hostname!r}, chroma host={chroma_host!r}. "
        "Point POSTGRES_URL and CHROMADB_HOST at a local stack and set ENV=development."
    )


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
    from chromadb.api import AsyncClientAPI
    from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
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

    if not settings.POSTGRES_URL:
        raise RuntimeError("POSTGRES_URL must be set to run the memory suite")
    _refuse_non_development_target(settings.ENV, settings.POSTGRES_URL, settings.CHROMADB_HOST)
    url, connect_args = postgresql_module._adapt_url_for_asyncpg(settings.POSTGRES_URL)
    engine = create_async_engine(url, poolclass=NullPool, connect_args=connect_args)

    async with engine.begin() as conn:
        await conn.run_sync(postgresql_module.Base.metadata.create_all)

    async def _get_engine() -> AsyncEngine:
        await asyncio.sleep(0)
        return engine

    postgresql_module.get_postgresql_engine = _get_engine
    print("  [bootstrap] Postgres engine ready", flush=True)

    chroma_client = await chromadb.AsyncHttpClient(
        host=settings.CHROMADB_HOST, port=settings.CHROMADB_PORT
    )
    for name in (CHROMA_MEMORIES_COLLECTION, CHROMA_MEMORY_EPISODES_COLLECTION):
        await chroma_client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})

    async def _get_client(*_args: object, **_kwargs: object) -> AsyncClientAPI:
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

    from app.agents.llm.client import (
        LLMInvokeOptions,
        StructuredCallOptions,
        ainvoke_llm,
        get_default_llm,
    )
    import app.memory.extraction as extraction_mod

    async def json_object_ainvoke_structured(
        schema: type[SchemaT],
        prompt: BaseMessage | list[BaseMessage],
        *,
        label: str,
        config: RunnableConfig | None = None,
        options: StructuredCallOptions = StructuredCallOptions(),
    ) -> SchemaT:
        temperature = options.temperature
        timeout = options.timeout
        schema_hint = SystemMessage(
            content=(
                "Reply with a single JSON object that conforms exactly to this JSON "
                f"schema, no markdown fences and no commentary:\n{json_module.dumps(schema.model_json_schema())}"
            )
        )
        messages = [*prompt, schema_hint] if isinstance(prompt, list) else [schema_hint, prompt]
        invoke_config = cast(
            RunnableConfig,
            {
                **(config or {}),
                "configurable": {
                    **(config or {}).get("configurable", {}),
                    "model_kwargs": {"response_format": {"type": "json_object"}},
                },
            },
        )
        message = await ainvoke_llm(
            get_default_llm(temperature=temperature),
            messages,
            config=invoke_config,
            label=label,
            options=LLMInvokeOptions(timeout=timeout),
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

    #: Scored inside this suite's own ``score()`` from the transport's end
    #: state, not through the shared dispatcher — a benchmark verdict, not a
    #: reusable check. Declared so load-time validation knows the name is real.
    EXTRA_GATES: ClassVar[ExtraGates] = {"probes": SELF_SCORED}

    def __init__(self, cfg: EvalConfig) -> None:
        del cfg
        self._scenarios: dict[str, Scenario] | None = None

    def _scenario(self, case_id: str) -> Scenario:
        if self._scenarios is None:
            from scripts.memory_benchmark.dataset import SCENARIOS

            self._scenarios = {
                str(scenario["id"]): cast(Scenario, scenario) for scenario in SCENARIOS
            }
        return self._scenarios[case_id]

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
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
        for case in cases:
            validate_gates(self.name, case.id, case.gates, self.EXTRA_GATES)
        return cases

    def transport(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> Awaitable[CaseRun]:
        return self._run(case, cfg, tracker, provider)

    async def _run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg
        await _ensure_ready(tracker)
        scenario = self._scenario(case.id)
        from scripts.memory_benchmark.runner import run_scenario

        tokens_in_before = tracker.total_input
        tokens_out_before = tracker.total_output
        # run_scenario is declared over bare dicts in the benchmark, which is not
        # ours to retype; the cast names the shape it really returns so the rest
        # of this method is checked.
        raw_results = await run_scenario(cast("dict[str, object]", scenario))
        results = [cast(ProbeResult, result) for result in raw_results]
        tokens_in = tracker.total_input - tokens_in_before
        tokens_out = tracker.total_output - tokens_out_before

        probes: list[dict[str, object]] = []
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
            messages.append({"role": "user", "content": str(probe["query"])})
            messages.append({"role": "assistant", "content": str(probe["recalled_text"])})

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

    def finalize_scorers(self, cfg: EvalConfig) -> list[object]:
        del cfg
        # Memory verdicts are the benchmark's deterministic substring checks,
        # already applied at runtime and journaled per probe. An LLM judge
        # would add cost without information, so Opik finalize stays free.
        return []
