"""Moving inbox alerts to thread todos: only GAIA's own watch goes, and only the desks' silent threads speak."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest
from scripts.move_inbox_alerts_to_threads import (
    LEGACY_DESK_WATCH_CONDITIONS,
    SPEAKING_THREAD,
    MigrationResult,
    run_migration,
)

from app.constants.triggers import GMAIL_EMAIL_SENT_TRIGGER_NAME, GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.trigger_subscription_models import (
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    TriggerSubscription,
)

MODULE = "scripts.move_inbox_alerts_to_threads"
DESK_REF = ExternalRef(source=ExternalRefSource.INBOX_DESK, id="gmail")


def _watch(
    conditions: frozenset[SubscriptionCondition] | list[SubscriptionCondition],
    trigger_name: str = GMAIL_NEW_MESSAGE_TRIGGER_NAME,
) -> TriggerSubscription:
    return TriggerSubscription(
        trigger_name=trigger_name,
        conditions=list(conditions),
        action=SubscriptionAction.EXECUTE,
        resolution=SubscriptionResolution.ACCOUNT,
    )


def _desk(desk_id: str, user_id: str, *watches: TriggerSubscription) -> TodoDocument:
    return TodoDocument(
        id=desk_id,
        user_id=user_id,
        title="Inbox desk",
        external_ref=DESK_REF,
        trigger_subscriptions=list(watches),
    )


def _thread(
    todo_id: str, parent: str | None, *, notify_on_run: bool, user_id: str = "u-1"
) -> TodoDocument:
    return TodoDocument(
        id=todo_id,
        user_id=user_id,
        title="Reply to Sam",
        parent_todo_id=parent,
        notify_on_run=notify_on_run,
        external_ref=ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id=f"thread-{todo_id}"),
    )


@dataclass
class _Seams:
    unregister: AsyncMock
    update: AsyncMock
    recorded: AsyncMock


@pytest.fixture
def seams() -> Iterator[_Seams]:
    with (
        patch(f"{MODULE}.unregister_subscription", AsyncMock()) as unregister,
        patch(f"{MODULE}.todo_repository.update", AsyncMock(return_value=object())) as update,
        patch(f"{MODULE}.record_field_changes", AsyncMock()) as recorded,
    ):
        yield _Seams(unregister, update, recorded)


async def _run(
    desks: list[TodoDocument], threads: Sequence[TodoDocument] = (), *, dry_run: bool
) -> MigrationResult:
    by_source = {ExternalRefSource.INBOX_DESK: desks, ExternalRefSource.GMAIL_THREAD: list(threads)}
    with patch(
        f"{MODULE}.todo_repository.list_open_by_external_ref_source",
        AsyncMock(side_effect=lambda source: by_source[source]),
    ):
        return await run_migration(dry_run=dry_run)


async def test_a_dry_run_reports_what_would_change_and_writes_nothing(seams: _Seams) -> None:
    legacy = _watch(LEGACY_DESK_WATCH_CONDITIONS)
    silent = _thread("t-1", "d-1", notify_on_run=False)

    result = await _run([_desk("d-1", "u-1", legacy)], [silent], dry_run=True)

    assert result.watched == {"d-1": [legacy]}
    assert result.silent_threads == [silent]
    seams.unregister.assert_not_awaited()
    seams.update.assert_not_awaited()


async def test_only_gaias_own_mail_watch_is_removed(seams: _Seams) -> None:
    legacy = _watch(LEGACY_DESK_WATCH_CONDITIONS)
    asked_for = _watch(
        [
            SubscriptionCondition(
                field_name="sender", operator=ConditionOperator.CONTAINS, value="boss@acme.com"
            )
        ]
    )
    sent = _watch(LEGACY_DESK_WATCH_CONDITIONS, trigger_name=GMAIL_EMAIL_SENT_TRIGGER_NAME)

    result = await _run(
        [_desk("d-1", "u-1", legacy, asked_for, sent), _desk("d-2", "u-2", asked_for)],
        dry_run=False,
    )

    seams.unregister.assert_awaited_once_with("d-1", "u-1", legacy.id)
    assert result.watches_removed == 1
    assert result.failures == {}


async def test_only_a_desks_silent_thread_todos_start_delivering(seams: _Seams) -> None:
    silent = _thread("t-1", "d-1", notify_on_run=False)
    already = _thread("t-2", "d-1", notify_on_run=True)
    top_level = _thread("t-3", None, notify_on_run=False)
    other_parent = _thread("t-4", "not-a-desk", notify_on_run=False)

    result = await _run(
        [_desk("d-1", "u-1")], [silent, already, top_level, other_parent], dry_run=False
    )

    seams.update.assert_awaited_once_with("t-1", user_id="u-1", update=SPEAKING_THREAD)
    seams.recorded.assert_awaited_once()
    assert result.threads_speaking == 1


async def test_a_todo_that_fails_is_reported_and_the_rest_still_run(seams: _Seams) -> None:
    first, second = _watch(LEGACY_DESK_WATCH_CONDITIONS), _watch(LEGACY_DESK_WATCH_CONDITIONS)
    seams.unregister.side_effect = [RuntimeError("mongo down"), None]
    seams.update.side_effect = [None, object()]

    result = await _run(
        [_desk("d-1", "u-1", first), _desk("d-2", "u-2", second)],
        [_thread("t-1", "d-1", notify_on_run=False), _thread("t-2", "d-2", notify_on_run=False)],
        dry_run=False,
    )

    assert result.failures["d-1"] == "RuntimeError: mongo down"
    assert result.failures["t-1"].startswith("LookupError: Thread todo t-1 vanished")
    assert (result.watches_removed, result.threads_speaking) == (1, 1)
    seams.unregister.assert_any_await("d-2", "u-2", second.id)
