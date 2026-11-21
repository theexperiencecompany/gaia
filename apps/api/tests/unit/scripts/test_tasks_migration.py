"""The parts of the tasks migration where one wrong byte loses data: ids, playbook validity, activity cuts."""

from datetime import UTC, datetime

from bson import ObjectId
import pytest
from scripts.tasks_migration.legacy import (
    LegacyPlaybook,
    LegacyStep,
    LegacyTodo,
    LegacyWorkflow,
    legacy_workflow_hash,
)
from scripts.tasks_migration.transform import (
    Unmappable,
    playbook_for_task,
    runs_from_activity,
    slice_activity,
    task_from_todo,
)

from app.constants.tasks import TASK_ID_PATTERN, TaskRunKind, TaskRunStatus
from app.models.task_models import new_task_id
from app.models.workflow_models import WorkflowStep
from app.services.tasks.body_hash import task_body_hash
from app.services.workflow.playbook.workflow_hash import workflow_hash

pytestmark = pytest.mark.unit

AT = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
STEPS = [{"id": "s1", "title": "Fetch mail", "category": "gmail", "description": "Read today's"}]


def _workflow(prompt: str = "Summarise my inbox.", **fields: object) -> LegacyWorkflow:
    return LegacyWorkflow.model_validate(
        {
            "_id": "wf_0123456789ab",
            "user_id": "u1",
            "title": "Inbox summary",
            "prompt": prompt,
            "steps": STEPS,
            "trigger_config": {"type": "schedule", "cron_expression": "0 8 * * *"},
            "created_at": AT,
            "updated_at": AT,
            **fields,
        }
    )


def _playbook(workflow_hash_value: str) -> LegacyPlaybook:
    return LegacyPlaybook.model_validate(
        {
            "playbook_id": "pb_1",
            "workflow_id": "wf_0123456789ab",
            "user_id": "u1",
            "workflow_hash": workflow_hash_value,
            "description": "Fetch and summarise.",
            "steps": [{"id": "fetch", "tool": "GMAIL_FETCH_EMAILS", "args": {}}],
            "result_brief": "Say what came in.",
            "created_at": AT,
            "updated_at": AT,
        }
    )


class TestPlaybookValidity:
    def test_the_frozen_fingerprint_is_byte_for_byte_the_apps(self) -> None:
        steps = [WorkflowStep.model_validate(step) for step in STEPS]

        frozen = legacy_workflow_hash("p", [LegacyStep.model_validate(step) for step in STEPS])

        assert frozen == workflow_hash("p", steps)

    def test_a_valid_playbook_is_valid_for_the_tasks_body(self) -> None:
        workflow = _workflow()
        valid = _playbook(legacy_workflow_hash(workflow.effective_prompt, workflow.steps))

        carried = playbook_for_task(valid, workflow)

        assert carried.body_hash == task_body_hash(workflow.effective_prompt)

    def test_a_legacy_prompt_less_workflow_is_valid_for_its_description(self) -> None:
        workflow = _workflow(prompt="", description="Summarise my inbox.")
        valid = _playbook(legacy_workflow_hash("Summarise my inbox.", workflow.steps))

        assert playbook_for_task(valid, workflow).body_hash == task_body_hash("Summarise my inbox.")

    def test_a_stale_playbook_stays_stale(self) -> None:
        workflow = _workflow()
        stale = _playbook(legacy_workflow_hash("An older prompt.", workflow.steps))

        carried = playbook_for_task(stale, workflow)

        assert carried.body_hash == stale.workflow_hash
        assert carried.body_hash != task_body_hash(workflow.effective_prompt)

    def test_no_legacy_hash_can_pass_for_a_body_hash(self) -> None:
        assert legacy_workflow_hash("same text", []) != task_body_hash("same text")


ACTIVITY = (
    "- 2026-11-01T09:00:00+00:00 [created] by GAIA\n"
    "- 2026-11-01T09:00:01.250000+00:00 [run_started] scheduled check (conversation 1a2b3c4d)\n"
    "### 2026-11-01\n"
    "GAIA's own note about the run, with no stamp.\n"
    "- 2026-11-01T09:02:00+00:00 [run_finished] run r1: found two quotes\n"
    "- 2026-11-02T09:00:00+00:00 [run_skipped] scheduled check waits: another run is going\n"
    "- 2026-11-03T09:00:00+00:00 [scheduled] run at 2026-11-04T09:00:00+00:00, by GAIA\n"
    "trailing text with no newline"
)


class TestActivityCuts:
    def test_the_slices_join_back_to_the_log_exactly(self) -> None:
        assert "".join(cut.text for cut in slice_activity(ACTIVITY)) == ACTIVITY

    def test_each_run_ends_its_own_slice_and_the_tail_is_history(self) -> None:
        first, second, tail = slice_activity(ACTIVITY)

        assert (first.status, first.summary) == (TaskRunStatus.SUCCESS, "run r1: found two quotes")
        assert first.started_at == datetime(2026, 11, 1, 9, 0, 1, 250000, tzinfo=UTC)
        assert first.ended_at == datetime(2026, 11, 1, 9, 2, tzinfo=UTC)
        assert second.status is TaskRunStatus.SKIPPED and second.started_at == second.ended_at
        assert tail.status is None and "trailing text" in tail.text

    def test_a_log_with_no_run_is_one_history_record(self) -> None:
        todo = LegacyTodo.model_validate(
            {
                "_id": ObjectId(),
                "user_id": "u1",
                "title": "t",
                "labels": ["gaia-tracked"],
                "activity_content": "free text only\n",
                "created_at": AT,
            }
        )

        (record,) = runs_from_activity(todo)

        assert (record.kind, record.status, record.started_at) == (TaskRunKind.HISTORY, None, AT)
        assert record.imported is not None and record.imported.text == "free text only\n"


class TestIds:
    def test_every_id_a_task_can_carry_matches_and_none_overlap(self) -> None:
        todo_id, workflow_id, new_id = str(ObjectId()), "wf_0123456789ab", new_task_id()

        assert all(TASK_ID_PATTERN.fullmatch(i) for i in (todo_id, workflow_id, new_id))
        # A todo id is 24 hex digits; the other two carry "_", which no hex digit is.
        assert "_" not in todo_id and len({todo_id[:3], workflow_id[:3], new_id[:5]}) == 3


class TestUnmappable:
    def test_a_question_on_a_todo_waiting_on_time_is_refused_not_dropped(self) -> None:
        todo = LegacyTodo.model_validate(
            {
                "_id": ObjectId(),
                "user_id": "u1",
                "title": "t",
                "labels": ["gaia-tracked"],
                "waiting_on": "time",
                "question": "Which day?",
            }
        )

        with pytest.raises(Unmappable):
            task_from_todo(todo, is_users_desk=False)
