"""The attempt's reply shaping: what a run's stream folds into, what clients are sent, and what is saved."""

import pytest

from app.models.conversation_frame_models import (
    FollowUpActionsEvent,
    ReasoningEvent,
    ResponseEvent,
    StreamPayload,
    ToolDataEvent,
)
from app.models.conversation_log_models import Batch, Entry, Reply, StepClaim
from app.models.stream_events import ReasoningPayload
from app.services.conversation.ports import Replied
from app.services.conversation.reply_text import ReplyText
from app.services.conversation.step_attempt import (
    Attempt,
    Showing,
    final_reply,
    folded_reply,
    is_visible,
    quote_in,
    reply_bubbles,
    reply_deltas,
    settled_entry,
    waking_entry,
)
from app.services.conversation.step_view import StepView
from app.services.conversation.tool_timeline import tool_timeline
from shared.py.conversation_wire import (
    BubbleTextDelta,
    CardsDelta,
    FollowUpsDelta,
    ReplyOutcome,
    ToolDataEntry,
)
from tests.unit.services.conversation.log_helpers import EMPTY, at, finished, logged, user

CARD: ToolDataEntry = {"tool_name": "search", "data": {"q": "x"}}


def _reply(reply_id: str, text: str = "", tool_data: tuple[ToolDataEntry, ...] = ()) -> Reply:
    return Reply(
        id=f"{reply_id}:reply", reply_id=reply_id, attempt_id="1", text=text, tool_data=tool_data
    )


def _attempt(progress: Showing | None, woken_by: Entry | None = None) -> Attempt:
    waking = logged(1, woken_by or user("u1"))
    return Attempt(
        claim=StepClaim(conversation_id="c1", user_id="u1", epoch=1),
        run_id="run",
        reply_id="r1",
        batch=Batch(start=1, end=1, waking=(waking,), first_at=at(1)),
        handed=(waking,),
        ledger="c1:run",
        seen=1,
        view=StepView(state=EMPTY, after=0, entries=[]),
        hint_head=EMPTY.head,
        progress=progress,
    )


def _showing(reply: Reply) -> Attempt:
    return _attempt(Showing(reply=reply))


def test_an_entry_that_wakes_nothing_is_refused_naming_its_seq_and_kind() -> None:
    reply = _reply("r1", "hi")
    with pytest.raises(TypeError) as refused:
        waking_entry(logged(2, reply))
    assert str(refused.value) == f"seq 2 is a {reply.kind}, not a waking entry"


def test_streamed_follow_ups_fold_into_the_reply_and_are_sent_as_they_stand() -> None:
    before = _reply("r1", "hi")
    payload = FollowUpActionsEvent(follow_up_actions=["Plan my week", "Draft it"])

    folded = folded_reply(before, payload, ReplyText())

    assert folded.follow_up_actions == ("Plan my week", "Draft it")
    assert reply_deltas(before, folded, payload, (), ()) == [
        FollowUpsDelta(follow_up_actions=("Plan my week", "Draft it"))
    ]


def test_a_shown_slot_that_kept_nothing_saves_the_runs_replied_content() -> None:
    attempt = _showing(_reply("r1"))
    outcome = Replied("the answer", tool_data=(CARD,), follow_up_actions=("And next?",))

    reply, worded = final_reply(attempt, outcome)

    assert (reply.text, reply.tool_data, reply.follow_up_actions) == (
        "the answer",
        (CARD,),
        ("And next?",),
    )
    assert worded


def test_a_shown_reply_keeps_what_it_streamed_over_the_runs_replied_content() -> None:
    attempt = _showing(_reply("r1", "streamed"))

    reply, worded = final_reply(attempt, Replied("never shown"))

    assert (reply.text, worded) == ("streamed", True)


@pytest.mark.parametrize(
    ("between", "quoted"),
    [
        (_reply("r0", "an earlier answer"), "u1"),
        (_reply("r0", tool_data=(CARD,)), "u1"),
        (_reply("r0"), None),
    ],
)
def test_a_reply_showing_text_or_its_own_cards_interrupts_the_answered_message(
    between: Reply, quoted: str | None
) -> None:
    entries = [logged(1, user("u1")), logged(2, between)]
    assert quote_in(("u1",), 3, entries) == quoted


def test_a_reply_is_never_the_message_a_reply_quotes() -> None:
    entries = [logged(1, _reply("r0", "an earlier answer")), logged(2, user("u5"))]
    assert quote_in(("r0",), 3, entries) is None


def test_a_settle_keeps_the_quote_and_names_the_work_its_reply_narrates() -> None:
    settle = settled_entry(
        _attempt(None, finished("f1", "t1")), ReplyOutcome.ANSWERED, ("u1",), 1, "u1"
    )
    assert (settle.quote_target, settle.narrates) == ("u1", ("t1",))


def test_reply_text_splits_into_its_bubbles() -> None:
    assert reply_bubbles("first<NEW_MESSAGE_BREAK>second") == ("first", "second")


def test_only_text_and_cards_other_than_a_hand_over_show_a_reply() -> None:
    shown: list[StreamPayload] = [ResponseEvent(response="hi"), ToolDataEvent(tool_data=CARD)]
    assert [is_visible(payload) for payload in shown] == [True, True]
    assert is_visible(ResponseEvent(response="")) is False


def test_streamed_text_folds_into_the_reply_and_sends_only_what_grew() -> None:
    payload = ResponseEvent(response="Hi there")
    folded = folded_reply(_reply("r1"), payload, ReplyText().take(payload))

    assert folded.text == "Hi there"
    assert reply_deltas(_reply("r1"), folded, payload, ("Hi",), ("Hi there",)) == [
        BubbleTextDelta(bubble=0, text=" there")
    ]


def test_a_new_card_folds_into_the_reply_and_is_sent_with_its_timeline() -> None:
    payload = ToolDataEvent(tool_data=CARD)
    before = _reply("r1", "hi")

    folded = folded_reply(before, payload, ReplyText())

    assert folded.tool_data == (CARD,)
    assert reply_deltas(before, folded, payload, (), ()) == [
        CardsDelta(tool_data=(CARD,), timeline=tool_timeline((CARD,)))
    ]


def test_a_payload_that_shows_no_card_changes_nothing_and_sends_nothing() -> None:
    payload = ReasoningEvent(reasoning=ReasoningPayload(content=""))
    shown = _reply("r1", "hi", (CARD,))

    assert folded_reply(shown, payload, ReplyText()) is shown
    assert reply_deltas(shown, shown, payload, (), ()) == []


def test_an_empty_answer_holds_no_words() -> None:
    assert final_reply(_showing(_reply("r1")), Replied("")) == (_reply("r1"), False)


def test_a_run_that_showed_nothing_saves_a_fresh_reply_narrating_the_work_it_answers() -> None:
    reply, _ = final_reply(_attempt(None, finished("f1", "t1")), Replied("t1 is done"))

    assert (reply.id, reply.reply_id, reply.attempt_id) == ("run:reply", "r1", "run")
    assert (reply.text, reply.narrates) == ("t1 is done", ("t1",))
