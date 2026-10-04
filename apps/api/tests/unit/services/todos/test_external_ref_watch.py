"""What an open todo about an outside object watches: a thread's mail, or new mail for the desk."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.todos import (
    INBOX_DESK_AUTOMATED_SENDERS,
    INBOX_DESK_WATCH_LABELS,
    INBOX_DESK_WATCH_WINDOW_SECONDS,
)
from app.constants.triggers import GMAIL_EMAIL_SENT_TRIGGER_NAME, GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.models.todo_models import ExternalRef, ExternalRefSource
from app.models.trigger_subscription_models import (
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.services.todos.external_ref_watch import watch_external_ref
from app.services.triggers.condition_matching import conditions_match
from app.services.triggers.subscription_service import DEFAULT_COOLDOWN_SECONDS, SubscriptionError

pytestmark = pytest.mark.unit

MODULE = "app.services.todos.external_ref_watch"
TODO_ID = "66f838cc8829054e5f10e401"
USER_ID = "507f1f77bcf86cd799439011"
DESK = ExternalRef(source=ExternalRefSource.INBOX_DESK, id="gmail")
THREAD = ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="18c2f0a9b7d4e611")


@pytest.fixture
def register() -> Iterator[AsyncMock]:
    async def _register(
        *, trigger_name: str, conditions: list[SubscriptionCondition], **_: object
    ) -> tuple[TriggerSubscription, None, bool]:
        stored = TriggerSubscription(
            trigger_name=trigger_name,
            conditions=conditions,
            action=SubscriptionAction.EXECUTE,
            resolution=SubscriptionResolution.ACCOUNT,
        )
        return stored, None, True

    with patch(f"{MODULE}.register_subscription", AsyncMock(side_effect=_register)) as mock:
        yield mock


def _desk_conditions(register: AsyncMock) -> list[SubscriptionCondition]:
    (call,) = register.await_args_list
    return list(call.kwargs["conditions"])


async def test_the_desk_wakes_on_new_mail_at_most_once_a_window(register: AsyncMock) -> None:
    await watch_external_ref(TODO_ID, USER_ID, DESK, ())

    (call,) = register.await_args_list
    assert call.kwargs["trigger_name"] == GMAIL_NEW_MESSAGE_TRIGGER_NAME
    assert call.kwargs["action"] is SubscriptionAction.EXECUTE
    assert call.kwargs["cooldown_seconds"] == INBOX_DESK_WATCH_WINDOW_SECONDS


@pytest.mark.parametrize(
    ("labels", "sender", "wakes"),
    [
        (["INBOX", "CATEGORY_PERSONAL", "UNREAD"], "Priya <priya@northwind.vc>", True),
        (["INBOX", "CATEGORY_UPDATES"], "Priya <priya@northwind.vc>", False),
        (["CATEGORY_PERSONAL", "SENT"], "me@example.com", False),
        (["INBOX", "CATEGORY_PERSONAL"], "GitHub <notifications@github.com>", False),
        (["INBOX", "CATEGORY_PERSONAL"], "Acme <no-reply@acme.com>", False),
    ],
)
async def test_only_a_person_writing_to_the_primary_inbox_wakes_the_desk(
    register: AsyncMock, labels: list[str], sender: str, wakes: bool
) -> None:
    await watch_external_ref(TODO_ID, USER_ID, DESK, ())

    payload: dict[str, object] = {"label_ids": labels, "sender": sender}
    assert (
        conditions_match(GMAIL_NEW_MESSAGE_TRIGGER_NAME, _desk_conditions(register), payload)
        is wakes
    )


async def test_the_desk_skips_the_same_senders_its_fetch_filters(register: AsyncMock) -> None:
    await watch_external_ref(TODO_ID, USER_ID, DESK, ())

    excluded = {
        c.value for c in _desk_conditions(register) if c.operator is ConditionOperator.NOT_CONTAINS
    }
    assert excluded == set(INBOX_DESK_AUTOMATED_SENDERS)
    included = {
        c.value for c in _desk_conditions(register) if c.operator is ConditionOperator.CONTAINS
    }
    assert included == set(INBOX_DESK_WATCH_LABELS)


async def test_a_desk_already_watching_gets_no_second_watch(register: AsyncMock) -> None:
    await watch_external_ref(TODO_ID, USER_ID, DESK, ())
    existing = TriggerSubscription(
        trigger_name=GMAIL_NEW_MESSAGE_TRIGGER_NAME,
        conditions=_desk_conditions(register),
        action=SubscriptionAction.EXECUTE,
        resolution=SubscriptionResolution.ACCOUNT,
    )
    register.reset_mock()

    added = await watch_external_ref(TODO_ID, USER_ID, DESK, [existing])

    assert added == []
    register.assert_not_awaited()


async def test_a_concurrent_winners_row_is_not_rolled_back_with_this_calls_failures() -> None:
    """A later watch failing must not take down a concurrent winner's row."""
    winner = TriggerSubscription(
        trigger_name=GMAIL_NEW_MESSAGE_TRIGGER_NAME,
        conditions=[],
        action=SubscriptionAction.EXECUTE,
        resolution=SubscriptionResolution.ACCOUNT,
    )
    with (
        patch(
            f"{MODULE}.register_subscription",
            AsyncMock(
                side_effect=[
                    (winner, None, False),
                    SubscriptionError("registration_failed"),
                ]
            ),
        ),
        patch(f"{MODULE}.unregister_subscription", new_callable=AsyncMock) as unregister,
    ):
        with pytest.raises(SubscriptionError):
            await watch_external_ref(TODO_ID, USER_ID, THREAD, [])

    unregister.assert_not_awaited()


async def test_a_thread_watches_its_mail_both_ways_in_the_default_window(
    register: AsyncMock,
) -> None:
    await watch_external_ref(TODO_ID, USER_ID, THREAD, ())

    on_thread = [
        SubscriptionCondition(
            field_name="thread_id", operator=ConditionOperator.EQUALS, value=THREAD.id
        )
    ]
    assert [
        (call.kwargs["trigger_name"], call.kwargs["conditions"], call.kwargs["cooldown_seconds"])
        for call in register.await_args_list
    ] == [
        (GMAIL_NEW_MESSAGE_TRIGGER_NAME, on_thread, DEFAULT_COOLDOWN_SECONDS),
        (GMAIL_EMAIL_SENT_TRIGGER_NAME, on_thread, DEFAULT_COOLDOWN_SECONDS),
    ]
