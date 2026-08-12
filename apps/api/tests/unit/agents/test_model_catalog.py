"""Behavior tests for app.agents.llm.model_catalog (OpenRouter vision catalog).

Locks: image-support parsing from ``input_modalities``, the TTL/retry cache
semantics (fresh snapshot reused, failed refresh remembered for the backoff
window, stale snapshot outliving a failure, fail-safe to non-vision with no
snapshot), and rejection of a catalog that yields no models.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.llm.model_catalog import OpenRouterModelCatalog
from app.constants.llm import OPENROUTER_MODEL_CATALOG_TTL_SECONDS

CATALOG = "app.agents.llm.model_catalog"

MODEL_VISION = "vision/model"
MODEL_TEXT = "text/model"
MODEL_NO_MODALITIES = "empty/model"
MODEL_NO_ARCH = "noarch/model"

PAYLOAD_VISION = {
    "data": [
        {"id": MODEL_VISION, "architecture": {"input_modalities": ["text", "image"]}},
        {"id": MODEL_TEXT, "architecture": {"input_modalities": ["text"]}},
        {"id": MODEL_NO_MODALITIES, "architecture": {"input_modalities": []}},
        {"id": MODEL_NO_ARCH, "architecture": None},
        {"no_id": True},
    ]
}


def _httpx_client(payload: dict | None = None, error: Exception | None = None) -> MagicMock:
    """A mocked httpx.AsyncClient whose GET returns ``payload`` or raises ``error``."""
    mock_client_cls = MagicMock()
    client_instance = mock_client_cls.return_value.__aenter__.return_value
    if error is not None:
        client_instance.get = AsyncMock(side_effect=error)
    else:
        response = MagicMock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        client_instance.get = AsyncMock(return_value=response)
    return mock_client_cls


def _catalog_with_snapshot() -> OpenRouterModelCatalog:
    catalog = OpenRouterModelCatalog()
    catalog._models = {MODEL_VISION: True, MODEL_TEXT: False}
    catalog._fetched_at = time.monotonic()
    return catalog


class TestParse:
    def test_image_modality_is_vision_true(self) -> None:
        assert OpenRouterModelCatalog._parse(PAYLOAD_VISION)[MODEL_VISION] is True

    def test_text_only_model_is_not_vision(self) -> None:
        assert OpenRouterModelCatalog._parse(PAYLOAD_VISION)[MODEL_TEXT] is False

    def test_empty_modalities_and_missing_architecture_are_not_vision(self) -> None:
        parsed = OpenRouterModelCatalog._parse(PAYLOAD_VISION)
        assert parsed[MODEL_NO_MODALITIES] is False
        assert parsed[MODEL_NO_ARCH] is False

    def test_entries_without_an_id_are_skipped(self) -> None:
        parsed = OpenRouterModelCatalog._parse(PAYLOAD_VISION)
        assert set(parsed) == {MODEL_VISION, MODEL_TEXT, MODEL_NO_MODALITIES, MODEL_NO_ARCH}


class TestAcceptsImages:
    async def test_fresh_snapshot_is_used_without_a_refresh(self) -> None:
        catalog = _catalog_with_snapshot()
        with patch(f"{CATALOG}.httpx.AsyncClient") as mock_client:
            assert await catalog.accepts_images(MODEL_VISION) is True
            assert await catalog.accepts_images(MODEL_TEXT) is False
            assert await catalog.accepts_images("unknown/model") is False
        mock_client.assert_not_called()

    async def test_unknown_model_fails_safe_to_false(self) -> None:
        catalog = _catalog_with_snapshot()
        assert await catalog.accepts_images("does/not/exist") is False

    async def test_no_snapshot_fetches_and_parses(self) -> None:
        catalog = OpenRouterModelCatalog()
        with patch(f"{CATALOG}.httpx.AsyncClient", _httpx_client(PAYLOAD_VISION)):
            assert await catalog.accepts_images(MODEL_VISION) is True
            assert catalog._models is not None

    async def test_stale_snapshot_triggers_a_refresh(self) -> None:
        catalog = _catalog_with_snapshot()
        catalog._fetched_at = time.monotonic() - OPENROUTER_MODEL_CATALOG_TTL_SECONDS - 10
        with patch(f"{CATALOG}.httpx.AsyncClient", _httpx_client(PAYLOAD_VISION)):
            assert await catalog.accepts_images(MODEL_VISION) is True

    async def test_failed_refresh_with_no_snapshot_fails_safe_and_backs_off(self) -> None:
        catalog = OpenRouterModelCatalog()
        mock_client = _httpx_client(error=RuntimeError("openrouter down"))
        with patch(f"{CATALOG}.httpx.AsyncClient", mock_client):
            assert await catalog.accepts_images(MODEL_VISION) is False
            # The failure is remembered: within the backoff window no retry happens.
            assert await catalog.accepts_images(MODEL_VISION) is False
        assert mock_client.return_value.__aenter__.return_value.get.await_count == 1

    async def test_failed_refresh_keeps_the_stale_snapshot(self) -> None:
        catalog = _catalog_with_snapshot()
        catalog._fetched_at = time.monotonic() - OPENROUTER_MODEL_CATALOG_TTL_SECONDS - 10
        with patch(f"{CATALOG}.httpx.AsyncClient", _httpx_client(error=RuntimeError("down"))):
            assert await catalog.accepts_images(MODEL_VISION) is True
        assert catalog._models[MODEL_VISION] is True

    async def test_catalog_with_no_models_is_treated_as_a_failure(self) -> None:
        catalog = OpenRouterModelCatalog()
        with patch(f"{CATALOG}.httpx.AsyncClient", _httpx_client({"data": []})):
            assert await catalog.accepts_images(MODEL_VISION) is False
        assert catalog._models is None
        assert catalog._failed_at is not None

    async def test_http_error_status_marks_a_failure(self) -> None:
        catalog = OpenRouterModelCatalog()
        mock_client_cls = MagicMock()
        client_instance = mock_client_cls.return_value.__aenter__.return_value
        response = MagicMock()
        response.raise_for_status.side_effect = RuntimeError("502")
        client_instance.get = AsyncMock(return_value=response)
        with patch(f"{CATALOG}.httpx.AsyncClient", mock_client_cls):
            assert await catalog.accepts_images(MODEL_VISION) is False
        assert catalog._failed_at is not None
