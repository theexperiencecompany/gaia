"""What a comms attempt shows the model: stable-id messages for log entries, and the context notes."""

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from app.agents.core.interruption import INTERRUPTION_MARKER, INTERRUPTION_SOURCE
from app.constants.conversation import (
    BARGE_IN_NOTE,
    LOG_SEQ,
    NOTICE_DELIVERED_NOTE,
    REACTION_NOTE,
    SERVER_RESTART_NOTE,
    WORK_DONE_NOTE,
    WORK_UNFINISHED_NOTE,
)
from app.models.chat_models import ReactionBy
from app.models.conversation_log_models import (
    Batch,
    LoggedEntry,
    Reaction,
    Reply,
    ReplyOutcome,
    WorkOutcome,
)
from app.services.conversation.comms_input import (
    AS_TYPED,
    absorbed_messages,
    attempt_messages,
    entry_messages,
)
from tests.unit.services.conversation.log_helpers import (
    barge,
    finished,
    logged,
    notice,
    replied,
    settled,
    stop,
    user,
)


def batch(*entries: LoggedEntry) -> Batch:
    return Batch(start=entries[0].seq, end=entries[-1].seq, waking=entries, first_at=entries[0].at)


def ids(messages: list[AnyMessage]) -> list[str | None]:
    return [message.id for message in messages]


def test_a_user_message_is_one_human_message_keyed_on_its_entry_and_seq() -> None:
    [message] = entry_messages(logged(4, user("u1")))
    assert isinstance(message, HumanMessage)
    assert (message.id, message.content, message.additional_kwargs) == (
        "log:u1",
        "text of u1",
        {LOG_SEQ: 4},
    )


def test_a_reaction_jev_already_gave_is_noted_after_the_message() -> None:
    reacted = user("u1").model_copy(update={"reaction": Reaction(emoji="👍", by=ReactionBy.JEV)})
    messages = entry_messages(logged(1, reacted))
    assert ids(messages) == ["log:u1", "log:u1:reaction"]
    assert messages[1].content == REACTION_NOTE.format(emoji="👍")


def test_a_reaction_the_chat_model_gave_needs_no_note() -> None:
    reacted = user("u1").model_copy(
        update={"reaction": Reaction(emoji="👍", by=ReactionBy.CHAT_MODEL)}
    )
    assert ids(entry_messages(logged(1, reacted))) == ["log:u1"]


def test_finished_work_asks_for_the_result_in_the_reply_and_cancelled_work_is_silent() -> None:
    [done] = entry_messages(logged(2, finished("f1", "t1")))
    [failed] = entry_messages(logged(3, finished("f2", "t2", WorkOutcome.FAILED)))
    assert done.content == WORK_DONE_NOTE.format(report="report")
    assert failed.content == WORK_UNFINISHED_NOTE.format(outcome="failed", report="report")
    assert entry_messages(logged(4, finished("f3", "t3", WorkOutcome.CANCELLED))) == []


def test_context_notes_for_a_stop_a_notice_and_a_recovered_reply() -> None:
    [marker] = entry_messages(logged(2, stop("s1", 1)))
    [note] = entry_messages(logged(3, notice("n1")))
    recovered = settled("r1:recovered:2", (), 0, outcome=ReplyOutcome.FAILED)
    [restart] = entry_messages(logged(4, recovered))
    assert (marker.content, marker.additional_kwargs["lc_source"]) == (
        INTERRUPTION_MARKER,
        INTERRUPTION_SOURCE,
    )
    assert note.content == NOTICE_DELIVERED_NOTE.format(text="delivered")
    assert restart.content == SERVER_RESTART_NOTE


def test_a_settled_answer_and_an_open_reply_show_the_model_nothing() -> None:
    opened, answered = replied("r1", ("u1",), 1)
    assert entry_messages(logged(2, opened)) == []
    assert entry_messages(logged(3, answered)) == []


def test_a_reply_the_user_spoke_over_tells_the_model_only_its_heard_part_was_heard() -> None:
    cut = Reply(id="o", reply_id="r1", attempt_id="a1", text="Your flight", heard_through=11)
    [note] = entry_messages(logged(2, cut))
    assert (note.id, note.content) == ("log:o", BARGE_IN_NOTE.format(heard="Your flight"))
    assert entry_messages(logged(3, barge("b", "r1", 11))) == []


def test_context_and_batch_render_in_seq_order() -> None:
    messages = attempt_messages(
        batch(logged(3, user("u3"))),
        [logged(1, user("u1")), logged(2, stop("s2", 1))],
        [],
        AS_TYPED,
    )
    assert ids(messages) == ["log:u1", "log:s2", "log:u3"]


def test_a_stop_the_thread_already_records_after_its_inputs_is_not_said_again() -> None:
    thread: list[AnyMessage] = [
        HumanMessage(content="text of u1", id="log:u1", additional_kwargs={LOG_SEQ: 1}),
        HumanMessage(
            content=INTERRUPTION_MARKER, additional_kwargs={"lc_source": INTERRUPTION_SOURCE}
        ),
    ]
    context = [logged(1, user("u1")), logged(2, stop("s2", 1))]
    assert ids(attempt_messages(batch(logged(3, user("u3"))), context, thread, AS_TYPED)) == [
        "log:u1",
        "log:u3",
    ]


def test_a_stop_whose_inputs_never_reached_the_thread_is_said() -> None:
    thread: list[AnyMessage] = [
        AIMessage(content="an older answer"),
        HumanMessage(
            content=INTERRUPTION_MARKER, additional_kwargs={"lc_source": INTERRUPTION_SOURCE}
        ),
    ]
    context = [logged(1, user("u1")), logged(2, stop("s2", 1))]
    assert "log:s2" in ids(
        attempt_messages(batch(logged(3, user("u3"))), context, thread, AS_TYPED)
    )


def test_absorbing_stops_at_the_first_stop() -> None:
    messages, stopped = absorbed_messages(
        [logged(2, user("u2")), logged(3, stop("s3", 2)), logged(4, user("u4"))], AS_TYPED
    )
    assert (ids(messages), stopped) == (["log:u2"], True)
    assert absorbed_messages([logged(5, user("u5"))], AS_TYPED)[1] is False


def test_a_user_message_reads_as_its_reframed_content_when_it_has_one() -> None:
    [message] = entry_messages(logged(4, user("u1")), {"u1": "text of u1\n\nFiles: invoice.pdf"})
    [plain] = entry_messages(logged(5, user("u2")), {"u1": "other"})
    assert message.content == "text of u1\n\nFiles: invoice.pdf"
    assert plain.content == "text of u2"
