"""The three playbook tools, against the real validator and a fake collection.

Only the two seams are stood in for: the workflow lookup and the playbook
collection. The shape check is the tool's own bound schema and the registry
check is the real one, so a rejected write is rejected for the reason
production would reject it.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
import json
from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock, call, patch

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ValidationError
import pytest
import yaml

from app.agents.tools.execute.execute_tool import execute
from app.agents.tools.playbook_tools import (
    _explain_validation_error,
    decline_playbook,
    disable_playbook,
    read_playbook,
    read_run_record,
    write_playbook,
)
from app.constants.agents import PLAYBOOK_REPLAYED_CALLS_KEY
from app.constants.log_tags import LogTag
from app.models.playbook_models import (
    DeclineKind,
    PlaybookDocument,
    PlaybookRunStatus,
    ToolStep,
)
from app.models.workflow_execution_models import RecordedCall
from app.models.workflow_models import (
    PlaybookDiscard,
    TriggerConfig,
    TriggerType,
    WorkflowDocument,
    WorkflowUpdate,
)
from app.services.workflow.integration_pause import PauseOutcome
from app.services.workflow.playbook.record import PlaybookPick
from app.services.workflow.playbook.workflow_hash import workflow_hash

TOOLS_MODULE = "app.agents.tools.playbook_tools"
PARSER_MODULE = "app.services.workflow.playbook.parser"

USER_ID = "507f1f77bcf86cd799439011"
WORKFLOW_ID = "wf_abc123"


@tool
async def list_events(calendar_id: Annotated[str, "Calendar"]) -> dict[str, Any]:
    """List calendar events."""
    return {}


class _FakeRegistry:
    def get_tool_dict(self) -> dict[str, BaseTool]:
        return {"list_events": list_events, "execute": execute}


class _FakePlaybookStore:
    """Stands in for the playbooks collection, keeping the one-per-workflow rule."""

    def __init__(self) -> None:
        self.documents: dict[tuple[str, str], PlaybookDocument] = {}

    async def get_for_workflow(self, workflow_id: str, user_id: str) -> PlaybookDocument | None:
        return self.documents.get((workflow_id, user_id))

    async def upsert_for_workflow(self, playbook: PlaybookDocument) -> PlaybookDocument:
        key = (playbook.workflow_id, playbook.user_id)
        existing = self.documents.get(key)
        stored = (
            playbook
            if existing is None
            else playbook.model_copy(update={"playbook_id": existing.playbook_id})
        )
        self.documents[key] = stored
        return stored

    async def delete_for_workflow(self, workflow_id: str, user_id: str) -> bool:
        return self.documents.pop((workflow_id, user_id), None) is not None


RUN_ID = "stream_run_1"


def _config() -> RunnableConfig:
    return {
        "configurable": {"user_id": USER_ID, "workflow_id": WORKFLOW_ID, "stream_id": RUN_ID},
        "metadata": {"user_id": USER_ID},
    }


def _config_for_run(run_id: str) -> RunnableConfig:
    return {
        "configurable": {"user_id": USER_ID, "workflow_id": WORKFLOW_ID, "stream_id": run_id},
        "metadata": {"user_id": USER_ID},
    }


def _write_playbook_call_schema() -> type[BaseModel]:
    schema = write_playbook.tool_call_schema
    assert isinstance(schema, type) and issubclass(schema, BaseModel)
    return schema


def _workflow() -> WorkflowDocument:
    return WorkflowDocument(
        id=WORKFLOW_ID,
        user_id=USER_ID,
        title="Daily agenda",
        prompt="Mail the agenda",
        steps=[],
        trigger_config=TriggerConfig(type=TriggerType.SCHEDULE, enabled=True),
    )


OTHER_USER = "507f1f77bcf86cd799439012"


def _config_for(user_id: str) -> RunnableConfig:
    return {
        "configurable": {"user_id": user_id, "workflow_id": WORKFLOW_ID},
        "metadata": {"user_id": user_id},
    }


class _FakeWorkflowStore:
    """A workflow lookup scoped per user, exactly as the repository is.

    A MagicMock that answers for anybody cannot show a tenant leak; this can.
    """

    def __init__(self) -> None:
        self.workflow = _workflow()

    async def get_for_user(self, workflow_id: str, user_id: str) -> WorkflowDocument | None:
        if (workflow_id, user_id) == (WORKFLOW_ID, USER_ID):
            return self.workflow
        return None

    async def update_for_user(
        self, workflow_id: str, user_id: str, update: WorkflowUpdate
    ) -> WorkflowDocument | None:
        if (workflow_id, user_id) != (WORKFLOW_ID, USER_ID):
            return None
        self.workflow = self.workflow.model_copy(update=update.model_dump(exclude_unset=True))
        return self.workflow


def _existing(store: _FakePlaybookStore) -> PlaybookDocument:
    now = datetime.now(UTC)
    document = PlaybookDocument(
        playbook_id="pb_existing",
        workflow_id=WORKFLOW_ID,
        user_id=USER_ID,
        workflow_hash="stale",
        description="Old",
        steps=[ToolStep(id="one", tool="list_events", args={"calendar_id": "primary"})],
        result_brief="Old synthesis.",
        last_run_status=PlaybookRunStatus.SUCCESS,
        created_at=now,
        updated_at=now,
    )
    store.documents[(WORKFLOW_ID, USER_ID)] = document
    return document


#: The run every write test authors from, unless a test records its own.
AGENDA_CALL = RecordedCall(
    tool_name="list_events",
    args={"calendar_id": "primary"},
    result_digest=json.dumps({"events": [{"id": "e1", "title": "standup"}]}),
)

NEW_STEPS: list[dict[str, Any]] = [{"call": 1, "id": "agenda"}]
#: The step NEW_STEPS builds from AGENDA_CALL, as it is stored.
NEW_STORED_STEPS: list[dict[str, Any]] = [
    {"id": "agenda", "tool": "list_events", "args": {"calendar_id": "primary"}}
]

NEW_ARGS: dict[str, Any] = {
    "description": "Read the day's events",
    "steps": NEW_STEPS,
    "result_brief": "Say what is on today.",
}

#: Exactly what read_playbook renders for the playbook ``_existing`` stores.
#: Pinned as a literal rather than recomputed with dump_playbook, so a change to
#: the rendering has to be an intentional edit here instead of passing silently.
OLD_YAML = (
    "description: Old\n"
    "steps:\n"
    "- id: one\n"
    "  tool: list_events\n"
    "  args:\n"
    "    calendar_id: primary\n"
    "result_brief: Old synthesis.\n"
)


#: Six picks of calls the run never made, so the write yields six issues in
#: document order. Six, not five, because the log line truncates at five and
#: the returned message does not: a single count cannot tell the two apart.
SIX_INVALID_STEPS: list[dict[str, Any]] = [{"call": 11 + index} for index in range(6)]

SIX_ISSUES = [
    f"steps[{index}].call: call {11 + index} is not in this run's record; the calls you can "
    "pick are 1 (read_run_record lists them)"
    for index in range(6)
]


@pytest.fixture
def store() -> _FakePlaybookStore:
    return _FakePlaybookStore()


@pytest.fixture(autouse=True)
def run_record() -> Iterator[list[RecordedCall]]:
    """Record one agenda call as the run every tool reads, unless a test records its own."""
    calls = [AGENDA_CALL]
    with patch(f"{TOOLS_MODULE}.read_recorded_calls", AsyncMock(side_effect=lambda _: calls)):
        yield calls


@pytest.fixture
def workflows() -> MagicMock:
    repo = MagicMock()
    repo.get_for_user = AsyncMock(return_value=_workflow())
    repo.update_for_user = AsyncMock(return_value=_workflow())
    return repo


@pytest.mark.unit
class TestWritePlaybook:
    async def test_a_step_carrying_keys_the_schema_never_asked_for_is_still_written(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """A stray goal/task/note beside a correct call is dropped, not refused (17 of 57 production authoring attempts were thrown away for this)."""
        _existing(store)
        annotated = [
            {
                "call": 1,
                "id": "agenda",
                "goal": "read the events",
                "task": "agenda",
                "note": "runs every morning",
            }
        ]
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS | {"steps": annotated}, config=_config())

        assert result["success"] is True
        stored = store.documents[(WORKFLOW_ID, USER_ID)]
        assert stored.steps[0].model_dump(exclude_defaults=True) == {
            "id": "agenda",
            "tool": "list_events",
            "args": {"calendar_id": "primary"},
        }

    async def test_playbook_failing_validation_writes_nothing(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(
                NEW_ARGS | {"steps": [{"call": 4}]},
                config=_config(),
            )

        assert result["success"] is False
        assert "call 4 is not in this run's record" in result["message"]
        assert store.documents == {}

    async def test_valid_write_overwrites_the_existing_playbook(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        _existing(store)
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS, config=_config())

        assert result["success"] is True
        assert len(store.documents) == 1
        stored = store.documents[(WORKFLOW_ID, USER_ID)]
        assert stored.description == "Read the day's events"
        assert stored.workflow_hash != "stale"

    @pytest.mark.regression
    async def test_steps_sent_as_json_text_are_written_as_the_steps_they_encode(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """Captured from prod (7 refused writes): the model JSON-encoded the steps list."""
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(
                NEW_ARGS | {"steps": json.dumps(NEW_STEPS)}, config=_config()
            )

        assert result["success"] is True
        stored = store.documents[(WORKFLOW_ID, USER_ID)]
        assert [step.to_document() for step in stored.steps] == NEW_STORED_STEPS

    async def test_the_stored_playbook_is_the_recorded_calls_with_only_the_marked_values_changed(
        self, store: _FakePlaybookStore, workflows: MagicMock, run_record: list[RecordedCall]
    ) -> None:
        """Each pick is one step in run order, an execute call replays through execute as its account, and nothing unmarked moves."""
        run_record[:] = [
            AGENDA_CALL,
            RecordedCall(
                tool_name="list_events",
                args={"calendar_id": "2026-11-03"},
                result_digest=json.dumps({"events": [{"id": "e2"}]}),
            ),
            RecordedCall(
                tool_name="GMAIL_SEND_EMAIL",
                args={"to": "dana@acme.com", "subject": "Agenda"},
                result_digest=json.dumps({"id": "m1"}),
                proxied=True,
                account="work@acme.com",
            ),
        ]
        picks = [
            {"call": 1, "id": "agenda"},
            {"call": 2, "id": "mail", "vary": {"calendar_id": "$today"}},
            {"call": 3, "vary": {"subject": {"$ask": "a subject for today's agenda"}}},
        ]
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS | {"steps": picks}, config=_config())

        assert result["success"] is True
        stored = store.documents[(WORKFLOW_ID, USER_ID)]
        assert [step.to_document() for step in stored.steps] == [
            {"id": "agenda", "tool": "list_events", "args": {"calendar_id": "primary"}},
            {"id": "mail", "tool": "list_events", "args": {"calendar_id": "$today"}},
            {
                "id": "call3",
                "tool": "execute",
                "args": {
                    "task_description": "GMAIL_SEND_EMAIL",
                    "tool_name": "GMAIL_SEND_EMAIL",
                    "data": {
                        "to": "dana@acme.com",
                        "subject": {"$ask": "a subject for today's agenda"},
                    },
                    "account": "work@acme.com",
                },
            },
        ]

    async def test_unknown_workflow_is_refused(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        workflows.get_for_user = AsyncMock(return_value=None)
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS, config=_config())

        assert result["error"] == "workflow_not_found"
        assert store.documents == {}


@pytest.mark.unit
class TestReadPlaybook:
    async def test_missing_playbook_is_a_clean_miss(self, store: _FakePlaybookStore) -> None:
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await read_playbook.ainvoke({}, config=_config())

        assert result["success"] is True
        assert result["data"] == {"exists": False}

    async def test_returns_the_yaml_and_the_last_run_outcome(
        self, store: _FakePlaybookStore
    ) -> None:
        _existing(store)
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await read_playbook.ainvoke({}, config=_config())

        assert result["data"]["yaml"] == OLD_YAML
        assert result["data"]["last_run_used_it"] is True
        assert result["data"]["last_run_status"] == "success"


@pytest.mark.unit
class TestDeclinePlaybook:
    async def test_declining_records_the_reason_and_writes_no_playbook(
        self, store: _FakePlaybookStore
    ) -> None:
        """A decline must leave the playbook store untouched and carry its reason onto the wide event, the only place a repeated decline can be diagnosed."""
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", _FakeWorkflowStore()),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            result = await decline_playbook.ainvoke(
                {
                    "kind": "order_branches",
                    "branch_on": "create_todo",
                    "reason": "the call order depends on the inbox",
                },
                config=_config(),
            )

        assert result == {
            "success": True,
            "data": {"declined": True},
            "message": "Noted. This run reasons it out; the next run is asked again.",
        }
        assert store.documents == {}, "a decline must never write a playbook"
        log.set.assert_called_once_with(
            tool={"name": "decline_playbook", "action": "decline"}, workflow_id=WORKFLOW_ID
        )
        log.set_ns.assert_called_once_with(
            "playbook",
            declined=True,
            decline_kind="order_branches",
            decline_reason="the call order depends on the inbox",
        )

    @pytest.mark.regression
    async def test_a_workflow_that_declined_three_times_is_still_asked(
        self, store: _FakePlaybookStore
    ) -> None:
        """Regression: the third decline retired a workflow for good, and a later decline was refused as not_asked."""
        workflows = _FakeWorkflowStore()
        decline = {"kind": "order_branches", "branch_on": "create_todo", "reason": "order varies"}
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
        ):
            results = [
                await decline_playbook.ainvoke(decline, config=_config_for_run(f"fire {n}"))
                for n in range(4)
            ]

        assert [r["success"] for r in results] == [True, True, True, True]
        assert all(r["data"] == {"declined": True} for r in results)

    async def test_declining_during_a_heal_removes_the_playbook(
        self, store: _FakePlaybookStore
    ) -> None:
        """A decline during a heal must clear the stored sequence, or every later fire gets briefed to heal it again."""
        existing = _existing(store)
        store.documents[(WORKFLOW_ID, USER_ID)] = existing.model_copy(
            update={"last_run_status": PlaybookRunStatus.SUSPECT}
        )
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", _FakeWorkflowStore()),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            result = await decline_playbook.ainvoke(
                {"kind": "order_branches", "branch_on": "create_todo", "reason": "order varies"},
                config=_config(),
            )

        assert result == {
            "success": True,
            "data": {"declined": True, "disabled": True},
            "message": "Noted. The stored playbook was removed; the next run reasons it out and "
            "is asked again.",
        }
        log.set_ns.assert_called_with("playbook", disabled=True, reason="order varies")
        assert store.documents == {}

    async def test_declining_outside_a_heal_keeps_a_working_playbook(
        self, store: _FakePlaybookStore
    ) -> None:
        before = _existing(store)
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", _FakeWorkflowStore()),
        ):
            result = await decline_playbook.ainvoke(
                {"kind": "order_branches", "branch_on": "create_todo", "reason": "order varies"},
                config=_config(),
            )

        assert result == {
            "success": True,
            "data": {"declined": True},
            "message": "Noted. This run reasons it out; the next run is asked again.",
        }
        assert store.documents[(WORKFLOW_ID, USER_ID)] == before

    async def test_a_write_clears_the_discard_the_worker_recorded(
        self, store: _FakePlaybookStore
    ) -> None:
        """A stale discard reason must be cleared on a successful write, or it describes a playbook document that no longer exists."""
        workflows = _FakeWorkflowStore()
        workflows.workflow = workflows.workflow.model_copy(
            update={
                "last_playbook_discard": PlaybookDiscard(
                    playbook_id="pb_old",
                    revision=1,
                    reason="stale_workflow_hash",
                    at=datetime.now(UTC),
                )
            }
        )
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS, config=_config())

        assert result["success"] is True
        assert workflows.workflow.last_playbook_discard is None

    async def test_declining_an_unknown_workflow_is_refused(
        self, store: _FakePlaybookStore
    ) -> None:
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", _FakeWorkflowStore()),
        ):
            result = await decline_playbook.ainvoke(
                {"kind": "order_branches", "branch_on": "create_todo", "reason": "order varies"},
                config=_config_for(OTHER_USER),
            )

        assert result == {
            "success": False,
            "error": "workflow_not_found",
            "message": f"No workflow {WORKFLOW_ID} for this user.",
        }


@pytest.mark.unit
class TestDisablePlaybook:
    async def test_disabling_removes_the_playbook(self, store: _FakePlaybookStore) -> None:
        _existing(store)
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await disable_playbook.ainvoke(
                {"reason": "the order now depends on the inbox"},
                config=_config(),
            )

        assert result == {
            "success": True,
            "data": {"disabled": True},
            "message": "Playbook removed. This workflow reasons out every run again.",
        }
        assert store.documents == {}

    async def test_disabling_a_workflow_without_one_is_not_a_decision(
        self, store: _FakePlaybookStore
    ) -> None:
        """A disable that removes nothing must not count as answering the write-or-decline obligation."""
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await disable_playbook.ainvoke(
                {"reason": "nothing to disable"}, config=_config()
            )

        assert result == {
            "success": False,
            "error": "nothing_to_disable",
            "message": f"Workflow {WORKFLOW_ID} has no playbook. Call write_playbook or "
            "decline_playbook instead.",
        }


@pytest.mark.unit
class TestWorkflowIdFromConfig:
    """The workflow id comes from the run's configurable, never from the model.

    Regression: the tools used to take workflow_id as an argument, and a live
    run hallucinated one ("inbox-triage") even though the server already knew
    the real id from the executor's config.
    """

    async def test_a_write_lands_on_the_workflow_the_run_is_executing(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS, config=_config())

        assert result["success"] is True
        workflows.get_for_user.assert_awaited_once_with(WORKFLOW_ID, USER_ID)
        assert set(store.documents) == {(WORKFLOW_ID, USER_ID)}

    async def test_a_read_resolves_the_workflow_from_the_configurable(
        self, store: _FakePlaybookStore
    ) -> None:
        _existing(store)
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await read_playbook.ainvoke({}, config=_config())

        assert result["data"]["exists"] is True

    @pytest.mark.parametrize(
        ("playbook_tool", "args"),
        [
            (write_playbook, NEW_ARGS),
            (read_playbook, {}),
            (decline_playbook, {"kind": "unstable_discovery", "reason": "r"}),
            (disable_playbook, {"reason": "r"}),
        ],
        ids=["write", "read", "decline", "disable"],
    )
    async def test_outside_a_workflow_run_each_tool_refuses_with_the_reason(
        self, store: _FakePlaybookStore, playbook_tool: BaseTool, args: dict[str, Any]
    ) -> None:
        # The tools are bound to the executor in chat runs too, where calling
        # one is a model mistake; the error has to say so instead of failing
        # deep in the repository with a missing id.
        no_workflow: RunnableConfig = {
            "configurable": {"user_id": USER_ID},
            "metadata": {"user_id": USER_ID},
        }
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await playbook_tool.ainvoke(args, config=no_workflow)

        assert result["success"] is False
        assert result["error"] == "not_in_workflow_run"
        assert "workflow run" in result["message"]
        assert store.documents == {}


@pytest.mark.unit
class TestPlaybookToolContract:
    """The exact envelope each tool returns, because the model reads it.

    A tool's error code and message are not logging: they are the only thing the
    authoring agent has to decide whether to retry, fix its arguments, or stop.
    A code that silently changes shape turns a recoverable rejection into an
    unrecoverable one, and nothing in review would show it.
    """

    async def test_writing_against_an_unknown_workflow_names_the_reason(
        self, store: _FakePlaybookStore
    ) -> None:
        workflows = MagicMock()
        workflows.get_for_user = AsyncMock(return_value=None)

        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS, config=_config())

        assert result["success"] is False
        assert result["error"] == "workflow_not_found"
        assert WORKFLOW_ID in result["message"]
        assert store.documents == {}, "a refused write must leave nothing behind"

    async def test_a_successful_write_reports_what_was_stored(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS, config=_config())

        stored = store.documents[(WORKFLOW_ID, USER_ID)]
        assert result == {
            "success": True,
            "data": {"playbook_id": stored.playbook_id, "steps": len(stored.steps)},
            "message": "Playbook written. Later runs of this workflow replay it.",
        }

    async def test_an_unexpected_write_failure_is_reported_not_swallowed(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """The agent must learn the write did not happen, or it moves on believing it did."""
        with (
            patch.object(
                store, "upsert_for_workflow", new=AsyncMock(side_effect=RuntimeError("mongo down"))
            ),
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            result = await write_playbook.ainvoke(NEW_ARGS, config=_config())

        assert result == {"success": False, "error": "write_failed", "message": "mongo down"}
        log.error.assert_called_once_with(
            f"{LogTag.TOOL} write_playbook: exception", error_type="RuntimeError", exc_info=True
        )

    async def test_reading_a_workflow_without_a_playbook_says_so_without_failing(
        self, store: _FakePlaybookStore
    ) -> None:
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await read_playbook.ainvoke({}, config=_config())

        assert result == {
            "success": True,
            "data": {"exists": False},
            "message": f"Workflow {WORKFLOW_ID} has no playbook yet.",
        }

    async def test_a_read_failure_is_reported_as_a_failure(self, store: _FakePlaybookStore) -> None:
        with (
            patch.object(
                store, "get_for_workflow", new=AsyncMock(side_effect=RuntimeError("mongo down"))
            ),
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            result = await read_playbook.ainvoke({}, config=_config())

        assert result == {"success": False, "error": "read_failed", "message": "mongo down"}
        log.error.assert_called_once_with(
            f"{LogTag.TOOL} read_playbook: exception", error_type="RuntimeError", exc_info=True
        )

    async def test_a_decline_failure_is_reported_as_a_failure(
        self, store: _FakePlaybookStore
    ) -> None:
        """A decline that fails to persist must not report success, or the agent thinks an unanswered question is answered."""
        workflows = MagicMock()
        workflows.get_for_user = AsyncMock(side_effect=RuntimeError("mongo down"))

        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            result = await decline_playbook.ainvoke(
                {"kind": "order_branches", "branch_on": "create_todo", "reason": "order varies"},
                config=_config(),
            )

        assert result == {"success": False, "error": "decline_failed", "message": "mongo down"}
        log.error.assert_called_once_with(
            f"{LogTag.TOOL} decline_playbook: exception", error_type="RuntimeError", exc_info=True
        )

    async def test_a_disable_failure_is_reported_as_a_failure(
        self, store: _FakePlaybookStore
    ) -> None:
        with (
            patch.object(
                store, "delete_for_workflow", new=AsyncMock(side_effect=RuntimeError("mongo down"))
            ),
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            result = await disable_playbook.ainvoke({"reason": "r"}, config=_config())

        assert result == {"success": False, "error": "disable_failed", "message": "mongo down"}
        log.error.assert_called_once_with(
            f"{LogTag.TOOL} disable_playbook: exception", error_type="RuntimeError", exc_info=True
        )


@pytest.mark.unit
class TestPlaybookStorageDetails:
    """What actually lands in the document, beyond "a write happened"."""

    async def test_the_stored_hash_fingerprints_the_workflow_it_was_written_for(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """A wrong hash either falls back to the agent every run or keeps replaying a sequence that no longer answers the edited workflow."""
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            await write_playbook.ainvoke(NEW_ARGS, config=_config())

        workflow = _workflow()
        stored = store.documents[(WORKFLOW_ID, USER_ID)]
        assert stored.workflow_hash == workflow_hash(workflow.prompt, workflow.steps)

    async def test_a_write_stamps_one_moment_on_both_timestamps(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """A fresh, never-revised playbook has "written" and "updated" as the same instant."""
        before = datetime.now(UTC)
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            await write_playbook.ainvoke(NEW_ARGS, config=_config())

        stored = store.documents[(WORKFLOW_ID, USER_ID)]
        assert stored.created_at == stored.updated_at
        assert before <= stored.updated_at <= datetime.now(UTC)

    async def test_a_rejected_write_reports_every_problem_with_where_it_is(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """Reporting a single problem, or one without its node path, costs a round trip per issue and the agent often gives up first."""
        steps = [{"call": 4}, {"call": 1, "vary": {"calendar_id": "primary"}}]
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS | {"steps": steps}, config=_config())

        assert result == {
            "success": False,
            "error": "invalid_playbook",
            "message": "The playbook was not written. Fix these and call write_playbook again: "
            "steps[0].call: call 4 is not in this run's record; the calls you can pick are 1 "
            "(read_run_record lists them); steps[1].vary.calendar_id: 'primary' holds no "
            "placeholder, so it does not change per run; leave 'calendar_id' out to replay the "
            "recorded 'primary', or write one ($today, $steps.<step_id>.<path>, $item.<path>, ...)",
        }
        assert store.documents == {}

    async def test_a_rejected_write_logs_the_first_five_problems_and_the_whole_count(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """The log line truncates to protect the run's event, but the count beside it must report every problem, not just the five shown."""
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            result = await write_playbook.ainvoke(
                NEW_ARGS | {"steps": SIX_INVALID_STEPS}, config=_config()
            )

        log.warning.assert_called_once_with(
            f"{LogTag.TOOL} write_playbook: rejected — " + "; ".join(SIX_ISSUES[:5]),
            issues=6,
            workflow_id=WORKFLOW_ID,
        )
        assert result["message"] == (
            "The playbook was not written. Fix these and call write_playbook again: "
            + "; ".join(SIX_ISSUES)
        )


@pytest.mark.unit
class TestReadPlaybookDetails:
    async def test_a_playbook_that_has_never_replayed_says_so(
        self, store: _FakePlaybookStore
    ) -> None:
        """Distinguishes "written and working" from "written and never exercised"; a never-run playbook must not report as used."""
        document = _existing(store)
        store.documents[(WORKFLOW_ID, USER_ID)] = document.model_copy(
            update={"last_run_status": PlaybookRunStatus.NOT_RUN}
        )
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await read_playbook.ainvoke({}, config=_config())

        assert result["data"]["exists"] is True
        assert result["data"]["last_run_used_it"] is False
        assert result["data"]["last_run_status"] == "not_run"

    async def test_it_reports_when_the_playbook_was_last_written(
        self, store: _FakePlaybookStore
    ) -> None:
        """Staleness is judged from this timestamp, so it must be the last write, not the first."""
        document = _existing(store)
        revised = document.updated_at.replace(microsecond=0)
        store.documents[(WORKFLOW_ID, USER_ID)] = document.model_copy(
            update={"updated_at": revised}
        )
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await read_playbook.ainvoke({}, config=_config())

        assert result["data"]["written_at"] == revised.isoformat()


@pytest.mark.unit
class TestPlaybookTenantIsolation:
    """Every playbook operation is scoped to the caller.

    A workflow id is guessable and appears in URLs; if any of these three tools
    resolved one without the user, one account could read, overwrite, or delete
    another account's automation.
    """

    async def test_a_write_cannot_target_another_users_workflow(
        self, store: _FakePlaybookStore
    ) -> None:
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", _FakeWorkflowStore()),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS, config=_config_for(OTHER_USER))

        assert result["error"] == "workflow_not_found"
        assert store.documents == {}

    async def test_a_read_cannot_reach_another_users_playbook(
        self, store: _FakePlaybookStore
    ) -> None:
        _existing(store)
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await read_playbook.ainvoke({}, config=_config_for(OTHER_USER))

        assert result["data"] == {"exists": False}

    async def test_a_disable_cannot_delete_another_users_playbook(
        self, store: _FakePlaybookStore
    ) -> None:
        _existing(store)
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await disable_playbook.ainvoke(
                {"reason": "not mine"},
                config=_config_for(OTHER_USER),
            )

        assert result["success"] is False
        assert (WORKFLOW_ID, USER_ID) in store.documents


@pytest.mark.unit
class TestPlaybookWideEvents:
    """The fields each tool puts on the run's wide event.

    These are the only production record that a playbook was written, read, or
    disabled and for which workflow. Without them an authoring agent that has
    quietly stopped writing playbooks, or that disables one every run, is
    invisible in the logs.
    """

    async def test_a_write_records_the_tool_the_workflow_and_what_was_stored(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            await write_playbook.ainvoke(NEW_ARGS, config=_config())

        log.set.assert_called_once_with(
            tool={"name": "write_playbook", "action": "write"}, workflow_id=WORKFLOW_ID
        )
        stored = store.documents[(WORKFLOW_ID, USER_ID)]
        # How much of the run there was to pick from, and how much was picked.
        assert log.set_ns.call_args_list == [
            call("playbook", record_calls=1, picks=1),
            call("playbook", id=stored.playbook_id, steps=1),
        ]

    async def test_a_rejected_write_is_recorded_with_how_many_problems(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            await write_playbook.ainvoke(NEW_ARGS | {"steps": [{"call": 4}]}, config=_config())

        assert log.warning.call_args.kwargs["issues"] == 1
        # The record is stamped before the verdict, so a refusal still says what
        # it picked from; nothing about a stored playbook follows.
        assert log.set_ns.call_args_list == [call("playbook", record_calls=1, picks=1)]

    async def test_a_read_records_the_tool_and_the_workflow(
        self, store: _FakePlaybookStore
    ) -> None:
        _existing(store)
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            await read_playbook.ainvoke({}, config=_config())

        log.set.assert_called_once_with(
            tool={"name": "read_playbook", "action": "read"}, workflow_id=WORKFLOW_ID
        )

    async def test_a_disable_records_the_reason_it_was_given(
        self, store: _FakePlaybookStore
    ) -> None:
        _existing(store)
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            await disable_playbook.ainvoke(
                {"reason": "the order now depends on the inbox"},
                config=_config(),
            )

        log.set.assert_called_once_with(
            tool={"name": "disable_playbook", "action": "disable"}, workflow_id=WORKFLOW_ID
        )
        log.set_ns.assert_called_once_with(
            "playbook", disabled=True, reason="the order now depends on the inbox"
        )

    async def test_disabling_nothing_records_no_disable(self, store: _FakePlaybookStore) -> None:
        """A no-op must not look like a disable, or the logs show a playbook being torn down that was never there."""
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            await disable_playbook.ainvoke({"reason": "nothing to disable"}, config=_config())

        log.set_ns.assert_not_called()


@pytest.mark.unit
class TestWritePlaybookBoundary:
    """The tool's own schema and what a call that misses it gets back.

    The schema is the only place the model learns the shape, and the boundary
    error is the only thing it has to work from when the shape is wrong. In
    production 36 of 57 authoring attempts were rejected, and a framework-level
    error the model could not read is why it retried the same shape.
    """

    def test_the_schema_asks_for_three_things_and_no_ask_section(self) -> None:
        """The top-level ask table was removed after 5 of the 8 asks ever written went unreferenced by any step; a reappearing ask property is that mistake returning."""
        schema = _write_playbook_call_schema().model_json_schema()

        assert schema["required"] == ["description", "steps", "result_brief"]
        assert "ask" not in schema["properties"]
        # The workflow is resolved from the run's config server-side.
        assert "workflow_id" not in schema["properties"]

    def test_the_step_schema_does_not_forbid_extra_keys(self) -> None:
        """additionalProperties: false is what a provider reads as "no other keys allowed"; its absence is the leniency, expressed where the model reads it."""
        schema = _write_playbook_call_schema().model_json_schema()

        step = schema["$defs"][PlaybookPick.__name__]
        assert step.get("additionalProperties") is not False

    @pytest.mark.parametrize(
        ("arguments", "expected_problems"),
        [
            (
                {"steps": NEW_STEPS, "result_brief": "Say what is on today."},
                "description: Field required",
            ),
            (
                {**NEW_ARGS, "steps": [{"id": "agenda"}]},
                "steps[0].call: Field required",
            ),
            (
                {"steps": NEW_STEPS},
                "description: Field required; result_brief: Field required",
            ),
        ],
        ids=["missing-description", "pick-without-a-call", "two-problems"],
    )
    async def test_arguments_that_miss_the_schema_come_back_as_a_readable_refusal(
        self,
        store: _FakePlaybookStore,
        workflows: MagicMock,
        arguments: dict[str, Any],
        expected_problems: str,
    ) -> None:
        """Langchain raises before the coroutine runs; without the tool's handle_validation_error hook the model sees a framework traceback instead of a recoverable envelope."""
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(arguments, config=_config())

        assert isinstance(result, str), "the hook hands the model a string, not a raised error"
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "invalid_playbook"
        assert parsed["message"] == (
            "The playbook was not written. Fix these and call write_playbook again: "
            + expected_problems
        )
        assert store.documents == {}

    def test_a_refusal_with_no_field_to_point_at_names_the_arguments_as_a_whole(self) -> None:
        """A pydantic error on the call as a whole carries no location, so it must point at the arguments rather than render an empty field path."""
        with pytest.raises(ValidationError) as raised:
            _write_playbook_call_schema().model_validate("not a mapping")

        assert json.loads(_explain_validation_error(raised.value))["message"] == (
            "The playbook was not written. Fix these and call write_playbook again: "
            "arguments: Input should be a valid dictionary or instance of write_playbook"
        )


@pytest.mark.unit
class TestReadPlaybookYaml:
    async def test_the_yaml_carries_the_result_brief_and_no_ask_section(
        self, store: _FakePlaybookStore
    ) -> None:
        """The stored YAML must match write_playbook's own shape, or the agent learns to write back a section (like a stray top-level ask:) the tool no longer has."""
        now = datetime.now(UTC)
        store.documents[(WORKFLOW_ID, USER_ID)] = PlaybookDocument(
            playbook_id="pb_slots",
            workflow_id=WORKFLOW_ID,
            user_id=USER_ID,
            workflow_hash="h",
            description="Read the day's events",
            steps=[
                ToolStep(
                    id="agenda",
                    tool="list_events",
                    args={"calendar_id": {"$ask": "which calendar to read"}},
                )
            ],
            result_brief="Say what is on today.",
            created_at=now,
            updated_at=now,
        )
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await read_playbook.ainvoke({}, config=_config())

        document = yaml.safe_load(result["data"]["yaml"])
        assert document["result_brief"] == "Say what is on today."
        assert "ask" not in document
        assert document["steps"][0]["args"]["calendar_id"] == {"$ask": "which calendar to read"}


@tool("GMAIL_FETCH_MESSAGES")
async def gmail_fetch_messages(query: Annotated[str, "Search query"]) -> dict[str, Any]:
    """Named as the real Composio tool is, since the playbook this class is about froze $steps.<id>.threadId on it."""
    return {}


@tool("GMAIL_REPLY")
async def gmail_reply(
    thread_id: Annotated[str, "Thread to reply on"], body: Annotated[str, "Reply body"]
) -> dict[str, Any]:
    """Reply on a thread."""
    return {}


class _GmailRegistry:
    """The two tools the authoring-run fixtures below call."""

    def get_tool_dict(self) -> dict[str, BaseTool]:
        return {
            "GMAIL_FETCH_MESSAGES": gmail_fetch_messages,
            "GMAIL_REPLY": gmail_reply,
            "execute": execute,
        }


def _fetch(result: object) -> RecordedCall:
    return RecordedCall(
        tool_name="GMAIL_FETCH_MESSAGES",
        args={"query": "is:unread"},
        result_digest=json.dumps(result),
    )


def _reply(result: object) -> RecordedCall:
    return RecordedCall(
        tool_name="GMAIL_REPLY",
        args={"thread_id": "t1", "body": "hi"},
        result_digest=json.dumps(result),
    )


@pytest.mark.unit
class TestWritePlaybookAgainstTheAuthoringRun:
    """What the picked calls returned in this run decides the write.

    pb_c7d357db77dd froze $steps.fetch_msgs.threadId on a tool that does
    not return one and broke on its first replay; two more were frozen from
    calls that came back empty. In every case the result was in this same
    run's record when write_playbook was called.
    """

    async def test_a_reference_to_a_field_the_call_never_returned_is_refused_with_the_keys(
        self, store: _FakePlaybookStore, workflows: MagicMock, run_record: list[RecordedCall]
    ) -> None:
        """The exact production failure: the refusal must list what the result DOES carry, not just what's missing."""
        run_record[:] = [_fetch({"messages": [{"id": "m1"}]}), _reply({"sent": [{"id": "1"}]})]
        steps = [
            {"call": 1, "id": "fetch"},
            {"call": 2, "vary": {"thread_id": "$steps.fetch.threadId"}},
        ]
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_GmailRegistry()),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS | {"steps": steps}, config=_config())

        assert result["success"] is False
        assert (
            "steps[1].args.thread_id: $steps.fetch.threadId is not in step 'fetch''s result"
            in result["message"]
        )
        assert "its result has keys: messages" in result["message"]
        assert store.documents == {}

    async def test_a_pick_of_a_call_that_returned_nothing_is_refused(
        self, store: _FakePlaybookStore, workflows: MagicMock, run_record: list[RecordedCall]
    ) -> None:
        """A frozen call that found no items still replays, delivering nothing and getting marked SUSPECT one fire later."""
        run_record[:] = [_fetch({"messages": []})]
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_GmailRegistry()),
        ):
            result = await write_playbook.ainvoke(
                NEW_ARGS | {"steps": [{"call": 1}]}, config=_config()
            )

        assert result["success"] is False
        assert "GMAIL_FETCH_MESSAGES returned no items in this run" in result["message"]
        assert store.documents == {}

    async def test_a_playbook_reading_what_the_run_returned_is_written(
        self, store: _FakePlaybookStore, workflows: MagicMock, run_record: list[RecordedCall]
    ) -> None:
        """The checks must accept the shape a run actually produces, or every playbook gets refused, which is worse than the bug."""
        run_record[:] = [
            _fetch({"messages": [{"id": "m1", "threadId": "t1"}]}),
            _reply({"sent": [{"id": "1"}]}),
        ]
        steps = [
            {"call": 1, "id": "fetch"},
            {"call": 2, "vary": {"thread_id": "$steps.fetch.messages.0.threadId"}},
        ]
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_GmailRegistry()),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS | {"steps": steps}, config=_config())

        assert result["success"] is True
        stored = store.documents[(WORKFLOW_ID, USER_ID)]
        assert stored.steps[1].to_document() == {
            "id": "call2",
            "tool": "GMAIL_REPLY",
            "args": {"thread_id": "$steps.fetch.messages.0.threadId", "body": "hi"},
        }

    async def test_a_stopped_replays_calls_come_first_and_can_be_picked(
        self, store: _FakePlaybookStore, workflows: MagicMock, run_record: list[RecordedCall]
    ) -> None:
        """A heal run is told not to repeat the replay's calls, so a rewrite that keeps one picks it from the replay."""
        replayed = RecordedCall(
            tool_name="execute",
            args={
                "task_description": "Listing unread mail",
                "tool_name": "GMAIL_FETCH_MESSAGES",
                "data": {"query": "is:unread"},
            },
            result_digest=json.dumps({"messages": [{"id": "m1", "threadId": "t1"}]}),
            replayed=True,
        )
        run_record[:] = [_reply({"sent": [{"id": "1"}]})]
        config = _config()
        config["configurable"][PLAYBOOK_REPLAYED_CALLS_KEY] = [replayed.model_dump(mode="json")]
        steps = [
            {"call": 1, "id": "fetch"},
            {"call": 2, "vary": {"thread_id": "$steps.fetch.messages.0.threadId"}},
        ]
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_GmailRegistry()),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS | {"steps": steps}, config=config)

        assert result["success"] is True
        first = store.documents[(WORKFLOW_ID, USER_ID)].steps[0].to_document()
        assert first["tool"] == "execute"
        args = first["args"]
        assert isinstance(args, dict)
        assert args["data"] == {"query": "is:unread"}


@pytest.mark.unit
class TestReadRunRecord:
    """What the author picks from: every call, numbered, minus the run's own bookkeeping."""

    async def test_the_calls_are_numbered_with_their_args_and_result_shape(
        self, run_record: list[RecordedCall]
    ) -> None:
        run_record[:] = [
            RecordedCall(tool_name="retrieve_tools", args={"query": "mail"}),
            _fetch({"messages": [{"id": "m1", "threadId": "t1"}]}),
            RecordedCall(tool_name="create_todo", args={"title": "x"}),
            RecordedCall(tool_name="read_run_record", args={}),
        ]

        result = await read_run_record.ainvoke({}, config=_config())

        assert result["data"]["calls"] == [
            {
                "call": 1,
                "tool": "GMAIL_FETCH_MESSAGES",
                "args": {"query": "is:unread"},
                "returned": {"messages": {"list of 1": {"id": "str", "threadId": "str"}}},
            },
            {
                "call": 2,
                "tool": "create_todo",
                "args": {"title": "x"},
                "returned": "str",
            },
        ]

    async def test_a_failed_call_shows_its_error_instead_of_a_shape(
        self, run_record: list[RecordedCall]
    ) -> None:
        run_record[:] = [
            RecordedCall(
                tool_name="list_events",
                args={"calendar_id": "primary"},
                result_digest="Error: TimeoutError: no answer",
                failed=True,
            )
        ]

        result = await read_run_record.ainvoke({}, config=_config())

        assert result["data"]["calls"][0]["failed"] == "Error: TimeoutError: no answer"
        assert "returned" not in result["data"]["calls"][0]

    async def test_outside_a_workflow_run_it_refuses(self) -> None:
        result = await read_run_record.ainvoke({}, config={"configurable": {"user_id": USER_ID}})

        assert result == {
            "success": False,
            "error": "not_in_workflow_run",
            "message": "No workflow in this run's config: this tool only works inside a workflow "
            "run.",
        }

    async def test_a_run_with_nothing_to_replay_says_so(self) -> None:
        with patch(f"{TOOLS_MODULE}.read_recorded_calls", AsyncMock(return_value=[])) as reader:
            result = await read_run_record.ainvoke({}, config=_config())

        reader.assert_awaited_once_with(RUN_ID)
        assert result == {
            "success": True,
            "data": {"calls": []},
            "message": "This run has made no call a playbook can replay, so there is nothing "
            "to freeze.",
        }

    async def test_a_read_records_the_tool_the_workflow_and_how_many_calls(self) -> None:
        with patch(f"{TOOLS_MODULE}.log") as log:
            await read_run_record.ainvoke({}, config=_config())

        log.set.assert_called_once_with(
            tool={"name": "read_run_record", "action": "read"}, workflow_id=WORKFLOW_ID
        )
        assert log.set_ns.call_args_list == [call("playbook", record_calls=1)]

    async def test_a_write_refused_by_the_validator_logs_its_workflow(
        self, store: _FakePlaybookStore, workflows: MagicMock, run_record: list[RecordedCall]
    ) -> None:
        run_record[:] = [_fetch({"messages": [{"id": "m1"}]}), _reply({"sent": [{"id": "1"}]})]
        steps = [
            {"call": 1, "id": "fetch"},
            {"call": 2, "vary": {"thread_id": "$steps.fetch.threadId"}},
        ]
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_GmailRegistry()),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            await write_playbook.ainvoke(NEW_ARGS | {"steps": steps}, config=_config())

        assert log.warning.call_args.kwargs == {"issues": 1, "workflow_id": WORKFLOW_ID}


PAUSE_TARGET = "app.services.workflow.integration_pause.pause_workflow_for_missing_integrations"


@pytest.mark.unit
class TestBlockedDeclines:
    """A run that never reached the work did not judge the sequence.

    Prod ran ~907 declines in 48h and ~80% of them said the same thing: the
    integration was never connected. Counting those burned all three chances in
    under two days and locked the workflow out of ever earning a playbook — the
    one thing that would have made it cheap once the user did connect.
    """

    async def test_a_blocked_run_pauses_the_workflow_and_costs_no_strike(
        self, store: _FakePlaybookStore
    ) -> None:
        workflows = _FakeWorkflowStore()
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(
                PAUSE_TARGET, AsyncMock(return_value=PauseOutcome(paused=["github"], unrelated=[]))
            ) as pause,
        ):
            result = await decline_playbook.ainvoke(
                {
                    "kind": "blocked_missing_integration",
                    "integrations": ["github"],
                    "reason": "GitHub is not connected, so no PRs were fetched",
                },
                config=_config(),
            )

        pause.assert_awaited_once_with(WORKFLOW_ID, USER_ID, ["github"], used_by_run=[])
        assert result == {
            "success": True,
            "data": {
                "declined": True,
                "blocked": True,
                "paused": True,
                "integrations": ["github"],
            },
            "message": "Noted. This workflow is paused until github is connected, and resumes "
            "by itself then.",
        }

    async def test_a_pause_on_several_integrations_names_them_all(
        self, store: _FakePlaybookStore
    ) -> None:
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", _FakeWorkflowStore()),
            patch(
                PAUSE_TARGET,
                AsyncMock(return_value=PauseOutcome(paused=["github", "gmail"], unrelated=[])),
            ),
        ):
            result = await decline_playbook.ainvoke(
                {
                    "kind": "blocked_missing_integration",
                    "integrations": ["github", "gmail"],
                    "reason": "neither is connected",
                },
                config=_config(),
            )
        assert result["message"] == (
            "Noted. This workflow is paused until github, gmail are connected, and resumes "
            "by itself then."
        )

    async def test_an_integration_the_run_never_used_is_refused_not_recorded(
        self, store: _FakePlaybookStore
    ) -> None:
        """The run's own activations are the evidence; a claim they don't support is refused so the model names what it actually needed."""
        workflows = _FakeWorkflowStore()
        # Two activations of gmail and one answer in between: the answered message
        # carries no tool calls, and the target is listed once.
        activated = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "h1",
                    "name": "activate_integration",
                    "args": {"integration_id": "gmail"},
                    "type": "tool_call",
                },
                {
                    "id": "h2",
                    "name": "activate_integration",
                    "args": {"integration_id": "gmail"},
                    "type": "tool_call",
                },
            ],
        )
        answered = ToolMessage(content="12 threads", tool_call_id="h1")
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(
                PAUSE_TARGET,
                AsyncMock(return_value=PauseOutcome(paused=[], unrelated=["slack", "notion"])),
            ) as pause,
        ):
            result = await decline_playbook.ainvoke(
                {
                    "kind": "blocked_missing_integration",
                    "integrations": ["slack", "notion"],
                    "reason": "neither is connected",
                    "state": {"messages": [activated, answered]},
                },
                config=_config(),
            )
        pause.assert_awaited_once_with(
            WORKFLOW_ID, USER_ID, ["slack", "notion"], used_by_run=["gmail"]
        )
        assert result == {
            "success": False,
            "error": "integration_not_in_run",
            "message": "slack, notion are not part of this workflow's steps and this run never "
            "activated it. Name the integration the run actually needed, or decline with "
            "the kind that says why the sequence cannot hold.",
        }
        assert workflows.workflow.activated is True

    async def test_one_unrelated_integration_is_named_in_the_singular(
        self, store: _FakePlaybookStore
    ) -> None:
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", _FakeWorkflowStore()),
            patch(
                PAUSE_TARGET, AsyncMock(return_value=PauseOutcome(paused=[], unrelated=["slack"]))
            ),
        ):
            result = await decline_playbook.ainvoke(
                {
                    "kind": "blocked_missing_integration",
                    "integrations": ["slack"],
                    "reason": "Slack is not connected",
                },
                config=_config(),
            )
        assert result["message"].startswith("slack is not part of this workflow's steps")

    async def test_a_claim_that_does_not_check_out_pauses_nothing(
        self, store: _FakePlaybookStore
    ) -> None:
        """A model-named integration may be connected and have failed for an unrelated reason; pausing a working workflow costs more than it saves."""
        workflows = _FakeWorkflowStore()
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(PAUSE_TARGET, AsyncMock(return_value=PauseOutcome(paused=[], unrelated=[]))),
        ):
            result = await decline_playbook.ainvoke(
                {
                    "kind": "blocked_missing_integration",
                    "integrations": ["github"],
                    "reason": "GitHub looked disconnected",
                },
                config=_config(),
            )

        assert result == {
            "success": True,
            "data": {"declined": True, "blocked": True, "paused": False},
            "message": "Noted, but those integrations look connected from here, so the "
            "workflow is still active.",
        }

    async def test_a_blocked_run_mid_heal_keeps_the_stored_playbook(
        self, store: _FakePlaybookStore
    ) -> None:
        """Unlike an ordinary decline during a heal, a blocked run never ran the sequence, so deleting the stored playbook here is pure loss."""
        existing = _existing(store)
        existing.last_run_status = PlaybookRunStatus.SUSPECT
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", _FakeWorkflowStore()),
            patch(
                PAUSE_TARGET, AsyncMock(return_value=PauseOutcome(paused=["gmail"], unrelated=[]))
            ),
        ):
            await decline_playbook.ainvoke(
                {
                    "kind": "blocked_missing_integration",
                    "integrations": ["gmail"],
                    "reason": "Gmail is not connected",
                },
                config=_config(),
            )

        assert store.documents, "a blocked run must not delete the workflow's playbook"

    async def test_no_budget_pauses_nothing(self, store: _FakePlaybookStore) -> None:
        workflows = _FakeWorkflowStore()
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(PAUSE_TARGET, AsyncMock()) as pause,
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            result = await decline_playbook.ainvoke(
                {"kind": "blocked_no_budget", "reason": "daily allowance was spent"},
                config=_config(),
            )

        pause.assert_not_awaited()
        assert result == {
            "success": True,
            "data": {"declined": True, "blocked": True},
            "message": "Noted — this run never reached the work. It will be asked again on a run "
            "that gets further.",
        }
        assert call("playbook", blocked=True, blocked_integrations=[]) in log.set_ns.call_args_list


@pytest.mark.unit
class TestDeclineKindArguments:
    """The schema refuses the exact answers that were wrong in prod, so the agent re-decides in the same graph loop instead of costing another model call."""

    async def test_a_blocked_integration_decline_must_name_the_integrations(
        self, store: _FakePlaybookStore
    ) -> None:
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", _FakeWorkflowStore()),
        ):
            result = await decline_playbook.ainvoke(
                {"kind": "blocked_missing_integration", "reason": "nothing was connected"},
                config=_config(),
            )

        assert result == {
            "success": False,
            "error": "integrations_required",
            "message": "blocked_missing_integration has to name the integrations the run "
            "could not use. Call decline_playbook again with integrations=[...].",
        }

    async def test_order_branches_must_name_the_branching_call(
        self, store: _FakePlaybookStore
    ) -> None:
        """Closes a real false decline citing "a run-dependent event and its attendees" — those are arguments, already carried by placeholders, so there's no call to name."""
        workflows = _FakeWorkflowStore()
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
        ):
            result = await decline_playbook.ainvoke(
                {"kind": "order_branches", "reason": "the attendees differ every run"},
                config=_config(),
            )

        assert result == {
            "success": False,
            "error": "branch_on_required",
            "message": "order_branches has to name the one call that runs on some days and not "
            "others, as branch_on. If every call you made happens every run and only their "
            "arguments differ, the order does not branch — use placeholders and call "
            "write_playbook. If only the NUMBER of times a call repeats differs, that is a "
            "for_each step, not a decline.",
        }

    async def test_there_is_no_kind_for_arguments_varying(self) -> None:
        """args_vary is unspellable by construction, closing off a wrong decline reason seen ~15 times in two days on the most expensive workflows."""
        assert "args_vary" not in {k.value for k in DeclineKind}
        assert "fan_out_varies" not in {k.value for k in DeclineKind}


@pytest.mark.unit
class TestOneDecisionPerRun:
    """A run is one decision: a write and a decline in the same run are the write."""

    async def test_a_decline_after_a_write_in_the_same_run_is_not_a_second_decision(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """Seen live: a write followed by a decline in the same turn — the write is the decision, and the decline must not undo it."""
        tally = _FakeWorkflowStore()
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", tally),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            written = await write_playbook.ainvoke(NEW_ARGS, config=_config())
            declined = await decline_playbook.ainvoke(
                {"kind": "order_branches", "branch_on": "list_events", "reason": "r"},
                config=_config(),
            )

        assert written["success"] is True
        assert declined == {
            "success": True,
            "data": {"declined": True},
            "message": "This run already wrote a playbook, and that is its decision; nothing "
            "to record.",
        }
        assert store.documents[(WORKFLOW_ID, USER_ID)].authored_run == RUN_ID

    async def test_a_quiet_day_claim_is_refused_when_the_run_did_the_work(
        self, store: _FakePlaybookStore
    ) -> None:
        """A doing-call (create, send, update) counts as work regardless of what the model claims."""
        workflows = _FakeWorkflowStore()
        did_work = AIMessage(
            content="",
            tool_calls=[
                {"id": "c1", "name": "create_todo", "args": {"title": "x"}, "type": "tool_call"},
                {"id": "c2", "name": "send_email", "args": {"to": "a@b.com"}, "type": "tool_call"},
            ],
        )
        answered = [
            ToolMessage(content=json.dumps({"success": True}), tool_call_id="c1"),
            ToolMessage(content="sent", tool_call_id="c2"),
        ]
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
        ):
            result = await decline_playbook.ainvoke(
                {
                    "kind": "no_work_today",
                    "reason": "nothing to do",
                    "state": {"messages": [did_work, *answered]},
                },
                config=_config(),
            )

        assert result["success"] is False
        assert result == {
            "success": False,
            "error": "work_happened",
            "message": "This run called create_todo, send_email, so the work happened today. "
            "Freeze it with write_playbook, or decline with the kind that says why the "
            "sequence cannot hold.",
        }

    async def test_a_doing_call_still_in_flight_is_work_too(
        self, store: _FakePlaybookStore
    ) -> None:
        """A create and a decline can arrive in the same parallel batch; the still-in-flight create still counts as work."""
        workflows = _FakeWorkflowStore()
        in_flight = AIMessage(
            content="",
            tool_calls=[
                {"id": "c1", "name": "create_todo", "args": {"title": "x"}, "type": "tool_call"},
                {"id": "d1", "name": "decline_playbook", "args": {}, "type": "tool_call"},
            ],
        )
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
        ):
            result = await decline_playbook.ainvoke(
                {
                    "kind": "no_work_today",
                    "reason": "nothing to do",
                    "state": {"messages": [in_flight]},
                },
                config=_config(),
            )

        assert result["error"] == "work_happened"
        assert result["message"].startswith("This run called create_todo, so the work happened")

    @pytest.mark.regression
    async def test_the_runs_own_bookkeeping_is_not_the_work(
        self, store: _FakePlaybookStore
    ) -> None:
        """Regression from prod (95 refused quiet-day declines): update_tasks and a refused write_playbook were counted as doing-calls."""
        workflows = _FakeWorkflowStore()
        bookkeeping = AIMessage(
            content="",
            tool_calls=[
                {"id": "c1", "name": "plan_tasks", "args": {"tasks": []}, "type": "tool_call"},
                {"id": "c2", "name": "update_tasks", "args": {"updates": []}, "type": "tool_call"},
                {"id": "c3", "name": "write_playbook", "args": {}, "type": "tool_call"},
                {
                    "id": "c4",
                    "name": "execute",
                    "args": {
                        "task_description": "Listing unread mail",
                        "tool_name": "GMAIL_FETCH_MESSAGES",
                        "data": {"timeframe": "1d"},
                    },
                    "type": "tool_call",
                },
            ],
        )
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
        ):
            result = await decline_playbook.ainvoke(
                {
                    "kind": "no_work_today",
                    "reason": "only newsletters arrived",
                    "state": {"messages": [bookkeeping]},
                },
                config=_config(),
            )

        assert result["success"] is True
        assert result["data"] == {"declined": True}

    @pytest.mark.regression
    async def test_a_doing_call_run_through_execute_is_work(
        self, store: _FakePlaybookStore
    ) -> None:
        workflows = _FakeWorkflowStore()
        drafted = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "c1",
                    "name": "execute",
                    "args": {
                        "task_description": "Drafting a reply",
                        "tool_name": "GMAIL_CREATE_EMAIL_DRAFT",
                        "data": {"thread_id": "t1", "body": "Thanks"},
                    },
                    "type": "tool_call",
                }
            ],
        )
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
        ):
            result = await decline_playbook.ainvoke(
                {
                    "kind": "no_work_today",
                    "reason": "nothing to do",
                    "state": {"messages": [drafted]},
                },
                config=_config(),
            )

        assert result["error"] == "work_happened"
        assert result["message"].startswith(
            "This run called GMAIL_CREATE_EMAIL_DRAFT, so the work happened"
        )

    async def test_a_quiet_day_is_not_a_verdict(self, store: _FakePlaybookStore) -> None:
        """No calls at all means nothing to act on; counting that would spend a seasonal workflow's limited decline chances on empty days."""
        workflows = _FakeWorkflowStore()
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            result = await decline_playbook.ainvoke(
                {"kind": "no_work_today", "reason": "no overdue todos"}, config=_config()
            )

        assert result == {
            "success": True,
            "data": {"declined": True},
            "message": "Noted: nothing to freeze on a day the work did not happen. The next run "
            "is asked again.",
        }
        assert call("playbook", quiet_day=True) in log.set_ns.call_args_list
        assert workflows.workflow.activated is True
