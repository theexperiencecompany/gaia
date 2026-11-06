"""gate_inbox_desks: the backfill that puts the system gate on desks opened before it shipped."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from app.constants.todos import INBOX_DESK_AUTOMATED_SENDERS, INBOX_DESK_WATCH_LABELS
from app.constants.trigger_gates import SystemGatePreset
from app.constants.triggers import GMAIL_NEW_MESSAGE_TRIGGER_NAME
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
from app.scripts import gate_inbox_desks as script
from tests.e2e._harness.fake_todos import InMemoryTodos

pytestmark = pytest.mark.unit

DESK = ExternalRef(source=ExternalRefSource.INBOX_DESK, id="gmail")
DESK_GATE = SystemGate(preset=SystemGatePreset.INBOX_DESK)
TURNED_OFF = SystemGate(preset=SystemGatePreset.INBOX_DESK, enabled=False)
UNGATED_ID = "66f838cc8829054e5f10e401"
ALSO_UNGATED_ID = "66f838cc8829054e5f10e405"
DESK_MAIL = [
    *(
        SubscriptionCondition(field_name="label_ids", operator=ConditionOperator.CONTAINS, value=v)
        for v in INBOX_DESK_WATCH_LABELS
    ),
    *(
        SubscriptionCondition(field_name="sender", operator=ConditionOperator.NOT_CONTAINS, value=v)
        for v in INBOX_DESK_AUTOMATED_SENDERS
    ),
]
ON_THREAD = [
    SubscriptionCondition(field_name="thread_id", operator=ConditionOperator.EQUALS, value="t-1")
]


def _watch(
    conditions: list[SubscriptionCondition], gate: SystemGate | None = None
) -> TriggerSubscription:
    return TriggerSubscription(
        trigger_name=GMAIL_NEW_MESSAGE_TRIGGER_NAME,
        conditions=conditions,
        action=SubscriptionAction.EXECUTE,
        resolution=SubscriptionResolution.ACCOUNT,
        gate=gate,
    )


def _desk(
    todo_id: str, user_id: str, *watches: TriggerSubscription, **fields: object
) -> TodoDocument:
    return TodoDocument.model_validate(
        {
            "id": todo_id,
            "user_id": user_id,
            "title": "Inbox desk",
            "external_ref": DESK,
            "trigger_subscriptions": list(watches),
            **fields,
        }
    )


@pytest.fixture
def todos() -> Iterator[InMemoryTodos]:
    """Every desk shape the backfill meets, behind the two repository calls it makes."""
    fake = InMemoryTodos(
        _desk(UNGATED_ID, "u1", _watch(DESK_MAIL), _watch(ON_THREAD)),
        _desk("66f838cc8829054e5f10e402", "u2", _watch(DESK_MAIL, TURNED_OFF)),
        _desk("66f838cc8829054e5f10e403", "u3", _watch(DESK_MAIL, DESK_GATE)),
        _desk("66f838cc8829054e5f10e404", "u4", _watch(DESK_MAIL), completed=True),
        _desk(ALSO_UNGATED_ID, "u5", _watch(DESK_MAIL)),
    )
    with (
        patch.object(
            todo_repository,
            "list_open_by_external_ref_all_users",
            fake.list_open_by_external_ref_all_users,
        ),
        patch.object(
            todo_repository, "gate_ungated_subscriptions", fake.gate_ungated_subscriptions
        ),
    ):
        yield fake


async def _gates(todos: InMemoryTodos) -> dict[str, list[AuthoredGate | SystemGate | None]]:
    """Each desk's watch gates, by owner."""
    desks = [await todos.get(f"66f838cc8829054e5f10e40{n}") for n in range(1, 6)]
    return {d.user_id: [w.gate for w in d.trigger_subscriptions] for d in desks if d is not None}


BEFORE = {
    "u1": [None, None],
    "u2": [TURNED_OFF],
    "u3": [DESK_GATE],
    "u4": [None],
    "u5": [None],
}
AFTER = {**BEFORE, "u1": [DESK_GATE, None], "u5": [DESK_GATE]}


async def test_a_dry_run_names_each_desk_it_would_gate_and_writes_nothing(
    todos: InMemoryTodos, capsys: pytest.CaptureFixture[str]
) -> None:
    await script._run(argparse.Namespace(apply=False))

    assert await _gates(todos) == BEFORE
    assert capsys.readouterr().out.splitlines() == [
        "open Inbox desks: 4",
        "desks whose mail watch has no gate: 2",
        f"  desk {UNGATED_ID} of user u1",
        f"  desk {ALSO_UNGATED_ID} of user u5",
        "",
        "dry run: nothing written. Re-run with --apply to gate them.",
    ]


async def test_apply_gates_only_the_mail_watch_that_never_had_one(
    todos: InMemoryTodos, capsys: pytest.CaptureFixture[str]
) -> None:
    await script._run(argparse.Namespace(apply=True))

    assert await _gates(todos) == AFTER
    assert capsys.readouterr().out.splitlines()[-1] == "gated 2 desk(s)"


async def test_a_second_apply_finds_nothing_left_to_gate(
    todos: InMemoryTodos, capsys: pytest.CaptureFixture[str]
) -> None:
    await script._run(argparse.Namespace(apply=True))
    capsys.readouterr()

    await script._run(argparse.Namespace(apply=True))

    assert await _gates(todos) == AFTER
    assert capsys.readouterr().out.splitlines() == [
        "open Inbox desks: 4",
        "desks whose mail watch has no gate: 0",
        "",
        "gated 0 desk(s)",
    ]
