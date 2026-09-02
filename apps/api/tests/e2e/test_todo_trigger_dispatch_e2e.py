"""E2E: a fired trigger fans out to subscribed todos, against real Mongo + Redis.

WHAT THIS PROVES — the loop the dispatch unit test mocks away in full (it patches
the repository, Redis, the enqueue, notifications and completion). Here every one
of those is real: ``dispatch_to_subscribed_todos`` resolves subscribers through
the real todo finders, evaluates conditions, claims the cooldown slot in real
Redis, and runs each action for real — enqueues ``execute``, writes a
notification, completes-and-tears-down.

Seeding goes through the REAL update path (``todo_repository.update`` with a
``TodoUpdate`` carrying the subscription), because the finders match on
``trigger_subscriptions.$elemMatch: {status: "active"}``. A subscription that did
not round-trip whole — the ``exclude_unset`` regression that shipped once — would
be stored without ``status`` and the ``$elemMatch`` would never match, so these
tests would go red. That makes this file the end-to-end guard for that bug.

Needs USE_REAL_SERVICES=1 (real Mongo + Redis); skipped at collection otherwise.

NOT here: running the woken ``execute_tracked_todo`` agent. Its request is covered
by ``tests/integration/test_tracked_todo_agent_request.py`` and the subscribe path
through the compiled graph by ``tests/e2e/test_todo_trigger_subscription_flow.py``.
This file asserts the ``execute`` hand-off — the enqueued job and its
``TriggerOrigin`` — not the run itself, so ``enqueue_worker_job`` is the one seam
spied rather than executed.
"""

from unittest.mock import AsyncMock, patch

from bson import ObjectId
import pytest

from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoDocument, TodoUpdate
from app.models.trigger_subscription_models import (
    ConditionMatch,
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    SubscriptionStatus,
    TriggerOrigin,
    TriggerSubscription,
)
from app.services.triggers.subscription_dispatch import dispatch_to_subscribed_todos

pytestmark = pytest.mark.e2e

_MOD = "app.services.triggers.subscription_dispatch"
GMAIL = "gmail_new_message"
SLACK = "slack_new_message"


def _condition(field: str, op: ConditionOperator, value: str) -> SubscriptionCondition:
    return SubscriptionCondition(field_name=field, operator=op, value=value)


async def _seed_watch(
    user_id: str,
    *,
    conditions: list[SubscriptionCondition],
    action: SubscriptionAction = SubscriptionAction.EXECUTE,
    match: ConditionMatch = ConditionMatch.ALL,
    resolution: SubscriptionResolution = SubscriptionResolution.ACCOUNT,
    composio_trigger_ids: list[str] | None = None,
    cooldown_seconds: int = 0,
    trigger_name: str = GMAIL,
    labels: list[str] | None = None,
) -> tuple[str, TriggerSubscription]:
    """Create a todo, then attach a subscription through the real update path.

    The update path (not create) is deliberate: it is the one that dropped nested
    defaults via ``exclude_unset`` before the fix, and it is what registration
    actually uses.
    """
    todo = await todo_repository.create(
        TodoDocument.model_validate(
            {"user_id": user_id, "title": "Chase the thing", "labels": labels or []}
        )
    )
    subscription = TriggerSubscription(
        trigger_name=trigger_name,
        conditions=conditions,
        match=match,
        action=action,
        cooldown_seconds=cooldown_seconds,
        resolution=resolution,
        composio_trigger_ids=composio_trigger_ids or [],
    )
    await todo_repository.update(
        todo.id, user_id=user_id, update=TodoUpdate(trigger_subscriptions=[subscription])
    )
    return todo.id, subscription


@pytest.fixture
def _new_user() -> str:
    return str(ObjectId())


@pytest.mark.usefixtures("mongo_db", "real_redis")
class TestTriggerDispatchAgainstRealInfra:
    async def test_a_matching_event_enqueues_execute_with_its_origin(self, _new_user) -> None:
        todo_id, sub = await _seed_watch(
            _new_user, conditions=[_condition("thread_id", ConditionOperator.EQUALS, "t-1")]
        )

        with patch(f"{_MOD}.enqueue_worker_job", new_callable=AsyncMock) as enqueue:
            with patch(f"{_MOD}.capture_event"):
                fired = await dispatch_to_subscribed_todos(
                    GMAIL, None, _new_user, {"thread_id": "t-1", "sender": "a@acme.com"}
                )

        assert fired == 1
        # The subscription was found by the real $elemMatch on status="active",
        # which only passes if it round-tripped whole through the update path.
        assert enqueue.await_count == 1
        args = enqueue.await_args.args
        assert args[1] == "execute_tracked_todo"
        assert args[2] == todo_id
        origin = args[3]
        assert isinstance(origin, TriggerOrigin)
        assert origin.subscription_id == sub.id
        assert origin.payload["thread_id"] == "t-1"

    async def test_a_non_matching_payload_does_not_fire(self, _new_user) -> None:
        await _seed_watch(
            _new_user, conditions=[_condition("thread_id", ConditionOperator.EQUALS, "t-1")]
        )

        with patch(f"{_MOD}.enqueue_worker_job", new_callable=AsyncMock) as enqueue:
            with patch(f"{_MOD}.capture_event"):
                fired = await dispatch_to_subscribed_todos(
                    GMAIL, None, _new_user, {"thread_id": "t-999"}
                )

        assert fired == 0
        enqueue.assert_not_awaited()

    async def test_a_per_resource_event_resolves_by_trigger_id_without_a_user(
        self, _new_user
    ) -> None:
        todo_id, _ = await _seed_watch(
            _new_user,
            trigger_name=SLACK,
            resolution=SubscriptionResolution.TRIGGER_ID,
            composio_trigger_ids=["ti-42"],
            conditions=[],
        )

        with patch(f"{_MOD}.enqueue_worker_job", new_callable=AsyncMock) as enqueue:
            with patch(f"{_MOD}.capture_event"):
                fired = await dispatch_to_subscribed_todos(SLACK, "ti-42", None, {"channel": "C1"})

        assert fired == 1
        assert enqueue.await_args.args[2] == todo_id

    async def test_any_mode_fires_on_a_single_matching_condition(self, _new_user) -> None:
        # match=any: one satisfied condition is enough, where match=all would need both.
        await _seed_watch(
            _new_user,
            match=ConditionMatch.ANY,
            conditions=[
                _condition("sender", ConditionOperator.CONTAINS, "acme.com"),
                _condition("sender", ConditionOperator.CONTAINS, "northwind.com"),
            ],
        )

        with patch(f"{_MOD}.enqueue_worker_job", new_callable=AsyncMock) as enqueue:
            with patch(f"{_MOD}.capture_event"):
                fired = await dispatch_to_subscribed_todos(
                    GMAIL, None, _new_user, {"sender": "ap@northwind.com"}
                )

        assert fired == 1
        assert enqueue.await_count == 1

    async def test_cooldown_suppresses_the_second_fire(self, _new_user) -> None:
        await _seed_watch(
            _new_user,
            cooldown_seconds=300,
            conditions=[_condition("thread_id", ConditionOperator.EQUALS, "t-1")],
        )
        payload = {"thread_id": "t-1"}

        with patch(f"{_MOD}.enqueue_worker_job", new_callable=AsyncMock) as enqueue:
            with patch(f"{_MOD}.capture_event"):
                first = await dispatch_to_subscribed_todos(GMAIL, None, _new_user, payload)
                second = await dispatch_to_subscribed_todos(GMAIL, None, _new_user, payload)

        # The real Redis SET NX cooldown slot is claimed on the first fire and
        # still held on the second, within the 300s window.
        assert first == 1
        assert second == 0
        assert enqueue.await_count == 1

    async def test_notify_writes_a_notification_and_leaves_the_todo_open(
        self, _new_user, mongo_db
    ) -> None:
        todo_id, sub = await _seed_watch(
            _new_user,
            action=SubscriptionAction.NOTIFY,
            conditions=[_condition("thread_id", ConditionOperator.EQUALS, "t-1")],
        )

        with patch(f"{_MOD}.capture_event"):
            fired = await dispatch_to_subscribed_todos(GMAIL, None, _new_user, {"thread_id": "t-1"})

        assert fired == 1
        note = await mongo_db["notifications"].find_one({"user_id": _new_user})
        assert note is not None, "notify action did not persist a notification"
        # notify changes no todo state — that is the whole point of the action.
        after = await todo_repository.get(todo_id, user_id=_new_user)
        assert after is not None and after.completed is False
        assert len(after.trigger_subscriptions) == 1

    async def test_complete_action_completes_the_todo_and_tears_down_the_watch(
        self, _new_user
    ) -> None:
        todo_id, _ = await _seed_watch(
            _new_user,
            action=SubscriptionAction.COMPLETE,
            conditions=[_condition("thread_id", ConditionOperator.EQUALS, "t-1")],
        )

        with patch(f"{_MOD}.capture_event"):
            fired = await dispatch_to_subscribed_todos(GMAIL, None, _new_user, {"thread_id": "t-1"})

        assert fired == 1
        after = await todo_repository.get(todo_id, user_id=_new_user)
        assert after is not None
        assert after.completed is True
        # Completion tears the watch down, or a done todo keeps burning events.
        assert after.trigger_subscriptions == []

    async def test_a_paused_subscription_does_not_fire(self, _new_user) -> None:
        # The real $elemMatch requires status="active"; a paused watch is invisible
        # to dispatch until the integration reconnects.
        await _seed_watch(
            _new_user, conditions=[_condition("thread_id", ConditionOperator.EQUALS, "t-1")]
        )
        # Flip the stored subscription to paused through the update path.
        todos = await todo_repository.find_active_by_user_and_trigger(_new_user, GMAIL)
        paused = (
            todos[0]
            .trigger_subscriptions[0]
            .model_copy(update={"status": SubscriptionStatus.PAUSED})
        )
        await todo_repository.update(
            todos[0].id, user_id=_new_user, update=TodoUpdate(trigger_subscriptions=[paused])
        )

        with patch(f"{_MOD}.enqueue_worker_job", new_callable=AsyncMock) as enqueue:
            with patch(f"{_MOD}.capture_event"):
                fired = await dispatch_to_subscribed_todos(
                    GMAIL, None, _new_user, {"thread_id": "t-1"}
                )

        assert fired == 0
        enqueue.assert_not_awaited()
