"""A send entering the step: the logged message, the open-on-first-send retry, the title, the count, the bot and barge-in sends."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.constants.chat import ConversationSource
from app.models.bot_models import BotChatRequest
from app.models.calendar_models import GoogleCalendarEventDateTime
from app.models.chat_models import ConversationModel
from app.models.conversation_log_models import BargeIn, Entry, UserMessage
from app.models.conversation_send_models import (
    BargeInAccepted,
    BargeInRequest,
    BotMessageAccepted,
    MessageAccepted,
    SendMessageRequest,
)
from app.models.message_models import FileData, SelectedCalendarEventData
from app.models.user_models import AuthenticatedUser
from app.services.conversation.ports import Appended
from app.services.conversation.send import (
    submit_barge_in,
    submit_bot_message,
    submit_message,
)
from app.utils.errors import ConversationAlreadyExistsError, ConversationNotFoundError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.chat import ChatMessageSubmitted
from shared.py.analytics.context import AnalyticsContext, analytics_context
from shared.py.conversation_wire import ReplyToMessageData
from tests.factories import make_authenticated_user
from tests.unit.services.conversation.log_helpers import workflow_run
from tests.unit.services.conversation.runtime_doubles import (
    USER,
    EffectCall,
    FakeClock,
    InMemoryConversationLog,
    LogUnderTest,
    RecordingEffects,
    Runtime,
)

SEND = "app.services.conversation.send"
CONVERSATION = "conv-send"
UPLOAD = FileData(fileId="f1", url="https://files/f1", filename="notes.pdf")
QUOTED = ReplyToMessageData(id="m0", content="earlier", role="assistant")
CALENDAR_EVENT = SelectedCalendarEventData(
    id="ev1",
    summary="Standup",
    description="daily",
    start=GoogleCalendarEventDateTime(dateTime="2026-11-14T09:00:00Z"),
    end=GoogleCalendarEventDateTime(dateTime="2026-11-14T09:15:00Z"),
)


class OpenedOnlyLog(InMemoryConversationLog):
    """The in-memory log that, like Mongo's, refuses an append to a conversation nobody created."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        super().__init__(clock)
        self.opened: set[str] = set()
        # Whose name each accepted append was written under; Mongo scopes every write by it.
        self.writers: list[str] = []

    async def append(self, conversation_id: str, user_id: str, entry: Entry) -> Appended:
        if conversation_id not in self.opened:
            raise ConversationNotFoundError(message=f"conversation {conversation_id} is missing")
        self.writers.append(user_id)
        return await super().append(conversation_id, user_id, entry)


async def _no_lapse() -> None:
    return None


@dataclass
class World:
    """The send's collaborators: the step's ports over an in-memory log, and the edges it calls out to."""

    runtime: Runtime
    log: OpenedOnlyLog
    user: AuthenticatedUser
    create: AsyncMock
    budget: AsyncMock
    files: MagicMock
    capture: MagicMock
    title: MagicMock
    spawn: MagicMock
    wide: MagicMock
    bots: MagicMock
    charge: AsyncMock
    token: MagicMock

    async def entries(self) -> list[Entry]:
        return [logged.entry for logged in await self.log.read_after(CONVERSATION, USER, 0)]


def _world(effects: RecordingEffects) -> Iterator[World]:
    holder: list[OpenedOnlyLog] = []

    def make_log(clock: FakeClock) -> LogUnderTest:
        holder.append(OpenedOnlyLog(clock))
        return LogUnderTest(log=holder[0], lapse=_no_lapse)

    runtime = Runtime(effects=effects, make_log=make_log)
    log = holder[0]

    async def create(model: ConversationModel, _user: AuthenticatedUser) -> None:
        log.opened.add(model.conversation_id)

    files = MagicMock()
    files.attach_uploads = AsyncMock()
    files.get_uploads = AsyncMock(return_value=[UPLOAD])
    bots = MagicMock()
    bots.get_or_create_session = AsyncMock(return_value=CONVERSATION)
    world = World(
        runtime=runtime,
        log=log,
        user=make_authenticated_user(user_id=USER),
        create=AsyncMock(side_effect=create),
        budget=AsyncMock(),
        files=files,
        capture=MagicMock(),
        title=MagicMock(return_value="title-coroutine"),
        spawn=MagicMock(),
        wide=MagicMock(),
        bots=bots,
        charge=AsyncMock(),
        token=MagicMock(return_value="session-token"),
    )
    with (
        patch(f"{SEND}.runtime_ports", return_value=runtime.ports),
        patch(f"{SEND}.create_conversation_service", world.create),
        patch(f"{SEND}.enforce_cost_budget", world.budget),
        patch(f"{SEND}.FileService", files),
        patch(f"{SEND}.capture", world.capture),
        patch(f"{SEND}.title_conversation", world.title),
        patch(f"{SEND}.spawn_background_task", world.spawn),
        patch(f"{SEND}.log", world.wide),
        patch(f"{SEND}.BotService", bots),
        patch(f"{SEND}.charge_bot_turn", world.charge),
        patch(f"{SEND}.create_bot_session_token", world.token),
    ):
        yield world


@pytest.fixture
def world() -> Iterator[World]:
    yield from _world(RecordingEffects())


@pytest.fixture
def kick_failing() -> Iterator[World]:
    yield from _world(RecordingEffects(failing=frozenset({"kick"})))


def _submitted(**overrides: object) -> ChatMessageSubmitted:
    fields: dict[str, object] = {
        "source": "web",
        "has_files": False,
        "stream_id": "m1",
        "is_retry": False,
        "is_new_conversation": False,
        "file_count": 0,
        "is_reply": False,
    }
    return ChatMessageSubmitted.model_validate({**fields, **overrides})


async def test_a_first_send_opens_the_conversation_logs_the_message_titles_and_counts_it(
    world: World,
) -> None:
    body = SendMessageRequest(
        message_id="m1",
        text="summarise these",
        file_ids=["f1"],
        selected_tool="gmail_send",
        tool_category="gmail",
        reply_to_message=QUOTED,
    )
    session = AnalyticsContext(
        attribution=Attribution(
            actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=EntrySurface.WEB
        ),
        posthog_session_id="ph-session",
    )
    with analytics_context(session):
        accepted = await submit_message(CONVERSATION, world.user, body, ConversationSource.WEB)

    assert accepted == MessageAccepted(conversation_id=CONVERSATION, message_id="m1", seq=1)
    message = UserMessage(
        id="m1",
        text="summarise these",
        surface=ConversationSource.WEB,
        reply_to="m0",
        file_ids=("f1",),
        files=(UPLOAD,),
        selected_tool="gmail_send",
        tool_category="gmail",
        reply_to_message=QUOTED,
        posthog_session_id="ph-session",
    )
    assert await world.entries() == [message]
    world.budget.assert_awaited_once_with(USER, feature_key="chat_messages")
    world.create.assert_awaited_once_with(
        ConversationModel(conversation_id=CONVERSATION, source=ConversationSource.WEB), world.user
    )
    # Once on the send that found no conversation, once on the retry after opening it.
    uploads = [call(["f1"], USER, CONVERSATION)] * 2
    assert world.files.attach_uploads.await_args_list == uploads
    assert world.files.get_uploads.await_args_list == uploads
    world.title.assert_called_once_with(CONVERSATION, world.user, message)
    world.spawn.assert_called_once_with("title-coroutine", name="conversation-title")
    world.capture.assert_called_once_with(
        UserId(USER),
        _submitted(has_files=True, is_new_conversation=True, file_count=1),
    )
    world.wide.set_ns.assert_called_once_with("conversation", seq=1, duplicate=False)
    world.wide.error.assert_not_called()
    assert world.runtime.effects.calls == [EffectCall("kick"), EffectCall("start_ack", "m1")]


async def test_a_send_into_an_open_conversation_is_neither_created_nor_titled(
    world: World,
) -> None:
    world.log.opened.add(CONVERSATION)
    body = SendMessageRequest(
        message_id="m1",
        text="again",
        reply_to="m0",
        retry_of="m0",
        voice=True,
        selected_workflow=workflow_run().workflow,
        selected_calendar_event=CALENDAR_EVENT,
    )
    accepted = await submit_message(CONVERSATION, world.user, body, ConversationSource.WEB)

    assert accepted == MessageAccepted(conversation_id=CONVERSATION, message_id="m1", seq=1)
    assert await world.entries() == [
        UserMessage(
            id="m1",
            text="again",
            surface=ConversationSource.WEB,
            reply_to="m0",
            retry_of="m0",
            voice=True,
            selected_workflow=workflow_run().workflow,
            selected_calendar_event=CALENDAR_EVENT,
        )
    ]
    assert world.log.writers == [USER]
    world.create.assert_not_awaited()
    world.files.attach_uploads.assert_not_awaited()
    world.files.get_uploads.assert_not_awaited()
    world.spawn.assert_not_called()
    world.capture.assert_called_once_with(UserId(USER), _submitted(is_retry=True, is_reply=True))


async def test_a_resent_message_keeps_its_first_seq_and_is_counted_once(world: World) -> None:
    body = SendMessageRequest(message_id="m1", text="hello")
    first = await submit_message(CONVERSATION, world.user, body, ConversationSource.WEB)
    again = await submit_message(CONVERSATION, world.user, body, ConversationSource.WEB)

    assert again == first == MessageAccepted(conversation_id=CONVERSATION, message_id="m1", seq=1)
    assert len(await world.entries()) == 1
    world.capture.assert_called_once()
    world.spawn.assert_called_once()
    assert world.wide.set_ns.call_args_list[-1].kwargs == {"seq": 1, "duplicate": True}


async def test_a_first_send_that_lost_the_create_race_is_not_titled_as_new(world: World) -> None:
    async def created_by_the_other_send(model: ConversationModel, _user: AuthenticatedUser) -> None:
        world.log.opened.add(model.conversation_id)
        raise ConversationAlreadyExistsError(message="created by the concurrent first send")

    world.create.side_effect = created_by_the_other_send
    body = SendMessageRequest(message_id="m1", text="hello")
    accepted = await submit_message(CONVERSATION, world.user, body, ConversationSource.WEB)

    assert accepted.seq == 1
    world.spawn.assert_not_called()
    world.capture.assert_called_once_with(UserId(USER), _submitted(is_new_conversation=False))


async def test_a_message_whose_kick_failed_is_still_accepted_for_the_sweeper(
    kick_failing: World,
) -> None:
    kick_failing.log.opened.add(CONVERSATION)
    body = SendMessageRequest(message_id="m1", text="hello")
    accepted = await submit_message(CONVERSATION, kick_failing.user, body, ConversationSource.WEB)

    assert accepted == MessageAccepted(conversation_id=CONVERSATION, message_id="m1", seq=1)
    kick_failing.wide.error.assert_called_once_with(
        "conversation step kick failed after accept; the sweeper will advance it",
        conversation_id=CONVERSATION,
        seq=1,
    )


def _bot_request(**overrides: object) -> BotChatRequest:
    fields: dict[str, object] = {
        "message": "hi from telegram",
        "platform": "telegram",
        "platform_user_id": "pu1",
        "channel_id": "ch1",
        "is_dm": False,
        "platform_message_id": "77",
    }
    return BotChatRequest.model_validate({**fields, **overrides})


async def test_a_bot_message_lands_in_its_session_under_its_platform_message_id(
    world: World,
) -> None:
    world.log.opened.add(CONVERSATION)
    accepted = await submit_bot_message(_bot_request(file_ids=["f1"]), world.user)

    assert accepted == BotMessageAccepted(
        conversation_id=CONVERSATION, message_id="telegram:77", seq=1, session_token="session-token"
    )
    assert await world.entries() == [
        UserMessage(
            id="telegram:77",
            text="hi from telegram",
            surface=ConversationSource.TELEGRAM,
            platform_message_id="77",
            file_ids=("f1",),
            files=(UPLOAD,),
        )
    ]
    world.bots.get_or_create_session.assert_awaited_once_with(
        "telegram", "pu1", "ch1", world.user, is_dm=False
    )
    world.charge.assert_awaited_once_with(USER)
    world.capture.assert_called_once_with(
        UserId(USER),
        ChatMessageSubmitted(
            source="telegram", has_files=True, stream_id="telegram:77", is_retry=False
        ),
    )
    world.token.assert_called_once_with(user_id=USER, platform="telegram", platform_user_id="pu1")


async def test_a_resent_bot_message_is_counted_once(world: World) -> None:
    world.log.opened.add(CONVERSATION)
    first = await submit_bot_message(_bot_request(), world.user)
    again = await submit_bot_message(_bot_request(), world.user)

    assert again == first
    world.capture.assert_called_once()


async def test_a_bot_message_without_a_platform_id_gets_its_own_and_counts_its_files(
    world: World,
) -> None:
    world.log.opened.add(CONVERSATION)
    accepted = await submit_bot_message(
        _bot_request(platform_message_id=None, file_data=[UPLOAD.model_dump()]), world.user
    )

    assert len(accepted.message_id) == 32
    int(accepted.message_id, 16)
    [message] = await world.entries()
    assert isinstance(message, UserMessage)
    assert (message.id, message.platform_message_id) == (accepted.message_id, None)
    world.capture.assert_called_once_with(
        UserId(USER),
        ChatMessageSubmitted(
            source="telegram", has_files=True, stream_id=accepted.message_id, is_retry=False
        ),
    )


async def test_a_barge_in_is_logged_against_its_reply_and_a_resend_keeps_its_seq(
    world: World,
) -> None:
    world.log.opened.add(CONVERSATION)
    body = BargeInRequest(reply_id="r1", heard_through=3)
    first = await submit_barge_in(CONVERSATION, world.user, body)
    again = await submit_barge_in(CONVERSATION, world.user, body)

    assert first == again == BargeInAccepted(conversation_id=CONVERSATION, seq=1)
    assert await world.entries() == [BargeIn(id="r1:barge", reply_id="r1", heard_through=3)]
    assert world.log.writers == [USER, USER]
    assert [c.kwargs for c in world.wide.set_ns.call_args_list] == [
        {"seq": 1, "duplicate": False},
        {"seq": 1, "duplicate": True},
    ]
    assert world.wide.set_ns.call_args.args == ("conversation",)
