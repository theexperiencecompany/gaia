"""The Inbox desk's own fetches come back bucketed by one JEV call per email; any other run's mail is untouched."""

from collections.abc import Iterator
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.constants.desk_buckets import DESK_BUCKET_CRITERIA, DESK_BUCKET_QUESTION_KEY, DeskBucket
from app.constants.trigger_gates import SystemGatePreset
from app.models.composio_schemas.gmail import GmailMessageView
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.trigger_gate_models import SystemGate
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.services.todos.desk_mail_buckets import desk_bucketed_views
from app.utils.timezone import Timezone
from tests.helpers import trigger_gate_seams

pytestmark = pytest.mark.unit

MODULE = "app.services.todos.desk_mail_buckets"
USER_ID = "507f1f77bcf86cd799439011"
DESK_ID = "66f838cc8829054e5f10e401"
DESK_GATE = SystemGate(preset=SystemGatePreset.INBOX_DESK)
SIGN_IN = "Successful login from new device"
DECLINED = "Card transaction declined"
NEWSLETTER = "This week in AI"


def _view(n: int, subject: str) -> GmailMessageView:
    return GmailMessageView(
        id=f"m{n}",
        thread_id=f"t{n}",
        sender=f"Sender {n} <s{n}@example.com>",
        from_address=f"s{n}@example.com",
        to="aryan@heygaia.io",
        subject=subject,
        snippet="",
        time="",
        is_read=False,
        has_attachment=False,
        attachments=[],
        labels=["INBOX"],
        cc="",
    )


def _watch(gate: SystemGate | None = DESK_GATE) -> TriggerSubscription:
    return TriggerSubscription.model_validate(
        {
            "trigger_name": "gmail_new_message",
            "action": SubscriptionAction.EXECUTE,
            "resolution": SubscriptionResolution.ACCOUNT,
            "gate": gate,
        }
    )


def _todo(
    source: ExternalRefSource = ExternalRefSource.INBOX_DESK, **overrides: object
) -> TodoDocument:
    fields: dict[str, object] = {
        "id": DESK_ID,
        "user_id": USER_ID,
        "title": "Inbox desk",
        "external_ref": ExternalRef(source=source, id="gmail"),
        "trigger_subscriptions": [_watch()],
    }
    fields.update(overrides)
    return TodoDocument.model_validate(fields)


def _bucket(choice: str, probability: float = 0.99) -> httpx.Response:
    answer = {"type": "choice", "choice": choice, "probabilities": {choice: probability}}
    return httpx.Response(200, json={"answers": {DESK_BUCKET_QUESTION_KEY: answer}})


def _by_subject(answers: dict[str, httpx.Response | Exception]) -> object:
    def answer(request: httpx.Request) -> httpx.Response:
        given = answers[json.loads(request.content)["state"]["event"]["subject"]]
        if isinstance(given, Exception):
            raise given
        return given

    return answer


@pytest.fixture
def seams() -> Iterator[SimpleNamespace]:
    with (
        trigger_gate_seams(Timezone.parse("Asia/Kolkata")) as gate_seams,
        patch(f"{MODULE}.todo_repository.get", AsyncMock(return_value=_todo())) as get,
    ):
        yield SimpleNamespace(jev=gate_seams.jev, get=get)


async def test_each_email_comes_back_in_order_carrying_the_bucket_jev_chose(
    seams: SimpleNamespace,
) -> None:
    seams.jev.mock(
        side_effect=_by_subject(
            {SIGN_IN: _bucket("fyi"), DECLINED: _bucket("act"), NEWSLETTER: _bucket("junk")}
        )
    )
    views = [_view(0, SIGN_IN), _view(1, DECLINED), _view(2, NEWSLETTER)]

    bucketed = await desk_bucketed_views(USER_ID, DESK_ID, views)

    assert [(v.id, v.bucket) for v in bucketed] == [
        ("m0", DeskBucket.FYI),
        ("m1", DeskBucket.ACT),
        ("m2", DeskBucket.JUNK),
    ]
    assert seams.jev.call_count == 3
    seams.get.assert_awaited_once_with(DESK_ID, user_id=USER_ID)


async def test_jev_is_asked_one_choice_among_the_five_buckets(seams: SimpleNamespace) -> None:
    seams.jev.mock(return_value=_bucket("reply"))

    await desk_bucketed_views(USER_ID, DESK_ID, [_view(0, DECLINED)])

    sent = json.loads(seams.jev.calls.last.request.content)
    (question,) = sent["questions"].values()
    assert list(sent["questions"]) == [DESK_BUCKET_QUESTION_KEY]
    assert question["type"] == "choice"
    assert list(question["criteria"]) == [bucket.value for bucket in DeskBucket]
    assert question["criteria"] == {b.value: t for b, t in DESK_BUCKET_CRITERIA.items()}
    assert sent["state"]["event"]["subject"] == DECLINED


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(500),
        httpx.Response(200, json={"answers": {}}),
        _bucket("not_a_bucket"),
        httpx.ConnectTimeout("slow"),
    ],
    ids=["http-error", "no-answer", "unknown-choice", "timeout"],
)
async def test_an_email_jev_fails_on_reaches_the_desk_unbucketed_and_the_rest_keep_theirs(
    seams: SimpleNamespace, failure: httpx.Response | Exception
) -> None:
    seams.jev.mock(side_effect=_by_subject({SIGN_IN: failure, DECLINED: _bucket("act")}))

    bucketed = await desk_bucketed_views(USER_ID, DESK_ID, [_view(0, SIGN_IN), _view(1, DECLINED)])

    assert [v.bucket for v in bucketed] == [None, DeskBucket.ACT]


@pytest.mark.parametrize(
    "todo",
    [
        None,
        _todo(ExternalRefSource.GMAIL_THREAD),
        _todo(trigger_subscriptions=[_watch(gate=None)]),
        _todo(trigger_subscriptions=[_watch(DESK_GATE.model_copy(update={"enabled": False}))]),
    ],
    ids=["missing-todo", "not-the-desk", "no-gate", "gate-turned-off"],
)
async def test_mail_outside_a_desk_with_its_gate_on_is_returned_unasked(
    seams: SimpleNamespace, todo: TodoDocument | None
) -> None:
    seams.get.return_value = todo
    views = [_view(0, DECLINED)]

    assert await desk_bucketed_views(USER_ID, DESK_ID, views) == views
    assert seams.jev.call_count == 0


@pytest.mark.parametrize(
    ("probability", "bucket"),
    [(0.95, DeskBucket.JUNK), (0.949, None)],
    ids=["at-the-line", "just-under"],
)
async def test_junk_hides_an_email_only_at_the_gates_skip_line(
    seams: SimpleNamespace, probability: float, bucket: DeskBucket | None
) -> None:
    seams.jev.mock(return_value=_bucket("junk", probability))

    (view,) = await desk_bucketed_views(USER_ID, DESK_ID, [_view(0, NEWSLETTER)])

    assert view.bucket is bucket


async def test_a_less_sure_answer_of_any_other_bucket_still_stands(
    seams: SimpleNamespace,
) -> None:
    seams.jev.mock(return_value=_bucket("act", 0.4))

    (view,) = await desk_bucketed_views(USER_ID, DESK_ID, [_view(0, DECLINED)])

    assert view.bucket is DeskBucket.ACT
