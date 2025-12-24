"""
Pytest fixtures for Composio custom tool testing.

Provides shared fixtures:
- composio_client: Initialized Composio client
- user_id: User ID from CLI arg
- calendar_id: Primary calendar ID
- test_event: Creates/cleans up a test event

Usage:
    pytest tests/composio_tools/test_calendar_pytest.py -v --user-id USER_ID
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, Generator

import nest_asyncio
import pytest
from pytest_check import check  # noqa: F401 - for soft assertions

# Apply nest_asyncio for nested event loops
nest_asyncio.apply()


def pytest_addoption(parser):
    """Add custom CLI options for pytest."""
    parser.addoption(
        "--user-id",
        action="store",
        required=True,
        help="User ID for Composio authentication",
    )
    parser.addoption(
        "--skip-destructive",
        action="store_true",
        default=False,
        help="Skip tests that create/modify/delete events",
    )


@pytest.fixture(scope="session")
def user_id(request) -> str:
    """Get user ID from CLI argument."""
    return request.config.getoption("--user-id")


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
    from app.agents.evals.initialization import init_eval_providers
    from app.core.lazy_loader import providers

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
    composio_client, tool_name: str, params: Dict[str, Any], user_id: str
) -> Dict[str, Any]:
    """Execute a Composio tool and return the result.

    Args:
        composio_client: The Composio client
        tool_name: Name of the tool to execute
        params: Parameters for the tool
        user_id: User ID for execution context

    Returns:
        The tool execution result
    """
    result = composio_client.tools.execute(
        slug=tool_name,
        arguments=params,
        user_id=user_id,
    )
    return result.data if hasattr(result, "data") else result


@pytest.fixture(scope="session")
def calendar_id(composio_client, user_id: str) -> str:
    """Get the primary calendar ID for the user."""
    result = execute_tool(
        composio_client,
        "GOOGLECALENDAR_CUSTOM_LIST_CALENDARS",
        {"short": True},
        user_id,
    )

    if not result.get("successful"):
        pytest.fail(f"Failed to list calendars: {result.get('error')}")

    calendars = result.get("data", {}).get("calendars", [])
    if not calendars:
        pytest.fail("No calendars found for user")

    # Prefer primary calendar, otherwise use first available
    for cal in calendars:
        if cal.get("primary"):
            return cal["id"]
    return calendars[0]["id"]


@pytest.fixture(scope="session")
def test_event(
    composio_client, user_id: str, calendar_id: str
) -> Generator[Dict[str, Any], None, None]:
    """Create a test event for the session and clean up after.

    Yields:
        Dict with event_id and calendar_id
    """
    # Create event for 2 hours from now
    now = datetime.now()
    start_time = (now + timedelta(hours=2)).replace(second=0, microsecond=0)

    result = execute_tool(
        composio_client,
        "GOOGLECALENDAR_CUSTOM_CREATE_EVENT",
        {
            "events": [
                {
                    "summary": "[PYTEST] Session Test Event",
                    "description": "Auto-created by pytest suite. Will be auto-deleted.",
                    "calendar_id": calendar_id,
                    "start_datetime": start_time.isoformat(),
                    "duration_hours": 1,
                    "duration_minutes": 0,
                    "is_all_day": False,
                }
            ],
            "confirm_immediately": True,
        },
        user_id,
    )

    if not result.get("successful"):
        pytest.fail(f"Failed to create test event: {result.get('error')}")

    created = result.get("data", {}).get("created_events", [])
    if not created:
        pytest.fail("No event created in response")

    event_info = {
        "event_id": created[0].get("event_id"),
        "calendar_id": created[0].get("calendar_id") or calendar_id,
    }

    yield event_info

    # Cleanup: delete the test event
    execute_tool(
        composio_client,
        "GOOGLECALENDAR_CUSTOM_DELETE_EVENT",
        {
            "events": [
                {
                    "event_id": event_info["event_id"],
                    "calendar_id": event_info["calendar_id"],
                }
            ],
            "send_updates": "none",
        },
        user_id,
    )
