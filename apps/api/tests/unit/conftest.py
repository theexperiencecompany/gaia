"""Shared fixtures for unit tests."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from loguru import logger as loguru_logger
import pytest
import sentry_sdk
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport
from sentry_sdk.types import Event

from app.agents.core.background import session as stream_session
from app.config.sentry import init_sentry
from tests.factories import make_config, make_state, make_user
from tests.helpers import create_fake_llm, create_fake_llm_with_tool_calls


@pytest.fixture(autouse=True)
def _isolate_stream_registries() -> Iterator[None]:
    # Module-global: a stream id another test left abandoned makes finalize skip delivery.
    stream_session._sessions.clear()
    stream_session._abandoned.clear()
    yield
    stream_session._sessions.clear()
    stream_session._abandoned.clear()


class _CapturingTransport(Transport):
    """Keep every error event the client would send to Sentry, in send order."""

    def __init__(self, options: dict[str, object]) -> None:
        super().__init__(options)
        self.events: list[Event] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        event = envelope.get_event()
        if event is not None:
            self.events.append(event)


@pytest.fixture
def sentry_events() -> Iterator[list[Event]]:
    """Run the real init_sentry against a transport stub; yields the error events sent."""
    with (
        patch("app.config.sentry.settings.SENTRY_DSN", "https://public@sentry.invalid/1"),
        patch("app.config.sentry._loguru") as sentry_loguru,
    ):
        init_sentry()
    # Re-run the sink registration on the real logger so this fixture owns its handler ids.
    added_sinks = [
        loguru_logger.add(*call.args, **call.kwargs) for call in sentry_loguru.add.call_args_list
    ]
    client = sentry_sdk.get_client()
    transport = _CapturingTransport(client.options)
    client.transport = transport
    yield transport.events
    for handler_id in added_sinks:
        loguru_logger.remove(handler_id)
    # init_sentry's tags live on the global scope; left there, a later test reads them as its own.
    global_scope = sentry_sdk.get_global_scope()
    global_scope.clear()
    global_scope.set_client(None)


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
        mock_get_collection.side_effect = lambda name: collection_mocks.get(name, AsyncMock())
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
def sample_user() -> dict:
    return make_user()


@pytest.fixture
def sample_state():
    return make_state()


@pytest.fixture
def sample_config() -> dict:
    return make_config()
