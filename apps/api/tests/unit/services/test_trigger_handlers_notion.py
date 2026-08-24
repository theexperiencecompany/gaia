"""Tests for app.services.triggers.handlers.notion."""

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-populate the circular-import path with a stub so importing the Notion
# handler does not trigger the full workflow → trigger_service → triggers loop.
_queue_stub = MagicMock()
sys.modules.setdefault("app.services.workflow.queue_service", _queue_stub)
sys.modules.setdefault("app.services.workflow.trigger_service", MagicMock())

from app.services.triggers.handlers.notion import NotionTriggerHandler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler() -> NotionTriggerHandler:
    return NotionTriggerHandler()


def _make_trigger_config(trigger_data: Any) -> MagicMock:
    tc = MagicMock()
    tc.trigger_data = trigger_data
    return tc


# ---------------------------------------------------------------------------
# NotionTriggerHandler properties
# ---------------------------------------------------------------------------


class TestNotionTriggerHandlerProperties:
    def test_trigger_names(self) -> None:
        handler = _make_handler()
        assert "notion_new_page_in_db" in handler.trigger_names
        assert "notion_page_updated" in handler.trigger_names
        assert "notion_page_content_updated" in handler.trigger_names
        # Composio retired the underlying slug; no longer offered.
        assert "notion_all_page_events" not in handler.trigger_names

    def test_event_types(self) -> None:
        handler = _make_handler()
        assert "NOTION_PAGE_CREATED" in handler.event_types
        assert "NOTION_PAGE_PROPERTIES_UPDATED" in handler.event_types
        assert "NOTION_PAGE_CONTENT_UPDATED" in handler.event_types


# ---------------------------------------------------------------------------
# get_config_options
# ---------------------------------------------------------------------------


class TestGetConfigOptions:
    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.get_composio_service")
    async def test_database_id_field(self, mock_get_svc: MagicMock) -> None:
        handler = _make_handler()

        mock_item = MagicMock()
        mock_item.id = "db1"
        mock_item.title = "My Database"

        mock_data = MagicMock()
        mock_data.get_items.return_value = [mock_item]

        mock_tool = MagicMock()
        mock_tool.invoke.return_value = {"successful": True, "data": {}}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_svc.return_value = svc

        with patch("app.services.triggers.handlers.notion.NotionFetchDataData") as mock_cls:
            mock_cls.model_validate.return_value = mock_data

            result = await handler.get_config_options(
                "notion_new_page_in_db", "database_id", "u1", "notion"
            )

        assert len(result) == 1
        assert result[0].value == "db1"
        assert result[0].label == "My Database"

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.get_composio_service")
    async def test_page_id_field(self, mock_get_svc: MagicMock) -> None:
        handler = _make_handler()

        mock_item = MagicMock()
        mock_item.id = "pg1"
        mock_item.title = "My Page"

        mock_data = MagicMock()
        mock_data.get_items.return_value = [mock_item]

        mock_tool = MagicMock()
        mock_tool.invoke.return_value = {"successful": True, "data": {}}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_svc.return_value = svc

        with patch("app.services.triggers.handlers.notion.NotionFetchDataData") as mock_cls:
            mock_cls.model_validate.return_value = mock_data
            result = await handler.get_config_options(
                "notion_page_updated", "page_id", "u1", "notion"
            )

        assert result[0].value == "pg1"

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.get_composio_service")
    async def test_unknown_field_uses_all(self, mock_get_svc: MagicMock) -> None:
        handler = _make_handler()

        mock_data = MagicMock()
        mock_data.get_items.return_value = []

        mock_tool = MagicMock()
        mock_tool.invoke.return_value = {"successful": True, "data": {}}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_svc.return_value = svc

        with patch("app.services.triggers.handlers.notion.NotionFetchDataData") as mock_cls:
            mock_cls.model_validate.return_value = mock_data
            result = await handler.get_config_options(
                "notion_all_page_events", "something_else", "u1", "notion"
            )

        assert result == []

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.get_composio_service")
    async def test_tool_not_found_returns_empty(self, mock_get_svc: MagicMock) -> None:
        handler = _make_handler()

        svc = MagicMock()
        svc.get_tool.return_value = None
        mock_get_svc.return_value = svc

        result = await handler.get_config_options(
            "notion_new_page_in_db", "database_id", "u1", "notion"
        )
        assert result == []

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.get_composio_service")
    async def test_api_error_returns_empty(self, mock_get_svc: MagicMock) -> None:
        handler = _make_handler()

        mock_tool = MagicMock()
        mock_tool.invoke.return_value = {"successful": False, "error": "API Error"}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_svc.return_value = svc

        result = await handler.get_config_options(
            "notion_new_page_in_db", "database_id", "u1", "notion"
        )
        assert result == []

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.get_composio_service")
    async def test_exception_returns_empty(self, mock_get_svc: MagicMock) -> None:
        handler = _make_handler()

        mock_get_svc.side_effect = RuntimeError("fail")
        result = await handler.get_config_options(
            "notion_new_page_in_db", "database_id", "u1", "notion"
        )
        assert result == []

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.get_composio_service")
    async def test_skips_items_without_id(self, mock_get_svc: MagicMock) -> None:
        handler = _make_handler()

        mock_item_no_id = MagicMock()
        mock_item_no_id.id = None
        mock_item_no_id.title = "No ID"

        mock_item_ok = MagicMock()
        mock_item_ok.id = "db2"
        mock_item_ok.title = None  # should fall back to "Untitled"

        mock_data = MagicMock()
        mock_data.get_items.return_value = [mock_item_no_id, mock_item_ok]

        mock_tool = MagicMock()
        mock_tool.invoke.return_value = {"successful": True, "data": {}}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_svc.return_value = svc

        with patch("app.services.triggers.handlers.notion.NotionFetchDataData") as mock_cls:
            mock_cls.model_validate.return_value = mock_data
            result = await handler.get_config_options(
                "notion_new_page_in_db", "database_id", "u1", "notion"
            )

        assert len(result) == 1
        assert result[0].label == "Untitled"


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


class TestRegister:
    @pytest.mark.asyncio
    async def test_unknown_trigger_raises(self) -> None:
        from app.utils.exceptions import TriggerRegistrationError

        handler = _make_handler()
        tc = _make_trigger_config(None)
        with pytest.raises(TriggerRegistrationError, match="Unknown Notion trigger"):
            await handler.register("u1", "wf1", "bad_trigger", tc)

    @pytest.mark.asyncio
    async def test_new_page_in_db_wrong_type_raises(self) -> None:
        handler = _make_handler()
        tc = _make_trigger_config("not_right_type")
        # Exact-message asserts throughout: substring matches survive
        # mutmut's mutations of the f-string internals.
        with pytest.raises(
            TypeError,
            match=r"^Expected NotionNewPageInDbConfig for trigger "
            r"'notion_new_page_in_db', but got str$",
        ):
            await handler.register("u1", "wf1", "notion_new_page_in_db", tc)

    @pytest.mark.asyncio
    async def test_new_page_in_db_empty_ids(self) -> None:
        from app.models.trigger_configs import NotionNewPageInDbConfig

        handler = _make_handler()
        td = MagicMock(spec=NotionNewPageInDbConfig)
        td.database_ids = []
        tc = _make_trigger_config(td)

        result = await handler.register("u1", "wf1", "notion_new_page_in_db", tc)
        assert result == []

    @pytest.mark.asyncio
    async def test_new_page_in_db_calls_parallel_register(self) -> None:
        from app.models.trigger_configs import NotionNewPageInDbConfig

        handler = _make_handler()
        td = MagicMock(spec=NotionNewPageInDbConfig)
        td.database_ids = ["db1", "db2"]
        tc = _make_trigger_config(td)

        with patch.object(
            handler,
            "_register_triggers_parallel",
            new_callable=AsyncMock,
            return_value=["t1", "t2"],
        ) as mock_reg:
            result = await handler.register("u1", "wf1", "notion_new_page_in_db", tc)

        assert result == ["t1", "t2"]
        mock_reg.assert_called_once()
        call_kwargs = mock_reg.call_args
        assert call_kwargs.kwargs["composio_slug"] == "NOTION_PAGE_CREATED"
        # database_ids map onto Composio's data_source_id config param.
        assert call_kwargs.kwargs["configs"] == [
            {"data_source_id": "db1"},
            {"data_source_id": "db2"},
        ]

    @pytest.mark.asyncio
    async def test_page_updated_wrong_type_raises(self) -> None:
        handler = _make_handler()
        tc = _make_trigger_config("bad")
        with pytest.raises(
            TypeError,
            match=r"^Expected NotionPageUpdatedConfig for trigger "
            r"'notion_page_updated', but got str$",
        ):
            await handler.register("u1", "wf1", "notion_page_updated", tc)

    @pytest.mark.asyncio
    async def test_page_updated_empty_ids(self) -> None:
        from app.models.trigger_configs import NotionPageUpdatedConfig

        handler = _make_handler()
        td = MagicMock(spec=NotionPageUpdatedConfig)
        td.page_ids = []
        tc = _make_trigger_config(td)

        result = await handler.register("u1", "wf1", "notion_page_updated", tc)
        assert result == []

    @pytest.mark.asyncio
    async def test_page_updated_calls_parallel_register(self) -> None:
        from app.models.trigger_configs import NotionPageUpdatedConfig

        handler = _make_handler()
        td = MagicMock(spec=NotionPageUpdatedConfig)
        td.page_ids = ["p1"]
        tc = _make_trigger_config(td)

        with patch.object(
            handler,
            "_register_triggers_parallel",
            new_callable=AsyncMock,
            return_value=["t1"],
        ):
            result = await handler.register("u1", "wf1", "notion_page_updated", tc)
        assert result == ["t1"]

    @pytest.mark.asyncio
    async def test_page_content_updated_calls_parallel_register(self) -> None:
        from app.models.trigger_configs import NotionPageContentUpdatedConfig

        handler = _make_handler()
        td = MagicMock(spec=NotionPageContentUpdatedConfig)
        td.page_ids = ["p1", "p2"]
        tc = _make_trigger_config(td)

        with patch.object(
            handler,
            "_register_triggers_parallel",
            new_callable=AsyncMock,
            return_value=["t1", "t2"],
        ) as mock_reg:
            result = await handler.register("u1", "wf1", "notion_page_content_updated", tc)

        assert result == ["t1", "t2"]
        call_kwargs = mock_reg.call_args
        assert call_kwargs.kwargs["composio_slug"] == "NOTION_PAGE_CONTENT_UPDATED"
        assert call_kwargs.kwargs["configs"] == [{"page_id": "p1"}, {"page_id": "p2"}]

    @pytest.mark.asyncio
    async def test_page_content_updated_no_ids_registers_unscoped(self) -> None:
        from app.models.trigger_configs import NotionPageContentUpdatedConfig

        handler = _make_handler()
        td = MagicMock(spec=NotionPageContentUpdatedConfig)
        td.page_ids = []
        tc = _make_trigger_config(td)

        with patch.object(
            handler,
            "_register_triggers_parallel",
            new_callable=AsyncMock,
            return_value=["t1"],
        ) as mock_reg:
            result = await handler.register("u1", "wf1", "notion_page_content_updated", tc)
        assert result == ["t1"]
        assert mock_reg.call_args.kwargs["configs"] == [{}]

    @pytest.mark.asyncio
    async def test_page_content_updated_none_data_raises_exact_message(self) -> None:
        # Exact-message assert (including the terminal "None"): substring
        # match survives mutmut's case/XX-wrap mutations of the f-string.
        handler = _make_handler()
        tc = _make_trigger_config(None)
        with pytest.raises(
            TypeError,
            match=r"^Expected NotionPageContentUpdatedConfig for trigger "
            r"'notion_page_content_updated', but got None$",
        ):
            await handler.register("u1", "wf1", "notion_page_content_updated", tc)

    @pytest.mark.asyncio
    async def test_page_content_updated_wrong_type_raises_exact_message(self) -> None:
        # Truthy wrong type pins the f-string's type() branch, which the
        # None-data case above never evaluates.
        handler = _make_handler()
        tc = _make_trigger_config("bad")
        with pytest.raises(
            TypeError,
            match=r"^Expected NotionPageContentUpdatedConfig for trigger "
            r"'notion_page_content_updated', but got str$",
        ):
            await handler.register("u1", "wf1", "notion_page_content_updated", tc)


# ---------------------------------------------------------------------------
# find_workflows
# ---------------------------------------------------------------------------


class TestFindWorkflows:
    # find_workflows delegates the Mongo query + doc parsing to
    # workflow_repository.find_active_by_composio_trigger (contract-tested). Here we
    # verify the handler's delegation, payload validation, and fail-loud-swallow.
    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.workflow_repository")
    async def test_finds_matching_workflows(self, mock_repo: MagicMock) -> None:
        handler = _make_handler()
        mock_repo.find_active_by_composio_trigger = AsyncMock(return_value=[MagicMock()])

        result = await handler.find_workflows("NOTION_PAGE_CREATED", "trig1", {})

        assert len(result) == 1
        mock_repo.find_active_by_composio_trigger.assert_awaited_once_with("trig1")

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.workflow_repository")
    async def test_returns_empty_on_no_match(self, mock_repo: MagicMock) -> None:
        handler = _make_handler()
        mock_repo.find_active_by_composio_trigger = AsyncMock(return_value=[])

        result = await handler.find_workflows("NOTION_PAGE_CREATED", "trig_missing", {})
        assert result == []

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.workflow_repository")
    async def test_exception_returns_empty(self, mock_repo: MagicMock) -> None:
        handler = _make_handler()
        mock_repo.find_active_by_composio_trigger = AsyncMock(side_effect=RuntimeError("db error"))

        result = await handler.find_workflows("NOTION_PAGE_PROPERTIES_UPDATED", "trig1", {})
        assert result == []

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.NotionPageCreatedPayload")
    @patch("app.services.triggers.handlers.notion.workflow_repository")
    async def test_validates_page_created_payload(
        self, mock_repo: MagicMock, mock_payload: MagicMock
    ) -> None:
        handler = _make_handler()
        mock_repo.find_active_by_composio_trigger = AsyncMock(return_value=[])

        data = {"page_id": "p1"}
        await handler.find_workflows("NOTION_page_created_EVENT", "trig1", data)
        # Exact-arg assert: a bare called-once check survives mutants that
        # swap `data` for None.
        mock_payload.model_validate.assert_called_once_with(data)

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.NotionPagePropertiesUpdatedPayload")
    @patch("app.services.triggers.handlers.notion.workflow_repository")
    async def test_validates_page_properties_updated_payload(
        self, mock_repo: MagicMock, mock_payload: MagicMock
    ) -> None:
        handler = _make_handler()
        mock_repo.find_active_by_composio_trigger = AsyncMock(return_value=[])

        data = {"page_id": "p1"}
        await handler.find_workflows("NOTION_properties_updated_EVENT", "trig1", data)
        mock_payload.model_validate.assert_called_once_with(data)

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.NotionPageContentUpdatedPayload")
    @patch("app.services.triggers.handlers.notion.workflow_repository")
    async def test_validates_page_content_updated_payload(
        self, mock_repo: MagicMock, mock_payload: MagicMock
    ) -> None:
        handler = _make_handler()
        mock_repo.find_active_by_composio_trigger = AsyncMock(return_value=[])

        data = {"page_id": "p1"}
        await handler.find_workflows("NOTION_content_updated_EVENT", "trig1", data)
        mock_payload.model_validate.assert_called_once_with(data)
