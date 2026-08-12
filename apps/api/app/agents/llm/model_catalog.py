"""Concentrate model catalog: which models accept image input.

`capabilities.image_input.supported` in the live catalog is the source of truth,
so vision support needs no per-model curation on our side.

The catalog is consulted from the pre-model hook, i.e. on *every* model call, so
its caching rules are load-bearing rather than an optimization:

- A good snapshot is reused for ``TTL`` seconds.
- A failed refresh is remembered for ``RETRY`` seconds. Without that, a
  Concentrate outage would charge every model call a full fetch timeout and turn
  a degraded dependency into an unusable product.
- A stale snapshot outlives a failed refresh, so models don't flip between
  image and text-description behavior mid-conversation.
- With no snapshot at all, callers fail safe to non-vision.
"""

import time
from typing import Any, cast

import httpx

from app.constants.llm import (
    CONCENTRATE_MODEL_CATALOG_RETRY_SECONDS,
    CONCENTRATE_MODEL_CATALOG_TIMEOUT_SECONDS,
    CONCENTRATE_MODEL_CATALOG_TTL_SECONDS,
    CONCENTRATE_MODELS_URL,
)
from app.constants.log_tags import LogTag
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from shared.py.wide_events import log


class ConcentrateModelCatalog:
    """In-process cache of each Concentrate model's image-input support.

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
        """Whether ``model`` supports image input per the live catalog.

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
        return time.monotonic() - self._fetched_at > CONCENTRATE_MODEL_CATALOG_TTL_SECONDS

    def _in_backoff(self) -> bool:
        if self._failed_at is None:
            return False
        return time.monotonic() - self._failed_at < CONCENTRATE_MODEL_CATALOG_RETRY_SECONDS

    async def _refresh(self) -> None:
        try:
            async with httpx.AsyncClient(
                timeout=CONCENTRATE_MODEL_CATALOG_TIMEOUT_SECONDS
            ) as client:
                response = await client.get(CONCENTRATE_MODELS_URL)
                response.raise_for_status()
                payload = response.json()
                models = self._parse(payload)
        except Exception as exc:
            self._fail(f"refresh failed: {exc}")
            return
        if not models:
            self._fail("catalog returned no models")
            return

        # The full catalog currently comes back in one page (``has_more`` false).
        # If Concentrate ever paginates it, the snapshot silently missing models
        # would downgrade their vision support — fail the refresh loudly instead
        # and keep the previous complete snapshot.
        if payload.get("has_more"):
            self._fail("catalog is paginated (has_more=true); parser only reads one page")
            return

        self._models = models
        self._fetched_at = time.monotonic()
        self._failed_at = None
        log.info(
            f"{LogTag.AGENT} Concentrate model catalog refreshed",
            model_catalog={"models": len(models)},
        )

    def _fail(self, reason: str) -> None:
        self._failed_at = time.monotonic()
        log.warning(
            f"{LogTag.AGENT} Concentrate model catalog unavailable; backing off",
            model_catalog={
                "has_snapshot": self._models is not None,
                "reason": reason,
                "backoff_seconds": CONCENTRATE_MODEL_CATALOG_RETRY_SECONDS,
            },
        )

    @staticmethod
    def _parse(payload: dict[str, Any]) -> dict[str, bool]:
        models: dict[str, bool] = {}
        for entry in payload.get("data") or []:
            model_id = entry.get("id")
            if not isinstance(model_id, str):
                continue
            capabilities = entry.get("capabilities") or {}
            image_input = capabilities.get("image_input") or {}
            models[model_id] = bool(image_input.get("supported"))
        return models


CONCENTRATE_MODEL_CATALOG_PROVIDER = "concentrate_model_catalog"


@lazy_provider(name=CONCENTRATE_MODEL_CATALOG_PROVIDER, strategy=MissingKeyStrategy.ERROR)
def init_concentrate_model_catalog() -> ConcentrateModelCatalog:
    """Register the catalog as a sync provider.

    The loader is deliberately sync: `accepts_images` is awaited from the
    pre-model hook, which `sync_execute_hooks` runs under a fresh, short-lived
    event loop each turn. An async provider guards initialization with an
    `asyncio.Lock` bound to the loop it was first used on, which would then fail
    against those later loops; a sync loader uses a thread lock and a lock-free
    fast path once initialized, so it is loop-agnostic.
    """
    return ConcentrateModelCatalog()


async def get_concentrate_catalog() -> ConcentrateModelCatalog:
    """Resolve the process-wide catalog from the provider registry."""
    catalog = await providers.aget(CONCENTRATE_MODEL_CATALOG_PROVIDER)
    if catalog is None:
        raise RuntimeError("Concentrate model catalog provider is not available")
    # aget() is typed Any | None (generic provider registry); this provider is
    # always registered with init_concentrate_model_catalog(), which returns
    # ConcentrateModelCatalog.
    return cast(ConcentrateModelCatalog, catalog)
