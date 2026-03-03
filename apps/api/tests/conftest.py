"""Root test configuration for GAIA API tests."""

import os

os.environ.setdefault("ENV", "development")
os.environ.setdefault("MONGO_DB", "gaia_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("WORKOS_API_KEY", "test_workos_api_key")
os.environ.setdefault("WORKOS_CLIENT_ID", "test_workos_client_id")
os.environ.setdefault("WORKOS_COOKIE_PASSWORD", "test_cookie_password_at_least_32_chars_long!!")
os.environ.setdefault("MCP_ENCRYPTION_KEY", "dGVzdF9lbmNyeXB0aW9uX2tleV8zMl9ieXRlcw==")  # base64 test key

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (fast, no external deps)")
    config.addinivalue_line(
        "markers",
        "integration: Integration tests (compiled graphs, mocked services)",
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-end tests (real or near-real services)"
    )
    config.addinivalue_line(
        "markers", "composio: Composio integration tests (require credentials)"
    )
    config.addinivalue_line("markers", "slow: Slow tests")


def pytest_addoption(parser):
    """Add custom CLI options for test configuration."""
    parser.addoption(
        "--user-id",
        action="store",
        default=None,
        help="User ID for integration tests",
    )
    parser.addoption(
        "--skip-destructive",
        action="store_true",
        default=False,
        help="Skip destructive tests",
    )
    parser.addoption(
        "--yes",
        action="store_true",
        default=False,
        help="Auto-confirm interactive prompts",
    )


@pytest.fixture(scope="session")
def user_id(request):
    """Get test user ID from CLI or environment."""
    return request.config.getoption("--user-id") or os.environ.get("EVAL_USER_ID")


@pytest.fixture(scope="session")
def skip_destructive(request):
    """Whether to skip destructive tests."""
    return request.config.getoption("--skip-destructive")
