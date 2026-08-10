"""Unit tests for the workflows API endpoints.

Tests cover:
- POST   /api/v1/workflows
- GET    /api/v1/workflows
- POST   /api/v1/workflows/{id}/execute
- GET    /api/v1/workflows/{id}/executions
- GET    /api/v1/workflows/{id}/status
- POST   /api/v1/workflows/{id}/activate
- POST   /api/v1/workflows/{id}/deactivate
- POST   /api/v1/workflows/{id}/regenerate-steps
- POST   /api/v1/workflows/from-todo
- POST   /api/v1/workflows/{id}/publish
- POST   /api/v1/workflows/{id}/unpublish
- GET    /api/v1/workflows/explore
- GET    /api/v1/workflows/community
- GET    /api/v1/workflows/public/{ref}
- POST   /api/v1/workflows/generate-prompt
- GET    /api/v1/workflows/{id}
- PUT    /api/v1/workflows/{id}
- POST   /api/v1/workflows/{id}/reset-to-default
- DELETE /api/v1/workflows/{id}
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from pymongo.errors import DuplicateKeyError

from app.constants.log_tags import LogTag

from app.models.workflow_execution_models import WorkflowExecutionsResponse
from app.models.workflow_models import (
    CreateWorkflowRequest,
    PromptTriggerHint,
    PublicWorkflowRow,
    PublicWorkflowsResponse,
    UpdateWorkflowRequest,
    Workflow,
    WorkflowCreatorInfo,
    WorkflowDocument,
    WorkflowExecutionRequest,
    WorkflowExecutionResponse,
    WorkflowStatusResponse,
)
from app.utils.exceptions import TriggerRegistrationError

BASE_URL = "/api/v1/workflows"

# Fake user resolved by the client fixture's auth override.
USER_ID = "507f1f77bcf86cd799439011"
# FAKE_USER stores timezone "UTC"; get_user_timezone_from_preferences resolves it to "UTC".
USER_TIMEZONE = "UTC"

# Patch targets
_WF_SERVICE = "app.api.v1.endpoints.workflows.WorkflowService"
_WF_GEN_SERVICE = "app.api.v1.endpoints.workflows.WorkflowGenerationService"
_WF_REPO = "app.api.v1.endpoints.workflows.workflow_repository"
_GET_EXECUTIONS = "app.api.v1.endpoints.workflows.get_executions"
_GEN_SLUG = "app.api.v1.endpoints.workflows.generate_unique_workflow_slug"
_RESET_DEFAULT = "app.api.v1.endpoints.workflows.reset_system_workflow_to_default"
_INTEGRATIONS_STATUS = "app.api.v1.endpoints.workflows.get_all_integrations_status"


@pytest.fixture
def mock_log() -> Iterator[MagicMock]:
    """The endpoint module's wide-event logger, patched so calls are assertable.

    The observability contract is part of the endpoint behavior — a wide event
    carrying the wrong operation/outcome/error is a broken alert path, so
    successful paths pin their ``log.set``/``log.set_ns``/``log.info`` calls and
    failure paths pin the exact ``log.error`` call.
    """
    with patch("app.api.v1.endpoints.workflows.log") as m:
        yield m


def _make_workflow(**overrides) -> Workflow:
    """Build a real Workflow Pydantic model instance for service mock returns."""
    base: dict = {
        "id": "wf_abc123",
        "user_id": USER_ID,
        "title": "My Workflow",
        "description": "A test workflow",
        "prompt": "Do the thing",
        "steps": [
            {
                "id": "step_1",
                "title": "Step 1",
                "category": "general",
                "description": "First step",
            }
        ],
        "trigger_config": {"type": "manual", "enabled": True},
        "activated": True,
        "is_public": False,
        "slug": None,
        "total_executions": 0,
        "successful_executions": 0,
        "last_executed_at": None,
        "created_at": datetime(2025, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2025, 1, 1, tzinfo=UTC),
    }
    base.update(overrides)
    return Workflow(**base)


def _make_workflow_doc(**overrides) -> WorkflowDocument:
    """Build a WorkflowDocument stand-in for repository mock returns (the typed
    seam the endpoints read from)."""
    wf = _make_workflow(**overrides)
    return WorkflowDocument(**wf.model_dump())


def _create_workflow_payload(**overrides) -> dict:
    base: dict = {
        "title": "My Workflow",
        "prompt": "Do the thing for me",
        "trigger_config": {"type": "manual", "enabled": True},
    }
    base.update(overrides)
    return base


def _assert_workflow_body(data: dict, *, id: str = "wf_abc123", title: str = "My Workflow") -> None:
    """Pin the serialized workflow shape the wire contract promises."""
    workflow = data["workflow"]
    assert workflow["id"] == id
    assert workflow["user_id"] == USER_ID
    assert workflow["title"] == title
    assert workflow["description"] == "A test workflow"
    assert workflow["prompt"] == "Do the thing"
    assert workflow["steps"] == [
        {
            "id": "step_1",
            "title": "Step 1",
            "category": "general",
            "description": "First step",
        }
    ]
    assert workflow["trigger_config"]["type"] == "manual"
    assert workflow["trigger_config"]["enabled"] is True
    assert workflow["activated"] is True
    assert workflow["is_public"] is False
    assert workflow["slug"] is None
    assert workflow["integration_ids"] == []
    assert workflow["created_at"] == "2025-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# POST /workflows
# ---------------------------------------------------------------------------


class TestCreateWorkflow:
    """Tests for the create workflow endpoint."""

    async def test_create_workflow_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        mock_wf = _make_workflow()
        with (
            patch(
                _INTEGRATIONS_STATUS,
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                f"{_WF_SERVICE}.create_workflow",
                new_callable=AsyncMock,
                return_value=mock_wf,
            ) as mock_create,
        ):
            response = await client.post(BASE_URL, json=_create_workflow_payload())

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Workflow created successfully"
        _assert_workflow_body(data)

        assert mock_create.await_count == 1
        assert mock_create.await_args.args[1] == USER_ID
        assert mock_create.await_args.kwargs == {"user_timezone": USER_TIMEZONE}
        sent_request: CreateWorkflowRequest = mock_create.await_args.args[0]
        assert sent_request.title == "My Workflow"
        assert sent_request.prompt == "Do the thing for me"
        assert sent_request.trigger_config.type.value == "manual"
        assert sent_request.trigger_config.enabled is True

        mock_log.set.assert_any_call(
            user={"id": USER_ID},
            workflow={"operation": "create", "title": "My Workflow", "trigger_type": "TriggerType.MANUAL"},
        )
        mock_log.set.assert_any_call(
            workflow={
                "id": "wf_abc123",
                "title": "My Workflow",
                "steps_count": 1,
                "trigger_type": None,
            },
            outcome="success",
        )
        mock_log.error.assert_not_called()

    async def test_create_workflow_strips_system_fields(self, client: AsyncClient):
        """System fields sent by a client are stripped before reaching the service."""
        with (
            patch(_INTEGRATIONS_STATUS, new_callable=AsyncMock, return_value={}),
            patch(
                f"{_WF_SERVICE}.create_workflow",
                new_callable=AsyncMock,
                return_value=_make_workflow(),
            ) as mock_create,
        ):
            response = await client.post(
                BASE_URL,
                json=_create_workflow_payload(
                    is_system_workflow=True,
                    source_integration="gmail",
                    system_workflow_key="gmail:email_intelligence",
                ),
            )

        assert response.status_code == 200
        sent_request: CreateWorkflowRequest = mock_create.await_args.args[0]
        assert sent_request.is_system_workflow is False
        assert sent_request.source_integration is None
        assert sent_request.system_workflow_key is None

    async def test_create_workflow_defaults_integration_ids_from_connected(
        self, client: AsyncClient
    ):
        """No integration_ids in the payload → default to the user's connected ones."""
        with (
            patch(
                _INTEGRATIONS_STATUS,
                new_callable=AsyncMock,
                return_value={"gmail": True, "slack": False, "notion": True},
            ) as status_map,
            patch(
                f"{_WF_SERVICE}.create_workflow",
                new_callable=AsyncMock,
                return_value=_make_workflow(),
            ) as mock_create,
        ):
            response = await client.post(BASE_URL, json=_create_workflow_payload())

        assert response.status_code == 200
        sent_request: CreateWorkflowRequest = mock_create.await_args.args[0]
        assert sent_request.integration_ids == ["gmail", "notion"]
        status_map.assert_awaited_once_with(USER_ID)

    async def test_create_workflow_no_connected_integrations_leaves_ids_none(
        self, client: AsyncClient
    ):
        """Nothing connected → integration_ids stays None (the `or None` sentinel)."""
        with (
            patch(_INTEGRATIONS_STATUS, new_callable=AsyncMock, return_value={}),
            patch(
                f"{_WF_SERVICE}.create_workflow",
                new_callable=AsyncMock,
                return_value=_make_workflow(),
            ) as mock_create,
        ):
            response = await client.post(BASE_URL, json=_create_workflow_payload())

        assert response.status_code == 200
        sent_request: CreateWorkflowRequest = mock_create.await_args.args[0]
        assert sent_request.integration_ids is None

    async def test_create_workflow_keeps_explicit_integration_ids(self, client: AsyncClient):
        """Payload integration_ids win — the status map is not consulted."""
        status_map = AsyncMock()
        with (
            patch(_INTEGRATIONS_STATUS, status_map),
            patch(
                f"{_WF_SERVICE}.create_workflow",
                new_callable=AsyncMock,
                return_value=_make_workflow(),
            ) as mock_create,
        ):
            response = await client.post(
                BASE_URL,
                json=_create_workflow_payload(integration_ids=["gmail"]),
            )

        assert response.status_code == 200
        sent_request: CreateWorkflowRequest = mock_create.await_args.args[0]
        assert sent_request.integration_ids == ["gmail"]
        status_map.assert_not_awaited()

    async def test_create_workflow_logs_trigger_type_when_present(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        """A workflow carrying a ``trigger_type`` attribute surfaces it in the
        success wide event — the ``hasattr`` guard takes the truthy branch."""
        mock_wf = _make_workflow()
        object.__setattr__(mock_wf, "trigger_type", "manual")
        with (
            patch(_INTEGRATIONS_STATUS, new_callable=AsyncMock, return_value={}),
            patch(
                f"{_WF_SERVICE}.create_workflow",
                new_callable=AsyncMock,
                return_value=mock_wf,
            ),
        ):
            response = await client.post(BASE_URL, json=_create_workflow_payload())

        assert response.status_code == 200
        mock_log.set.assert_any_call(
            workflow={
                "id": "wf_abc123",
                "title": "My Workflow",
                "steps_count": 1,
                "trigger_type": "manual",
            },
            outcome="success",
        )

    async def test_create_workflow_missing_title_returns_422(self, client: AsyncClient):
        response = await client.post(
            BASE_URL,
            json={
                "prompt": "Do something",
                "trigger_config": {"type": "manual", "enabled": True},
            },
        )
        assert response.status_code == 422

    async def test_create_workflow_missing_prompt_returns_422(self, client: AsyncClient):
        response = await client.post(
            BASE_URL,
            json={
                "title": "My Workflow",
                "trigger_config": {"type": "manual", "enabled": True},
            },
        )
        assert response.status_code == 422

    async def test_create_workflow_empty_title_returns_422(self, client: AsyncClient):
        response = await client.post(
            BASE_URL,
            json=_create_workflow_payload(title=""),
        )
        assert response.status_code == 422

    async def test_create_workflow_value_error_returns_400(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with (
            patch(_INTEGRATIONS_STATUS, new_callable=AsyncMock, return_value={}),
            patch(
                f"{_WF_SERVICE}.create_workflow",
                new_callable=AsyncMock,
                side_effect=ValueError("Invalid trigger config"),
            ),
        ):
            response = await client.post(BASE_URL, json=_create_workflow_payload())

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid trigger config"
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID},
            workflow={"operation": "create", "title": "My Workflow", "trigger_type": "TriggerType.MANUAL"},
        )
        mock_log.error.assert_not_called()

    async def test_create_workflow_trigger_registration_error_returns_400(
        self, client: AsyncClient
    ):
        with (
            patch(_INTEGRATIONS_STATUS, new_callable=AsyncMock, return_value={}),
            patch(
                f"{_WF_SERVICE}.create_workflow",
                new_callable=AsyncMock,
                side_effect=TriggerRegistrationError("Trigger failed", "gmail_new_message"),
            ),
        ):
            response = await client.post(BASE_URL, json=_create_workflow_payload())

        assert response.status_code == 400
        assert response.json()["detail"] == "Trigger failed"

    async def test_create_workflow_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with (
            patch(_INTEGRATIONS_STATUS, new_callable=AsyncMock, return_value={}),
            patch(
                f"{_WF_SERVICE}.create_workflow",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB failure"),
            ),
        ):
            response = await client.post(BASE_URL, json=_create_workflow_payload())

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to create workflow"
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID},
            workflow={"operation": "create", "title": "My Workflow", "trigger_type": "TriggerType.MANUAL"},
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error creating workflow",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="DB failure",
        )


# ---------------------------------------------------------------------------
# GET /workflows
# ---------------------------------------------------------------------------


class TestListWorkflows:
    """Tests for the list workflows endpoint."""

    async def test_list_workflows_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        with patch(
            f"{_WF_SERVICE}.list_workflows",
            new_callable=AsyncMock,
            return_value=([_make_workflow()], 1),
        ) as mock_list:
            response = await client.get(BASE_URL)

        assert response.status_code == 200
        data = response.json()
        assert len(data["workflows"]) == 1
        _assert_workflow_body({"workflow": data["workflows"][0], "message": ""})
        mock_list.assert_awaited_once_with(USER_ID)
        mock_log.set.assert_any_call(user={"id": USER_ID}, workflow={"operation": "list"})
        mock_log.set.assert_any_call(workflow={"result_count": 1}, outcome="success")
        mock_log.error.assert_not_called()

    async def test_list_workflows_empty(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.list_workflows",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            response = await client.get(BASE_URL)

        assert response.status_code == 200
        assert response.json() == {"workflows": []}

    async def test_list_workflows_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_SERVICE}.list_workflows",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(BASE_URL)

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to list workflows"
        mock_log.set.assert_called_once_with(user={"id": USER_ID}, workflow={"operation": "list"})
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error listing workflows",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# POST /workflows/{id}/execute
# ---------------------------------------------------------------------------


class TestExecuteWorkflow:
    """Tests for the execute workflow endpoint."""

    async def test_execute_workflow_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        mock_result = WorkflowExecutionResponse(
            execution_id="exec_123",
            message="Workflow execution started",
        )
        with patch(
            f"{_WF_SERVICE}.execute_workflow",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_execute:
            response = await client.post(f"{BASE_URL}/wf_abc123/execute", json={})

        assert response.status_code == 200
        assert response.json() == {
            "execution_id": "exec_123",
            "message": "Workflow execution started",
        }
        mock_execute.assert_awaited_once_with(
            "wf_abc123", WorkflowExecutionRequest(context=None), USER_ID
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID}, workflow={"operation": "execute", "id": "wf_abc123"}
        )
        mock_log.set.assert_any_call(workflow={"execution_id": "exec_123"}, outcome="success")
        mock_log.error.assert_not_called()

    async def test_execute_workflow_falsy_execution_id_logs_none(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        """A falsy execution_id takes the ``and``-short-circuit: the log records
        None, and the response echoes the raw value back."""
        mock_result = WorkflowExecutionResponse(execution_id="", message="OK")
        with patch(
            f"{_WF_SERVICE}.execute_workflow",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_execute:
            response = await client.post(f"{BASE_URL}/wf_abc123/execute", json={})

        assert response.status_code == 200
        assert response.json() == {"execution_id": "", "message": "OK"}
        mock_execute.assert_awaited_once_with(
            "wf_abc123", WorkflowExecutionRequest(context=None), USER_ID
        )
        mock_log.set.assert_any_call(workflow={"execution_id": None}, outcome="success")

    async def test_execute_workflow_with_context(self, client: AsyncClient):
        mock_result = WorkflowExecutionResponse(
            execution_id="exec_123",
            message="OK",
        )
        with patch(
            f"{_WF_SERVICE}.execute_workflow",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_execute:
            response = await client.post(
                f"{BASE_URL}/wf_abc123/execute",
                json={"context": {"key": "value"}},
            )

        assert response.status_code == 200
        assert response.json()["execution_id"] == "exec_123"
        mock_execute.assert_awaited_once_with(
            "wf_abc123", WorkflowExecutionRequest(context={"key": "value"}), USER_ID
        )

    async def test_execute_workflow_value_error_returns_400(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.execute_workflow",
            new_callable=AsyncMock,
            side_effect=ValueError("Workflow is deactivated"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/execute", json={})

        assert response.status_code == 400
        assert response.json()["detail"] == "Workflow is deactivated"

    async def test_execute_workflow_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_SERVICE}.execute_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Execution engine error"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/execute", json={})

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to execute workflow"
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID}, workflow={"operation": "execute", "id": "wf_abc123"}
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error executing workflow",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="Execution engine error",
        )


# ---------------------------------------------------------------------------
# GET /workflows/{id}/executions
# ---------------------------------------------------------------------------


class TestGetWorkflowExecutions:
    """Tests for the get workflow executions endpoint."""

    async def test_get_executions_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        mock_result = WorkflowExecutionsResponse(
            executions=[],
            total=0,
            has_more=False,
        )
        with patch(
            _GET_EXECUTIONS,
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_get:
            response = await client.get(f"{BASE_URL}/wf_abc123/executions")

        assert response.status_code == 200
        assert response.json() == {"executions": [], "total": 0, "has_more": False}
        mock_get.assert_awaited_once_with(
            workflow_id="wf_abc123",
            user_id=USER_ID,
            limit=10,
            offset=0,
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID}, workflow={"operation": "list_executions", "id": "wf_abc123"}
        )
        mock_log.set.assert_any_call(workflow={"result_count": 0}, outcome="success")
        mock_log.error.assert_not_called()

    async def test_get_executions_none_executions_logs_none(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        """A result body with ``executions=None`` (model_construct bypasses
        validation) logs result_count=None — the ``and`` guard on
        ``is not None`` short-circuits instead of taking the length."""
        mock_result = WorkflowExecutionsResponse.model_construct(
            executions=None, total=0, has_more=False
        )
        with patch(
            _GET_EXECUTIONS,
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_get:
            response = await client.get(f"{BASE_URL}/wf_abc123/executions")

        assert response.status_code == 200
        mock_get.assert_awaited_once_with(
            workflow_id="wf_abc123", user_id=USER_ID, limit=10, offset=0
        )
        mock_log.set.assert_any_call(workflow={"result_count": None}, outcome="success")

    async def test_get_executions_with_pagination(self, client: AsyncClient):
        mock_result = WorkflowExecutionsResponse(executions=[], total=0, has_more=False)
        with patch(
            _GET_EXECUTIONS,
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_get:
            await client.get(
                f"{BASE_URL}/wf_abc123/executions",
                params={"limit": 5, "offset": 10},
            )

        mock_get.assert_awaited_once_with(
            workflow_id="wf_abc123",
            user_id=USER_ID,
            limit=5,
            offset=10,
        )

    async def test_get_executions_clamps_limit_above_max(self, client: AsyncClient):
        mock_result = WorkflowExecutionsResponse(executions=[], total=0, has_more=False)
        with patch(
            _GET_EXECUTIONS,
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_get:
            response = await client.get(
                f"{BASE_URL}/wf_abc123/executions",
                params={"limit": 1000},
            )

        assert response.status_code == 200
        mock_get.assert_awaited_once_with(
            workflow_id="wf_abc123", user_id=USER_ID, limit=100, offset=0
        )

    async def test_get_executions_clamps_limit_and_offset_below_min(self, client: AsyncClient):
        mock_result = WorkflowExecutionsResponse(executions=[], total=0, has_more=False)
        with patch(
            _GET_EXECUTIONS,
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_get:
            response = await client.get(
                f"{BASE_URL}/wf_abc123/executions",
                params={"limit": 0, "offset": -5},
            )

        assert response.status_code == 200
        mock_get.assert_awaited_once_with(
            workflow_id="wf_abc123", user_id=USER_ID, limit=1, offset=0
        )

    async def test_get_executions_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            _GET_EXECUTIONS,
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(f"{BASE_URL}/wf_abc123/executions")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to get workflow executions"
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID}, workflow={"operation": "list_executions", "id": "wf_abc123"}
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error getting executions for workflow",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# GET /workflows/{id}/status
# ---------------------------------------------------------------------------


class TestGetWorkflowStatus:
    """Tests for the get workflow status endpoint."""

    async def test_get_status_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        mock_status = WorkflowStatusResponse(
            workflow_id="wf_abc123",
            activated=True,
            current_step_index=0,
            total_steps=3,
            progress_percentage=0.0,
            last_updated=datetime(2025, 1, 1, tzinfo=UTC),
            error_message=None,
            logs=[],
        )
        with patch(
            f"{_WF_SERVICE}.get_workflow_status",
            new_callable=AsyncMock,
            return_value=mock_status,
        ) as mock_status_call:
            response = await client.get(f"{BASE_URL}/wf_abc123/status")

        assert response.status_code == 200
        assert response.json() == {
            "workflow_id": "wf_abc123",
            "activated": True,
            "current_step_index": 0,
            "total_steps": 3,
            "progress_percentage": 0.0,
            "last_updated": "2025-01-01T00:00:00Z",
            "error_message": None,
            "logs": [],
        }
        mock_status_call.assert_awaited_once_with("wf_abc123", USER_ID)
        mock_log.set.assert_any_call(
            user={"id": USER_ID}, workflow={"operation": "status", "id": "wf_abc123"}
        )
        mock_log.set.assert_any_call(workflow={"execution_id": None}, outcome="success")
        mock_log.error.assert_not_called()

    async def test_get_status_not_found_returns_404(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.get_workflow_status",
            new_callable=AsyncMock,
            side_effect=ValueError("Workflow not found"),
        ):
            response = await client.get(f"{BASE_URL}/wf_nonexist/status")

        assert response.status_code == 404
        assert response.json()["detail"] == "Workflow not found"

    async def test_get_status_logs_execution_id_when_present(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        """A status body carrying an ``execution_id`` attribute surfaces it in
        the success wide event — the ``hasattr`` guard takes the truthy branch."""
        mock_status = WorkflowStatusResponse(
            workflow_id="wf_abc123",
            activated=True,
            current_step_index=0,
            total_steps=3,
            progress_percentage=0.0,
            last_updated=datetime(2025, 1, 1, tzinfo=UTC),
            error_message=None,
            logs=[],
        )
        object.__setattr__(mock_status, "execution_id", "exec_9")
        with patch(
            f"{_WF_SERVICE}.get_workflow_status",
            new_callable=AsyncMock,
            return_value=mock_status,
        ):
            response = await client.get(f"{BASE_URL}/wf_abc123/status")

        assert response.status_code == 200
        mock_log.set.assert_any_call(workflow={"execution_id": "exec_9"}, outcome="success")

    async def test_get_status_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_SERVICE}.get_workflow_status",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(f"{BASE_URL}/wf_abc123/status")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to get workflow status"
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID}, workflow={"operation": "status", "id": "wf_abc123"}
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error getting workflow status",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# POST /workflows/{id}/activate
# ---------------------------------------------------------------------------


class TestActivateWorkflow:
    """Tests for the activate workflow endpoint."""

    async def test_activate_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        mock_wf = _make_workflow(activated=True)
        with patch(
            f"{_WF_SERVICE}.activate_workflow",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ) as mock_activate:
            response = await client.post(f"{BASE_URL}/wf_abc123/activate")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Workflow activated successfully"
        _assert_workflow_body(data)
        mock_activate.assert_awaited_once_with(
            "wf_abc123", USER_ID, user_timezone=USER_TIMEZONE
        )
        mock_log.set.assert_any_call(user={"id": USER_ID}, workflow={"id": "wf_abc123"})
        mock_log.set.assert_any_call(outcome="success")
        mock_log.error.assert_not_called()

    async def test_activate_not_found_returns_404(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.activate_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.post(f"{BASE_URL}/wf_nonexist/activate")

        assert response.status_code == 404
        assert response.json()["detail"] == "Workflow wf_nonexist not found"

    async def test_activate_value_error_returns_400(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.activate_workflow",
            new_callable=AsyncMock,
            side_effect=ValueError("Missing step integrations"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/activate")

        assert response.status_code == 400
        assert response.json()["detail"] == "Missing step integrations"

    async def test_activate_trigger_registration_error_returns_400(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.activate_workflow",
            new_callable=AsyncMock,
            side_effect=TriggerRegistrationError("Trigger failed", "gmail_new_message"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/activate")

        assert response.status_code == 400
        assert response.json()["detail"] == "Trigger failed"

    async def test_activate_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_SERVICE}.activate_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Trigger error"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/activate")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to activate workflow"
        mock_log.set.assert_called_once_with(user={"id": USER_ID}, workflow={"id": "wf_abc123"})
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error activating workflow",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="Trigger error",
        )


# ---------------------------------------------------------------------------
# POST /workflows/{id}/deactivate
# ---------------------------------------------------------------------------


class TestDeactivateWorkflow:
    """Tests for the deactivate workflow endpoint."""

    async def test_deactivate_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        mock_wf = _make_workflow(activated=False)
        with patch(
            f"{_WF_SERVICE}.deactivate_workflow",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ) as mock_deactivate:
            response = await client.post(f"{BASE_URL}/wf_abc123/deactivate")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Workflow deactivated successfully"
        assert data["workflow"]["activated"] is False
        mock_deactivate.assert_awaited_once_with(
            "wf_abc123", USER_ID, user_timezone=USER_TIMEZONE
        )
        mock_log.set.assert_any_call(user={"id": USER_ID}, workflow={"id": "wf_abc123"})
        mock_log.set.assert_any_call(outcome="success")
        mock_log.error.assert_not_called()

    async def test_deactivate_not_found_returns_404(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.deactivate_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.post(f"{BASE_URL}/wf_nonexist/deactivate")

        assert response.status_code == 404
        assert response.json()["detail"] == "Workflow wf_nonexist not found"

    async def test_deactivate_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_SERVICE}.deactivate_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/deactivate")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to deactivate workflow"
        mock_log.set.assert_called_once_with(user={"id": USER_ID}, workflow={"id": "wf_abc123"})
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error deactivating workflow",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# POST /workflows/{id}/regenerate-steps
# ---------------------------------------------------------------------------


class TestRegenerateSteps:
    """Tests for the regenerate workflow steps endpoint."""

    async def test_regenerate_steps_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        mock_wf = _make_workflow()
        with patch(
            f"{_WF_SERVICE}.regenerate_workflow_steps",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ) as mock_regenerate:
            response = await client.post(
                f"{BASE_URL}/wf_abc123/regenerate-steps",
                json={
                    "instruction": "Make it better",
                    "reason": "User asked",
                    "force_different_tools": True,
                    "integration_ids": ["gmail"],
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Workflow regeneration started"
        _assert_workflow_body(data)
        mock_regenerate.assert_awaited_once_with(
            "wf_abc123",
            USER_ID,
            regeneration_reason="User asked",
            force_different_tools=True,
            integration_ids=["gmail"],
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID},
            workflow={"operation": "regenerate_steps", "id": "wf_abc123"},
        )
        mock_log.set.assert_any_call(outcome="success")
        mock_log.error.assert_not_called()

    async def test_regenerate_steps_passes_defaults(self, client: AsyncClient):
        mock_wf = _make_workflow()
        with patch(
            f"{_WF_SERVICE}.regenerate_workflow_steps",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ) as mock_regenerate:
            response = await client.post(
                f"{BASE_URL}/wf_abc123/regenerate-steps",
                json={"instruction": "Make it better"},
            )

        assert response.status_code == 200
        mock_regenerate.assert_awaited_once_with(
            "wf_abc123",
            USER_ID,
            regeneration_reason=None,
            force_different_tools=False,
            integration_ids=None,
        )

    async def test_regenerate_steps_not_found_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        """When the service returns None the endpoint raises HTTPException(404)
        inside a bare ``except Exception`` block, so the caller actually
        receives a 500.  (The endpoint is missing ``except HTTPException: raise``.)
        """
        with patch(
            f"{_WF_SERVICE}.regenerate_workflow_steps",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.post(
                f"{BASE_URL}/wf_abc123/regenerate-steps",
                json={"instruction": "Change tools"},
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to regenerate workflow steps"
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID},
            workflow={"operation": "regenerate_steps", "id": "wf_abc123"},
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error regenerating workflow steps",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="HTTPException",
            error="404: Workflow not found",
        )

    async def test_regenerate_steps_value_error_returns_400(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.regenerate_workflow_steps",
            new_callable=AsyncMock,
            side_effect=ValueError("Cannot regenerate"),
        ):
            response = await client.post(
                f"{BASE_URL}/wf_abc123/regenerate-steps",
                json={"instruction": "Change tools"},
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "Cannot regenerate"

    async def test_regenerate_steps_missing_instruction_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{BASE_URL}/wf_abc123/regenerate-steps",
            json={},
        )
        assert response.status_code == 422

    async def test_regenerate_steps_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_SERVICE}.regenerate_workflow_steps",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM timeout"),
        ):
            response = await client.post(
                f"{BASE_URL}/wf_abc123/regenerate-steps",
                json={"instruction": "Regen steps"},
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to regenerate workflow steps"
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID},
            workflow={"operation": "regenerate_steps", "id": "wf_abc123"},
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error regenerating workflow steps",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="LLM timeout",
        )


# ---------------------------------------------------------------------------
# POST /workflows/from-todo
# ---------------------------------------------------------------------------


class TestCreateWorkflowFromTodo:
    """Tests for the create workflow from todo endpoint."""

    async def test_from_todo_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        mock_wf = _make_workflow(title="Todo: Buy groceries")
        with patch(
            f"{_WF_SERVICE}.create_workflow",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ) as mock_create:
            response = await client.post(
                f"{BASE_URL}/from-todo",
                json={
                    "todo_id": "todo_123",
                    "todo_title": "Buy groceries",
                    "todo_description": "Get milk, eggs, and bread",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Workflow created from todo successfully"
        assert data["workflow"]["title"] == "Todo: Buy groceries"

        mock_create.assert_awaited_once()
        expected = CreateWorkflowRequest(
            title="Todo: Buy groceries",
            description="Workflow for todo: Buy groceries",
            prompt="Get milk, eggs, and bread",
            trigger_config={"type": "manual", "enabled": True},
            generate_immediately=True,
        )
        assert mock_create.await_args.args[0] == expected
        assert mock_create.await_args.args[1] == USER_ID
        assert mock_create.await_args.kwargs == {"user_timezone": USER_TIMEZONE}
        mock_log.set.assert_any_call(user={"id": USER_ID}, workflow={"operation": "create"})
        mock_log.set.assert_any_call(
            workflow={"id": "wf_abc123", "title": "Todo: Buy groceries", "steps_count": 1},
            outcome="success",
        )
        mock_log.error.assert_not_called()

    async def test_from_todo_prompt_falls_back_to_title(self, client: AsyncClient):
        """No todo_description → prompt becomes 'Complete todo: {title}'."""
        with patch(
            f"{_WF_SERVICE}.create_workflow",
            new_callable=AsyncMock,
            return_value=_make_workflow(),
        ) as mock_create:
            response = await client.post(
                f"{BASE_URL}/from-todo",
                json={"todo_id": "todo_123", "todo_title": "Buy groceries"},
            )

        assert response.status_code == 200
        expected = CreateWorkflowRequest(
            title="Todo: Buy groceries",
            description="Workflow for todo: Buy groceries",
            prompt="Complete todo: Buy groceries",
            trigger_config={"type": "manual", "enabled": True},
            generate_immediately=True,
        )
        assert mock_create.await_args.args[0] == expected

    async def test_from_todo_missing_todo_id_returns_400(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        response = await client.post(
            f"{BASE_URL}/from-todo",
            json={"todo_title": "Buy groceries"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "todo_id and todo_title are required"
        mock_log.set.assert_called_once_with(user={"id": USER_ID}, workflow={"operation": "create"})
        mock_log.error.assert_not_called()

    async def test_from_todo_missing_todo_title_returns_400(self, client: AsyncClient):
        response = await client.post(
            f"{BASE_URL}/from-todo",
            json={"todo_id": "todo_123"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "todo_id and todo_title are required"

    async def test_from_todo_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_SERVICE}.create_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.post(
                f"{BASE_URL}/from-todo",
                json={"todo_id": "todo_123", "todo_title": "Task"},
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to create workflow from todo"
        mock_log.set.assert_called_once_with(user={"id": USER_ID}, workflow={"operation": "create"})
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error creating workflow from todo",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# POST /workflows/{id}/publish
# ---------------------------------------------------------------------------


class TestPublishWorkflow:
    """Tests for the publish workflow endpoint."""

    async def test_publish_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        doc = _make_workflow_doc(title="My Public Workflow", slug=None)
        with (
            patch(f"{_WF_REPO}.get_for_user", new_callable=AsyncMock, return_value=doc)
            as get_for_user,
            patch(f"{_WF_REPO}.publish", new_callable=AsyncMock, return_value=doc) as publish,
            patch(
                _GEN_SLUG,
                new_callable=AsyncMock,
                return_value="my-public-workflow-abc123",
            ) as gen,
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/publish")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Workflow published successfully"
        assert data["workflow_id"] == "wf_abc123"
        assert data["slug"] == "my-public-workflow-abc123"
        get_for_user.assert_awaited_once_with("wf_abc123", USER_ID)
        publish.assert_awaited_once_with("wf_abc123", created_by=USER_ID, slug="my-public-workflow-abc123")
        gen.assert_awaited_once_with(doc.title, exclude_id="wf_abc123")
        mock_log.set.assert_any_call(
            user={"id": USER_ID}, workflow={"operation": "publish", "id": "wf_abc123"}
        )
        mock_log.set.assert_any_call(outcome="success")
        mock_log.info.assert_called_once_with(
            f"{LogTag.WORKFLOW} Published workflow",
            workflow_id="wf_abc123",
            user_id=USER_ID,
        )
        mock_log.error.assert_not_called()

    async def test_publish_keeps_existing_slug(self, client: AsyncClient):
        """A workflow that already has a slug re-publishes with it — no regen."""
        doc = _make_workflow_doc(slug="already-set-abcdef")
        gen = AsyncMock()
        with (
            patch(f"{_WF_REPO}.get_for_user", new_callable=AsyncMock, return_value=doc),
            patch(f"{_WF_REPO}.publish", new_callable=AsyncMock, return_value=doc) as publish,
            patch(_GEN_SLUG, gen),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/publish")

        assert response.status_code == 200
        assert response.json()["slug"] == "already-set-abcdef"
        gen.assert_not_awaited()
        publish.assert_awaited_once_with(
            "wf_abc123", created_by=USER_ID, slug="already-set-abcdef"
        )

    async def test_publish_retries_on_duplicate_slug(self, client: AsyncClient):
        """A generated-slug collision retries with a fresh slug (the unique-index race)."""
        doc = _make_workflow_doc(slug=None)
        publish = AsyncMock(side_effect=[DuplicateKeyError("dup"), doc])
        with (
            patch(f"{_WF_REPO}.get_for_user", new_callable=AsyncMock, return_value=doc),
            patch(f"{_WF_REPO}.publish", publish),
            patch(_GEN_SLUG, new_callable=AsyncMock, side_effect=["slug-1", "slug-2"]),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/publish")

        assert response.status_code == 200
        assert publish.await_count == 2
        assert response.json()["slug"] == "slug-2"
        assert response.json()["workflow_id"] == "wf_abc123"

    async def test_publish_empty_generated_slug_becomes_empty_string(self, client: AsyncClient):
        """A falsy generated slug is normalized to '' before publish (slug=slug or '')."""
        doc = _make_workflow_doc(slug=None)
        with (
            patch(f"{_WF_REPO}.get_for_user", new_callable=AsyncMock, return_value=doc),
            patch(f"{_WF_REPO}.publish", new_callable=AsyncMock, return_value=doc) as publish,
            patch(_GEN_SLUG, new_callable=AsyncMock, return_value=None),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/publish")

        assert response.status_code == 200
        assert response.json()["slug"] is None
        publish.assert_awaited_once_with("wf_abc123", created_by=USER_ID, slug="")

    async def test_publish_exhausts_retries_returns_500(self, client: AsyncClient):
        """Five consecutive collisions on fresh slugs → the retry loop gives up."""
        doc = _make_workflow_doc(slug=None)
        publish = AsyncMock(side_effect=DuplicateKeyError("dup"))
        with (
            patch(f"{_WF_REPO}.get_for_user", new_callable=AsyncMock, return_value=doc),
            patch(f"{_WF_REPO}.publish", publish),
            patch(_GEN_SLUG, new_callable=AsyncMock, side_effect=["s1", "s2", "s3", "s4", "s5"]),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/publish")

        assert response.status_code == 500
        assert response.json()["detail"] == "Could not allocate a unique slug, please retry"
        assert publish.await_count == 5

    async def test_publish_existing_slug_collision_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        """A collision on an existing slug re-raises — never regenerated."""
        doc = _make_workflow_doc(slug="already-set-abcdef")
        gen = AsyncMock()
        with (
            patch(f"{_WF_REPO}.get_for_user", new_callable=AsyncMock, return_value=doc),
            patch(
                f"{_WF_REPO}.publish",
                new_callable=AsyncMock,
                side_effect=DuplicateKeyError("dup"),
            ),
            patch(_GEN_SLUG, gen),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/publish")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to publish workflow"
        gen.assert_not_awaited()
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID}, workflow={"operation": "publish", "id": "wf_abc123"}
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error publishing workflow",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="DuplicateKeyError",
            error="dup",
        )

    async def test_publish_not_found_returns_404(self, client: AsyncClient):
        with patch(f"{_WF_REPO}.get_for_user", new_callable=AsyncMock, return_value=None):
            response = await client.post(f"{BASE_URL}/wf_nonexist/publish")

        assert response.status_code == 404
        assert response.json()["detail"] == "Workflow not found or access denied"

    async def test_publish_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_REPO}.get_for_user",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/publish")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to publish workflow"
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID}, workflow={"operation": "publish", "id": "wf_abc123"}
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error publishing workflow",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# POST /workflows/{id}/unpublish
# ---------------------------------------------------------------------------


class TestUnpublishWorkflow:
    """Tests for the unpublish workflow endpoint."""

    async def test_unpublish_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        doc = _make_workflow_doc(is_public=True)
        with (
            patch(f"{_WF_REPO}.get_for_user", new_callable=AsyncMock, return_value=doc)
            as get_for_user,
            patch(f"{_WF_REPO}.unpublish", new_callable=AsyncMock, return_value=doc)
            as unpublish,
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/unpublish")

        assert response.status_code == 200
        assert response.json() == {"message": "Workflow unpublished successfully"}
        get_for_user.assert_awaited_once_with("wf_abc123", USER_ID)
        unpublish.assert_awaited_once_with("wf_abc123")
        mock_log.set.assert_any_call(user={"id": USER_ID}, workflow={"id": "wf_abc123"})
        mock_log.set.assert_any_call(outcome="success")
        mock_log.info.assert_called_once_with(
            f"{LogTag.WORKFLOW} Unpublished workflow",
            workflow_id="wf_abc123",
            user_id=USER_ID,
        )
        mock_log.error.assert_not_called()

    async def test_unpublish_not_found_returns_404(self, client: AsyncClient):
        with patch(f"{_WF_REPO}.get_for_user", new_callable=AsyncMock, return_value=None):
            response = await client.post(f"{BASE_URL}/wf_nonexist/unpublish")

        assert response.status_code == 404
        assert response.json()["detail"] == "Workflow not found or access denied"

    async def test_unpublish_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        doc = _make_workflow_doc(is_public=True)
        with (
            patch(f"{_WF_REPO}.get_for_user", new_callable=AsyncMock, return_value=doc),
            patch(
                f"{_WF_REPO}.unpublish",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB error"),
            ),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/unpublish")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to unpublish workflow"
        mock_log.set.assert_called_once_with(user={"id": USER_ID}, workflow={"id": "wf_abc123"})
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error unpublishing workflow",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# GET /workflows/explore
# ---------------------------------------------------------------------------


class TestExploreWorkflows:
    """Tests for the explore workflows endpoint."""

    async def test_explore_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        mock_result = PublicWorkflowsResponse(workflows=[], total=0)
        with patch(
            f"{_WF_SERVICE}.get_explore_workflows",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_explore:
            response = await client.get(f"{BASE_URL}/explore")

        assert response.status_code == 200
        assert response.json() == {"workflows": [], "total": 0}
        mock_explore.assert_awaited_once_with(limit=25, offset=0)
        mock_log.set.assert_called_once_with(workflow={"operation": "explore"})
        mock_log.set_ns.assert_called_once_with("workflow", result_count=0)
        mock_log.error.assert_not_called()

    async def test_explore_passes_pagination(self, client: AsyncClient):
        mock_result = PublicWorkflowsResponse(workflows=[], total=0)
        with patch(
            f"{_WF_SERVICE}.get_explore_workflows",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_explore:
            response = await client.get(f"{BASE_URL}/explore", params={"limit": 5, "offset": 10})

        assert response.status_code == 200
        mock_explore.assert_awaited_once_with(limit=5, offset=10)

    async def test_explore_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_SERVICE}.get_explore_workflows",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(f"{BASE_URL}/explore")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to fetch explore workflows"
        mock_log.set.assert_called_once_with(workflow={"operation": "explore"})
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error fetching explore workflows",
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# GET /workflows/community
# ---------------------------------------------------------------------------


class TestCommunityWorkflows:
    """Tests for the community workflows endpoint."""

    async def test_community_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        mock_result = PublicWorkflowsResponse(workflows=[], total=0)
        with patch(
            f"{_WF_SERVICE}.get_community_workflows",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_community:
            response = await client.get(f"{BASE_URL}/community")

        assert response.status_code == 200
        assert response.json() == {"workflows": [], "total": 0}
        mock_community.assert_awaited_once_with(limit=20, offset=0, user_id=None)
        mock_log.set.assert_called_once_with(workflow={"operation": "list_public"})
        mock_log.set_ns.assert_called_once_with("workflow", result_count=0)
        mock_log.error.assert_not_called()

    async def test_community_passes_pagination(self, client: AsyncClient):
        mock_result = PublicWorkflowsResponse(workflows=[], total=0)
        with patch(
            f"{_WF_SERVICE}.get_community_workflows",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_community:
            response = await client.get(
                f"{BASE_URL}/community", params={"limit": 5, "offset": 10}
            )

        assert response.status_code == 200
        mock_community.assert_awaited_once_with(limit=5, offset=10, user_id=None)

    async def test_community_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_SERVICE}.get_community_workflows",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(f"{BASE_URL}/community")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to fetch public workflows"
        mock_log.set.assert_called_once_with(workflow={"operation": "list_public"})
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error fetching public workflows",
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# GET /workflows/public/{ref}
# ---------------------------------------------------------------------------


class TestGetPublicWorkflow:
    """Tests for the get public workflow endpoint."""

    async def test_get_public_workflow_by_id_returns_200(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        # slug present → ensure_public_workflow_slug short-circuits (no repo write).
        row = PublicWorkflowRow(
            **_make_workflow(
                title="Public Workflow", is_public=True, slug="public-workflow"
            ).model_dump(),
            creator_info=[WorkflowCreatorInfo(name="Test User")],
        )
        with patch(
            f"{_WF_REPO}.get_public_with_creator",
            new_callable=AsyncMock,
            return_value=row,
        ) as mock_lookup:
            response = await client.get(f"{BASE_URL}/public/wf_abc123")

        assert response.status_code == 200
        assert response.json()["message"] == "Workflow retrieved successfully"
        data = response.json()["workflow"]
        assert data["id"] == "wf_abc123"
        assert data["creator"]["name"] == "Test User"
        # the join scaffolding must not leak into the response
        assert "creator_info" not in data
        mock_lookup.assert_awaited_once_with("wf_abc123", by_slug=False)
        mock_log.set.assert_any_call(
            workflow={"operation": "get_public"},
            public_workflow={"ref": "wf_abc123", "lookup_mode": "id"},
        )
        mock_log.set_ns.assert_not_called()
        mock_log.error.assert_not_called()

    async def test_get_public_workflow_logs_creator_on_success(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        """The success wide event carries the resolved creator and step count."""
        row = PublicWorkflowRow(
            **_make_workflow(
                title="Public Workflow",
                is_public=True,
                slug="public-workflow",
                created_by=USER_ID,
            ).model_dump(),
            creator_info=[WorkflowCreatorInfo(name="Test User")],
        )
        with patch(
            f"{_WF_REPO}.get_public_with_creator",
            new_callable=AsyncMock,
            return_value=row,
        ):
            response = await client.get(f"{BASE_URL}/public/public-workflow")

        assert response.status_code == 200
        mock_log.set.assert_any_call(
            public_workflow={
                "id": "wf_abc123",
                "slug": "public-workflow",
                "creator_id": USER_ID,
                "creator_name": "Test User",
                "step_count": 1,
            }
        )
        mock_log.error.assert_not_called()

    async def test_get_public_workflow_by_slug_returns_200(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        row = PublicWorkflowRow(
            **_make_workflow(
                title="Public Workflow", is_public=True, slug="public-workflow"
            ).model_dump(),
            creator_info=[WorkflowCreatorInfo(name="Test User")],
        )
        with patch(
            f"{_WF_REPO}.get_public_with_creator",
            new_callable=AsyncMock,
            return_value=row,
        ) as mock_lookup:
            response = await client.get(f"{BASE_URL}/public/public-workflow")

        assert response.status_code == 200
        assert response.json()["message"] == "Workflow retrieved successfully"
        assert response.json()["workflow"]["slug"] == "public-workflow"
        mock_lookup.assert_awaited_once_with("public-workflow", by_slug=True)
        mock_log.set.assert_any_call(
            workflow={"operation": "get_public"},
            public_workflow={"ref": "public-workflow", "lookup_mode": "slug"},
        )

    async def test_get_public_workflow_empty_steps_logs_zero(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        """A public workflow with no steps logs step_count 0 — the else branch
        of the success wide event, not the length of an empty list."""
        row = PublicWorkflowRow(
            **_make_workflow(
                title="Public Workflow", is_public=True, slug="public-workflow", steps=[]
            ).model_dump(),
            creator_info=[WorkflowCreatorInfo(name="Test User")],
        )
        with patch(
            f"{_WF_REPO}.get_public_with_creator",
            new_callable=AsyncMock,
            return_value=row,
        ):
            response = await client.get(f"{BASE_URL}/public/public-workflow")

        assert response.status_code == 200
        mock_log.set.assert_any_call(
            public_workflow={
                "id": "wf_abc123",
                "slug": "public-workflow",
                "creator_id": None,
                "creator_name": "Test User",
                "step_count": 0,
            }
        )
        mock_log.error.assert_not_called()

    async def test_get_public_workflow_not_found_returns_404(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_REPO}.get_public_with_creator",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get(f"{BASE_URL}/public/nonexistent-slug")

        assert response.status_code == 404
        assert response.json()["detail"] == "Public workflow not found"
        mock_log.set.assert_called_once_with(
            workflow={"operation": "get_public"},
            public_workflow={"ref": "nonexistent-slug", "lookup_mode": "slug"},
        )
        mock_log.info.assert_called_once_with(
            f"{LogTag.WORKFLOW} get_public_workflow: no public workflow found",
            workflow_ref="nonexistent-slug",
        )
        mock_log.error.assert_not_called()

    async def test_get_public_workflow_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_REPO}.get_public_with_creator",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(f"{BASE_URL}/public/wf_abc123")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to get workflow"
        mock_log.set.assert_called_once_with(
            workflow={"operation": "get_public"},
            public_workflow={"ref": "wf_abc123", "lookup_mode": "id"},
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error getting public workflow",
            workflow_ref="wf_abc123",
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# POST /workflows/generate-prompt
# ---------------------------------------------------------------------------


class TestGeneratePrompt:
    """Tests for the generate workflow prompt endpoint."""

    async def test_generate_prompt_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        mock_result = {
            "prompt": "Generated instructions for the workflow",
            "suggested_trigger": None,
        }
        with patch(
            f"{_WF_GEN_SERVICE}.generate_workflow_prompt",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_generate:
            response = await client.post(
                f"{BASE_URL}/generate-prompt",
                json={"title": "My Workflow"},
            )

        assert response.status_code == 200
        assert response.json() == mock_result
        mock_generate.assert_awaited_once_with(
            title="My Workflow",
            description=None,
            trigger_config=None,
            existing_prompt=None,
            integration_ids=None,
            user_id=USER_ID,
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID}, workflow={"operation": "generate_prompt"}
        )
        mock_log.set.assert_any_call(outcome="success")
        mock_log.error.assert_not_called()

    async def test_generate_prompt_with_existing_prompt(self, client: AsyncClient):
        mock_result = {
            "prompt": "Improved instructions",
            "suggested_trigger": {"type": "schedule", "cron_expression": "0 9 * * *"},
        }
        with patch(
            f"{_WF_GEN_SERVICE}.generate_workflow_prompt",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_generate:
            response = await client.post(
                f"{BASE_URL}/generate-prompt",
                json={
                    "title": "Daily Report",
                    "description": "Send me a report.",
                    "existing_prompt": "Send me a report.",
                    "trigger_config": {"type": "schedule", "cron_expression": "0 9 * * *"},
                    "integration_ids": ["gmail"],
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["prompt"] == "Improved instructions"
        assert data["suggested_trigger"] == {
            "type": "schedule",
            "cron_expression": "0 9 * * *",
            "trigger_name": None,
        }
        mock_generate.assert_awaited_once_with(
            title="Daily Report",
            description="Send me a report.",
            trigger_config=PromptTriggerHint(
                type="schedule", cron_expression="0 9 * * *"
            ),
            existing_prompt="Send me a report.",
            integration_ids=["gmail"],
            user_id=USER_ID,
        )

    async def test_generate_prompt_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_GEN_SERVICE}.generate_workflow_prompt",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM error"),
        ):
            response = await client.post(
                f"{BASE_URL}/generate-prompt",
                json={"title": "Workflow"},
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to generate workflow prompt"
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID}, workflow={"operation": "generate_prompt"}
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error generating workflow prompt",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="LLM error",
        )


# ---------------------------------------------------------------------------
# GET /workflows/{id}
# ---------------------------------------------------------------------------


class TestGetWorkflow:
    """Tests for the get workflow by ID endpoint."""

    async def test_get_workflow_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        mock_wf = _make_workflow()
        with patch(
            f"{_WF_SERVICE}.get_workflow",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ) as mock_get:
            response = await client.get(f"{BASE_URL}/wf_abc123")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Workflow retrieved successfully"
        _assert_workflow_body(data)
        mock_get.assert_awaited_once_with("wf_abc123", USER_ID)
        mock_log.set.assert_any_call(
            user={"id": USER_ID}, workflow={"operation": "get", "id": "wf_abc123"}
        )
        mock_log.set.assert_any_call(
            workflow={"title": "My Workflow", "steps_count": 1}, outcome="success"
        )
        mock_log.error.assert_not_called()

    async def test_get_workflow_empty_steps_logs_none(self, client: AsyncClient, mock_log: MagicMock):
        """A falsy ``steps`` list short-circuits the success wide event's
        steps_count to None (the ``and`` guard, not the length)."""
        mock_wf = _make_workflow(steps=[])
        with patch(
            f"{_WF_SERVICE}.get_workflow",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ) as mock_get:
            response = await client.get(f"{BASE_URL}/wf_abc123")

        assert response.status_code == 200
        assert response.json()["workflow"]["steps"] == []
        mock_get.assert_awaited_once_with("wf_abc123", USER_ID)
        mock_log.set.assert_any_call(
            workflow={"title": "My Workflow", "steps_count": None}, outcome="success"
        )

    async def test_get_workflow_not_found_returns_404(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.get_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get(f"{BASE_URL}/wf_nonexist")

        assert response.status_code == 404
        assert response.json()["detail"] == "Workflow wf_nonexist not found"

    async def test_get_workflow_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_SERVICE}.get_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(f"{BASE_URL}/wf_abc123")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to get workflow"
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID}, workflow={"operation": "get", "id": "wf_abc123"}
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error getting workflow",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# PUT /workflows/{id}
# ---------------------------------------------------------------------------


class TestUpdateWorkflow:
    """Tests for the update workflow endpoint."""

    async def test_update_workflow_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        mock_wf = _make_workflow(title="Updated Title")
        with patch(
            f"{_WF_SERVICE}.update_workflow",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ) as mock_update:
            response = await client.put(
                f"{BASE_URL}/wf_abc123",
                json={"title": "Updated Title"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Workflow updated successfully"
        assert data["workflow"]["title"] == "Updated Title"
        mock_update.assert_awaited_once()
        assert mock_update.await_args.args[0] == "wf_abc123"
        assert mock_update.await_args.args[1] == UpdateWorkflowRequest(title="Updated Title")
        assert mock_update.await_args.args[2] == USER_ID
        assert mock_update.await_args.kwargs == {"user_timezone": USER_TIMEZONE}
        mock_log.set.assert_any_call(
            user={"id": USER_ID}, workflow={"operation": "update", "id": "wf_abc123"}
        )
        mock_log.set.assert_any_call(outcome="success")
        mock_log.error.assert_not_called()

    async def test_update_workflow_not_found_returns_404(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.update_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.put(
                f"{BASE_URL}/wf_nonexist",
                json={"title": "New Title"},
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Workflow wf_nonexist not found"

    async def test_update_workflow_value_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        """A ValueError from the service lands in the bare ``except Exception`` —
        the endpoint has no ValueError → 400 branch, so the caller sees a 500."""
        with patch(
            f"{_WF_SERVICE}.update_workflow",
            new_callable=AsyncMock,
            side_effect=ValueError("Invalid trigger config"),
        ):
            response = await client.put(
                f"{BASE_URL}/wf_abc123",
                json={"title": "New Title"},
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to update workflow"
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID}, workflow={"operation": "update", "id": "wf_abc123"}
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error updating workflow",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="ValueError",
            error="Invalid trigger config",
        )

    async def test_update_workflow_trigger_registration_error_returns_400(
        self, client: AsyncClient
    ):
        with patch(
            f"{_WF_SERVICE}.update_workflow",
            new_callable=AsyncMock,
            side_effect=TriggerRegistrationError("Trigger failed", "gmail_new_message"),
        ):
            response = await client.put(
                f"{BASE_URL}/wf_abc123",
                json={"title": "New Title"},
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "Trigger failed"

    async def test_update_workflow_empty_title_returns_422(self, client: AsyncClient):
        response = await client.put(
            f"{BASE_URL}/wf_abc123",
            json={"title": ""},
        )
        assert response.status_code == 422

    async def test_update_workflow_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_SERVICE}.update_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.put(
                f"{BASE_URL}/wf_abc123",
                json={"title": "Updated"},
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to update workflow"
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID}, workflow={"operation": "update", "id": "wf_abc123"}
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error updating workflow",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# POST /workflows/{id}/reset-to-default
# ---------------------------------------------------------------------------


class TestResetWorkflowToDefault:
    """Tests for the reset workflow to default endpoint."""

    async def test_reset_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        with patch(
            _RESET_DEFAULT,
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_reset:
            response = await client.post(f"{BASE_URL}/wf_abc123/reset-to-default")

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "message": "Workflow reset to default.",
        }
        mock_reset.assert_awaited_once_with(workflow_id="wf_abc123", user_id=USER_ID)
        mock_log.set.assert_any_call(user={"id": USER_ID}, workflow={"id": "wf_abc123"})
        mock_log.set.assert_any_call(outcome="success")
        mock_log.error.assert_not_called()

    async def test_reset_not_system_workflow_returns_400(self, client: AsyncClient):
        with patch(
            _RESET_DEFAULT,
            new_callable=AsyncMock,
            return_value=False,
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/reset-to-default")

        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "Workflow not found or is not a resettable system workflow."
        )

    async def test_reset_service_error_returns_500(self, client: AsyncClient, mock_log: MagicMock):
        with patch(
            _RESET_DEFAULT,
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/reset-to-default")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to reset workflow"
        mock_log.set.assert_called_once_with(user={"id": USER_ID}, workflow={"id": "wf_abc123"})
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error resetting workflow",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# DELETE /workflows/{id}
# ---------------------------------------------------------------------------


class TestDeleteWorkflow:
    """Tests for the delete workflow endpoint."""

    async def test_delete_workflow_returns_200(self, client: AsyncClient, mock_log: MagicMock):
        with patch(
            f"{_WF_SERVICE}.delete_workflow",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_delete:
            response = await client.delete(f"{BASE_URL}/wf_abc123")

        assert response.status_code == 200
        assert response.json() == {"message": "Workflow deleted successfully"}
        mock_delete.assert_awaited_once_with("wf_abc123", USER_ID)
        mock_log.set.assert_any_call(
            user={"id": USER_ID}, workflow={"operation": "delete", "id": "wf_abc123"}
        )
        mock_log.set.assert_any_call(outcome="success")
        mock_log.error.assert_not_called()

    async def test_delete_workflow_not_found_returns_404(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.delete_workflow",
            new_callable=AsyncMock,
            return_value=False,
        ):
            response = await client.delete(f"{BASE_URL}/wf_nonexist")

        assert response.status_code == 404
        assert response.json()["detail"] == "Workflow wf_nonexist not found"

    async def test_delete_workflow_service_error_returns_500(
        self, client: AsyncClient, mock_log: MagicMock
    ):
        with patch(
            f"{_WF_SERVICE}.delete_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.delete(f"{BASE_URL}/wf_abc123")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to delete workflow"
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID}, workflow={"operation": "delete", "id": "wf_abc123"}
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Error deleting workflow",
            workflow_id="wf_abc123",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="DB error",
        )
