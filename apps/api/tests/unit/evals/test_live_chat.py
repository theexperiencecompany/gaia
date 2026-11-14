"""The live-chat client folds a conversation's events into what one message caused.

Every eval grades the reply text, tool list and approvals this fold produces, so its
rules are pinned here against scripted frames, and send_turn against a scripted API.
"""

from __future__ import annotations

from collections.abc import Sequence
import dataclasses
from datetime import UTC, datetime
import json

import httpx
import pytest
from scripts.evals.core.live_chat import (
    NO_TEXT_REPLY,
    NOTHING_DELIVERED,
    ApprovalSeen,
    TurnOptions,
    TurnReader,
    called_tools,
    send_turn,
)

from app.constants.chat import ConversationSource
from app.models.chat_models import ReactionBy
from app.models.conversation_frame_models import RetractFrame, StateFrame
from app.models.conversation_log_models import (
    ApprovalRequested,
    DisplayState,
    Reaction,
    UserMessage,
)
from app.models.conversation_screen_models import (
    ScreenFrame,
    ScreenInsertFrame,
    ScreenStreamFrame,
    ScreenUpdateFrame,
    UserItem,
    WorkItem,
    WorkStatus,
)
from app.models.conversation_send_models import ConversationEvent
from app.models.stream_events import ApprovalRequestEntry, ApprovalRequestEntryData
from shared.py.approvals import ApprovalDecider, ApprovalOutcome
from shared.py.conversation_wire import (
    BubbleTextDelta,
    FailureReason,
    ReplyDeltaFrame,
    ReplyItem,
    ReplyOutcome,
    ToolDataEntry,
    ToolTimeline,
)

pytestmark = pytest.mark.unit

MESSAGE = "m1"
TASK = "task-1"
API = "http://api.test"
CONVERSATION = "c1"
NOW = datetime(2026, 11, 13, tzinfo=UTC)


def user(seq: int = 1, message_id: str = MESSAGE, reaction: Reaction | None = None) -> UserItem:
    return UserItem(
        id=message_id,
        seq=seq,
        at=NOW,
        message=UserMessage(
            id=message_id, text="hi", surface=ConversationSource.WEB, reaction=reaction
        ),
    )


def reply(
    seq: int,
    reply_id: str,
    text: str,
    outcome: ReplyOutcome | None = ReplyOutcome.ANSWERED,
    **over: object,
) -> ReplyItem:
    item = ReplyItem(
        id=reply_id,
        seq=seq,
        at=NOW,
        bubbles=(text,) if text else (),
        tool_data=(),
        timeline=ToolTimeline(),
        follow_up_actions=(),
        image=None,
        pinned=False,
        quote=None,
        outcome=outcome,
        failure=None,
        narrates=(),
        retry_target=None,
        files=(),
    )
    return item.model_copy(update=over)


def work(
    seq: int, status: WorkStatus = WorkStatus.RUNNING, task_id: str = TASK, **over: object
) -> WorkItem:
    item = WorkItem(
        id=f"work:{task_id}",
        seq=seq,
        at=NOW,
        task_id=task_id,
        status=status,
        asking=(),
        asked_seq=0,
        approvals=(),
        handoff=None,
        tool_data=(),
        timeline=ToolTimeline(),
        image=None,
        retry_target=None,
    )
    return item.model_copy(update={"asked_seq": seq if over.get("asking") else 0, **over})


def approval_card(outcome: ApprovalOutcome | None) -> ApprovalRequestEntry:
    return ApprovalRequestEntry(
        tool_name="approval_request",
        tool_category="hil",
        data=ApprovalRequestEntryData(
            approval_id="ap1",
            tool_call_id="tc1",
            gated_tool_name="send_email",
            integration_name=None,
            summary="send it",
            args_preview={},
            outcome=outcome,
            decider=None if outcome is None else ApprovalDecider.USER,
            feedback=None,
            auto_reason=None,
            timeout_seconds=60,
        ),
        timestamp=NOW.isoformat(),
    )


def card(tool_name: str, data: object) -> ToolDataEntry:
    return {"tool_name": tool_name, "data": data}


def shown(*items: UserItem | ReplyItem | WorkItem) -> ScreenFrame:
    return ScreenFrame(items=items, head=max((item.seq for item in items), default=0))


def insert(item: UserItem | ReplyItem | WorkItem) -> ScreenInsertFrame:
    return ScreenInsertFrame(item=item, head=item.seq)


def update(item: UserItem | ReplyItem | WorkItem) -> ScreenUpdateFrame:
    return ScreenUpdateFrame(item=item, head=item.seq)


def state(head: int, display: DisplayState) -> StateFrame:
    return StateFrame(head=head, display=display, work=())


def read(*frames: ScreenStreamFrame) -> TurnReader:
    reader = TurnReader("hi", MESSAGE, collect_frame_kinds=True)
    for frame in frames:
        reader.feed(frame)
    return reader


class TestReply:
    def test_the_settled_reply_after_the_message_is_the_reply(self) -> None:
        reader = read(shown(user()), insert(reply(2, "r1", "hello there", None)))
        assert not reader.answered

        reader.feed(update(reply(2, "r1", "hello there")))
        turn = reader.turn()
        assert reader.answered and reader.settled
        assert turn.reply == "hello there"
        assert turn.outcome is ReplyOutcome.ANSWERED
        assert turn.last_seq == 2

    def test_a_reply_from_before_the_message_does_not_answer_it(self) -> None:
        reader = read(shown(reply(1, "r0", "older"), user(2)))

        assert not reader.answered
        assert reader.turn().reply == NO_TEXT_REPLY

    def test_streamed_text_stands_in_until_the_reply_is_filled(self) -> None:
        delta = ReplyDeltaFrame(
            attempt_id="a1",
            reply_id="r1",
            index=0,
            payload=BubbleTextDelta(bubble=0, text="typed so far"),
        )
        reader = read(shown(user()), delta, insert(reply(2, "r1", "")))

        assert reader.turn().reply == "typed so far"

    def test_a_retracted_attempt_leaves_no_text(self) -> None:
        delta = ReplyDeltaFrame(
            attempt_id="a1",
            reply_id="r1",
            index=0,
            payload=BubbleTextDelta(bubble=0, text="let me look"),
        )
        reader = read(
            shown(user()), delta, RetractFrame(attempt_id="a1"), insert(reply(2, "r1", ""))
        )

        assert reader.turn().reply == NO_TEXT_REPLY

    def test_a_failed_reply_is_an_error(self) -> None:
        failed = reply(2, "r1", "", ReplyOutcome.FAILED, failure=FailureReason.MODEL_ERROR)
        reader = read(shown(user()), insert(failed))

        assert reader.answered
        assert reader.turn().error == "reply failed: model_error"

    def test_a_reaction_alone_answers_once_the_conversation_moves_on(self) -> None:
        reacted = user(reaction=Reaction(emoji="\U0001f6d2", by=ReactionBy.CHAT_MODEL))
        reader = read(shown(user()), state(1, DisplayState.THINKING), update(reacted))
        assert not reader.answered

        reader.feed(state(2, DisplayState.IDLE))
        assert reader.answered
        assert reader.turn().reaction == "\U0001f6d2"

    def test_follow_up_actions_come_from_the_reply(self) -> None:
        reader = read(
            shown(user()), insert(reply(2, "r1", "ok", follow_up_actions=("a", "b", "c")))
        )

        assert reader.turn().follow_up_actions == ["a", "b", "c"]


class TestDelegation:
    def test_work_the_message_started_holds_the_turn_until_its_write_up_settles(self) -> None:
        reader = read(shown(user()), insert(work(2)), insert(reply(3, "r1", "on it")))
        assert reader.answered and not reader.settled

        reader.feed(update(work(2, WorkStatus.DONE)))
        assert not reader.settled

        reader.feed(insert(reply(4, "r2", "here are your dashboards", None, narrates=(TASK,))))
        assert not reader.settled
        reader.feed(update(reply(4, "r2", "here are your dashboards", narrates=(TASK,))))
        turn = reader.turn()
        assert reader.settled
        assert turn.delegated
        assert turn.reply == "on it"
        assert turn.delivered == ["here are your dashboards"]

    def test_work_from_before_the_message_is_not_this_turns(self) -> None:
        reader = read(shown(work(1, task_id="old"), user(2)), insert(reply(3, "r1", "hi")))

        assert reader.settled
        assert not reader.turn().delegated

    def test_cards_of_the_turns_work_count_as_its_tools(self) -> None:
        call = card(
            "tool_calls_data",
            {"tool_name": "create_todo", "tool_call_id": "t1", "inputs": {"title": "milk"}},
        )
        reader = read(shown(user()), insert(work(2, WorkStatus.DONE, tool_data=(call, call))))

        turn = reader.turn()
        assert turn.tools == ["tool_calls_data", "create_todo"]
        assert reader.turn(include_nested_tool_names=False).tools == ["tool_calls_data"]
        assert called_tools(turn.tool_data) == [{"name": "create_todo", "args": {"title": "milk"}}]

    def test_cards_of_work_from_before_the_message_do_not_count(self) -> None:
        reader = read(
            shown(work(1, task_id="old", tool_data=(card("weather", {}),)), user(2)),
            insert(work(3, tool_data=(card("search", {}),))),
        )

        assert reader.turn().tools == ["search"]


class TestApprovals:
    def test_an_approval_the_turns_work_asks_is_pending_until_decided(self) -> None:
        asked = ApprovalRequested(id="ar", task_id=TASK, approval_id="ap1")
        reader = read(
            shown(user()),
            insert(
                work(
                    2,
                    WorkStatus.AWAITING_APPROVAL,
                    asking=(asked,),
                    approvals=(approval_card(None),),
                )
            ),
        )
        assert reader.awaiting_approval

        reader.feed(update(work(2, approvals=(approval_card(ApprovalOutcome.APPROVED),))))
        assert not reader.awaiting_approval
        assert reader.turn().approvals == [
            ApprovalSeen(approval_id="ap1", outcome="pending"),
            ApprovalSeen(approval_id="ap1", outcome="approved", decider="user"),
        ]

    def test_an_auto_approved_card_is_seen_without_a_request(self) -> None:
        auto = card(
            "approval_request", {"approval_id": "ap2", "outcome": "approved", "decider": "auto"}
        )
        reader = read(shown(user()), insert(work(2, tool_data=(auto,))))

        assert reader.turn().approvals == [
            ApprovalSeen(approval_id="ap2", outcome="approved", decider="auto")
        ]


def _sse(frames: Sequence[ScreenStreamFrame]) -> bytes:
    events = [ConversationEvent(frame=frame).model_dump_json() for frame in frames]
    return "".join(f": keepalive\n\ndata: {event}\n\n" for event in events).encode()


class TestSendTurn:
    async def test_sends_a_minted_id_and_follows_after_the_accepted_seq(self) -> None:
        seen: list[httpx.Request] = []
        frames: list[ScreenStreamFrame] = []

        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.method == "POST":
                body = json.loads(request.content)
                frames.extend(
                    [
                        shown(user(5, message_id=body["message_id"])),
                        insert(reply(6, "r1", "hello")),
                    ]
                )
                return httpx.Response(
                    202,
                    json={
                        "conversation_id": CONVERSATION,
                        "message_id": body["message_id"],
                        "seq": 5,
                    },
                )
            return httpx.Response(200, content=_sse(frames))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            turn = await send_turn(client, API, "hi", CONVERSATION)

        post, events = seen
        assert post.url.path == f"/api/v1/conversations/{CONVERSATION}/messages"
        assert json.loads(post.content)["text"] == "hi"
        assert events.url.path == f"/api/v1/conversations/{CONVERSATION}/events"
        assert events.url.params["after"] == "4"
        assert turn.reply == "hello"

    async def test_a_refused_send_is_a_row_not_an_exception(self) -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(402, text="pay up"))
        )
        async with client:
            turn = await send_turn(client, API, "hi", CONVERSATION)

        assert turn.reply == "[HTTP 402] pay up"

    async def test_the_delivered_answer_follows_the_ack_with_the_harness_prefix(self) -> None:
        options = dataclasses.replace(TurnOptions(), delivered_prefix=" | ")
        async with scripted_api(_delegated_frames(ack="on it")) as client:
            turn = await send_turn(client, API, "hi", CONVERSATION, options)

        assert turn.reply == "on it | the answer"

    async def test_drop_sentinel_leaves_only_the_delivered_answer(self) -> None:
        options = dataclasses.replace(
            TurnOptions(), delivered_prefix="\n\n", drop_sentinel_before_delivery=True
        )
        async with scripted_api(_delegated_frames(ack="")) as client:
            turn = await send_turn(client, API, "hi", CONVERSATION, options)

        assert turn.reply == "the answer"

    async def test_without_wait_for_work_the_turn_ends_at_its_own_reply(self) -> None:
        options = dataclasses.replace(TurnOptions(), wait_for_work=False)
        async with scripted_api(_delegated_frames(ack="on it")) as client:
            turn = await send_turn(client, API, "hi", CONVERSATION, options)

        assert turn.reply == "on it"
        assert turn.delivered == []

    async def test_work_that_never_reports_is_marked_undelivered(self) -> None:
        options = dataclasses.replace(TurnOptions(), delivery_wait_seconds=0.0)
        frames = _delegated_frames(ack="on it")[:3]
        async with scripted_api(
            [*frames, insert(reply(9, "x", "unrelated")), insert(reply(10, "y", "unrelated"))]
        ) as client:
            turn = await send_turn(client, API, "hi", CONVERSATION, options)

        assert turn.reply == "on it" + NOTHING_DELIVERED


def _delegated_frames(ack: str) -> list[ScreenStreamFrame]:
    return [
        shown(user(5)),
        insert(work(6)),
        insert(reply(7, "r1", ack)),
        update(work(6, WorkStatus.DONE)),
        insert(reply(8, "r2", "the answer", narrates=(TASK,))),
    ]


def scripted_api(frames: list[ScreenStreamFrame]) -> httpx.AsyncClient:
    """Script an API that accepts the message as MESSAGE, so the scripted frames answer it."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202, json={"conversation_id": CONVERSATION, "message_id": MESSAGE, "seq": 5}
            )
        return httpx.Response(200, content=_sse(frames))

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))
