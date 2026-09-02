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

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from pymongo.errors import DuplicateKeyError
import pytest

from app.models.payment_models import PlanType
from app.models.workflow_execution_models import WorkflowExecutionsResponse
from app.models.workflow_models import (
    PublicWorkflowRow,
    PublicWorkflowsResponse,
    Workflow,
    WorkflowCreatorInfo,
    WorkflowDocument,
    WorkflowExecutionResponse,
    WorkflowStatusResponse,
)
from app.services.analytics_service import AnalyticsEvents
from shared.py.wide_events import WorkflowContext

BASE_URL = "/api/v1/workflows"

# Patch targets
_WF_SERVICE = "app.api.v1.endpoints.workflows.WorkflowService"
_WF_GEN_SERVICE = "app.api.v1.endpoints.workflows.WorkflowGenerationService"
_WF_REPO = "app.api.v1.endpoints.workflows.workflow_repository"
_GET_EXECUTIONS = "app.api.v1.endpoints.workflows.get_executions"
_GEN_SLUG = "app.api.v1.endpoints.workflows.generate_unique_workflow_slug"
_RESET_DEFAULT = "app.api.v1.endpoints.workflows.reset_system_workflow_to_default"

# The `client` fixture's user is FREE by default (root conftest patches
# get_user_subscription_status to FREE) — GAIA is paid-only, so create/
# execute/activate/from-todo now 402 before the handler runs. Classes that
# exercise handler behavior (not the paywall itself) opt into PRO here, the
# same seam `payment_service.get_cached_plan_type` reads through.
_GET_SUBSCRIPTION_STATUS = (
    "app.services.payments.payment_service.payment_service.get_user_subscription_status"
)


def _subscription_mock(plan_type: PlanType = PlanType.PRO) -> MagicMock:
    sub = MagicMock()
    sub.plan_type = plan_type
    return sub


@pytest.fixture(autouse=True)
def _no_real_redis_plan_cache():
    """``get_cached_plan_type`` reads ``subscription_plan:<user_id>`` from Redis
    before consulting ``get_user_subscription_status``, and every test in this
    file shares FAKE_USER's id. The test env's REDIS_URL points at a real
    local Redis (``tests/conftest.py``) — without this, a plan tier cached by
    one test leaks into a later test that patches a different tier, which is
    the "stray local Redis singleton" flake noted in ``apps/api/CLAUDE.md``.
    """
    with (
        patch(
            "app.services.payments.payment_service.redis_cache.get",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.payments.payment_service.redis_cache.set",
            new=AsyncMock(),
        ),
    ):
        yield


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


# ---------------------------------------------------------------------------
# Paid-only gate — GAIA is paid-only, so create/execute/activate/from-todo
# must 402 for a FREE-plan user before the service layer ever runs, and let a
# PRO-plan user through untouched. The `client` fixture is FREE by default
# (root conftest), so these need no extra patching for the free-user half.
# ---------------------------------------------------------------------------


class TestWorkflowPaidOnlyGate:
    """402 contract on the workflow endpoints that create/run work."""

    async def test_create_workflow_free_user_gets_402(self, client: AsyncClient):
        with patch(f"{_WF_SERVICE}.create_workflow", new_callable=AsyncMock) as mock_create:
            response = await client.post(BASE_URL, json=_create_workflow_payload())

        assert response.status_code == 402
        assert response.json()["detail"]["code"] == "subscription_required"
        mock_create.assert_not_called()

    async def test_execute_workflow_free_user_gets_402(self, client: AsyncClient):
        with patch(f"{_WF_SERVICE}.execute_workflow", new_callable=AsyncMock) as mock_execute:
            response = await client.post(f"{BASE_URL}/wf_abc123/execute", json={})

        assert response.status_code == 402
        assert response.json()["detail"]["code"] == "subscription_required"
        mock_execute.assert_not_called()

    async def test_activate_workflow_free_user_gets_402(self, client: AsyncClient):
        with patch(f"{_WF_SERVICE}.activate_workflow", new_callable=AsyncMock) as mock_activate:
            response = await client.post(f"{BASE_URL}/wf_abc123/activate")

        assert response.status_code == 402
        assert response.json()["detail"]["code"] == "subscription_required"
        mock_activate.assert_not_called()

    async def test_create_from_todo_free_user_gets_402(self, client: AsyncClient):
        with patch(f"{_WF_SERVICE}.create_workflow", new_callable=AsyncMock) as mock_create:
            response = await client.post(
                f"{BASE_URL}/from-todo",
                json={"todo_id": "todo_123", "todo_title": "Buy groceries"},
            )

        assert response.status_code == 402
        assert response.json()["detail"]["code"] == "subscription_required"
        mock_create.assert_not_called()

    async def test_regenerate_steps_free_user_gets_402(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.regenerate_workflow_steps", new_callable=AsyncMock
        ) as mock_regen:
            response = await client.post(
                f"{BASE_URL}/wf_abc123/regenerate-steps",
                json={"instruction": "Make it better"},
            )

        assert response.status_code == 402
        assert response.json()["detail"]["code"] == "subscription_required"
        mock_regen.assert_not_called()

    async def test_generate_prompt_free_user_gets_402(self, client: AsyncClient):
        with patch(
            f"{_WF_GEN_SERVICE}.generate_workflow_prompt", new_callable=AsyncMock
        ) as mock_gen:
            response = await client.post(
                f"{BASE_URL}/generate-prompt",
                json={"title": "My Workflow"},
            )

        assert response.status_code == 402
        assert response.json()["detail"]["code"] == "subscription_required"
        mock_gen.assert_not_called()

    async def test_deactivate_workflow_free_user_is_not_gated(self, client: AsyncClient):
        """Deactivate must stay reachable for a lapsed user — otherwise a free
        user could never turn off a workflow the paywall itself deactivated."""
        mock_wf = _make_workflow(activated=False)
        with patch(
            f"{_WF_SERVICE}.deactivate_workflow",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/deactivate")

        assert response.status_code == 200

    async def test_list_workflows_free_user_is_not_gated(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.list_workflows",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            response = await client.get(BASE_URL)

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /workflows
# ---------------------------------------------------------------------------


class TestCreateWorkflow:
    """Tests for the create workflow endpoint."""

    @pytest.fixture(autouse=True)
    def _pro_subscription(self):
        with patch(
            _GET_SUBSCRIPTION_STATUS,
            new_callable=AsyncMock,
            return_value=_subscription_mock(),
        ):
            yield

    async def test_create_workflow_returns_200(self, client: AsyncClient):
        mock_wf = _make_workflow()
        with (
            patch(
                "app.api.v1.endpoints.workflows.get_all_integrations_status",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                f"{_WF_SERVICE}.create_workflow",
                new_callable=AsyncMock,
                return_value=mock_wf,
            ),
            patch("app.api.v1.endpoints.workflows.capture_context_event") as mock_capture,
            patch("app.api.v1.endpoints.workflows.log") as mock_log,
        ):
            response = await client.post(BASE_URL, json=_create_workflow_payload())

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Workflow created successfully"
        mock_capture.assert_called_once_with(
            AnalyticsEvents.WORKFLOW_CREATED,
            {
                "trigger_type": "manual",
                "steps_count": 1,
                "generated_immediately": False,
            },
        )
        assert type(mock_capture.call_args.args[1]["trigger_type"]) is str
        mock_log.set.assert_any_call(
            workflow=WorkflowContext(
                id="wf_abc123",
                title="My Workflow",
                steps_count=1,
                trigger_type="manual",
            ),
            outcome="success",
        )

    async def test_create_workflow_without_steps_captures_zero(self, client: AsyncClient):
        """A workflow with no steps reports steps_count 0, not 1."""
        mock_wf = _make_workflow(steps=[])
        with (
            patch(
                "app.api.v1.endpoints.workflows.get_all_integrations_status",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                f"{_WF_SERVICE}.create_workflow",
                new_callable=AsyncMock,
                return_value=mock_wf,
            ),
            patch("app.api.v1.endpoints.workflows.capture_context_event") as mock_capture,
        ):
            response = await client.post(BASE_URL, json=_create_workflow_payload())

        assert response.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.WORKFLOW_CREATED,
            {
                "trigger_type": "manual",
                "steps_count": 0,
                "generated_immediately": False,
            },
        )

    async def test_create_workflow_captures_trigger_type(self, client: AsyncClient):
        """The request's trigger_config.type is reported in the capture."""
        mock_wf = _make_workflow()
        with (
            patch(
                "app.api.v1.endpoints.workflows.get_all_integrations_status",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                f"{_WF_SERVICE}.create_workflow",
                new_callable=AsyncMock,
                return_value=mock_wf,
            ),
            patch("app.api.v1.endpoints.workflows.capture_context_event") as mock_capture,
        ):
            response = await client.post(
                BASE_URL,
                json=_create_workflow_payload(trigger_config={"type": "schedule", "enabled": True}),
            )

        assert response.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.WORKFLOW_CREATED,
            {
                "trigger_type": "schedule",
                "steps_count": 1,
                "generated_immediately": False,
            },
        )
        assert type(mock_capture.call_args.args[1]["trigger_type"]) is str

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

    async def test_create_workflow_value_error_returns_400(self, client: AsyncClient):
        with (
            patch(
                "app.api.v1.endpoints.workflows.get_all_integrations_status",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                f"{_WF_SERVICE}.create_workflow",
                new_callable=AsyncMock,
                side_effect=ValueError("Invalid trigger config"),
            ),
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


class TestListWorkflows:
    """Tests for the list workflows endpoint."""

    async def test_list_workflows_returns_200(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.list_workflows",
            new_callable=AsyncMock,
            return_value=([_make_workflow()], 1),
        ):
            response = await client.get(BASE_URL)

        assert response.status_code == 200

    async def test_list_workflows_empty(self, client: AsyncClient):
        with patch(
            f"{_WF_SERVICE}.list_workflows",
            new_callable=AsyncMock,
            return_value=([], 0),
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


class TestExecuteWorkflow:
    """Tests for the execute workflow endpoint."""

    @pytest.fixture(autouse=True)
    def _pro_subscription(self):
        with patch(
            _GET_SUBSCRIPTION_STATUS,
            new_callable=AsyncMock,
            return_value=_subscription_mock(),
        ):
            yield

    async def test_execute_workflow_returns_200(self, client: AsyncClient):
        mock_result = WorkflowExecutionResponse(
            execution_id="exec_123",
            message="Workflow execution started",
        )
        with (
            patch(
                f"{_WF_SERVICE}.execute_workflow",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("app.api.v1.endpoints.workflows.log") as mock_log,
            patch("app.api.v1.endpoints.workflows.capture_context_event") as mock_capture,
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/execute", json={})

        assert response.status_code == 200
        mock_log.set.assert_any_call(
            workflow=WorkflowContext(execution_id="exec_123"),
            outcome="success",
        )
        mock_capture.assert_called_once_with(AnalyticsEvents.WORKFLOW_EXECUTED)
        assert any(
            "execution_id" in c.kwargs["workflow"]
            and type(c.kwargs["workflow"]["execution_id"]) is str
            for c in mock_log.set.call_args_list
            if "workflow" in c.kwargs
        )

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

    async def test_execute_workflow_service_error_returns_500(self, client: AsyncClient):
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


class TestGetWorkflowStatus:
    """Tests for the get workflow status endpoint."""

    async def test_get_status_returns_200(self, client: AsyncClient):
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


class TestActivateWorkflow:
    """Tests for the activate workflow endpoint."""

    @pytest.fixture(autouse=True)
    def _pro_subscription(self):
        with patch(
            _GET_SUBSCRIPTION_STATUS,
            new_callable=AsyncMock,
            return_value=_subscription_mock(),
        ):
            yield

    async def test_activate_returns_200(self, client: AsyncClient):
        mock_wf = _make_workflow(activated=True)
        with (
            patch(
                f"{_WF_SERVICE}.activate_workflow",
                new_callable=AsyncMock,
                return_value=mock_wf,
            ),
            patch("app.api.v1.endpoints.workflows.capture_context_event") as mock_capture,
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/activate")

        assert response.status_code == 200
        mock_capture.assert_called_once_with(AnalyticsEvents.WORKFLOW_ACTIVATED)
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


class TestRegenerateSteps:
    """Tests for the regenerate workflow steps endpoint."""

    @pytest.fixture(autouse=True)
    def _pro_subscription(self):
        with patch(
            _GET_SUBSCRIPTION_STATUS,
            new_callable=AsyncMock,
            return_value=_subscription_mock(),
        ):
            yield

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

    async def test_regenerate_steps_missing_instruction_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{BASE_URL}/wf_abc123/regenerate-steps",
            json={},
        )
        assert response.status_code == 422

    async def test_regenerate_steps_service_error_returns_500(self, client: AsyncClient):
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


class TestCreateWorkflowFromTodo:
    """Tests for the create workflow from todo endpoint."""

    @pytest.fixture(autouse=True)
    def _pro_subscription(self):
        with patch(
            _GET_SUBSCRIPTION_STATUS,
            new_callable=AsyncMock,
            return_value=_subscription_mock(),
        ):
            yield

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


class TestPublishWorkflow:
    """Tests for the publish workflow endpoint."""

    async def test_publish_returns_200(self, client: AsyncClient):
        doc = _make_workflow_doc(title="My Public Workflow", slug=None)
        with (
            patch(f"{_WF_REPO}.get_for_user", new_callable=AsyncMock, return_value=doc),
            patch(f"{_WF_REPO}.publish", new_callable=AsyncMock, return_value=doc),
            patch(
                _GEN_SLUG,
                new_callable=AsyncMock,
                return_value="my-public-workflow-abc123",
            ),
            patch("app.api.v1.endpoints.workflows.capture_context_event") as mock_capture,
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/publish")

        assert response.status_code == 200
        mock_capture.assert_called_once_with(AnalyticsEvents.WORKFLOW_PUBLISHED)
        data = response.json()
        assert data["message"] == "Workflow published successfully"
        assert data["slug"] == "my-public-workflow-abc123"

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
        assert publish.await_args.kwargs["slug"] == "already-set-abcdef"

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

    async def test_publish_not_found_returns_404(self, client: AsyncClient):
        with patch(f"{_WF_REPO}.get_for_user", new_callable=AsyncMock, return_value=None):
            response = await client.post(f"{BASE_URL}/wf_nonexist/publish")

        assert response.status_code == 404

    async def test_publish_service_error_returns_500(self, client: AsyncClient):
        with patch(
            f"{_WF_REPO}.get_for_user",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/publish")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /workflows/{id}/unpublish
# ---------------------------------------------------------------------------


class TestUnpublishWorkflow:
    """Tests for the unpublish workflow endpoint."""

    async def test_unpublish_returns_200(self, client: AsyncClient):
        doc = _make_workflow_doc(is_public=True)
        with (
            patch(f"{_WF_REPO}.get_for_user", new_callable=AsyncMock, return_value=doc),
            patch(f"{_WF_REPO}.unpublish", new_callable=AsyncMock, return_value=doc),
        ):
            response = await client.post(f"{BASE_URL}/wf_abc123/unpublish")

        assert response.status_code == 200
        assert response.json()["message"] == "Workflow unpublished successfully"

    async def test_unpublish_not_found_returns_404(self, client: AsyncClient):
        with patch(f"{_WF_REPO}.get_for_user", new_callable=AsyncMock, return_value=None):
            response = await client.post(f"{BASE_URL}/wf_nonexist/unpublish")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /workflows/explore
# ---------------------------------------------------------------------------


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


class TestGetPublicWorkflow:
    """Tests for the get public workflow endpoint."""

    async def test_get_public_workflow_by_id_returns_200(self, client: AsyncClient):
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
        ):
            response = await client.get(f"{BASE_URL}/public/wf_abc123")

        assert response.status_code == 200
        data = response.json()["workflow"]
        assert data["id"] == "wf_abc123"
        assert data["creator"]["name"] == "Test User"
        # the join scaffolding must not leak into the response
        assert "creator_info" not in data

    async def test_get_public_workflow_not_found_returns_404(self, client: AsyncClient):
        with patch(
            f"{_WF_REPO}.get_public_with_creator",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get(f"{BASE_URL}/public/nonexistent-slug")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /workflows/generate-prompt
# ---------------------------------------------------------------------------


class TestGeneratePrompt:
    """Tests for the generate workflow prompt endpoint."""

    @pytest.fixture(autouse=True)
    def _pro_subscription(self):
        with patch(
            _GET_SUBSCRIPTION_STATUS,
            new_callable=AsyncMock,
            return_value=_subscription_mock(),
        ):
            yield

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
