"""Unit tests for model_service (model lookup with Cacheable layer bypassed)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest

from app.models.models_models import ModelConfig, ModelProvider, PlanType
from app.services.model_service import get_model_by_id

_MOD = "app.services.model_service"


def _model_config() -> ModelConfig:
    return ModelConfig(
        model_id="gemini-3.1-flash-lite",
        name="Gemini 3.1 Flash Lite",
        model_provider=ModelProvider.GEMINI,
        inference_provider=ModelProvider.GEMINI,
        provider_model_name="gemini-3.1-flash-lite",
        max_tokens=8192,
        available_in_plans=[PlanType.FREE],
        lowest_tier=PlanType.FREE,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_redis_cache():
    """Bypass the @Cacheable layer so the wrapped function body runs."""
    with (
        patch("app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None),
        patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
    ):
        yield


@pytest.fixture
def mock_repo():
    with patch(f"{_MOD}.ai_model_repository") as m:
        m.get_by_model_id = AsyncMock()
        m.get_default = AsyncMock()
        yield m


class TestGetModelById:
    async def test_returns_model(self, mock_repo, mock_redis_cache):
        model = _model_config()
        mock_repo.get_by_model_id.return_value = model

        result = await get_model_by_id("gemini-3.1-flash-lite")

        assert result is model
        mock_repo.get_by_model_id.assert_awaited_once_with("gemini-3.1-flash-lite")

    async def test_returns_none_when_unknown(self, mock_repo, mock_redis_cache):
        mock_repo.get_by_model_id.return_value = None

        result = await get_model_by_id("does-not-exist")

        assert result is None

    async def test_repository_failure_becomes_500(self, mock_repo, mock_redis_cache):
        mock_repo.get_by_model_id.side_effect = RuntimeError("mongo down")

        with pytest.raises(HTTPException) as exc_info:
            await get_model_by_id("gemini-3.1-flash-lite")

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to fetch model"
