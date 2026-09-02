"""OpenRouter's own billing record for a generation, with an on-disk cache.

Shared by the backfill scripts: both ask what a call really cost, both must not
re-ask for ids they have already resolved, and both must survive interruption.
One copy, so the retry and caching rules cannot drift apart between them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
import json
import os
from pathlib import Path

import httpx
from pydantic import BaseModel

from shared.py.wide_events import log

OPENROUTER_URL = "https://openrouter.ai/api/v1/generation"
_LOOKUP_CONCURRENCY = 5
_LOOKUP_ATTEMPTS = 4


class GenerationRecord(BaseModel):
    """OpenRouter's own billing record for one generation."""

    total_cost: float = 0.0
    provider_name: str = "unknown"


class _Lookup(BaseModel):
    """A generation lookup outcome. ``resolved`` False means the answer is
    still unknown (network/5xx exhausted) and must NOT be cached — a 404 is a
    resolved ``None``, because OpenRouter will never know that id again."""

    resolved: bool
    record: GenerationRecord | None = None


async def _lookup_generation(
    client: httpx.AsyncClient, api_key: str, generation_id: str, gate: asyncio.Semaphore
) -> _Lookup:
    """Ask OpenRouter what one generation really cost, with backoff on 429/5xx."""
    async with gate:
        for attempt in range(_LOOKUP_ATTEMPTS):
            try:
                response = await client.get(
                    OPENROUTER_URL,
                    params={"id": generation_id},
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            except httpx.HTTPError:
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                await asyncio.sleep(1.2 * (attempt + 1))
                continue
            if response.status_code == 404:
                # OpenRouter drops old generations; unverifiable, not a failure.
                return _Lookup(resolved=True, record=None)
            response.raise_for_status()
            data = response.json().get("data")
            record = GenerationRecord.model_validate(data) if data else None
            return _Lookup(resolved=True, record=record)
    log.warning(
        "[backfill] generation lookup exhausted its retries",
        error_type="openrouter_unreachable",
        generation_id=generation_id,
    )
    return _Lookup(resolved=False)


def _read_cache(path: Path) -> dict[str, GenerationRecord | None]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {
        key: GenerationRecord.model_validate(value) if value else None for key, value in raw.items()
    }


def default_cache_dir() -> Path:
    """Where resolved generations are cached between runs.

    Under the invoking user's cache home, never a shared temp directory: the
    cache is written and read back as the script's own input, so a world-
    writable path lets anyone on the box pre-create it and decide what this
    backfill believes each call cost — and that number is written to
    ``usage_daily``. Ephemeral either way; it only makes a re-run cheaper.
    """
    xdg = os.environ.get("XDG_CACHE_HOME")
    return (Path(xdg) if xdg else Path.home() / ".cache") / "gaia-true-cost"


def _write_cache(path: Path, known: Mapping[str, GenerationRecord | None]) -> None:
    # 0o700: same reason as _default_cache_dir — nobody else gets to write what
    # this run reads back as the real cost of a call.
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps({k: (v.model_dump() if v else None) for k, v in known.items()}))


async def resolve_generations(
    client: httpx.AsyncClient,
    api_key: str,
    generation_ids: Iterable[str],
    cache_path: Path,
) -> dict[str, GenerationRecord | None]:
    """Resolve every generation id in ``calls``, reusing the day's cache file."""
    known = _read_cache(cache_path)
    todo = sorted({gid for gid in generation_ids if gid} - set(known))
    if not todo:
        return known
    gate = asyncio.Semaphore(_LOOKUP_CONCURRENCY)
    lookups = await asyncio.gather(
        *(_lookup_generation(client, api_key, gen_id, gate) for gen_id in todo)
    )
    for gen_id, lookup in zip(todo, lookups, strict=True):
        if lookup.resolved:
            known[gen_id] = lookup.record
    _write_cache(cache_path, known)
    return known
