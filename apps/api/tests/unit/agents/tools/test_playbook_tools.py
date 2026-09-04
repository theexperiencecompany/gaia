"""The three playbook tools, against the real validator and a fake collection.

Only the two seams are stood in for: the workflow lookup and the playbook
collection. The shape check is the tool's own bound schema and the registry
check is the real one, so a rejected write is rejected for the reason
production would reject it.
"""

from datetime import UTC, datetime
import json
from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock, call, patch

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import BaseTool, tool
from pydantic import ValidationError
import pytest
import yaml

from app.agents.tools.playbook_tools import (
    _explain_validation_error,
    _run_results,
    decline_playbook,
    disable_playbook,
    read_playbook,
    write_playbook,
)
from app.constants.agents import PLAYBOOK_DECLINE_LIMIT
from app.constants.log_tags import LogTag
from app.models.playbook_models import (
    PlaybookBody,
    PlaybookDocument,
    PlaybookRunStatus,
    PlaybookStepInput,
    playbook_body_from_input,
)
from app.models.workflow_models import (
    PlaybookDiscard,
    TriggerConfig,
    TriggerType,
    WorkflowDocument,
    WorkflowUpdate,
)
from app.services.workflow.playbook.parser import (
    PlaybookValidation,
    RunResults,
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
        result_brief="Old synthesis.",
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
    async def test_a_step_carrying_keys_the_schema_never_asked_for_is_still_written(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """A stray ``goal``/``task``/``note`` beside a correct call is dropped,
        not refused.

        Measured in production: 17 of 57 authoring attempts were thrown away
        whole because the model annotated a step it had otherwise written
        correctly. If this fails, the step input has gone back to forbidding
        extras and the same writes start being rejected again.
        """
        _existing(store)
        annotated = [
            {
                "id": "agenda",
                "tool": "list_events",
                "args": {"calendar_id": "primary"},
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
            result = await write_playbook.ainvoke(
                {**NEW_ARGS, "steps": annotated}, config=_config()
            )

        assert result["success"] is True
        stored = store.documents[(WORKFLOW_ID, USER_ID)]
        assert stored.steps[0].model_dump(exclude_defaults=True) == {
            "id": "agenda",
            "tool": "list_events",
            "args": {"calendar_id": "primary"},
        }

    async def test_a_tool_step_nested_under_a_handoff_child_is_refused_not_dropped(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """Playbooks are depth-1: a handoff's children are plain tool calls.

        The child model drops unknown keys, so without its own rule a third
        level would vanish silently and the stored playbook would run a fraction
        of what the author wrote. If this fails, either a grandchild is being
        stored (a level the runner cannot execute) or it is being discarded
        without a word to the author.
        """
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
            patch(
                f"{PARSER_MODULE}.resolve_subagent_tools",
                AsyncMock(
                    return_value=SubagentTools(
                        tools=_FakeRegistry().get_tool_dict(), initial_tool_ids=[]
                    )
                ),
            ),
        ):
            result = await write_playbook.ainvoke({**NEW_ARGS, "steps": deeper}, config=_config())

        assert isinstance(result, str), "refused at the boundary, through handle_validation_error"
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "invalid_playbook"
        assert "steps[0].steps[0]: " in parsed["message"]
        assert "one level deep" in parsed["message"]
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
            {
                "id": "written",
                "tool": "list_events",
                "args": {"calendar_id": {"$ask": "which calendar the agenda came from"}},
            },
        ]
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
            result = await write_playbook.ainvoke({**NEW_ARGS, "steps": steps}, config=_config())

        assert result["success"] is True
        stored = store.documents[(WORKFLOW_ID, USER_ID)]
        expected = playbook_body_from_input(
            description="Read the day's events",
            steps=[PlaybookStepInput.model_validate(step) for step in steps],
            result_brief="Say what is on today.",
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

    async def test_a_write_clears_the_discard_the_worker_recorded(
        self, store: _FakePlaybookStore
    ) -> None:
        """The discard says why this workflow's LAST playbook was thrown away.
        Left behind after a successful write it describes a document that no
        longer exists, and the workflow reads as having lost a shortcut it now
        has."""
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

        async def spying_validate(
            body: PlaybookBody, user_id: str, results: RunResults | None = None
        ) -> PlaybookValidation:
            seen.append((body, user_id))
            return await validate_playbook(body, user_id, results)

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
                    result_brief="Say what is on today.",
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
        # No graph state reaches a direct ainvoke, so the run check records
        # None — the field that tells prod whether InjectedState was filled.
        assert log.set_ns.call_args_list == [
            call("playbook", checked_against_calls=None),
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
            await write_playbook.ainvoke(
                {**NEW_ARGS, "steps": [{"id": "one", "tool": "send_owl", "args": {}}]},
                config=_config(),
            )

        assert log.warning.call_args.kwargs["issues"] == 1
        # The run check is stamped before the verdict, so a refusal still says
        # what it was checked against; nothing about a stored playbook follows.
        assert log.set_ns.call_args_list == [call("playbook", checked_against_calls=None)]

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


@pytest.mark.unit
class TestWritePlaybookBoundary:
    """The tool's own schema and what a call that misses it gets back.

    The schema is the only place the model learns the shape, and the boundary
    error is the only thing it has to work from when the shape is wrong. In
    production 36 of 57 authoring attempts were rejected, and a framework-level
    error the model could not read is why it retried the same shape.
    """

    def test_the_schema_asks_for_three_things_and_no_ask_section(self) -> None:
        """``ask`` was a separate table the model had to reason about, and five
        of the eight asks ever written were referenced by no step. The slot now
        lives inside the argument, so there is nothing at the top level to get
        wrong; a reappearing ``ask`` property is that mistake coming back.
        """
        schema = write_playbook.tool_call_schema.model_json_schema()

        assert schema["required"] == ["description", "steps", "result_brief"]
        assert "ask" not in schema["properties"]
        # The workflow is resolved from the run's config server-side.
        assert "workflow_id" not in schema["properties"]

    def test_the_step_schema_does_not_forbid_extra_keys(self) -> None:
        """``additionalProperties: false`` is what a provider renders as "no
        other keys allowed", and it is what turned a step annotated with a
        ``goal`` into a refused write. Its absence is the leniency, expressed
        where the model actually reads it."""
        schema = write_playbook.tool_call_schema.model_json_schema()

        step = schema["$defs"][PlaybookStepInput.__name__]
        assert step.get("additionalProperties") is not False
        child_name = step["properties"]["steps"]["items"]["$ref"].rsplit("/", 1)[-1]
        assert schema["$defs"][child_name].get("additionalProperties") is not False

    @pytest.mark.parametrize(
        ("arguments", "expected_problems"),
        [
            (
                {"steps": NEW_STEPS, "result_brief": "Say what is on today."},
                "description: Field required",
            ),
            (
                {
                    **NEW_ARGS,
                    "steps": [
                        {"id": "agenda", "tool": "list_events", "handoff": "gmail", "args": {}}
                    ],
                },
                "steps[0]: Value error, step agenda: set exactly one of 'tool' or 'handoff'",
            ),
            (
                {"steps": NEW_STEPS},
                "description: Field required; result_brief: Field required",
            ),
        ],
        ids=["missing-description", "both-tool-and-handoff", "two-problems"],
    )
    async def test_arguments_that_miss_the_schema_come_back_as_a_readable_refusal(
        self,
        store: _FakePlaybookStore,
        workflows: MagicMock,
        arguments: dict[str, Any],
        expected_problems: str,
    ) -> None:
        """langchain raises before the coroutine runs, so without the tool's
        ``handle_validation_error`` hook the model gets a framework traceback
        rather than the tool's own envelope. If this fails, a shape mistake stops
        being recoverable: the model cannot tell what to fix, and nothing says
        the playbook was not written.
        """
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
        """A pydantic error on the call as a whole carries no location. Rendered
        as the empty string the model reads ": Input should be..." and has
        nothing to act on; the arguments themselves are what is wrong."""
        with pytest.raises(ValidationError) as raised:
            write_playbook.tool_call_schema.model_validate("not a mapping")

        assert json.loads(_explain_validation_error(raised.value))["message"] == (
            "The playbook was not written. Fix these and call write_playbook again: "
            "arguments: Input should be a valid dictionary or instance of write_playbook"
        )


@pytest.mark.unit
class TestReadPlaybookYaml:
    async def test_the_yaml_carries_the_result_brief_and_no_ask_section(
        self, store: _FakePlaybookStore
    ) -> None:
        """The YAML is the document the agent reads before revising, so it has to
        be the shape write_playbook takes. A stray top-level ``ask:`` would teach
        the agent to write back a section the tool no longer has."""
        now = datetime.now(UTC)
        store.documents[(WORKFLOW_ID, USER_ID)] = PlaybookDocument(
            playbook_id="pb_slots",
            workflow_id=WORKFLOW_ID,
            user_id=USER_ID,
            workflow_hash="h",
            description="Read the day's events",
            steps=[
                {
                    "id": "agenda",
                    "tool": "list_events",
                    "args": {"calendar_id": {"$ask": "which calendar to read"}},
                }
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
    """Fetch messages. Named as the real Composio tool is, because the playbook
    this class is about froze $steps.<id>.threadId on it."""
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
        return {"GMAIL_FETCH_MESSAGES": gmail_fetch_messages, "GMAIL_REPLY": gmail_reply}


def _run_state(*calls: tuple[str, dict[str, Any], object]) -> dict[str, Any]:
    """Graph state whose messages are the run's calls and the answers to them.

    Built as real messages rather than as a results list, because reading the
    run out of ``state["messages"]`` — pairing each AIMessage tool call with the
    ToolMessage that answers its id — is half of what is under test.
    """
    messages: list[Any] = []
    for index, (name, args, result) in enumerate(calls):
        call_id = f"call_{index}"
        messages.append(
            AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])
        )
        messages.append(ToolMessage(content=json.dumps(result), tool_call_id=call_id, name=name))
    return {"messages": messages}


FETCH_STEP: dict[str, Any] = {
    "id": "fetch",
    "tool": "GMAIL_FETCH_MESSAGES",
    "args": {"query": "is:unread"},
}


@pytest.mark.unit
class TestWritePlaybookAgainstTheAuthoringRun:
    """The run's own results, injected as state, decide the write.

    ``pb_c7d357db77dd`` froze ``$steps.fetch_msgs.threadId`` on a tool that does
    not return one and broke on its first replay; two more were frozen from
    calls that came back empty. In every case the result was in this same
    conversation when write_playbook was called.
    """

    async def test_a_step_freezing_a_field_the_run_never_returned_is_refused_with_the_keys(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """The exact production failure. The refusal has to list what the result
        DOES carry, or the author is told to fix something without being told
        what it could have written instead."""
        state = _run_state(
            ("GMAIL_FETCH_MESSAGES", {"query": "is:unread"}, {"messages": [{"id": "m1"}]}),
            ("GMAIL_REPLY", {"thread_id": "t1", "body": "hi"}, {"sent": [{"id": "1"}]}),
        )
        steps = [
            FETCH_STEP,
            {
                "id": "reply",
                "tool": "GMAIL_REPLY",
                "args": {"thread_id": "$steps.fetch.threadId", "body": "hi"},
            },
        ]
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_GmailRegistry()),
        ):
            result = await write_playbook.ainvoke(
                {**NEW_ARGS, "steps": steps, "state": state}, config=_config()
            )

        assert result["success"] is False
        assert (
            "steps[1].args.thread_id: $steps.fetch.threadId is not in step 'fetch''s result"
            in (result["message"])
        )
        assert "its result has keys: messages" in result["message"]
        assert store.documents == {}

    async def test_a_step_freezing_a_call_that_returned_nothing_is_refused(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """A frozen call that found no items replays into a workflow that
        delivers nothing and is marked SUSPECT one fire later."""
        state = _run_state(("GMAIL_FETCH_MESSAGES", {"query": "is:unread"}, {"messages": []}))
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_GmailRegistry()),
        ):
            result = await write_playbook.ainvoke(
                {**NEW_ARGS, "steps": [FETCH_STEP], "state": state}, config=_config()
            )

        assert result["success"] is False
        assert "GMAIL_FETCH_MESSAGES returned no items in this run" in result["message"]
        assert store.documents == {}

    async def test_a_playbook_that_matches_what_the_run_returned_is_written(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """The checks must accept the shape the run actually produced. A refusal
        here would refuse every playbook, which is worse than the bug."""
        state = _run_state(
            (
                "GMAIL_FETCH_MESSAGES",
                {"query": "is:unread"},
                {"messages": [{"id": "m1", "threadId": "t1"}]},
            ),
            ("GMAIL_REPLY", {"thread_id": "t1", "body": "hi"}, {"sent": [{"id": "1"}]}),
        )
        steps = [
            FETCH_STEP,
            {
                "id": "reply",
                "tool": "GMAIL_REPLY",
                "args": {"thread_id": "$steps.fetch.messages.0.threadId", "body": "hi"},
            },
        ]
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_GmailRegistry()),
        ):
            result = await write_playbook.ainvoke(
                {**NEW_ARGS, "steps": steps, "state": state}, config=_config()
            )

        assert result["success"] is True
        assert len(store.documents[(WORKFLOW_ID, USER_ID)].steps) == 2

    def test_the_run_state_is_injected_and_never_shown_to_the_model(self) -> None:
        """``state`` is filled by the graph. If it appeared in the schema the
        model would be asked to write its own transcript back as an argument,
        and the checks would read whatever it invented."""
        schema = write_playbook.tool_call_schema.model_json_schema()

        assert "state" not in schema["properties"]
        assert schema["required"] == ["description", "steps", "result_brief"]


@pytest.mark.unit
class TestTheRunTheWriteIsCheckedAgainst:
    """Reading the run out of the graph state: each recorded call paired with
    the message that answered it. What this drops never reaches the validator,
    and what it invents is checked against a call that never happened."""

    def test_a_call_is_recorded_with_its_arguments_and_what_came_back(self) -> None:
        """A tool answering in content blocks rather than a string is the normal
        shape for several providers. Dropped or blanked, the step it belongs to
        is refused as "did not run in this run"."""
        state = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "GMAIL_FETCH_MESSAGES", "args": {"query": "is:unread"}, "id": "c1"}
                    ],
                ),
                ToolMessage(
                    content=[
                        {"type": "text", "text": "one", "at": datetime(2026, 9, 1, tzinfo=UTC)}
                    ],
                    tool_call_id="c1",
                ),
            ]
        }

        results = _run_results(state)

        assert [recorded.tool_name for recorded in results] == ["GMAIL_FETCH_MESSAGES"]
        assert results[0].args == {"query": "is:unread"}
        assert results[0].result == [
            {"type": "text", "text": "one", "at": "2026-09-01 00:00:00+00:00"}
        ]

    def test_a_call_with_no_tool_name_is_not_a_call_a_step_could_have_frozen(self) -> None:
        """A nameless call matches no step's tool. Kept, it becomes a recorded
        result under a name no playbook can ever address."""
        state = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "", "args": {}, "id": "c1"}]),
                ToolMessage(content=json.dumps({"ok": True}), tool_call_id="c1"),
            ]
        }

        assert _run_results(state) == []

    def test_a_call_still_in_flight_is_skipped_and_the_ones_beside_it_are_kept(self) -> None:
        """``write_playbook`` itself is unanswered in every real run. Stopping at
        it throws away the calls the playbook is being written from."""
        state = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "write_playbook", "args": {}, "id": "c0"},
                        {
                            "name": "GMAIL_FETCH_MESSAGES",
                            "args": {"query": "is:unread"},
                            "id": "c1",
                        },
                    ],
                ),
                ToolMessage(content=json.dumps({"messages": [{"id": "m1"}]}), tool_call_id="c1"),
            ]
        }

        results = _run_results(state)

        assert [recorded.tool_name for recorded in results] == ["GMAIL_FETCH_MESSAGES"]

    async def test_a_write_records_how_many_of_the_runs_calls_it_was_checked_against(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        """``None`` and ``0`` are different answers — no graph state reached the
        tool at all, versus a run that genuinely made no calls — and this count
        is the only field that tells them apart in production."""
        state = _run_state(
            ("GMAIL_FETCH_MESSAGES", {"query": "is:unread"}, {"messages": [{"id": "m1"}]}),
            ("GMAIL_REPLY", {"thread_id": "t1", "body": "hi"}, {"sent": [{"id": "1"}]}),
        )
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_GmailRegistry()),
            patch(f"{TOOLS_MODULE}.log") as log,
        ):
            await write_playbook.ainvoke(
                {**NEW_ARGS, "steps": [FETCH_STEP], "state": state}, config=_config()
            )

        assert log.set_ns.call_args_list[0] == call("playbook", checked_against_calls=2)
