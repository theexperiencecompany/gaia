"""Compose: the contract a composed message must keep, the retry, the degraded render, and the thread write."""

from datetime import UTC, datetime
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage
import pytest

from app.agents.prompts.compose_prompts import OUTCOME_REPLY_SHAPES, SPOKEN_COMPOSE_RULES
from app.constants.agents import OutcomeState
from app.constants.chat import ConversationSource
from app.constants.outbound import OUTBOUND_TTL_SECONDS_DEFAULT, OUTBOUND_TTL_SECONDS_GREETING
from app.constants.outbox import COMPOSE_EARLIER_RUN_CHARS, COMPOSE_EARLIER_RUNS
from app.models.outbox_models import OutboxItemDocument, OutboxMessageDocument
from app.models.ownership_models import DeliveryPolicy
from app.models.task_report_models import TaskReport
from app.schemas.outbound import OutboundAttachment
from app.services.outbox import compose as compose_module
from app.services.outbox.compose import _item_view, _validate, compose, record_in_thread
from app.services.outbox.judge_models import ItemJudgement, Moment
from app.services.outbox.models import (
    ComposeMode,
    ComposeResult,
    DropReason,
    Initiative,
    ItemState,
    NoticeOutcome,
    NoticeReport,
    ProducerGuidance,
    ProducerKind,
    RunReport,
    Subject,
    SubjectKind,
    UrgencyClass,
)
from app.services.outbox.prerendered import PrerenderedKind, PrerenderedMessage, prerendered_text
from app.services.outbox.router import InApp, Route
from tests._harness.judge import verdict

MODULE = "app.services.outbox.compose"


def _item(report_id: str, urgency: UrgencyClass, initiative: Initiative) -> OutboxItemDocument:
    return OutboxItemDocument(
        user_id="u",
        report_id=report_id,
        report=NoticeReport(
            report_id=report_id,
            recipient="u",
            producer=ProducerKind.REMINDER,
            subject=Subject(kind=SubjectKind.REMINDER, id=report_id, label=f"Label {report_id}"),
            occurred_at=datetime(2026, 11, 10, tzinfo=UTC),
            initiative=initiative,
            delivery_policy=DeliveryPolicy(),
            outcome=NoticeOutcome.INFO,
            facts=[f"fact {report_id}"],
        ),
        urgency=urgency,
        mode=ComposeMode.UNSOLICITED,
        expires_at=datetime(2027, 1, 1, tzinfo=UTC),
    )


MUST = _item("must", UrgencyClass.TIMELY, Initiative.SELF_INITIATED)
OPTIONAL = _item("optional", UrgencyClass.BACKGROUND, Initiative.SELF_INITIATED)


def _result(*actions: tuple[str, str], parts: list[str]) -> ComposeResult:
    return ComposeResult.model_validate(
        {
            "dispositions": [{"item_id": i, "action": a, "reason": "r"} for i, a in actions],
            "parts": parts,
        }
    )


@pytest.mark.parametrize(
    ("result", "fragment"),
    [
        (_result(("must", "include"), parts=["x"]), "exactly once"),
        (
            _result(("must", "include"), ("must", "include"), ("optional", "skip"), parts=["x"]),
            "exactly once",
        ),
        (_result(("must", "skip"), ("optional", "skip"), parts=[]), "must be said"),
        (_result(("must", "include"), ("optional", "skip"), parts=[" "]), "no parts"),
        (_result(("must", "include"), ("optional", "include"), parts=[]), "no parts"),
    ],
)
def test_a_result_that_breaks_the_contract_is_named(result: ComposeResult, fragment: str) -> None:
    assert fragment in (_validate(result, [MUST, OPTIONAL]) or "")


def test_a_result_that_keeps_the_contract_passes() -> None:
    assert (
        _validate(
            _result(("must", "include"), ("optional", "skip"), parts=["hello"]), [MUST, OPTIONAL]
        )
        is None
    )
    assert _validate(_result(("optional", "skip"), parts=[]), [OPTIONAL]) is None


def _model(*answers: ComposeResult) -> AsyncMock:
    return AsyncMock(side_effect=list(answers))


async def _compose(
    model: AsyncMock,
    items: list[OutboxItemDocument],
    *,
    requested_unavailable: ConversationSource | None = None,
    leaks: list[list[str]] | None = None,
    target: InApp = InApp(reason="no_chat_app"),
):
    """Compose items; leaks lists what the internals guard finds in each answer's parts, in order (none by default)."""
    graph = SimpleNamespace(aget_state=AsyncMock(return_value=SimpleNamespace(values={})))
    with (
        patch(f"{MODULE}.ainvoke_structured", model),
        patch(f"{MODULE}.GraphManager.get_graph", AsyncMock(return_value=graph)),
        patch(f"{MODULE}.outbox_messages_repository.recent_sent", AsyncMock(return_value=[])),
        patch(
            f"{MODULE}.leaked_internals",
            AsyncMock(side_effect=lambda *_: leaks.pop(0) if leaks else []),
        ),
    ):
        return await compose(
            items,
            user_id="u",
            mode=ComposeMode.UNSOLICITED,
            destination=Route(
                alert_conversation_id="c",
                recorded_in=("c",),
                target=target,
                requested_unavailable=requested_unavailable,
            ),
            locale="en",
        )


async def test_a_valid_answer_is_used_as_is() -> None:
    model = _model(_result(("must", "include"), ("optional", "skip"), parts=[" Hi "]))

    composed = await _compose(model, [MUST, OPTIONAL])

    assert (composed.parts, composed.included, composed.skipped, composed.degraded) == (
        ["Hi"],
        ["must"],
        ["optional"],
        False,
    )


async def test_a_dropped_must_say_item_is_asked_again_with_the_violation_stated() -> None:
    model = _model(
        _result(("must", "skip"), parts=[]),
        _result(("must", "include"), parts=["ok"]),
    )

    composed = await _compose(model, [MUST])

    assert composed.degraded is False and composed.parts == ["ok"]
    retry_prompt = model.await_args_list[1].args[1]
    assert "must be said" in retry_prompt[-1].content


async def test_two_broken_answers_send_the_plain_render_and_count_it() -> None:
    bad = _result(("must", "skip"), parts=[])
    with patch(f"{MODULE}.OUTBOX_COMPOSE_DEGRADED") as counter:
        composed = await _compose(_model(bad, bad), [MUST, OPTIONAL])

    counter.inc.assert_called_once_with()
    assert composed.degraded is True
    assert composed.included == ["must"] and composed.skipped == ["optional"]
    assert "Label must: fact must" in composed.parts[0]
    assert "fact optional" not in composed.parts[0]


async def test_a_message_naming_internals_is_asked_again_with_what_leaked_stated() -> None:
    model = _model(
        _result(("must", "include"), parts=["the executor sent it"]),
        _result(("must", "include"), parts=["it went out"]),
    )

    composed = await _compose(model, [MUST], leaks=[[], ["executor"], []])

    assert composed.parts == ["it went out"] and composed.degraded is False
    assert "names GAIA internals (executor)" in model.await_args_list[1].args[1][-1].content


async def test_a_routine_message_that_keeps_naming_internals_is_dropped_loudly() -> None:
    leaky = _result(("optional", "include"), parts=["task_id abc"])

    composed = await _compose(
        _model(leaky, leaky), [OPTIONAL], leaks=[[], ["task_id"], ["task_id"]]
    )

    assert composed.skip_reason is DropReason.LEAK_UNRESOLVED
    assert composed.skipped == ["optional"] and composed.included == []


async def test_a_must_say_message_that_keeps_naming_internals_is_told_from_the_facts_alone() -> (
    None
):
    leaky = _result(("must", "include"), parts=["the executor did it"])

    composed = await _compose(_model(leaky, leaky), [MUST], leaks=[[], ["executor"], ["executor"]])

    assert composed.included == ["must"] and composed.degraded is True
    assert "executor" not in " ".join(composed.parts)


async def test_an_item_with_no_urgency_is_a_bug_not_a_default() -> None:
    unqueued = _item("x", UrgencyClass.ROUTINE, Initiative.ASKED).model_copy(
        update={"urgency": None}
    )

    with pytest.raises(ValueError, match="without an urgency"):
        await _compose(_model(), [unqueued])


async def test_record_in_thread_writes_one_ai_message_as_the_tools_node_under_the_lock() -> None:
    events: list[str] = []

    class Lock:
        async def __aenter__(self) -> None:
            events.append("lock")

        async def __aexit__(self, *_: object) -> None:
            events.append("unlock")

    async def update(config, values, as_node):
        events.append(f"write:{as_node}")
        [message] = values["messages"]
        assert isinstance(message, AIMessage) and message.id
        assert config["configurable"]["thread_id"] == "c"

    graph = SimpleNamespace(aupdate_state=update)
    with (
        patch(f"{MODULE}.comms_thread_lock", lambda _id: Lock()),
        patch(f"{MODULE}.GraphManager.get_graph", AsyncMock(return_value=graph)),
    ):
        await record_in_thread("c", "told")

    assert events == ["lock", "write:tools", "unlock"]


async def test_a_failed_thread_write_is_raised_not_swallowed() -> None:
    graph = SimpleNamespace(aupdate_state=AsyncMock(side_effect=RuntimeError("checkpoint down")))
    with (
        patch(f"{MODULE}.GraphManager.get_graph", AsyncMock(return_value=graph)),
        patch(f"{MODULE}.comms_thread_lock"),
        pytest.raises(RuntimeError, match="checkpoint down"),
    ):
        await record_in_thread("c", "told")


def test_compose_module_exposes_no_graph_run() -> None:
    assert not hasattr(compose_module, "execute_graph_silent")


def _run_item(
    report_id: str = "run-1",
    *,
    outcome: OutcomeState = OutcomeState.DONE,
    initiative: Initiative = Initiative.ASKED,
    urgency: UrgencyClass = UrgencyClass.ROUTINE,
    **report_fields: Any,
) -> OutboxItemDocument:
    report = RunReport(
        report_id=report_id,
        recipient="u",
        producer=ProducerKind.EXECUTOR,
        subject=Subject(kind=SubjectKind.ASK, id=report_id, label="Send the invoice"),
        occurred_at=datetime(2026, 11, 10, tzinfo=UTC),
        initiative=initiative,
        report=TaskReport(outcome=outcome),
        **report_fields,
    )
    return OutboxItemDocument(
        user_id="u",
        report_id=report_id,
        report=report,
        urgency=urgency,
        mode=ComposeMode.ANSWER,
        expires_at=datetime(2027, 1, 1, tzinfo=UTC),
    )


def _context(model: AsyncMock) -> dict[str, Any]:
    return json.loads(model.await_args_list[0].args[1][1].content)


class TestASpokenMessage:
    async def test_a_message_for_a_live_call_is_worded_to_be_heard(self) -> None:
        model = _model(_result(("run-1", "include"), parts=["Sent."]))

        await _compose(model, [_run_item()], target=InApp(reason="in_call", call_room="room-1"))

        assert _context(model)["destination"] == "voice"
        assert SPOKEN_COMPOSE_RULES in model.await_args_list[0].args[1][0].content

    async def test_a_message_for_the_app_is_not(self) -> None:
        model = _model(_result(("run-1", "include"), parts=["Sent."]))

        await _compose(model, [_run_item()])

        assert _context(model)["destination"] == "web"
        assert SPOKEN_COMPOSE_RULES not in model.await_args_list[0].args[1][0].content


class TestWhatComposeIsShownOfARun:
    async def test_the_deliverable_the_outcome_and_how_to_say_it(self) -> None:
        item = _run_item(result="Invoice 42 went to Priya")
        model = _model(_result(("run-1", "include"), parts=["Sent."]))

        await _compose(model, [item])

        [view] = _context(model)["items"]
        assert view["result"] == "Invoice 42 went to Priya"
        assert view["how_to_say"] == OUTCOME_REPLY_SHAPES[OutcomeState.DONE]
        assert "review_problem" not in view and "guidance" not in view

    async def test_a_report_the_calls_do_not_back_is_shown_with_why(self) -> None:
        item = _run_item(outcome=OutcomeState.UNVERIFIED, review_problem="no work call succeeded")
        model = _model(_result(("run-1", "include"), parts=["Not sure."]))

        await _compose(model, [item])

        [view] = _context(model)["items"]
        assert view["review_problem"] == "no work call succeeded"
        assert view["how_to_say"] == OUTCOME_REPLY_SHAPES[OutcomeState.UNVERIFIED]

    async def test_what_the_user_wrote_down_about_a_todo_is_shown(self) -> None:
        item = _run_item(
            guidance=ProducerGuidance(title="Desk", standing_rules="- tell me every time")
        )
        model = _model(_result(("run-1", "include"), parts=["x"]))

        await _compose(model, [item])

        [view] = _context(model)["items"]
        assert view["guidance"] == {
            "title": "Desk",
            "standing_rules": "- tell me every time",
            "runs_once": False,
            "verbatim": False,
        }

    async def test_a_chat_app_the_user_asked_for_and_cannot_be_used_is_named(self) -> None:
        model = _model(_result(("run-1", "include"), parts=["x"]))

        await _compose(model, [_run_item()], requested_unavailable=ConversationSource.SLACK)

        assert _context(model)["requested_channel_unavailable"] == "slack"

    async def test_no_unavailable_channel_is_named_when_none_was_asked_for(self) -> None:
        model = _model(_result(("run-1", "include"), parts=["x"]))

        await _compose(model, [_run_item()])

        assert "requested_channel_unavailable" not in _context(model)


class TestWhatGaiaDidWithEarlierRunsOfOneProducer:
    def _series_item(self) -> OutboxItemDocument:
        item = _run_item("todo-run-3")
        subject = item.report.subject.model_copy(update={"series": "todo:t1"})
        return item.model_copy(
            update={"report": item.report.model_copy(update={"subject": subject})}
        )

    def _past(self, state: ItemState, minute: int, **fields: object) -> OutboxItemDocument:
        return _run_item(f"todo-run-{minute}").model_copy(
            update={
                "state": state,
                "report": _run_item(f"todo-run-{minute}").report.model_copy(
                    update={"occurred_at": datetime(2026, 11, 10, 8, minute, tzinfo=UTC)}
                ),
                **fields,
            }
        )

    async def _earlier(
        self, past: list[OutboxItemDocument], messages: dict[str, OutboxMessageDocument | None]
    ) -> list[str]:
        model = _model(_result(("todo-run-3", "include"), parts=["x"]))
        item = self._series_item()
        with (
            patch(
                f"{MODULE}.outbox_items_repository.list_settled_of_series",
                AsyncMock(return_value=past),
            ) as listed,
            patch(
                f"{MODULE}.outbox_messages_repository.get_by_attempt",
                AsyncMock(side_effect=lambda _user, attempt: messages[attempt]),
            ),
        ):
            await _compose(model, [item])
        listed.assert_awaited_once_with(
            "u", "todo:t1", before=item.report.occurred_at, limit=COMPOSE_EARLIER_RUNS
        )
        return _context(model)["earlier_runs"]["todo-run-3"]

    def _message(self, *parts: str) -> OutboxMessageDocument:
        return OutboxMessageDocument(
            user_id="u",
            compose_attempt_id="a1",
            report_ids=["x"],
            mode=ComposeMode.UNSOLICITED,
            max_class=UrgencyClass.ROUTINE,
            parts=list(parts),
            destination="in_app",
            destination_basis="active_in_app",
            conversation_id="c",
            recorded_in=["c"],
            expires_at=datetime(2027, 1, 1, tzinfo=UTC),
        )

    async def test_a_message_that_was_sent_and_one_kept_quiet_read_oldest_first(self) -> None:
        sent = self._past(ItemState.SENT, 2, compose_attempt_id="a1")
        quiet = self._past(ItemState.DROPPED, 1, drop_reason=DropReason.NOTHING_NEW)

        earlier = await self._earlier(
            [sent, quiet], {"a1": self._message("Deploy failed.", "Want a rollback?")}
        )

        assert earlier == [
            "2026-11-10T08:01+00:00: kept quiet (nothing_new)",
            "2026-11-10T08:02+00:00: told them: Deploy failed. Want a rollback?",
        ]

    async def test_a_long_message_is_bounded(self) -> None:
        sent = self._past(ItemState.SENT, 2, compose_attempt_id="a1")

        [line] = await self._earlier([sent], {"a1": self._message("x" * 1000)})

        assert line.endswith("x" * COMPOSE_EARLIER_RUN_CHARS)
        assert len(line) < COMPOSE_EARLIER_RUN_CHARS + 60

    async def test_a_producer_with_no_series_has_no_record(self) -> None:
        model = _model(_result(("run-1", "include"), parts=["x"]))

        await _compose(model, [_run_item()])

        assert "earlier_runs" not in _context(model)

    async def test_a_sent_item_whose_message_is_missing_is_a_bug_not_a_blank(self) -> None:
        sent = self._past(ItemState.SENT, 2, compose_attempt_id="gone")

        with pytest.raises(ValueError, match="no ledger message"):
            await self._earlier([sent], {"gone": None})


class TestAVerbatimResultIsToldExactlyAsWritten:
    RESULT = "1 needs you\n\nNeeds you\n- Priya: pitch deck, by Fri"

    def _verbatim(self) -> OutboxItemDocument:
        return _run_item(
            "run-1",
            urgency=UrgencyClass.BACKGROUND,
            initiative=Initiative.SELF_INITIATED,
            result=self.RESULT,
            guidance=ProducerGuidance(title="Desk", verbatim=True),
        )

    def test_a_retelling_is_refused(self) -> None:
        retold = _result(("run-1", "include"), parts=["Priya: send the deck by Friday."])

        assert "exactly as its result is written" in (_validate(retold, [self._verbatim()]) or "")

    def test_the_result_as_written_passes_whatever_the_bubbles(self) -> None:
        as_written = _result(
            ("run-1", "include"), parts=["1 needs you", "Needs you\n- Priya: pitch deck, by Fri"]
        )

        assert _validate(as_written, [self._verbatim()]) is None

    def test_keeping_it_quiet_is_still_the_composers_call(self) -> None:
        assert _validate(_result(("run-1", "skip"), parts=[]), [self._verbatim()]) is None

    async def test_two_retellings_send_the_result_not_a_summary_of_its_facts(self) -> None:
        item = self._verbatim().model_copy(update={"urgency": UrgencyClass.TIMELY})
        retold = _result(("run-1", "include"), parts=["Priya: deck."])

        composed = await _compose(_model(retold, retold), [item])

        assert composed.degraded is True
        assert self.RESULT in composed.parts[0]


def _written(report_id: str = "w", **overrides: object) -> OutboxItemDocument:
    fields: dict[str, object] = {
        "outcome": NoticeOutcome.INFO,
        "facts": [f"fact {report_id}"],
        "producer": ProducerKind.BROWSER,
        "subject": Subject(kind=SubjectKind.BROWSER_JOB, id=report_id, label="Browser"),
    }
    base = _item(report_id, UrgencyClass.ROUTINE, Initiative.ASKED)
    report = base.report.model_copy(update={**fields, **overrides})
    return base.model_copy(update={"report": report})


async def test_a_prerendered_notice_is_said_as_its_copy_with_no_model_call() -> None:
    model = _model()
    item = _written(
        prerendered=PrerenderedMessage(kind=PrerenderedKind.ACCOUNT_LINKED, platform="Telegram")
    )

    composed = await _compose(model, [item])

    model.assert_not_awaited()
    assert composed.parts == [
        prerendered_text(PrerenderedKind.ACCOUNT_LINKED, "en", platform="Telegram")
    ]
    assert (composed.included, composed.skipped, composed.degraded) == (["w"], [], False)


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        (PrerenderedKind.ACCOUNT_LINKED, {"platform": "Telegram"}),
        (PrerenderedKind.FIRST_CONTACT, {"bubbles": ["Hey"]}),
    ],
)
async def test_a_greeting_expires_on_the_short_greeting_ttl(
    kind: PrerenderedKind, fields: dict[str, object]
) -> None:
    composed = await _compose(
        _model(),
        [_written(prerendered=PrerenderedMessage.model_validate({"kind": kind, **fields}))],
    )

    assert composed.ttl_seconds == OUTBOUND_TTL_SECONDS_GREETING < OUTBOUND_TTL_SECONDS_DEFAULT


async def test_any_other_message_keeps_the_default_ttl() -> None:
    composed = await _compose(_model(), [_written(outcome=NoticeOutcome.PROGRESS)])

    assert composed.ttl_seconds == OUTBOUND_TTL_SECONDS_DEFAULT


async def test_progress_is_said_as_its_producers_own_words_with_no_model_call() -> None:
    model = _model()

    composed = await _compose(model, [_written(outcome=NoticeOutcome.PROGRESS)])

    model.assert_not_awaited()
    assert composed.parts == ["fact w"]


async def test_a_file_notice_carries_its_file_and_no_words() -> None:
    model = _model()
    photo = OutboundAttachment(url="https://cdn.example.com/a.png", filename="a.png", caption="c")

    composed = await _compose(model, [_written(artifacts=[photo])])

    model.assert_not_awaited()
    assert (composed.parts, composed.attachments) == ([], [photo])
    assert composed.included == ["w"]


async def test_items_a_producer_wrote_and_items_to_word_are_one_message() -> None:
    model = _model(_result(("must", "include"), ("optional", "skip"), parts=["Hi"]))
    written = _written(outcome=NoticeOutcome.PROGRESS)

    composed = await _compose(model, [MUST, OPTIONAL, written])

    assert composed.parts == ["Hi", "fact w"]
    assert sorted(composed.included) == ["must", "w"]
    assert composed.skipped == ["optional"]
    shown = json.loads(model.await_args.args[1][1].content)["items"]
    assert [item["item_id"] for item in shown] == ["must", "optional"]


def _judged(**verdict_fields: object) -> OutboxItemDocument:
    return MUST.model_copy(update={"judgement": ItemJudgement(verdict=verdict(**verdict_fields))})


def test_an_item_the_judge_found_suspicious_is_marked_so_the_composer_warns() -> None:
    assert _item_view(_judged(suspicious=True))["suspicious"] is True


def test_an_item_the_judge_wants_said_with_care_is_marked_soften() -> None:
    assert _item_view(_judged(moment=Moment.SOFTEN))["soften"] is True


@pytest.mark.parametrize("judgement", [None, ItemJudgement(verdict=verdict())])
def test_an_unremarkable_item_carries_no_judge_marks(judgement: ItemJudgement | None) -> None:
    view = _item_view(MUST.model_copy(update={"judgement": judgement}))

    assert "suspicious" not in view and "soften" not in view
