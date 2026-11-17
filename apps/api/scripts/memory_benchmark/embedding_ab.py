"""Retrieval-only A/B of memory embedders and rerankers.

Holds the corpus, the queries and the candidate depth fixed and varies only the
embedder and the reranker, so a difference in the numbers is a difference in the
models — not in extraction, reconciliation or LLM answering, which the full
``memory_benchmark`` runner mixes in.

Pipeline per query, mirroring ``retrieval.recall``'s dense half: cosine ANN over
the corpus, top ``RERANK_CANDIDATES`` candidates, cross-encoder rerank of those,
ranked list. Metrics are scored before and after the rerank.

Datasets:
  lme   LongMemEval ``_s`` (cleaned). Per question, the corpus is that question's
        haystack user turns; gold is every user turn labelled ``has_answer``.
  gaia  The hard scenarios in ``dataset.py``. One pooled corpus of every user
        turn across all scenarios (so other scenarios act as distractors); gold
        is the probe's own-scenario user turns containing a ``must_contain`` term.

The baseline runs the app's own fastembed helpers (``_embed_sync``,
``_embed_query_sync``, ``_rerank_sync``), so it is the production math, not a
reimplementation. Embeddings are cached on disk per model, so reruns only pay
for new texts.

Inputs, the vector cache and the report all live in ``BENCH_DIR``; ``--lme``
names a file inside it.

    uv run python -m scripts.memory_benchmark.embedding_ab \\
        --lme longmemeval_s_cleaned.json --lme-num 100
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
import sys
import time
from typing import Final, NotRequired, Protocol, TypedDict

import httpx
import numpy as np
from numpy.typing import NDArray

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config.settings import settings
from app.constants.memory import RERANK_CANDIDATES
from app.memory.embeddings import _embed_query_sync, _embed_sync, _rerank_sync

from .dataset import SCENARIOS

Vector = NDArray[np.float32]

CF_RUN_URL: Final = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
CF_CONCURRENCY: Final = 8
CF_RETRIES: Final = 4
#: Workers AI sizes a batch as len(batch) x tokens(longest text) — every text is
#: padded to the longest — and rejects one over the model's context (60k tokens
#: for bge-m3). Measured: 100 texts totalling 19,470 chars billed 35,400 tokens.
#: Batches are grouped by length against this padded budget, counting each char
#: as at most one token; well under the limit, since near-limit batches time out.
CF_MAX_PADDED_TOKENS: Final = 16_000
#: Documents are cut to roughly a 512-token window for every arm alike, so the
#: longer-context models get no extra text the 512-token baseline never sees.
MAX_DOC_CHARS: Final = 2000
BOOTSTRAP_SAMPLES: Final = 10_000
BASELINE_ARM: Final = "mxbai-embed-large-v1 + jina-reranker-v1-turbo"
BENCH_DIR: Final = Path.home() / ".cache" / "gaia" / "embedding_ab"
CACHE_DIR: Final = BENCH_DIR / "vectors"
REPORT_PATH: Final = BENCH_DIR / "report.json"
BGE_QUERY_PREFIX: Final = "Represent this sentence for searching relevant passages: "
GEMMA_QUERY_PREFIX: Final = "task: search result | query: "
GEMMA_DOC_PREFIX: Final = "title: none | text: "


# ── Backends ─────────────────────────────────────────────────────────────────


class Embedder(Protocol):
    name: str

    async def embed_queries(self, texts: list[str]) -> list[Vector]: ...
    async def embed_docs(self, texts: list[str]) -> list[Vector]: ...


class Reranker(Protocol):
    name: str

    async def score(self, query: str, docs: list[str]) -> list[float]: ...


class _VectorCache:
    """On-disk vector cache keyed by (model, role, text)."""

    def __init__(self, model: str) -> None:
        CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        slug = hashlib.sha256(model.encode()).hexdigest()[:12]
        self._db = sqlite3.connect(CACHE_DIR / f"{slug}.sqlite")
        self._db.execute("CREATE TABLE IF NOT EXISTS v (k TEXT PRIMARY KEY, b BLOB)")

    @staticmethod
    def _key(role: str, text: str) -> str:
        return hashlib.sha256(f"{role}\x00{text}".encode()).hexdigest()

    def get(self, role: str, texts: list[str]) -> dict[int, Vector]:
        found: dict[int, Vector] = {}
        for i, text in enumerate(texts):
            row = self._db.execute("SELECT b FROM v WHERE k=?", (self._key(role, text),)).fetchone()
            if row:
                found[i] = np.frombuffer(row[0], dtype=np.float32)
        return found

    def put(self, role: str, texts: list[str], vectors: list[Vector]) -> None:
        self._db.executemany(
            "INSERT OR REPLACE INTO v VALUES (?, ?)",
            [
                (self._key(role, t), np.asarray(v, dtype=np.float32).tobytes())
                for t, v in zip(texts, vectors, strict=True)
            ],
        )
        self._db.commit()


async def _cached(
    cache: _VectorCache,
    role: str,
    texts: list[str],
    compute: Callable[[list[str]], Awaitable[list[Vector]]],
) -> list[Vector]:
    found = cache.get(role, texts)
    missing = [i for i in range(len(texts)) if i not in found]
    if missing:
        computed = await compute([texts[i] for i in missing])
        cache.put(role, [texts[i] for i in missing], computed)
        found.update(zip(missing, computed, strict=True))
    return [found[i] for i in range(len(texts))]


@dataclass
class LocalFastembed:
    """The production stack: fastembed mxbai + jina, via the app's sync helpers."""

    name: str = "mxbai-embed-large-v1"
    _cache: _VectorCache = field(init=False)

    def __post_init__(self) -> None:
        self._cache = _VectorCache(self.name)

    async def embed_queries(self, texts: list[str]) -> list[Vector]:
        async def run(batch: list[str]) -> list[Vector]:
            return [
                np.asarray(await asyncio.to_thread(_embed_query_sync, t), dtype=np.float32)
                for t in batch
            ]

        return await _cached(self._cache, "q", texts, run)

    async def embed_docs(self, texts: list[str]) -> list[Vector]:
        async def run(batch: list[str]) -> list[Vector]:
            vectors = await asyncio.to_thread(_embed_sync, batch)
            return [np.asarray(v, dtype=np.float32) for v in vectors]

        return await _cached(self._cache, "d", texts, run)


@dataclass
class LocalJinaReranker:
    name: str = "jina-reranker-v1-turbo"

    async def score(self, query: str, docs: list[str]) -> list[float]:
        return await asyncio.to_thread(_rerank_sync, query, docs)


class _CloudflareClient:
    def __init__(self) -> None:
        account = settings.CLOUDFLARE_AI_ACCOUNT_ID
        token = settings.CLOUDFLARE_AI_API_TOKEN
        if not (account and token):
            raise RuntimeError("CLOUDFLARE_AI_ACCOUNT_ID / CLOUDFLARE_AI_API_TOKEN are required")
        self._account = account
        self._http = httpx.AsyncClient(timeout=120, headers={"Authorization": f"Bearer {token}"})
        self._slots = asyncio.Semaphore(CF_CONCURRENCY)

    async def run(self, model: str, body: dict[str, object]) -> dict[str, object]:
        url = CF_RUN_URL.format(account_id=self._account, model=model)
        async with self._slots:
            for attempt in range(CF_RETRIES):
                try:
                    response = await self._http.post(url, json=body)
                except httpx.TransportError:
                    if attempt == CF_RETRIES - 1:
                        raise
                    await asyncio.sleep(2**attempt)
                    continue
                if response.status_code in (429, 500, 502, 503, 504) and attempt < CF_RETRIES - 1:
                    await asyncio.sleep(2**attempt)
                    continue
                if response.is_error:
                    raise RuntimeError(
                        f"{model}: HTTP {response.status_code} {response.text[:300]}"
                    )
                payload = response.json()
                if not payload.get("success", False):
                    raise RuntimeError(f"{model}: {payload.get('errors')}")
                result: dict[str, object] = payload["result"]
                return result
        raise RuntimeError(f"{model}: retries exhausted")


@dataclass(frozen=True)
class CloudflareModelSpec:
    """How one Workers AI embedder wants its queries and documents shaped."""

    model: str
    batch: int
    query_body: Callable[[list[str]], dict[str, object]]
    doc_body: Callable[[list[str]], dict[str, object]]


CLOUDFLARE_EMBEDDERS: Final[dict[str, CloudflareModelSpec]] = {
    "bge-m3": CloudflareModelSpec(
        "@cf/baai/bge-m3",
        100,
        lambda q: {"text": q},
        lambda d: {"text": d},
    ),
    "bge-large-en-v1.5": CloudflareModelSpec(
        "@cf/baai/bge-large-en-v1.5",
        100,
        lambda q: {"text": [BGE_QUERY_PREFIX + t for t in q], "pooling": "cls"},
        lambda d: {"text": d, "pooling": "cls"},
    ),
    "qwen3-embedding-0.6b": CloudflareModelSpec(
        "@cf/qwen/qwen3-embedding-0.6b",
        32,
        lambda q: {"queries": q},
        lambda d: {"documents": d},
    ),
    "embeddinggemma-2": CloudflareModelSpec(
        "@cf/google/embeddinggemma-2",
        100,
        lambda q: {"input": [GEMMA_QUERY_PREFIX + t for t in q]},
        lambda d: {"input": [GEMMA_DOC_PREFIX + t for t in d]},
    ),
    "embeddinggemma-300m": CloudflareModelSpec(
        "@cf/google/embeddinggemma-300m",
        100,
        lambda q: {"text": [GEMMA_QUERY_PREFIX + t for t in q]},
        lambda d: {"text": [GEMMA_DOC_PREFIX + t for t in d]},
    ),
}


def _result_vectors(result: dict[str, object]) -> list[list[float]]:
    """Vectors from a Workers AI embedding result, native (bare lists) or OpenAI-shaped."""
    data = result["data"]
    assert isinstance(data, list)
    if data and isinstance(data[0], dict):
        return [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]
    return data


def padded_batches(texts: list[str], max_texts: int, max_padded: int) -> list[list[int]]:
    """Group text indices by length so len(batch) x longest stays within max_padded."""
    batches: list[list[int]] = []
    current: list[int] = []
    for index in sorted(range(len(texts)), key=lambda i: len(texts[i])):
        longest = len(texts[index])
        if current and (len(current) >= max_texts or (len(current) + 1) * longest > max_padded):
            batches.append(current)
            current = []
        current.append(index)
    if current:
        batches.append(current)
    return batches


@dataclass
class CloudflareEmbedder:
    name: str
    client: _CloudflareClient
    _spec: CloudflareModelSpec = field(init=False)
    _cache: _VectorCache = field(init=False)

    def __post_init__(self) -> None:
        self._spec = CLOUDFLARE_EMBEDDERS[self.name]
        self._cache = _VectorCache(self._spec.model)

    async def _embed(
        self, texts: list[str], body: Callable[[list[str]], dict[str, object]]
    ) -> list[Vector]:
        batches = padded_batches(texts, self._spec.batch, CF_MAX_PADDED_TOKENS)
        results = await asyncio.gather(
            *(self.client.run(self._spec.model, body([texts[i] for i in b])) for b in batches)
        )
        vectors: list[Vector | None] = [None] * len(texts)
        for batch, result in zip(batches, results, strict=True):
            for index, vector in zip(batch, _result_vectors(result), strict=True):
                vectors[index] = np.asarray(vector, dtype=np.float32)
        missing = [i for i, v in enumerate(vectors) if v is None]
        if missing:
            raise RuntimeError(f"{self._spec.model}: no vector returned for {len(missing)} texts")
        return [v for v in vectors if v is not None]

    async def embed_queries(self, texts: list[str]) -> list[Vector]:
        return await _cached(
            self._cache, "q", texts, lambda b: self._embed(b, self._spec.query_body)
        )

    async def embed_docs(self, texts: list[str]) -> list[Vector]:
        return await _cached(self._cache, "d", texts, lambda b: self._embed(b, self._spec.doc_body))


@dataclass(frozen=True)
class HostedSpec:
    """One non-Cloudflare hosted embedder: endpoint, auth header and wire shape."""

    url: str
    auth_header: Callable[[], dict[str, str]]
    batch: int
    query_body: Callable[[list[str]], dict[str, object]]
    doc_body: Callable[[list[str]], dict[str, object]]
    vectors: Callable[[dict[str, object]], list[list[float]]]


def _openai_body(model: str) -> Callable[[list[str]], dict[str, object]]:
    return lambda texts: {"model": model, "input": texts}


def _openai_vectors(payload: dict[str, object]) -> list[list[float]]:
    data = payload["data"]
    assert isinstance(data, list)
    return [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]


def _gemini_body(task: str) -> Callable[[list[str]], dict[str, object]]:
    model = "models/gemini-embedding-001"
    return lambda texts: {
        "requests": [
            {"model": model, "content": {"parts": [{"text": t}]}, "taskType": task} for t in texts
        ]
    }


def _gemini_vectors(payload: dict[str, object]) -> list[list[float]]:
    embeddings = payload["embeddings"]
    assert isinstance(embeddings, list)
    return [item["values"] for item in embeddings]


HOSTED_EMBEDDERS: Final[dict[str, HostedSpec]] = {
    "openai-3-small": HostedSpec(
        "https://api.openai.com/v1/embeddings",
        lambda: {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
        256,
        _openai_body("text-embedding-3-small"),
        _openai_body("text-embedding-3-small"),
        _openai_vectors,
    ),
    "gemini-embedding-001": HostedSpec(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents",
        lambda: {"x-goog-api-key": str(settings.GOOGLE_API_KEY)},
        100,
        _gemini_body("RETRIEVAL_QUERY"),
        _gemini_body("RETRIEVAL_DOCUMENT"),
        _gemini_vectors,
    ),
}


@dataclass
class HostedEmbedder:
    """An OpenAI- or Gemini-hosted embedder, batched under the same padded budget."""

    name: str
    _spec: HostedSpec = field(init=False)
    _cache: _VectorCache = field(init=False)
    _http: httpx.AsyncClient = field(init=False)
    _slots: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self._spec = HOSTED_EMBEDDERS[self.name]
        self._cache = _VectorCache(self.name)
        self._http = httpx.AsyncClient(timeout=120, headers=self._spec.auth_header())
        self._slots = asyncio.Semaphore(CF_CONCURRENCY)

    async def _post(self, body: dict[str, object]) -> list[list[float]]:
        async with self._slots:
            for attempt in range(CF_RETRIES):
                try:
                    response = await self._http.post(self._spec.url, json=body)
                except httpx.TransportError:
                    if attempt == CF_RETRIES - 1:
                        raise
                    await asyncio.sleep(2**attempt)
                    continue
                if response.status_code in (429, 500, 502, 503, 504) and attempt < CF_RETRIES - 1:
                    await asyncio.sleep(2 ** (attempt + 2))
                    continue
                if response.is_error:
                    raise RuntimeError(
                        f"{self.name}: HTTP {response.status_code} {response.text[:300]}"
                    )
                return self._spec.vectors(response.json())
        raise RuntimeError(f"{self.name}: retries exhausted")

    async def _embed(
        self, texts: list[str], body: Callable[[list[str]], dict[str, object]]
    ) -> list[Vector]:
        batches = padded_batches(texts, self._spec.batch, CF_MAX_PADDED_TOKENS * 4)
        results = await asyncio.gather(*(self._post(body([texts[i] for i in b])) for b in batches))
        vectors: list[Vector | None] = [None] * len(texts)
        for batch, result in zip(batches, results, strict=True):
            for index, vector in zip(batch, result, strict=True):
                vectors[index] = np.asarray(vector, dtype=np.float32)
        missing = [i for i, v in enumerate(vectors) if v is None]
        if missing:
            raise RuntimeError(f"{self.name}: no vector returned for {len(missing)} texts")
        return [v for v in vectors if v is not None]

    async def embed_queries(self, texts: list[str]) -> list[Vector]:
        return await _cached(
            self._cache, "q", texts, lambda b: self._embed(b, self._spec.query_body)
        )

    async def embed_docs(self, texts: list[str]) -> list[Vector]:
        return await _cached(self._cache, "d", texts, lambda b: self._embed(b, self._spec.doc_body))


@dataclass
class CloudflareReranker:
    client: _CloudflareClient
    name: str = "bge-reranker-base"

    async def score(self, query: str, docs: list[str]) -> list[float]:
        result = await self.client.run(
            "@cf/baai/bge-reranker-base",
            {"query": query, "contexts": [{"text": d} for d in docs], "top_k": len(docs)},
        )
        scores = [0.0] * len(docs)
        response = result["response"]
        assert isinstance(response, list)
        for item in response:
            scores[int(item["id"])] = float(item["score"])
        return scores


# ── Datasets ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Query:
    text: str
    corpus_id: str
    gold: frozenset[int]


@dataclass
class Dataset:
    name: str
    corpora: dict[str, list[str]]
    queries: list[Query]
    skipped: int = 0


class LmeTurn(TypedDict):
    role: str
    content: str
    has_answer: NotRequired[bool]


class LmeItem(TypedDict):
    question_id: str
    question_type: str
    question: str
    haystack_sessions: list[list[LmeTurn]]


def bench_file(name: str) -> Path:
    """Resolve a file name inside BENCH_DIR, refusing any path that leaves it."""
    root = BENCH_DIR.resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"{name!r} is outside {root}")
    return path


def _answerable(item: LmeItem) -> bool:
    """A non-abstention question whose answer sits in some user turn."""
    if item["question_id"].endswith("_abs"):
        return False
    return any(
        t.get("has_answer") and t["role"] == "user" for s in item["haystack_sessions"] for t in s
    )


def _user_turns(item: LmeItem) -> tuple[list[str], frozenset[int]]:
    """A question's haystack user turns, and the indices of those holding the answer."""
    docs: list[str] = []
    gold: set[int] = set()
    for session in item["haystack_sessions"]:
        for turn in session:
            if turn["role"] != "user":
                continue
            if turn.get("has_answer"):
                gold.add(len(docs))
            docs.append(turn["content"][:MAX_DOC_CHARS])
    return docs, frozenset(gold)


def load_lme(path: Path, num: int, seed: int) -> Dataset:
    raw: list[LmeItem] = json.loads(path.read_text())
    eligible = [item for item in raw if _answerable(item)]
    by_type: dict[str, list[LmeItem]] = {}
    for item in eligible:
        by_type.setdefault(item["question_type"], []).append(item)
    rng = random.Random(seed)
    per_type = max(1, num // len(by_type))
    sample = [x for items in by_type.values() for x in rng.sample(items, min(per_type, len(items)))]

    dataset = Dataset("lme", {}, [], skipped=len(raw) - len(eligible))
    for item in sample:
        docs, gold = _user_turns(item)
        corpus_id = item["question_id"]
        dataset.corpora[corpus_id] = docs
        dataset.queries.append(Query(item["question"], corpus_id, gold))
    return dataset


def load_gaia() -> Dataset:
    pooled = [
        (str(turn["content"])[:MAX_DOC_CHARS], str(scenario["id"]))
        for scenario in SCENARIOS
        for turn in scenario["turns"]
        if turn["role"] == "user"
    ]
    dataset = Dataset("gaia", {"pooled": [doc for doc, _ in pooled]}, [])
    probes = [(s, p) for s in SCENARIOS for p in s["probes"] if not p.get("is_negative")]
    for scenario, probe in probes:
        terms = [str(t).lower() for t in probe["must_contain"]]
        gold = frozenset(
            i
            for i, (doc, sid) in enumerate(pooled)
            if sid == scenario["id"] and any(term in doc.lower() for term in terms)
        )
        if gold:
            dataset.queries.append(Query(str(probe["query"]), "pooled", gold))
        else:
            dataset.skipped += 1
    return dataset


# ── Metrics ──────────────────────────────────────────────────────────────────


def recall_at(ranked: Sequence[int], gold: frozenset[int], k: int) -> float:
    return len(set(ranked[:k]) & gold) / len(gold)


def ndcg_at(ranked: Sequence[int], gold: frozenset[int], k: int) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, doc in enumerate(ranked[:k]) if doc in gold)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(gold))))
    return dcg / ideal


METRICS: Final[dict[str, Callable[[Sequence[int], frozenset[int]], float]]] = {
    "R@5": lambda r, g: recall_at(r, g, 5),
    "R@10": lambda r, g: recall_at(r, g, 10),
    "NDCG@10": lambda r, g: ndcg_at(r, g, 10),
}


def paired_delta_ci(
    arm: Sequence[float], base: Sequence[float], seed: int
) -> tuple[float, float, float]:
    diffs = np.asarray(arm) - np.asarray(base)
    rng = np.random.default_rng(seed)
    samples = rng.choice(diffs, size=(BOOTSTRAP_SAMPLES, len(diffs)), replace=True).mean(axis=1)
    return (
        float(diffs.mean()),
        float(np.percentile(samples, 2.5)),
        float(np.percentile(samples, 97.5)),
    )


# ── Run ──────────────────────────────────────────────────────────────────────


def _normalize(vectors: list[Vector]) -> NDArray[np.float32]:
    matrix = np.vstack(vectors).astype(np.float32)
    normed: NDArray[np.float32] = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    return normed


async def ann_rankings(embedder: Embedder, dataset: Dataset) -> list[list[int]]:
    """Top RERANK_CANDIDATES corpus indices per query, by cosine."""
    corpus_matrix: dict[str, NDArray[np.float32]] = {}
    for corpus_id, docs in dataset.corpora.items():
        corpus_matrix[corpus_id] = _normalize(await embedder.embed_docs(docs))
    query_matrix = _normalize(await embedder.embed_queries([q.text for q in dataset.queries]))
    rankings: list[list[int]] = []
    for q, qv in zip(dataset.queries, query_matrix, strict=True):
        sims = corpus_matrix[q.corpus_id] @ qv
        rankings.append([int(i) for i in np.argsort(-sims)[:RERANK_CANDIDATES]])
    return rankings


async def reranked(
    reranker: Reranker, dataset: Dataset, rankings: list[list[int]]
) -> list[list[int]]:
    async def one(q: Query, ranking: list[int]) -> list[int]:
        docs = dataset.corpora[q.corpus_id]
        scores = await reranker.score(q.text, [docs[i] for i in ranking])
        return [ranking[i] for i in np.argsort(-np.asarray(scores))]

    return list(
        await asyncio.gather(*(one(q, r) for q, r in zip(dataset.queries, rankings, strict=True)))
    )


def per_query(dataset: Dataset, rankings: list[list[int]]) -> dict[str, list[float]]:
    return {
        metric: [fn(r, q.gold) for q, r in zip(dataset.queries, rankings, strict=True)]
        for metric, fn in METRICS.items()
    }


async def run(datasets: list[Dataset], embedder_names: list[str], seed: int) -> dict[str, object]:
    client = _CloudflareClient()
    embedders: list[Embedder] = [LocalFastembed()] + [
        HostedEmbedder(name) if name in HOSTED_EMBEDDERS else CloudflareEmbedder(name, client)
        for name in embedder_names
    ]
    rerankers: list[Reranker] = [LocalJinaReranker(), CloudflareReranker(client)]

    report: dict[str, object] = {}
    for dataset in datasets:
        print(
            f"\n## {dataset.name}: {len(dataset.queries)} queries, "
            f"{sum(len(d) for d in dataset.corpora.values())} docs, skipped {dataset.skipped}"
        )
        scores: dict[str, dict[str, list[float]]] = {}
        for embedder in embedders:
            started = time.perf_counter()
            ann = await ann_rankings(embedder, dataset)
            scores[f"{embedder.name} (ANN only)"] = per_query(dataset, ann)
            for reranker in rerankers:
                scores[f"{embedder.name} + {reranker.name}"] = per_query(
                    dataset, await reranked(reranker, dataset, ann)
                )
            print(f"   {embedder.name} done in {time.perf_counter() - started:.0f}s")

        base = scores[BASELINE_ARM]
        rows: list[dict[str, object]] = []
        for arm, metrics in scores.items():
            row: dict[str, object] = {"arm": arm}
            for metric, values in metrics.items():
                mean, lo, hi = paired_delta_ci(values, base[metric], seed)
                row[metric] = round(100 * float(np.mean(values)), 1)
                row[f"Δ{metric}"] = f"{100 * mean:+.1f} [{100 * lo:+.1f}, {100 * hi:+.1f}]"
            rows.append(row)
        report[dataset.name] = rows
        _print_table(rows)
    return report


def _print_table(rows: list[dict[str, object]]) -> None:
    header = ["arm", "R@5", "ΔR@5", "R@10", "NDCG@10", "ΔNDCG@10"]
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for row in rows:
        print("| " + " | ".join(str(row[h]) for h in header) + " |")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lme", help="LongMemEval _s (cleaned) file name inside BENCH_DIR")
    parser.add_argument("--lme-num", type=int, default=100)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--embedders",
        default=",".join(CLOUDFLARE_EMBEDDERS),
        help="Comma-separated hosted embedders (Workers AI, OpenAI, Gemini) to compare against the baseline",
    )
    args = parser.parse_args()

    datasets = [load_gaia()]
    if args.lme:
        datasets.append(load_lme(bench_file(args.lme), args.lme_num, args.seed))
    report = await run(datasets, args.embedders.split(","), args.seed)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
