"""Contract + finder tests for TodosRepository against real Mongo + Redis.

Todos is the migration's stress test, so this file also exercises the base
primitives it forced into existence: ``_apply_ops`` (array/positional/$unset),
``_bulk_set``/``_bulk_delete``, and their user-scope enforcement.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from app.constants.todos import GAIA_TRACKED_LABEL
from app.db.repositories.todos import TodosRepository
from app.models.todo_models import (
    Priority,
    SearchMode,
    SubTask,
    TodoDocument,
    TodoLabelCount,
    TodoSearchParams,
    TodoUpdate,
)
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    SubscriptionStatus,
    TriggerSubscription,
)
from tests.contracts.base_contract import UserScopedRepositoryContract


@pytest.fixture
def repo(raw_collection) -> TodosRepository:
    return TodosRepository()


@pytest.fixture
def make_doc() -> Callable[..., TodoDocument]:
    def _make(**overrides: object) -> TodoDocument:
        return TodoDocument.model_validate({"user_id": "user-1", "title": "Task", **overrides})

    return _make


@pytest.fixture
def make_update() -> Callable[..., TodoUpdate]:
    def _make(**fields: object) -> TodoUpdate:
        return TodoUpdate.model_validate(fields or {"title": "edited"})

    return _make


def _subscription(**overrides: object) -> TriggerSubscription:
    return TriggerSubscription.model_validate(
        {
            "trigger_name": "gmail_new_message",
            "action": SubscriptionAction.EXECUTE,
            "resolution": SubscriptionResolution.ACCOUNT,
            **overrides,
        }
    )


def _all_params(**overrides: object) -> TodoSearchParams:
    return TodoSearchParams.model_validate({"mode": SearchMode.TEXT, **overrides})


class TestTodosRepository(UserScopedRepositoryContract):
    """Runs the full user-scoped contract against the real todos repository."""

    async def list_via_cache(self, repo, user_id: str) -> list:
        page = await repo.list_page(user_id=user_id, params=_all_params(), inbox_project_id=None)
        return page.items

    # ---- list_page ---------------------------------------------------------

    async def test_list_page_filters_and_paginates(self, repo, make_doc):
        for i in range(3):
            await repo.create(make_doc(user_id="u", title=f"a{i}", project_id="p1"))
        await repo.create(make_doc(user_id="u", title="b", project_id="p2", completed=True))
        page = await repo.list_page(
            user_id="u", params=_all_params(project_id="p1"), inbox_project_id=None
        )
        assert page.total == 3
        assert {t.project_id for t in page.items} == {"p1"}

        done = await repo.list_page(
            user_id="u", params=_all_params(completed=True), inbox_project_id=None
        )
        assert done.total == 1
        assert done.items[0].title == "b"

    async def test_list_page_defaults_to_inbox_when_unfiltered(self, repo, make_doc):
        await repo.create(make_doc(user_id="u", title="inbox", project_id="inbox-1"))
        await repo.create(make_doc(user_id="u", title="other", project_id="p2"))
        page = await repo.list_page(user_id="u", params=_all_params(), inbox_project_id="inbox-1")
        assert page.total == 1
        assert page.items[0].title == "inbox"

    async def test_list_page_text_search(self, repo, make_doc):
        await repo.create(make_doc(user_id="u", title="Buy milk"))
        await repo.create(make_doc(user_id="u", title="Call bank"))
        page = await repo.list_page(
            user_id="u", params=_all_params(q="milk"), inbox_project_id=None
        )
        assert [t.title for t in page.items] == ["Buy milk"]

    async def test_list_page_orders_newest_first(self, repo, make_doc):
        """created_at descending — the order the todo list is rendered in."""
        now = datetime.now(UTC)
        # Inserted oldest-first so a stable-but-unsorted read would fail here.
        for title, age in (("Oldest", 3), ("Middle", 1), ("Newest", 0)):
            await repo.create(
                make_doc(user_id="u", title=title, created_at=now - timedelta(hours=age))
            )

        page = await repo.list_page(user_id="u", params=_all_params(), inbox_project_id=None)

        assert [t.title for t in page.items] == ["Newest", "Middle", "Oldest"]

    async def test_list_page_filters_by_priority(self, repo, make_doc):
        await repo.create(make_doc(user_id="u", title="High prio", priority=Priority.HIGH))
        await repo.create(make_doc(user_id="u", title="Low prio", priority=Priority.LOW))
        await repo.create(make_doc(user_id="u", title="Another high", priority=Priority.HIGH))

        page = await repo.list_page(
            user_id="u", params=_all_params(priority=Priority.HIGH), inbox_project_id=None
        )

        assert page.total == 2
        assert all(t.priority is Priority.HIGH for t in page.items)

    async def test_list_page_slices_pages_without_overlap(self, repo, make_doc):
        """page/per_page walk disjoint windows, and every page reports the
        unpaginated total for the same filter."""
        now = datetime.now(UTC)
        for i in range(5):
            await repo.create(
                make_doc(user_id="u", title=f"Todo {i}", created_at=now - timedelta(seconds=i))
            )

        pages = [
            await repo.list_page(
                user_id="u", params=_all_params(page=n, per_page=2), inbox_project_id=None
            )
            for n in (1, 2, 3)
        ]

        assert [len(p.items) for p in pages] == [2, 2, 1]
        assert {p.total for p in pages} == {5}
        seen = [t.id for page in pages for t in page.items]
        assert len(set(seen)) == 5
        # Pages are consecutive slices of the newest-first ordering.
        assert [t.title for t in pages[0].items] == ["Todo 0", "Todo 1"]
        assert [t.title for t in pages[2].items] == ["Todo 4"]

    async def test_list_page_scopes_to_the_caller(self, repo, make_doc):
        await repo.create(make_doc(user_id="user-A", title="A's todo"))
        await repo.create(make_doc(user_id="user-A", title="A's other todo"))
        await repo.create(make_doc(user_id="user-B", title="B's todo"))

        page_a = await repo.list_page(user_id="user-A", params=_all_params(), inbox_project_id=None)
        page_b = await repo.list_page(user_id="user-B", params=_all_params(), inbox_project_id=None)

        assert page_a.total == 2 and page_b.total == 1
        assert all(t.user_id == "user-A" for t in page_a.items)
        assert all(t.user_id == "user-B" for t in page_b.items)

    async def test_list_page_overdue_filter(self, repo, make_doc):
        """Overdue is past-due AND incomplete — a completed past-due todo is not."""
        now = datetime.now(UTC)
        await repo.create(
            make_doc(
                user_id="u", title="Overdue", completed=False, due_date=now - timedelta(days=1)
            )
        )
        await repo.create(
            make_doc(user_id="u", title="Future", completed=False, due_date=now + timedelta(days=1))
        )
        await repo.create(
            make_doc(
                user_id="u",
                title="Completed overdue",
                completed=True,
                due_date=now - timedelta(days=2),
            )
        )

        page = await repo.list_page(
            user_id="u", params=_all_params(overdue=True), inbox_project_id=None
        )

        assert page.total == 1
        assert page.items[0].title == "Overdue"

    # ---- id finders --------------------------------------------------------

    async def test_get_by_id_is_unscoped(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="owner"))
        fetched = await repo.get_by_id(created.id)
        assert fetched is not None and fetched.id == created.id
        assert await repo.get_by_id("0" * 24) is None

    async def test_find_by_ids_returns_only_matching_user_docs(self, repo, make_doc):
        a = await repo.create(make_doc(user_id="owner", title="a"))
        b = await repo.create(make_doc(user_id="owner", title="b"))
        other = await repo.create(make_doc(user_id="attacker", title="c"))
        found = await repo.find_by_ids("owner", [a.id, b.id, other.id])
        assert sorted(t.title for t in found) == ["a", "b"]

    async def test_count_in_project(self, repo, make_doc):
        await repo.create(make_doc(user_id="u", project_id="p1"))
        await repo.create(make_doc(user_id="u", project_id="p1"))
        await repo.create(make_doc(user_id="u", project_id="p2"))
        assert await repo.count_in_project("u", "p1") == 2

    # ---- aggregations ------------------------------------------------------

    async def test_compute_stats(self, repo, make_doc):
        await repo.create(make_doc(user_id="u", completed=True, priority=Priority.HIGH))
        await repo.create(
            make_doc(user_id="u", completed=False, priority=Priority.LOW, labels=["x"])
        )
        await repo.create(
            make_doc(user_id="u", completed=False, priority=Priority.LOW, labels=["x"])
        )
        stats = await repo.compute_stats(user_id="u")
        assert stats.total == 3
        assert stats.completed == 1
        assert stats.pending == 2
        assert stats.by_priority == {"high": 1, "low": 2}
        assert stats.labels == [TodoLabelCount(name="x", count=2)]

    async def test_compute_counts(self, repo, make_doc):
        now = datetime.now(UTC)
        await repo.create(make_doc(user_id="u", project_id="inbox-1", completed=False))
        await repo.create(make_doc(user_id="u", completed=True))
        await repo.create(make_doc(user_id="u", due_date=now - timedelta(days=1), completed=False))
        counts = await repo.compute_counts(user_id="u", inbox_project_id="inbox-1")
        assert counts.inbox == 1
        assert counts.completed == 1
        assert counts.overdue == 1

    async def test_top_labels(self, repo, make_doc):
        await repo.create(make_doc(user_id="u", labels=["a", "b"]))
        await repo.create(make_doc(user_id="u", labels=["a"]))
        labels = await repo.top_labels(user_id="u", limit=10)
        assert labels[0].name == "a" and labels[0].count == 2

    # ---- tracked / system finders -----------------------------------------

    async def test_list_active_tracked_only_open_tracked(self, repo, make_doc):
        await repo.create(make_doc(user_id="u", title="open", labels=[GAIA_TRACKED_LABEL]))
        await repo.create(
            make_doc(user_id="u", title="done", labels=[GAIA_TRACKED_LABEL], completed=True)
        )
        await repo.create(make_doc(user_id="u", title="plain"))
        active = await repo.list_active_tracked("u", limit=10)
        assert [t.title for t in active] == ["open"]

    async def test_vfs_partitions_by_tracked_label(self, repo, make_doc):
        cutoff = datetime.now(UTC) - timedelta(days=7)
        await repo.create(make_doc(user_id="u", title="tracked", labels=[GAIA_TRACKED_LABEL]))
        await repo.create(make_doc(user_id="u", title="user", labels=[]))
        gaia = await repo.list_active_gaia_tracked_since("u", completed_since=cutoff)
        users = await repo.list_active_user_todos_since("u", completed_since=cutoff)
        assert [t.title for t in gaia] == ["tracked"]
        assert [t.title for t in users] == ["user"]

    async def test_all_users_tracked_finders_span_users(self, repo, make_doc):
        now = datetime.now(UTC)
        await repo.create(make_doc(user_id="u1", labels=[GAIA_TRACKED_LABEL]))
        await repo.create(
            make_doc(
                user_id="u2",
                labels=[GAIA_TRACKED_LABEL],
                scheduled_at=now - timedelta(minutes=5),
                gaia_retry_count=0,
            )
        )
        everyone = await repo.list_active_tracked_all_users(limit=100)
        assert len(everyone) == 2
        due = await repo.find_due_tracked_all_users(now=now, max_retries=3, limit=100)
        assert len(due) == 1
        assert due[0].user_id == "u2"

    # ---- trigger-subscription finders --------------------------------------

    async def test_find_active_by_composio_trigger_spans_users(self, repo, make_doc):
        shared = _subscription(
            trigger_name="slack_new_message",
            resolution=SubscriptionResolution.TRIGGER_ID,
            composio_trigger_ids=["ti_shared"],
        )
        await repo.create(make_doc(user_id="u1", title="a", trigger_subscriptions=[shared]))
        await repo.create(make_doc(user_id="u2", title="b", trigger_subscriptions=[shared]))
        await repo.create(
            make_doc(
                user_id="u3",
                title="other",
                trigger_subscriptions=[
                    _subscription(
                        trigger_name="slack_new_message",
                        resolution=SubscriptionResolution.TRIGGER_ID,
                        composio_trigger_ids=["ti_other"],
                    )
                ],
            )
        )

        found = await repo.find_active_by_composio_trigger("ti_shared")

        assert sorted(t.title for t in found) == ["a", "b"]

    async def test_find_active_by_composio_trigger_skips_completed_and_paused(self, repo, make_doc):
        live = _subscription(
            resolution=SubscriptionResolution.TRIGGER_ID, composio_trigger_ids=["ti_1"]
        )
        paused = _subscription(
            resolution=SubscriptionResolution.TRIGGER_ID,
            composio_trigger_ids=["ti_1"],
            status=SubscriptionStatus.PAUSED,
        )
        await repo.create(make_doc(user_id="u", title="live", trigger_subscriptions=[live]))
        await repo.create(
            make_doc(user_id="u", title="done", trigger_subscriptions=[live], completed=True)
        )
        await repo.create(make_doc(user_id="u", title="paused", trigger_subscriptions=[paused]))

        found = await repo.find_active_by_composio_trigger("ti_1")

        assert [t.title for t in found] == ["live"]

    async def test_find_active_by_user_and_trigger_is_user_scoped(self, repo, make_doc):
        gmail = _subscription()
        await repo.create(make_doc(user_id="u1", title="mine", trigger_subscriptions=[gmail]))
        await repo.create(make_doc(user_id="u2", title="theirs", trigger_subscriptions=[gmail]))

        found = await repo.find_active_by_user_and_trigger("u1", "gmail_new_message")

        assert [t.title for t in found] == ["mine"]

    async def test_find_active_by_user_and_trigger_filters_by_trigger_name(self, repo, make_doc):
        await repo.create(
            make_doc(user_id="u", title="gmail", trigger_subscriptions=[_subscription()])
        )
        await repo.create(
            make_doc(
                user_id="u",
                title="calendar",
                trigger_subscriptions=[_subscription(trigger_name="calendar_event_starting_soon")],
            )
        )

        found = await repo.find_active_by_user_and_trigger("u", "gmail_new_message")

        assert [t.title for t in found] == ["gmail"]

    async def test_a_subscription_written_by_update_is_findable(self, repo, make_doc):
        """Registration writes through ``update``, not ``create``.

        ``_apply_update`` dumps with ``exclude_unset=True``, which recurses into
        the nested subscription: every field left at its default was dropped
        before reaching Mongo, so the stored record had no ``status`` — and the
        dispatch finders match on ``status``. The write succeeded, the document
        looked plausible, and the watch simply never fired.
        """
        doc = await repo.create(make_doc(user_id="u"))
        subscription = _subscription()

        await repo.update(
            doc.id, user_id="u", update=TodoUpdate(trigger_subscriptions=[subscription])
        )

        found = await repo.find_active_by_user_and_trigger("u", "gmail_new_message")
        assert [t.id for t in found] == [doc.id]

        stored = await repo.get(doc.id, user_id="u")
        written = stored.trigger_subscriptions[0]
        assert written.id == subscription.id
        assert written.status is SubscriptionStatus.ACTIVE
        assert written.created_at is not None

    async def test_a_trigger_id_subscription_written_by_update_is_findable(self, repo, make_doc):
        doc = await repo.create(make_doc(user_id="u"))
        subscription = _subscription(
            resolution=SubscriptionResolution.TRIGGER_ID, composio_trigger_ids=["ti_upd"]
        )

        await repo.update(
            doc.id, user_id="u", update=TodoUpdate(trigger_subscriptions=[subscription])
        )

        found = await repo.find_active_by_composio_trigger("ti_upd")
        assert [t.id for t in found] == [doc.id]

    async def test_count_trigger_references_counts_across_users(self, repo, make_doc):
        sub = _subscription(
            resolution=SubscriptionResolution.TRIGGER_ID, composio_trigger_ids=["ti_1"]
        )
        await repo.create(make_doc(user_id="u1", trigger_subscriptions=[sub]))
        await repo.create(make_doc(user_id="u2", trigger_subscriptions=[sub]))

        assert await repo.count_trigger_references("ti_1") == 2
        assert await repo.count_trigger_references("ti_missing") == 0

    async def test_count_trigger_references_counts_paused_subscriptions(self, repo, make_doc):
        # A paused subscription resumes on reconnect, so its trigger must survive.
        paused = _subscription(
            resolution=SubscriptionResolution.TRIGGER_ID,
            composio_trigger_ids=["ti_1"],
            status=SubscriptionStatus.PAUSED,
        )
        await repo.create(make_doc(user_id="u", trigger_subscriptions=[paused]))

        assert await repo.count_trigger_references("ti_1") == 1

    async def test_count_trigger_references_can_exclude_the_todo_being_deleted(
        self, repo, make_doc
    ):
        sub = _subscription(
            resolution=SubscriptionResolution.TRIGGER_ID, composio_trigger_ids=["ti_1"]
        )
        doc = await repo.create(make_doc(user_id="u", trigger_subscriptions=[sub]))

        assert await repo.count_trigger_references("ti_1", excluding_todo_id=doc.id) == 0

    # ---- bulk (base primitives) -------------------------------------------

    async def test_bulk_update_scopes_to_user(self, repo, make_doc):
        a = await repo.create(make_doc(user_id="owner", title="a"))
        b = await repo.create(make_doc(user_id="owner", title="b"))
        intruder = await repo.create(make_doc(user_id="attacker", title="c"))
        modified = await repo.bulk_update(
            "owner", [a.id, b.id, intruder.id], TodoUpdate(completed=True)
        )
        assert modified == 2  # attacker's doc untouched despite being in the id list
        assert (await repo.get_by_id(intruder.id)).completed is False

    async def test_bulk_delete_scopes_to_user(self, repo, make_doc):
        a = await repo.create(make_doc(user_id="owner", title="a"))
        intruder = await repo.create(make_doc(user_id="attacker", title="c"))
        deleted = await repo.bulk_delete("owner", [a.id, intruder.id])
        assert deleted == 1
        assert await repo.get_by_id(intruder.id) is not None
        assert await repo.get_by_id(a.id) is None

    # ---- array / positional / $unset via _apply_ops -----------------------

    async def test_add_labels_dedupes(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="u", labels=["keep"]))
        updated = await repo.add_labels(created.id, user_id="u", labels=["keep", "failed"])
        assert updated is not None
        assert sorted(updated.labels) == ["failed", "keep"]

    async def test_add_references_appends(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="u"))
        updated = await repo.add_references(created.id, user_id="u", references=["r1", "r2"])
        assert updated is not None and sorted(updated.references) == ["r1", "r2"]

    async def test_subtask_lifecycle(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="u"))
        sub = SubTask(id="s1", title="step")
        after_add = await repo.add_subtask(created.id, user_id="u", subtask=sub)
        assert after_add is not None and after_add.subtasks[0].id == "s1"

        toggled = await repo.set_subtask_fields(
            created.id, user_id="u", subtask_id="s1", completed=True
        )
        assert toggled is not None and toggled.subtasks[0].completed is True

        removed = await repo.remove_subtask(created.id, user_id="u", subtask_id="s1")
        assert removed is not None and removed.subtasks == []

    async def test_clear_workflow_id(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="u", workflow_id="wf1"))
        cleared = await repo.clear_workflow_id(created.id, user_id="u")
        assert cleared is not None and cleared.workflow_id is None

    async def test_apply_ops_is_user_scoped(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="owner", labels=["keep"]))
        assert await repo.add_labels(created.id, user_id="attacker", labels=["x"]) is None
        untouched = await repo.get_by_id(created.id)
        assert untouched is not None and untouched.labels == ["keep"]


class TestCrossDomainDeletes:
    """Finders/deletes used by the onboarding + dev-reset cross-domain callers."""

    async def test_delete_all_for_user_is_scoped(self, repo, make_doc):
        await repo.create(make_doc(user_id="u1", title="a"))
        await repo.create(make_doc(user_id="u1", title="b"))
        await repo.create(make_doc(user_id="u2", title="c"))
        assert await repo.delete_all_for_user("u1") == 2
        assert await repo.delete_all_for_user("u2") == 1

    async def test_onboarding_todos_list_and_delete(self, repo, make_doc):
        await repo.create(make_doc(user_id="u1", title="ob1", labels=["onboarding"]))
        await repo.create(make_doc(user_id="u1", title="ob2", labels=["onboarding"]))
        await repo.create(make_doc(user_id="u1", title="other", labels=["work"]))
        listed = await repo.list_onboarding_todos("u1", limit=10)
        assert {t.title for t in listed} == {"ob1", "ob2"}
        assert await repo.delete_onboarding_todos("u1") == 2
        assert await repo.list_onboarding_todos("u1", limit=10) == []
