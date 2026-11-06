"""What an open todo about an outside object watches: a thread's mail; the desk runs on its schedule."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest

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


@pytest.mark.regression
async def test_new_mail_never_wakes_the_desk(register: AsyncMock) -> None:
    """Regression: the desk woke on any person's mail, so it spoke at random hours."""
    added = await watch_external_ref(TODO_ID, USER_ID, DESK, ())

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
    assert [call.kwargs["account_id"] for call in register.await_args_list] == [None, None]


async def test_a_thread_in_one_account_only_watches_that_account(register: AsyncMock) -> None:
    """A Gmail thread id means nothing outside its mailbox, so another account's mail never wakes it."""
    in_work = ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id=THREAD.id, account="acct_work")

    await watch_external_ref(TODO_ID, USER_ID, in_work, ())

    assert [call.kwargs["account_id"] for call in register.await_args_list] == [
        "acct_work",
        "acct_work",
    ]


async def test_a_watch_on_the_threads_other_account_is_not_the_one_it_needs(
    register: AsyncMock,
) -> None:
    in_work = ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id=THREAD.id, account="acct_work")
    on_thread = SubscriptionCondition(
        field_name="thread_id", operator=ConditionOperator.EQUALS, value=THREAD.id
    )
    elsewhere = [
        TriggerSubscription(
            trigger_name=name,
            account_id="acct_home",
            conditions=[on_thread],
            action=SubscriptionAction.EXECUTE,
            resolution=SubscriptionResolution.ACCOUNT,
        )
        for name in (GMAIL_NEW_MESSAGE_TRIGGER_NAME, GMAIL_EMAIL_SENT_TRIGGER_NAME)
    ]

    await watch_external_ref(TODO_ID, USER_ID, in_work, elsewhere)

    assert register.await_count == 2
