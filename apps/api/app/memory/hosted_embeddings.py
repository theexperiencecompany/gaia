"""Memory embeddings from OpenAI's hosted model — no CPU of ours, no sidecar queue.

text-embedding-3-small was chosen on 2026-11-15 by the retrieval A/B
(scripts/memory_benchmark/embedding_ab.py): best of the hosted candidates on the
GAIA probes, significantly ahead of the local stack on LongMemEval, and 193ms
p50 / 306ms p95 for one query from the prod host.
"""

import asyncio
from collections.abc import Sequence
from typing import Final

import httpx
from pydantic import BaseModel

from app.constants.memory import (
    HOSTED_EMBEDDING_BATCH_TEXTS,
    HOSTED_EMBEDDING_RETRIES,
    HOSTED_EMBEDDING_TIMEOUT_SECONDS,
    MEMORY_VECTOR_MODEL,
)
from app.constants.providers import CredentialProviderName
from app.services.providers.provider_credentials_service import is_usable, resolved_config

_EMBEDDINGS_URL: Final = "https://api.openai.com/v1/embeddings"
_RETRYABLE: Final = frozenset({429, 500, 502, 503, 504})


class HostedEmbeddingError(RuntimeError):
    """OpenAI refused or failed an embedding request."""


class _Embedding(BaseModel):
    index: int
    embedding: list[float]


class _EmbeddingsResponse(BaseModel):
    data: list[_Embedding]


_clients: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}


def configured() -> bool:
    """Whether an OpenAI key is available to embed with."""
    config = resolved_config(CredentialProviderName.OPENAI)
    return config is not None and is_usable(CredentialProviderName.OPENAI, config)


def _client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        config = resolved_config(CredentialProviderName.OPENAI)
        if config is None or not is_usable(CredentialProviderName.OPENAI, config):
            raise HostedEmbeddingError("OpenAI is not configured")
        client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=HOSTED_EMBEDDING_TIMEOUT_SECONDS,
        )
        _clients[loop] = client
    return client


async def _embed(texts: list[str], *, retries: int) -> list[list[float]]:
    for attempt in range(retries + 1):
        try:
            response = await _client().post(
                _EMBEDDINGS_URL, json={"model": MEMORY_VECTOR_MODEL, "input": texts}
            )
        except httpx.TransportError:
            if attempt == retries:
                raise
            await asyncio.sleep(2**attempt)
            continue
        if response.status_code in _RETRYABLE and attempt < retries:
            await asyncio.sleep(2**attempt)
            continue
        if response.is_error:
            raise HostedEmbeddingError(
                f"{MEMORY_VECTOR_MODEL}: HTTP {response.status_code} {response.text[:300]}"
            )
        data = _EmbeddingsResponse.model_validate_json(response.content).data
        if len(data) != len(texts):
            raise HostedEmbeddingError(
                f"{MEMORY_VECTOR_MODEL}: {len(data)} vectors for {len(texts)} texts"
            )
        return [item.embedding for item in sorted(data, key=lambda item: item.index)]
    raise HostedEmbeddingError(f"{MEMORY_VECTOR_MODEL}: retries exhausted")


async def embed_documents(texts: Sequence[str]) -> list[list[float]]:
    """Embed memory contents for storage, retried, in the input's order."""
    batches = [
        list(texts[i : i + HOSTED_EMBEDDING_BATCH_TEXTS])
        for i in range(0, len(texts), HOSTED_EMBEDDING_BATCH_TEXTS)
    ]
    results = await asyncio.gather(
        *(_embed(batch, retries=HOSTED_EMBEDDING_RETRIES) for batch in batches)
    )
    return [vector for result in results for vector in result]


async def embed_query(text: str) -> list[float]:
    """Embed one query on the reply path: no retry, the caller's budget bounds it."""
    (vector,) = await _embed([text], retries=0)
    return vector
