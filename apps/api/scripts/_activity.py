"""OpenRouter's own books, as the anchor a backfill reconciles against.

``GET /api/v1/activity`` (management key) returns one row per day, model,
provider and endpoint: real billed dollars, real token counts, real request
counts. Unlike per-generation lookups it needs no generation ids, covers every
key on the account, and survives the generations' own 30-day expiry — but it is
itself a rolling ~25-day window, so a snapshot taken today preserves days the
API will refuse to return next week. That is why this module reads snapshot
files and merges them: yesterday's file keeps the days that have already rolled
out, today's fetch adds the days that have appeared since.

Merging rule: rows are keyed by (day, model, provider, endpoint) and the copy
with the larger ``usage`` wins — a later snapshot of the same day can only have
accumulated more, so "larger" and "newer" are the same thing.
"""

from collections import defaultdict
from collections.abc import Iterable
import json
from pathlib import Path

import httpx
from pydantic import BaseModel

ACTIVITY_URL = "https://openrouter.ai/api/v1/activity"


class ActivityPool(BaseModel):
    """Everything OpenRouter billed for one (day, model), summed across providers."""

    usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    requests: int = 0

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens + self.reasoning_tokens


def _merge_rows(row_sets: Iterable[list[dict]]) -> dict[tuple, dict]:
    merged: dict[tuple, dict] = {}
    for rows in row_sets:
        for row in rows:
            key = (
                str(row.get("date", ""))[:10],
                str(row.get("model", "")),
                str(row.get("provider_name", "")),
                str(row.get("endpoint_id", "")),
            )
            kept = merged.get(key)
            if kept is None or float(row.get("usage", 0)) > float(kept.get("usage", 0)):
                merged[key] = row
    return merged


async def load_pools(
    snapshot_paths: list[Path], management_key: str | None
) -> dict[tuple[str, str], ActivityPool]:
    """Per-(day, model) billing pools from snapshots plus a live fetch.

    Snapshot files are the raw ``{"data": [...]}`` body the endpoint returns.
    The live fetch is attempted whenever a management key is available and its
    failure is non-fatal — the snapshots alone are still an anchor.
    """
    row_sets: list[list[dict]] = []
    for path in snapshot_paths:
        row_sets.append(json.loads(path.read_text()).get("data", []))
    if management_key:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                ACTIVITY_URL, headers={"Authorization": f"Bearer {management_key}"}
            )
            response.raise_for_status()
            row_sets.append(response.json().get("data", []))
    pools: dict[tuple[str, str], ActivityPool] = defaultdict(ActivityPool)
    for (day, model, _provider, _endpoint), row in _merge_rows(row_sets).items():
        pool = pools[(day, model)]
        pool.usd += float(row.get("usage", 0))
        pool.prompt_tokens += int(row.get("prompt_tokens", 0))
        pool.completion_tokens += int(row.get("completion_tokens", 0))
        pool.reasoning_tokens += int(row.get("reasoning_tokens", 0))
        pool.requests += int(row.get("requests", 0))
    return dict(pools)
