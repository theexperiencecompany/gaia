"""Tests for app/api/v1/endpoints/short_links.py"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.models.short_link_models import PublicTodoDeliverable, ShortLinkTargetType

# routes.py mounts the short-links router at its own "/l" prefix.
BASE = "/api/v1/l"

_ENDPOINT = "app.api.v1.endpoints.short_links"


class TestResolveShortLink:
    """Tests for GET /l/{slug}."""

    @pytest.mark.asyncio
    async def test_resolved_view_is_never_cached(self, client: AsyncClient) -> None:
        """A capability URL can be revoked at any moment; a cached 200 in a
        browser or an intermediary would keep serving content the owner has
        already taken back."""
        view = PublicTodoDeliverable(
            target_type=ShortLinkTargetType.TODO_DELIVERABLE,
            title="Q3 plan",
            completed=True,
            content="body",
        )
        with patch(f"{_ENDPOINT}.get_public_view", AsyncMock(return_value=view)):
            response = await client.get(f"{BASE}/abcdefghijk")

        assert response.status_code == 200
        assert response.json() == view.model_dump(mode="json")
        assert response.headers["cache-control"] == "no-store"

    @pytest.mark.asyncio
    async def test_unknown_slug_is_404(self, client: AsyncClient) -> None:
        with patch(f"{_ENDPOINT}.get_public_view", AsyncMock(return_value=None)):
            response = await client.get(f"{BASE}/abcdefghijk")

        assert response.status_code == 404


class TestShortLinkFile:
    """Tests for GET /l/{slug}/file."""

    @pytest.mark.asyncio
    async def test_a_slug_without_a_file_is_404(self, client: AsyncClient) -> None:
        with patch(f"{_ENDPOINT}.get_public_file", AsyncMock(return_value=None)):
            response = await client.get(f"{BASE}/abcdefghijk/file")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_the_file_is_sandboxed_and_never_cached(
        self, client: AsyncClient, tmp_path
    ) -> None:
        page = tmp_path / "report.html"
        page.write_text("<script>alert(1)</script>")
        with patch(f"{_ENDPOINT}.get_public_file", AsyncMock(return_value=page)):
            response = await client.get(f"{BASE}/abcdefghijk/file")

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
            patch(f"{_ENDPOINT}.get_or_create_short_link", AsyncMock()) as mint,
        ):
            response = await client.post(
                BASE, json={"target_type": "workflow_run", "target_id": "exec-of-someone-else"}
            )

        assert response.status_code == 404
        mint.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_owned_target_returns_its_link(self, client: AsyncClient) -> None:
        view = PublicTodoDeliverable(
            target_type=ShortLinkTargetType.TODO_DELIVERABLE,
            title="t",
            completed=False,
            content="",
        )
        with (
            patch(f"{_ENDPOINT}.project_target", AsyncMock(return_value=view)),
            patch(
                f"{_ENDPOINT}.get_or_create_short_link",
                AsyncMock(return_value="https://heygaia.link/abcdefghijk"),
            ),
        ):
            response = await client.post(
                BASE, json={"target_type": "todo_deliverable", "target_id": "t1"}
            )

        assert response.status_code == 200
        assert response.json() == {"url": "https://heygaia.link/abcdefghijk"}
