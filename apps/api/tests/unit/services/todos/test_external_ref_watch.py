"""What an open todo about an outside object watches: a thread's mail, or new mail for the desk."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.todos import (
    INBOX_DESK_AUTOMATED_SENDERS,
    INBOX_DESK_WATCH_LABELS,
    INBOX_DESK_WATCH_WINDOW_SECONDS,
)
from app.constants.trigger_gates import SystemGatePreset
from app.constants.triggers import GMAIL_EMAIL_SENT_TRIGGER_NAME, GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.db.repositories.todos import todo_repository
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.trigger_gate_models import AuthoredGate, SystemGate
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
from tests.e2e._harness.fake_todos import InMemoryTodos

pytestmark = pytest.mark.unit

MODULE = "app.services.todos.external_ref_watch"
TODO_ID = "66f838cc8829054e5f10e401"
USER_ID = "507f1f77bcf86cd799439011"
DESK = ExternalRef(source=ExternalRefSource.INBOX_DESK, id="gmail")
THREAD = ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="18c2f0a9b7d4e611")
DESK_GATE = SystemGate(preset=SystemGatePreset.INBOX_DESK)


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


@contextmanager
def _stored(todo: TodoDocument) -> Iterator[InMemoryTodos]:
    """Hold the todo behind the repository's gate write."""
    fake = InMemoryTodos(todo)
    with patch.object(
        todo_repository, "gate_ungated_subscriptions", fake.gate_ungated_subscriptions
    ):
        yield fake


async def _watches_made(register: AsyncMock, ref: ExternalRef) -> list[TriggerSubscription]:
    """Return the subscriptions a first watch of ref stored, as an older release stored them."""
    await watch_external_ref(TODO_ID, USER_ID, ref, ())
    made = [
        TriggerSubscription(
            trigger_name=call.kwargs["trigger_name"],
            conditions=call.kwargs["conditions"],
            action=SubscriptionAction.EXECUTE,
            cooldown_seconds=call.kwargs["cooldown_seconds"],
            resolution=SubscriptionResolution.ACCOUNT,
        )
        for call in register.await_args_list
    ]
    register.reset_mock()
    return made


def _todo(ref: ExternalRef, watches: list[TriggerSubscription]) -> TodoDocument:
    return TodoDocument.model_validate(
        {
            "id": TODO_ID,
            "user_id": USER_ID,
            "title": "Inbox desk",
            "external_ref": ref,
            "trigger_subscriptions": watches,
        }
    )


async def _gates_after_rewatch(
    ref: ExternalRef, todo: TodoDocument
) -> list[AuthoredGate | SystemGate | None]:
    with _stored(todo) as todos:
        await watch_external_ref(TODO_ID, USER_ID, ref, todo.trigger_subscriptions)
        stored = await todos.get(TODO_ID, user_id=USER_ID)
    assert stored is not None
    return [s.gate for s in stored.trigger_subscriptions]


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


async def test_the_desk_watch_asks_the_inbox_desk_gate_before_it_runs(
    register: AsyncMock,
) -> None:
    await watch_external_ref(TODO_ID, USER_ID, DESK, ())

    (call,) = register.await_args_list
    assert call.kwargs["gate"] == DESK_GATE


async def test_a_desk_watching_since_before_the_gate_gets_it_and_no_second_watch(
    register: AsyncMock,
) -> None:
    desk = _todo(DESK, await _watches_made(register, DESK))

    assert await _gates_after_rewatch(DESK, desk) == [DESK_GATE]
    register.assert_not_awaited()


@pytest.mark.parametrize(
    "gate",
    [SystemGate(preset=SystemGatePreset.INBOX_DESK, enabled=False), DESK_GATE],
    ids=["turned_off_by_the_user", "already_on"],
)
async def test_a_desk_watch_that_has_a_gate_keeps_it(register: AsyncMock, gate: SystemGate) -> None:
    (watch,) = await _watches_made(register, DESK)
    desk = _todo(DESK, [watch.model_copy(update={"gate": gate})])

    assert await _gates_after_rewatch(DESK, desk) == [gate]
    register.assert_not_awaited()


async def test_only_the_desks_mail_watch_is_gated(register: AsyncMock) -> None:
    """A watch on one thread, or one that only notifies, is not the desk's mail watch."""
    (watch,) = await _watches_made(register, DESK)
    on_thread = TriggerSubscription(
        trigger_name=GMAIL_NEW_MESSAGE_TRIGGER_NAME,
        conditions=[
            SubscriptionCondition(
                field_name="thread_id", operator=ConditionOperator.EQUALS, value=THREAD.id
            )
        ],
        action=SubscriptionAction.EXECUTE,
        resolution=SubscriptionResolution.ACCOUNT,
    )
    notify = watch.model_copy(update={"id": "notify-1", "action": SubscriptionAction.NOTIFY})
    desk = _todo(DESK, [watch, on_thread, notify])

    assert await _gates_after_rewatch(DESK, desk) == [DESK_GATE, None, None]


async def test_a_desk_already_watching_gets_no_second_watch(register: AsyncMock) -> None:
    await watch_external_ref(TODO_ID, USER_ID, DESK, ())
    existing = TriggerSubscription(
        trigger_name=GMAIL_NEW_MESSAGE_TRIGGER_NAME,
        conditions=_desk_conditions(register),
        action=SubscriptionAction.EXECUTE,
        resolution=SubscriptionResolution.ACCOUNT,
        gate=DESK_GATE,
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
    assert [call.kwargs["account_id"] for call in register.await_args_list] == [None, None]


async def test_a_threads_watches_ask_no_gate(register: AsyncMock) -> None:
    """Every event on a thread is a continuation, which runs without asking."""
    await watch_external_ref(TODO_ID, USER_ID, THREAD, ())
    assert [call.kwargs["gate"] for call in register.await_args_list] == [None, None]
    register.reset_mock()

    thread = _todo(THREAD, await _watches_made(register, THREAD))

    assert await _gates_after_rewatch(THREAD, thread) == [None, None]


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
