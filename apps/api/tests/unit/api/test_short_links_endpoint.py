"""The short-link routes' HTTP contract: who the viewer is, what is logged, and how input is refused.

The service behind each route runs for real over Mongo in
tests/integration/real/test_links_real.py; here it is mocked at the route's
import so the request shape, status codes and log fields are pinned alone.
"""

from typing import Final
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import AsyncClient
import pytest

from app.api.v1.dependencies.oauth_dependencies import get_optional_user
from app.models.openui_artifact_models import ArtifactKind, OpenUIArtifact
from app.models.short_link_models import (
    LinkDenial,
    LinkViewer,
    LinkViewerKind,
    ShortLink,
    ShortLinkTargetType,
)
from app.services.links.errors import LinkDeniedError
from app.services.storage import JuiceFSUnavailable
from app.utils.log_identifiers import hash_short_link_slug
from tests.conftest import FAKE_USER
from tests.helpers import captured_wide_event

BASE = "/api/v1/l"
SLUG = "abcdefghijk"
TODO: Final = ShortLinkTargetType.TODO_DELIVERABLE
_ENDPOINT = "app.api.v1.endpoints.short_links"
_LINK = ShortLink(slug=SLUG, user_id="owner", target_type=TODO, target_id="t1")


@pytest.fixture
def known_slug():
    with patch(f"{_ENDPOINT}.get_link", AsyncMock(return_value=_LINK)) as get:
        yield get


@pytest.fixture
def no_lockout():
    with (
        patch(f"{_ENDPOINT}.abuse.refuse_when_locked_out", AsyncMock()),
        patch(f"{_ENDPOINT}.abuse.record_miss", AsyncMock()) as miss,
    ):
        yield miss


class TestRecordOpen:
    """POST /l/{slug}/opened, which the viewer's browser sends once the page shows."""

    async def test_a_signed_out_viewer_is_counted_by_address_and_browser(
        self, unauthed_client: AsyncClient, known_slug: AsyncMock
    ) -> None:
        with patch(
            f"{_ENDPOINT}.record_open", AsyncMock(return_value=LinkViewerKind.RECIPIENT)
        ) as record:
            async with captured_wide_event() as event:
                response = await unauthed_client.post(
                    f"{BASE}/{SLUG}/opened", headers={"user-agent": "Safari/605"}
                )

        assert response.status_code == 204
        ((link, viewer), _) = record.await_args
        assert link == _LINK
        assert viewer == LinkViewer(
            user_id=None, email=None, ip="127.0.0.1", user_agent="Safari/605"
        )
        assert event["short_link"] == {
            "operation": "opened",
            "slug_hash": hash_short_link_slug(SLUG),
            "viewer_kind": "recipient",
        }
        assert SLUG not in str(event)

    async def test_a_signed_in_viewer_is_named_with_their_email(
        self, client: AsyncClient, test_app: FastAPI, known_slug: AsyncMock
    ) -> None:
        test_app.dependency_overrides[get_optional_user] = lambda: FAKE_USER
        try:
            with patch(
                f"{_ENDPOINT}.record_open", AsyncMock(return_value=LinkViewerKind.OWNER)
            ) as record:
                response = await client.post(f"{BASE}/{SLUG}/opened")
        finally:
            del test_app.dependency_overrides[get_optional_user]

        assert response.status_code == 204
        ((_, viewer), _) = record.await_args
        assert (viewer.user_id, viewer.email) == (FAKE_USER.user_id, FAKE_USER.email)

    async def test_a_denial_answers_with_its_code(
        self, unauthed_client: AsyncClient, known_slug: AsyncMock
    ) -> None:
        denied = LinkDeniedError.for_denial(LinkDenial.EXPIRED)
        with patch(f"{_ENDPOINT}.record_open", AsyncMock(side_effect=denied)):
            response = await unauthed_client.post(f"{BASE}/{SLUG}/opened")

        assert response.status_code == 410
        assert response.json()["code"] == "link_expired"

    async def test_a_viewer_sending_no_user_agent_is_counted_with_an_empty_one(
        self, unauthed_client: AsyncClient, known_slug: AsyncMock
    ) -> None:
        del unauthed_client.headers["user-agent"]
        with patch(
            f"{_ENDPOINT}.record_open", AsyncMock(return_value=LinkViewerKind.RECIPIENT)
        ) as record:
            await unauthed_client.post(f"{BASE}/{SLUG}/opened")

        ((_, viewer), _) = record.await_args
        assert viewer.user_agent == ""


class TestResolve:
    async def test_an_unknown_slug_counts_toward_the_lockout(
        self, unauthed_client: AsyncClient, no_lockout: AsyncMock
    ) -> None:
        with patch(f"{_ENDPOINT}.get_link", AsyncMock(return_value=None)):
            response = await unauthed_client.get(f"{BASE}/{SLUG}")

        assert response.status_code == 404
        assert response.json()["code"] == "link_not_found"
        no_lockout.assert_awaited_once_with("127.0.0.1", SLUG)

    async def test_a_forbidden_viewer_learns_only_who_they_are_signed_in_as(
        self, unauthed_client: AsyncClient, known_slug: AsyncMock, no_lockout: AsyncMock
    ) -> None:
        denied = LinkDeniedError.for_denial(LinkDenial.FORBIDDEN, signed_in_as="me@example.com")
        with patch(f"{_ENDPOINT}.resolve", AsyncMock(side_effect=denied)):
            response = await unauthed_client.get(f"{BASE}/{SLUG}")

        assert response.status_code == 403
        assert response.json()["code"] == "link_forbidden"
        assert response.json()["signed_in_as"] == "me@example.com"
        no_lockout.assert_not_awaited()


class TestShare:
    async def test_workspace_storage_offline_is_503_not_500(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.services.links.targets.session_artifact.stat_artifact",
                AsyncMock(side_effect=JuiceFSUnavailable("down")),
            ),
            patch(
                "app.services.links.service.short_link_repository.get_live_for_target",
                AsyncMock(return_value=None),
            ),
        ):
            response = await client.post(
                BASE, json={"target_type": "session_artifact", "target_id": "conv-1/a.html"}
            )

        assert response.status_code == 503
        assert response.json()["code"] == "workspace_storage_offline"

    async def test_a_target_the_caller_does_not_own_is_never_minted(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(
                "app.services.links.targets.todo_deliverable.todo_repository.get",
                AsyncMock(return_value=None),
            ) as read,
            patch("app.services.links.service.short_link_repository") as repo,
        ):
            repo.get_live_for_target = AsyncMock(return_value=None)
            repo.create = AsyncMock()
            response = await client.post(BASE, json={"target_type": TODO.value, "target_id": "t1"})

        assert response.status_code == 404
        read.assert_awaited_once_with("t1", user_id=FAKE_USER.user_id)
        repo.create.assert_not_awaited()

    async def test_an_unknown_setting_is_422(self, client: AsyncClient) -> None:
        response = await client.post(
            BASE,
            json={"target_type": TODO.value, "target_id": "t1", "settings": {"acess": "public"}},
        )
        assert response.status_code == 422

    async def test_a_naive_expiry_is_422(self, client: AsyncClient) -> None:
        response = await client.patch(f"{BASE}/{SLUG}", json={"expires_at": "2030-01-01T00:00:00"})
        assert response.status_code == 422

    async def test_a_grantee_that_is_no_email_is_422(self, client: AsyncClient) -> None:
        response = await client.patch(f"{BASE}/{SLUG}", json={"grantees": ["not-an-email"]})
        assert response.status_code == 422


class TestShareState:
    async def test_the_state_route_is_not_resolved_as_a_slug(self, client: AsyncClient) -> None:
        with patch(f"{_ENDPOINT}.live_share_link", AsyncMock(return_value=None)) as live:
            response = await client.get(
                f"{BASE}/state", params={"target_type": TODO.value, "target_id": "t1"}
            )

        assert response.status_code == 200
        assert response.json() == {"link": None}
        live.assert_awaited_once_with(FAKE_USER.user_id, TODO, "t1")

    async def test_a_missing_target_is_422(self, client: AsyncClient) -> None:
        response = await client.get(f"{BASE}/state", params={"target_type": "briefing"})
        assert response.status_code == 422


class TestSlugNeverLoggedInPlaintext:
    async def test_a_404_logs_the_route_template_not_the_slug(
        self, client: AsyncClient, no_lockout: AsyncMock
    ) -> None:
        with patch(f"{_ENDPOINT}.get_link", AsyncMock(return_value=None)):
            async with captured_wide_event() as event:
                await client.get(f"{BASE}/{SLUG}")

        assert SLUG not in str(event)
        assert [w["path"] for w in event["warnings"]] == [f"{BASE}/{{slug}}"]

    async def test_a_405_refused_before_the_route_runs_never_logs_the_slug(
        self, client: AsyncClient
    ) -> None:
        async with captured_wide_event() as event:
            response = await client.put(f"{BASE}/{SLUG}/download")

        assert response.status_code == 405
        assert SLUG not in str(event)
        assert [w["path"] for w in event["warnings"]] == [f"{BASE}/{{slug}}/download"]

    async def test_a_content_id_is_masked_too(self, client: AsyncClient) -> None:
        cid = "abcdefghijklmnopqrstuvwxyz"
        async with captured_wide_event() as event:
            response = await client.get(f"/api/v1/usercontent/{cid}")

        assert response.status_code == 404
        assert cid not in str(event)


class TestShortLinkPdf:
    async def test_a_link_the_viewer_may_open_serves_its_pdf(
        self, unauthed_client: AsyncClient, known_slug: AsyncMock
    ) -> None:
        link = _LINK.model_copy(update={"target_type": ShortLinkTargetType.OPENUI_ARTIFACT})
        artifact = OpenUIArtifact(
            id="t1",
            user_id="owner",
            kind=ArtifactKind.REPORT,
            title="Q3 plan",
            program="p",
            brief_hash="h",
            model="gpt-6-luna",
        )
        with (
            patch(f"{_ENDPOINT}.openable_link", AsyncMock(return_value=link)) as openable,
            patch(
                f"{_ENDPOINT}.owner_artifact_pdf", AsyncMock(return_value=(artifact, b"%PDF-1.7"))
            ) as export,
        ):
            response = await unauthed_client.get(f"{BASE}/{SLUG}/pdf")

        assert response.status_code == 200
        assert response.content == b"%PDF-1.7"
        assert response.headers["content-disposition"] == 'attachment; filename="Q3 plan.pdf"'
        assert openable.await_args.args[2] is ShortLinkTargetType.OPENUI_ARTIFACT
        export.assert_awaited_once_with("owner", "t1")

    async def test_a_gated_link_refuses_a_signed_out_viewer(
        self, unauthed_client: AsyncClient, known_slug: AsyncMock
    ) -> None:
        denied = LinkDeniedError.for_denial(LinkDenial.SIGN_IN_REQUIRED)
        with (
            patch(f"{_ENDPOINT}.openable_link", AsyncMock(side_effect=denied)),
            patch(f"{_ENDPOINT}.owner_artifact_pdf", AsyncMock()) as export,
        ):
            response = await unauthed_client.get(f"{BASE}/{SLUG}/pdf")

        assert response.status_code == 401
        export.assert_not_awaited()
