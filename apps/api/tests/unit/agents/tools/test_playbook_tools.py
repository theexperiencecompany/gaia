"""The three playbook tools, against the real validator and a fake collection.

Only the two seams are stood in for: the workflow lookup and the playbook
collection. The shape check is the tool's own bound schema and the registry
check is the real one, so a rejected write is rejected for the reason
production would reject it.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock, call, patch

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import BaseTool, tool
from pydantic import ValidationError
import pytest
import yaml

from app.agents.tools.playbook_tools import (
    decline_playbook,
    disable_playbook,
    read_playbook,
    write_playbook,
)
from app.constants.agents import PLAYBOOK_DECLINE_LIMIT
from app.constants.log_tags import LogTag
from app.models.playbook_models import (
    PlaybookAsk,
    PlaybookBody,
    PlaybookDocument,
    PlaybookRunStatus,
    PlaybookStepInput,
    playbook_body_from_input,
)
from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    WorkflowDocument,
    WorkflowUpdate,
)
from app.services.workflow.playbook.parser import (
    PlaybookValidation,
    dump_playbook,
    validate_playbook,
)
from app.services.workflow.playbook.tool_space import SubagentTools
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
        return {"list_events": list_events}


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


def _config() -> RunnableConfig:
    return {
        "configurable": {"user_id": USER_ID, "workflow_id": WORKFLOW_ID},
        "metadata": {"user_id": USER_ID},
    }


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
    """A workflow lookup that is scoped per user, exactly as the repository is,
    and that keeps the flat ``$set`` writes the decline bookkeeping makes.

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
        steps=[{"id": "one", "tool": "list_events", "args": {"calendar_id": "primary"}}],
        synthesize="Old synthesis.",
        last_run_status=PlaybookRunStatus.SUCCESS,
        created_at=now,
        updated_at=now,
    )
    store.documents[(WORKFLOW_ID, USER_ID)] = document
    return document


NEW_STEPS: list[dict[str, Any]] = [
    {"id": "agenda", "tool": "list_events", "args": {"calendar_id": "primary"}}
]

NEW_ARGS: dict[str, Any] = {
    "description": "Read the day's events",
    "steps": NEW_STEPS,
    "synthesize": "Say what is on today.",
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
    "synthesize: Old synthesis.\n"
)


#: Six steps naming six tools that do not exist, so validation yields six issues
#: in document order. Six, not five, because the log line truncates at five and
#: the returned message does not: a single count cannot tell the two apart.
SIX_INVALID_STEPS: list[dict[str, Any]] = [
    {"id": f"step{index}", "tool": f"send_owl_{index}", "args": {}} for index in range(6)
]

SIX_ISSUES = [f"steps[{index}]: no tool named 'send_owl_{index}' exists" for index in range(6)]


@pytest.fixture
def store() -> _FakePlaybookStore:
    return _FakePlaybookStore()


@pytest.fixture
def workflows() -> MagicMock:
    repo = MagicMock()
    repo.get_for_user = AsyncMock(return_value=_workflow())
    repo.update_for_user = AsyncMock(return_value=_workflow())
    return repo


@pytest.mark.unit
class TestWritePlaybook:
    async def test_a_step_the_schema_does_not_know_never_reaches_the_tool(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        # Regression: the playbook used to arrive as one YAML string, so an
        # invented key like `goal` got all the way to the parser. The bound
        # schema now refuses it before the tool body runs.
        before = _existing(store)
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
            pytest.raises(ValidationError, match="goal"),
        ):
            await write_playbook.ainvoke(
                {**NEW_ARGS, "steps": [{"id": "agenda", "goal": "read the events"}]},
                config=_config(),
            )

        assert store.documents[(WORKFLOW_ID, USER_ID)] == before

    async def test_a_tool_step_nested_under_a_handoff_child_is_refused(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        # Playbooks are depth-1: a handoff's children are plain tool calls, and
        # the flat input model is what makes deeper nesting unrepresentable.
        deeper = [
            {
                "handoff": "gmail",
                "steps": [
                    {
                        "id": "mail",
                        "tool": "list_events",
                        "args": {},
                        "steps": [{"id": "deeper", "tool": "list_events", "args": {}}],
                    }
                ],
            }
        ]
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
            pytest.raises(ValidationError),
        ):
            await write_playbook.ainvoke({**NEW_ARGS, "steps": deeper}, config=_config())

        assert store.documents == {}

    async def test_playbook_failing_validation_writes_nothing(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(
                {**NEW_ARGS, "steps": [{"id": "one", "tool": "send_owl", "args": {}}]},
                config=_config(),
            )

        assert result["success"] is False
        assert "send_owl" in result["message"]
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

    async def test_the_rendered_yaml_matches_the_arguments_it_was_written_from(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        # dump_playbook is what read_playbook hands the agent to read back, so the
        # rendering has to be the same document the arguments described, not an
        # approximation of it.
        steps: list[dict[str, Any]] = [
            {"id": "agenda", "tool": "list_events", "args": {"calendar_id": "primary"}},
            {
                "handoff": "gmail",
                "steps": [{"id": "mail", "tool": "list_events", "args": {"calendar_id": "$now"}}],
            },
        ]
        ask = {"subject": {"prompt": "one subject line", "uses": ["agenda", "mail"]}}
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
            # A handoff's children are validated against that subagent's own
            # space, which for an MCP integration is fetched from the user's
            # client. Declared here rather than resolved from a live registry.
            patch(
                f"{PARSER_MODULE}.resolve_subagent_tools",
                AsyncMock(
                    return_value=SubagentTools(
                        tools=_FakeRegistry().get_tool_dict(), initial_tool_ids=[]
                    )
                ),
            ),
        ):
            result = await write_playbook.ainvoke(
                {**NEW_ARGS, "steps": steps, "ask": ask}, config=_config()
            )

        assert result["success"] is True
        stored = store.documents[(WORKFLOW_ID, USER_ID)]
        expected = playbook_body_from_input(
            description="Read the day's events",
            steps=[PlaybookStepInput.model_validate(step) for step in steps],
            synthesize="Say what is on today.",
            ask={"subject": PlaybookAsk.model_validate(ask["subject"])},
        )
        assert PlaybookBody.model_validate(yaml.safe_load(dump_playbook(stored))) == expected

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
        """The check requires every asked run to end by calling exactly one of
        write_playbook or decline_playbook. The decline must leave the playbook
        store untouched and carry its reason onto the wide event, which is the
        only place a repeated decline can be diagnosed."""
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", _FakeWorkflowStore()),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            result = await decline_playbook.ainvoke(
                {"reason": "the call order depends on the inbox"},
                config=_config(),
            )

        assert result == {
            "success": True,
            "data": {"declined": True},
            "message": "Noted. This workflow keeps reasoning out every run for now.",
        }
        assert store.documents == {}, "a decline must never write a playbook"
        log.set.assert_called_once_with(
            tool={"name": "decline_playbook", "action": "decline"}, workflow_id=WORKFLOW_ID
        )
        assert log.set_ns.call_args_list == [
            call("playbook", declined=True, decline_reason="the call order depends on the inbox"),
            call("playbook", declines=1),
        ]

    async def test_a_decline_when_the_check_was_not_asked_is_refused_and_not_counted(
        self, store: _FakePlaybookStore
    ) -> None:
        """Seen live: past the decline limit the check goes silent, but the
        tool is always bound and the model declined anyway, so the count kept
        growing on a question nobody asked."""
        workflows = _FakeWorkflowStore()
        workflows.workflow.playbook_declines = PLAYBOOK_DECLINE_LIMIT
        workflows.workflow.playbook_declined_hash = workflow_hash(
            workflows.workflow.prompt, workflows.workflow.steps
        )
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
        ):
            result = await decline_playbook.ainvoke({"reason": "order varies"}, config=_config())

        assert result == {
            "success": False,
            "error": "not_asked",
            "message": "This workflow is no longer asked about a playbook; nothing to decline.",
        }
        assert workflows.workflow.playbook_declines == PLAYBOOK_DECLINE_LIMIT

    async def test_a_decline_is_counted_against_the_workflow_as_it_stands(
        self, store: _FakePlaybookStore
    ) -> None:
        """Nothing was persisted before, so a workflow whose order genuinely
        varies was asked the whole check on every fire, forever."""
        workflows = _FakeWorkflowStore()
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
        ):
            await decline_playbook.ainvoke({"reason": "order varies"}, config=_config())
            await decline_playbook.ainvoke({"reason": "order varies"}, config=_config())

        assert workflows.workflow.playbook_declines == 2
        assert workflows.workflow.playbook_declined_hash == workflow_hash(
            workflows.workflow.prompt, workflows.workflow.steps
        )

    async def test_declines_on_an_older_workflow_do_not_carry_over_an_edit(
        self, store: _FakePlaybookStore
    ) -> None:
        workflows = _FakeWorkflowStore()
        workflows.workflow = workflows.workflow.model_copy(
            update={
                "playbook_declines": PLAYBOOK_DECLINE_LIMIT,
                "playbook_declined_hash": "hash-before-the-edit",
            }
        )
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
        ):
            await decline_playbook.ainvoke({"reason": "order varies"}, config=_config())

        assert workflows.workflow.playbook_declines == 1

    async def test_declining_during_a_heal_removes_the_playbook(
        self, store: _FakePlaybookStore
    ) -> None:
        """Inside a heal run, a decline means the stored sequence cannot hold.
        Left FAILED/SUSPECT, every later fire would be briefed to heal it again."""
        existing = _existing(store)
        store.documents[(WORKFLOW_ID, USER_ID)] = existing.model_copy(
            update={"last_run_status": PlaybookRunStatus.SUSPECT}
        )
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", _FakeWorkflowStore()),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            result = await decline_playbook.ainvoke({"reason": "order varies"}, config=_config())

        assert result == {
            "success": True,
            "data": {"declined": True, "disabled": True},
            "message": "Noted. The stored playbook was removed; this workflow reasons out every "
            "run again.",
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
            result = await decline_playbook.ainvoke({"reason": "order varies"}, config=_config())

        assert result == {
            "success": True,
            "data": {"declined": True},
            "message": "Noted. This workflow keeps reasoning out every run for now.",
        }
        assert store.documents[(WORKFLOW_ID, USER_ID)] == before

    async def test_a_write_resets_the_declines(self, store: _FakePlaybookStore) -> None:
        workflows = _FakeWorkflowStore()
        workflows.workflow = workflows.workflow.model_copy(
            update={"playbook_declines": 2, "playbook_declined_hash": "h"}
        )
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS, config=_config())

        assert result["success"] is True
        assert workflows.workflow.playbook_declines == 0
        assert workflows.workflow.playbook_declined_hash is None

    async def test_declining_an_unknown_workflow_is_refused(
        self, store: _FakePlaybookStore
    ) -> None:
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", _FakeWorkflowStore()),
        ):
            result = await decline_playbook.ainvoke(
                {"reason": "order varies"}, config=_config_for(OTHER_USER)
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
        """A briefed run with no playbook owes write or decline; a disable that
        removes nothing must not read as the decision being made."""
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
            (decline_playbook, {"reason": "r"}),
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
        store.upsert_for_workflow = AsyncMock(side_effect=RuntimeError("mongo down"))

        with (
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
        store.get_for_workflow = AsyncMock(side_effect=RuntimeError("mongo down"))

        with (
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
        """A decline that failed to persist has not been recorded, so the count
        did not move and the check will ask again. Reporting it as a success
        would tell the agent the question is answered when it is not."""
        workflows = MagicMock()
        workflows.get_for_user = AsyncMock(side_effect=RuntimeError("mongo down"))

        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            result = await decline_playbook.ainvoke({"reason": "order varies"}, config=_config())

        assert result == {"success": False, "error": "decline_failed", "message": "mongo down"}
        log.error.assert_called_once_with(
            f"{LogTag.TOOL} decline_playbook: exception", error_type="RuntimeError", exc_info=True
        )

    async def test_a_disable_failure_is_reported_as_a_failure(
        self, store: _FakePlaybookStore
    ) -> None:
        store.delete_for_workflow = AsyncMock(side_effect=RuntimeError("mongo down"))

        with (
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
        """The replay path compares this hash before running the frozen steps.

        Fingerprinting the wrong thing means either every run falls back to the
        agent (the playbook never pays off) or an edited workflow keeps replaying
        a sequence that no longer answers it.
        """
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
        """A fresh playbook has never been revised, so "written" and "updated"
        are the same instant. A read reports ``updated_at`` back to the agent as
        when the document was written."""
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
        """The agent fixes the whole document in one revision or not at all.

        Reporting a single problem, or a problem without its node path, costs a
        round trip per issue and the agent often gives up first.
        """
        steps = [
            {"id": "one", "tool": "send_owl", "args": {}},
            {"id": "two", "tool": "list_events", "args": {"calendar_id": 5}},
        ]
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke({**NEW_ARGS, "steps": steps}, config=_config())

        assert result == {
            "success": False,
            "error": "invalid_playbook",
            "message": "The playbook was not written. Fix these and call write_playbook again: "
            "steps[0]: no tool named 'send_owl' exists; "
            "steps[1].args.calendar_id: expected string, got int",
        }
        assert store.documents == {}

    async def test_a_rejected_write_logs_the_first_five_problems_and_the_whole_count(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """The log line is truncated where the returned message is not: one
        hopeless playbook must not flood the run's event, but the agent still
        needs every problem to revise in one pass. The count beside the line is
        what says how much was cut, so it counts all of them, not the five.
        """
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            result = await write_playbook.ainvoke(
                {**NEW_ARGS, "steps": SIX_INVALID_STEPS}, config=_config()
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

    async def test_the_playbook_is_validated_for_the_user_whose_run_wrote_it(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """Whether a tool exists has no user-independent answer: a handoff's
        children run in that subagent's space, and an MCP integration's tools
        live on that user's own client. Validating for nobody would accept steps
        the replay cannot run, and refuse ones it can.
        """
        seen: list[tuple[PlaybookBody, str]] = []

        async def spying_validate(body: PlaybookBody, user_id: str) -> PlaybookValidation:
            seen.append((body, user_id))
            return await validate_playbook(body, user_id)

        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
            patch(f"{TOOLS_MODULE}.validate_playbook", spying_validate),
        ):
            result = await write_playbook.ainvoke(NEW_ARGS, config=_config())

        assert result["success"] is True
        assert seen == [
            (
                playbook_body_from_input(
                    description="Read the day's events",
                    steps=[PlaybookStepInput.model_validate(step) for step in NEW_STEPS],
                    synthesize="Say what is on today.",
                    ask=None,
                ),
                USER_ID,
            )
        ]


@pytest.mark.unit
class TestReadPlaybookDetails:
    async def test_a_playbook_that_has_never_replayed_says_so(
        self, store: _FakePlaybookStore
    ) -> None:
        """This flag is how the agent tells "written and working" from "written
        and never exercised". Reporting a never-run playbook as used hides the
        case where the replay path is silently never taken."""
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
        """The agent decides whether a playbook is stale from this timestamp, so
        it has to be the last write, not the first."""
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
        log.set_ns.assert_called_once_with("playbook", id=stored.playbook_id, steps=1)

    async def test_a_rejected_write_is_recorded_with_how_many_problems(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            await write_playbook.ainvoke(
                {**NEW_ARGS, "steps": [{"id": "one", "tool": "send_owl", "args": {}}]},
                config=_config(),
            )

        assert log.warning.call_args.kwargs["issues"] == 1
        log.set_ns.assert_not_called()

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
        """A no-op must not look like a disable, or the logs show playbooks being
        torn down that were never there."""
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            await disable_playbook.ainvoke({"reason": "nothing to disable"}, config=_config())

        log.set_ns.assert_not_called()
