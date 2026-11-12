"""POST /conversations/{id}/messages accepts into the step at once, checked against real MongoDB."""

from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from httpx import AsyncClient
import pytest
from redis.asyncio import Redis

from app.constants.conversation import ConversationRuntime
from app.constants.error_codes import CONVERSATION_ON_STREAM_PATH
from app.db.repositories.conversation_log import conversation_log_repository
from app.db.repositories.conversations import conversation_repository
from app.models.conversation_log_models import UserMessage
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.ports import RuntimePorts
from app.services.conversation.runtime import install_runtime_ports
from tests.conftest import FAKE_USER
from tests.unit.services.conversation.runtime_doubles import (
    EffectCall,
    RecordingEffects,
    RecordingFrames,
    ScriptedApprovals,
    ScriptedRunner,
    TickGate,
)

pytestmark = pytest.mark.service


async def _no_tick() -> None:
    return None


@dataclass(frozen=True)
class Sends:
    """The route's recorded effects, and its analytics capture."""

    effects: RecordingEffects
    captured: MagicMock


@pytest.fixture
def sends(conversations_collection: object, real_redis: Redis) -> Iterator[Sends]:
    """Install the real Mongo log behind recording effects, and clear the gates the route charges."""
    recorded = RecordingEffects()
    ticks = TickGate()
    install_runtime_ports(
        RuntimePorts(
            log=MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC)),
            runner=ScriptedRunner(ticks),
            frames=RecordingFrames(),
            effects=recorded,
            approvals=ScriptedApprovals(),
            clock=lambda: datetime.now(UTC),
            tick=_no_tick,
        )
    )
    with (
        patch(
            "app.api.v1.middleware.tiered_rate_limiter.tiered_limiter.check_and_increment",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("app.services.conversation.send.enforce_cost_budget", new_callable=AsyncMock),
        patch("app.services.conversation.send.capture") as captured,
        patch("app.services.conversation_service.capture"),
    ):
        yield Sends(effects=recorded, captured=captured)


def _send(message_id: str, text: str = "book it for $600") -> dict[str, object]:
    return {"message_id": message_id, "text": text}


async def test_a_send_returns_202_with_its_seq_and_kicks_the_step(
    client: AsyncClient, sends: Sends
) -> None:
    conversation_id = f"convrt-{uuid4().hex[:10]}"
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json=_send("m1")
    )
    assert response.status_code == 202, response.text
    assert response.json() == {"conversation_id": conversation_id, "message_id": "m1", "seq": 1}
    row = await conversation_repository.read_runtime(conversation_id, user_id=FAKE_USER.user_id)
    assert row is not None
    assert row.runtime is ConversationRuntime.STEP
    assert EffectCall("kick") in sends.effects.calls


async def test_a_resent_message_keeps_its_first_seq_and_is_stored_once(
    client: AsyncClient, sends: Sends
) -> None:
    conversation_id = f"convrt-{uuid4().hex[:10]}"
    url = f"/api/v1/conversations/{conversation_id}/messages"
    first = await client.post(url, json=_send("m1"))
    again = await client.post(url, json=_send("m1"))
    entries = await conversation_log_repository.read_log(conversation_id, user_id=FAKE_USER.user_id)
    assert (first.status_code, again.status_code) == (202, 202), first.text
    assert (first.json()["seq"], again.json()["seq"]) == (1, 1)
    assert [e.entry.id for e in entries or [] if isinstance(e.entry, UserMessage)] == ["m1"]
    assert sends.captured.call_count == 1


async def test_a_send_into_a_legacy_conversation_is_refused(
    client: AsyncClient,
    sends: Sends,
    make_conversation: Callable[..., Awaitable[str]],
) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json=_send("m1")
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == CONVERSATION_ON_STREAM_PATH
    assert sends.effects.calls == []
