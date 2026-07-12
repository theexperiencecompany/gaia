"""OpenRouter model catalog: which models accept image input.

The catalog (https://openrouter.ai/api/v1/models) is the source of truth for
every OpenRouter model's ``architecture.input_modalities``, so vision support
needs no per-model curation. It is fetched lazily, cached in-process, and kept
stale-on-error: a refresh failure reuses the last good snapshot instead of
flip-flopping models between image and text-description behavior. With no
snapshot at all, callers fail safe to non-vision.
"""

import time
from typing import Any

import httpx

from app.constants.llm import (
    OPENROUTER_MODEL_CATALOG_TIMEOUT_SECONDS,
    OPENROUTER_MODEL_CATALOG_TTL_SECONDS,
    OPENROUTER_MODELS_URL,
)
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

_IMAGE_MODALITY = "image"

# (fetched_at monotonic seconds, model id -> accepts image input). Concurrent
# cold-start refreshes may fetch in parallel (last writer wins); an asyncio
# primitive can't guard this because hooks run under more than one event loop
# (sync_execute_hooks spins up its own).
_snapshot: tuple[float, dict[str, bool]] | None = None


def _parse_image_input_models(payload: dict[str, Any]) -> dict[str, bool]:
    models: dict[str, bool] = {}
    for entry in payload.get("data", []):
        model_id = entry.get("id")
        if not isinstance(model_id, str):
            continue
        modalities = entry.get("architecture", {}).get("input_modalities", [])
        models[model_id] = _IMAGE_MODALITY in modalities
    return models


async def _refresh_snapshot() -> dict[str, bool] | None:
    global _snapshot
    try:
        async with httpx.AsyncClient(timeout=OPENROUTER_MODEL_CATALOG_TIMEOUT_SECONDS) as client:
            response = await client.get(OPENROUTER_MODELS_URL)
            response.raise_for_status()
            models = _parse_image_input_models(response.json())
    except Exception as exc:
        log.warning(f"{LogTag.AGENT} OpenRouter model catalog refresh failed: {exc}")
        return None
    if not models:
        log.warning(f"{LogTag.AGENT} OpenRouter model catalog returned no models; keeping stale")
        return None
    _snapshot = (time.monotonic(), models)
    log.info(
        f"{LogTag.AGENT} OpenRouter model catalog refreshed",
        model_catalog={"models": len(models)},
    )
    return models


async def openrouter_model_accepts_images(model: str) -> bool:
    """Whether an OpenRouter model lists ``image`` among its input modalities.

    Unknown models and catalog outages (with no stale snapshot) return False —
    fail safe to the text-description fallback, never a rejected provider call.
    """
    snapshot = _snapshot
    if snapshot is None or time.monotonic() - snapshot[0] > OPENROUTER_MODEL_CATALOG_TTL_SECONDS:
        refreshed = await _refresh_snapshot()
        if refreshed is not None:
            return refreshed.get(model, False)
        if snapshot is None:
            return False
    return snapshot[1].get(model, False)
