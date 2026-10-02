"""Unit tests for tracked_todo_service (GAIA working-memory todo lifecycle).

Covers the VFS label + canvas/log persistence + ChromaDB indexing pipeline,
completion/archival, and the context-summary renderers the agent sees.
"""

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.constants import todos as todo_constants
from app.constants.todos import (
    ACTIVE_TRACKED_SUMMARY_LIMIT,
    CANVAS_SECTIONS,
    GAIA_TRACKED_LABEL,
    TodoActivityEvent,
)
from app.constants.triggers import GMAIL_EMAIL_SENT_TRIGGER_NAME, GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.models.todo_models import (
    ExternalRef,
    ExternalRefSource,
    Priority,
    TodoDocument,
    TodoModel,
    TodoResponse,
    TodoUpdate,
)
from app.models.trigger_subscription_models import (
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
)
from app.services.canvas_markdown import normalize_canvas
from app.services.todos import errors as todo_errors
from app.services.todos.errors import SubTodoParentError
from app.services.tracked_todo_service import (
    CANVAS_TEMPLATE,
    TrackedTodoService,
    require_sub_todo_parent,
    starting_canvas,
    tracked_todo_service,
)
from app.services.triggers.subscription_service import SubscriptionError
from app.utils.occurrence import occurrence_stamp

_MOD = "app.services.tracked_todo_service"
USER_ID = "507f1f77bcf86cd799439011"
TODO_ID = "todo-1"


def _todo_doc(**overrides: object) -> TodoDocument:
    now = datetime.now(UTC)
    data: dict[str, object] = {
        "id": TODO_ID,
        "user_id": USER_ID,
        "title": "Prepare Q3 report",
        "labels": [GAIA_TRACKED_LABEL, "work"],
        "vfs_path": f"/workspace/gaia-tasks/{TODO_ID}",
        "canvas_content": "# Prepare Q3 report\n\n## Key Details\nthread: abc123\n\n## Timeline\n- step one\n",
        "log_content": "# System Log\n",
        "completed": False,
        "created_at": now - timedelta(days=2),
        "updated_at": now - timedelta(hours=1),
        "due_date": None,
    }
    data.update(overrides)
    return TodoDocument(**data)


def _todo_response(**overrides: object) -> TodoResponse:
    now = datetime.now(UTC)
    data: dict[str, object] = {
        "id": TODO_ID,
        "user_id": USER_ID,
        "title": "Prepare Q3 report",
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return TodoResponse(**data)


@pytest.fixture
def mock_repo():
    with patch(f"{_MOD}.todo_repository") as m:
        m.get = AsyncMock(return_value=None)
        m.update = AsyncMock(return_value=None)
        m.list_active_tracked = AsyncMock(return_value=[])
        m.find_sub_todos = AsyncMock(return_value=[])
        m.count_open_sub_todos = AsyncMock(return_value={})
        m.is_valid_id = MagicMock(side_effect=lambda todo_id: len(todo_id) == 24)
        yield m


@pytest.fixture
def mock_deps():
    with (
        patch(f"{_MOD}.TodoService.create_todo", new_callable=AsyncMock) as m_create,
        patch(f"{_MOD}.store_canvas_embedding", new_callable=AsyncMock) as m_store,
        patch(f"{_MOD}.mark_canvas_completed", new_callable=AsyncMock) as m_mark,
        patch(f"{_MOD}.schedule_gaia_tasks_sync", new_callable=MagicMock) as m_sync,
        patch(f"{_MOD}.RedisPoolManager.get_pool", new_callable=AsyncMock) as m_pool,
        # create=True: append_activity is imported into the service only on
        # this branch. The regression lane runs these tests against base,
        # where the name is absent, and an erroring fixture is not proof.
        patch(f"{_MOD}.append_activity", new_callable=AsyncMock, create=True) as m_append_activity,
        patch(f"{_MOD}.append_log", new_callable=AsyncMock) as m_append_log,
        patch(f"{_MOD}.teardown_subscriptions", new_callable=AsyncMock) as m_teardown,
        patch(f"{_MOD}.record_activity", new_callable=AsyncMock) as m_record,
    ):
        yield SimpleNamespace(
            create=m_create,
            store=m_store,
            mark=m_mark,
            sync=m_sync,
            pool=m_pool,
            append_activity=m_append_activity,
            append_log=m_append_log,
            teardown=m_teardown,
            record=m_record,
        )


_THREAD = ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="thread-1")
_REGISTER = "app.services.todos.external_ref_watch.register_subscription"


@pytest.fixture
def watch():
    with (
        patch(_REGISTER, new_callable=AsyncMock) as m_register,
        patch(f"{_MOD}.TodoService.delete_todo", new_callable=AsyncMock) as m_delete,
    ):
        yield SimpleNamespace(register=m_register, delete=m_delete)


class TestCreateThreadTodo:
    """A todo about a Gmail thread is created already watching that thread both ways."""

    async def test_the_ref_reaches_the_insert(self, mock_repo, mock_deps, watch):
        mock_deps.create.return_value = _todo_response()
        await TrackedTodoService.create_tracked_todo(USER_ID, "Reply", external_ref=_THREAD)
        assert mock_deps.create.await_args.args[1] == USER_ID
        assert mock_deps.create.await_args.kwargs["external_ref"] == _THREAD

    async def test_incoming_and_sent_mail_on_the_thread_both_run_the_todo(
        self, mock_repo, mock_deps, watch
    ):
        mock_deps.create.return_value = _todo_response()

        await TrackedTodoService.create_tracked_todo(USER_ID, "Reply", external_ref=_THREAD)

        calls = [c.kwargs for c in watch.register.await_args_list]
        assert sorted(c["trigger_name"] for c in calls) == sorted(
            [GMAIL_NEW_MESSAGE_TRIGGER_NAME, GMAIL_EMAIL_SENT_TRIGGER_NAME]
        )
        on_thread = [
            SubscriptionCondition(
                field_name="thread_id", operator=ConditionOperator.EQUALS, value="thread-1"
            )
        ]
        for kwargs in calls:
            assert kwargs["todo_id"] == TODO_ID
            assert kwargs["user_id"] == USER_ID
            assert kwargs["conditions"] == on_thread
            assert kwargs["action"] is SubscriptionAction.EXECUTE

    async def test_the_watches_follow_the_creation_entry(self, mock_repo, mock_deps, watch):
        """Each watch appends to activity.md, so it must land after the write that sets it."""
        order: list[str] = []
        mock_deps.create.return_value = _todo_response()
        mock_repo.update.side_effect = lambda *a, **k: order.append("setup")
        watch.register.side_effect = lambda **k: order.append(k["trigger_name"])

        await TrackedTodoService.create_tracked_todo(USER_ID, "Reply", external_ref=_THREAD)

        assert order[0] == "setup" and len(order) == 3

    async def test_a_todo_without_a_ref_watches_nothing(self, mock_repo, mock_deps, watch):
        mock_deps.create.return_value = _todo_response()
        await TrackedTodoService.create_tracked_todo(USER_ID, "Reply")
        watch.register.assert_not_awaited()

    async def test_the_inbox_desk_ref_is_an_identity_that_watches_nothing(
        self, mock_repo, mock_deps, watch
    ):
        desk = ExternalRef(source=ExternalRefSource.INBOX_DESK, id="gmail")
        mock_deps.create.return_value = _todo_response()

        await TrackedTodoService.create_tracked_todo(USER_ID, "Inbox desk", external_ref=desk)

        assert mock_deps.create.await_args.kwargs["external_ref"] == desk
        watch.register.assert_not_awaited()

    async def test_a_watch_that_fails_takes_the_todo_with_it(self, mock_repo, mock_deps, watch):
        """An unwatched thread todo would hold the thread's key, so every retry would get it back."""
        mock_deps.create.return_value = _todo_response()
        watch.register.side_effect = [None, SubscriptionError("could not register")]

        with pytest.raises(SubscriptionError):
            await TrackedTodoService.create_tracked_todo(USER_ID, "Reply", external_ref=_THREAD)

        watch.delete.assert_awaited_once_with(TODO_ID, USER_ID)

    async def test_a_rollback_that_fails_still_raises_the_watch_error(
        self, mock_repo, mock_deps, watch
    ):
        """The watch error is the one the caller can act on; the failed delete rides along on it."""
        mock_deps.create.return_value = _todo_response()
        watch.register.side_effect = SubscriptionError("could not register")
        watch.delete.side_effect = RuntimeError("mongo down")

        with patch(f"{_MOD}.log") as log_mock, pytest.raises(SubscriptionError) as raised:
            await TrackedTodoService.create_tracked_todo(USER_ID, "Reply", external_ref=_THREAD)

        assert str(raised.value) == "could not register"
        assert raised.value.__notes__ == [
            f"Deleting the unwatched todo {TODO_ID} failed too: RuntimeError('mongo down')"
        ]
        log_mock.error.assert_called_once_with(
            "tracked_todo.unwatched_discard_failed",
            todo_id=TODO_ID,
            user_id=USER_ID,
            error="mongo down",
            error_type="RuntimeError",
        )


class TestCreateTrackedTodo:
    async def test_activity_in_the_initial_canvas_is_moved_to_activity_md(
        self, mock_repo, mock_deps
    ):
        """Seen with a real model: it still composes an Activity Log section inside initial_canvas; the split at create time keeps canvas.md a recall doc without waiting for the sweep."""
        mock_deps.create.return_value = _todo_response()
        initial = (
            "# T\n\n## Key Details\n- Thread: NW-4471\n\n## Current State\nWaiting.\n\n"
            "## Activity Log\n- 2026-09-12: Tracked todo created.\n\n## Learnings\n"
        )

        await TrackedTodoService.create_tracked_todo(
            USER_ID, "Prepare Q3 report", initial_canvas=initial
        )

        update = mock_repo.update.await_args.kwargs["update"]
        assert "## Activity Log" not in update.canvas_content
        assert "- Thread: NW-4471" in update.canvas_content
        assert update.activity_content.startswith("- 2026-09-12: Tracked todo created.")
        assert update.activity_content.endswith("[created]")
        assert "Tracked todo created" in mock_deps.store.await_args.kwargs["canvas_content"]

    async def test_activity_and_embedding_are_joined_with_a_blank_line(self, mock_repo, mock_deps):
        """The moved activity, creation marker, and embedding text are separate paragraphs joined by a blank line; any other joiner welds them into one line the append-only parser can no longer read."""
        mock_deps.create.return_value = _todo_response()
        fixed = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
        initial = "# T\n\n## Activity Log\n- did x\n\n## Learnings\n"

        with (
            patch("app.services.todo_activity.datetime") as m_dt,
            patch(f"{_MOD}.datetime") as m_now,
        ):
            m_dt.now.return_value = fixed
            m_now.now.return_value = fixed
            await TrackedTodoService.create_tracked_todo(
                USER_ID, "Prepare Q3 report", initial_canvas=initial
            )

        update = mock_repo.update.await_args.kwargs["update"]
        assert update.activity_content == "- did x\n\n- 2026-09-13T12:00:00+00:00 [created]"
        assert mock_deps.store.await_args.kwargs["canvas_content"] == (
            f"{update.canvas_content}\n\n- did x\n\n- 2026-09-13T12:00:00+00:00 [created]"
        )

    async def test_the_creation_entry_names_its_conversation_at_the_creation_time(
        self, mock_repo, mock_deps
    ):
        mock_deps.create.return_value = _todo_response()
        fixed = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)

        with patch(f"{_MOD}.datetime") as m_now:
            m_now.now.return_value = fixed
            await TrackedTodoService.create_tracked_todo(
                USER_ID, "Prepare Q3 report", source_conversation_id="0123abcd-ffff-4444"
            )

        assert mock_repo.update.await_args.kwargs["update"].activity_content == (
            "- 2026-09-13T12:00:00+00:00 [created] from conversation 0123abcd"
        )

    @pytest.mark.regression
    async def test_the_schedule_is_saved_with_the_insert(self, mock_repo, mock_deps):
        """A schedule written after the insert could fail and leave the todo half-made for a retry to duplicate."""
        mock_deps.create.return_value = _todo_response()
        at = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
        due = datetime(2026, 10, 2, 17, 0, tzinfo=UTC)
        expires = datetime(2026, 10, 9, 0, 0, tzinfo=UTC)
        schedule = TodoUpdate(scheduled_at=at, recurrence="daily", due_date=due, expires_at=expires)

        await TrackedTodoService.create_tracked_todo(
            USER_ID, "Prepare Q3 report", schedule=schedule
        )

        inserted: TodoModel = mock_deps.create.call_args.args[0]
        assert (inserted.scheduled_at, inserted.recurrence) == (at, "daily")
        assert (inserted.due_date, inserted.expires_at) == (due, expires)
        assert mock_repo.update.await_args.kwargs["update"].model_fields_set.isdisjoint(
            {"scheduled_at", "recurrence", "due_date", "expires_at"}
        )

    @pytest.mark.parametrize(
        ("conversation_id", "actor"),
        [("00f7c88f-4ac1-4169", "GAIA in conversation 00f7c88f"), (None, "GAIA")],
        ids=["from-a-conversation", "outside-a-conversation"],
    )
    async def test_the_schedule_is_on_the_timeline_naming_who_set_it(
        self, mock_repo, mock_deps, conversation_id, actor
    ):
        mock_deps.create.return_value = _todo_response()
        fixed = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
        due = datetime(2026, 10, 2, 17, 0, tzinfo=UTC)

        with patch(f"{_MOD}.datetime") as m_now:
            m_now.now.return_value = fixed
            await TrackedTodoService.create_tracked_todo(
                USER_ID,
                "Prepare Q3 report",
                source_conversation_id=conversation_id,
                schedule=TodoUpdate(due_date=due),
            )

        activity = mock_repo.update.await_args.kwargs["update"].activity_content
        assert activity.splitlines()[-1] == (
            f"- 2026-09-13T12:00:00+00:00 [due_date_changed] due {due.isoformat()}, by {actor}"
        )
        assert activity.count("\n") == 1  # the creation marker, then the due date

    async def test_an_initial_canvas_missing_sections_gets_them(self, mock_repo, mock_deps):
        """A canvas a later edit would refuse for its shape must not be created in that shape."""
        mock_deps.create.return_value = _todo_response()

        await TrackedTodoService.create_tracked_todo(
            USER_ID, "Prepare Q3 report", initial_canvas="# T\n\n## Key Details\nk\n"
        )

        canvas = mock_repo.update.await_args.kwargs["update"].canvas_content
        for section in ("## Current State", "## Context", "## Learnings"):
            assert canvas.count(section) == 1

    async def test_a_clean_initial_canvas_sets_no_activity(self, mock_repo, mock_deps):
        mock_deps.create.return_value = _todo_response()

        await TrackedTodoService.create_tracked_todo(
            USER_ID, "Prepare Q3 report", initial_canvas="# T\n\n## Key Details\nk\n"
        )

        update = mock_repo.update.await_args.kwargs["update"]
        assert update.canvas_content.startswith("# T\n\n## Standing rules\n\n## Key Details\nk\n")
        assert update.activity_content.count("\n") == 0  # only the creation marker

    async def test_creates_with_template_canvas_and_indexes(self, mock_repo, mock_deps):
        mock_deps.create.return_value = _todo_response()

        result = await TrackedTodoService.create_tracked_todo(USER_ID, "Prepare Q3 report")

        assert result.id == TODO_ID
        assert result.vfs_path == f"/workspace/gaia-tasks/{TODO_ID}"

        todo_model: TodoModel = mock_deps.create.call_args.args[0]
        assert GAIA_TRACKED_LABEL in todo_model.labels

        update = mock_repo.update.await_args.kwargs["update"]
        assert update.vfs_path == f"/workspace/gaia-tasks/{TODO_ID}"
        assert update.canvas_content == CANVAS_TEMPLATE.format(title="Prepare Q3 report")
        # Lifecycle lives in activity.md; log.md is only the audit of file writes.
        assert update.log_content == "# System Log: Prepare Q3 report\n"
        # activity.md is never empty: an `edit` that appends needs a last line
        # to anchor on, and a real model tried exactly that on a fresh todo.
        assert update.activity_content is not None
        assert update.activity_content.startswith("- 20")
        assert update.activity_content.endswith("[created]")

        mock_deps.store.assert_awaited_once()
        store_kwargs = mock_deps.store.call_args.kwargs
        assert store_kwargs["todo_id"] == TODO_ID
        assert store_kwargs["user_id"] == USER_ID
        assert store_kwargs["title"] == "Prepare Q3 report"
        assert GAIA_TRACKED_LABEL in store_kwargs["labels"]
        mock_deps.sync.assert_called_once_with(USER_ID)

    async def test_uses_provided_initial_canvas(self, mock_repo, mock_deps):
        mock_deps.create.return_value = _todo_response()

        await TrackedTodoService.create_tracked_todo(
            USER_ID, "Prepare Q3 report", initial_canvas="custom canvas"
        )

        assert mock_repo.update.await_args.kwargs["update"].canvas_content.startswith(
            "custom canvas"
        )
        assert mock_deps.store.call_args.kwargs["canvas_content"].startswith("custom canvas")

    async def test_run_results_are_delivered_unless_the_caller_opts_out(self, mock_repo, mock_deps):
        """The default decides whether a new tracked todo ever messages the user at all."""
        mock_deps.create.return_value = _todo_response()

        await TrackedTodoService.create_tracked_todo(USER_ID, "Prepare Q3 report")

        assert mock_deps.create.call_args.args[0].notify_on_run is True

    async def test_a_caller_can_create_a_silent_todo(self, mock_repo, mock_deps):
        mock_deps.create.return_value = _todo_response()

        await TrackedTodoService.create_tracked_todo(
            USER_ID, "Prepare Q3 report", notify_on_run=False
        )

        assert mock_deps.create.call_args.args[0].notify_on_run is False

    async def test_preserves_caller_labels(self, mock_repo, mock_deps):
        mock_deps.create.return_value = _todo_response()

        await TrackedTodoService.create_tracked_todo(
            USER_ID, "Prepare Q3 report", labels=["work", "finance"]
        )

        todo_model: TodoModel = mock_deps.create.call_args.args[0]
        assert set(todo_model.labels) == {"work", "finance", GAIA_TRACKED_LABEL}

    async def test_the_todos_it_references_are_saved_with_it(self, mock_repo, mock_deps):
        mock_deps.create.return_value = _todo_response()

        await TrackedTodoService.create_tracked_todo(
            USER_ID, "Reply to Sam", references=["desk-1", "lease-1"]
        )

        assert mock_deps.create.call_args.args[0].references == ["desk-1", "lease-1"]

    async def test_standing_rules_over_their_cap_save_nothing(self, mock_repo, mock_deps):
        rules = "- " + "x" * todo_constants.STANDING_RULES_MAX_CHARS

        with pytest.raises(todo_errors.CanvasShapeError, match="shorten"):
            await TrackedTodoService.create_tracked_todo(
                USER_ID, "Inbox desk", initial_canvas=f"## Standing rules\n{rules}\n"
            )

        mock_deps.create.assert_not_awaited()
        mock_repo.update.assert_not_awaited()

    def test_a_canvas_refusal_is_a_bad_request_naming_every_problem(self) -> None:
        refused = todo_errors.CanvasShapeError(["shorten the rules", "merge the sections"])

        assert (refused.status_code, refused.code, refused.message) == (
            400,
            "canvas_shape_invalid",
            "initial_canvas breaks the canvas shape: shorten the rules; merge the sections.",
        )


_PARENT_ID = "66f838cc8829054e5f10e401"
_CHILD_ID = "66f838cc8829054e5f10e402"


def _parent(**overrides: object) -> TodoDocument:
    return _todo_doc(id=_PARENT_ID, title="Inbox desk", **overrides)


def _child(**overrides: object) -> TodoDocument:
    fields: dict[str, object] = {"id": _CHILD_ID, "title": "Reply to Sam"}
    fields.update(overrides)
    return _todo_doc(parent_todo_id=_PARENT_ID, **fields)


class TestSubTodoParent:
    """One level deep, same owner, open and tracked: anything else is refused before a write."""

    async def test_an_open_tracked_todo_of_the_same_user_is_accepted(self, mock_repo):
        mock_repo.get.return_value = _parent()

        await require_sub_todo_parent(USER_ID, _PARENT_ID)

        mock_repo.get.assert_awaited_once_with(_PARENT_ID, user_id=USER_ID)

    @pytest.mark.parametrize(
        ("parent", "reason"),
        [
            pytest.param(None, "no open tracked todo", id="missing-or-another-users"),
            pytest.param(_todo_doc(id=_PARENT_ID, completed=True), "is completed", id="completed"),
            pytest.param(
                _todo_doc(id=_PARENT_ID, labels=["work"]), "not a tracked todo", id="untracked"
            ),
            pytest.param(
                _todo_doc(id=_PARENT_ID, parent_todo_id=_CHILD_ID),
                "itself a sub-todo",
                id="grandchild",
            ),
        ],
    )
    async def test_an_unusable_parent_is_refused_with_the_reason(self, mock_repo, parent, reason):
        mock_repo.get.return_value = parent

        with pytest.raises(SubTodoParentError, match=reason):
            await require_sub_todo_parent(USER_ID, _PARENT_ID)

    async def test_a_malformed_id_is_refused_without_a_lookup(self, mock_repo):
        with pytest.raises(SubTodoParentError, match="no open tracked todo"):
            await require_sub_todo_parent(USER_ID, "not-an-id")

        mock_repo.get.assert_not_awaited()

    async def test_a_todo_cannot_be_its_own_parent(self, mock_repo):
        mock_repo.get.return_value = _parent()

        with pytest.raises(SubTodoParentError) as refused:
            await require_sub_todo_parent(USER_ID, _PARENT_ID, child_id=_PARENT_ID)

        assert refused.value.message == "A todo cannot be its own parent."
        assert refused.value.status_code == HTTPStatus.BAD_REQUEST
        assert refused.value.code == "sub_todo_parent_invalid"

    async def test_a_todo_with_sub_todos_cannot_become_one(self, mock_repo):
        mock_repo.get.return_value = _parent()
        mock_repo.find_sub_todos.return_value = [_child()]

        with pytest.raises(SubTodoParentError, match="has sub-todos of its own"):
            await require_sub_todo_parent(USER_ID, _PARENT_ID, child_id=TODO_ID)

        mock_repo.find_sub_todos.assert_awaited_once_with(USER_ID, [TODO_ID])


class TestCreateSubTodo:
    async def test_the_parent_reaches_the_insert(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _parent()
        mock_deps.create.return_value = _todo_response()

        await TrackedTodoService.create_tracked_todo(
            USER_ID, "Reply to Sam", parent_todo_id=_PARENT_ID
        )

        assert mock_deps.create.await_args.kwargs["parent_todo_id"] == _PARENT_ID
        mock_repo.get.assert_awaited_once_with(_PARENT_ID, user_id=USER_ID)

    async def test_a_sub_todo_reports_to_its_parent_instead_of_the_user_by_default(
        self, mock_repo, mock_deps
    ):
        mock_repo.get.return_value = _parent()
        mock_deps.create.return_value = _todo_response()

        await TrackedTodoService.create_tracked_todo(
            USER_ID, "Reply to Sam", parent_todo_id=_PARENT_ID
        )

        assert mock_deps.create.call_args.args[0].notify_on_run is False

    async def test_a_sub_todo_can_still_ask_to_message_the_user(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _parent()
        mock_deps.create.return_value = _todo_response()

        await TrackedTodoService.create_tracked_todo(
            USER_ID, "Reply to Sam", parent_todo_id=_PARENT_ID, notify_on_run=True
        )

        assert mock_deps.create.call_args.args[0].notify_on_run is True

    async def test_an_unusable_parent_creates_nothing(self, mock_repo, mock_deps):
        with pytest.raises(SubTodoParentError):
            await TrackedTodoService.create_tracked_todo(
                USER_ID, "Reply to Sam", parent_todo_id=_PARENT_ID
            )

        mock_deps.create.assert_not_awaited()


class TestCompletingAParentCompletesItsSubTodos:
    """A sub-todo does not outlive its parent: completion goes through the one completion path."""

    async def test_each_open_sub_todo_is_completed_and_stops_watching(self, mock_repo, mock_deps):
        docs = {_PARENT_ID: _parent(), _CHILD_ID: _child()}
        mock_repo.get.side_effect = lambda todo_id, user_id: docs.get(todo_id)
        mock_repo.find_sub_todos.side_effect = lambda user_id, parent_ids: (
            [docs[_CHILD_ID]] if parent_ids == [_PARENT_ID] else []
        )

        async def _write(todo_id: str, *, user_id: str, update: object) -> None:
            docs[todo_id] = docs[todo_id].model_copy(update={"completed": True})

        mock_repo.update.side_effect = _write

        await TrackedTodoService.complete_tracked_todo(_PARENT_ID, USER_ID, "Desk retired")

        completed = [c.args[0] for c in mock_repo.update.await_args_list]
        assert completed == [_CHILD_ID, _PARENT_ID]
        assert [c.args[0] for c in mock_deps.teardown.await_args_list] == [_CHILD_ID, _PARENT_ID]
        child_entry = mock_deps.record.await_args_list[0].args
        assert child_entry == (
            _CHILD_ID,
            USER_ID,
            TodoActivityEvent.COMPLETED,
            'Parent "Inbox desk" completed: Desk retired',
        )
        assert mock_repo.find_sub_todos.await_args_list[0] == call(USER_ID, [_PARENT_ID])

    async def test_a_sub_todo_already_completed_is_left_alone(self, mock_repo, mock_deps):
        docs = {_PARENT_ID: _parent(), _CHILD_ID: _child(completed=True)}
        mock_repo.get.side_effect = lambda todo_id, user_id: docs.get(todo_id)
        mock_repo.find_sub_todos.return_value = [docs[_CHILD_ID]]

        await TrackedTodoService.complete_tracked_todo(_PARENT_ID, USER_ID, "Desk retired")

        assert [c.args[0] for c in mock_repo.update.await_args_list] == [_PARENT_ID]

    async def test_a_sub_todo_created_while_the_parent_closes_is_completed_too(
        self, mock_repo, mock_deps
    ):
        docs = {_PARENT_ID: _parent(), _CHILD_ID: _child()}
        mock_repo.get.side_effect = lambda todo_id, user_id: docs.get(todo_id)
        mock_repo.find_sub_todos.side_effect = [[], [docs[_CHILD_ID]], [], []]

        await TrackedTodoService.complete_tracked_todo(_PARENT_ID, USER_ID, "Desk retired")

        assert [c.args[0] for c in mock_repo.update.await_args_list] == [_PARENT_ID, _CHILD_ID]
        assert mock_deps.record.await_args_list[1] == call(
            _CHILD_ID,
            USER_ID,
            TodoActivityEvent.COMPLETED,
            'Parent "Inbox desk" completed: Desk retired',
        )


class TestACompletedSubTodoReportsToItsParent:
    async def test_the_parents_timeline_gets_the_sub_todos_outcome(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _child()

        await TrackedTodoService.complete_tracked_todo(_CHILD_ID, USER_ID, "Sam confirmed Friday")

        assert mock_deps.record.await_args_list == [
            call(_CHILD_ID, USER_ID, TodoActivityEvent.COMPLETED, "Sam confirmed Friday"),
            call(
                _PARENT_ID,
                USER_ID,
                TodoActivityEvent.SUB_TODO_COMPLETED,
                f'"Reply to Sam" ({_CHILD_ID}): Sam confirmed Friday',
            ),
        ]

    async def test_a_top_level_todo_reports_nowhere(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _parent()

        await TrackedTodoService.complete_tracked_todo(_PARENT_ID, USER_ID, "Desk retired")

        assert mock_deps.record.await_args_list == [
            call(_PARENT_ID, USER_ID, TodoActivityEvent.COMPLETED, "Desk retired")
        ]


class TestTheSummaryCollapsesSubTodos:
    """Sub-todos would push every other todo out of the 15 the agent sees; they fold under a count."""

    async def test_only_top_level_todos_are_listed_each_with_its_open_sub_todo_count(
        self, mock_repo
    ):
        mock_repo.list_active_tracked.return_value = [_parent()]
        mock_repo.count_open_sub_todos.return_value = {_PARENT_ID: 12}

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        mock_repo.list_active_tracked.assert_awaited_once_with(
            USER_ID, limit=ACTIVE_TRACKED_SUMMARY_LIMIT, top_level=True
        )
        mock_repo.count_open_sub_todos.assert_awaited_once_with(USER_ID, [_PARENT_ID])
        assert f"ID: {_PARENT_ID}" in summary
        assert "12 open sub-todos" in summary

    async def test_the_running_sub_todo_is_shown_even_though_sub_todos_are_folded(self, mock_repo):
        mock_repo.list_active_tracked.return_value = [_parent()]
        mock_repo.count_open_sub_todos.return_value = {_PARENT_ID: 1}
        mock_repo.get.return_value = _child()

        summary = await TrackedTodoService.get_active_tracked_summary(
            USER_ID, active_todo_id=_CHILD_ID
        )

        lines = summary.split("\n")
        assert lines[1].startswith('  ⭐ ACTIVE "Reply to Sam"')
        assert f"sub-todo of {_PARENT_ID}" in lines[1]
        mock_repo.get.assert_awaited_once_with(_CHILD_ID, user_id=USER_ID)

    async def test_a_todo_without_sub_todos_shows_no_count(self, mock_repo):
        mock_repo.list_active_tracked.return_value = [_todo_doc()]

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        assert "sub-todo" not in summary
        assert summary.split("\n")[1] == (
            '  "Prepare Q3 report" [work] — 2d old, updated 0d ago'
            " | ID: todo-1 | files: /workspace/gaia-tasks/prepare-q3-report-todo-1/"
        )

    async def test_a_completed_running_todo_is_not_pinned(self, mock_repo):
        mock_repo.list_active_tracked.return_value = [_parent()]
        mock_repo.get.return_value = _child(completed=True)

        summary = await TrackedTodoService.get_active_tracked_summary(
            USER_ID, active_todo_id=_CHILD_ID
        )

        assert [line.split('"')[1] for line in summary.split("\n")[1:]] == ["Inbox desk"]


def test_the_template_opens_on_standing_rules_and_is_already_in_shape() -> None:
    canvas = CANVAS_TEMPLATE.format(title="Inbox desk")

    assert normalize_canvas(canvas) == (canvas, None)
    assert re.findall(r"^## (.+)$", canvas, re.MULTILINE) == list(CANVAS_SECTIONS)


class TestStartingCanvas:
    def test_without_rules_it_is_the_template(self) -> None:
        assert starting_canvas("Inbox desk") == CANVAS_TEMPLATE.format(title="Inbox desk")

    def test_rules_open_the_standing_rules_section_under_its_comment_in_order(self) -> None:
        template = CANVAS_TEMPLATE.format(title="Inbox desk")

        canvas = starting_canvas("Inbox desk", ["Brief me by 9", "Never send a draft"])

        assert canvas == template.replace(
            "-->\n\n## Key Details",
            "-->\n- Brief me by 9\n- Never send a draft\n\n## Key Details",
            1,
        )
        assert normalize_canvas(canvas) == (canvas, None)


class TestCompleteTrackedTodo:
    async def test_false_for_missing_todo(self, mock_repo, mock_deps):
        assert await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done") is False
        mock_deps.record.assert_not_awaited()

    async def test_idempotent_for_already_completed(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc(completed=True)

        assert await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done") is True
        mock_deps.record.assert_not_awaited()
        mock_repo.update.assert_not_awaited()

    async def test_appends_log_marks_completed_and_archives_path(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc()

        ok = await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "Wrapped it up")

        assert ok is True
        mock_deps.record.assert_awaited_once_with(
            TODO_ID, USER_ID, TodoActivityEvent.COMPLETED, "Wrapped it up"
        )

        update = mock_repo.update.await_args.kwargs["update"]
        assert update.completed is True
        assert update.completed_at is not None
        assert update.vfs_path == f"/workspace/gaia-tasks/archive/{TODO_ID}"
        mock_deps.mark.assert_awaited_once_with(TODO_ID)
        mock_deps.sync.assert_called_once_with(USER_ID)

    async def test_completion_stops_the_todo_watching(self, mock_repo, mock_deps):
        # Teardown lives inside completion rather than at its callers (tool, sweep,
        # worker) so no completion path can forget it and strand a live trigger.
        mock_repo.get.return_value = _todo_doc()

        await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done")

        mock_deps.teardown.assert_awaited_once_with(TODO_ID, USER_ID, reason="completed")

    async def test_an_already_completed_todo_does_not_tear_down_again(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc(completed=True)

        await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done")

        mock_deps.teardown.assert_not_awaited()

    async def test_missing_vfs_path_falls_back_to_derived_workspace_label(
        self, mock_repo: MagicMock, mock_deps: SimpleNamespace
    ) -> None:
        """A doc with no stored label must get the derived /workspace-scoped one — never None, never derived from the wrong id."""
        mock_repo.get.return_value = _todo_doc(vfs_path=None)

        ok = await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done")

        assert ok is True
        update = mock_repo.update.await_args.kwargs["update"]
        assert update.vfs_path == f"/workspace/gaia-tasks/archive/{TODO_ID}"

    async def test_legacy_user_scoped_label_is_healed_on_completion(
        self, mock_repo: MagicMock, mock_deps: SimpleNamespace
    ) -> None:
        """A doc still storing the host-side /users/<uid> label must not have it persisted back on completion."""
        mock_repo.get.return_value = _todo_doc(vfs_path=f"/users/{USER_ID}/todos/{TODO_ID}")

        ok = await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done")

        assert ok is True
        update = mock_repo.update.await_args.kwargs["update"]
        assert update.vfs_path == f"/workspace/gaia-tasks/archive/{TODO_ID}"


class TestGetActiveTrackedSummary:
    async def test_empty_string_without_docs(self, mock_repo):
        assert await TrackedTodoService.get_active_tracked_summary(USER_ID) == ""

    @pytest.mark.regression
    async def test_stored_user_scoped_vfs_path_never_leaks_into_agent_context(
        self, mock_repo: MagicMock, mock_deps: SimpleNamespace
    ) -> None:
        """Old docs store vfs_path as /users/<uid>/todos/<id> — that host-side path must never reach the LLM."""
        stale_doc = _todo_doc(vfs_path=f"/users/{USER_ID}/todos/{TODO_ID}")
        mock_repo.list_active_tracked.return_value = [stale_doc]

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        assert USER_ID not in summary
        assert "/users/" not in summary

    async def test_summary_names_the_absolute_notes_folder(self, mock_repo):
        """A real model read gaia-tasks/<folder>/canvas.md relative and got file not found before retrying with the absolute path."""
        mock_repo.list_active_tracked.return_value = [
            _todo_doc(id="66f838cc8829054e5f10e407", title="Fix the thing")
        ]

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        assert "files: /workspace/gaia-tasks/fix-the-thing-5f10e407/" in summary

    async def test_renders_summary_lines(self, mock_repo):
        mock_repo.list_active_tracked.return_value = [_todo_doc()]

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        lines = summary.split("\n")
        assert lines[0] == "ACTIVE TRACKED TODOS:"
        assert '"Prepare Q3 report" [work]' in lines[1]
        assert "ID: todo-1" in lines[1]
        assert "VFS" not in lines[1]
        assert USER_ID not in lines[1]
        assert lines[1].endswith("2d old, updated 0d ago") or "d old" in lines[1]

    async def test_active_todo_pinned_with_star(self, mock_repo):
        docs = [
            _todo_doc(id="todo-2", title="Second"),
            _todo_doc(id="todo-3", title="Third"),
        ]
        mock_repo.list_active_tracked.return_value = docs

        summary = await TrackedTodoService.get_active_tracked_summary(
            USER_ID, active_todo_id="todo-3"
        )

        lines = summary.split("\n")
        assert lines[1].startswith('  ⭐ ACTIVE "Third"')
        assert lines[2].startswith('  "Second"')

    async def test_due_and_overdue_suffixes(self, mock_repo):
        now = datetime.now(UTC)
        docs = [
            _todo_doc(id="todo-due", title="Due soon", due_date=now + timedelta(days=3, hours=1)),
            _todo_doc(id="todo-late", title="Late", due_date=now - timedelta(days=3, hours=23)),
        ]
        mock_repo.list_active_tracked.return_value = docs

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        assert " due(3d)" in summary.split("\n")[1]
        assert " OVERDUE(4d)" in summary.split("\n")[2]


class TestSystemLog:
    async def test_appends_formatted_entry(self, mock_repo, mock_deps):
        await TrackedTodoService.system_log(TODO_ID, USER_ID, "rescheduled", "Retry at 9am")

        entry = mock_deps.append_log.await_args.args[2]
        assert "[rescheduled]" in entry
        assert "Retry at 9am" in entry


class TestScheduleExecution:
    async def test_the_job_is_armed_for_its_occurrence(self, mock_repo, mock_deps):
        pool = AsyncMock()
        mock_deps.pool.return_value = pool
        when = datetime.now(UTC) + timedelta(hours=1)

        ok = await TrackedTodoService.schedule_execution(TODO_ID, when)

        assert ok is True
        # enqueue_worker_job may stamp the caller's _gaia_trace_id kwarg when
        # an ambient wide-event trace is active (the full suite leaks one
        # into this worker) — pin the job contract, not the trace.
        pool.enqueue_job.assert_awaited_once()
        args, kwargs = pool.enqueue_job.await_args
        stamp = occurrence_stamp(when)
        assert args == ("execute_tracked_todo", TODO_ID)
        assert kwargs["scheduled_for"] == stamp
        # One job id per occurrence: a repeat enqueue for it dedupes in ARQ.
        assert kwargs["_job_id"] == f"execute_tracked_todo:{TODO_ID}:{stamp}"
        assert kwargs["_defer_until"] == when

    async def test_a_delayed_fire_keeps_the_occurrence_it_is_for(self, mock_repo, mock_deps):
        pool = AsyncMock()
        mock_deps.pool.return_value = pool
        due = datetime.now(UTC) - timedelta(minutes=5)
        later = datetime.now(UTC) + timedelta(seconds=30)

        await TrackedTodoService.schedule_execution(TODO_ID, due, defer_until=later)

        kwargs = pool.enqueue_job.await_args.kwargs
        assert kwargs["scheduled_for"] == occurrence_stamp(due)
        assert kwargs["_defer_until"] == later

    async def test_a_naive_time_is_stamped_as_the_utc_instant_mongo_stores(
        self, mock_repo, mock_deps
    ):
        pool = AsyncMock()
        mock_deps.pool.return_value = pool
        naive = datetime(2026, 9, 27, 10, 0, 0)

        await TrackedTodoService.schedule_execution(TODO_ID, naive)

        aware = naive.replace(tzinfo=UTC)
        kwargs = pool.enqueue_job.await_args.kwargs
        assert kwargs["scheduled_for"] == occurrence_stamp(aware)
        # A naive defer time would be read as the worker's local time, not UTC.
        assert kwargs["_defer_until"] == aware

    async def test_false_when_the_occurrence_is_already_queued(self, mock_repo, mock_deps):
        pool = AsyncMock()
        pool.enqueue_job.return_value = None
        mock_deps.pool.return_value = pool

        assert await TrackedTodoService.schedule_execution(TODO_ID, datetime.now(UTC)) is False

    async def test_a_queue_failure_propagates(self, mock_repo, mock_deps):
        """Every caller persisted scheduled_at first; hiding the failure hid a todo that never runs."""
        mock_deps.pool.side_effect = RuntimeError("redis down")

        with pytest.raises(RuntimeError, match="redis down"):
            await TrackedTodoService.schedule_execution(TODO_ID, datetime.now(UTC))


class TestArchiveTrackedTodo:
    async def test_completes_with_the_reason_on_the_timeline(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc()

        ok = await TrackedTodoService.archive_tracked_todo(TODO_ID, USER_ID, "expired")

        assert ok is True
        mock_deps.record.assert_awaited_once_with(
            TODO_ID, USER_ID, TodoActivityEvent.COMPLETED, "Auto-archived: expired"
        )

    async def test_false_when_completion_fails(self, mock_repo, mock_deps):
        mock_repo.get.return_value = None

        assert await TrackedTodoService.archive_tracked_todo(TODO_ID, USER_ID, "expired") is False

    async def test_false_when_unexpected_error(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc()
        mock_repo.update.side_effect = RuntimeError("boom")

        assert await TrackedTodoService.archive_tracked_todo(TODO_ID, USER_ID, "expired") is False


class TestSingleton:
    def test_module_singleton_is_an_instance(self):
        assert isinstance(tracked_todo_service, TrackedTodoService)

    def test_priority_default_is_none(self):
        assert Priority.NONE.value == "none"


_CLEAN_CANVAS = (
    "# T\n\n## Standing rules\n\n## Key Details\nk\n\n## Current State\n\n## Context\n\n"
    "## Learnings\n"
)


class TestMigrateLegacyCanvas:
    LEGACY = (
        "# T\n\n## Key Details\nk\n\n## Activity Log\n- did x\n\n"
        "## Timeline\n- 2026-01-02T00:00:00+00:00 second\n- 2026-01-01T00:00:00+00:00 first\n\n"
        "## Learnings\n"
    )

    async def test_legacy_canvas_is_split_into_both_fields(self):
        doc = _todo_doc(canvas_content=self.LEGACY, activity_content=None)
        with patch(
            f"{_MOD}.repair_canvas_and_activity", new_callable=AsyncMock, return_value=True
        ) as write:
            assert await TrackedTodoService.normalize_stored_canvas(doc) is True

        kwargs = write.await_args.kwargs
        assert write.await_args.args == (doc.id, doc.user_id)
        assert kwargs["expected_updated_at"] == doc.updated_at
        assert "## Activity Log" not in kwargs["canvas"]
        assert "## Timeline" not in kwargs["canvas"]
        assert kwargs["activity"].index("first") < kwargs["activity"].index("second")
        assert "did x" in kwargs["activity"]

    async def test_moved_legacy_entries_come_before_existing_activity(self):
        doc = _todo_doc(canvas_content=self.LEGACY, activity_content="- already here")
        with patch(
            f"{_MOD}.repair_canvas_and_activity", new_callable=AsyncMock, return_value=True
        ) as write:
            await TrackedTodoService.normalize_stored_canvas(doc)

        activity = write.await_args.kwargs["activity"]
        assert activity == (
            "- 2026-01-01T00:00:00+00:00 first\n\n- 2026-01-02T00:00:00+00:00 second\n\n"
            "- did x\n\n- already here"
        )

    async def test_clean_canvas_is_not_touched(self):
        doc = _todo_doc(canvas_content=_CLEAN_CANVAS)
        with patch(f"{_MOD}.repair_canvas_and_activity", new_callable=AsyncMock) as write:
            assert await TrackedTodoService.normalize_stored_canvas(doc) is False

        write.assert_not_awaited()

    async def test_empty_canvas_is_not_touched(self):
        doc = _todo_doc(canvas_content=None)
        with patch(f"{_MOD}.repair_canvas_and_activity", new_callable=AsyncMock) as write:
            assert await TrackedTodoService.normalize_stored_canvas(doc) is False

        write.assert_not_awaited()

    async def test_revision_race_retries_once_against_fresh_content(self, mock_repo):
        stale = _todo_doc(canvas_content=self.LEGACY, activity_content=None)
        fresh = _todo_doc(
            canvas_content=self.LEGACY,
            activity_content="- fresh here",
            updated_at=datetime.now(UTC),
        )
        mock_repo.get.return_value = fresh
        with patch(
            f"{_MOD}.repair_canvas_and_activity",
            new_callable=AsyncMock,
            side_effect=[False, True],
        ) as write:
            assert await TrackedTodoService.normalize_stored_canvas(stale) is True

        mock_repo.get.assert_awaited_once_with(stale.id, user_id=stale.user_id)
        assert write.await_count == 2
        assert write.await_args_list[0].args == (stale.id, stale.user_id)
        assert write.await_args_list[1].args == (fresh.id, fresh.user_id)
        assert write.await_args_list[0].kwargs["expected_updated_at"] == stale.updated_at
        assert write.await_args_list[1].kwargs["expected_updated_at"] == fresh.updated_at
        assert write.await_args_list[1].kwargs["canvas"] == _CLEAN_CANVAS
        assert write.await_args_list[1].kwargs["activity"] == (
            "- 2026-01-01T00:00:00+00:00 first\n\n- 2026-01-02T00:00:00+00:00 second\n\n"
            "- did x\n\n- fresh here"
        )

    async def test_fresh_doc_already_clean_skips_retry(self, mock_repo):
        """When the re-read doc has no legacy sections, the migration gives up instead of reporting a write it never made."""
        fresh = _todo_doc(
            canvas_content=_CLEAN_CANVAS,
            updated_at=datetime.now(UTC),
        )
        mock_repo.get.return_value = fresh
        with patch(
            f"{_MOD}.repair_canvas_and_activity", new_callable=AsyncMock, return_value=False
        ) as write:
            assert (
                await TrackedTodoService.normalize_stored_canvas(
                    _todo_doc(canvas_content=self.LEGACY)
                )
                is False
            )

        write.assert_awaited_once()

    async def test_vanished_todo_is_not_retried(self, mock_repo):
        mock_repo.get.return_value = None
        with patch(
            f"{_MOD}.repair_canvas_and_activity", new_callable=AsyncMock, return_value=False
        ) as write:
            assert (
                await TrackedTodoService.normalize_stored_canvas(
                    _todo_doc(canvas_content=self.LEGACY)
                )
                is False
            )

        write.assert_awaited_once()
