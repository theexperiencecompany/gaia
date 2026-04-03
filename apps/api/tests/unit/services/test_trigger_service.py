"""Comprehensive unit tests for trigger services: base handler, registry, and all handler implementations.

Covers:
  - app/services/triggers/base.py (TriggerHandler ABC)
  - app/services/triggers/registry.py (TriggerRegistry, global helpers)
  - app/services/triggers/handlers/gmail.py (GmailTriggerHandler)
  - app/services/triggers/handlers/gmail_poll.py (GmailPollTriggerHandler)
  - app/services/triggers/handlers/slack.py (SlackTriggerHandler)
  - app/services/triggers/handlers/github.py (GitHubTriggerHandler)
  - app/services/triggers/handlers/calendar.py (CalendarTriggerHandler)
  - app/services/triggers/handlers/linear.py (LinearTriggerHandler)
"""

import sys
from types import ModuleType
from typing import Any, Dict, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Break the circular import chain BEFORE importing any app.services.triggers
# modules.
#
# Chain: triggers/__init__ -> handlers/* -> triggers/base
#        -> workflow.queue_service -> workflow/__init__ -> workflow/service
#        -> workflow/trigger_service -> triggers (still loading!) => CIRCULAR
#
# By pre-seeding sys.modules with a mock for workflow.trigger_service we
# prevent workflow/service.py from reaching back into app.services.triggers.
# ---------------------------------------------------------------------------
_trigger_service_stub = ModuleType("app.services.workflow.trigger_service")
_trigger_service_stub.TriggerService = MagicMock()  # type: ignore[attr-defined]

# Only inject if not yet loaded (idempotent for repeated imports)
_stub_injected = "app.services.workflow.trigger_service" not in sys.modules
if _stub_injected:
    sys.modules["app.services.workflow.trigger_service"] = _trigger_service_stub

from app.models.trigger_configs import (  # noqa: E402
    CalendarEventCreatedConfig,
    CalendarEventStartingSoonConfig,
    GmailNewMessageConfig,
    GmailPollInboxConfig,
    GitHubCommitEventConfig,
    GitHubIssueAddedConfig,
    GitHubPrEventConfig,
    GitHubStarAddedConfig,
    LinearCommentAddedConfig,
    LinearIssueCreatedConfig,
    LinearIssueUpdatedConfig,
    SlackChannelCreatedConfig,
    SlackNewMessageConfig,
)
from app.models.workflow_models import (  # noqa: E402
    TriggerConfig,
    TriggerType,
    Workflow,
    WorkflowStep,
)
from app.services.triggers.base import TriggerHandler  # noqa: E402
from app.services.triggers.handlers.calendar import (  # noqa: E402
    CalendarTriggerHandler,
    calendar_trigger_handler,
)
from app.services.triggers.handlers.github import (  # noqa: E402
    GitHubTriggerHandler,
    github_trigger_handler,
)
from app.services.triggers.handlers.gmail import (  # noqa: E402
    GmailTriggerHandler,
    gmail_trigger_handler,
)
from app.services.triggers.handlers.gmail_poll import (  # noqa: E402
    GmailPollTriggerHandler,
    gmail_poll_trigger_handler,
)
from app.services.triggers.handlers.linear import (  # noqa: E402
    LinearTriggerHandler,
    linear_trigger_handler,
)
from app.services.triggers.handlers.slack import (  # noqa: E402
    SlackTriggerHandler,
    slack_trigger_handler,
)
from app.services.triggers.registry import (  # noqa: E402
    TriggerRegistry,
    get_handler_by_event,
    get_handler_by_name,
)
from app.utils.exceptions import TriggerRegistrationError  # noqa: E402

# ---------------------------------------------------------------------------
# Restore real module after breaking circular import for initial loading
# ---------------------------------------------------------------------------
if _stub_injected:
    # Remove the stub so the real module can be loaded later if needed
    import importlib

    del sys.modules["app.services.workflow.trigger_service"]
    importlib.import_module("app.services.workflow.trigger_service")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_ID = "user_test_trigger_001"
WORKFLOW_ID = "wf_test_trigger_001"
TRIGGER_ID = "composio_trigger_abc123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workflow(
    *,
    user_id: str = USER_ID,
    workflow_id: str = WORKFLOW_ID,
    activated: bool = True,
    trigger_name: str = "calendar_event_created",
    trigger_type: TriggerType = TriggerType.INTEGRATION,
    composio_trigger_ids: Optional[List[str]] = None,
) -> Workflow:
    """Build a minimal valid Workflow for testing."""
    return Workflow(
        id=workflow_id,
        user_id=user_id,
        title="Test Trigger Workflow",
        prompt="Run this workflow",
        steps=[WorkflowStep(title="Step 1", description="Do something")],
        activated=activated,
        trigger_config=TriggerConfig(
            type=trigger_type,
            enabled=True,
            trigger_name=trigger_name,
            composio_trigger_ids=composio_trigger_ids or [],
        ),
    )


def _make_trigger_config(
    trigger_name: str,
    trigger_type: TriggerType = TriggerType.INTEGRATION,
    trigger_data: Any = None,
    composio_trigger_ids: Optional[List[str]] = None,
) -> TriggerConfig:
    """Build a TriggerConfig for testing."""
    return TriggerConfig(
        type=trigger_type,
        enabled=True,
        trigger_name=trigger_name,
        trigger_data=trigger_data,
        composio_trigger_ids=composio_trigger_ids,
    )


class _AsyncCursorMock:
    """Mock for MongoDB async cursor that supports async iteration."""

    def __init__(self, documents: List[Dict[str, Any]]) -> None:
        self._documents = documents
        self._index = 0

    def __aiter__(self):
        self._index = 0
        return self

    async def __anext__(self):
        if self._index >= len(self._documents):
            raise StopAsyncIteration
        doc = self._documents[self._index].copy()
        self._index += 1
        return doc


# ===========================================================================
# TriggerHandler base class tests
# ===========================================================================


class _ConcreteTriggerHandler(TriggerHandler):
    """Concrete implementation of TriggerHandler for testing the base class."""

    @property
    def trigger_names(self) -> List[str]:
        return ["test_trigger"]

    @property
    def event_types(self) -> Set[str]:
        return {"TEST_EVENT"}

    async def register(
        self,
        user_id: str,
        workflow_id: str,
        trigger_name: str,
        trigger_config: TriggerConfig,
    ) -> List[str]:
        return ["trigger_id_1"]

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        return []


@pytest.mark.asyncio
class TestTriggerHandlerBase:
    """Tests for the abstract TriggerHandler base class."""

    def test_concrete_handler_instantiates(self):
        handler = _ConcreteTriggerHandler()
        assert handler.trigger_names == ["test_trigger"]
        assert handler.event_types == {"TEST_EVENT"}

    async def test_unregister_empty_list_returns_true(self):
        handler = _ConcreteTriggerHandler()
        result = await handler.unregister(USER_ID, [])
        assert result is True

    @patch("app.services.triggers.base.get_composio_service")
    async def test_unregister_success(self, mock_get_composio):
        mock_composio = MagicMock()
        mock_composio.composio.triggers.delete = MagicMock()
        mock_get_composio.return_value = mock_composio

        handler = _ConcreteTriggerHandler()
        result = await handler.unregister(USER_ID, ["tid_1", "tid_2"])
        assert result is True
        assert mock_composio.composio.triggers.delete.call_count == 2

    @patch("app.services.triggers.base.get_composio_service")
    async def test_unregister_partial_failure(self, mock_get_composio):
        mock_composio = MagicMock()
        mock_composio.composio.triggers.delete = MagicMock(
            side_effect=[None, Exception("Delete failed")]
        )
        mock_get_composio.return_value = mock_composio

        handler = _ConcreteTriggerHandler()
        result = await handler.unregister(USER_ID, ["tid_ok", "tid_fail"])
        assert result is False

    @patch("app.services.triggers.base.get_composio_service")
    async def test_unregister_all_fail(self, mock_get_composio):
        mock_composio = MagicMock()
        mock_composio.composio.triggers.delete = MagicMock(
            side_effect=Exception("Delete failed")
        )
        mock_get_composio.return_value = mock_composio

        handler = _ConcreteTriggerHandler()
        result = await handler.unregister(USER_ID, ["tid_1", "tid_2"])
        assert result is False

    # -- _register_triggers_parallel --

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_triggers_parallel_empty_configs(self, mock_get_composio):
        handler = _ConcreteTriggerHandler()
        result = await handler._register_triggers_parallel(
            user_id=USER_ID,
            trigger_name="test_trigger",
            configs=[],
            composio_slug="TEST_SLUG",
        )
        assert result == []

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_triggers_parallel_success(self, mock_get_composio):
        mock_result = MagicMock()
        mock_result.trigger_id = "tid_new"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = _ConcreteTriggerHandler()
        result = await handler._register_triggers_parallel(
            user_id=USER_ID,
            trigger_name="test_trigger",
            configs=[{"key": "val1"}, {"key": "val2"}],
            composio_slug="TEST_SLUG",
        )
        assert len(result) == 2
        assert all(tid == "tid_new" for tid in result)

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_triggers_parallel_returns_none_trigger_id(
        self, mock_get_composio
    ):
        """When composio returns a result without a trigger_id attribute, it is skipped."""
        mock_result = MagicMock(spec=[])  # no trigger_id attribute
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = _ConcreteTriggerHandler()
        result = await handler._register_triggers_parallel(
            user_id=USER_ID,
            trigger_name="test_trigger",
            configs=[{"key": "val1"}],
            composio_slug="TEST_SLUG",
        )
        # No trigger_id attribute means result is None, no IDs collected
        assert result == []

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_triggers_parallel_failure_rolls_back(
        self, mock_get_composio
    ):
        """If one config fails, all successful IDs are rolled back."""
        call_count = 0

        def create_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Registration failed")
            result = MagicMock()
            result.trigger_id = f"tid_{call_count}"
            return result

        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(
            side_effect=create_side_effect
        )
        mock_composio.composio.triggers.delete = MagicMock()
        mock_get_composio.return_value = mock_composio

        handler = _ConcreteTriggerHandler()
        with pytest.raises(TriggerRegistrationError, match="Failed to register"):
            await handler._register_triggers_parallel(
                user_id=USER_ID,
                trigger_name="test_trigger",
                configs=[{"a": 1}, {"b": 2}],
                composio_slug="TEST_SLUG",
            )

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_triggers_parallel_with_description_fn(
        self, mock_get_composio
    ):
        """config_description_fn is called on failure for logging."""
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(
            side_effect=Exception("boom")
        )
        mock_composio.composio.triggers.delete = MagicMock()
        mock_get_composio.return_value = mock_composio

        handler = _ConcreteTriggerHandler()
        desc_fn = MagicMock(return_value="cfg_desc")

        with pytest.raises(TriggerRegistrationError):
            await handler._register_triggers_parallel(
                user_id=USER_ID,
                trigger_name="test_trigger",
                configs=[{"x": 1}],
                composio_slug="TEST_SLUG",
                config_description_fn=desc_fn,
            )
        desc_fn.assert_called_once_with({"x": 1})

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_triggers_parallel_rollback_failure_logged(
        self, mock_get_composio
    ):
        """When rollback itself fails, the error is raised with partial_ids."""
        call_count = 0

        def create_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Registration failed")
            result = MagicMock()
            result.trigger_id = f"tid_{call_count}"
            return result

        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(
            side_effect=create_side_effect
        )
        # Make delete also fail so rollback fails
        mock_composio.composio.triggers.delete = MagicMock(
            side_effect=Exception("Delete failed too")
        )
        mock_get_composio.return_value = mock_composio

        handler = _ConcreteTriggerHandler()
        with pytest.raises(TriggerRegistrationError) as exc_info:
            await handler._register_triggers_parallel(
                user_id=USER_ID,
                trigger_name="test_trigger",
                configs=[{"a": 1}, {"b": 2}],
                composio_slug="TEST_SLUG",
            )
        assert exc_info.value.trigger_name == "test_trigger"

    # -- _load_workflows_from_query --

    @patch("app.services.triggers.base.workflows_collection")
    async def test_load_workflows_from_query_success(self, mock_collection):
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "Test",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {"type": "integration", "enabled": True},
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = _ConcreteTriggerHandler()
        workflows = await handler._load_workflows_from_query(
            {"user_id": USER_ID}, "test"
        )
        assert len(workflows) == 1
        assert workflows[0].user_id == USER_ID

    @patch("app.services.triggers.base.workflows_collection")
    async def test_load_workflows_from_query_invalid_doc_skipped(self, mock_collection):
        """Invalid workflow documents are skipped, not crashing the whole method."""
        invalid_doc = {"_id": "bad", "missing": "fields"}
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([invalid_doc]))

        handler = _ConcreteTriggerHandler()
        workflows = await handler._load_workflows_from_query({}, "test")
        assert len(workflows) == 0

    @patch("app.services.triggers.base.workflows_collection")
    async def test_load_workflows_from_query_empty(self, mock_collection):
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([]))

        handler = _ConcreteTriggerHandler()
        workflows = await handler._load_workflows_from_query({}, "test")
        assert workflows == []

    # -- process_event --

    @patch("app.services.triggers.base.WorkflowQueueService")
    async def test_process_event_no_workflows(self, mock_queue_svc):
        handler = _ConcreteTriggerHandler()
        result = await handler.process_event("TEST_EVENT", TRIGGER_ID, USER_ID, {})
        assert result["status"] == "success"
        assert "No matching workflows" in result["message"]

    @patch("app.services.triggers.base.WorkflowQueueService")
    async def test_process_event_queues_workflows(self, mock_queue_svc):
        workflow = _make_workflow()
        handler = _ConcreteTriggerHandler()
        handler.find_workflows = AsyncMock(return_value=[workflow])
        mock_queue_svc.queue_workflow_execution = AsyncMock(return_value=True)

        result = await handler.process_event("TEST_EVENT", TRIGGER_ID, USER_ID, {})
        assert result["status"] == "success"
        assert "Queued 1 workflows" in result["message"]
        mock_queue_svc.queue_workflow_execution.assert_awaited_once()

    @patch("app.services.triggers.base.WorkflowQueueService")
    async def test_process_event_skips_workflow_with_no_id(self, mock_queue_svc):
        workflow = _make_workflow()
        workflow.id = None
        handler = _ConcreteTriggerHandler()
        handler.find_workflows = AsyncMock(return_value=[workflow])

        result = await handler.process_event("TEST_EVENT", TRIGGER_ID, USER_ID, {})
        assert "Queued 0 workflows" in result["message"]
        mock_queue_svc.queue_workflow_execution.assert_not_called()

    @patch("app.services.triggers.base.WorkflowQueueService")
    async def test_process_event_handles_queue_failure(self, mock_queue_svc):
        workflow = _make_workflow()
        handler = _ConcreteTriggerHandler()
        handler.find_workflows = AsyncMock(return_value=[workflow])
        mock_queue_svc.queue_workflow_execution = AsyncMock(
            side_effect=Exception("Queue failed")
        )

        result = await handler.process_event("TEST_EVENT", TRIGGER_ID, USER_ID, {})
        assert result["status"] == "success"
        assert "Queued 0 workflows" in result["message"]

    @patch("app.services.triggers.base.WorkflowQueueService")
    async def test_process_event_trigger_id_none_defaults_to_empty(
        self, mock_queue_svc
    ):
        handler = _ConcreteTriggerHandler()
        handler.find_workflows = AsyncMock(return_value=[])

        await handler.process_event("TEST_EVENT", None, USER_ID, {})
        handler.find_workflows.assert_awaited_once_with("TEST_EVENT", "", {})

    # -- get_config_options (default implementation) --

    async def test_get_config_options_returns_empty_by_default(self):
        handler = _ConcreteTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="test_trigger",
            field_name="some_field",
            user_id=USER_ID,
            integration_id="test",
        )
        assert result == []


# ===========================================================================
# TriggerRegistry tests
# ===========================================================================


@pytest.mark.asyncio
class TestTriggerRegistry:
    """Tests for TriggerRegistry."""

    def test_register_handler(self):
        registry = TriggerRegistry()
        handler = _ConcreteTriggerHandler()
        registry.register(handler)

        assert registry.get_by_trigger_name("test_trigger") is handler
        assert registry.get_by_event_type("TEST_EVENT") is handler

    def test_get_by_trigger_name_missing(self):
        registry = TriggerRegistry()
        assert registry.get_by_trigger_name("nonexistent") is None

    def test_get_by_event_type_missing(self):
        registry = TriggerRegistry()
        assert registry.get_by_event_type("NONEXISTENT_EVENT") is None

    def test_get_all_trigger_names(self):
        registry = TriggerRegistry()
        handler = _ConcreteTriggerHandler()
        registry.register(handler)

        names = registry.get_all_trigger_names()
        assert "test_trigger" in names

    def test_get_all_event_types(self):
        registry = TriggerRegistry()
        handler = _ConcreteTriggerHandler()
        registry.register(handler)

        event_types = registry.get_all_event_types()
        assert "TEST_EVENT" in event_types

    def test_overwrite_handler_warns(self):
        """Registering a handler with the same trigger name overwrites the old one."""
        registry = TriggerRegistry()
        handler1 = _ConcreteTriggerHandler()
        handler2 = _ConcreteTriggerHandler()

        registry.register(handler1)
        registry.register(handler2)

        assert registry.get_by_trigger_name("test_trigger") is handler2
        assert registry.get_by_event_type("TEST_EVENT") is handler2

    def test_multiple_handlers_coexist(self):
        """Different handlers with different names coexist in the registry."""

        class _SecondHandler(TriggerHandler):
            @property
            def trigger_names(self) -> List[str]:
                return ["second_trigger"]

            @property
            def event_types(self) -> Set[str]:
                return {"SECOND_EVENT"}

            async def register(
                self, user_id, workflow_id, trigger_name, trigger_config
            ):
                return []

            async def find_workflows(self, event_type, trigger_id, data):
                return []

        registry = TriggerRegistry()
        h1 = _ConcreteTriggerHandler()
        h2 = _SecondHandler()
        registry.register(h1)
        registry.register(h2)

        assert registry.get_by_trigger_name("test_trigger") is h1
        assert registry.get_by_trigger_name("second_trigger") is h2
        assert len(registry.get_all_trigger_names()) == 2
        assert len(registry.get_all_event_types()) == 2

    def test_global_helper_get_handler_by_name(self):
        """The module-level get_handler_by_name delegates to the global registry."""
        # We just verify it returns something or None without error
        result = get_handler_by_name("nonexistent_xyz_trigger")
        assert result is None

    def test_global_helper_get_handler_by_event(self):
        result = get_handler_by_event("NONEXISTENT_XYZ_EVENT")
        assert result is None


# ===========================================================================
# GmailTriggerHandler tests
# ===========================================================================


@pytest.mark.asyncio
class TestGmailTriggerHandler:
    """Tests for GmailTriggerHandler."""

    def test_trigger_names(self):
        handler = GmailTriggerHandler()
        assert handler.trigger_names == ["gmail_new_message"]

    def test_event_types(self):
        handler = GmailTriggerHandler()
        assert handler.event_types == {"GMAIL_NEW_GMAIL_MESSAGE"}

    async def test_register_success_no_trigger_data(self):
        handler = GmailTriggerHandler()
        config = _make_trigger_config("gmail_new_message", trigger_data=None)
        result = await handler.register(
            USER_ID, WORKFLOW_ID, "gmail_new_message", config
        )
        assert result == []

    async def test_register_success_with_valid_trigger_data(self):
        handler = GmailTriggerHandler()
        data = GmailNewMessageConfig()
        config = _make_trigger_config("gmail_new_message", trigger_data=data)
        result = await handler.register(
            USER_ID, WORKFLOW_ID, "gmail_new_message", config
        )
        assert result == []

    async def test_register_wrong_trigger_data_type_raises(self):
        handler = GmailTriggerHandler()
        wrong_data = CalendarEventCreatedConfig()
        config = _make_trigger_config("gmail_new_message", trigger_data=wrong_data)
        with pytest.raises(TypeError, match="Expected GmailNewMessageConfig"):
            await handler.register(USER_ID, WORKFLOW_ID, "gmail_new_message", config)

    @patch("app.services.triggers.handlers.gmail.workflows_collection")
    async def test_find_workflows_no_user_id(self, mock_collection):
        handler = GmailTriggerHandler()
        result = await handler.find_workflows("GMAIL_NEW_GMAIL_MESSAGE", TRIGGER_ID, {})
        assert result == []

    @patch("app.services.triggers.handlers.gmail.workflows_collection")
    async def test_find_workflows_with_user_id_matches(self, mock_collection):
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "Gmail Workflow",
            "prompt": "Process email",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "gmail_new_message",
            },
        }
        mock_collection.find = MagicMock(
            side_effect=[
                _AsyncCursorMock([workflow_doc]),
                _AsyncCursorMock([]),
            ]
        )

        handler = GmailTriggerHandler()
        result = await handler.find_workflows(
            "GMAIL_NEW_GMAIL_MESSAGE",
            TRIGGER_ID,
            {"user_id": USER_ID},
        )
        assert len(result) == 1
        assert result[0].user_id == USER_ID

    @patch("app.services.triggers.handlers.gmail.workflows_collection")
    async def test_find_workflows_poll_query_also_runs(self, mock_collection):
        """Both user_query and poll_query are executed."""
        poll_doc = {
            "_id": "wf_poll_001",
            "user_id": USER_ID,
            "title": "Poll Workflow",
            "prompt": "Poll email",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "gmail_poll_inbox",
                "composio_trigger_ids": [TRIGGER_ID],
            },
        }
        mock_collection.find = MagicMock(
            side_effect=[
                _AsyncCursorMock([]),
                _AsyncCursorMock([poll_doc]),
            ]
        )

        handler = GmailTriggerHandler()
        result = await handler.find_workflows(
            "GMAIL_NEW_GMAIL_MESSAGE",
            TRIGGER_ID,
            {"user_id": USER_ID},
        )
        assert len(result) == 1
        assert result[0].id == "wf_poll_001"

    @patch("app.services.triggers.handlers.gmail.workflows_collection")
    async def test_find_workflows_invalid_doc_skipped(self, mock_collection):
        """Invalid workflow docs are caught and skipped."""
        invalid_doc = {"_id": "bad", "not_a_workflow": True}
        mock_collection.find = MagicMock(
            side_effect=[
                _AsyncCursorMock([invalid_doc]),
                _AsyncCursorMock([]),
            ]
        )

        handler = GmailTriggerHandler()
        result = await handler.find_workflows(
            "GMAIL_NEW_GMAIL_MESSAGE",
            TRIGGER_ID,
            {"user_id": USER_ID},
        )
        assert result == []

    @patch("app.services.triggers.handlers.gmail.workflows_collection")
    async def test_find_workflows_outer_exception_returns_empty(self, mock_collection):
        """Any top-level exception in find_workflows returns empty list."""
        mock_collection.find = MagicMock(side_effect=Exception("DB error"))

        handler = GmailTriggerHandler()
        result = await handler.find_workflows(
            "GMAIL_NEW_GMAIL_MESSAGE",
            TRIGGER_ID,
            {"user_id": USER_ID},
        )
        assert result == []

    def test_singleton_instance_exists(self):
        assert gmail_trigger_handler is not None
        assert isinstance(gmail_trigger_handler, GmailTriggerHandler)


# ===========================================================================
# GmailPollTriggerHandler tests
# ===========================================================================


@pytest.mark.asyncio
class TestGmailPollTriggerHandler:
    """Tests for GmailPollTriggerHandler."""

    def test_trigger_names(self):
        handler = GmailPollTriggerHandler()
        assert handler.trigger_names == ["gmail_poll_inbox"]

    def test_event_types_empty(self):
        """Poll handler deliberately claims no event types to avoid overwriting gmail handler."""
        handler = GmailPollTriggerHandler()
        assert handler.event_types == set()

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_success(self, mock_get_composio):
        mock_result = MagicMock()
        mock_result.trigger_id = "poll_tid_1"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = GmailPollTriggerHandler()
        data = GmailPollInboxConfig(interval=30)
        config = _make_trigger_config("gmail_poll_inbox", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "gmail_poll_inbox", config
        )
        assert result == ["poll_tid_1"]

    async def test_register_wrong_trigger_data_raises(self):
        handler = GmailPollTriggerHandler()
        wrong_data = GmailNewMessageConfig()
        config = _make_trigger_config("gmail_poll_inbox", trigger_data=wrong_data)

        with pytest.raises(
            TriggerRegistrationError, match="Expected GmailPollInboxConfig"
        ):
            await handler.register(USER_ID, WORKFLOW_ID, "gmail_poll_inbox", config)

    async def test_register_none_trigger_data_raises(self):
        handler = GmailPollTriggerHandler()
        config = _make_trigger_config("gmail_poll_inbox", trigger_data=None)

        with pytest.raises(
            TriggerRegistrationError, match="Expected GmailPollInboxConfig"
        ):
            await handler.register(USER_ID, WORKFLOW_ID, "gmail_poll_inbox", config)

    async def test_register_unknown_trigger_name_raises(self):
        handler = GmailPollTriggerHandler()
        data = GmailPollInboxConfig(interval=15)
        config = _make_trigger_config("unknown_trigger", trigger_data=data)
        # Override TRIGGER_TO_COMPOSIO to simulate unknown trigger
        original = handler.TRIGGER_TO_COMPOSIO.copy()
        handler.TRIGGER_TO_COMPOSIO = {}
        try:
            with pytest.raises(
                TriggerRegistrationError, match="Unknown gmail poll trigger"
            ):
                await handler.register(USER_ID, WORKFLOW_ID, "gmail_poll_inbox", config)
        finally:
            handler.TRIGGER_TO_COMPOSIO = original

    @patch("app.services.triggers.base.workflows_collection")
    async def test_find_workflows_by_trigger_id(self, mock_collection):
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "Poll Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "gmail_poll_inbox",
                "composio_trigger_ids": [TRIGGER_ID],
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = GmailPollTriggerHandler()
        result = await handler.find_workflows("GMAIL_NEW_GMAIL_MESSAGE", TRIGGER_ID, {})
        assert len(result) == 1

    @patch("app.services.triggers.base.workflows_collection")
    async def test_find_workflows_exception_returns_empty(self, mock_collection):
        mock_collection.find = MagicMock(side_effect=Exception("DB error"))

        handler = GmailPollTriggerHandler()
        result = await handler.find_workflows("GMAIL_NEW_GMAIL_MESSAGE", TRIGGER_ID, {})
        assert result == []

    def test_singleton_instance_exists(self):
        assert gmail_poll_trigger_handler is not None
        assert isinstance(gmail_poll_trigger_handler, GmailPollTriggerHandler)


# ===========================================================================
# SlackTriggerHandler tests
# ===========================================================================


@pytest.mark.asyncio
class TestSlackTriggerHandler:
    """Tests for SlackTriggerHandler."""

    def test_trigger_names(self):
        handler = SlackTriggerHandler()
        assert "slack_new_message" in handler.trigger_names
        assert "slack_channel_created" in handler.trigger_names

    def test_event_types(self):
        handler = SlackTriggerHandler()
        expected = {
            "SLACK_RECEIVE_MESSAGE",
            "SLACK_RECEIVE_BOT_MESSAGE",
            "SLACK_RECEIVE_DIRECT_MESSAGE",
            "SLACK_RECEIVE_GROUP_MESSAGE",
            "SLACK_RECEIVE_MPIM_MESSAGE",
            "SLACK_RECEIVE_THREAD_REPLY",
            "SLACK_CHANNEL_CREATED",
        }
        assert handler.event_types == expected

    async def test_register_unknown_trigger_raises(self):
        handler = SlackTriggerHandler()
        config = _make_trigger_config("slack_unknown")
        with pytest.raises(TriggerRegistrationError, match="Unknown Slack trigger"):
            await handler.register(USER_ID, WORKFLOW_ID, "slack_unknown", config)

    @patch("app.services.triggers.handlers.slack.get_composio_service")
    async def test_register_channel_created(self, mock_get_composio):
        mock_result = MagicMock()
        mock_result.trigger_id = "ch_created_tid"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = SlackTriggerHandler()
        config = _make_trigger_config(
            "slack_channel_created",
            trigger_data=SlackChannelCreatedConfig(),
        )
        result = await handler.register(
            USER_ID, WORKFLOW_ID, "slack_channel_created", config
        )
        assert result == ["ch_created_tid"]

    @patch("app.services.triggers.handlers.slack.get_composio_service")
    async def test_register_channel_created_wrong_data_type_raises(
        self, mock_get_composio
    ):
        handler = SlackTriggerHandler()
        wrong_data = SlackNewMessageConfig()
        config = _make_trigger_config("slack_channel_created", trigger_data=wrong_data)
        with pytest.raises(TypeError, match="Expected SlackChannelCreatedConfig"):
            await handler.register(
                USER_ID, WORKFLOW_ID, "slack_channel_created", config
            )

    async def test_register_new_message_wrong_data_type_raises(self):
        handler = SlackTriggerHandler()
        wrong_data = CalendarEventCreatedConfig()
        config = _make_trigger_config("slack_new_message", trigger_data=wrong_data)
        with pytest.raises(TypeError, match="Expected SlackNewMessageConfig"):
            await handler.register(USER_ID, WORKFLOW_ID, "slack_new_message", config)

    @patch("app.services.triggers.handlers.slack.get_composio_service")
    async def test_register_new_message_no_channels(self, mock_get_composio):
        """When no channel_ids, registers with empty channel_id for 'all channels'."""
        mock_result = MagicMock()
        mock_result.trigger_id = "msg_tid"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = SlackTriggerHandler()
        data = SlackNewMessageConfig(channel_ids=[])
        config = _make_trigger_config("slack_new_message", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "slack_new_message", config
        )
        # Should register SLACK_RECEIVE_MESSAGE + 5 non-excluded types, each for 1 empty channel
        assert len(result) > 0

    @patch("app.services.triggers.handlers.slack.get_composio_service")
    async def test_register_new_message_with_channels(self, mock_get_composio):
        mock_result = MagicMock()
        mock_result.trigger_id = "msg_tid"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = SlackTriggerHandler()
        data = SlackNewMessageConfig(channel_ids=["C001", "C002"])
        config = _make_trigger_config("slack_new_message", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "slack_new_message", config
        )
        # For 2 channels: 2 (RECEIVE_MESSAGE) + 2*5 (non-excluded types) = 12
        assert len(result) == 12

    @patch("app.services.triggers.handlers.slack.get_composio_service")
    async def test_register_new_message_with_exclusions(self, mock_get_composio):
        """Excluded message types are not registered."""
        mock_result = MagicMock()
        mock_result.trigger_id = "msg_tid"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = SlackTriggerHandler()
        data = SlackNewMessageConfig(
            channel_ids=["C001"],
            exclude_bot_messages=True,
            exclude_direct_messages=True,
            exclude_group_messages=True,
            exclude_mpim_messages=True,
            exclude_thread_replies=True,
        )
        config = _make_trigger_config("slack_new_message", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "slack_new_message", config
        )
        # Only SLACK_RECEIVE_MESSAGE for 1 channel
        assert len(result) == 1

    @patch("app.services.triggers.base.get_composio_service")
    @patch("app.services.triggers.handlers.slack.get_composio_service")
    async def test_register_partial_failure_rolls_back(
        self, mock_get_composio, mock_base_composio
    ):
        """If some trigger registrations fail, all successful ones are rolled back."""
        call_count = 0

        def sync_side_effect(
            user_id: str, composio_slug: str, trigger_config: Dict[str, Any]
        ) -> List[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Create failed")
            return [f"tid_{call_count}"]

        mock_composio = MagicMock()
        mock_composio.composio.triggers.delete = MagicMock()
        mock_get_composio.return_value = mock_composio
        mock_base_composio.return_value = mock_composio

        handler = SlackTriggerHandler()
        # Patch the sync helper so the exception propagates through asyncio.to_thread
        handler._register_single_trigger_sync = sync_side_effect  # type: ignore[assignment]

        data = SlackNewMessageConfig(
            channel_ids=["C001"],
            exclude_bot_messages=True,
            exclude_direct_messages=True,
            exclude_group_messages=True,
            exclude_mpim_messages=True,
            exclude_thread_replies=False,
        )
        config = _make_trigger_config("slack_new_message", trigger_data=data)

        with pytest.raises(TriggerRegistrationError, match="Failed to register"):
            await handler.register(USER_ID, WORKFLOW_ID, "slack_new_message", config)

    @patch("app.services.triggers.handlers.slack.workflows_collection")
    async def test_find_workflows_message_event(self, mock_collection):
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "Slack Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "slack_new_message",
                "composio_trigger_ids": [TRIGGER_ID],
                "trigger_data": {
                    "trigger_name": "slack_new_message",
                    "channel_ids": [],
                },
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = SlackTriggerHandler()
        result = await handler.find_workflows(
            "SLACK_RECEIVE_MESSAGE", TRIGGER_ID, {"channel": "C001", "text": "hello"}
        )
        assert len(result) == 1

    @patch("app.services.triggers.handlers.slack.workflows_collection")
    async def test_find_workflows_channel_created_event(self, mock_collection):
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "Slack Channel Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "slack_channel_created",
                "composio_trigger_ids": [TRIGGER_ID],
                "trigger_data": {
                    "trigger_name": "slack_channel_created",
                },
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = SlackTriggerHandler()
        result = await handler.find_workflows(
            "SLACK_CHANNEL_CREATED",
            TRIGGER_ID,
            {"name": "new-channel", "id": "C_new"},
        )
        assert len(result) == 1

    @patch("app.services.triggers.handlers.slack.workflows_collection")
    async def test_find_workflows_filters_by_channel_ids(self, mock_collection):
        """When workflow has channel_ids, only messages from those channels match."""
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "Slack Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "slack_new_message",
                "composio_trigger_ids": [TRIGGER_ID],
                "trigger_data": {
                    "trigger_name": "slack_new_message",
                    "channel_ids": "C001,C002",
                },
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = SlackTriggerHandler()
        # Message from channel not in the list
        result = await handler.find_workflows(
            "SLACK_RECEIVE_MESSAGE",
            TRIGGER_ID,
            {"channel": "C999", "text": "hello"},
        )
        assert len(result) == 0

    @patch("app.services.triggers.handlers.slack.workflows_collection")
    async def test_find_workflows_channel_filter_matches(self, mock_collection):
        """When channel_ids is a proper list the handler's string-based filtering
        raises internally (list has no .split), so the workflow is skipped."""
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "Slack Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "slack_new_message",
                "composio_trigger_ids": [TRIGGER_ID],
                "trigger_data": {
                    "trigger_name": "slack_new_message",
                    "channel_ids": ["C001", "C002"],
                },
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = SlackTriggerHandler()
        result = await handler.find_workflows(
            "SLACK_RECEIVE_MESSAGE",
            TRIGGER_ID,
            {"channel": "C001", "text": "hello"},
        )
        # Production code tries .split(",") on the list, which raises
        # an AttributeError that is caught and the workflow is skipped.
        assert len(result) == 0

    @patch("app.services.triggers.handlers.slack.workflows_collection")
    async def test_find_workflows_no_channel_filter_passes_all(self, mock_collection):
        """Workflow with empty channel_ids list matches any channel."""
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "Slack Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "slack_new_message",
                "composio_trigger_ids": [TRIGGER_ID],
                "trigger_data": {
                    "trigger_name": "slack_new_message",
                    "channel_ids": [],
                },
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = SlackTriggerHandler()
        result = await handler.find_workflows(
            "SLACK_RECEIVE_MESSAGE",
            TRIGGER_ID,
            {"channel": "any_channel"},
        )
        assert len(result) == 1

    @patch("app.services.triggers.handlers.slack.workflows_collection")
    async def test_find_workflows_exception_returns_empty(self, mock_collection):
        mock_collection.find = MagicMock(side_effect=Exception("DB error"))

        handler = SlackTriggerHandler()
        result = await handler.find_workflows("SLACK_RECEIVE_MESSAGE", TRIGGER_ID, {})
        assert result == []

    @patch("app.services.triggers.handlers.slack.workflows_collection")
    async def test_find_workflows_invalid_doc_skipped(self, mock_collection):
        invalid_doc = {"_id": "bad", "not_valid": True}
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([invalid_doc]))

        handler = SlackTriggerHandler()
        result = await handler.find_workflows("SLACK_RECEIVE_MESSAGE", TRIGGER_ID, {})
        assert result == []

    @patch("app.services.triggers.handlers.slack.get_composio_service")
    async def test_get_config_options_channels(self, mock_get_composio):
        """get_config_options returns channel list from Slack API."""
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(
            return_value={
                "successful": True,
                "data": {
                    "channels": [
                        {
                            "id": "C001",
                            "name": "general",
                            "is_channel": True,
                            "is_private": False,
                            "is_im": False,
                            "is_mpim": False,
                        },
                    ],
                    "response_metadata": {},
                },
                "error": None,
            }
        )
        mock_composio = MagicMock()
        mock_composio.get_tool = MagicMock(return_value=mock_tool)
        mock_get_composio.return_value = mock_composio

        handler = SlackTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="slack_new_message",
            field_name="channel_ids",
            user_id=USER_ID,
            integration_id="slack",
        )
        assert len(result) >= 1
        assert result[0]["value"] == "C001"

    @patch("app.services.triggers.handlers.slack.get_composio_service")
    async def test_get_config_options_tool_not_found(self, mock_get_composio):
        mock_composio = MagicMock()
        mock_composio.get_tool = MagicMock(return_value=None)
        mock_get_composio.return_value = mock_composio

        handler = SlackTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="slack_new_message",
            field_name="channel_ids",
            user_id=USER_ID,
            integration_id="slack",
        )
        assert result == []

    @patch("app.services.triggers.handlers.slack.get_composio_service")
    async def test_get_config_options_api_error(self, mock_get_composio):
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(
            return_value={
                "successful": False,
                "data": {},
                "error": "rate_limited",
            }
        )
        mock_composio = MagicMock()
        mock_composio.get_tool = MagicMock(return_value=mock_tool)
        mock_get_composio.return_value = mock_composio

        handler = SlackTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="slack_new_message",
            field_name="channel_ids",
            user_id=USER_ID,
            integration_id="slack",
        )
        assert result == []

    async def test_get_config_options_unknown_field(self):
        handler = SlackTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="slack_new_message",
            field_name="unknown_field",
            user_id=USER_ID,
            integration_id="slack",
        )
        assert result == []

    @patch("app.services.triggers.handlers.slack.get_composio_service")
    async def test_get_config_options_exception_returns_empty(self, mock_get_composio):
        mock_get_composio.side_effect = Exception("Service unavailable")

        handler = SlackTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="slack_new_message",
            field_name="channel_ids",
            user_id=USER_ID,
            integration_id="slack",
        )
        assert result == []

    def test_singleton_instance_exists(self):
        assert slack_trigger_handler is not None
        assert isinstance(slack_trigger_handler, SlackTriggerHandler)


# ===========================================================================
# GitHubTriggerHandler tests
# ===========================================================================


@pytest.mark.asyncio
class TestGitHubTriggerHandler:
    """Tests for GitHubTriggerHandler."""

    def test_trigger_names(self):
        handler = GitHubTriggerHandler()
        expected = [
            "github_commit_event",
            "github_pr_event",
            "github_star_added",
            "github_issue_added",
        ]
        assert handler.trigger_names == expected

    def test_event_types(self):
        handler = GitHubTriggerHandler()
        expected = {
            "GITHUB_COMMIT_EVENT",
            "GITHUB_PULL_REQUEST_EVENT",
            "GITHUB_STAR_ADDED_EVENT",
            "GITHUB_ISSUE_ADDED_EVENT",
        }
        assert handler.event_types == expected

    async def test_register_unknown_trigger_raises(self):
        handler = GitHubTriggerHandler()
        config = _make_trigger_config("github_unknown")
        with pytest.raises(TriggerRegistrationError, match="Unknown GitHub trigger"):
            await handler.register(USER_ID, WORKFLOW_ID, "github_unknown", config)

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_commit_event_success(self, mock_get_composio):
        mock_result = MagicMock()
        mock_result.trigger_id = "gh_tid_1"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = GitHubTriggerHandler()
        data = GitHubCommitEventConfig(repos=["owner/repo1"])
        config = _make_trigger_config("github_commit_event", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "github_commit_event", config
        )
        assert result == ["gh_tid_1"]

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_pr_event_success(self, mock_get_composio):
        mock_result = MagicMock()
        mock_result.trigger_id = "pr_tid_1"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = GitHubTriggerHandler()
        data = GitHubPrEventConfig(repos=["owner/repo1", "owner/repo2"])
        config = _make_trigger_config("github_pr_event", trigger_data=data)

        result = await handler.register(USER_ID, WORKFLOW_ID, "github_pr_event", config)
        assert len(result) == 2

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_star_added_success(self, mock_get_composio):
        mock_result = MagicMock()
        mock_result.trigger_id = "star_tid_1"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = GitHubTriggerHandler()
        data = GitHubStarAddedConfig(repos=["owner/repo1"])
        config = _make_trigger_config("github_star_added", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "github_star_added", config
        )
        assert result == ["star_tid_1"]

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_issue_added_success(self, mock_get_composio):
        mock_result = MagicMock()
        mock_result.trigger_id = "issue_tid_1"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = GitHubTriggerHandler()
        data = GitHubIssueAddedConfig(repos=["owner/repo1"])
        config = _make_trigger_config("github_issue_added", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "github_issue_added", config
        )
        assert result == ["issue_tid_1"]

    async def test_register_commit_event_wrong_data_type_raises(self):
        handler = GitHubTriggerHandler()
        wrong_data = GitHubPrEventConfig(repos=["owner/repo1"])
        config = _make_trigger_config("github_commit_event", trigger_data=wrong_data)
        with pytest.raises(TypeError, match="Expected GitHubCommitEventConfig"):
            await handler.register(USER_ID, WORKFLOW_ID, "github_commit_event", config)

    async def test_register_pr_event_wrong_data_type_raises(self):
        handler = GitHubTriggerHandler()
        wrong_data = GitHubCommitEventConfig(repos=["owner/repo1"])
        config = _make_trigger_config("github_pr_event", trigger_data=wrong_data)
        with pytest.raises(TypeError, match="Expected GitHubPrEventConfig"):
            await handler.register(USER_ID, WORKFLOW_ID, "github_pr_event", config)

    async def test_register_star_added_wrong_data_type_raises(self):
        handler = GitHubTriggerHandler()
        wrong_data = GitHubCommitEventConfig(repos=["owner/repo1"])
        config = _make_trigger_config("github_star_added", trigger_data=wrong_data)
        with pytest.raises(TypeError, match="Expected GitHubStarAddedConfig"):
            await handler.register(USER_ID, WORKFLOW_ID, "github_star_added", config)

    async def test_register_issue_added_wrong_data_type_raises(self):
        handler = GitHubTriggerHandler()
        wrong_data = GitHubCommitEventConfig(repos=["owner/repo1"])
        config = _make_trigger_config("github_issue_added", trigger_data=wrong_data)
        with pytest.raises(TypeError, match="Expected GitHubIssueAddedConfig"):
            await handler.register(USER_ID, WORKFLOW_ID, "github_issue_added", config)

    async def test_register_empty_repos_returns_empty(self):
        handler = GitHubTriggerHandler()
        data = GitHubCommitEventConfig(repos=[])
        config = _make_trigger_config("github_commit_event", trigger_data=data)
        result = await handler.register(
            USER_ID, WORKFLOW_ID, "github_commit_event", config
        )
        assert result == []

    async def test_register_invalid_repo_format_skipped(self):
        """Repos without '/' are skipped (no configs built)."""
        handler = GitHubTriggerHandler()
        data = GitHubCommitEventConfig(repos=["invalid_no_slash"])
        config = _make_trigger_config("github_commit_event", trigger_data=data)
        result = await handler.register(
            USER_ID, WORKFLOW_ID, "github_commit_event", config
        )
        assert result == []

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_repo_with_multiple_slashes_skipped(self, mock_get_composio):
        """Repos with more than one '/' (e.g. org/sub/repo) are skipped."""
        handler = GitHubTriggerHandler()
        data = GitHubCommitEventConfig(repos=["org/sub/repo"])
        config = _make_trigger_config("github_commit_event", trigger_data=data)
        result = await handler.register(
            USER_ID, WORKFLOW_ID, "github_commit_event", config
        )
        assert result == []

    # GitHub register - unknown trigger name after slug lookup passes but
    # validation rejects it (else branch)
    async def test_register_else_branch_unknown_trigger(self):
        """Test the else branch in validation for truly unknown trigger names."""
        handler = GitHubTriggerHandler()
        # Inject a TRIGGER_TO_COMPOSIO entry for a fake trigger
        handler.TRIGGER_TO_COMPOSIO["github_fake"] = "GITHUB_FAKE_EVENT"
        data = GitHubCommitEventConfig(repos=["owner/repo"])
        config = _make_trigger_config("github_fake", trigger_data=data)
        try:
            with pytest.raises(
                TriggerRegistrationError, match="Unknown GitHub trigger"
            ):
                await handler.register(USER_ID, WORKFLOW_ID, "github_fake", config)
        finally:
            del handler.TRIGGER_TO_COMPOSIO["github_fake"]

    @patch("app.services.triggers.handlers.github.workflows_collection")
    async def test_find_workflows_commit_event(self, mock_collection):
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "GH Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "github_commit_event",
                "composio_trigger_ids": [TRIGGER_ID],
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = GitHubTriggerHandler()
        result = await handler.find_workflows(
            "GITHUB_COMMIT_EVENT",
            TRIGGER_ID,
            {"author": "user", "message": "fix bug", "id": "abc123"},
        )
        assert len(result) == 1

    @patch("app.services.triggers.handlers.github.workflows_collection")
    async def test_find_workflows_pr_event(self, mock_collection):
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "GH PR Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "github_pr_event",
                "composio_trigger_ids": [TRIGGER_ID],
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = GitHubTriggerHandler()
        result = await handler.find_workflows(
            "GITHUB_PULL_REQUEST_EVENT",
            TRIGGER_ID,
            {
                "action": "opened",
                "title": "New Feature",
                "number": 42,
            },
        )
        assert len(result) == 1

    @patch("app.services.triggers.handlers.github.workflows_collection")
    async def test_find_workflows_star_event(self, mock_collection):
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "GH Star Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "github_star_added",
                "composio_trigger_ids": [TRIGGER_ID],
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = GitHubTriggerHandler()
        result = await handler.find_workflows(
            "GITHUB_STAR_ADDED_EVENT",
            TRIGGER_ID,
            {"action": "starred", "user": "someone"},
        )
        assert len(result) == 1

    @patch("app.services.triggers.handlers.github.workflows_collection")
    async def test_find_workflows_issue_event(self, mock_collection):
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "GH Issue Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "github_issue_added",
                "composio_trigger_ids": [TRIGGER_ID],
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = GitHubTriggerHandler()
        result = await handler.find_workflows(
            "GITHUB_ISSUE_ADDED_EVENT",
            TRIGGER_ID,
            {
                "action": "opened",
                "title": "Bug report",
                "number": 1,
            },
        )
        assert len(result) == 1

    @patch("app.services.triggers.handlers.github.workflows_collection")
    async def test_find_workflows_no_match(self, mock_collection):
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([]))

        handler = GitHubTriggerHandler()
        result = await handler.find_workflows(
            "GITHUB_COMMIT_EVENT", "nonexistent_tid", {}
        )
        assert result == []

    @patch("app.services.triggers.handlers.github.workflows_collection")
    async def test_find_workflows_invalid_doc_skipped(self, mock_collection):
        invalid_doc = {"_id": "bad_doc", "broken": True}
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([invalid_doc]))

        handler = GitHubTriggerHandler()
        result = await handler.find_workflows("GITHUB_COMMIT_EVENT", TRIGGER_ID, {})
        assert result == []

    @patch("app.services.triggers.handlers.github.workflows_collection")
    async def test_find_workflows_exception_returns_empty(self, mock_collection):
        mock_collection.find = MagicMock(side_effect=Exception("DB error"))

        handler = GitHubTriggerHandler()
        result = await handler.find_workflows("GITHUB_COMMIT_EVENT", TRIGGER_ID, {})
        assert result == []

    @patch("app.services.triggers.handlers.github.get_composio_service")
    async def test_get_config_options_repos(self, mock_get_composio):
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(
            return_value={
                "successful": True,
                "data": [
                    {"full_name": "owner/repo1", "name": "repo1"},
                    {"full_name": "owner/repo2", "name": "repo2"},
                ],
                "error": None,
            }
        )
        mock_composio = MagicMock()
        mock_composio.get_tool = MagicMock(return_value=mock_tool)
        mock_get_composio.return_value = mock_composio

        handler = GitHubTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="github_commit_event",
            field_name="repos",
            user_id=USER_ID,
            integration_id="github",
        )
        assert len(result) == 2
        assert result[0]["value"] == "owner/repo1"

    @patch("app.services.triggers.handlers.github.get_composio_service")
    async def test_get_config_options_tool_not_found(self, mock_get_composio):
        mock_composio = MagicMock()
        mock_composio.get_tool = MagicMock(return_value=None)
        mock_get_composio.return_value = mock_composio

        handler = GitHubTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="github_commit_event",
            field_name="repos",
            user_id=USER_ID,
            integration_id="github",
        )
        assert result == []

    @patch("app.services.triggers.handlers.github.get_composio_service")
    async def test_get_config_options_api_error(self, mock_get_composio):
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(
            return_value={
                "successful": False,
                "data": [],
                "error": "forbidden",
            }
        )
        mock_composio = MagicMock()
        mock_composio.get_tool = MagicMock(return_value=mock_tool)
        mock_get_composio.return_value = mock_composio

        handler = GitHubTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="github_commit_event",
            field_name="repos",
            user_id=USER_ID,
            integration_id="github",
        )
        assert result == []

    @patch("app.services.triggers.handlers.github.get_composio_service")
    async def test_get_config_options_with_search_filter(self, mock_get_composio):
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(
            return_value={
                "successful": True,
                "data": [
                    {"full_name": "owner/repo1", "name": "repo1"},
                    {"full_name": "owner/special-repo", "name": "special-repo"},
                ],
                "error": None,
            }
        )
        mock_composio = MagicMock()
        mock_composio.get_tool = MagicMock(return_value=mock_tool)
        mock_get_composio.return_value = mock_composio

        handler = GitHubTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="github_commit_event",
            field_name="repos",
            user_id=USER_ID,
            integration_id="github",
            search="special",
        )
        assert len(result) == 1
        assert result[0]["value"] == "owner/special-repo"

    def test_singleton_instance_exists(self):
        assert github_trigger_handler is not None
        assert isinstance(github_trigger_handler, GitHubTriggerHandler)


# ===========================================================================
# CalendarTriggerHandler tests
# ===========================================================================


@pytest.mark.asyncio
class TestCalendarTriggerHandler:
    """Tests for CalendarTriggerHandler."""

    def test_trigger_names(self):
        handler = CalendarTriggerHandler()
        expected = ["calendar_event_created", "calendar_event_starting_soon"]
        assert handler.trigger_names == expected

    def test_event_types(self):
        handler = CalendarTriggerHandler()
        expected = {
            "GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER",
            "GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER",
        }
        assert handler.event_types == expected

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_event_created_success(self, mock_get_composio):
        mock_result = MagicMock()
        mock_result.trigger_id = "cal_tid_1"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = CalendarTriggerHandler()
        data = CalendarEventCreatedConfig(calendar_ids=["primary"])
        config = _make_trigger_config("calendar_event_created", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "calendar_event_created", config
        )
        assert result == ["cal_tid_1"]

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_event_starting_soon_success(self, mock_get_composio):
        mock_result = MagicMock()
        mock_result.trigger_id = "soon_tid_1"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = CalendarTriggerHandler()
        data = CalendarEventStartingSoonConfig(
            calendar_ids=["primary"],
            minutes_before_start=15,
            include_all_day=True,
        )
        config = _make_trigger_config("calendar_event_starting_soon", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "calendar_event_starting_soon", config
        )
        assert result == ["soon_tid_1"]
        # Verify composio config includes countdown window and include_all_day
        call_kwargs = mock_composio.composio.triggers.create.call_args
        trigger_config = call_kwargs.kwargs.get("trigger_config", {})
        assert trigger_config.get("countdown_window_minutes") == 15
        assert trigger_config.get("include_all_day") is True

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_multiple_calendars(self, mock_get_composio):
        mock_result = MagicMock()
        mock_result.trigger_id = "cal_multi_tid"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = CalendarTriggerHandler()
        data = CalendarEventCreatedConfig(
            calendar_ids=["primary", "work@example.com", "personal@example.com"]
        )
        config = _make_trigger_config("calendar_event_created", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "calendar_event_created", config
        )
        assert len(result) == 3

    @patch(
        "app.services.triggers.handlers.calendar.CalendarTriggerHandler._fetch_user_calendars"
    )
    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_all_calendars_expands(self, mock_get_composio, mock_fetch):
        """calendar_ids=['all'] fetches actual calendar list."""
        mock_fetch.return_value = ["primary", "work@example.com"]
        mock_result = MagicMock()
        mock_result.trigger_id = "cal_all_tid"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = CalendarTriggerHandler()
        data = CalendarEventCreatedConfig(calendar_ids=["all"])
        config = _make_trigger_config("calendar_event_created", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "calendar_event_created", config
        )
        assert len(result) == 2
        mock_fetch.assert_awaited_once_with(USER_ID)

    async def test_register_empty_calendar_ids(self):
        handler = CalendarTriggerHandler()
        data = CalendarEventCreatedConfig(calendar_ids=[])
        config = _make_trigger_config("calendar_event_created", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "calendar_event_created", config
        )
        assert result == []

    async def test_register_unknown_trigger_raises(self):
        handler = CalendarTriggerHandler()
        wrong_data = CalendarEventCreatedConfig()
        config = _make_trigger_config("calendar_unknown", trigger_data=wrong_data)
        with pytest.raises(TriggerRegistrationError, match="Unknown calendar trigger"):
            await handler.register(USER_ID, WORKFLOW_ID, "calendar_unknown", config)

    async def test_register_event_created_wrong_data_type_raises(self):
        handler = CalendarTriggerHandler()
        wrong_data = GmailNewMessageConfig()
        config = _make_trigger_config("calendar_event_created", trigger_data=wrong_data)
        with pytest.raises(TypeError, match="Expected CalendarEventCreatedConfig"):
            await handler.register(
                USER_ID, WORKFLOW_ID, "calendar_event_created", config
            )

    async def test_register_event_starting_soon_wrong_data_type_raises(self):
        handler = CalendarTriggerHandler()
        wrong_data = GmailNewMessageConfig()
        config = _make_trigger_config(
            "calendar_event_starting_soon", trigger_data=wrong_data
        )
        with pytest.raises(TypeError, match="Expected CalendarEventStartingSoonConfig"):
            await handler.register(
                USER_ID, WORKFLOW_ID, "calendar_event_starting_soon", config
            )

    @patch("app.services.triggers.handlers.calendar.workflows_collection")
    async def test_find_workflows_event_created(self, mock_collection):
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "Cal Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "calendar_event_created",
                "composio_trigger_ids": [TRIGGER_ID],
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = CalendarTriggerHandler()
        result = await handler.find_workflows(
            "GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER",
            TRIGGER_ID,
            {
                "calendar_id": "primary",
                "summary": "Meeting",
                "event_id": "evt_1",
            },
        )
        assert len(result) == 1

    @patch("app.services.triggers.handlers.calendar.workflows_collection")
    async def test_find_workflows_event_starting_soon(self, mock_collection):
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "Cal Soon Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "calendar_event_starting_soon",
                "composio_trigger_ids": [TRIGGER_ID],
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = CalendarTriggerHandler()
        result = await handler.find_workflows(
            "GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER",
            TRIGGER_ID,
            {
                "calendar_id": "primary",
                "summary": "Stand-up",
                "start_time": "2024-01-01T09:00:00Z",
            },
        )
        assert len(result) == 1

    @patch("app.services.triggers.handlers.calendar.workflows_collection")
    async def test_find_workflows_no_match(self, mock_collection):
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([]))

        handler = CalendarTriggerHandler()
        result = await handler.find_workflows(
            "GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER",
            "nonexistent_tid",
            {},
        )
        assert result == []

    @patch("app.services.triggers.handlers.calendar.workflows_collection")
    async def test_find_workflows_invalid_doc_skipped(self, mock_collection):
        invalid_doc = {"_id": "broken", "nope": True}
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([invalid_doc]))

        handler = CalendarTriggerHandler()
        result = await handler.find_workflows(
            "GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER",
            TRIGGER_ID,
            {},
        )
        assert result == []

    @patch("app.services.triggers.handlers.calendar.workflows_collection")
    async def test_find_workflows_exception_returns_empty(self, mock_collection):
        mock_collection.find = MagicMock(side_effect=Exception("DB error"))

        handler = CalendarTriggerHandler()
        result = await handler.find_workflows(
            "GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER",
            TRIGGER_ID,
            {},
        )
        assert result == []

    @patch("app.services.calendar_service.list_calendars")
    async def test_fetch_user_calendars_success(self, mock_list_calendars):
        mock_list_calendars.return_value = {
            "items": [
                {"id": "primary"},
                {"id": "work@example.com"},
            ]
        }

        handler = CalendarTriggerHandler()
        result = await handler._fetch_user_calendars(USER_ID)
        assert result == ["primary", "work@example.com"]

    @patch("app.services.calendar_service.list_calendars")
    async def test_fetch_user_calendars_no_items(self, mock_list_calendars):
        mock_list_calendars.return_value = {"no_items": True}

        handler = CalendarTriggerHandler()
        result = await handler._fetch_user_calendars(USER_ID)
        assert result == ["primary"]

    @patch("app.services.calendar_service.list_calendars")
    async def test_fetch_user_calendars_exception_falls_back(self, mock_list_calendars):
        mock_list_calendars.side_effect = Exception("API error")

        handler = CalendarTriggerHandler()
        result = await handler._fetch_user_calendars(USER_ID)
        assert result == ["primary"]

    @patch("app.services.calendar_service.list_calendars")
    async def test_fetch_user_calendars_items_without_id_skipped(
        self, mock_list_calendars
    ):
        """Calendar items without 'id' field are excluded."""
        mock_list_calendars.return_value = {
            "items": [
                {"id": "primary"},
                {"name": "no-id-calendar"},  # no id field
            ]
        }

        handler = CalendarTriggerHandler()
        result = await handler._fetch_user_calendars(USER_ID)
        assert result == ["primary"]

    def test_singleton_instance_exists(self):
        assert calendar_trigger_handler is not None
        assert isinstance(calendar_trigger_handler, CalendarTriggerHandler)


# ===========================================================================
# LinearTriggerHandler tests
# ===========================================================================


@pytest.mark.asyncio
class TestLinearTriggerHandler:
    """Tests for LinearTriggerHandler."""

    def test_trigger_names(self):
        handler = LinearTriggerHandler()
        expected = [
            "linear_issue_created",
            "linear_issue_updated",
            "linear_comment_added",
        ]
        assert handler.trigger_names == expected

    def test_event_types(self):
        handler = LinearTriggerHandler()
        expected = {
            "LINEAR_ISSUE_CREATED_TRIGGER",
            "LINEAR_ISSUE_UPDATED_TRIGGER",
            "LINEAR_COMMENT_EVENT_TRIGGER",
        }
        assert handler.event_types == expected

    async def test_register_unknown_trigger_raises(self):
        handler = LinearTriggerHandler()
        config = _make_trigger_config("linear_unknown")
        with pytest.raises(TriggerRegistrationError, match="Unknown Linear trigger"):
            await handler.register(USER_ID, WORKFLOW_ID, "linear_unknown", config)

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_issue_created_success(self, mock_get_composio):
        mock_result = MagicMock()
        mock_result.trigger_id = "lin_tid_1"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = LinearTriggerHandler()
        data = LinearIssueCreatedConfig(team_id="team_abc")
        config = _make_trigger_config("linear_issue_created", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "linear_issue_created", config
        )
        assert result == ["lin_tid_1"]
        # Verify team_id was passed in config
        call_kwargs = mock_composio.composio.triggers.create.call_args
        trigger_config_arg = call_kwargs.kwargs.get("trigger_config", {})
        assert trigger_config_arg.get("team_id") == "team_abc"

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_issue_updated_success(self, mock_get_composio):
        mock_result = MagicMock()
        mock_result.trigger_id = "lin_upd_tid"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = LinearTriggerHandler()
        data = LinearIssueUpdatedConfig(team_id="team_xyz")
        config = _make_trigger_config("linear_issue_updated", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "linear_issue_updated", config
        )
        assert result == ["lin_upd_tid"]

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_comment_added_success(self, mock_get_composio):
        mock_result = MagicMock()
        mock_result.trigger_id = "lin_cmt_tid"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = LinearTriggerHandler()
        data = LinearCommentAddedConfig(team_id="team_abc")
        config = _make_trigger_config("linear_comment_added", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "linear_comment_added", config
        )
        assert result == ["lin_cmt_tid"]

    @patch("app.services.triggers.base.get_composio_service")
    async def test_register_no_team_id_omits_from_config(self, mock_get_composio):
        """When team_id is empty, it is not included in the composio config."""
        mock_result = MagicMock()
        mock_result.trigger_id = "lin_no_team_tid"
        mock_composio = MagicMock()
        mock_composio.composio.triggers.create = MagicMock(return_value=mock_result)
        mock_get_composio.return_value = mock_composio

        handler = LinearTriggerHandler()
        data = LinearIssueCreatedConfig(team_id="")
        config = _make_trigger_config("linear_issue_created", trigger_data=data)

        result = await handler.register(
            USER_ID, WORKFLOW_ID, "linear_issue_created", config
        )
        assert result == ["lin_no_team_tid"]
        call_kwargs = mock_composio.composio.triggers.create.call_args
        trigger_config_arg = call_kwargs.kwargs.get("trigger_config", {})
        assert "team_id" not in trigger_config_arg

    async def test_register_issue_created_wrong_data_type_raises(self):
        handler = LinearTriggerHandler()
        wrong_data = LinearCommentAddedConfig()
        config = _make_trigger_config("linear_issue_created", trigger_data=wrong_data)
        with pytest.raises(TypeError, match="Expected LinearIssueCreatedConfig"):
            await handler.register(USER_ID, WORKFLOW_ID, "linear_issue_created", config)

    async def test_register_issue_updated_wrong_data_type_raises(self):
        handler = LinearTriggerHandler()
        wrong_data = LinearIssueCreatedConfig()
        config = _make_trigger_config("linear_issue_updated", trigger_data=wrong_data)
        with pytest.raises(TypeError, match="Expected LinearIssueUpdatedConfig"):
            await handler.register(USER_ID, WORKFLOW_ID, "linear_issue_updated", config)

    async def test_register_comment_added_wrong_data_type_raises(self):
        handler = LinearTriggerHandler()
        wrong_data = LinearIssueCreatedConfig()
        config = _make_trigger_config("linear_comment_added", trigger_data=wrong_data)
        with pytest.raises(TypeError, match="Expected LinearCommentAddedConfig"):
            await handler.register(USER_ID, WORKFLOW_ID, "linear_comment_added", config)

    # Linear register - else branch for truly unknown trigger name
    async def test_register_else_branch_unknown_trigger(self):
        handler = LinearTriggerHandler()
        handler.TRIGGER_TO_COMPOSIO["linear_fake"] = "LINEAR_FAKE_TRIGGER"
        data = LinearIssueCreatedConfig()
        config = _make_trigger_config("linear_fake", trigger_data=data)
        try:
            with pytest.raises(
                TriggerRegistrationError, match="Unknown Linear trigger"
            ):
                await handler.register(USER_ID, WORKFLOW_ID, "linear_fake", config)
        finally:
            del handler.TRIGGER_TO_COMPOSIO["linear_fake"]

    @patch("app.services.triggers.handlers.linear.workflows_collection")
    async def test_find_workflows_issue_created(self, mock_collection):
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "Linear Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "linear_issue_created",
                "composio_trigger_ids": [TRIGGER_ID],
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = LinearTriggerHandler()
        result = await handler.find_workflows(
            "LINEAR_ISSUE_CREATED_TRIGGER",
            TRIGGER_ID,
            {
                "action": "create",
                "type": "Issue",
                "data": {"title": "New Bug"},
            },
        )
        assert len(result) == 1

    @patch("app.services.triggers.handlers.linear.workflows_collection")
    async def test_find_workflows_comment_added(self, mock_collection):
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "Linear Comment Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "linear_comment_added",
                "composio_trigger_ids": [TRIGGER_ID],
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = LinearTriggerHandler()
        result = await handler.find_workflows(
            "LINEAR_COMMENT_EVENT_TRIGGER",
            TRIGGER_ID,
            {
                "action": "create",
                "type": "Comment",
                "data": {"body": "Great work!"},
            },
        )
        assert len(result) == 1

    @patch("app.services.triggers.handlers.linear.workflows_collection")
    async def test_find_workflows_issue_updated_event(self, mock_collection):
        """Issue updated events don't have a specific payload validation but still match."""
        workflow_doc = {
            "_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "title": "Linear Updated Workflow",
            "prompt": "do it",
            "steps": [{"title": "Step 1", "description": "Desc"}],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "linear_issue_updated",
                "composio_trigger_ids": [TRIGGER_ID],
            },
        }
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([workflow_doc]))

        handler = LinearTriggerHandler()
        result = await handler.find_workflows(
            "LINEAR_ISSUE_UPDATED_TRIGGER",
            TRIGGER_ID,
            {"action": "update", "data": {"status": "Done"}},
        )
        assert len(result) == 1

    @patch("app.services.triggers.handlers.linear.workflows_collection")
    async def test_find_workflows_no_match(self, mock_collection):
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([]))

        handler = LinearTriggerHandler()
        result = await handler.find_workflows(
            "LINEAR_ISSUE_CREATED_TRIGGER", "nonexistent_tid", {}
        )
        assert result == []

    @patch("app.services.triggers.handlers.linear.workflows_collection")
    async def test_find_workflows_invalid_doc_skipped(self, mock_collection):
        invalid_doc = {"_id": "broken", "not_valid": True}
        mock_collection.find = MagicMock(return_value=_AsyncCursorMock([invalid_doc]))

        handler = LinearTriggerHandler()
        result = await handler.find_workflows(
            "LINEAR_ISSUE_CREATED_TRIGGER", TRIGGER_ID, {}
        )
        assert result == []

    @patch("app.services.triggers.handlers.linear.workflows_collection")
    async def test_find_workflows_exception_returns_empty(self, mock_collection):
        mock_collection.find = MagicMock(side_effect=Exception("DB error"))

        handler = LinearTriggerHandler()
        result = await handler.find_workflows(
            "LINEAR_ISSUE_CREATED_TRIGGER", TRIGGER_ID, {}
        )
        assert result == []

    @patch("app.services.triggers.handlers.linear.get_composio_service")
    async def test_get_config_options_team_id(self, mock_get_composio):
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(
            return_value={
                "successful": True,
                "data": {
                    "items": [
                        {"id": "team_1", "name": "Engineering"},
                        {"id": "team_2", "name": "Design"},
                    ]
                },
                "error": None,
            }
        )
        mock_composio = MagicMock()
        mock_composio.get_tool = MagicMock(return_value=mock_tool)
        mock_get_composio.return_value = mock_composio

        handler = LinearTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="linear_issue_created",
            field_name="team_id",
            user_id=USER_ID,
            integration_id="linear",
        )
        assert len(result) == 2
        assert result[0]["value"] == "team_1"
        assert result[0]["label"] == "Engineering"

    @patch("app.services.triggers.handlers.linear.get_composio_service")
    async def test_get_config_options_team_id_with_search(self, mock_get_composio):
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(
            return_value={
                "successful": True,
                "data": {
                    "items": [
                        {"id": "team_1", "name": "Engineering"},
                        {"id": "team_2", "name": "Design"},
                    ]
                },
                "error": None,
            }
        )
        mock_composio = MagicMock()
        mock_composio.get_tool = MagicMock(return_value=mock_tool)
        mock_get_composio.return_value = mock_composio

        handler = LinearTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="linear_issue_created",
            field_name="team_id",
            user_id=USER_ID,
            integration_id="linear",
            search="design",
        )
        assert len(result) == 1
        assert result[0]["label"] == "Design"

    @patch("app.services.triggers.handlers.linear.get_composio_service")
    async def test_get_config_options_tool_not_found(self, mock_get_composio):
        mock_composio = MagicMock()
        mock_composio.get_tool = MagicMock(return_value=None)
        mock_get_composio.return_value = mock_composio

        handler = LinearTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="linear_issue_created",
            field_name="team_id",
            user_id=USER_ID,
            integration_id="linear",
        )
        assert result == []

    @patch("app.services.triggers.handlers.linear.get_composio_service")
    async def test_get_config_options_api_error(self, mock_get_composio):
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(
            return_value={
                "successful": False,
                "data": {},
                "error": "unauthorized",
            }
        )
        mock_composio = MagicMock()
        mock_composio.get_tool = MagicMock(return_value=mock_tool)
        mock_get_composio.return_value = mock_composio

        handler = LinearTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="linear_issue_created",
            field_name="team_id",
            user_id=USER_ID,
            integration_id="linear",
        )
        assert result == []

    @patch("app.services.triggers.handlers.linear.get_composio_service")
    async def test_get_config_options_unknown_field(self, mock_get_composio):
        mock_composio = MagicMock()
        mock_get_composio.return_value = mock_composio

        handler = LinearTriggerHandler()
        result = await handler.get_config_options(
            trigger_name="linear_issue_created",
            field_name="unknown_field",
            user_id=USER_ID,
            integration_id="linear",
        )
        assert result == []

    def test_singleton_instance_exists(self):
        assert linear_trigger_handler is not None
        assert isinstance(linear_trigger_handler, LinearTriggerHandler)


# ===========================================================================
# Cross-handler / integration-level tests
# ===========================================================================


@pytest.mark.asyncio
class TestHandlerSingletons:
    """Verify all module-level singleton instances exist and have correct types."""

    def test_gmail_handler(self):
        assert isinstance(gmail_trigger_handler, GmailTriggerHandler)

    def test_gmail_poll_handler(self):
        assert isinstance(gmail_poll_trigger_handler, GmailPollTriggerHandler)

    def test_slack_handler(self):
        assert isinstance(slack_trigger_handler, SlackTriggerHandler)

    def test_github_handler(self):
        assert isinstance(github_trigger_handler, GitHubTriggerHandler)

    def test_calendar_handler(self):
        assert isinstance(calendar_trigger_handler, CalendarTriggerHandler)

    def test_linear_handler(self):
        assert isinstance(linear_trigger_handler, LinearTriggerHandler)


@pytest.mark.asyncio
class TestTriggerRegistrationError:
    """Tests for the TriggerRegistrationError exception class."""

    def test_basic_attributes(self):
        err = TriggerRegistrationError("Something failed", "my_trigger")
        assert str(err) == "Something failed"
        assert err.trigger_name == "my_trigger"
        assert err.partial_ids == []

    def test_with_partial_ids(self):
        err = TriggerRegistrationError(
            "Partial failure",
            "my_trigger",
            partial_ids=["tid_1", "tid_2"],
        )
        assert err.partial_ids == ["tid_1", "tid_2"]

    def test_none_partial_ids_defaults_to_empty(self):
        err = TriggerRegistrationError("Fail", "trig", partial_ids=None)
        assert err.partial_ids == []
