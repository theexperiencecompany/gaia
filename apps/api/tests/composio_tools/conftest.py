"""
Pytest fixtures for Composio custom tool testing.

Provides shared fixtures:
- composio_client: Initialized Composio client
- user_id: User ID from CLI arg
- calendar_id: Primary calendar ID
- test_event: Creates/cleans up a test event

Usage:
    pytest tests/composio_tools/test_calendar.py -v --user-id USER_ID
"""

import asyncio
import json
import logging
from typing import Any, Dict

import app.patches  # noqa: F401, E402
import nest_asyncio
import pytest
from app.core.lazy_loader import providers
from app.services.composio.composio_service import get_composio_service

from tests.composio_tools.config_utils import get_user_id

# Apply nest_asyncio for nested event loops
nest_asyncio.apply()

logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    """Add custom CLI options for pytest."""
    parser.addoption(
        "--user-id",
        action="store",
        default=None,
        help="User ID for Composio authentication",
    )
    parser.addoption(
        "--skip-destructive",
        action="store_true",
        default=False,
        help="Skip tests that create/modify/delete events",
    )
    parser.addoption(
        "--yes",
        action="store_true",
        default=False,
        help="Automatically confirm all interactive prompts",
    )


@pytest.fixture(scope="session")
def user_id(request) -> str:
    """Get user ID from CLI argument or config/env."""
    cli_user_id = request.config.getoption("--user-id")
    if cli_user_id:
        return cli_user_id

    # Fall back to config/env
    config_user_id = get_user_id()

    if not config_user_id:
        pytest.fail("No user ID provided. Set EVAL_USER_ID or use --user-id flag.")

    return config_user_id


@pytest.fixture(scope="session")
def skip_destructive(request) -> bool:
    """Check if destructive tests should be skipped."""
    return request.config.getoption("--skip-destructive")


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def composio_client(user_id: str):
    """Initialize Composio client and all required providers.

    This is a session-scoped fixture that initializes once for all tests.
    """
    # Import here to avoid triggering settings/Infisical at module load time
    from app.agents.evals.initialization import init_eval_providers

    # Run async initialization
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_eval_providers())

    # Get composio service from providers
    composio_service = providers.get("composio_service")
    if not composio_service:
        pytest.fail("Composio service not available. Check COMPOSIO_KEY.")
        return None

    return composio_service.composio


def execute_tool(
    composio_client, tool_name: str, payload: Dict[str, Any], user_id: str
) -> Dict[str, Any]:
    """
    Execute a tool using ComposioService and LangChain adapter.

    Args:
        composio_client: Ignored (kept for compatibility), uses provider service
        tool_name: Name of the tool to execute
        payload: Tool arguments
        user_id: User ID to execute as

    Returns:
        Dict containing 'successful', 'data', etc.
    """
    # Get the service which provides LangChain-compatible tools
    composio_service = get_composio_service()

    # Get the specific tool with all hooks applied
    tool = composio_service.get_tool(tool_name, user_id=user_id)
    if not tool:
        raise ValueError(f"Tool {tool_name} not found")

    # Invoke the tool using the LangChain interface
    try:
        # Note: tool.invoke() calls _run() which calls client.tools.execute()
        # and returns the full response dict (successful, data, etc.)
        result = tool.invoke(payload)

        # If result is a string (common for custom tools), try to parse it
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                # If not JSON, wrap it as data
                # Assuming success if it returned without error
                result = {"successful": True, "data": result}

        # Also check if 'data' field is a JSON string (Composio sometimes returns stringified data)
        if isinstance(result, dict) and isinstance(result.get("data"), str):
            try:
                result["data"] = json.loads(result["data"])
            except (json.JSONDecodeError, TypeError):
                pass  # Keep as string if not valid JSON

        return result
    except Exception as e:
        # Fallback for errors during invocation that behave like tool failures
        error_msg = str(e)
        if hasattr(e, "response") and hasattr(e.response, "text"):
            error_msg += f" | Response: {e.response.text}"

        return {"successful": False, "error": error_msg, "data": None}


@pytest.fixture(scope="function")
def confirm_action(request):
    """
    Fixture to request user confirmation for destructive actions.
    Requires running pytest with '-s' (no capture) to work interactively.
    """

    def _confirm(message: str) -> None:
        # Check for non-interactive mode flag (optional override)
        if request.config.getoption("--yes", default=False):
            return

        full_msg = f"\n[CONFIRMATION REQUIRED] {message}\nProceed? (y/N): "

        try:
            response = input(full_msg)
        except OSError:
            pytest.fail(
                "Cannot read input. Run pytest with '-s' to enable interactive confirmation."
            )

        if response.lower() not in ["y", "yes"]:
            pytest.skip("Skipped by user")

    return _confirm
