"""Tests for Google Sheets trigger handler."""

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Break the circular import: triggers.__init__ -> handlers -> base ->
# workflow.queue_service -> workflow.__init__ -> workflow.service ->
# workflow.trigger_service -> triggers (not yet finished)
#
# Strategy: pre-seed `app.services.workflow` as a fully-loaded stub module
# BEFORE anything in the triggers package tries to import from it.
# ---------------------------------------------------------------------------

_api_root = Path(__file__).resolve().parents[3]

# Stub the workflow sub-package so triggers.base can import WorkflowQueueService
if "app.services.workflow" not in sys.modules:
    _wf_pkg = types.ModuleType("app.services.workflow")
    _wf_pkg.__path__ = [str(_api_root / "app" / "services" / "workflow")]
    _wf_pkg.__package__ = "app.services.workflow"
    sys.modules["app.services.workflow"] = _wf_pkg

if "app.services.workflow.queue_service" not in sys.modules:
    _qs_mod = types.ModuleType("app.services.workflow.queue_service")
    _qs_mod.WorkflowQueueService = MagicMock()  # type: ignore[attr-defined]
    sys.modules["app.services.workflow.queue_service"] = _qs_mod

from app.services.triggers.handlers.google_sheets import (  # noqa: E402
    GoogleSheetsTriggerHandler,
    google_sheets_trigger_handler,
)


# ---------------------------------------------------------------------------
# Properties and class attributes
# ---------------------------------------------------------------------------


class TestGoogleSheetsHandlerProperties:
    def setup_method(self) -> None:
        self.handler = GoogleSheetsTriggerHandler()

    def test_trigger_names(self) -> None:
        names = self.handler.trigger_names
        assert "google_sheets_new_row" in names
        assert "google_sheets_new_sheet" in names

    def test_event_types(self) -> None:
        events = self.handler.event_types
        assert "GOOGLESHEETS_NEW_ROWS_TRIGGER" in events
        assert "GOOGLESHEETS_NEW_SHEET_ADDED_TRIGGER" in events

    def test_supported_triggers_list(self) -> None:
        assert len(self.handler.SUPPORTED_TRIGGERS) == 2

    def test_trigger_to_composio_map(self) -> None:
        assert (
            self.handler.TRIGGER_TO_COMPOSIO["google_sheets_new_row"]
            == "GOOGLESHEETS_NEW_ROWS_TRIGGER"
        )
        assert (
            self.handler.TRIGGER_TO_COMPOSIO["google_sheets_new_sheet"]
            == "GOOGLESHEETS_NEW_SHEET_ADDED_TRIGGER"
        )

    def test_global_instance(self) -> None:
        assert isinstance(google_sheets_trigger_handler, GoogleSheetsTriggerHandler)


# ---------------------------------------------------------------------------
# get_config_options - spreadsheet_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetConfigOptionsSpreadsheets:
    def setup_method(self) -> None:
        self.handler = GoogleSheetsTriggerHandler()

    @patch("app.services.triggers.handlers.google_sheets.get_composio_service")
    async def test_returns_spreadsheet_options(self, mock_get_svc: MagicMock) -> None:
        mock_tool = MagicMock()
        # Simulate successful tool invocation
        mock_tool.invoke = MagicMock(
            return_value={
                "successful": True,
                "data": {
                    "spreadsheets": [
                        {
                            "id": "sp1",
                            "name": "My Sheet",
                            "shared": False,
                            "owners": [{"me": True}],
                        },
                        {
                            "id": "sp2",
                            "name": "Shared Sheet",
                            "shared": True,
                            "owners": [{"me": False}],
                        },
                    ]
                },
                "error": None,
            }
        )
        mock_svc = MagicMock()
        mock_svc.get_tool = MagicMock(return_value=mock_tool)
        mock_get_svc.return_value = mock_svc

        result = await self.handler.get_config_options(
            trigger_name="google_sheets_new_row",
            field_name="spreadsheet_ids",
            user_id="user1",
            integration_id="google_sheets",
        )

        assert len(result) == 2
        assert result[0]["value"] == "sp1"
        assert result[0]["label"] == "My Sheet"
        assert "(Shared)" in result[1]["label"]

    @patch("app.services.triggers.handlers.google_sheets.get_composio_service")
    async def test_returns_empty_on_tool_not_found(
        self, mock_get_svc: MagicMock
    ) -> None:
        mock_svc = MagicMock()
        mock_svc.get_tool = MagicMock(return_value=None)
        mock_get_svc.return_value = mock_svc

        result = await self.handler.get_config_options(
            trigger_name="google_sheets_new_row",
            field_name="spreadsheet_ids",
            user_id="user1",
            integration_id="google_sheets",
        )
        assert result == []

    @patch("app.services.triggers.handlers.google_sheets.get_composio_service")
    async def test_returns_empty_on_api_error(self, mock_get_svc: MagicMock) -> None:
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(
            return_value={"successful": False, "data": {}, "error": "API error"}
        )
        mock_svc = MagicMock()
        mock_svc.get_tool = MagicMock(return_value=mock_tool)
        mock_get_svc.return_value = mock_svc

        result = await self.handler.get_config_options(
            trigger_name="google_sheets_new_row",
            field_name="spreadsheet_ids",
            user_id="user1",
            integration_id="google_sheets",
        )
        assert result == []

    @patch("app.services.triggers.handlers.google_sheets.get_composio_service")
    async def test_skips_sheets_without_id_or_name(
        self, mock_get_svc: MagicMock
    ) -> None:
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(
            return_value={
                "successful": True,
                "data": {
                    "spreadsheets": [
                        {"id": None, "name": "No ID", "shared": False, "owners": []},
                        {"id": "sp1", "name": None, "shared": False, "owners": []},
                        {"id": "sp2", "name": "Valid", "shared": False, "owners": []},
                    ]
                },
                "error": None,
            }
        )
        mock_svc = MagicMock()
        mock_svc.get_tool = MagicMock(return_value=mock_tool)
        mock_get_svc.return_value = mock_svc

        result = await self.handler.get_config_options(
            trigger_name="google_sheets_new_row",
            field_name="spreadsheet_ids",
            user_id="user1",
            integration_id="google_sheets",
        )
        assert len(result) == 1
        assert result[0]["value"] == "sp2"

    async def test_unknown_field_returns_empty(self) -> None:
        result = await self.handler.get_config_options(
            trigger_name="google_sheets_new_row",
            field_name="unknown_field",
            user_id="user1",
            integration_id="google_sheets",
        )
        assert result == []

    @patch("app.services.triggers.handlers.google_sheets.get_composio_service")
    async def test_exception_returns_empty(self, mock_get_svc: MagicMock) -> None:
        mock_get_svc.side_effect = RuntimeError("service down")

        result = await self.handler.get_config_options(
            trigger_name="google_sheets_new_row",
            field_name="spreadsheet_ids",
            user_id="user1",
            integration_id="google_sheets",
        )
        assert result == []


# ---------------------------------------------------------------------------
# get_config_options - sheet_names
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetConfigOptionsSheetNames:
    def setup_method(self) -> None:
        self.handler = GoogleSheetsTriggerHandler()

    @patch("app.services.triggers.handlers.google_sheets.get_composio_service")
    async def test_returns_grouped_sheet_names(self, mock_get_svc: MagicMock) -> None:
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(
            return_value={
                "successful": True,
                "data": {"sheet_names": ["Sheet1", "Sheet2"]},
                "error": None,
            }
        )
        mock_svc = MagicMock()
        mock_svc.get_tool = MagicMock(return_value=mock_tool)
        mock_get_svc.return_value = mock_svc

        result = await self.handler.get_config_options(
            trigger_name="google_sheets_new_row",
            field_name="sheet_names",
            user_id="user1",
            integration_id="google_sheets",
            parent_ids=["sp1"],
        )

        assert len(result) == 1
        assert result[0]["group"] == "sp1"
        assert len(result[0]["options"]) == 2

    @patch("app.services.triggers.handlers.google_sheets.get_composio_service")
    async def test_sheet_names_without_parent_ids_returns_empty(
        self, mock_get_svc: MagicMock
    ) -> None:
        result = await self.handler.get_config_options(
            trigger_name="google_sheets_new_row",
            field_name="sheet_names",
            user_id="user1",
            integration_id="google_sheets",
            parent_ids=None,
        )
        assert result == []

    @patch("app.services.triggers.handlers.google_sheets.get_composio_service")
    async def test_sheet_names_tool_not_found(self, mock_get_svc: MagicMock) -> None:
        mock_svc = MagicMock()
        mock_svc.get_tool = MagicMock(return_value=None)
        mock_get_svc.return_value = mock_svc

        result = await self.handler.get_config_options(
            trigger_name="google_sheets_new_row",
            field_name="sheet_names",
            user_id="user1",
            integration_id="google_sheets",
            parent_ids=["sp1"],
        )
        assert result == []

    @patch("app.services.triggers.handlers.google_sheets.get_composio_service")
    async def test_sheet_names_api_failure(self, mock_get_svc: MagicMock) -> None:
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(
            return_value={
                "successful": False,
                "data": {},
                "error": "Cannot access spreadsheet",
            }
        )
        mock_svc = MagicMock()
        mock_svc.get_tool = MagicMock(return_value=mock_tool)
        mock_get_svc.return_value = mock_svc

        result = await self.handler.get_config_options(
            trigger_name="google_sheets_new_row",
            field_name="sheet_names",
            user_id="user1",
            integration_id="google_sheets",
            parent_ids=["sp1"],
        )
        assert result == []

    @patch("app.services.triggers.handlers.google_sheets.get_composio_service")
    async def test_multiple_parent_ids(self, mock_get_svc: MagicMock) -> None:
        mock_tool = MagicMock()
        # Both spreadsheets return different sheets
        call_count = 0

        def invoke_side_effect(*args: object, **kwargs: object) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "successful": True,
                    "data": {"sheet_names": ["Sheet1"]},
                    "error": None,
                }
            return {
                "successful": True,
                "data": {"sheet_names": ["Sheet2", "Sheet3"]},
                "error": None,
            }

        mock_tool.invoke = MagicMock(side_effect=invoke_side_effect)
        mock_svc = MagicMock()
        mock_svc.get_tool = MagicMock(return_value=mock_tool)
        mock_get_svc.return_value = mock_svc

        result = await self.handler.get_config_options(
            trigger_name="google_sheets_new_row",
            field_name="sheet_names",
            user_id="user1",
            integration_id="google_sheets",
            parent_ids=["sp1", "sp2"],
        )

        assert len(result) == 2


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRegister:
    def setup_method(self) -> None:
        self.handler = GoogleSheetsTriggerHandler()

    async def test_unknown_trigger_raises(self) -> None:
        from app.utils.exceptions import TriggerRegistrationError

        mock_config = MagicMock()
        with pytest.raises(TriggerRegistrationError):
            await self.handler.register("user1", "wf1", "unknown_trigger", mock_config)

    async def test_wrong_config_type_for_new_row_raises(self) -> None:
        mock_config = MagicMock()
        mock_config.trigger_data = "not_the_right_type"

        with pytest.raises(TypeError, match="Expected GoogleSheetsNewRowConfig"):
            await self.handler.register(
                "user1", "wf1", "google_sheets_new_row", mock_config
            )

    async def test_wrong_config_type_for_new_sheet_raises(self) -> None:
        mock_config = MagicMock()
        mock_config.trigger_data = "not_the_right_type"

        with pytest.raises(TypeError, match="Expected GoogleSheetsNewSheetConfig"):
            await self.handler.register(
                "user1", "wf1", "google_sheets_new_sheet", mock_config
            )

    @patch.object(
        GoogleSheetsTriggerHandler,
        "_register_triggers_parallel",
        new_callable=AsyncMock,
    )
    async def test_new_row_with_spreadsheets_and_sheets(
        self, mock_parallel: AsyncMock
    ) -> None:
        from app.models.trigger_configs import GoogleSheetsNewRowConfig

        mock_parallel.return_value = ["trigger_id_1"]

        trigger_data = GoogleSheetsNewRowConfig(
            spreadsheet_ids=["sp1"],
            sheet_names=["sp1::Sheet1", "sp1::Sheet2"],
        )
        mock_config = MagicMock()
        mock_config.trigger_data = trigger_data

        result = await self.handler.register(
            "user1", "wf1", "google_sheets_new_row", mock_config
        )

        assert result == ["trigger_id_1"]
        mock_parallel.assert_called_once()
        configs_arg = mock_parallel.call_args.kwargs["configs"]
        assert len(configs_arg) == 2

    @patch.object(
        GoogleSheetsTriggerHandler,
        "_register_triggers_parallel",
        new_callable=AsyncMock,
    )
    async def test_new_row_without_sheet_names(self, mock_parallel: AsyncMock) -> None:
        from app.models.trigger_configs import GoogleSheetsNewRowConfig

        mock_parallel.return_value = ["t1"]
        trigger_data = GoogleSheetsNewRowConfig(spreadsheet_ids=["sp1"], sheet_names=[])
        mock_config = MagicMock()
        mock_config.trigger_data = trigger_data

        await self.handler.register(
            "user1", "wf1", "google_sheets_new_row", mock_config
        )

        configs_arg = mock_parallel.call_args.kwargs["configs"]
        assert len(configs_arg) == 1
        assert configs_arg[0] == {"spreadsheet_id": "sp1"}

    @patch.object(
        GoogleSheetsTriggerHandler,
        "_register_triggers_parallel",
        new_callable=AsyncMock,
    )
    async def test_new_sheet_register(self, mock_parallel: AsyncMock) -> None:
        from app.models.trigger_configs import GoogleSheetsNewSheetConfig

        mock_parallel.return_value = ["t1"]
        trigger_data = GoogleSheetsNewSheetConfig(
            spreadsheet_ids=["sp1", "sp2"],
        )
        mock_config = MagicMock()
        mock_config.trigger_data = trigger_data

        await self.handler.register(
            "user1", "wf1", "google_sheets_new_sheet", mock_config
        )

        configs_arg = mock_parallel.call_args.kwargs["configs"]
        assert len(configs_arg) == 2

    @patch.object(
        GoogleSheetsTriggerHandler,
        "_register_triggers_parallel",
        new_callable=AsyncMock,
    )
    async def test_new_row_no_spreadsheets(self, mock_parallel: AsyncMock) -> None:
        from app.models.trigger_configs import GoogleSheetsNewRowConfig

        mock_parallel.return_value = ["t1"]
        trigger_data = GoogleSheetsNewRowConfig(spreadsheet_ids=[], sheet_names=[])
        mock_config = MagicMock()
        mock_config.trigger_data = trigger_data

        await self.handler.register(
            "user1", "wf1", "google_sheets_new_row", mock_config
        )

        configs_arg = mock_parallel.call_args.kwargs["configs"]
        assert len(configs_arg) == 1
        assert configs_arg[0] == {}

    @patch.object(
        GoogleSheetsTriggerHandler,
        "_register_triggers_parallel",
        new_callable=AsyncMock,
    )
    async def test_sheet_name_without_composite_key(
        self, mock_parallel: AsyncMock
    ) -> None:
        from app.models.trigger_configs import GoogleSheetsNewRowConfig

        mock_parallel.return_value = ["t1"]
        trigger_data = GoogleSheetsNewRowConfig(
            spreadsheet_ids=["sp1"],
            sheet_names=["Sheet1"],  # No :: separator
        )
        mock_config = MagicMock()
        mock_config.trigger_data = trigger_data

        await self.handler.register(
            "user1", "wf1", "google_sheets_new_row", mock_config
        )

        configs_arg = mock_parallel.call_args.kwargs["configs"]
        assert len(configs_arg) == 1
        assert configs_arg[0]["sheet_name"] == "Sheet1"

    @patch.object(
        GoogleSheetsTriggerHandler,
        "_register_triggers_parallel",
        new_callable=AsyncMock,
    )
    async def test_composite_key_mismatched_spreadsheet_skipped(
        self, mock_parallel: AsyncMock
    ) -> None:
        from app.models.trigger_configs import GoogleSheetsNewRowConfig

        mock_parallel.return_value = ["t1"]
        trigger_data = GoogleSheetsNewRowConfig(
            spreadsheet_ids=["sp1"],
            sheet_names=["sp2::Sheet1"],  # Different spreadsheet
        )
        mock_config = MagicMock()
        mock_config.trigger_data = trigger_data

        await self.handler.register(
            "user1", "wf1", "google_sheets_new_row", mock_config
        )

        configs_arg = mock_parallel.call_args.kwargs["configs"]
        # sp2::Sheet1 doesn't match sp1, so it's skipped
        assert len(configs_arg) == 0


# ---------------------------------------------------------------------------
# find_workflows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFindWorkflows:
    def setup_method(self) -> None:
        self.handler = GoogleSheetsTriggerHandler()

    @patch("app.services.triggers.handlers.google_sheets.workflows_collection")
    async def test_finds_matching_workflows(self, mock_coll: MagicMock) -> None:
        workflow_doc = {
            "_id": "wf1",
            "user_id": "user1",
            "title": "Test WF",
            "steps": [],
            "activated": True,
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "composio_trigger_ids": ["tid1"],
            },
        }

        async def mock_cursor():
            yield workflow_doc

        mock_coll.find = MagicMock(return_value=mock_cursor())

        result = await self.handler.find_workflows(
            "GOOGLESHEETS_NEW_ROWS_TRIGGER", "tid1", {"row": "data"}
        )

        assert len(result) == 1

    @patch("app.services.triggers.handlers.google_sheets.workflows_collection")
    async def test_returns_empty_on_no_match(self, mock_coll: MagicMock) -> None:
        async def mock_cursor():
            return
            yield  # NOSONAR — intentionally unreachable: makes this an async generator

        mock_coll.find = MagicMock(return_value=mock_cursor())

        result = await self.handler.find_workflows(
            "GOOGLESHEETS_NEW_ROWS_TRIGGER", "tid1", {}
        )
        assert result == []

    @patch("app.services.triggers.handlers.google_sheets.workflows_collection")
    async def test_handles_db_error(self, mock_coll: MagicMock) -> None:
        mock_coll.find = MagicMock(side_effect=RuntimeError("db down"))

        result = await self.handler.find_workflows(
            "GOOGLESHEETS_NEW_ROWS_TRIGGER", "tid1", {}
        )
        assert result == []

    @patch("app.services.triggers.handlers.google_sheets.workflows_collection")
    async def test_skips_invalid_workflow_docs(self, mock_coll: MagicMock) -> None:
        # This doc will cause Workflow() to fail
        bad_doc = {"_id": "wf1"}  # Missing required fields

        async def mock_cursor():
            yield bad_doc

        mock_coll.find = MagicMock(return_value=mock_cursor())

        result = await self.handler.find_workflows(
            "GOOGLESHEETS_NEW_ROWS_TRIGGER", "tid1", {}
        )
        assert result == []

    @patch("app.services.triggers.handlers.google_sheets.workflows_collection")
    async def test_validates_new_row_payload(self, mock_coll: MagicMock) -> None:
        """Should attempt payload validation but still query even if it fails."""

        async def mock_cursor():
            return
            yield

        mock_coll.find = MagicMock(return_value=mock_cursor())

        # Invalid payload structure, but find_workflows should still work
        result = await self.handler.find_workflows(
            "GOOGLESHEETS_NEW_ROWS_TRIGGER",
            "tid1",
            {"invalid": "payload"},
        )
        assert result == []

    @patch("app.services.triggers.handlers.google_sheets.workflows_collection")
    async def test_validates_new_sheet_event(self, mock_coll: MagicMock) -> None:
        async def mock_cursor():
            return
            yield  # NOSONAR — intentionally unreachable: makes this an async generator

        mock_coll.find = MagicMock(return_value=mock_cursor())

        result = await self.handler.find_workflows(
            "GOOGLESHEETS_NEW_SHEET_ADDED_TRIGGER",
            "tid1",
            {"sheet": "data"},
        )
        assert result == []
