"""Unit tests for tracked_todo_service (GAIA working-memory todo lifecycle).

Covers the facet persistence (deliverable / notes / log) + ChromaDB indexing
pipeline, the creation gate's staging invariant, completion/archival, and the
context-summary renderers the agent sees.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.todos import (
    ASSIGNEE_GAIA,
    DELIVERABLE_TEMPLATE,
    FACET_LOG,
    NOTES_TEMPLATE,
)
from app.models.todo_models import (
    ExecutionStatus,
    Priority,
    TodoDocument,
    TodoModel,
    TodoResponse,
    TrackedTodoDraft,
)
from app.services.todos.gaia_todo_lifecycle import TraceabilityError
from app.services.tracked_todo_service import (
    TrackedTodoService,
    tracked_todo_service,
)

_MOD = "app.services.tracked_todo_service"
USER_ID = "507f1f77bcf86cd799439011"
TODO_ID = "todo-1"
SERVES = "the user asked for the Q3 report"
WORKSPACE_LABEL = f"/workspace/gaia-tasks/{TODO_ID}"


def _todo_doc(**overrides: object) -> TodoDocument:
    now = datetime.now(UTC)
    data: dict[str, object] = {
        "id": TODO_ID,
        "user_id": USER_ID,
        "title": "Prepare Q3 report",
        "labels": ["work"],
        "assignee": ASSIGNEE_GAIA,
        "vfs_path": WORKSPACE_LABEL,
        "notes_content": "# Prepare Q3 report\n\n## Key Details\nthread: abc123\n",
        "deliverable_content": "## Output\nthe report",
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
        m.list_active_gaia_for_summary = AsyncMock(return_value=[])
        yield m


@pytest.fixture
def mock_deps():
    """Every seam the service writes through, with the creation gate open."""
    with (
        patch(f"{_MOD}.TodoService.create_todo", new_callable=AsyncMock) as m_create,
        patch(f"{_MOD}.store_canvas_embedding", new_callable=AsyncMock) as m_store,
        patch(f"{_MOD}.mark_canvas_completed", new_callable=AsyncMock) as m_mark,
        patch(f"{_MOD}.update_canvas_embedding", new_callable=AsyncMock) as m_update_emb,
        patch(f"{_MOD}.schedule_gaia_tasks_sync", new_callable=MagicMock) as m_sync,
        patch(f"{_MOD}.append_facet", new_callable=AsyncMock) as m_append,
        patch(f"{_MOD}.track", new_callable=MagicMock) as m_track,
        patch(f"{_MOD}.lifecycle.gate_creation", new_callable=AsyncMock) as m_gate,
        patch(f"{_MOD}.lifecycle.enforce_budget_post_insert", new_callable=AsyncMock) as m_budget,
        patch(f"{_MOD}.lifecycle.mark_execution_status", new_callable=AsyncMock) as m_status,
        patch(f"{_MOD}.lifecycle.schedule_execution", new_callable=AsyncMock) as m_schedule,
        patch(f"{_MOD}.lifecycle.reschedule_execution", new_callable=AsyncMock) as m_reschedule,
        patch(f"{_MOD}.lifecycle.system_log", new_callable=AsyncMock) as m_system_log,
        patch(
            f"{_MOD}.lifecycle.get_rejection_strikes_summary",
            new_callable=AsyncMock,
            return_value="",
        ) as m_strikes,
        patch(f"{_MOD}.teardown_subscriptions", new_callable=AsyncMock) as m_teardown,
    ):
        m_gate.return_value = (SERVES, ExecutionStatus.QUEUED)
        yield SimpleNamespace(
            create=m_create,
            store=m_store,
            mark=m_mark,
            update_emb=m_update_emb,
            sync=m_sync,
            append=m_append,
            track=m_track,
            gate=m_gate,
            budget=m_budget,
            status=m_status,
            schedule=m_schedule,
            reschedule=m_reschedule,
            system_log=m_system_log,
            strikes=m_strikes,
            teardown=m_teardown,
        )


async def _create(**kwargs: object) -> TodoResponse:
    """Create with the required gate arguments filled in."""
    params: dict[str, object] = {
        "title": "Prepare Q3 report",
        "serves": SERVES,
        "requires_approval": False,
    }
    params.update(kwargs)
    return await TrackedTodoService.create_tracked_todo(USER_ID, TrackedTodoDraft(**params))


class TestCreateTrackedTodo:
    async def test_creates_with_template_facets_and_indexes(self, mock_repo, mock_deps):
        mock_deps.create.return_value = _todo_response()

        result = await _create()

        assert result.id == TODO_ID
        assert result.vfs_path == WORKSPACE_LABEL

        todo_model: TodoModel = mock_deps.create.call_args.args[0]
        assert todo_model.assignee == ASSIGNEE_GAIA
        assert todo_model.execution_status is ExecutionStatus.QUEUED
        assert todo_model.serves == SERVES

        update = mock_repo.update.await_args_list[0].kwargs["update"]
        assert update.vfs_path == WORKSPACE_LABEL
        assert update.deliverable_content == DELIVERABLE_TEMPLATE.format(title="Prepare Q3 report")
        assert update.notes_content == NOTES_TEMPLATE.format(title="Prepare Q3 report")
        assert "[CREATED]" in update.log_content
        assert "Source: agent" in update.log_content

        mock_deps.store.assert_awaited_once()
        store_kwargs = mock_deps.store.call_args.kwargs
        assert store_kwargs["todo_id"] == TODO_ID
        assert store_kwargs["user_id"] == USER_ID
        assert store_kwargs["title"] == "Prepare Q3 report"
        mock_deps.sync.assert_called_once_with(USER_ID)

    async def test_indexes_notes_and_deliverable_but_never_the_log(self, mock_repo, mock_deps):
        """The log facet is audit noise — indexing it would match signals on
        timestamps instead of on the work."""
        mock_deps.create.return_value = _todo_response()

        await _create(initial_notes="notes body", initial_deliverable="deliverable body")

        content = mock_deps.store.call_args.kwargs["content"]
        assert "notes body" in content
        assert "deliverable body" in content
        assert "[CREATED]" not in content

    async def test_uses_provided_initial_facets(self, mock_repo, mock_deps):
        mock_deps.create.return_value = _todo_response()

        await _create(initial_notes="custom notes", initial_deliverable="custom deliverable")

        update = mock_repo.update.await_args_list[0].kwargs["update"]
        assert update.notes_content == "custom notes"
        assert update.deliverable_content == "custom deliverable"

    async def test_persists_the_originating_conversation(self, mock_repo, mock_deps):
        """The run's result is delivered back into the chat the todo came from,
        so the originating conversation id has to reach the doc."""
        mock_deps.create.return_value = _todo_response()

        await _create(source_conversation_id="conv-9")

        update = mock_repo.update.await_args_list[0].kwargs["update"]
        assert update.source_conversation_id == "conv-9"

    async def test_preserves_caller_labels_without_stamping_a_tracked_label(
        self, mock_repo, mock_deps
    ):
        """`assignee == "gaia"` is the discriminator now; a stamped label would
        show as a stray chip on the user's todo."""
        mock_deps.create.return_value = _todo_response()

        await _create(labels=["work", "finance"])

        todo_model: TodoModel = mock_deps.create.call_args.args[0]
        assert todo_model.labels == ["work", "finance"]

    async def test_the_gate_sees_the_draft_verbatim(self, mock_repo, mock_deps):
        """The gate decides traceability, budgets and entry state — a draft field
        that never reaches it is a rule silently not applied."""
        mock_deps.create.return_value = _todo_response()

        await _create(kind="goal")

        mock_deps.gate.assert_awaited_once_with(
            USER_ID, SERVES, False, title="Prepare Q3 report", kind="goal"
        )

    async def test_a_goal_draft_creates_a_goal_lane(self, mock_repo, mock_deps):
        """Goals are exempt from the in-flight budget and skip the day timeline,
        so a goal draft landing as a task changes which rules apply to it."""
        mock_deps.create.return_value = _todo_response()

        await _create(kind="goal")

        todo_model: TodoModel = mock_deps.create.call_args.args[0]
        assert todo_model.kind == "goal"

    async def test_any_other_kind_creates_a_task(self, mock_repo, mock_deps):
        mock_deps.create.return_value = _todo_response()

        await _create(kind="task")

        todo_model: TodoModel = mock_deps.create.call_args.args[0]
        assert todo_model.kind == "task"

    async def test_budget_is_re_enforced_after_the_insert(self, mock_repo, mock_deps):
        mock_deps.create.return_value = _todo_response()

        await _create()

        mock_deps.budget.assert_awaited_once_with(USER_ID, TODO_ID, ExecutionStatus.QUEUED)

    async def test_gate_rejection_propagates_and_creates_nothing(self, mock_repo, mock_deps):
        mock_deps.gate.side_effect = TraceabilityError("no goal named")

        with pytest.raises(TraceabilityError, match="no goal named"):
            await _create(serves="")

        mock_deps.create.assert_not_awaited()

    async def test_queued_todo_executes_immediately(self, mock_repo, mock_deps):
        """Internal work needs no permission: it is scheduled on creation, not
        only when a schedule happens to be attached."""
        mock_deps.create.return_value = _todo_response()

        await _create()

        # The stamped scheduled_at and the enqueued run must be the same instant,
        # for the same todo — a mismatch shows the user a time nothing fires at.
        schedule_write = mock_repo.update.await_args_list[1]
        assert schedule_write.args[0] == TODO_ID
        assert schedule_write.kwargs["user_id"] == USER_ID
        scheduled_at = schedule_write.kwargs["update"].scheduled_at
        assert scheduled_at is not None
        mock_deps.schedule.assert_awaited_once_with(TODO_ID, scheduled_at)

    async def test_auto_execute_false_leaves_the_schedule_to_the_caller(self, mock_repo, mock_deps):
        mock_deps.create.return_value = _todo_response()

        await _create(auto_execute=False)

        mock_deps.schedule.assert_not_awaited()


class TestCreateProposalStagingInvariant:
    """Approving a proposal releases its deliverable verbatim, so the gate
    rejects a proposal that has no finished content to release."""

    @pytest.mark.parametrize("deliverable", [None, "", "   \n  "])
    async def test_proposal_without_a_deliverable_is_rejected(
        self, mock_repo, mock_deps, deliverable
    ):
        """Whitespace is not staged work either — the gate strips before judging."""
        mock_deps.gate.return_value = (SERVES, ExecutionStatus.PROPOSED)

        with pytest.raises(TraceabilityError) as excinfo:
            await _create(requires_approval=True, initial_deliverable=deliverable)

        # The message is the agent's only instruction on how to recover, so its
        # wording is a contract, not decoration.
        assert str(excinfo.value) == (
            "A proposal must carry its staged work: pass `initial_deliverable` "
            "with the exact content approving will release (drafts, list, post). "
            "If the content does not exist yet, create the internal prep todo "
            "first and stage this proposal when the prep run finishes."
        )
        mock_deps.create.assert_not_awaited()

    async def test_proposal_with_unfilled_placeholders_is_rejected(self, mock_repo, mock_deps):
        mock_deps.gate.return_value = (SERVES, ExecutionStatus.PROPOSED)

        with pytest.raises(TraceabilityError) as excinfo:
            await _create(requires_approval=True, initial_deliverable="Hi [Name], we should talk.")

        assert str(excinfo.value) == (
            "A proposal cannot ship template placeholders: the staged "
            "deliverable still has unfilled tokens like [Name] or [industry], so "
            "approving would release literal brackets. Fill every placeholder "
            "with the real value before staging — if you don't have it yet, do "
            "the prep to get it first."
        )
        mock_deps.create.assert_not_awaited()

    async def test_markdown_links_and_checkboxes_are_not_placeholders(self, mock_repo, mock_deps):
        mock_deps.gate.return_value = (SERVES, ExecutionStatus.PROPOSED)
        mock_deps.create.return_value = _todo_response()

        await _create(
            requires_approval=True,
            initial_deliverable="- [x] done\nSee [the docs](https://example.com).",
        )

        mock_deps.create.assert_awaited_once()

    async def test_a_staged_proposal_is_tracked_and_not_auto_executed(self, mock_repo, mock_deps):
        mock_deps.gate.return_value = (SERVES, ExecutionStatus.PROPOSED)
        mock_deps.create.return_value = _todo_response()

        await _create(requires_approval=True, initial_deliverable="Ready to send.")

        mock_deps.schedule.assert_not_awaited()
        # Approve rate is derived from this event, so it has to be attributed to
        # the right user and carry the traceability the gate accepted.
        mock_deps.track.assert_called_once_with(
            USER_ID, "todo_proposed", {"todo_id": TODO_ID, "serves": SERVES}
        )


class TestCompleteTrackedTodo:
    async def test_false_for_missing_todo(self, mock_repo, mock_deps):
        assert await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done") is False
        mock_deps.append.assert_not_awaited()

    async def test_idempotent_for_already_completed(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc(completed=True)

        assert await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done") is True
        mock_deps.append.assert_not_awaited()
        mock_repo.update.assert_not_awaited()

    async def test_appends_log_marks_completed_and_archives_path(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc()

        ok = await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "Wrapped it up")

        assert ok is True
        todo_id, user_id, facet, entry = mock_deps.append.await_args.args
        assert (todo_id, user_id, facet) == (TODO_ID, USER_ID, FACET_LOG)
        assert "[COMPLETED]" in entry
        assert "Wrapped it up" in entry

        update = mock_repo.update.await_args.kwargs["update"]
        assert update.completed is True
        assert update.completed_at is not None
        assert update.vfs_path == f"/workspace/gaia-tasks/archive/{TODO_ID}"
        mock_deps.status.assert_awaited_once_with(TODO_ID, USER_ID, ExecutionStatus.DONE)
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
        """A doc with no stored label must get the derived /workspace-scoped one —
        never None, and never a label derived from the wrong id."""
        mock_repo.get.return_value = _todo_doc(vfs_path=None)

        ok = await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done")

        assert ok is True
        update = mock_repo.update.await_args.kwargs["update"]
        assert update.vfs_path == f"/workspace/gaia-tasks/archive/{TODO_ID}"

    async def test_legacy_user_scoped_label_is_healed_on_completion(
        self, mock_repo: MagicMock, mock_deps: SimpleNamespace
    ) -> None:
        """A doc still storing the host-side /users/<uid> label must not have it
        persisted back on completion — the derived archive label replaces it."""
        mock_repo.get.return_value = _todo_doc(vfs_path=f"/users/{USER_ID}/todos/{TODO_ID}")

        ok = await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done")

        assert ok is True
        update = mock_repo.update.await_args.kwargs["update"]
        assert update.vfs_path == f"/workspace/gaia-tasks/archive/{TODO_ID}"


class TestGetActiveTrackedSummary:
    async def test_empty_string_without_docs(self, mock_repo, mock_deps):
        assert await TrackedTodoService.get_active_tracked_summary(USER_ID) == ""

    async def test_reads_this_user_within_the_context_budget(self, mock_repo, mock_deps):
        """The summary is injected into every prompt, so the row cap is a token
        budget — and both reads must be scoped to the calling user."""
        await TrackedTodoService.get_active_tracked_summary(USER_ID)

        mock_repo.list_active_gaia_for_summary.assert_awaited_once_with(USER_ID, limit=15)
        mock_deps.strikes.assert_awaited_once_with(USER_ID)

    async def test_strikes_are_surfaced_even_with_no_active_todos(self, mock_repo, mock_deps):
        mock_deps.strikes.return_value = "Rejected work: outreach (3x, BLOCKED)"

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        assert summary == "\nRejected work: outreach (3x, BLOCKED)"

    async def test_strikes_are_appended_after_the_todo_lines(self, mock_repo, mock_deps):
        mock_repo.list_active_gaia_for_summary.return_value = [_todo_doc()]
        mock_deps.strikes.return_value = "Rejected work: outreach (3x, BLOCKED)"

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        assert summary.split("\n")[-1] == "Rejected work: outreach (3x, BLOCKED)"

    @pytest.mark.regression
    async def test_stored_user_scoped_vfs_path_never_leaks_into_agent_context(
        self, mock_repo: MagicMock, mock_deps: SimpleNamespace
    ) -> None:
        """Old docs store vfs_path as /users/<uid>/todos/<id> — that host-side
        path must never reach the LLM, which only knows /workspace-scoped paths."""
        stale_doc = _todo_doc(vfs_path=f"/users/{USER_ID}/todos/{TODO_ID}")
        mock_repo.list_active_gaia_for_summary.return_value = [stale_doc]

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        assert USER_ID not in summary
        assert "/users/" not in summary

    async def test_renders_summary_lines(self, mock_repo, mock_deps):
        mock_repo.list_active_gaia_for_summary.return_value = [
            _todo_doc(execution_status=ExecutionStatus.QUEUED)
        ]

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        lines = summary.split("\n")
        assert lines[0] == "ACTIVE TRACKED TODOS:"
        assert '"Prepare Q3 report" [work]' in lines[1]
        assert "state: queued" in lines[1]
        assert "ID: todo-1" in lines[1]
        assert f"VFS: {WORKSPACE_LABEL}" in lines[1]
        assert "d old" in lines[1]

    async def test_multiple_labels_render_as_one_comma_separated_chip_list(
        self, mock_repo, mock_deps
    ):
        mock_repo.list_active_gaia_for_summary.return_value = [
            _todo_doc(labels=["work", "finance", "q3"])
        ]

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        assert '"Prepare Q3 report" [work, finance, q3] —' in summary.split("\n")[1]

    async def test_a_bare_todo_renders_without_empty_label_or_state_sections(
        self, mock_repo, mock_deps
    ):
        """A todo with no labels and no execution status must render the plain
        line — an empty section leaking a stray marker costs prompt tokens and
        teaches the agent a state that does not exist."""
        now = datetime.now(UTC)
        mock_repo.list_active_gaia_for_summary.return_value = [
            _todo_doc(
                labels=[],
                execution_status=None,
                created_at=now - timedelta(days=2),
                updated_at=now,
            )
        ]

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        assert summary.split("\n")[1] == (
            '  "Prepare Q3 report" — 2d old, updated 0d ago'
            f" | ID: {TODO_ID} | VFS: {WORKSPACE_LABEL}"
        )

    async def test_a_blocked_todo_shows_the_question_it_is_waiting_on(self, mock_repo, mock_deps):
        """A chat reply like "yes, use the second one" is only actionable if the
        agent can see which question it answers — and which state it answers in."""
        mock_repo.list_active_gaia_for_summary.return_value = [
            _todo_doc(
                execution_status=ExecutionStatus.NEEDS_YOU,
                blocker_question="Which vendor should I book?",
            )
        ]

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        assert ' | state: needs_you | waiting on user: "Which vendor should I book?"' in summary

    async def test_a_stale_blocker_question_is_not_shown_once_the_todo_is_unblocked(
        self, mock_repo, mock_deps
    ):
        """The question survives on the doc after it is answered; only the
        NEEDS_YOU state means the agent is actually waiting on a reply."""
        mock_repo.list_active_gaia_for_summary.return_value = [
            _todo_doc(
                execution_status=ExecutionStatus.QUEUED,
                blocker_question="Which vendor should I book?",
            )
        ]

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        assert "waiting on user" not in summary
        assert " | state: queued |" in summary

    async def test_active_todo_pinned_with_star(self, mock_repo, mock_deps):
        docs = [
            _todo_doc(id="todo-2", title="Second"),
            _todo_doc(id="todo-3", title="Third"),
        ]
        mock_repo.list_active_gaia_for_summary.return_value = docs

        summary = await TrackedTodoService.get_active_tracked_summary(
            USER_ID, active_todo_id="todo-3"
        )

        lines = summary.split("\n")
        assert lines[1].startswith('  ⭐ ACTIVE "Third"')
        assert lines[2].startswith('  "Second"')

    async def test_due_and_overdue_suffixes(self, mock_repo, mock_deps):
        now = datetime.now(UTC)
        docs = [
            _todo_doc(id="todo-due", title="Due soon", due_date=now + timedelta(days=3, hours=1)),
            _todo_doc(id="todo-late", title="Late", due_date=now - timedelta(days=3, hours=23)),
        ]
        mock_repo.list_active_gaia_for_summary.return_value = docs

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        assert " due(3d)" in summary.split("\n")[1]
        assert " OVERDUE(4d)" in summary.split("\n")[2]


class TestAppendActivityMarker:
    async def test_appends_to_the_log_facet(self, mock_repo, mock_deps):
        mock_deps.append.return_value = True

        assert await TrackedTodoService.append_activity_marker(TODO_ID, USER_ID, "step") is True
        todo_id, user_id, facet, line = mock_deps.append.await_args.args
        assert (todo_id, user_id, facet, line) == (TODO_ID, USER_ID, FACET_LOG, "- step")

    async def test_keeps_an_already_bulleted_entry_as_is(self, mock_repo, mock_deps):
        mock_deps.append.return_value = True

        await TrackedTodoService.append_activity_marker(TODO_ID, USER_ID, "- step")

        assert mock_deps.append.await_args.args[3] == "- step"

    async def test_false_when_the_write_fails(self, mock_repo, mock_deps):
        mock_deps.append.side_effect = RuntimeError("mongo down")

        assert await TrackedTodoService.append_activity_marker(TODO_ID, USER_ID, "step") is False

    async def test_a_swallowed_write_failure_still_names_itself_and_its_cause(
        self, mock_repo, mock_deps
    ):
        """This is the one path that returns False instead of raising, so the
        warning is the only trace of a lost paper trail — it has to carry the
        todo and the real error, not a placeholder."""
        mock_deps.append.side_effect = RuntimeError("mongo down")

        with patch(f"{_MOD}.log") as mock_log:
            await TrackedTodoService.append_activity_marker(TODO_ID, USER_ID, "step")

        mock_log.warning.assert_called_once_with(
            "tracked_todo.activity_marker_write_failed",
            todo_id=TODO_ID,
            error="mongo down",
        )


class TestSystemLog:
    async def test_delegates_to_the_lifecycle_audit_writer(self, mock_repo, mock_deps):
        await TrackedTodoService.system_log(TODO_ID, USER_ID, "rescheduled", "Retry at 9am")

        mock_deps.system_log.assert_awaited_once_with(
            TODO_ID, USER_ID, "rescheduled", "Retry at 9am"
        )


class TestReindexCanvas:
    async def test_false_for_missing_todo(self, mock_repo, mock_deps):
        assert await TrackedTodoService.reindex_canvas(TODO_ID, USER_ID) is False
        mock_deps.update_emb.assert_not_awaited()

    async def test_false_without_any_indexable_facet(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc(notes_content=None, deliverable_content=None)

        assert await TrackedTodoService.reindex_canvas(TODO_ID, USER_ID) is False

    async def test_reindexes_notes_and_deliverable(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc()
        mock_deps.update_emb.return_value = True

        ok = await TrackedTodoService.reindex_canvas(TODO_ID, USER_ID)

        assert ok is True
        kwargs = mock_deps.update_emb.call_args.kwargs
        assert kwargs["todo_id"] == TODO_ID
        assert kwargs["user_id"] == USER_ID
        assert kwargs["title"] == "Prepare Q3 report"
        assert kwargs["labels"] == ["work"]
        assert kwargs["content"] == (
            "# Prepare Q3 report\n\n## Key Details\nthread: abc123\n\n\n## Output\nthe report"
        )

    async def test_a_blank_facet_is_left_out_of_the_embedding(self, mock_repo, mock_deps):
        """A whitespace-only facet carries no signal — indexing it would prepend
        blank lines to every embedding for that todo."""
        mock_repo.get.return_value = _todo_doc(
            notes_content="   \n  ", deliverable_content="## Output\nthe report"
        )
        mock_deps.update_emb.return_value = True

        await TrackedTodoService.reindex_canvas(TODO_ID, USER_ID)

        assert mock_deps.update_emb.call_args.kwargs["content"] == "## Output\nthe report"

    async def test_a_legacy_proposal_indexes_its_canvas_as_both_facets(self, mock_repo, mock_deps):
        """Pre-facet proposals stored their staged content in canvas_content; the
        deliverable fallback is what keeps them searchable until the backfill."""
        mock_repo.get.return_value = _todo_doc(
            notes_content=None,
            deliverable_content=None,
            canvas_content="legacy body",
            execution_status=ExecutionStatus.PROPOSED,
        )
        mock_deps.update_emb.return_value = True

        await TrackedTodoService.reindex_canvas(TODO_ID, USER_ID)

        assert mock_deps.update_emb.call_args.kwargs["content"] == "legacy body\n\nlegacy body"

    async def test_a_non_proposal_never_reads_the_legacy_canvas_as_a_deliverable(
        self, mock_repo, mock_deps
    ):
        """Only a proposal's old canvas was staged output; for anything else it
        was working memory, so it indexes as notes alone."""
        mock_repo.get.return_value = _todo_doc(
            notes_content=None,
            deliverable_content=None,
            canvas_content="legacy body",
            execution_status=ExecutionStatus.QUEUED,
        )
        mock_deps.update_emb.return_value = True

        await TrackedTodoService.reindex_canvas(TODO_ID, USER_ID)

        assert mock_deps.update_emb.call_args.kwargs["content"] == "legacy body"

    async def test_the_log_facet_is_never_indexed(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc(log_content="## 2026 [CREATED]\n- audit line\n")
        mock_deps.update_emb.return_value = True

        await TrackedTodoService.reindex_canvas(TODO_ID, USER_ID)

        assert "audit line" not in mock_deps.update_emb.call_args.kwargs["content"]

    async def test_propagates_embedding_failure(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc()
        mock_deps.update_emb.return_value = False

        assert await TrackedTodoService.reindex_canvas(TODO_ID, USER_ID) is False


class TestScheduleExecution:
    async def test_delegates_to_the_lifecycle_scheduler(self, mock_repo, mock_deps):
        mock_deps.schedule.return_value = True
        when = datetime.now(UTC) + timedelta(hours=1)

        assert await TrackedTodoService.schedule_execution(TODO_ID, when) is True
        mock_deps.schedule.assert_awaited_once_with(TODO_ID, when)

    async def test_propagates_a_scheduling_failure(self, mock_repo, mock_deps):
        mock_deps.schedule.return_value = False

        assert await TrackedTodoService.schedule_execution(TODO_ID, datetime.now(UTC)) is False

    async def test_reschedule_delegates_to_the_lifecycle_rescheduler(self, mock_repo, mock_deps):
        mock_deps.reschedule.return_value = True
        when = datetime.now(UTC) + timedelta(hours=2)

        assert await TrackedTodoService.reschedule_execution(TODO_ID, when) is True
        mock_deps.reschedule.assert_awaited_once_with(TODO_ID, when)


class TestArchiveTrackedTodo:
    async def test_logs_reason_and_completes(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc()

        ok = await TrackedTodoService.archive_tracked_todo(TODO_ID, USER_ID, "expired")

        assert ok is True
        assert mock_deps.system_log.await_args.args[2] == "auto_archived"
        assert "expired" in mock_deps.system_log.await_args.args[3]

    async def test_false_when_completion_fails(self, mock_repo, mock_deps):
        mock_repo.get.return_value = None

        assert await TrackedTodoService.archive_tracked_todo(TODO_ID, USER_ID, "expired") is False

    async def test_false_when_unexpected_error(self, mock_repo, mock_deps):
        mock_deps.system_log.side_effect = RuntimeError("boom")

        assert await TrackedTodoService.archive_tracked_todo(TODO_ID, USER_ID, "expired") is False


class TestSingleton:
    def test_module_singleton_is_an_instance(self):
        assert isinstance(tracked_todo_service, TrackedTodoService)

    def test_priority_default_is_none(self):
        assert Priority.NONE.value == "none"
