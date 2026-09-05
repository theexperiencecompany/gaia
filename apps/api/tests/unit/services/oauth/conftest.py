"""Fixtures shared by the oauth service tests: every collaborator the service
reaches, patched at the module seam."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mock_user_repo():
    with patch("app.services.oauth.oauth_service.user_repository") as mock_repo:
        mock_repo.get_by_email = AsyncMock()
        mock_repo.get = AsyncMock()
        mock_repo.update = AsyncMock()
        mock_repo.create = AsyncMock()
        mock_repo.set_bio_status = AsyncMock()
        yield mock_repo


@pytest.fixture
def mock_user_integration_repo():
    with patch("app.services.oauth.oauth_service.user_integration_repository") as mock_repo:
        mock_repo.list_for_user = AsyncMock(return_value=[])
        yield mock_repo


@pytest.fixture
def mock_token_repository():
    with patch("app.services.oauth.oauth_service.token_repository") as mock_repo:
        yield mock_repo


@pytest.fixture
def mock_composio_service():
    mock_service = AsyncMock()
    mock_service.check_connection_status = AsyncMock(return_value={})
    with patch(
        "app.services.oauth.oauth_service.get_composio_service",
        return_value=mock_service,
    ):
        yield mock_service


@pytest.fixture
def mock_update_user_integration_status():
    with patch(
        "app.services.oauth.oauth_service.update_user_integration_status",
        new_callable=AsyncMock,
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_websocket_manager():
    with patch("app.services.oauth.oauth_service.websocket_manager") as mock_ws:
        mock_ws.broadcast_to_user = AsyncMock()
        yield mock_ws


@pytest.fixture
def mock_redis_pool_manager(route_enqueue_via_pool):
    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()
    with patch("app.services.oauth.oauth_service.RedisPoolManager") as mock_rpm:
        mock_rpm.get_pool = AsyncMock(return_value=mock_pool)
        yield mock_pool


@pytest.fixture
def mock_track_signup():
    with patch("app.services.oauth.oauth_service.track_signup") as mock_ts:
        yield mock_ts


@pytest.fixture
def mock_track_login():
    with patch("app.services.oauth.oauth_service.track_login") as mock_tl:
        yield mock_tl


@pytest.fixture
def mock_send_welcome_email():
    with patch(
        "app.services.oauth.oauth_service.send_welcome_email",
        new_callable=AsyncMock,
    ) as mock_swe:
        yield mock_swe


@pytest.fixture
def mock_add_marketing_contact():
    with patch(
        "app.services.oauth.oauth_service.add_marketing_contact",
        new_callable=AsyncMock,
    ) as mock_acr:
        yield mock_acr


@pytest.fixture
def mock_fetch_and_store_provider_metadata():
    with patch(
        "app.services.oauth.oauth_service.fetch_and_store_provider_metadata",
        new_callable=AsyncMock,
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_enqueue_personalization():
    """Gmail connect enqueues the personalization pipeline; a job id means it ran."""
    with patch(
        "app.services.oauth.oauth_service.enqueue_gmail_personalization",
        new_callable=AsyncMock,
        return_value="personalization-job-1",
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_schedule_user_provision():
    with patch("app.services.oauth.oauth_service.schedule_user_provision") as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_provision_system_workflows():
    with patch(
        "app.services.oauth.oauth_service.provision_system_workflows",
        new_callable=AsyncMock,
    ) as mock_fn:
        yield mock_fn


@pytest.fixture(autouse=True)
def bypass_cacheable():
    """Bypass the @Cacheable decorator so tests call the real function.

    The Cacheable wrapper (defined in app.decorators.caching) closes over
    get_cache / set_cache imported from app.db.redis.  Patching them there
    ensures every cached call goes straight through to the wrapped function.
    """
    with (
        patch("app.db.redis.redis_cache.get", new_callable=AsyncMock, return_value=None),
        patch("app.db.redis.redis_cache.set", new_callable=AsyncMock),
    ):
        yield
