"""Everything GAIA tells a user on its own goes through one retry-safe pipeline, against real Mongo and Redis.

The seams are the transports: the RabbitMQ publisher, Expo's HTTP endpoint, the
device-token store and the websocket. Routing, the notification record, the
per-channel claims, the bot DM session and its conversation log are real.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
import httpx
import pytest

from app.agents.core.background.todo_run_delivery import FinishedTodoRun, finish_todo_run
from app.constants.chat import CONVERSATION_ENTRIES_COLLECTION
from app.db.repositories.conversation_log import conversation_log_repository
from app.db.repositories.todos import todo_repository
from app.models.conversation_log_models import TodoReportForm
from app.models.reminder_models import AgentType, ReminderModel, StaticReminderPayload
from app.models.scheduler_models import ScheduledTaskStatus
from app.models.todo_models import TodoDocument
from app.models.workflow_models import TriggerType
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.ports import RuntimePorts
from app.services.conversation.runtime import install_runtime_ports
from app.services.hil.notify import notify_approval_pending
from app.services.integrations.integration_expiry import AccountExpired, announce_account_expiry
from app.services.platform_link_service import PlatformLinkService
from app.services.workflow.notifications import notify_workflow_result
from app.tasks.reminder_tasks import _execute_static_reminder
from shared.py.conversation_wire import ReplyOutcome
from tests.unit.services.conversation.runtime_doubles import (
    RecordingAnalytics,
    RecordingEffects,
    RecordingFrames,
    ScriptedApprovals,
    ScriptedRunner,
    TickGate,
)

pytestmark = pytest.mark.service

LINKED_OID = ObjectId("6acc0dac0cc0a00000000201")
UNLINKED_OID = ObjectId("6acc0dac0cc0a00000000202")
TELEGRAM_USER_ID = "tg-notify-1"
DEVICE_TOKEN = "ExponentPushToken[notify-pipeline]"


@dataclass
class Delivered:
    """What reached the user, per transport."""

    bot_messages: list[dict[str, object]] = field(default_factory=list)
    pushes: list[list[dict[str, object]]] = field(default_factory=list)
    socket_events: list[dict[str, object]] = field(default_factory=list)


@pytest.fixture
def delivered() -> Iterator[Delivered]:
    seen = Delivered()

    async def publish_outbound(queue: str, body: bytes, expiration: int) -> None:
        seen.bot_messages.append(json.loads(body))

    def expo(request: httpx.Request) -> httpx.Response:
        seen.pushes.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"status": "ok"}]})

    real_client = httpx.AsyncClient
    tokens = MagicMock()
    tokens.get_active_tokens = AsyncMock(return_value=[DEVICE_TOKEN])

    async def broadcast(user_id: str, message: dict[str, object]) -> None:
        seen.socket_events.append(message)

    with (
        patch(
            "app.services.outbound_delivery.get_rabbitmq_publisher",
            AsyncMock(return_value=MagicMock(publish_outbound=publish_outbound)),
        ),
        patch(
            "app.utils.notification.channels.push.httpx.AsyncClient",
            lambda **kw: real_client(transport=httpx.MockTransport(expo), **kw),
        ),
        patch(
            "app.utils.notification.channels.push.get_device_token_service",
            return_value=tokens,
        ),
        patch(
            "app.utils.notification.orchestrator.websocket_manager.broadcast_to_user",
            broadcast,
        ),
    ):
        yield seen


async def _no_tick() -> None:
    return None


@pytest.fixture(autouse=True)
def _runtime() -> None:
    """Install the real Mongo conversation log; nothing a Notice appends runs a step here."""
    install_runtime_ports(
        RuntimePorts(
            log=MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC)),
            runner=ScriptedRunner(TickGate()),
            frames=RecordingFrames(),
            effects=RecordingEffects(),
            approvals=ScriptedApprovals(),
            analytics=RecordingAnalytics(),
            clock=lambda: datetime.now(UTC),
            tick=_no_tick,
        )
    )


@pytest.fixture(autouse=True)
async def _users(mongo_db, real_redis, conversations_collection):
    oids = [LINKED_OID, UNLINKED_OID]
    await mongo_db["users"].delete_many({"_id": {"$in": oids}})
    await mongo_db["notifications"].delete_many({})
    await mongo_db["notifications"].create_index("id", unique=True)
    await mongo_db["bot_sessions"].delete_many({})
    await mongo_db["bot_sessions"].create_index("session_key", unique=True)
    await mongo_db["todos"].delete_many({"user_id": {"$in": [str(o) for o in oids]}})
    await mongo_db["users"].insert_many(
        [{"_id": oid, "email": f"notify-{oid}@gaia.local", "platform_links": {}} for oid in oids]
    )
    await PlatformLinkService.link_account(str(LINKED_OID), "telegram", TELEGRAM_USER_ID)
    yield
    await mongo_db["users"].delete_many({"_id": {"$in": oids}})
    await mongo_db["notifications"].delete_many({})
    await mongo_db["bot_sessions"].delete_many({})


async def _notifications(mongo_db, user_id: str) -> list[dict[str, object]]:
    return await mongo_db["notifications"].find({"user_id": user_id}).to_list(None)


async def _notices(mongo_db) -> list[dict[str, object]]:
    return await mongo_db[CONVERSATION_ENTRIES_COLLECTION].find({"kind": "notice"}).to_list(None)


def _reminder(user_id: str) -> ReminderModel:
    return ReminderModel(
        _id=str(ObjectId()),
        user_id=user_id,
        agent=AgentType.STATIC,
        payload=StaticReminderPayload(title="Stretch", body="Stand up for a minute").model_dump(),
        repeat=None,
        scheduled_at=datetime.now(UTC) + timedelta(hours=1),
        status=ScheduledTaskStatus.SCHEDULED,
        occurrence_count=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


async def test_a_retried_reminder_sends_one_notification_one_bot_message_one_push(
    mongo_db, delivered: Delivered
) -> None:
    reminder = _reminder(str(LINKED_OID))

    await _execute_static_reminder(reminder)
    await _execute_static_reminder(reminder)

    (stored,) = await _notifications(mongo_db, str(LINKED_OID))
    assert stored["status"] == "delivered"
    (message,) = delivered.bot_messages
    assert message["destination_id"] == TELEGRAM_USER_ID
    assert message["notification_id"] == stored["id"]
    assert message["text"] == "**Stretch**\nStand up for a minute"
    assert len(delivered.pushes) == 1
    assert [e["type"] for e in delivered.socket_events] == ["notification.delivered"]
    (notice,) = await _notices(mongo_db)
    assert notice["text"] == "**Stretch**\nStand up for a minute"


@pytest.mark.parametrize(
    ("oid", "bot_messages"), [(LINKED_OID, 1), (UNLINKED_OID, 0)], ids=["chat-app", "app-only"]
)
async def test_a_workflow_result_is_delivered_once_on_the_users_channel(
    mongo_db, delivered: Delivered, oid: ObjectId, bot_messages: int
) -> None:
    for _ in range(2):
        await notify_workflow_result(
            workflow_id="wf-1",
            workflow_title="Morning brief",
            execution_id="exec-1",
            conversation_id="wf-conv-1",
            user_id=str(oid),
            result_text="Three meetings today.",
        )

    (stored,) = await _notifications(mongo_db, str(oid))
    assert stored["status"] == "delivered"
    assert [m["text"] for m in delivered.bot_messages] == ["Three meetings today."] * bot_messages
    assert len(delivered.socket_events) == 1


@pytest.mark.parametrize(
    ("oid", "bot_messages"), [(LINKED_OID, 1), (UNLINKED_OID, 0)], ids=["chat-app", "app-only"]
)
async def test_a_todo_run_result_is_delivered_once_on_the_users_channel(
    mongo_db, delivered: Delivered, oid: ObjectId, bot_messages: int
) -> None:
    todo = await todo_repository.create(
        TodoDocument(user_id=str(oid), title="Watch flight prices", notify_on_run=True)
    )
    finished = FinishedTodoRun(
        run_id="run-1",
        todo_id=todo.id or "",
        user_id=str(oid),
        conversation_id="todo-conv-1",
        trigger_type=TriggerType.SCHEDULE,
        report_form=TodoReportForm.WRITE_UP,
        result_text="Fares dropped 12%.",
        write_up="Fares to Lisbon dropped 12%.",
        reply=ReplyOutcome.ANSWERED,
    )
    # A crash after the send and before the finish entry: the durable job runs it again.
    await finish_todo_run(finished)
    await mongo_db["todos"].update_one(
        {"_id": ObjectId(todo.id)}, {"$set": {"activity_content": ""}}
    )
    await finish_todo_run(finished)

    (stored,) = await _notifications(mongo_db, str(oid))
    assert stored["status"] == "delivered"
    assert [m["text"] for m in delivered.bot_messages] == [
        "Fares to Lisbon dropped 12%."
    ] * bot_messages


async def test_a_pending_approval_pushes_once_and_never_prompts_the_bot(
    mongo_db, delivered: Delivered
) -> None:
    for _ in range(2):
        await notify_approval_pending(str(LINKED_OID), "conv-9", "approval-1", "Send the email?")

    (push,) = delivered.pushes
    (message,) = push
    assert message["categoryId"] == "hil_approval"
    data = message["data"]
    assert isinstance(data, dict)
    assert data["approval_id"] == "approval-1"
    assert delivered.bot_messages == []
    assert delivered.socket_events == []
    assert len(await _notifications(mongo_db, str(LINKED_OID))) == 1


async def test_an_integration_expiry_raises_one_notification(
    mongo_db, delivered: Delivered
) -> None:
    account = MagicMock(id="acct-1", display_name="work")
    expired = AccountExpired(
        account=account, account_count=1, was_primary=True, integration_expired=True
    )
    with patch(
        "app.services.integrations.integration_expiry.websocket_manager",
        MagicMock(broadcast_to_user=AsyncMock()),
    ):
        for _ in range(2):
            await announce_account_expiry(str(LINKED_OID), "gmail", expired, [], None)

    (stored,) = await _notifications(mongo_db, str(LINKED_OID))
    request = stored["original_request"]
    assert isinstance(request, dict)
    assert request["source"] == "integration_expired"
    assert delivered.bot_messages == []
    assert len(delivered.socket_events) == 1
