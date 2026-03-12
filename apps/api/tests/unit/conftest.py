"""Shared fixtures for unit tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)

from tests.factories import make_config, make_state, make_user
from tests.helpers import create_fake_llm, create_fake_llm_with_tool_calls


@pytest.fixture
def fake_llm() -> FakeMessagesListChatModel:
    return create_fake_llm(["This is a test response."])


@pytest.fixture
def fake_llm_with_tool_calls() -> FakeMessagesListChatModel:
    tool_call = {
        "name": "test_tool",
        "args": {"query": "test"},
        "id": "call_test123",
        "type": "tool_call",
    }
    return create_fake_llm_with_tool_calls([tool_call, "Final response."])


@pytest.fixture
def mock_mongodb():
    collections = [
        "conversations_collection",
        "users_collection",
        "todos_collection",
        "integrations_collection",
        "user_integrations_collection",
        "workflows_collection",
        "reminders_collection",
        "notes_collection",
        "calendars_collection",
        "files_collection",
        "notifications_collection",
        "goals_collection",
        "feedback_collection",
        "mail_collection",
        "blog_collection",
        "support_collection",
        "payments_collection",
        "subscriptions_collection",
        "plans_collection",
        "skills_collection",
        "bot_sessions_collection",
        "device_tokens_collection",
        "vfs_nodes_collection",
        "projects_collection",
        "workflow_executions_collection",
        "processed_webhooks_collection",
    ]
    mocks = {}
    for col in collections:
        mock = AsyncMock()
        mocks[col] = mock

    with patch("app.db.mongodb.collections._get_collection") as mock_get_collection:
        collection_mocks = {col: AsyncMock() for col in collections}
        mock_get_collection.side_effect = lambda name: collection_mocks.get(
            name, AsyncMock()
        )
        yield collection_mocks


@pytest.fixture
def mock_redis():
    with patch("app.db.redis.redis_cache") as mock_cache:
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.delete = AsyncMock()
        mock_cache.redis = MagicMock()
        yield mock_cache


@pytest.fixture
def mock_mem0():
    with patch("app.services.memory_service.memory_service") as mock_service:
        mock_service.store_memory = AsyncMock(return_value=None)
        mock_service.store_memory_batch = AsyncMock(return_value=True)
        mock_service.search_memories = AsyncMock(
            return_value=MagicMock(memories=[], relations=[], total_count=0)
        )
        mock_service.get_all_memories = AsyncMock(
            return_value=MagicMock(memories=[], relations=[], total_count=0)
        )
        mock_service.delete_memory = AsyncMock(return_value=True)
        mock_service.delete_all_memories = AsyncMock(return_value=True)
        yield mock_service


@pytest.fixture
def sample_user() -> dict:
    return make_user()


@pytest.fixture
def sample_state():
    return make_state()


@pytest.fixture
def sample_config() -> dict:
    return make_config()
