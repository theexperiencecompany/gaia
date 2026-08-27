"""The three playbook tools, against the real validator and a fake collection.

Only the two seams are stood in for: the workflow lookup and the playbook
collection. The shape check is the tool's own bound schema and the registry
check is the real one, so a rejected write is rejected for the reason
production would reject it.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import BaseTool, tool
from pydantic import ValidationError
import pytest
import yaml

from app.agents.tools.playbook_tools import disable_playbook, read_playbook, write_playbook
from app.models.playbook_models import (
    PlaybookAsk,
    PlaybookBody,
    PlaybookDocument,
    PlaybookRunStatus,
    PlaybookStepInput,
    playbook_body_from_input,
)
from app.models.workflow_models import TriggerConfig, TriggerType, WorkflowDocument
from app.services.workflow.playbook.parser import dump_playbook

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
    return {"configurable": {"user_id": USER_ID}, "metadata": {"user_id": USER_ID}}


def _workflow() -> WorkflowDocument:
    return WorkflowDocument(
        id=WORKFLOW_ID,
        user_id=USER_ID,
        title="Daily agenda",
        prompt="Mail the agenda",
        steps=[],
        trigger_config=TriggerConfig(type=TriggerType.SCHEDULE, enabled=True),
    )


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
    "workflow_id": WORKFLOW_ID,
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


@pytest.fixture
def store() -> _FakePlaybookStore:
    return _FakePlaybookStore()


@pytest.fixture
def workflows() -> MagicMock:
    repo = MagicMock()
    repo.get_for_user = AsyncMock(return_value=_workflow())
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
            result = await read_playbook.ainvoke({"workflow_id": WORKFLOW_ID}, config=_config())

        assert result["success"] is True
        assert result["data"] == {"exists": False}

    async def test_returns_the_yaml_and_the_last_run_outcome(
        self, store: _FakePlaybookStore
    ) -> None:
        _existing(store)
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await read_playbook.ainvoke({"workflow_id": WORKFLOW_ID}, config=_config())

        assert result["data"]["yaml"] == OLD_YAML
        assert result["data"]["last_run_used_it"] is True
        assert result["data"]["last_run_status"] == "success"


@pytest.mark.unit
class TestDisablePlaybook:
    async def test_disabling_removes_the_playbook(self, store: _FakePlaybookStore) -> None:
        _existing(store)
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await disable_playbook.ainvoke(
                {"workflow_id": WORKFLOW_ID, "reason": "the order now depends on the inbox"},
                config=_config(),
            )

        assert result["data"] == {"disabled": True}
        assert store.documents == {}

    async def test_disabling_a_workflow_without_one_is_not_an_error(
        self, store: _FakePlaybookStore
    ) -> None:
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await disable_playbook.ainvoke(
                {"workflow_id": WORKFLOW_ID, "reason": "nothing to disable"}, config=_config()
            )

        assert result["success"] is True
        assert result["data"] == {"disabled": False}


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

        assert result["success"] is True
        stored = store.documents[(WORKFLOW_ID, USER_ID)]
        assert result["data"] == {
            "playbook_id": stored.playbook_id,
            "steps": len(stored.steps),
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
        ):
            result = await write_playbook.ainvoke(NEW_ARGS, config=_config())

        assert result["success"] is False
        assert result["error"] == "write_failed"
        assert "mongo down" in result["message"]

    async def test_reading_a_workflow_without_a_playbook_says_so_without_failing(
        self, store: _FakePlaybookStore
    ) -> None:
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await read_playbook.ainvoke({"workflow_id": WORKFLOW_ID}, config=_config())

        assert result["success"] is True
        assert result["data"] == {"exists": False}

    async def test_a_read_failure_is_reported_as_a_failure(self, store: _FakePlaybookStore) -> None:
        store.get_for_workflow = AsyncMock(side_effect=RuntimeError("mongo down"))

        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await read_playbook.ainvoke({"workflow_id": WORKFLOW_ID}, config=_config())

        assert result["success"] is False
        assert result["error"] == "read_failed"

    async def test_a_disable_failure_is_reported_as_a_failure(
        self, store: _FakePlaybookStore
    ) -> None:
        store.delete_for_workflow = AsyncMock(side_effect=RuntimeError("mongo down"))

        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await disable_playbook.ainvoke(
                {"workflow_id": WORKFLOW_ID, "reason": "r"}, config=_config()
            )

        assert result["success"] is False
        assert result["error"] == "disable_failed"
