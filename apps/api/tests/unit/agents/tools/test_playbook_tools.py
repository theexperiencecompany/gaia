"""The three playbook tools, against a real parser and a fake collection.

Only the two seams are stood in for: the workflow lookup and the playbook
collection. The parse-and-validate path the tools gate on is the real one, so a
rejected write is rejected for the reason production would reject it.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import BaseTool, tool
import pytest

from app.agents.tools.playbook_tools import disable_playbook, read_playbook, write_playbook
from app.models.playbook_models import PlaybookDocument, PlaybookRunStatus
from app.models.workflow_models import TriggerConfig, TriggerType, WorkflowDocument

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


def _existing(store: _FakePlaybookStore, raw_yaml: str) -> PlaybookDocument:
    now = datetime.now(UTC)
    document = PlaybookDocument(
        playbook_id="pb_existing",
        workflow_id=WORKFLOW_ID,
        user_id=USER_ID,
        workflow_hash="stale",
        raw_yaml=raw_yaml,
        description="Old",
        steps=[{"id": "one", "tool": "list_events", "args": {"calendar_id": "primary"}}],
        synthesize="Old synthesis.",
        last_run_status=PlaybookRunStatus.SUCCESS,
        created_at=now,
        updated_at=now,
    )
    store.documents[(WORKFLOW_ID, USER_ID)] = document
    return document


NEW_YAML = """
description: Read the day's events
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
synthesize: Say what is on today.
"""

OLD_YAML = (
    "description: Old\nsteps:\n  - id: one\n    tool: list_events\nsynthesize: Old synthesis.\n"
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
    async def test_invalid_yaml_writes_nothing_and_returns_the_error(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        before = _existing(store, OLD_YAML)
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(
                {"workflow_id": WORKFLOW_ID, "yaml": "description: [unclosed\nsteps:"},
                config=_config(),
            )

        assert result["success"] is False
        assert result["error"] == "invalid_playbook"
        assert "YAML" in result["message"]
        assert store.documents[(WORKFLOW_ID, USER_ID)] == before

    async def test_playbook_failing_validation_writes_nothing(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(
                {
                    "workflow_id": WORKFLOW_ID,
                    "yaml": "description: d\nsteps:\n  - id: one\n    tool: send_owl\nsynthesize: s\n",
                },
                config=_config(),
            )

        assert result["success"] is False
        assert "send_owl" in result["message"]
        assert store.documents == {}

    async def test_valid_write_overwrites_the_existing_playbook(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        _existing(store, OLD_YAML)
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
            patch(f"{PARSER_MODULE}.get_tool_registry", return_value=_FakeRegistry()),
        ):
            result = await write_playbook.ainvoke(
                {"workflow_id": WORKFLOW_ID, "yaml": NEW_YAML}, config=_config()
            )

        assert result["success"] is True
        assert len(store.documents) == 1
        stored = store.documents[(WORKFLOW_ID, USER_ID)]
        assert stored.raw_yaml == NEW_YAML
        assert stored.description == "Read the day's events"
        assert stored.workflow_hash != "stale"

    async def test_unknown_workflow_is_refused(
        self, store: _FakePlaybookStore, workflows: MagicMock
    ) -> None:
        workflows.get_for_user = AsyncMock(return_value=None)
        with (
            patch(f"{TOOLS_MODULE}.playbook_repository", store),
            patch(f"{TOOLS_MODULE}.workflow_repository", workflows),
        ):
            result = await write_playbook.ainvoke(
                {"workflow_id": WORKFLOW_ID, "yaml": NEW_YAML}, config=_config()
            )

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
        _existing(store, OLD_YAML)
        with patch(f"{TOOLS_MODULE}.playbook_repository", store):
            result = await read_playbook.ainvoke({"workflow_id": WORKFLOW_ID}, config=_config())

        assert result["data"]["yaml"] == OLD_YAML
        assert result["data"]["last_run_used_it"] is True
        assert result["data"]["last_run_status"] == "success"


@pytest.mark.unit
class TestDisablePlaybook:
    async def test_disabling_removes_the_playbook(self, store: _FakePlaybookStore) -> None:
        _existing(store, OLD_YAML)
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
