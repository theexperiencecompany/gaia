"""OpenRouter model catalog: which models accept image input.

`architecture.input_modalities` in the live catalog is the source of truth, so
vision support needs no per-model curation on our side.

The catalog is consulted from the pre-model hook, i.e. on *every* model call, so
its caching rules are load-bearing rather than an optimization:

- A good snapshot is reused for ``TTL`` seconds.
- A failed refresh is remembered for ``RETRY`` seconds. Without that, an
  OpenRouter outage would charge every model call a full fetch timeout and turn
  a degraded dependency into an unusable product.
- A stale snapshot outlives a failed refresh, so models don't flip between
  image and text-description behavior mid-conversation.
- With no snapshot at all, callers fail safe to non-vision.
"""

import time
from typing import Any

import httpx

from app.constants.llm import (
    OPENROUTER_MODEL_CATALOG_RETRY_SECONDS,
    OPENROUTER_MODEL_CATALOG_TIMEOUT_SECONDS,
    OPENROUTER_MODEL_CATALOG_TTL_SECONDS,
    OPENROUTER_MODELS_URL,
)
from app.constants.log_tags import LogTag
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from shared.py.wide_events import log

_IMAGE_MODALITY = "image"


class OpenRouterModelCatalog:
    """In-process cache of each OpenRouter model's image-input support.

    Concurrent cold-start refreshes may fetch in parallel and the last writer
    wins — harmless, and an asyncio lock could not guard it anyway, because the
    pre-model hooks run under more than one event loop (``sync_execute_hooks``
    spins up its own).
    """

    def __init__(self) -> None:
        self._models: dict[str, bool] | None = None
        self._fetched_at: float | None = None
        self._failed_at: float | None = None

    async def accepts_images(self, model: str) -> bool:
        """Whether ``model`` lists ``image`` among its input modalities.

        Unknown models, and outages with no snapshot to fall back on, return
        False — fail safe to the text-description fallback rather than to a
        provider request the model will reject.
        """
        if self._needs_refresh() and not self._in_backoff():
            await self._refresh()
        if self._models is None:
            return False
        return self._models.get(model, False)

    def _needs_refresh(self) -> bool:
        if self._models is None or self._fetched_at is None:
            return True
        return time.monotonic() - self._fetched_at > OPENROUTER_MODEL_CATALOG_TTL_SECONDS

    def _in_backoff(self) -> bool:
        if self._failed_at is None:
            return False
        return time.monotonic() - self._failed_at < OPENROUTER_MODEL_CATALOG_RETRY_SECONDS

    async def _refresh(self) -> None:
        try:
            async with httpx.AsyncClient(
                timeout=OPENROUTER_MODEL_CATALOG_TIMEOUT_SECONDS
            ) as client:
                response = await client.get(OPENROUTER_MODELS_URL)
                response.raise_for_status()
                models = self._parse(response.json())
        except Exception as exc:
            self._fail(f"refresh failed: {exc}")
            return
        if not models:
            self._fail("catalog returned no models")
            return

        self._models = models
        self._fetched_at = time.monotonic()
        self._failed_at = None
        log.info(
            f"{LogTag.AGENT} OpenRouter model catalog refreshed",
            model_catalog={"models": len(models)},
        )

    def _fail(self, reason: str) -> None:
        self._failed_at = time.monotonic()
        log.warning(
            f"{LogTag.AGENT} OpenRouter model catalog {reason}; "
            f"backing off {OPENROUTER_MODEL_CATALOG_RETRY_SECONDS}s",
            model_catalog={"has_snapshot": self._models is not None},
        )

    @staticmethod
    def _parse(payload: dict[str, Any]) -> dict[str, bool]:
        models: dict[str, bool] = {}
        for entry in payload.get("data") or []:
            model_id = entry.get("id")
            if not isinstance(model_id, str):
                continue
            architecture = entry.get("architecture") or {}
            modalities = architecture.get("input_modalities") or []
            models[model_id] = _IMAGE_MODALITY in modalities
        return models


OPENROUTER_MODEL_CATALOG_PROVIDER = "openrouter_model_catalog"


@lazy_provider(name=OPENROUTER_MODEL_CATALOG_PROVIDER, strategy=MissingKeyStrategy.ERROR)
def init_openrouter_model_catalog() -> OpenRouterModelCatalog:
    """Register the catalog as a sync provider.

    The loader is deliberately sync: `accepts_images` is awaited from the
    pre-model hook, which `sync_execute_hooks` runs under a fresh, short-lived
    event loop each turn. An async provider guards initialization with an
    `asyncio.Lock` bound to the loop it was first used on, which would then fail
    against those later loops; a sync loader uses a thread lock and a lock-free
    fast path once initialized, so it is loop-agnostic.
    """
    return OpenRouterModelCatalog()


async def get_openrouter_catalog() -> OpenRouterModelCatalog:
    """Resolve the process-wide catalog from the provider registry."""
    catalog = await providers.aget(OPENROUTER_MODEL_CATALOG_PROVIDER)
    if catalog is None:
        raise RuntimeError("OpenRouter model catalog provider is not available")
    return catalog
