"""submit_retry: a retry logs its target again as a retry of the original, and counts once."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.chat import ConversationSource
from app.models.conversation_log_models import UserMessage
from app.models.conversation_send_models import RetryMessageRequest
from app.services.conversation.runtime import install_runtime_ports
from app.services.conversation.send import submit_retry
from app.utils.errors import ConversationEntryNotFoundError
from shared.py.analytics import UserId
from tests.factories import make_authenticated_user
from tests.unit.services.conversation.runtime_doubles import Runtime

pytestmark = pytest.mark.unit

SEND = "app.services.conversation.send"
CONVERSATION = "conv-retry"
USER = make_authenticated_user()
TARGET = UserMessage(
    id="m1",
    text="plan my day",
    surface=ConversationSource.TELEGRAM,
    platform_message_id="tg-41",
    file_ids=("f1", "f2"),
    reply_to="m0",
)


@pytest.fixture
def runtime() -> Iterator[Runtime]:
    runtime = Runtime()
    install_runtime_ports(runtime.ports)
    with patch(f"{SEND}._posthog_session_id", return_value="ph-1"):
        yield runtime


@pytest.fixture(autouse=True)
def budget() -> Iterator[AsyncMock]:
    with patch(f"{SEND}.enforce_cost_budget", new=AsyncMock()) as gate:
        yield gate


def _target(found: UserMessage | None) -> AsyncMock:
    return AsyncMock(return_value=found)


async def _logged(runtime: Runtime) -> list[UserMessage]:
    entries = await runtime.log.read_after(CONVERSATION, USER.user_id, 0)
    return [e.entry for e in entries if isinstance(e.entry, UserMessage)]


async def test_a_retry_logs_its_target_again_as_a_retry_from_the_surface_it_came_from(
    runtime: Runtime, budget: AsyncMock
) -> None:
    with (
        patch(f"{SEND}.conversation_repository.find_user_message", new=_target(TARGET)) as find,
        patch(f"{SEND}.capture", new=MagicMock()) as capture,
    ):
        accepted = await submit_retry(
            CONVERSATION,
            USER,
            RetryMessageRequest(message_id="m2", target="m1"),
            ConversationSource.WEB,
        )

    find.assert_awaited_once_with(USER.user_id, CONVERSATION, "m1")
    budget.assert_awaited_once_with(USER.user_id, feature_key="chat_messages")
    (retry,) = await _logged(runtime)
    assert (
        retry.id,
        retry.text,
        retry.surface,
        retry.platform_message_id,
        retry.retry_of,
        retry.posthog_session_id,
    ) == ("m2", "plan my day", ConversationSource.WEB, None, "m1", "ph-1")
    assert (accepted.conversation_id, accepted.message_id) == (CONVERSATION, "m2")
    (distinct_id, event), _ = capture.call_args
    assert distinct_id == UserId(USER.user_id)
    assert (
        event.is_retry,
        event.is_new_conversation,
        event.stream_id,
        event.source,
        event.has_files,
        event.file_count,
        event.is_reply,
    ) == (True, False, "m2", "web", True, 2, True)


async def test_a_retry_of_a_retry_points_at_the_original_message(runtime: Runtime) -> None:
    earlier = TARGET.model_copy(update={"id": "m2", "retry_of": "m1"})
    with (
        patch(f"{SEND}.conversation_repository.find_user_message", new=_target(earlier)),
        patch(f"{SEND}.capture", new=MagicMock()),
    ):
        await submit_retry(
            CONVERSATION,
            USER,
            RetryMessageRequest(message_id="m3", target="m2"),
            ConversationSource.WEB,
        )

    (retry,) = await _logged(runtime)
    assert retry.retry_of == "m1"


async def test_a_resent_retry_is_logged_and_counted_once(runtime: Runtime) -> None:
    body = RetryMessageRequest(message_id="m2", target="m1")
    with (
        patch(f"{SEND}.conversation_repository.find_user_message", new=_target(TARGET)),
        patch(f"{SEND}.capture", new=MagicMock()) as capture,
    ):
        await submit_retry(CONVERSATION, USER, body, ConversationSource.WEB)
        await submit_retry(CONVERSATION, USER, body, ConversationSource.WEB)

    assert len(await _logged(runtime)) == 1
    capture.assert_called_once()


async def test_a_retry_of_a_message_the_conversation_does_not_hold_is_refused(
    runtime: Runtime,
) -> None:
    with (
        patch(f"{SEND}.conversation_repository.find_user_message", new=_target(None)),
        pytest.raises(
            ConversationEntryNotFoundError, match="no user message m9 in conversation"
        ) as refused,
    ):
        await submit_retry(
            CONVERSATION,
            USER,
            RetryMessageRequest(message_id="m2", target="m9"),
            ConversationSource.WEB,
        )

    assert await _logged(runtime) == []
    assert refused.value.meta == {"conversation_id": CONVERSATION, "entry_id": "m9"}
