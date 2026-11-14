"""Every writer of a chat message appends a log entry, and what a client then reads, on real Mongo."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from bson import ObjectId
from httpx import AsyncClient
import pytest
from redis.asyncio import Redis

from app.agents.core.background import folded_stream
from app.agents.core.background.folded_stream import close_folded_stream, open_folded_stream
from app.agents.core.background.running_registry import RunningSubagents
from app.agents.core.background.work_cancel import cancel_named_work
from app.api.v1.endpoints.bot_links import _persist_first_contact
from app.constants.chat import ConversationSource
from app.core.stream_manager import stream_manager
from app.db.repositories.conversation_log import conversation_log_repository
from app.db.repositories.conversations import conversation_repository
from app.models.agent_models import RunningSubagent
from app.models.bot_models import RedeemLinkCodeRequest
from app.models.conversation_log_models import (
    ApprovalDecided,
    Entry,
    Reply,
    ReplyOutcome,
    ReplySettled,
    UserMessage,
    WorkOutcome,
)
from app.models.conversation_models import ConversationDocument
from app.models.conversation_screen_models import WorkItem
from app.models.tool_data_models import ToolDataEntry
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.ports import RuntimePorts
from app.services.conversation.runtime import install_runtime_ports, runtime_ports
from app.services.conversation.screen import project_screen
from app.services.conversation.work_log import record_user_stop
from app.services.onboarding.first_conversation import FirstConversation
from app.utils.seeding_utils import seed_first_conversation
from shared.py.analytics.catalog.hil import ApprovalDecider, ApprovalOutcome
from tests.conftest import FAKE_USER
from tests.helpers import shown_messages
from tests.unit.services.conversation.log_helpers import asked, finished, started
from tests.unit.services.conversation.runtime_doubles import (
    RecordingAnalytics,
    RecordingEffects,
    RecordingFrames,
    ScriptedApprovals,
    ScriptedRunner,
    TickGate,
)

pytestmark = pytest.mark.service


async def _no_tick() -> None:
    return None


@pytest.fixture
def mongo_log(
    conversations_collection: object, real_redis: Redis
) -> Iterator[MongoConversationLog]:
    log = MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC))
    install_runtime_ports(
        RuntimePorts(
            log=log,
            runner=ScriptedRunner(TickGate()),
            frames=RecordingFrames(),
            effects=RecordingEffects(),
            approvals=ScriptedApprovals(),
            analytics=RecordingAnalytics(),
            clock=lambda: datetime.now(UTC),
            tick=_no_tick,
        )
    )
    with patch("app.services.conversation_service.capture"):
        yield log


async def _chat(user_id: str, entries: list[Entry]) -> str:
    conversation_id = f"c-{uuid4().hex}"
    await conversation_repository.create(
        ConversationDocument.model_validate(
            {"user_id": user_id, "conversation_id": conversation_id}
        )
    )
    for entry in entries:
        await runtime_ports().log.append(conversation_id, user_id, entry)
    return conversation_id


def _turn(text: str, *, cards: tuple[ToolDataEntry, ...] = ()) -> list[Entry]:
    return [
        UserMessage(id="u1", text=text, surface=ConversationSource.WEB),
        Reply(id="o1", reply_id="r1", attempt_id="a1", text="done", tool_data=cards),
        ReplySettled(
            id="s1",
            reply_id="r1",
            outcome=ReplyOutcome.ANSWERED,
            answers=("u1",),
            through=1,
            quote_target=None,
        ),
    ]


async def _messages(user_id: str, conversation_id: str) -> list[tuple[object, ...]]:
    doc = await conversation_repository.get(conversation_id, user_id=user_id)
    assert doc is not None
    return [(m.type, m.message_id, m.response) for m in shown_messages(doc)]


async def test_a_seeded_first_conversation_is_gaias_notices_with_their_cards_and_chips(
    mongo_log: MongoConversationLog,
) -> None:
    user_id = str(ObjectId())
    composed = FirstConversation(
        opening=["Hi", "I keep your day"],
        question="What first?",
        follow_ups=["Plan my day"],
        connect_options=[{"id": "gmail", "name": "Gmail"}],
    )

    conversation_id = await seed_first_conversation(user_id, composed)

    assert conversation_id is not None
    doc = await conversation_repository.get(conversation_id, user_id=user_id)
    assert doc is not None
    assert [(m.type, bool(m.tool_data), m.follow_up_actions) for m in shown_messages(doc)] == [
        ("bot", False, None),
        ("bot", True, None),
        ("bot", False, ["Plan my day"]),
    ]
    assert shown_messages(doc)[2].response == "What first?"
    state = await mongo_log.state(conversation_id, user_id)
    assert state.unsettled_waking == ()


async def test_the_first_contact_exchange_is_logged_and_wakes_no_reply(
    mongo_log: MongoConversationLog,
) -> None:
    user_id = str(ObjectId())
    conversation_id = await _chat(user_id, [])
    body = RedeemLinkCodeRequest(
        platform="telegram", platform_user_id="42", code="c", first_message="hey gaia"
    )

    with patch(
        "app.api.v1.endpoints.bot_links.BotService.get_or_create_session",
        new=AsyncMock(return_value=conversation_id),
    ):
        await _persist_first_contact(user_id, body, ["Hi!", "I'm GAIA"])

    assert await _messages(user_id, conversation_id) == [
        ("user", f"first-contact:{conversation_id}:user", "hey gaia"),
        ("bot", f"first-contact:{conversation_id}:intro", "Hi!<NEW_MESSAGE_BREAK>I'm GAIA"),
    ]
    state = await mongo_log.state(conversation_id, user_id)
    assert (state.unsettled_waking, state.head) == ((), 2)


async def test_put_messages_is_gone(client: AsyncClient, mongo_log: MongoConversationLog) -> None:
    response = await client.put("/api/v1/conversations/c1/messages", json={"messages": []})
    assert response.status_code == 405


async def test_a_pin_survives_reload_and_lists_until_unpinned(
    client: AsyncClient, mongo_log: MongoConversationLog
) -> None:
    conversation_id = await _chat(FAKE_USER.user_id, _turn("book it"))
    pin = f"/api/v1/conversations/{conversation_id}/messages/r1/pin"

    assert (await client.put(pin, json={"pinned": True})).status_code == 200
    doc = await conversation_repository.get(conversation_id, user_id=FAKE_USER.user_id)
    assert doc is not None
    assert [(m.message_id, m.pinned) for m in shown_messages(doc)] == [("u1", None), ("r1", True)]
    listed = await conversation_repository.list_pinned_messages(FAKE_USER.user_id)
    assert [(hit.conversation_id, hit.message.message_id) for hit in listed] == [
        (conversation_id, "r1")
    ]
    assert (await client.put(pin, json={"pinned": False})).status_code == 200
    assert await conversation_repository.list_pinned_messages(FAKE_USER.user_id) == []
    missing = f"/api/v1/conversations/{conversation_id}/messages/nope/pin"
    assert (await client.put(missing, json={"pinned": True})).status_code == 404


async def test_a_detached_runs_cards_sit_where_it_started_until_a_reply_answers_that_work(
    mongo_log: MongoConversationLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = str(ObjectId())
    conversation_id = await _chat(user_id, _turn("look it up"))
    cards: list[ToolDataEntry] = [{"tool_name": "browser", "data": {"step": 1}}]
    monkeypatch.setattr(folded_stream, "drain_executor_tool_data", lambda _stream: cards)

    assert await open_folded_stream("job-1", conversation_id=conversation_id, user_id=user_id)
    await mongo_log.append(
        conversation_id, user_id, UserMessage(id="u2", text="later", surface=ConversationSource.WEB)
    )
    await close_folded_stream("job-1", conversation_id=conversation_id, user_id=user_id)

    doc = await conversation_repository.get(conversation_id, user_id=user_id)
    assert doc is not None
    assert [(m.message_id, m.tool_data) for m in shown_messages(doc)[2:]] == [
        ("work:job-1", cards),
        ("u2", None),
    ]
    state = await mongo_log.state(conversation_id, user_id)
    assert (state.work, state.finished_work) == ((), ())


async def test_a_stop_cancels_a_background_subagent_that_outlived_its_run(
    mongo_log: MongoConversationLog,
) -> None:
    user_id = str(ObjectId())
    conversation_id = await _chat(user_id, _turn("research it"))
    stream_id = f"subagent_{uuid4().hex}"
    await stream_manager.start_stream(
        stream_id=stream_id, conversation_id=conversation_id, user_id=user_id
    )
    subagent = RunningSubagent(
        subagent_id="sa-1",
        subagent_thread_id=f"thread-{uuid4().hex}",
        integration_id="notion",
        agent_name="notion",
        task_summary="research it",
        started_at=datetime.now(UTC).isoformat(),
        stream_id=stream_id,
        dispatched_by="executor-stream-that-ended",
    )
    assert await RunningSubagents(conversation_id).claim(subagent)
    assert await open_folded_stream(stream_id, conversation_id=conversation_id, user_id=user_id)

    await record_user_stop(conversation_id, user_id, "stop-1")
    effects = runtime_ports().effects
    assert isinstance(effects, RecordingEffects)
    [cancel] = [call.argument for call in effects.calls if call.name == "cancel_work"]
    assert isinstance(cancel, tuple)
    cancelled = await cancel_named_work(conversation_id, user_id, cancel, approval_ids=())

    assert cancelled.subagent_ids == ["sa-1"]
    assert await stream_manager.is_cancelled(stream_id)


async def _card_status(user_id: str, conversation_id: str) -> object:
    """Read the approval card the screen draws for t1 from the stored log: its outcome and who decided."""
    entries = await conversation_log_repository.read_log(conversation_id, user_id=user_id)
    [work] = [item for item in project_screen(entries or []) if isinstance(item, WorkItem)]
    [card] = work.approvals
    return card.data.outcome, card.data.decider


def _ended(outcome: ApprovalOutcome, decider: ApprovalDecider | None = None) -> ApprovalDecided:
    return ApprovalDecided(
        id="approval:ap1:decided", approval_id="ap1", outcome=outcome, decider=decider
    )


@pytest.mark.parametrize(
    ("ending", "label"),
    [
        (_ended(ApprovalOutcome.APPROVED, ApprovalDecider.USER), ("approved", "user")),
        (_ended(ApprovalOutcome.APPROVED, ApprovalDecider.AUTO), ("approved", "auto")),
        (_ended(ApprovalOutcome.DENIED, ApprovalDecider.USER), ("denied", "user")),
        (_ended(ApprovalOutcome.EXPIRED), ("expired", None)),
        (_ended(ApprovalOutcome.CANCELLED), ("cancelled", None)),
        (_ended(ApprovalOutcome.WITHDRAWN), ("withdrawn", None)),
        (finished("work:t1:finished", "t1", WorkOutcome.CANCELLED), ("cancelled", None)),
    ],
)
async def test_an_approval_cards_outcome_follows_the_log(
    mongo_log: MongoConversationLog, ending: Entry, label: tuple[str, str | None]
) -> None:
    user_id = str(ObjectId())
    work: list[Entry] = [started("work:t1", "t1", 1), asked("approval:ap1", "t1", "ap1")]
    turn = _turn("send the mail")
    conversation_id = await _chat(user_id, [turn[0], *work, *turn[1:]])

    assert await _card_status(user_id, conversation_id) == (None, None)
    await mongo_log.append(conversation_id, user_id, ending)
    assert await _card_status(user_id, conversation_id) == label
