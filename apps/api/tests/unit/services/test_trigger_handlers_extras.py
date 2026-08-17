"""Tests for the Asana / Google Docs / Todoist trigger handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.trigger_configs import (
    AsanaTaskTriggerConfig,
    GoogleDocsNewDocumentConfig,
    TodoistNewTaskCreatedConfig,
)
from app.models.workflow_models import TriggerConfig
from app.services.triggers.handlers.asana import (
    AsanaTriggerHandler,
    asana_trigger_handler,
)
from app.services.triggers.handlers.google_docs import (
    GoogleDocsTriggerHandler,
    google_docs_trigger_handler,
)
from app.services.triggers.handlers.todoist import (
    TodoistTriggerHandler,
    todoist_trigger_handler,
)
from app.utils.exceptions import TriggerRegistrationError

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
        config = TriggerConfig(type="integration", trigger_data=config_cls())
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
        # An unfiltered trigger registers one Composio subscription with no
        # narrowing config — a None here is not the same request.
        assert call_kwargs["configs"] == [{}]


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
