"""Tests for the Asana / Google Docs / Todoist trigger handlers."""

from pathlib import Path
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Break the circular import: triggers.__init__ -> handlers -> base ->
# workflow.queue_service -> workflow.__init__ -> workflow.service ->
# workflow.trigger_service -> triggers (not yet finished)
# ---------------------------------------------------------------------------

_api_root = Path(__file__).resolve().parents[3]

if "app.services.workflow" not in sys.modules:
    _wf_pkg = types.ModuleType("app.services.workflow")
    _wf_pkg.__path__ = [str(_api_root / "app" / "services" / "workflow")]
    _wf_pkg.__package__ = "app.services.workflow"
    sys.modules["app.services.workflow"] = _wf_pkg

if "app.services.workflow.queue_service" not in sys.modules:
    _qs_mod = types.ModuleType("app.services.workflow.queue_service")
    _qs_mod.WorkflowQueueService = MagicMock()
    sys.modules["app.services.workflow.queue_service"] = _qs_mod

from app.models.trigger_configs import (  # ratchet-allow -- circular-import break; mirrors the grandfathered sibling test_trigger_handlers.py
    AsanaTaskTriggerConfig,
    GoogleDocsNewDocumentConfig,
    TodoistNewTaskCreatedConfig,
)
from app.models.workflow_models import (
    TriggerConfig,  # ratchet-allow -- circular-import break; mirrors the grandfathered sibling test_trigger_handlers.py
)
from app.services.triggers.handlers.asana import (  # ratchet-allow -- circular-import break; mirrors the grandfathered sibling test_trigger_handlers.py
    AsanaTriggerHandler,
    asana_trigger_handler,
)
from app.services.triggers.handlers.google_docs import (  # ratchet-allow -- circular-import break; mirrors the grandfathered sibling test_trigger_handlers.py
    GoogleDocsTriggerHandler,
    google_docs_trigger_handler,
)
from app.services.triggers.handlers.todoist import (  # ratchet-allow -- circular-import break; mirrors the grandfathered sibling test_trigger_handlers.py
    TodoistTriggerHandler,
    todoist_trigger_handler,
)
from app.utils.exceptions import (
    TriggerRegistrationError,  # ratchet-allow -- circular-import break; mirrors the grandfathered sibling test_trigger_handlers.py
)

TRIGGER_CONFIGS = {
    "asana": (
        AsanaTriggerHandler,
        asana_trigger_handler,
        AsanaTaskTriggerConfig,
        "asana_task_trigger",
    ),
    "google_docs": (
        GoogleDocsTriggerHandler,
        google_docs_trigger_handler,
        GoogleDocsNewDocumentConfig,
        "google_docs_new_document",
    ),
    "todoist": (
        TodoistTriggerHandler,
        todoist_trigger_handler,
        TodoistNewTaskCreatedConfig,
        "todoist_new_task_created",
    ),
}


def _registrable_config(config_cls: type) -> TriggerConfig:
    # Asana's Composio trigger requires a project GID at registration time.
    if config_cls is AsanaTaskTriggerConfig:
        return TriggerConfig(
            type="integration", trigger_data=AsanaTaskTriggerConfig(project_gid="1213430481840948")
        )
    return TriggerConfig(type="integration", trigger_data=config_cls())


@pytest.mark.parametrize(
    "handler_cls, instance, config_cls, trigger_name",
    TRIGGER_CONFIGS.values(),
    ids=TRIGGER_CONFIGS.keys(),
)
class TestTriggerHandlerProperties:
    def test_singleton_instance(self, handler_cls, instance, config_cls, trigger_name) -> None:
        assert isinstance(instance, handler_cls)

    def test_trigger_names_match_supported(
        self, handler_cls, instance, config_cls, trigger_name
    ) -> None:
        assert instance.trigger_names == instance.SUPPORTED_TRIGGERS

    def test_event_types_match_supported(
        self, handler_cls, instance, config_cls, trigger_name
    ) -> None:
        assert instance.event_types == instance.SUPPORTED_EVENTS

    def test_trigger_to_composio_has_every_supported_trigger(
        self, handler_cls, instance, config_cls, trigger_name
    ) -> None:
        assert set(instance.TRIGGER_TO_COMPOSIO) == set(instance.SUPPORTED_TRIGGERS)


@pytest.mark.parametrize(
    "handler_cls, instance, config_cls, trigger_name",
    TRIGGER_CONFIGS.values(),
    ids=TRIGGER_CONFIGS.keys(),
)
class TestTriggerHandlerRegister:
    async def test_unknown_trigger_raises_registration_error(
        self, handler_cls, instance, config_cls, trigger_name
    ) -> None:
        config = TriggerConfig(type="integration", trigger_data=config_cls())
        with pytest.raises(TriggerRegistrationError):
            await instance.register("u-1", "wf-1", "not_a_trigger", config)

    async def test_wrong_trigger_data_type_raises_type_error(
        self, handler_cls, instance, config_cls, trigger_name
    ) -> None:
        # A valid TriggerConfig carrying a DIFFERENT provider's config.
        wrong_config_cls = next(
            cfg for cls, _, cfg, _ in TRIGGER_CONFIGS.values() if cfg is not config_cls
        )
        config = TriggerConfig(type="integration", trigger_data=wrong_config_cls())
        with pytest.raises(TypeError):
            await instance.register("u-1", "wf-1", trigger_name, config)

    async def test_valid_registration_forwards_to_parallel_helper(
        self, handler_cls, instance, config_cls, trigger_name
    ) -> None:
        config = _registrable_config(config_cls)
        with patch.object(
            instance, "_register_triggers_parallel", new_callable=AsyncMock, return_value=["ok"]
        ) as mock_register:
            result = await instance.register("u-1", "wf-1", trigger_name, config)

        assert result == ["ok"]
        mock_register.assert_awaited_once()
        call_kwargs = mock_register.await_args.kwargs
        assert call_kwargs["user_id"] == "u-1"
        assert call_kwargs["trigger_name"] == trigger_name
        assert call_kwargs["composio_slug"] == instance.TRIGGER_TO_COMPOSIO[trigger_name]


class TestAsanaProjectGidRequirement:
    # Composio's ASANA_TASK_CREATED requires a project GID; these pin both
    # the rejection branch and the exact config forwarded upstream.
    @pytest.mark.asyncio
    async def test_empty_project_gid_raises_registration_error(self) -> None:
        config = TriggerConfig(
            type="integration", trigger_data=AsanaTaskTriggerConfig(project_gid="")
        )
        # Exact-message assert: substring match would survive mutmut's
        # XX-wrap / case mutations of the error string.
        with pytest.raises(
            TriggerRegistrationError,
            match=r"^asana_task_trigger now requires project_gid "
            r"\(Composio retired the unscoped ASANA_TASK_TRIGGER\)$",
        ) as excinfo:
            await asana_trigger_handler.register("u-1", "wf-1", "asana_task_trigger", config)
        assert excinfo.value.trigger_name == "asana_task_trigger"

    @pytest.mark.asyncio
    async def test_registration_forwards_project_gid_config(self) -> None:
        config = _registrable_config(AsanaTaskTriggerConfig)
        with patch.object(
            asana_trigger_handler,
            "_register_triggers_parallel",
            new_callable=AsyncMock,
            return_value=["ok"],
        ) as mock_register:
            await asana_trigger_handler.register("u-1", "wf-1", "asana_task_trigger", config)

        assert mock_register.await_args.kwargs["configs"] == [{"project_gid": "1213430481840948"}]


@pytest.mark.parametrize(
    "handler_cls, instance, config_cls, trigger_name",
    TRIGGER_CONFIGS.values(),
    ids=TRIGGER_CONFIGS.keys(),
)
class TestTriggerHandlerFindWorkflows:
    @patch("app.services.triggers.handlers.asana.workflow_repository", spec=object)
    @patch("app.services.triggers.handlers.google_docs.workflow_repository", spec=object)
    @patch("app.services.triggers.handlers.todoist.workflow_repository", spec=object)
    async def test_returns_matching_workflows(
        self, mock_todoist, mock_docs, mock_asana, handler_cls, instance, config_cls, trigger_name
    ) -> None:
        mock_workflow = MagicMock()
        for mock in (mock_asana, mock_docs, mock_todoist):
            mock.find_active_by_composio_trigger = AsyncMock(return_value=[mock_workflow])

        workflows = await instance.find_workflows("EVENT", "trig-1", {})
        assert workflows == [mock_workflow]

    @patch("app.services.triggers.handlers.asana.workflow_repository", spec=object)
    @patch("app.services.triggers.handlers.google_docs.workflow_repository", spec=object)
    @patch("app.services.triggers.handlers.todoist.workflow_repository", spec=object)
    async def test_repository_error_returns_empty(
        self, mock_todoist, mock_docs, mock_asana, handler_cls, instance, config_cls, trigger_name
    ) -> None:
        for mock in (mock_asana, mock_docs, mock_todoist):
            mock.find_active_by_composio_trigger = AsyncMock(side_effect=RuntimeError("down"))

        with (
            patch("app.services.triggers.handlers.asana.log"),
            patch("app.services.triggers.handlers.google_docs.log"),
            patch("app.services.triggers.handlers.todoist.log"),
        ):
            assert await instance.find_workflows("EVENT", "trig-1", {}) == []
