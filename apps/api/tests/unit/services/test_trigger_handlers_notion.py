"""Tests for app.services.triggers.handlers.notion."""

import sys
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-populate the circular-import path with a stub so importing the Notion
# handler does not trigger the full workflow → trigger_service → triggers loop.
_queue_stub = MagicMock()
sys.modules.setdefault("app.services.workflow.queue_service", _queue_stub)
sys.modules.setdefault("app.services.workflow.trigger_service", MagicMock())

from app.services.triggers.handlers.notion import NotionTriggerHandler  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler() -> NotionTriggerHandler:
    return NotionTriggerHandler()


def _make_trigger_config(trigger_data: Any) -> MagicMock:
    tc = MagicMock()
    tc.trigger_data = trigger_data
    return tc


def _make_workflow_doc(
    wid: str = "wf1",
    user_id: str = "u1",
    activated: bool = True,
) -> Dict[str, Any]:
    return {
        "_id": wid,
        "id": wid,
        "user_id": user_id,
        "activated": activated,
        "name": "Test Workflow",
        "trigger_config": {
            "type": "integration",
            "enabled": True,
            "composio_trigger_ids": ["trig1"],
        },
    }


class _AsyncCursorMock:
    """Simulates an async MongoDB cursor."""

    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self._docs = docs
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._docs):
            raise StopAsyncIteration
        doc = self._docs[self._index]
        self._index += 1
        return doc


# ---------------------------------------------------------------------------
# NotionTriggerHandler properties
# ---------------------------------------------------------------------------


class TestNotionTriggerHandlerProperties:
    def test_trigger_names(self) -> None:
        handler = _make_handler()
        assert "notion_new_page_in_db" in handler.trigger_names
        assert "notion_page_updated" in handler.trigger_names
        assert "notion_all_page_events" in handler.trigger_names

    def test_event_types(self) -> None:
        handler = _make_handler()
        assert "NOTION_PAGE_ADDED_TO_DATABASE" in handler.event_types
        assert "NOTION_PAGE_UPDATED_TRIGGER" in handler.event_types
        assert "NOTION_ALL_PAGE_EVENTS_TRIGGER" in handler.event_types


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

        with patch(
            "app.services.triggers.handlers.notion.NotionFetchDataData"
        ) as mock_cls:
            mock_cls.model_validate.return_value = mock_data

            result = await handler.get_config_options(
                "notion_new_page_in_db", "database_id", "u1", "notion"
            )

        assert len(result) == 1
        assert result[0]["value"] == "db1"
        assert result[0]["label"] == "My Database"

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

        with patch(
            "app.services.triggers.handlers.notion.NotionFetchDataData"
        ) as mock_cls:
            mock_cls.model_validate.return_value = mock_data
            result = await handler.get_config_options(
                "notion_page_updated", "page_id", "u1", "notion"
            )

        assert result[0]["value"] == "pg1"

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

        with patch(
            "app.services.triggers.handlers.notion.NotionFetchDataData"
        ) as mock_cls:
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

        with patch(
            "app.services.triggers.handlers.notion.NotionFetchDataData"
        ) as mock_cls:
            mock_cls.model_validate.return_value = mock_data
            result = await handler.get_config_options(
                "notion_new_page_in_db", "database_id", "u1", "notion"
            )

        assert len(result) == 1
        assert result[0]["label"] == "Untitled"


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
        with pytest.raises(TypeError, match="Expected NotionNewPageInDbConfig"):
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
        assert call_kwargs.kwargs["composio_slug"] == "NOTION_PAGE_ADDED_TO_DATABASE"

    @pytest.mark.asyncio
    async def test_page_updated_wrong_type_raises(self) -> None:
        handler = _make_handler()
        tc = _make_trigger_config("bad")
        with pytest.raises(TypeError, match="Expected NotionPageUpdatedConfig"):
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
    async def test_all_page_events_no_data(self) -> None:
        handler = _make_handler()
        tc = _make_trigger_config(None)

        with patch.object(
            handler,
            "_register_triggers_parallel",
            new_callable=AsyncMock,
            return_value=["t1"],
        ):
            result = await handler.register("u1", "wf1", "notion_all_page_events", tc)
        assert result == ["t1"]

    @pytest.mark.asyncio
    async def test_all_page_events_wrong_type_raises(self) -> None:
        handler = _make_handler()
        tc = _make_trigger_config("wrong_type")
        with pytest.raises(TypeError, match="Expected NotionAllPageEventsConfig"):
            await handler.register("u1", "wf1", "notion_all_page_events", tc)


# ---------------------------------------------------------------------------
# find_workflows
# ---------------------------------------------------------------------------


class TestFindWorkflows:
    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.workflows_collection")
    async def test_finds_matching_workflows(self, mock_coll: MagicMock) -> None:
        handler = _make_handler()
        mock_coll.find.return_value = _AsyncCursorMock([_make_workflow_doc()])

        with patch("app.services.triggers.handlers.notion.Workflow") as mock_wf_cls:
            mock_wf = MagicMock()
            mock_wf_cls.return_value = mock_wf

            result = await handler.find_workflows(
                "NOTION_PAGE_ADDED_TO_DATABASE", "trig1", {}
            )

        assert len(result) == 1

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.workflows_collection")
    async def test_returns_empty_on_no_match(self, mock_coll: MagicMock) -> None:
        handler = _make_handler()
        mock_coll.find.return_value = _AsyncCursorMock([])

        result = await handler.find_workflows(
            "NOTION_PAGE_ADDED_TO_DATABASE", "trig_missing", {}
        )
        assert result == []

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.workflows_collection")
    async def test_skips_invalid_workflow_doc(self, mock_coll: MagicMock) -> None:
        handler = _make_handler()
        mock_coll.find.return_value = _AsyncCursorMock([_make_workflow_doc()])

        with patch(
            "app.services.triggers.handlers.notion.Workflow",
            side_effect=Exception("bad"),
        ):
            result = await handler.find_workflows(
                "NOTION_PAGE_ADDED_TO_DATABASE", "trig1", {}
            )

        assert result == []

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.workflows_collection")
    async def test_exception_returns_empty(self, mock_coll: MagicMock) -> None:
        handler = _make_handler()
        mock_coll.find.side_effect = RuntimeError("db error")

        result = await handler.find_workflows(
            "NOTION_PAGE_UPDATED_TRIGGER", "trig1", {}
        )
        assert result == []

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.workflows_collection")
    async def test_validates_page_added_payload(self, mock_coll: MagicMock) -> None:
        handler = _make_handler()
        mock_coll.find.return_value = _AsyncCursorMock([])

        with patch(
            "app.services.triggers.handlers.notion.NotionPageAddedPayload"
        ) as mock_payload:
            mock_payload.model_validate.return_value = MagicMock()
            await handler.find_workflows(
                "NOTION_new_page_EVENT", "trig1", {"some": "data"}
            )
            mock_payload.model_validate.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.workflows_collection")
    async def test_validates_page_updated_payload(self, mock_coll: MagicMock) -> None:
        handler = _make_handler()
        mock_coll.find.return_value = _AsyncCursorMock([])

        with patch(
            "app.services.triggers.handlers.notion.NotionPageUpdatedPayload"
        ) as mock_payload:
            mock_payload.model_validate.return_value = MagicMock()
            await handler.find_workflows("NOTION_page_updated_EVENT", "trig1", {})
            mock_payload.model_validate.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.triggers.handlers.notion.workflows_collection")
    async def test_validates_all_page_events_payload(
        self, mock_coll: MagicMock
    ) -> None:
        handler = _make_handler()
        mock_coll.find.return_value = _AsyncCursorMock([])

        with patch(
            "app.services.triggers.handlers.notion.NotionAllPageEventsPayload"
        ) as mock_payload:
            mock_payload.model_validate.return_value = MagicMock()
            await handler.find_workflows("NOTION_all_page_events_EVENT", "trig1", {})
            mock_payload.model_validate.assert_called_once()
