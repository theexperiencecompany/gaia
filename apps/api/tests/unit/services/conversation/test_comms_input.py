"""What a comms attempt shows the model: stable-id messages for log entries, and the context notes."""

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from app.agents.core.interruption import INTERRUPTION_MARKER, INTERRUPTION_SOURCE
from app.constants.conversation import (
    ABSORBED_NOTE,
    BARGE_IN_NOTE,
    INTEGRATION_CONNECTED_NOTE,
    LOG_SEQ,
    NOTICE_DELIVERED_NOTE,
    REACTION_NOTE,
    SERVER_RESTART_NOTE,
    WORK_DONE_NOTE,
    WORK_UNFINISHED_NOTE,
    WORKFLOW_RUN_REQUEST,
)
from app.models.chat_models import ReactionBy
from app.models.conversation_log_models import (
    Batch,
    IntegrationConnected,
    LoggedEntry,
    Reaction,
    Reply,
    WorkFinished,
    WorkOutcome,
)
from app.services.conversation.comms_input import (
    AS_TYPED,
    absorbed_messages,
    attempt_messages,
    entry_messages,
)
from shared.py.conversation_wire import FailureReason, ReplyOutcome
from tests.unit.services.conversation.log_helpers import (
    barge,
    finished,
    fired,
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
        "[#4] text of u1",
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
    spoken_over = Reply(
        id="o", reply_id="r1", attempt_id="a1", text="Your flight leaves at 9", heard_through=11
    )
    [note] = entry_messages(logged(2, spoken_over))
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


def test_a_chat_runs_finish_its_approvals_decision_carries_on_is_not_reported_again() -> None:
    """Regression for conversation 741603c7: the decided ask reached the continuation's reply."""
    asked = finished("f1", "t1").model_copy(
        update={"continued_by_decision": True, "awaits_decision": True}
    )
    continuation = logged(5, finished("f2", "t2"))
    in_context = attempt_messages(batch(continuation), [logged(3, asked)], [], AS_TYPED)
    assert ids(in_context) == ["log:f2"]
    in_batch = attempt_messages(batch(logged(3, asked)), [], [], AS_TYPED)
    assert ids(in_batch) == ["log:f1"]


def test_messages_handed_to_a_working_run_say_the_earlier_request_is_still_owed() -> None:
    """Regression for conversation ac1f090c: a side question mid-research got "36" and no research."""
    u2, u3 = logged(2, user("u2")), logged(3, user("u3"))
    messages, _ = absorbed_messages([u2, u3], AS_TYPED)
    assert ids(messages) == ["log:u2", "log:u3", "log:u3:absorbed"]
    assert messages[-1].content == ABSORBED_NOTE
    assert messages[-1].additional_kwargs == {LOG_SEQ: 3}
    work, _ = absorbed_messages([logged(4, finished("f", "t1"))], AS_TYPED)
    assert ids(work) == ["log:f"]


def test_absorbing_stops_at_the_first_stop() -> None:
    u2, u5 = logged(2, user("u2")), logged(5, user("u5"))
    messages, joined = absorbed_messages(
        [u2, logged(3, stop("s3", 2)), logged(4, user("u4"))], AS_TYPED
    )
    assert (ids(messages), joined) == (["log:u2", "log:u2:absorbed"], (u2,))
    assert absorbed_messages([u5], AS_TYPED)[1] == (u5,)


def test_a_user_message_reads_as_its_reframed_content_when_it_has_one() -> None:
    [message] = entry_messages(logged(4, user("u1")), {"u1": "text of u1\n\nFiles: invoice.pdf"})
    [plain] = entry_messages(logged(5, user("u2")), {"u1": "other"})
    assert message.content == "[#4] text of u1\n\nFiles: invoice.pdf"
    assert plain.content == "[#5] text of u2"


def test_a_workflow_fire_reads_as_its_run_request_or_what_was_said_for_it() -> None:
    [request] = entry_messages(logged(3, fired("wf")))
    [said] = entry_messages(logged(3, fired("wf")), {"wf": "Run the brief, with files"})
    assert (request.id, request.content, request.additional_kwargs) == (
        "log:wf",
        WORKFLOW_RUN_REQUEST.format(title="Morning brief"),
        {LOG_SEQ: 3},
    )
    assert said.content == "Run the brief, with files"


def test_what_was_said_for_a_message_reaches_both_the_attempt_and_an_absorbed_input() -> None:
    reframed = {"u1": "text of u1\n\nFiles: a.pdf"}
    [attempt] = attempt_messages(batch(logged(1, user("u1"))), [], [], reframed)
    absorbed, _ = absorbed_messages([logged(1, user("u1"))], reframed)
    assert [attempt.content, absorbed[0].content] == [f"[#1] {reframed['u1']}"] * 2


def test_detached_work_that_delivered_its_own_result_says_nothing_and_any_other_work_reports() -> (
    None
):
    def done(**fields: object) -> WorkFinished:
        return WorkFinished.model_validate(
            {"id": "f1", "task_id": "t1", "outcome": WorkOutcome.DONE, "report": "", **fields}
        )

    assert entry_messages(logged(2, done(nothing_for_user=True))) == []
    [unflagged] = entry_messages(logged(2, done()))
    [reported] = entry_messages(logged(2, done(report="sent", nothing_for_user=True)))
    [noted] = entry_messages(logged(2, done(note="checked", nothing_for_user=True)))
    assert [unflagged.content, reported.content, noted.content] == [
        WORK_DONE_NOTE.format(report=""),
        WORK_DONE_NOTE.format(report="sent"),
        WORK_DONE_NOTE.format(report="checked"),
    ]


def test_a_works_report_and_its_reviews_note_read_as_two_paragraphs() -> None:
    work = finished("f1", "t1").model_copy(update={"note": "the review adds this"})
    [message] = entry_messages(logged(2, work))
    assert message.content == WORK_DONE_NOTE.format(report="report\n\nthe review adds this")


def test_a_connected_integration_tells_the_model_to_carry_on() -> None:
    connected = IntegrationConnected(
        id="ic1", integration_id="gmail", integration_name="Gmail", needed_id="in1"
    )
    [note] = entry_messages(logged(4, connected))
    assert note.content == INTEGRATION_CONNECTED_NOTE.format(integration="Gmail")


def test_a_thread_holding_the_stops_own_marker_does_not_say_it_again() -> None:
    [marker] = entry_messages(logged(2, stop("s2", 1)))
    thread: list[AnyMessage] = [
        HumanMessage(content="text of u1", id="log:u1", additional_kwargs={LOG_SEQ: 1}),
        marker,
    ]
    context = [logged(1, user("u1")), logged(2, stop("s2", 1))]
    assert ids(attempt_messages(batch(logged(3, user("u3"))), context, thread, AS_TYPED)) == [
        "log:u1",
        "log:u3",
    ]


def test_an_interruption_before_the_stops_inputs_does_not_record_the_stop() -> None:
    thread: list[AnyMessage] = [
        HumanMessage(
            content=INTERRUPTION_MARKER, additional_kwargs={"lc_source": INTERRUPTION_SOURCE}
        ),
        HumanMessage(content="text of u1", id="log:u1", additional_kwargs={LOG_SEQ: 1}),
    ]
    context = [logged(1, user("u1")), logged(2, stop("s2", 1))]
    assert ids(attempt_messages(batch(logged(3, user("u3"))), context, thread, AS_TYPED)) == [
        "log:u1",
        "log:s2",
        "log:u3",
    ]


def test_only_a_settle_failed_by_a_restart_tells_the_model_it_was_cut_off() -> None:
    recovered = settled("r1:recovered:2", ("u1",), 1, outcome=ReplyOutcome.FAILED)
    model_error = settled("r2:settled", (), 1, outcome=ReplyOutcome.FAILED).model_copy(
        update={"failure": FailureReason.MODEL_ERROR}
    )
    assert [m.content for m in entry_messages(logged(4, recovered))] == [SERVER_RESTART_NOTE]
    assert entry_messages(logged(5, model_error)) == []
