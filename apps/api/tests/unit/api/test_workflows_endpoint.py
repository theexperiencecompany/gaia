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

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.workflow_models import (
    PublicWorkflowsResponse,
    Workflow,
    WorkflowExecutionResponse,
    WorkflowStatusResponse,
)
from app.models.workflow_execution_models import WorkflowExecutionsResponse

BASE_URL = "/api/v1/workflows"

# Patch targets
_WF_SERVICE = "app.api.v1.endpoints.workflows.WorkflowService"
_WF_GEN_SERVICE = "app.api.v1.endpoints.workflows.WorkflowGenerationService"
_WF_COLLECTION = "app.api.v1.endpoints.workflows.workflows_collection"
_GET_EXECUTIONS = "app.api.v1.endpoints.workflows.get_executions"
_GEN_SLUG = "app.api.v1.endpoints.workflows.generate_unique_workflow_slug"
_RESET_DEFAULT = "app.api.v1.endpoints.workflows.reset_system_workflow_to_default"


def _make_workflow(**overrides) -> Workflow:
    """Build a real Workflow Pydantic model instance for service mock returns."""
    base: dict = {
        "id": "wf_abc123",
        "user_id": "507f1f77bcf86cd799439011",
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
        "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return Workflow(**base)


def _create_workflow_payload(**overrides) -> dict:
    base: dict = {
        "title": "My Workflow",
        "prompt": "Do the thing for me",
        "trigger_config": {"type": "manual", "enabled": True},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# POST /workflows
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateWorkflow:
    """Tests for the create workflow endpoint."""

    async def test_create_workflow_returns_200(self, client: AsyncClient):
        mock_wf = _make_workflow()
        with patch(
            f"{_WF_SERVICE}.create_workflow",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ):
            response = await client.post(BASE_URL, json=_create_workflow_payload())

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Workflow created successfully"

    async def test_create_workflow_missing_title_returns_422(self, client: AsyncClient):
        response = await client.post(
            BASE_URL,
            json={
                "prompt": "Do something",
                "trigger_config": {"type": "manual", "enabled": True},
            },
        )
        assert response.status_code == 422

    async def test_create_workflow_missing_prompt_returns_422(
        self, client: AsyncClient
    ):
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

    async def test_create_workflow_value_error_returns_400(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.create_workflow",
            new_callable=AsyncMock,
            side_effect=ValueError("Invalid trigger config"),
        ):
            response = await client.post(BASE_URL, json=_create_workflow_payload())

        assert response.status_code == 400

    async def test_create_workflow_service_error_returns_500(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.create_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB failure"),
        ):
            response = await client.post(BASE_URL, json=_create_workflow_payload())

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /workflows
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListWorkflows:
    """Tests for the list workflows endpoint."""

    async def test_list_workflows_returns_200(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.list_workflows",
            new_callable=AsyncMock,
            return_value=[_make_workflow()],
        ):
            response = await client.get(BASE_URL)

        assert response.status_code == 200

    async def test_list_workflows_empty(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.list_workflows",
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = await client.get(BASE_URL)

        assert response.status_code == 200

    async def test_list_workflows_service_error_returns_500(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.list_workflows",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(BASE_URL)

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /workflows/{id}/execute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteWorkflow:
    """Tests for the execute workflow endpoint."""

    async def test_execute_workflow_returns_200(self, client: AsyncClient):
        mock_result = WorkflowExecutionResponse(
            execution_id="exec_123",
            message="Workflow execution started",
        )
        with patch(
            f"{_WF_SERVICE}.execute_workflow",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/execute", json={})

        assert response.status_code == 200

    async def test_execute_workflow_with_context(self, client: AsyncClient):
        mock_result = WorkflowExecutionResponse(
            execution_id="exec_123",
            message="OK",
        )
        with patch(
            f"{_WF_SERVICE}.execute_workflow",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = await client.post(
                f"{BASE_URL}/wf_abc123/execute",
                json={"context": {"key": "value"}},
            )

        assert response.status_code == 200

    async def test_execute_workflow_value_error_returns_400(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.execute_workflow",
            new_callable=AsyncMock,
            side_effect=ValueError("Workflow is deactivated"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/execute", json={})

        assert response.status_code == 400

    async def test_execute_workflow_service_error_returns_500(
        self, client: AsyncClient
    ):
        with patch(
            f"{_WF_SERVICE}.execute_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Execution engine error"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/execute", json={})

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /workflows/{id}/executions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetWorkflowExecutions:
    """Tests for the get workflow executions endpoint."""

    async def test_get_executions_returns_200(self, client: AsyncClient):
        mock_result = WorkflowExecutionsResponse(
            executions=[],
            total=0,
            has_more=False,
        )
        with patch(
            _GET_EXECUTIONS,
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = await client.get(f"{BASE_URL}/wf_abc123/executions")

        assert response.status_code == 200

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
            user_id="507f1f77bcf86cd799439011",
            limit=5,
            offset=10,
        )

    async def test_get_executions_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _GET_EXECUTIONS,
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(f"{BASE_URL}/wf_abc123/executions")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /workflows/{id}/status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetWorkflowStatus:
    """Tests for the get workflow status endpoint."""

    async def test_get_status_returns_200(self, client: AsyncClient):
        mock_status = WorkflowStatusResponse(
            workflow_id="wf_abc123",
            activated=True,
            current_step_index=0,
            total_steps=3,
            progress_percentage=0.0,
            last_updated=datetime(2025, 1, 1, tzinfo=timezone.utc),
            error_message=None,
            logs=[],
        )
        with patch(
            f"{_WF_SERVICE}.get_workflow_status",
            new_callable=AsyncMock,
            return_value=mock_status,
        ):
            response = await client.get(f"{BASE_URL}/wf_abc123/status")

        assert response.status_code == 200

    async def test_get_status_not_found_returns_404(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.get_workflow_status",
            new_callable=AsyncMock,
            side_effect=ValueError("Workflow not found"),
        ):
            response = await client.get(f"{BASE_URL}/wf_nonexist/status")

        assert response.status_code == 404

    async def test_get_status_service_error_returns_500(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.get_workflow_status",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(f"{BASE_URL}/wf_abc123/status")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /workflows/{id}/activate
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestActivateWorkflow:
    """Tests for the activate workflow endpoint."""

    async def test_activate_returns_200(self, client: AsyncClient):
        mock_wf = _make_workflow(activated=True)
        with patch(
            f"{_WF_SERVICE}.activate_workflow",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/activate")

        assert response.status_code == 200
        assert response.json()["message"] == "Workflow activated successfully"

    async def test_activate_not_found_returns_404(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.activate_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.post(f"{BASE_URL}/wf_nonexist/activate")

        assert response.status_code == 404

    async def test_activate_service_error_returns_500(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.activate_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Trigger error"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/activate")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /workflows/{id}/deactivate
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeactivateWorkflow:
    """Tests for the deactivate workflow endpoint."""

    async def test_deactivate_returns_200(self, client: AsyncClient):
        mock_wf = _make_workflow(activated=False)
        with patch(
            f"{_WF_SERVICE}.deactivate_workflow",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/deactivate")

        assert response.status_code == 200
        assert response.json()["message"] == "Workflow deactivated successfully"

    async def test_deactivate_not_found_returns_404(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.deactivate_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.post(f"{BASE_URL}/wf_nonexist/deactivate")

        assert response.status_code == 404

    async def test_deactivate_service_error_returns_500(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.deactivate_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/deactivate")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /workflows/{id}/regenerate-steps
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegenerateSteps:
    """Tests for the regenerate workflow steps endpoint."""

    async def test_regenerate_steps_returns_200(self, client: AsyncClient):
        mock_wf = _make_workflow()
        with patch(
            f"{_WF_SERVICE}.regenerate_workflow_steps",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ):
            response = await client.post(
                f"{BASE_URL}/wf_abc123/regenerate-steps",
                json={"instruction": "Make it better"},
            )

        assert response.status_code == 200

    async def test_regenerate_steps_not_found_returns_500(self, client: AsyncClient):
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

    async def test_regenerate_steps_missing_instruction_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(
            f"{BASE_URL}/wf_abc123/regenerate-steps",
            json={},
        )
        assert response.status_code == 422

    async def test_regenerate_steps_service_error_returns_500(
        self, client: AsyncClient
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


# ---------------------------------------------------------------------------
# POST /workflows/from-todo
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateWorkflowFromTodo:
    """Tests for the create workflow from todo endpoint."""

    async def test_from_todo_returns_200(self, client: AsyncClient):
        mock_wf = _make_workflow(title="Todo: Buy groceries")
        with patch(
            f"{_WF_SERVICE}.create_workflow",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ):
            response = await client.post(
                f"{BASE_URL}/from-todo",
                json={
                    "todo_id": "todo_123",
                    "todo_title": "Buy groceries",
                    "todo_description": "Get milk, eggs, and bread",
                },
            )

        assert response.status_code == 200
        assert "Workflow created from todo" in response.json()["message"]

    async def test_from_todo_missing_todo_id_returns_400(self, client: AsyncClient):
        response = await client.post(
            f"{BASE_URL}/from-todo",
            json={"todo_title": "Buy groceries"},
        )
        assert response.status_code == 400

    async def test_from_todo_missing_todo_title_returns_400(self, client: AsyncClient):
        response = await client.post(
            f"{BASE_URL}/from-todo",
            json={"todo_id": "todo_123"},
        )
        assert response.status_code == 400

    async def test_from_todo_service_error_returns_500(self, client: AsyncClient):
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


# ---------------------------------------------------------------------------
# POST /workflows/{id}/publish
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPublishWorkflow:
    """Tests for the publish workflow endpoint."""

    async def test_publish_returns_200(self, client: AsyncClient):
        mock_doc = {
            "_id": "wf_abc123",
            "user_id": "507f1f77bcf86cd799439011",
            "title": "My Public Workflow",
            "slug": None,
        }
        with (
            patch(
                f"{_WF_COLLECTION}.find_one",
                new_callable=AsyncMock,
                return_value=mock_doc,
            ),
            patch(
                f"{_WF_COLLECTION}.update_one",
                new_callable=AsyncMock,
            ),
            patch(
                _GEN_SLUG,
                new_callable=AsyncMock,
                return_value="my-public-workflow-abc123",
            ),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/publish")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Workflow published successfully"

    async def test_publish_not_found_returns_404(self, client: AsyncClient):
        with patch(
            f"{_WF_COLLECTION}.find_one",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.post(f"{BASE_URL}/wf_nonexist/publish")

        assert response.status_code == 404

    async def test_publish_service_error_returns_500(self, client: AsyncClient):
        with patch(
            f"{_WF_COLLECTION}.find_one",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/publish")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /workflows/{id}/unpublish
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnpublishWorkflow:
    """Tests for the unpublish workflow endpoint."""

    async def test_unpublish_returns_200(self, client: AsyncClient):
        mock_doc = {
            "_id": "wf_abc123",
            "user_id": "507f1f77bcf86cd799439011",
            "is_public": True,
        }
        with (
            patch(
                f"{_WF_COLLECTION}.find_one",
                new_callable=AsyncMock,
                return_value=mock_doc,
            ),
            patch(
                f"{_WF_COLLECTION}.update_one",
                new_callable=AsyncMock,
            ),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/unpublish")

        assert response.status_code == 200
        assert response.json()["message"] == "Workflow unpublished successfully"

    async def test_unpublish_not_found_returns_404(self, client: AsyncClient):
        with patch(
            f"{_WF_COLLECTION}.find_one",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.post(f"{BASE_URL}/wf_nonexist/unpublish")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /workflows/explore
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExploreWorkflows:
    """Tests for the explore workflows endpoint."""

    async def test_explore_returns_200(self, client: AsyncClient):
        mock_result = PublicWorkflowsResponse(workflows=[], total=0)
        with patch(
            f"{_WF_SERVICE}.get_explore_workflows",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = await client.get(f"{BASE_URL}/explore")

        assert response.status_code == 200

    async def test_explore_service_error_returns_500(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.get_explore_workflows",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(f"{BASE_URL}/explore")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /workflows/community
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCommunityWorkflows:
    """Tests for the community workflows endpoint."""

    async def test_community_returns_200(self, client: AsyncClient):
        mock_result = PublicWorkflowsResponse(workflows=[], total=0)
        with patch(
            f"{_WF_SERVICE}.get_community_workflows",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = await client.get(f"{BASE_URL}/community")

        assert response.status_code == 200

    async def test_community_service_error_returns_500(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.get_community_workflows",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(f"{BASE_URL}/community")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /workflows/public/{ref}
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPublicWorkflow:
    """Tests for the get public workflow endpoint."""

    async def test_get_public_workflow_by_id_returns_200(self, client: AsyncClient):
        mock_doc = {
            "_id": "wf_abc123",
            "user_id": "507f1f77bcf86cd799439011",
            "title": "Public Workflow",
            "description": "A shared workflow",
            "prompt": "Do things",
            "steps": [],
            "trigger_config": {"type": "manual", "enabled": True},
            "activated": True,
            "is_public": True,
        }
        with (
            patch(
                f"{_WF_COLLECTION}.find_one",
                new_callable=AsyncMock,
                return_value=mock_doc,
            ),
            patch(
                "app.api.v1.endpoints.workflows.transform_workflow_document",
                return_value=mock_doc,
            ),
        ):
            response = await client.get(f"{BASE_URL}/public/wf_abc123")

        assert response.status_code == 200

    async def test_get_public_workflow_not_found_returns_404(self, client: AsyncClient):
        with (
            patch(
                f"{_WF_COLLECTION}.find_one",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.v1.endpoints.workflows.parse_workflow_slug",
                return_value=None,
            ),
        ):
            response = await client.get(f"{BASE_URL}/public/nonexistent-slug")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /workflows/generate-prompt
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGeneratePrompt:
    """Tests for the generate workflow prompt endpoint."""

    async def test_generate_prompt_returns_200(self, client: AsyncClient):
        mock_result = {
            "prompt": "Generated instructions for the workflow",
            "suggested_trigger": None,
        }
        with patch(
            f"{_WF_GEN_SERVICE}.generate_workflow_prompt",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = await client.post(
                f"{BASE_URL}/generate-prompt",
                json={"title": "My Workflow"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "prompt" in data

    async def test_generate_prompt_with_existing_prompt(self, client: AsyncClient):
        mock_result = {
            "prompt": "Improved instructions",
            "suggested_trigger": {"type": "schedule", "cron_expression": "0 9 * * *"},
        }
        with patch(
            f"{_WF_GEN_SERVICE}.generate_workflow_prompt",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = await client.post(
                f"{BASE_URL}/generate-prompt",
                json={
                    "title": "Daily Report",
                    "existing_prompt": "Send me a report.",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["suggested_trigger"]["type"] == "schedule"

    async def test_generate_prompt_service_error_returns_500(self, client: AsyncClient):
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


# ---------------------------------------------------------------------------
# GET /workflows/{id}
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetWorkflow:
    """Tests for the get workflow by ID endpoint."""

    async def test_get_workflow_returns_200(self, client: AsyncClient):
        mock_wf = _make_workflow()
        with patch(
            f"{_WF_SERVICE}.get_workflow",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ):
            response = await client.get(f"{BASE_URL}/wf_abc123")

        assert response.status_code == 200
        assert response.json()["message"] == "Workflow retrieved successfully"

    async def test_get_workflow_not_found_returns_404(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.get_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get(f"{BASE_URL}/wf_nonexist")

        assert response.status_code == 404

    async def test_get_workflow_service_error_returns_500(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.get_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(f"{BASE_URL}/wf_abc123")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# PUT /workflows/{id}
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateWorkflow:
    """Tests for the update workflow endpoint."""

    async def test_update_workflow_returns_200(self, client: AsyncClient):
        mock_wf = _make_workflow(title="Updated Title")
        with patch(
            f"{_WF_SERVICE}.update_workflow",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ):
            response = await client.put(
                f"{BASE_URL}/wf_abc123",
                json={"title": "Updated Title"},
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Workflow updated successfully"

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

    async def test_update_workflow_empty_title_returns_422(self, client: AsyncClient):
        response = await client.put(
            f"{BASE_URL}/wf_abc123",
            json={"title": ""},
        )
        assert response.status_code == 422

    async def test_update_workflow_service_error_returns_500(self, client: AsyncClient):
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


# ---------------------------------------------------------------------------
# POST /workflows/{id}/reset-to-default
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResetWorkflowToDefault:
    """Tests for the reset workflow to default endpoint."""

    async def test_reset_returns_200(self, client: AsyncClient):
        with patch(
            _RESET_DEFAULT,
            new_callable=AsyncMock,
            return_value=True,
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/reset-to-default")

        assert response.status_code == 200
        assert response.json()["success"] is True

    async def test_reset_not_system_workflow_returns_400(self, client: AsyncClient):
        with patch(
            _RESET_DEFAULT,
            new_callable=AsyncMock,
            return_value=False,
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/reset-to-default")

        assert response.status_code == 400

    async def test_reset_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _RESET_DEFAULT,
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/reset-to-default")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# DELETE /workflows/{id}
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteWorkflow:
    """Tests for the delete workflow endpoint."""

    async def test_delete_workflow_returns_200(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.delete_workflow",
            new_callable=AsyncMock,
            return_value=True,
        ):
            response = await client.delete(f"{BASE_URL}/wf_abc123")

        assert response.status_code == 200
        assert response.json()["message"] == "Workflow deleted successfully"

    async def test_delete_workflow_not_found_returns_404(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.delete_workflow",
            new_callable=AsyncMock,
            return_value=False,
        ):
            response = await client.delete(f"{BASE_URL}/wf_nonexist")

        assert response.status_code == 404

    async def test_delete_workflow_service_error_returns_500(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.delete_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.delete(f"{BASE_URL}/wf_abc123")

        assert response.status_code == 500
