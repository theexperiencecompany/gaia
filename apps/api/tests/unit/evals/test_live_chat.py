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
from app.models.conversation_frame_models import (
    EntryFrame,
    EntryUpdatedFrame,
    OutputFrame,
    RetractFrame,
    ToolDataEvent,
    WorkDeltaFrame,
)
from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    Entry,
    Reaction,
    Reply,
    ReplySettled,
    UserMessage,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.models.conversation_send_models import ConversationEvent
from shared.py.approvals import ApprovalDecider, ApprovalOutcome
from shared.py.conversation_wire import (
    BubbleTextDelta,
    FailureReason,
    ReplyDeltaFrame,
    ReplyOutcome,
    ToolDataEntry,
)

pytestmark = pytest.mark.unit

MESSAGE = "m1"
TASK = "task-1"
API = "http://api.test"
CONVERSATION = "c1"
NOW = datetime(2026, 11, 13, tzinfo=UTC)


def entry(seq: int, item: Entry) -> EntryFrame:
    return EntryFrame(seq=seq, at=NOW, entry=item)


def user(seq: int = 1) -> EntryFrame:
    return entry(seq, UserMessage(id=MESSAGE, text="hi", surface=ConversationSource.WEB))


def reply(
    seq: int, reply_id: str, text: str, attempt: str = "a1", follow_up: tuple[str, ...] = ()
) -> EntryFrame:
    return entry(
        seq,
        Reply(
            id=f"{reply_id}:r",
            reply_id=reply_id,
            attempt_id=attempt,
            text=text,
            follow_up_actions=follow_up,
        ),
    )


def settled(
    seq: int,
    reply_id: str,
    answers: Sequence[str] = (MESSAGE,),
    outcome: ReplyOutcome = ReplyOutcome.ANSWERED,
    failure: FailureReason | None = None,
) -> EntryFrame:
    return entry(
        seq,
        ReplySettled(
            id=f"{reply_id}:s",
            reply_id=reply_id,
            outcome=outcome,
            answers=tuple(answers),
            through=1,
            quote_target=None,
            failure=failure,
        ),
    )


def work_started(seq: int, answers: Sequence[str] = (MESSAGE,)) -> EntryFrame:
    return entry(
        seq, WorkStarted(id=f"work:{TASK}", task_id=TASK, cause_through=1, answers=tuple(answers))
    )


def work_finished(seq: int, cards: Sequence[ToolDataEntry] = ()) -> EntryFrame:
    return entry(
        seq,
        WorkFinished(
            id="wf", task_id=TASK, outcome=WorkOutcome.DONE, report="done", tool_data=tuple(cards)
        ),
    )


def card(tool_name: str, data: object) -> ToolDataEntry:
    return {"tool_name": tool_name, "data": data}


def read(*frames: OutputFrame) -> TurnReader:
    reader = TurnReader("hi", MESSAGE, collect_frame_kinds=True)
    for frame in frames:
        reader.feed(frame)
    return reader


class TestReply:
    def test_the_settled_reply_that_answers_the_message_is_the_reply(self) -> None:
        reader = read(user(), reply(2, "r1", "hello there"), settled(3, "r1"))

        turn = reader.turn()
        assert reader.answered and reader.settled
        assert turn.reply == "hello there"
        assert turn.outcome is ReplyOutcome.ANSWERED
        assert turn.last_seq == 3

    def test_a_reply_to_another_message_does_not_answer_this_one(self) -> None:
        reader = read(user(), reply(2, "r0", "older"), settled(3, "r0", answers=("m0",)))

        assert not reader.answered
        assert reader.turn().reply == NO_TEXT_REPLY

    def test_streamed_text_stands_in_until_the_entry_is_filled(self) -> None:
        delta = ReplyDeltaFrame(
            attempt_id="a1",
            reply_id=None,
            index=0,
            payload=BubbleTextDelta(bubble=0, text="typed so far"),
        )
        reader = read(user(), delta, reply(2, "r1", ""), settled(3, "r1"))

        assert reader.turn().reply == "typed so far"

    def test_a_retracted_attempt_leaves_no_text(self) -> None:
        delta = ReplyDeltaFrame(
            attempt_id="a1",
            reply_id=None,
            index=0,
            payload=BubbleTextDelta(bubble=0, text="let me look"),
        )
        reader = read(
            user(),
            delta,
            RetractFrame(attempt_id="a1"),
            reply(2, "r1", "", attempt="a1"),
            settled(3, "r1"),
        )

        assert reader.turn().reply == NO_TEXT_REPLY

    def test_a_failed_reply_is_an_error(self) -> None:
        reader = read(
            user(),
            settled(
                2, "r1", answers=(), outcome=ReplyOutcome.FAILED, failure=FailureReason.MODEL_ERROR
            ),
        )
        assert not reader.answered

        reader = read(
            user(), settled(2, "r1", outcome=ReplyOutcome.FAILED, failure=FailureReason.MODEL_ERROR)
        )
        assert reader.turn().error == "reply failed: model_error"

    def test_a_reaction_on_the_message_is_kept(self) -> None:
        reacted = UserMessage(
            id=MESSAGE,
            text="hi",
            surface=ConversationSource.WEB,
            reaction=Reaction(emoji="\U0001f6d2", by=ReactionBy.CHAT_MODEL),
        )
        reader = read(user(), EntryUpdatedFrame(seq=1, entry=reacted))

        assert reader.turn().reaction == "\U0001f6d2"

    def test_follow_up_actions_come_from_the_reply(self) -> None:
        reader = read(user(), reply(2, "r1", "ok", follow_up=("a", "b", "c")), settled(3, "r1"))

        assert reader.turn().follow_up_actions == ["a", "b", "c"]


class TestDelegation:
    def test_work_the_message_started_holds_the_turn_until_its_write_up_settles(self) -> None:
        reader = read(user(), work_started(2), reply(3, "r1", "on it"), settled(4, "r1"))
        assert reader.answered and not reader.settled

        reader.feed(work_finished(5))
        assert not reader.settled

        reader.feed(reply(6, TASK, "here are your dashboards", attempt="a2"))
        reader.feed(settled(7, TASK, answers=("wf", MESSAGE)))
        turn = reader.turn()
        assert reader.settled
        assert turn.delegated
        assert turn.reply == "on it"
        assert turn.delivered == ["here are your dashboards"]

    def test_work_started_for_another_message_is_not_this_turns(self) -> None:
        reader = read(
            user(), work_started(2, answers=("m0",)), reply(3, "r1", "hi"), settled(4, "r1")
        )

        assert reader.settled
        assert not reader.turn().delegated

    def test_cards_of_the_finished_work_count_as_the_turns_tools(self) -> None:
        call = card(
            "tool_calls_data",
            {"tool_name": "create_todo", "tool_call_id": "t1", "inputs": {"title": "milk"}},
        )
        reader = read(user(), work_started(2), work_finished(3, [call, call]))

        turn = reader.turn()
        assert turn.tools == ["tool_calls_data", "create_todo"]
        assert reader.turn(include_nested_tool_names=False).tools == ["tool_calls_data"]
        assert called_tools(turn.tool_data) == [{"name": "create_todo", "args": {"title": "milk"}}]

    def test_live_work_cards_only_count_for_this_turns_tasks(self) -> None:
        delta = WorkDeltaFrame(
            task_id=TASK, index=0, payload=ToolDataEvent(tool_data=card("search", {}))
        )
        other = WorkDeltaFrame(
            task_id="other", index=0, payload=ToolDataEvent(tool_data=card("weather", {}))
        )
        reader = read(user(), work_started(2), delta, other)

        assert reader.turn().tools == ["search"]


class TestApprovals:
    def test_an_approval_requested_by_the_turns_work_is_pending_until_decided(self) -> None:
        requested = ApprovalRequested(id="ar", task_id=TASK, approval_id="ap1")
        reader = read(user(), work_started(2), entry(3, requested))
        assert reader.awaiting_approval

        reader.feed(
            entry(
                4,
                ApprovalDecided(
                    id="ad",
                    approval_id="ap1",
                    outcome=ApprovalOutcome.APPROVED,
                    decider=ApprovalDecider.USER,
                ),
            )
        )
        assert not reader.awaiting_approval
        assert reader.turn().approvals == [
            ApprovalSeen(approval_id="ap1", outcome="pending"),
            ApprovalSeen(approval_id="ap1", outcome="approved", decider="user"),
        ]

    def test_an_auto_approved_card_is_seen_without_a_request(self) -> None:
        auto = card(
            "approval_request", {"approval_id": "ap2", "outcome": "approved", "decider": "auto"}
        )
        reader = read(
            user(),
            work_started(2),
            WorkDeltaFrame(task_id=TASK, index=0, payload=ToolDataEvent(tool_data=auto)),
        )

        assert reader.turn().approvals == [
            ApprovalSeen(approval_id="ap2", outcome="approved", decider="auto")
        ]
        assert not reader.awaiting_approval


def _sse(frames: Sequence[OutputFrame]) -> bytes:
    events = [ConversationEvent(stream_id=None, frame=frame).model_dump_json() for frame in frames]
    return "".join(f": keepalive\n\ndata: {event}\n\n" for event in events).encode()


class TestSendTurn:
    async def test_sends_a_minted_id_and_follows_after_the_accepted_seq(self) -> None:
        seen: list[httpx.Request] = []
        frames: list[OutputFrame] = []

        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.method == "POST":
                body = json.loads(request.content)
                frames.extend(
                    [
                        entry(
                            5,
                            UserMessage(
                                id=body["message_id"], text="hi", surface=ConversationSource.WEB
                            ),
                        ),
                        reply(6, "r1", "hello"),
                        entry(
                            7,
                            ReplySettled(
                                id="s",
                                reply_id="r1",
                                outcome=ReplyOutcome.ANSWERED,
                                answers=(body["message_id"],),
                                through=5,
                                quote_target=None,
                            ),
                        ),
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
        reader_frames = _delegated_frames(ack="on it")
        options = dataclasses.replace(TurnOptions(), delivered_prefix=" | ")
        async with scripted_api(reader_frames) as client:
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
            [*frames, reply(9, "x", "unrelated"), reply(10, "y", "unrelated")]
        ) as client:
            turn = await send_turn(client, API, "hi", CONVERSATION, options)

        assert turn.reply == "on it" + NOTHING_DELIVERED


def _delegated_frames(ack: str) -> list[OutputFrame]:
    return [
        work_started(6),
        reply(7, "r1", ack),
        settled(8, "r1"),
        work_finished(9),
        reply(10, TASK, "the answer", attempt="a2"),
        settled(11, TASK, answers=("wf", MESSAGE)),
    ]


def scripted_api(frames: list[OutputFrame]) -> httpx.AsyncClient:
    """Script an API that accepts the message as MESSAGE, so the scripted frames answer it."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202, json={"conversation_id": CONVERSATION, "message_id": MESSAGE, "seq": 5}
            )
        return httpx.Response(200, content=_sse(frames))

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))
