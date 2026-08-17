"""Contract tests for AiModelsRepository (global catalog, business key model_id)."""

from __future__ import annotations

import pytest

from app.db.repositories.ai_models import AiModelsRepository
from app.models.models_models import ModelConfig


def _model(**overrides: object) -> ModelConfig:
    data: dict[str, object] = {
        "model_id": "m1",
        "name": "Model One",
        "model_provider": "openai",
        "inference_provider": "openai",
        "provider_model_name": "gpt-x",
        "max_tokens": 1000,
        "available_in_plans": ["free"],
        "lowest_tier": "free",
    }
    data.update(overrides)
    return ModelConfig.model_validate(data)


@pytest.fixture
def repo(raw_collection) -> AiModelsRepository:
    return AiModelsRepository()


class TestAiModelsRepository:
    async def test_create_and_get_by_model_id(self, repo):
        created = await repo.create(_model(model_id="gpt-x"))
        assert created.model_id == "gpt-x"
        got = await repo.get_by_model_id("gpt-x")
        assert got is not None and got.model_id == "gpt-x"
        assert await repo.get_by_model_id("missing") is None

    async def test_count(self, repo):
        await repo.create(_model(model_id="x"))
        await repo.create(_model(model_id="y"))
        assert await repo.count() == 2
