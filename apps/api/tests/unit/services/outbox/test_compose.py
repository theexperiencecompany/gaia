"""Compose: the contract a composed message must keep, the retry, the degraded render, and the thread write."""

from datetime import UTC, datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage
import pytest

from app.constants.outbound import OUTBOUND_TTL_SECONDS_DEFAULT, OUTBOUND_TTL_SECONDS_GREETING
from app.models.outbox_models import OutboxItemDocument
from app.schemas.outbound import OutboundAttachment
from app.services.outbox import compose as compose_module
from app.services.outbox.compose import _validate, compose, record_in_thread
from app.services.outbox.models import (
    ComposeMode,
    ComposeResult,
    DeliveryPolicy,
    Initiative,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    Subject,
    SubjectKind,
    UrgencyClass,
)
from app.services.outbox.prerendered import PrerenderedKind, PrerenderedMessage, prerendered_text
from app.services.outbox.router import InApp

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


async def _compose(model: AsyncMock, items: list[OutboxItemDocument]):
    graph = SimpleNamespace(aget_state=AsyncMock(return_value=SimpleNamespace(values={})))
    with (
        patch(f"{MODULE}.ainvoke_structured", model),
        patch(f"{MODULE}.GraphManager.get_graph", AsyncMock(return_value=graph)),
        patch(f"{MODULE}.outbox_messages_repository.recent_sent", AsyncMock(return_value=[])),
    ):
        return await compose(
            items,
            user_id="u",
            mode=ComposeMode.UNSOLICITED,
            target=InApp(reason="no_chat_app"),
            conversation_id="c",
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
