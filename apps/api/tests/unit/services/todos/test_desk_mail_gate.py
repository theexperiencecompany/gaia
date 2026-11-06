"""The Inbox desk's own fetches pass the gate its Gmail watch passes; any other run's mail is untouched."""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.trigger_gates import GateOwner, SystemGatePreset
from app.models.composio_schemas.gmail import GmailMessageView
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.trigger_gate_models import SystemGate
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.services.todos.desk_mail_gate import desk_gated_views
from app.services.triggers.trigger_gate import GateRun, GateSkip

pytestmark = pytest.mark.unit

MODULE = "app.services.todos.desk_mail_gate"
USER_ID = "507f1f77bcf86cd799439011"
DESK_ID = "66f838cc8829054e5f10e401"
DESK_GATE = SystemGate(preset=SystemGatePreset.INBOX_DESK)
SKIP = GateSkip(event="Infisical", condition="a real person is waiting on you", certainty=0.99)


def _view(n: int) -> GmailMessageView:
    return GmailMessageView(
        id=f"m{n}",
        thread_id=f"t{n}",
        sender=f"Sender {n} <s{n}@example.com>",
        from_address=f"s{n}@example.com",
        to="aryan@heygaia.io",
        subject=f"Subject {n}",
        snippet="",
        time="",
        is_read=False,
        has_attachment=False,
        attachments=[],
        labels=["INBOX"],
        cc="",
    )


def _watch(trigger_name: str = "gmail_new_message", **overrides: object) -> TriggerSubscription:
    return TriggerSubscription.model_validate(
        {
            "trigger_name": trigger_name,
            "action": SubscriptionAction.EXECUTE,
            "resolution": SubscriptionResolution.ACCOUNT,
            "gate": DESK_GATE,
            **overrides,
        }
    )


def _todo(
    source: ExternalRefSource = ExternalRefSource.INBOX_DESK, **overrides: object
) -> TodoDocument:
    fields: dict[str, object] = {
        "id": DESK_ID,
        "user_id": USER_ID,
        "title": "Inbox desk",
        "description": "Triage the inbox",
        "external_ref": ExternalRef(source=source, id="gmail"),
        "trigger_subscriptions": [_watch()],
    }
    fields.update(overrides)
    return TodoDocument.model_validate(fields)


@pytest.fixture
def seams() -> Iterator[SimpleNamespace]:
    with (
        patch(f"{MODULE}.todo_repository.get", AsyncMock(return_value=_todo())) as get,
        patch(f"{MODULE}.decide_fetched_mail", AsyncMock()) as decide,
    ):
        yield SimpleNamespace(get=get, decide=decide)


async def test_the_desk_keeps_only_what_its_gate_lets_through(seams: SimpleNamespace) -> None:
    views = [_view(0), _view(1), _view(2)]
    (watch,) = seams.get.return_value.trigger_subscriptions
    seams.decide.return_value = [SKIP, GateRun(), SKIP]

    kept = await desk_gated_views(USER_ID, DESK_ID, views)

    assert kept == [views[1]]
    seams.get.assert_awaited_once_with(DESK_ID, user_id=USER_ID)
    gate, job, payloads = seams.decide.await_args.args
    assert gate == DESK_GATE
    assert (job.owner, job.id, job.user_id) == (GateOwner.TODO, watch.id, USER_ID)
    assert job.automation == "Inbox desk: Triage the inbox"
    assert [p["subject"] for p in payloads] == ["Subject 0", "Subject 1", "Subject 2"]


async def test_a_verdict_count_that_does_not_match_the_mail_fails_loud(
    seams: SimpleNamespace,
) -> None:
    seams.decide.return_value = [GateRun()]

    with pytest.raises(ValueError, match="zip"):
        await desk_gated_views(USER_ID, DESK_ID, [_view(0), _view(1)])


async def test_a_todo_that_is_not_the_desk_keeps_every_email_unasked(
    seams: SimpleNamespace,
) -> None:
    seams.get.return_value = _todo(ExternalRefSource.GMAIL_THREAD)
    views = [_view(0)]

    assert await desk_gated_views(USER_ID, DESK_ID, views) == views
    seams.decide.assert_not_awaited()


async def test_a_desk_with_no_gated_gmail_watch_keeps_every_email_unasked(
    seams: SimpleNamespace,
) -> None:
    seams.get.return_value = _todo(trigger_subscriptions=[_watch(gate=None)])
    views = [_view(0)]

    assert await desk_gated_views(USER_ID, DESK_ID, views) == views
    seams.decide.assert_not_awaited()


async def test_a_missing_todo_keeps_every_email(seams: SimpleNamespace) -> None:
    seams.get.return_value = None
    views = [_view(0)]

    assert await desk_gated_views(USER_ID, DESK_ID, views) == views
    seams.decide.assert_not_awaited()
