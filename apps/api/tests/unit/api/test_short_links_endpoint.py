"""Tests for app/api/v1/endpoints/short_links.py."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.config.settings import settings
from app.models.short_link_models import PublicTodoDeliverable, ShortLinkTargetType
from app.services.storage import JuiceFSUnavailable
from app.utils.log_identifiers import hash_short_link_slug
from tests.conftest import FAKE_USER
from tests.helpers import captured_wide_event

# routes.py mounts the short-links router at its own "/l" prefix.
BASE = "/api/v1/l"
SLUG = "abcdefghijk"
TODO = ShortLinkTargetType.TODO_DELIVERABLE

_ENDPOINT = "app.api.v1.endpoints.short_links"

_VIEW = PublicTodoDeliverable(target_type=TODO, title="Q3 plan", completed=True, content="body")


class TestResolveShortLink:
    """Tests for GET /l/{slug}."""

    @pytest.mark.asyncio
    async def test_resolved_view_is_never_cached(self, client: AsyncClient) -> None:
        """A capability URL can be revoked at any moment, so nothing may cache it."""
        with patch(f"{_ENDPOINT}.get_public_view", AsyncMock(return_value=_VIEW)) as resolve:
            response = await client.get(f"{BASE}/{SLUG}")

        assert response.status_code == 200
        assert response.json() == _VIEW.model_dump(mode="json")
        assert response.headers["cache-control"] == "no-store"
        resolve.assert_awaited_once_with(SLUG)

    @pytest.mark.asyncio
    async def test_the_wide_event_names_the_slug_hash_and_what_it_resolved_to(
        self, client: AsyncClient
    ) -> None:
        async with captured_wide_event() as event:
            with patch(f"{_ENDPOINT}.get_public_view", AsyncMock(return_value=_VIEW)):
                await client.get(f"{BASE}/{SLUG}")

        assert event["short_link"] == {
            "operation": "resolve",
            "slug_hash": hash_short_link_slug(SLUG),
            "target_type": "todo_deliverable",
        }

    @pytest.mark.asyncio
    async def test_unknown_slug_is_404(self, client: AsyncClient) -> None:
        with patch(f"{_ENDPOINT}.get_public_view", AsyncMock(return_value=None)):
            response = await client.get(f"{BASE}/{SLUG}")

        assert response.status_code == 404
        assert response.json()["message"] == "Short link not found"


class TestResolveStorageOutage:
    @pytest.mark.asyncio
    async def test_workspace_storage_offline_is_503_not_500(self, client: AsyncClient) -> None:
        """A session-artifact link while storage is down is a retryable outage, not a crash."""
        with patch(
            f"{_ENDPOINT}.get_public_view",
            AsyncMock(side_effect=JuiceFSUnavailable("mount missing")),
        ):
            response = await client.get(f"{BASE}/{SLUG}")

        assert response.status_code == 503
        assert response.json()["message"] == "Workspace storage offline"


class TestShortLinkFile:
    """Tests for GET /l/{slug}/file."""

    @pytest.mark.asyncio
    async def test_a_slug_without_a_file_is_404(self, client: AsyncClient) -> None:
        with patch(f"{_ENDPOINT}.get_public_file", AsyncMock(return_value=None)) as lookup:
            response = await client.get(f"{BASE}/{SLUG}/file")

        assert response.status_code == 404
        assert response.json()["message"] == "Short link not found"
        lookup.assert_awaited_once_with(SLUG)

    @pytest.mark.asyncio
    async def test_workspace_storage_offline_is_503_not_500(self, client: AsyncClient) -> None:
        with patch(
            f"{_ENDPOINT}.get_public_file",
            AsyncMock(side_effect=JuiceFSUnavailable("mount missing")),
        ):
            response = await client.get(f"{BASE}/{SLUG}/file")

        assert response.status_code == 503
        assert response.json()["message"] == "Workspace storage offline"

    @pytest.mark.asyncio
    async def test_the_wide_event_names_the_slug_hash(self, client: AsyncClient) -> None:
        async with captured_wide_event() as event:
            with patch(f"{_ENDPOINT}.get_public_file", AsyncMock(return_value=None)):
                await client.get(f"{BASE}/{SLUG}/file")

        assert event["short_link"] == {
            "operation": "file",
            "slug_hash": hash_short_link_slug(SLUG),
        }

    @pytest.mark.asyncio
    async def test_the_file_is_sandboxed_and_never_cached(
        self, client: AsyncClient, tmp_path
    ) -> None:
        page = tmp_path / "report.html"
        page.write_text("<script>alert(1)</script>")
        with patch(f"{_ENDPOINT}.get_public_file", AsyncMock(return_value=page)):
            response = await client.get(f"{BASE}/{SLUG}/file")

        assert response.status_code == 200
        assert response.headers["content-security-policy"] == "sandbox"
        assert response.headers["cache-control"] == "no-store"
        assert "attachment" in response.headers["content-disposition"]


class TestCreateShortLink:
    """Tests for POST /l."""

    @pytest.mark.asyncio
    async def test_a_target_the_caller_does_not_own_is_never_minted(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(f"{_ENDPOINT}.project_target", AsyncMock(return_value=None)),
            patch(f"{_ENDPOINT}.share_short_link", AsyncMock()) as mint,
        ):
            response = await client.post(
                BASE, json={"target_type": "workflow_run", "target_id": "exec-of-someone-else"}
            )

        assert response.status_code == 404
        assert response.json()["message"] == "Target not found"
        mint.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_workspace_storage_offline_is_503_not_500(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{_ENDPOINT}.project_target",
                AsyncMock(side_effect=JuiceFSUnavailable("mount missing")),
            ),
            patch(f"{_ENDPOINT}.share_short_link", AsyncMock()) as mint,
        ):
            response = await client.post(
                BASE, json={"target_type": "session_artifact", "target_id": "conv-1/a.html"}
            )

        assert response.status_code == 503
        assert response.json()["message"] == "Workspace storage offline"
        mint.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_owned_target_returns_its_link(self, client: AsyncClient) -> None:
        """Ownership is checked and the link minted for the caller, never another user."""
        with (
            patch(f"{_ENDPOINT}.project_target", AsyncMock(return_value=_VIEW)) as project,
            patch(
                f"{_ENDPOINT}.share_short_link",
                AsyncMock(return_value=f"https://heygaia.link/{SLUG}"),
            ) as mint,
        ):
            async with captured_wide_event() as event:
                response = await client.post(
                    BASE, json={"target_type": "todo_deliverable", "target_id": "t1"}
                )

        assert response.status_code == 200
        assert response.json() == {"url": f"https://heygaia.link/{SLUG}"}
        project.assert_awaited_once_with(TODO, FAKE_USER.user_id, "t1")
        mint.assert_awaited_once_with(FAKE_USER.user_id, TODO, "t1")
        assert event["user"] == {"id": FAKE_USER.user_id}
        assert event["short_link"] == {"operation": "create", "target_type": "todo_deliverable"}


class TestPathEscapingTarget:
    @pytest.mark.asyncio
    async def test_a_target_id_escaping_the_artifacts_root_is_404_not_500(
        self, client: AsyncClient, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Runs the real projection and storage containment check over a tmp mount."""
        monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(tmp_path))
        monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: True)
        with patch(f"{_ENDPOINT}.share_short_link", AsyncMock()) as mint:
            response = await client.post(
                BASE,
                json={"target_type": "session_artifact", "target_id": "conv-1/../../../etc"},
            )

        assert response.status_code == 404
        mint.assert_not_awaited()


class TestStopSharing:
    """Tests for POST /l/unshare."""

    @pytest.mark.asyncio
    async def test_the_owner_stops_sharing_their_target(self, client: AsyncClient) -> None:
        with patch(f"{_ENDPOINT}.stop_sharing", AsyncMock(return_value=True)) as stop:
            async with captured_wide_event() as event:
                response = await client.post(
                    f"{BASE}/unshare",
                    json={"target_type": "session_artifact", "target_id": "conv-1/a.html"},
                )

        assert response.status_code == 204
        stop.assert_awaited_once_with(
            FAKE_USER.user_id, ShortLinkTargetType.SESSION_ARTIFACT, "conv-1/a.html"
        )
        assert event["user"] == {"id": FAKE_USER.user_id}
        assert event["short_link"] == {
            "operation": "stop_sharing",
            "target_type": "session_artifact",
            "revoked": True,
        }

    @pytest.mark.asyncio
    async def test_a_target_with_nothing_shared_is_still_204(self, client: AsyncClient) -> None:
        """Stopping is idempotent: the target ends up unshared either way."""
        with patch(f"{_ENDPOINT}.stop_sharing", AsyncMock(return_value=False)):
            response = await client.post(
                f"{BASE}/unshare", json={"target_type": "workflow_run", "target_id": "exec-1"}
            )

        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_an_unknown_target_type_is_422(self, client: AsyncClient) -> None:
        with patch(f"{_ENDPOINT}.stop_sharing", AsyncMock()) as stop:
            response = await client.post(
                f"{BASE}/unshare", json={"target_type": "nope", "target_id": "x"}
            )

        assert response.status_code == 422
        stop.assert_not_awaited()


class TestSlugNeverLoggedInPlaintext:
    """The slug is a working capability: the request log records the route template."""

    @pytest.mark.asyncio
    async def test_a_404_logs_the_route_template_not_the_slug(self, client: AsyncClient) -> None:
        with patch(f"{_ENDPOINT}.get_public_view", AsyncMock(return_value=None)):
            async with captured_wide_event() as event:
                await client.get(f"{BASE}/{SLUG}")

        assert SLUG not in str(event)
        assert [w["path"] for w in event["warnings"]] == [f"{BASE}/{{slug}}"]

    @pytest.mark.asyncio
    async def test_a_405_refused_before_the_route_runs_never_logs_the_slug(
        self, client: AsyncClient
    ) -> None:
        async with captured_wide_event() as event:
            response = await client.post(f"{BASE}/{SLUG}/file")

        assert response.status_code == 405
        assert SLUG not in str(event)
        assert [w["path"] for w in event["warnings"]] == [f"{BASE}/{{slug}}/file"]
