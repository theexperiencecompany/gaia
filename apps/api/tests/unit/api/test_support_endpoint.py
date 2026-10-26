"""Endpoint tests for /api/v1/support.

Covers the MAX_PAGE_NUMBER page bound on the my-requests list and the
happy path with the service faked.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

from fastapi import FastAPI
import httpx
from httpx import ASGITransport, AsyncClient
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
import pytest
import respx

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_current_user as _get_current_user_dep,
    get_optional_user,
)
from app.api.v1.endpoints.support import router
from app.api.v1.middleware.rate_limiter import limiter
from app.config.settings import settings
from app.constants.general import MAX_PAGE_NUMBER
from app.constants.turnstile import TURNSTILE_SITEVERIFY_URL
from app.models.support_models import (
    SupportRequestDocument,
    SupportRequestSubmissionResponse,
    SupportRequestType,
)
from app.models.user_models import AuthenticatedUser
from shared.py.analytics import UserId
from shared.py.analytics.catalog.support import SupportFormSubmitted
from tests.conftest import FAKE_USER

SUPPORT_ENDPOINT = "app.api.v1.endpoints.support"


class TestSelfHostedInstances:
    """A self-hosted instance's users and their data never reach GAIA's support inbox."""

    async def test_every_support_route_refuses_on_a_self_hosted_instance(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "ENV", "selfhost")
        with (
            patch(f"{SUPPORT_ENDPOINT}.create_support_request", new_callable=AsyncMock) as create,
            patch(f"{SUPPORT_ENDPOINT}.get_user_support_requests", new_callable=AsyncMock),
        ):
            submitted = await client.post(
                "/api/v1/support/requests",
                json={
                    "type": "support",
                    "title": "Need help",
                    "description": "It broke completely",
                },
            )
            listed = await client.get("/api/v1/support/requests/my")

        assert submitted.status_code == 404
        assert submitted.json()["code"] == "gaia_support_unavailable"
        assert submitted.json()["message"] == (
            "In-app support is not available on a self-hosted instance"
        )
        assert submitted.json()["fix"] == (
            "Report bugs and request features on GitHub: "
            "https://github.com/theexperiencecompany/gaia/issues"
        )
        assert listed.status_code == 404
        create.assert_not_awaited()


class TestGetMySupportRequests:
    """GET /api/v1/support/requests/my."""

    async def test_page_over_max_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/v1/support/requests/my?page={MAX_PAGE_NUMBER + 1}")

        assert resp.status_code == 422

    async def test_list_returns_requests(self, client: AsyncClient) -> None:
        with patch(
            f"{SUPPORT_ENDPOINT}.get_user_support_requests",
            new_callable=AsyncMock,
            return_value={
                "requests": [],
                "pagination": {"page": 1, "per_page": 10, "total": 0, "pages": 0},
            },
        ) as fetch:
            resp = await client.get("/api/v1/support/requests/my?page=1&per_page=10")

        assert resp.status_code == 200
        body = resp.json()
        assert body["requests"] == []
        assert body["pagination"]["page"] == 1
        fetch.assert_awaited_once_with(
            user_id="507f1f77bcf86cd799439011", page=1, per_page=10, status_filter=None
        )


class TestSubmitSupportRequest:
    """POST /api/v1/support/requests (+ attachments variant)."""

    async def test_submit_captures_analytics(self, client: AsyncClient) -> None:
        result = SupportRequestSubmissionResponse(
            success=True, message="Submitted", ticket_id="T-123"
        )
        with (
            patch(
                f"{SUPPORT_ENDPOINT}.create_support_request",
                new_callable=AsyncMock,
                return_value=result,
            ),
            patch(f"{SUPPORT_ENDPOINT}.capture") as mock_capture,
        ):
            resp = await client.post(
                "/api/v1/support/requests",
                json={
                    "type": "support",
                    "title": "Need help",
                    "description": "It broke completely",
                },
            )

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(
            UserId(FAKE_USER.user_id),
            SupportFormSubmitted(
                request_type="support",
                title_length=len("Need help"),
                description_length=len("It broke completely"),
                attachment_count=0,
            ),
        )

    async def test_submit_passes_the_callers_identity_to_the_service(
        self, client: AsyncClient
    ) -> None:
        result = SupportRequestSubmissionResponse(
            success=True, message="Submitted", ticket_id="T-127"
        )
        with (
            patch(
                f"{SUPPORT_ENDPOINT}.create_support_request",
                new_callable=AsyncMock,
                return_value=result,
            ) as create,
            patch(f"{SUPPORT_ENDPOINT}.capture"),
        ):
            resp = await client.post(
                "/api/v1/support/requests",
                json={
                    "type": "support",
                    "title": "Need help",
                    "description": "It broke completely",
                },
            )

        assert resp.status_code == 200
        kwargs = create.await_args.kwargs
        assert kwargs["request_data"].title == "Need help"
        assert kwargs["user_id"] == "507f1f77bcf86cd799439011"
        assert kwargs["user_email"] == "test@example.com"
        assert kwargs["user_name"] == "Test User"

    async def test_submit_with_attachments_captures_analytics(self, client: AsyncClient) -> None:
        result = SupportRequestSubmissionResponse(
            success=True, message="Submitted", ticket_id="T-124"
        )
        with (
            patch(
                f"{SUPPORT_ENDPOINT}.create_support_request_with_attachments",
                new_callable=AsyncMock,
                return_value=result,
            ),
            patch(f"{SUPPORT_ENDPOINT}.capture") as mock_capture,
        ):
            resp = await client.post(
                "/api/v1/support/requests/with-attachments",
                data={"type": "feature", "title": "New idea", "description": "Add a thing"},
                files=[("attachments", ("a.png", b"png", "image/png"))],
            )

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(
            UserId(FAKE_USER.user_id),
            SupportFormSubmitted(
                request_type="feature",
                title_length=len("New idea"),
                description_length=len("Add a thing"),
                attachment_count=1,
            ),
        )

    async def test_submit_with_attachments_invalid_type_returns_400_exact_detail(
        self, client: AsyncClient
    ) -> None:
        """An unrecognized multipart type is rejected with every valid option named."""
        resp = await client.post(
            "/api/v1/support/requests/with-attachments",
            data={"type": "bogus", "title": "T", "description": "Something broke badly"},
        )

        assert resp.status_code == 400
        assert resp.json()["message"] == "Invalid request type. Must be one of: support, feature"

    async def test_submit_with_attachments_passes_exact_kwargs_to_service(
        self, client: AsyncClient
    ) -> None:
        """The service receives the validated type plus the caller's identity."""
        result = SupportRequestSubmissionResponse(
            success=True, message="Submitted", ticket_id="T-125"
        )
        with (
            patch(
                f"{SUPPORT_ENDPOINT}.create_support_request_with_attachments",
                new_callable=AsyncMock,
                return_value=result,
            ) as create,
            patch(f"{SUPPORT_ENDPOINT}.log"),
        ):
            resp = await client.post(
                "/api/v1/support/requests/with-attachments",
                data={
                    "type": "feature",
                    "title": "New idea",
                    "description": "Add a thing",
                },
                files=[("attachments", ("a.png", b"png", "image/png"))],
            )

        assert resp.status_code == 200
        create.assert_awaited_once()
        kwargs = create.await_args.kwargs
        assert kwargs["request_data"].type is SupportRequestType.FEATURE
        assert kwargs["request_data"].title == "New idea"
        assert kwargs["request_data"].description == "Add a thing"
        assert kwargs["user_id"] == "507f1f77bcf86cd799439011"
        assert kwargs["user_email"] == "test@example.com"
        assert kwargs["user_name"] == "Test User"
        assert isinstance(kwargs["attachments"], list) and len(kwargs["attachments"]) == 1

    async def test_submit_with_attachments_service_error_wraps_as_500_exact_detail(
        self, client: AsyncClient
    ) -> None:
        """A non-HTTP failure from the service becomes a 500 with the cause appended."""
        with (
            patch(
                f"{SUPPORT_ENDPOINT}.create_support_request_with_attachments",
                new_callable=AsyncMock,
                side_effect=RuntimeError("cloudinary down"),
            ),
            patch(f"{SUPPORT_ENDPOINT}.log"),
        ):
            resp = await client.post(
                "/api/v1/support/requests/with-attachments",
                data={"type": "support", "title": "T", "description": "Something broke badly"},
            )

        assert resp.status_code == 500
        assert resp.json()["message"] == "Failed to submit support request: cloudinary down"

    async def test_attachments_endpoint_requires_user_id_and_email(self, test_app: FastAPI) -> None:
        """Missing user_id OR email each yield 401 with the exact detail string."""
        for current_user in (
            AuthenticatedUser(user_id=""),
            AuthenticatedUser(user_id="u1"),
            AuthenticatedUser(user_id="", email="a@b.c"),
        ):
            original = test_app.dependency_overrides.get(get_current_user)
            test_app.dependency_overrides[get_current_user] = lambda cu=current_user: cu
            try:
                transport = ASGITransport(app=test_app, raise_app_exceptions=False)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:  # NOSONAR
                    resp = await ac.post(
                        "/api/v1/support/requests/with-attachments",
                        data={"type": "support", "title": "T", "description": "Something broke"},
                    )
            finally:
                if original is None:
                    test_app.dependency_overrides.pop(get_current_user, None)
                else:
                    test_app.dependency_overrides[get_current_user] = original

            assert resp.status_code == 401
            assert resp.json()["message"] == "User authentication required"


class TestSubmitSupportRequestLogPins:
    async def test_success_log_calls_are_exact(self, client: AsyncClient) -> None:
        result = SupportRequestSubmissionResponse(
            success=True, message="Submitted", ticket_id="T-126"
        )
        with (
            patch(
                f"{SUPPORT_ENDPOINT}.create_support_request_with_attachments",
                new_callable=AsyncMock,
                return_value=result,
            ),
            patch(f"{SUPPORT_ENDPOINT}.log") as mock_log,
        ):
            resp = await client.post(
                "/api/v1/support/requests/with-attachments",
                data={"type": "support", "title": "T", "description": "Something broke badly"},
            )

        assert resp.status_code == 200
        mock_log.set.assert_any_call(
            operation="submit_support_request_with_attachments", category="support"
        )
        mock_log.set.assert_any_call(ticket_id="T-126")
        mock_log.set.assert_any_call(outcome="success")

    async def test_missing_email_returns_exact_401_detail(self, test_app: FastAPI) -> None:
        """A user without an email address is rejected before anything runs."""
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        app.dependency_overrides[_get_current_user_dep] = lambda: AuthenticatedUser(user_id="u1")
        try:
            with patch(f"{SUPPORT_ENDPOINT}.log"):
                with TestClient(app, raise_server_exceptions=False) as c:
                    resp = c.post(
                        "/api/v1/support/requests/with-attachments",
                        data={"type": "support", "title": "T", "description": "Enough text"},
                    )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 401
        assert resp.json()["detail"] == "User authentication required"
        _ = test_app


PUBLIC_ENDPOINT = "/api/v1/support/requests/public"
VISITOR_IP = "198.51.100.7"
# Cloudflare's documented always-pass test secret; siteverify's answer is mocked.
TURNSTILE_TEST_SECRET = "1x0000000000000000000000000000000AA"
SERVICE = "app.services.support_service"


def _public_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "type": "support",
        "title": "Cannot sign in",
        "description": "The login page loops forever",
        "email": "visitor@example.com",
        "name": "Vis Itor",
        "turnstile_token": "tok-from-widget",
    }
    body.update(overrides)
    return {key: value for key, value in body.items() if value is not _OMIT}


_OMIT = object()


def _visitor_client(app: FastAPI, ip: str = VISITOR_IP) -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False, client=(ip, 41000))
    return AsyncClient(transport=transport, base_url="http://test")  # NOSONAR


@pytest.fixture
def turnstile_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", TURNSTILE_TEST_SECRET)


@pytest.fixture
def pipeline() -> Iterator[SimpleNamespace]:
    """Run the real support pipeline with only its repository and email sends faked."""
    repo = AsyncMock()

    async def _create(doc: SupportRequestDocument) -> SupportRequestDocument:
        doc.updated_at = doc.created_at
        return doc

    repo.create.side_effect = _create
    with (
        patch(f"{SERVICE}.support_request_repository", repo),
        patch(f"{SERVICE}.send_support_team_notification", new_callable=AsyncMock) as team,
        patch(f"{SERVICE}.send_support_to_user_email", new_callable=AsyncMock) as user,
        patch(f"{SUPPORT_ENDPOINT}.capture") as capture,
    ):
        yield SimpleNamespace(repo=repo, team=team, user=user, capture=capture)


def _siteverify(success: bool, *codes: str) -> respx.Route:
    return respx.post(TURNSTILE_SITEVERIFY_URL).mock(
        return_value=httpx.Response(200, json={"success": success, "error-codes": list(codes)})
    )


@pytest.mark.usefixtures("turnstile_secret")
class TestSubmitPublicSupportRequest:
    """POST /api/v1/support/requests/public — no session, Turnstile-gated, per-IP limited."""

    @respx.mock
    async def test_a_visitor_with_a_valid_token_files_a_ticket_through_the_shared_pipeline(
        self, test_app: FastAPI, pipeline: SimpleNamespace
    ) -> None:
        siteverify = _siteverify(True)

        async with _visitor_client(test_app) as client:
            resp = await client.post(PUBLIC_ENDPOINT, json=_public_body())

        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        assert resp.json()["support_request"]["user_id"] is None
        sent = parse_qs(siteverify.calls.last.request.content.decode())
        assert sent["response"] == ["tok-from-widget"]
        assert sent["remoteip"] == [VISITOR_IP]
        stored: SupportRequestDocument = pipeline.repo.create.await_args.args[0]
        assert stored.user_id is None
        assert stored.user_email == "visitor@example.com"
        assert stored.user_name == "Vis Itor"
        assert stored.metadata["source"] == "public_contact_form"
        notification = pipeline.user.await_args.args[0]
        assert notification.user_email == "visitor@example.com"
        pipeline.team.assert_awaited_once()
        pipeline.capture.assert_not_called()

    @respx.mock
    async def test_a_rejected_token_files_nothing(
        self, test_app: FastAPI, pipeline: SimpleNamespace
    ) -> None:
        _siteverify(False, "invalid-input-response")

        async with _visitor_client(test_app) as client:
            resp = await client.post(PUBLIC_ENDPOINT, json=_public_body(turnstile_token="forged"))

        assert resp.status_code == 400
        assert resp.json()["code"] == "turnstile_verification_failed"
        assert resp.json()["message"] == "We could not verify that you are human"
        pipeline.repo.create.assert_not_awaited()
        pipeline.user.assert_not_awaited()

    @respx.mock
    async def test_a_missing_token_is_refused_before_cloudflare_is_asked(
        self, test_app: FastAPI, pipeline: SimpleNamespace
    ) -> None:
        siteverify = _siteverify(True)

        async with _visitor_client(test_app) as client:
            missing = await client.post(PUBLIC_ENDPOINT, json=_public_body(turnstile_token=_OMIT))
            empty = await client.post(PUBLIC_ENDPOINT, json=_public_body(turnstile_token=""))

        assert (missing.status_code, empty.status_code) == (422, 422)
        assert not siteverify.called
        pipeline.repo.create.assert_not_awaited()

    @respx.mock
    async def test_a_siteverify_timeout_is_an_explicit_503_and_files_nothing(
        self, test_app: FastAPI, pipeline: SimpleNamespace
    ) -> None:
        respx.post(TURNSTILE_SITEVERIFY_URL).mock(side_effect=httpx.ReadTimeout("slow"))

        async with _visitor_client(test_app) as client:
            resp = await client.post(PUBLIC_ENDPOINT, json=_public_body())

        assert resp.status_code == 503
        assert resp.json()["code"] == "turnstile_unavailable"
        pipeline.repo.create.assert_not_awaited()

    @respx.mock
    async def test_an_unset_secret_is_an_explicit_503_and_files_nothing(
        self, test_app: FastAPI, pipeline: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", None)
        siteverify = _siteverify(True)

        async with _visitor_client(test_app) as client:
            resp = await client.post(PUBLIC_ENDPOINT, json=_public_body())

        assert resp.status_code == 503
        assert resp.json()["code"] == "turnstile_unavailable"
        assert not siteverify.called
        pipeline.repo.create.assert_not_awaited()

    @respx.mock
    async def test_a_visitor_without_an_email_is_refused_without_spending_the_token(
        self, test_app: FastAPI, pipeline: SimpleNamespace
    ) -> None:
        siteverify = _siteverify(True)

        async with _visitor_client(test_app) as client:
            resp = await client.post(PUBLIC_ENDPOINT, json=_public_body(email=_OMIT))

        assert resp.status_code == 422
        assert resp.json()["code"] == "contact_email_required"
        assert not siteverify.called
        pipeline.repo.create.assert_not_awaited()

    @respx.mock
    async def test_a_signed_in_caller_is_attributed_to_their_user_id(
        self, test_app: FastAPI, pipeline: SimpleNamespace
    ) -> None:
        _siteverify(True)
        no_email = AuthenticatedUser(user_id=FAKE_USER.user_id, name="Signed In")
        test_app.dependency_overrides[get_optional_user] = lambda: no_email
        try:
            async with _visitor_client(test_app) as client:
                resp = await client.post(PUBLIC_ENDPOINT, json=_public_body(name=_OMIT))
        finally:
            test_app.dependency_overrides.pop(get_optional_user, None)

        assert resp.status_code == 200, resp.text
        stored: SupportRequestDocument = pipeline.repo.create.await_args.args[0]
        assert stored.user_id == FAKE_USER.user_id
        assert stored.user_email == "visitor@example.com"
        assert stored.user_name == "Signed In"
        pipeline.capture.assert_called_once_with(
            UserId(FAKE_USER.user_id),
            SupportFormSubmitted(
                request_type="support",
                title_length=len("Cannot sign in"),
                description_length=len("The login page loops forever"),
                attachment_count=0,
            ),
        )

    @respx.mock
    async def test_the_hourly_limit_is_counted_per_client_ip(
        self,
        test_app: FastAPI,
        pipeline: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        storage = MemoryStorage()
        monkeypatch.setattr(limiter, "enabled", True)
        monkeypatch.setattr(limiter, "_storage", storage)
        monkeypatch.setattr(limiter, "_limiter", FixedWindowRateLimiter(storage))
        _siteverify(True)

        async with _visitor_client(test_app, "198.51.100.1") as first_ip:
            statuses = [
                (await first_ip.post(PUBLIC_ENDPOINT, json=_public_body())).status_code
                for _ in range(6)
            ]
        async with _visitor_client(test_app, "198.51.100.2") as second_ip:
            other = await second_ip.post(PUBLIC_ENDPOINT, json=_public_body())

        assert statuses == [200, 200, 200, 200, 200, 429]
        assert other.status_code == 200
        assert pipeline.repo.create.await_count == 6
