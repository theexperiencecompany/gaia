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

    async def test_get_default_prefers_default(self, repo):
        await repo.create(_model(model_id="a", is_default=False, is_active=True))
        await repo.create(_model(model_id="b", is_default=True, is_active=True))
        default = await repo.get_default()
        assert default is not None and default.model_id == "b"

    async def test_get_default_falls_back_to_any_active(self, repo):
        await repo.create(_model(model_id="only", is_default=False, is_active=True))
        await repo.create(_model(model_id="off", is_default=False, is_active=False))
        default = await repo.get_default()
        assert default is not None and default.model_id == "only"

    async def test_get_default_none_when_no_active(self, repo):
        await repo.create(_model(model_id="off", is_active=False))
        assert await repo.get_default() is None

    async def test_count(self, repo):
        await repo.create(_model(model_id="x"))
        await repo.create(_model(model_id="y"))
        assert await repo.count() == 2
