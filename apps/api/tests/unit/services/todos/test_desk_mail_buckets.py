"""The Inbox desk's own fetches come back carrying each email's verdict bucket; any other run's mail is untouched."""

import asyncio
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import httpx
import pytest
import time_machine

from app.constants.desk_buckets import (
    DESK_AUTOMATION,
    DESK_BUCKET_CRITERIA,
    DESK_BUCKET_INSTRUCTIONS,
    DESK_BUCKET_QUESTION_KEY,
    EMAIL_VERDICT_TTL_SECONDS,
    DeskBucket,
)
from app.constants.trigger_gates import (
    GateOwner,
    SystemGatePreset,
)
from app.constants.triggers import GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.models.composio_schemas.gmail import GmailMessageView
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.trigger_gate_models import SystemGate
from app.services.todos.desk_mail_buckets import desk_bucketed_views
from app.services.triggers.trigger_gate import (
    GatedJob,
    GateHold,
    GateRun,
    GateVerdict,
    decide_gate,
)
from app.utils.timezone import Timezone
from tests.helpers import email_verdict_answers, trigger_gate_seams

pytestmark = pytest.mark.unit

MODULE = "app.services.todos.desk_mail_buckets"
VERDICT = "app.services.mail.email_verdict"
KOLKATA = Timezone.parse("Asia/Kolkata")
# 14:30 and 02:30 on the user's clock in Kolkata, and the end of their quiet hours.
AFTERNOON = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
NIGHT = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)
MORNING = datetime(2026, 10, 2, 8, 0, tzinfo=KOLKATA.tzinfo)
USER_ID = "507f1f77bcf86cd799439011"
DESK_ID = "66f838cc8829054e5f10e401"
SIGN_IN = "Successful login from new device"
DECLINED = "Card transaction declined"
NEWSLETTER = "This week in AI"


def _view(n: int, subject: str) -> GmailMessageView:
    return GmailMessageView(
        id=f"m{n}",
        thread_id=f"m{n}",
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


def _todo(
    source: ExternalRefSource = ExternalRefSource.INBOX_DESK, **overrides: object
) -> TodoDocument:
    fields: dict[str, object] = {
        "id": DESK_ID,
        "user_id": USER_ID,
        "title": "Inbox desk",
        "external_ref": ExternalRef(source=source, id="gmail"),
    }
    fields.update(overrides)
    return TodoDocument.model_validate(fields)


def _verdict(bucket: str, probabilities: Mapping[str, float] | None = None) -> httpx.Response:
    return httpx.Response(200, json=email_verdict_answers(bucket, probabilities))


def _by_subject(
    answers: Mapping[str, httpx.Response | Exception],
) -> Callable[[httpx.Request], httpx.Response]:
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
            {SIGN_IN: _verdict("fyi"), DECLINED: _verdict("act"), NEWSLETTER: _verdict("junk")}
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
    seams.jev.mock(return_value=_verdict("reply"))

    await desk_bucketed_views(USER_ID, DESK_ID, [_view(0, DECLINED)])

    sent = json.loads(seams.jev.calls.last.request.content)
    assert list(sent["questions"]) == [DESK_BUCKET_QUESTION_KEY]
    question = sent["questions"][DESK_BUCKET_QUESTION_KEY]
    assert question["type"] == "choice"
    assert question["instructions"] == DESK_BUCKET_INSTRUCTIONS
    assert sent["state"]["automation"] == DESK_AUTOMATION
    assert question["criteria"] == {b.value: t for b, t in DESK_BUCKET_CRITERIA.items()}
    assert list(question["criteria"]) == [bucket.value for bucket in DeskBucket]
    assert sent["state"]["event"]["subject"] == DECLINED


async def test_a_verdict_is_kept_by_message_id_so_a_second_fetch_asks_nothing(
    seams: SimpleNamespace, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    seams.jev.mock(return_value=_verdict("act"))

    await desk_bucketed_views(USER_ID, DESK_ID, [_view(1, DECLINED)])
    (view,) = await desk_bucketed_views(USER_ID, DESK_ID, [_view(1, DECLINED)])

    assert view.bucket is DeskBucket.ACT
    assert seams.jev.call_count == 1
    assert 0 < await fake_redis.ttl(f"email_verdict:{USER_ID}:m1") <= EMAIL_VERDICT_TTL_SECONDS


@pytest.mark.parametrize(
    ("arrived_at", "on_arrival_verdict"),
    [(AFTERNOON, GateRun()), (NIGHT, GateHold(until=MORNING))],
    ids=["by-day", "in-quiet-hours"],
)
async def test_the_sweep_reads_the_verdict_the_desk_gate_asked_for_on_arrival(
    seams: SimpleNamespace,
    fake_redis: fakeredis.aioredis.FakeRedis,
    arrived_at: datetime,
    on_arrival_verdict: GateVerdict,
) -> None:
    """Regression: a bounce of the user's own mail was skipped on arrival and act at the sweep."""
    del fake_redis
    seams.jev.mock(return_value=_verdict("act"))
    arrival = {
        "thread_id": "m1",
        "message_id": "m1",
        "sender": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
        "subject": DECLINED,
        "message_text": "Your message was not delivered.",
        "label_ids": ["INBOX"],
        "payload": {"headers": []},
    }

    with time_machine.travel(arrived_at, tick=False):
        on_arrival = await decide_gate(
            SystemGate(preset=SystemGatePreset.INBOX_DESK),
            GatedJob(GateOwner.TODO, "watch-1", USER_ID, "Inbox desk"),
            trigger_name=GMAIL_NEW_MESSAGE_TRIGGER_NAME,
            payload=arrival,
        )
        (at_sweep,) = await desk_bucketed_views(USER_ID, DESK_ID, [_view(1, DECLINED)])

    assert on_arrival == on_arrival_verdict
    assert at_sweep.bucket is DeskBucket.ACT
    assert seams.jev.call_count == 1


_REPLY_IN_THREAD = {
    "thread_id": "t1",
    "message_id": "m2",
    "sender": "Sam Partner <sam@partner.example>",
    "subject": "Re: terms",
    "message_text": "Thanks, here is the revised term sheet.",
    "label_ids": ["INBOX"],
    "payload": {"headers": []},
}


@pytest.mark.parametrize(
    ("arrived_at", "on_arrival_verdict", "jev_calls"),
    [(AFTERNOON, GateRun(), 0), (NIGHT, GateHold(until=MORNING), 1)],
    ids=["by-day", "in-quiet-hours"],
)
async def test_a_reply_on_a_thread_the_user_wrote_in_is_bucketed_reply_whatever_jev_says(
    seams: SimpleNamespace,
    fake_redis: fakeredis.aioredis.FakeRedis,
    arrived_at: datetime,
    on_arrival_verdict: GateVerdict,
    jev_calls: int,
) -> None:
    """The founder's rule: the user wrote in the thread and the latest message is someone else's."""
    del fake_redis
    seams.jev.mock(return_value=_verdict("fyi", {"fyi": 1.0}))

    with time_machine.travel(arrived_at, tick=False):
        on_arrival = await decide_gate(
            SystemGate(preset=SystemGatePreset.INBOX_DESK),
            GatedJob(GateOwner.TODO, "watch-1", USER_ID, "Inbox desk"),
            trigger_name=GMAIL_NEW_MESSAGE_TRIGGER_NAME,
            payload=_REPLY_IN_THREAD,
        )
        (at_sweep,) = await desk_bucketed_views(USER_ID, DESK_ID, [_view(2, "Re: terms")])

    assert on_arrival == on_arrival_verdict
    assert at_sweep.bucket is DeskBucket.REPLY
    assert seams.jev.call_count == jev_calls


async def test_verdicts_are_kept_per_user(
    seams: SimpleNamespace, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    del fake_redis
    seams.jev.mock(return_value=_verdict("act"))
    other = "507f1f77bcf86cd799439012"
    seams.get.side_effect = [_todo(), _todo(user_id=other)]

    await desk_bucketed_views(USER_ID, DESK_ID, [_view(1, DECLINED)])
    await desk_bucketed_views(other, DESK_ID, [_view(1, DECLINED)])

    assert seams.jev.call_count == 2


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(500),
        httpx.Response(200, json={"answers": {}}),
        _verdict("not_a_bucket"),
        httpx.Response(200, json={"answers": {"bucket": {"type": "choice", "choice": "act"}}}),
        httpx.ConnectTimeout("slow"),
    ],
    ids=["http-error", "no-answer", "unknown-choice", "no-probabilities", "timeout"],
)
async def test_an_email_jev_fails_on_reaches_the_desk_unbucketed_and_the_rest_keep_theirs(
    seams: SimpleNamespace, failure: httpx.Response | Exception
) -> None:
    seams.jev.mock(side_effect=_by_subject({SIGN_IN: failure, DECLINED: _verdict("act")}))

    bucketed = await desk_bucketed_views(USER_ID, DESK_ID, [_view(0, SIGN_IN), _view(1, DECLINED)])

    assert [v.bucket for v in bucketed] == [None, DeskBucket.ACT]


async def test_a_failed_verdict_is_not_kept_so_the_next_fetch_asks_again(
    seams: SimpleNamespace, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    seams.jev.mock(side_effect=[httpx.Response(500), _verdict("act")])

    await desk_bucketed_views(USER_ID, DESK_ID, [_view(1, DECLINED)])
    (view,) = await desk_bucketed_views(USER_ID, DESK_ID, [_view(1, DECLINED)])

    assert view.bucket is DeskBucket.ACT
    assert await fake_redis.exists(f"email_verdict:{USER_ID}:m1") == 1


@pytest.mark.parametrize(
    "todo",
    [None, _todo(ExternalRefSource.GMAIL_THREAD)],
    ids=["missing-todo", "not-the-desk"],
)
async def test_mail_outside_a_desk_is_returned_unasked(
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
    seams.jev.mock(return_value=_verdict("junk", {"junk": probability}))

    (view,) = await desk_bucketed_views(USER_ID, DESK_ID, [_view(0, NEWSLETTER)])

    assert view.bucket is bucket


async def test_a_less_sure_answer_of_any_other_bucket_still_stands(
    seams: SimpleNamespace,
) -> None:
    seams.jev.mock(return_value=_verdict("act", {"act": 0.4, "fyi": 0.35}))

    (view,) = await desk_bucketed_views(USER_ID, DESK_ID, [_view(0, DECLINED)])

    assert view.bucket is DeskBucket.ACT


async def test_a_junk_answer_without_its_own_probability_is_left_unbucketed(
    seams: SimpleNamespace,
) -> None:
    seams.jev.mock(return_value=_verdict("junk", {"fyi": 0.6}))

    (view,) = await desk_bucketed_views(USER_ID, DESK_ID, [_view(0, NEWSLETTER)])

    assert view.bucket is None


async def test_a_failed_verdict_is_logged_with_why(seams: SimpleNamespace) -> None:
    seams.jev.mock(return_value=_verdict("not_a_bucket"))

    with patch(f"{MODULE}.log") as log:
        (view,) = await desk_bucketed_views(USER_ID, DESK_ID, [_view(0, DECLINED)])

    assert view.bucket is None
    log.warning.assert_called_once_with(
        "desk_bucket.jev_failed",
        reason="jev_malformed",
        error="unknown JEV bucket choice: 'not_a_bucket'",
        error_type="ValueError",
    )


async def test_a_long_error_is_logged_clipped(seams: SimpleNamespace) -> None:
    seams.jev.mock(side_effect=httpx.ConnectError("x" * 400))

    with patch(f"{MODULE}.log") as log:
        await desk_bucketed_views(USER_ID, DESK_ID, [_view(0, DECLINED)])

    assert log.warning.call_args.kwargs["error"] == "x" * 300


async def test_no_openrouter_key_leaves_the_mail_unbucketed_without_a_warning(
    seams: SimpleNamespace,
) -> None:
    with (
        patch("app.services.hil.jev_client.resolve", AsyncMock(return_value=None)),
        patch(f"{MODULE}.log") as log,
    ):
        (view,) = await desk_bucketed_views(USER_ID, DESK_ID, [_view(0, DECLINED)])

    assert view.bucket is None
    log.warning.assert_not_called()


async def test_an_answer_slower_than_the_budget_leaves_the_mail_unbucketed(
    seams: SimpleNamespace,
) -> None:
    async def never_answers(*_: object, **__: object) -> None:
        await asyncio.Event().wait()

    with (
        patch(f"{VERDICT}.EMAIL_VERDICT_JEV_TIMEOUT_SECONDS", 0.01),
        patch(f"{VERDICT}.post_decisions", never_answers),
        patch(f"{MODULE}.log") as log,
    ):
        (view,) = await desk_bucketed_views(USER_ID, DESK_ID, [_view(0, DECLINED)])

    assert view.bucket is None
    assert log.warning.call_args.kwargs["reason"] == "jev_timeout"
