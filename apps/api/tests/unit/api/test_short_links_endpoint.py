"""The short-link routes' HTTP contract: who the viewer is, what is logged, and how input is refused.

The service behind each route runs for real over Mongo in
tests/integration/real/test_links_real.py; here it is mocked at the route's
import so the request shape, status codes and log fields are pinned alone.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
import ipaddress
from typing import Final
from unittest.mock import AsyncMock, patch
import uuid

from fastapi import FastAPI
from httpx import AsyncClient
import pytest

from app.api.v1.dependencies.oauth_dependencies import get_optional_user
from app.api.v1.middleware.rate_limiter import limiter
from app.config.settings import settings
from app.constants.http import INTERNAL_CALLER_HEADER, VIEWER_IP_HEADER
from app.constants.short_links import DOWNLOAD_RATE_LIMIT, PDF_EXPORT_RATE_LIMIT
from app.models.openui_artifact_models import ArtifactKind, OpenUIArtifact
from app.models.short_link_models import (
    LinkAccess,
    LinkDenial,
    LinkEnvelope,
    LinkSettings,
    LinkSnapshot,
    LinkViewer,
    PublicTodoDeliverable,
    RecordTarget,
    RenderMode,
    ShortLink,
    ShortLinkTargetType,
    WorkspaceFileTarget,
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
_OPENUI_TARGET = "app.services.links.targets.openui_artifact"
TODO_T = RecordTarget(type=TODO, id="t1")
TODO_JSON = {"type": TODO.value, "id": "t1"}
FILE_JSON = {"type": "workspace_file", "conversation_id": "conv-1", "path": "a/b.html"}
_LINK = ShortLink(slug=SLUG, user_id="owner", target=TODO_T)
_SIGNED_OUT = LinkViewer(user_id=None, email=None, ip="127.0.0.1", user_agent="Safari/605")
_EXPIRES = datetime(2030, 1, 1, tzinfo=UTC)
_SHARED = _LINK.model_copy(
    update={"access": LinkAccess.PEOPLE, "grantees": ["a@example.com"], "expires_at": _EXPIRES}
)
_SHARED_JSON = {
    "url": f"{settings.SHORTLINK_BASE_URL}/{SLUG}",
    "slug": SLUG,
    "access": "people",
    "grantees": ["a@example.com"],
    "expires_at": "2030-01-01T00:00:00Z",
    "content_max_access": None,
}


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


_ENVELOPE = LinkEnvelope(
    access=LinkAccess.UNLISTED,
    target_type=TODO,
    view=PublicTodoDeliverable(target_type=TODO, title="Plan", completed=True, content="Done"),
    content=None,
    downloadable=False,
    is_owner=False,
    owner_target=None,
)


class TestRecordOpen:
    """POST /l/{slug}/opened: the viewer's browser opens the link once the page shows."""

    async def test_a_signed_out_viewer_gets_the_view_counted_by_address_and_browser(
        self, unauthed_client: AsyncClient, no_lockout: AsyncMock, known_slug: AsyncMock
    ) -> None:
        with patch(f"{_ENDPOINT}.record_open", AsyncMock(return_value=_ENVELOPE)) as record:
            async with captured_wide_event() as event:
                response = await unauthed_client.post(
                    f"{BASE}/{SLUG}/opened", headers={"user-agent": "Safari/605"}
                )

        assert response.status_code == 200
        assert response.json() == _ENVELOPE.model_dump(mode="json")
        assert response.headers["cache-control"] == "private, no-store"
        known_slug.assert_awaited_once_with(SLUG)
        ((link, viewer), _) = record.await_args
        assert link == _LINK
        assert viewer == _SIGNED_OUT
        assert event["short_link"] == {
            "operation": "opened",
            "slug_hash": hash_short_link_slug(SLUG),
        }
        assert SLUG not in str(event)

    async def test_a_signed_in_viewer_is_named_with_their_email(
        self, client: AsyncClient, test_app: FastAPI, no_lockout: AsyncMock, known_slug: AsyncMock
    ) -> None:
        test_app.dependency_overrides[get_optional_user] = lambda: FAKE_USER
        try:
            with patch(f"{_ENDPOINT}.record_open", AsyncMock(return_value=_ENVELOPE)) as record:
                response = await client.post(f"{BASE}/{SLUG}/opened")
        finally:
            del test_app.dependency_overrides[get_optional_user]

        assert response.status_code == 200
        ((_, viewer), _) = record.await_args
        assert (viewer.user_id, viewer.email) == (FAKE_USER.user_id, FAKE_USER.email)
        assert viewer.signed_in_as == FAKE_USER.email

    async def test_a_denial_answers_with_its_code(
        self, unauthed_client: AsyncClient, no_lockout: AsyncMock, known_slug: AsyncMock
    ) -> None:
        denied = LinkDeniedError.for_denial(LinkDenial.EXPIRED)
        with patch(f"{_ENDPOINT}.record_open", AsyncMock(side_effect=denied)):
            response = await unauthed_client.post(f"{BASE}/{SLUG}/opened")

        assert response.status_code == 410
        assert response.json()["code"] == "link_expired"

    async def test_an_unknown_slug_counts_toward_the_lockout(
        self, unauthed_client: AsyncClient, no_lockout: AsyncMock
    ) -> None:
        with patch(f"{_ENDPOINT}.get_link", AsyncMock(return_value=None)):
            response = await unauthed_client.post(f"{BASE}/{SLUG}/opened")

        assert (response.status_code, response.json()["code"]) == (404, "link_not_found")
        no_lockout.assert_awaited_once_with("127.0.0.1", SLUG)

    async def test_a_viewer_sending_no_user_agent_is_counted_with_an_empty_one(
        self, unauthed_client: AsyncClient, no_lockout: AsyncMock, known_slug: AsyncMock
    ) -> None:
        del unauthed_client.headers["user-agent"]
        with patch(f"{_ENDPOINT}.record_open", AsyncMock(return_value=_ENVELOPE)) as record:
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


class TestResolveOpens:
    async def test_an_open_link_answers_with_its_envelope_uncached(
        self, unauthed_client: AsyncClient, known_slug: AsyncMock
    ) -> None:
        with (
            patch(f"{_ENDPOINT}.abuse.refuse_when_locked_out", AsyncMock()) as lockout,
            patch(f"{_ENDPOINT}.abuse.record_miss", AsyncMock()) as miss,
            patch(f"{_ENDPOINT}.resolve", AsyncMock(return_value=_ENVELOPE)) as resolve,
        ):
            async with captured_wide_event() as event:
                response = await unauthed_client.get(
                    f"{BASE}/{SLUG}", headers={"user-agent": "Safari/605"}
                )

        assert response.status_code == 200
        assert response.json() == _ENVELOPE.model_dump(mode="json")
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["vary"] == "Cookie"
        lockout.assert_awaited_once_with("127.0.0.1")
        known_slug.assert_awaited_once_with(SLUG)
        miss.assert_not_awaited()
        resolve.assert_awaited_once_with(_LINK, _SIGNED_OUT)
        assert event["short_link"] == {
            "operation": "resolve",
            "slug_hash": hash_short_link_slug(SLUG),
            "target_type": "todo_deliverable",
            "access": "unlisted",
        }

    async def test_a_signed_in_viewer_opens_as_themself(
        self, client: AsyncClient, test_app: FastAPI, known_slug: AsyncMock, no_lockout: AsyncMock
    ) -> None:
        test_app.dependency_overrides[get_optional_user] = lambda: FAKE_USER
        denied = LinkDeniedError.for_denial(LinkDenial.FORBIDDEN)
        try:
            with patch(f"{_ENDPOINT}.resolve", AsyncMock(side_effect=denied)) as resolve:
                await client.get(f"{BASE}/{SLUG}")
        finally:
            del test_app.dependency_overrides[get_optional_user]

        ((_, viewer), _) = resolve.await_args
        assert viewer.user_id == FAKE_USER.user_id


class TestShare:
    async def test_sharing_mints_with_the_given_settings_and_answers_with_the_link(
        self, client: AsyncClient
    ) -> None:
        with patch(f"{_ENDPOINT}.share", AsyncMock(return_value=_SHARED)) as share:
            async with captured_wide_event() as event:
                response = await client.post(
                    BASE,
                    json={
                        "target": TODO_JSON,
                        "settings": {"access": "people", "grantees": ["a@example.com"]},
                    },
                )

        assert response.status_code == 200
        assert response.json() == _SHARED_JSON
        share.assert_awaited_once_with(
            FAKE_USER.user_id,
            TODO_T,
            LinkSettings(access=LinkAccess.PEOPLE, grantees=["a@example.com"]),
        )
        assert event["user"] == {"id": FAKE_USER.user_id}
        assert event["short_link"] == {"operation": "create", "target_type": "todo_deliverable"}

    async def test_workspace_storage_offline_is_503_not_500(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.services.links.targets.workspace_file.stat_artifact",
                AsyncMock(side_effect=JuiceFSUnavailable("down")),
            ),
            patch(
                "app.services.links.service.short_link_repository.get_live_for_target",
                AsyncMock(return_value=None),
            ),
        ):
            response = await client.post(BASE, json={"target": FILE_JSON})

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
            response = await client.post(BASE, json={"target": TODO_JSON})

        assert response.status_code == 404
        read.assert_awaited_once_with("t1", user_id=FAKE_USER.user_id)
        repo.create.assert_not_awaited()

    async def test_an_unknown_setting_is_422(self, client: AsyncClient) -> None:
        response = await client.post(
            BASE,
            json={"target": TODO_JSON, "settings": {"acess": "public"}},
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
            response = await client.post(f"{BASE}/state", json={"target": TODO_JSON})

        assert response.status_code == 200
        assert response.json() == {"link": None}
        live.assert_awaited_once_with(FAKE_USER.user_id, TODO_T)

    async def test_a_workspace_file_is_read_by_its_conversation_and_path(
        self, client: AsyncClient
    ) -> None:
        with patch(f"{_ENDPOINT}.live_share_link", AsyncMock(return_value=None)) as live:
            response = await client.post(f"{BASE}/state", json={"target": FILE_JSON})

        assert response.status_code == 200
        live.assert_awaited_once_with(
            FAKE_USER.user_id,
            WorkspaceFileTarget(
                type=ShortLinkTargetType.WORKSPACE_FILE, conversation_id="conv-1", path="a/b.html"
            ),
        )

    async def test_a_shared_target_answers_with_its_live_link(self, client: AsyncClient) -> None:
        with patch(f"{_ENDPOINT}.live_share_link", AsyncMock(return_value=_SHARED)):
            async with captured_wide_event() as event:
                response = await client.post(f"{BASE}/state", json={"target": TODO_JSON})

        assert response.json() == {"link": _SHARED_JSON}
        assert event["user"] == {"id": FAKE_USER.user_id}
        assert event["short_link"] == {
            "operation": "share_state",
            "target_type": "todo_deliverable",
            "shared": True,
        }

    async def test_an_unshared_target_is_logged_as_not_shared(self, client: AsyncClient) -> None:
        with patch(f"{_ENDPOINT}.live_share_link", AsyncMock(return_value=None)):
            async with captured_wide_event() as event:
                await client.post(f"{BASE}/state", json={"target": TODO_JSON})

        assert event["short_link"]["shared"] is False

    @pytest.mark.parametrize(
        "target",
        [
            {"type": "briefing"},
            {"type": "workspace_file", "conversation_id": "conv-1"},
            {"type": "workspace_file", "conversation_id": "conv-1", "path": ""},
            {"type": "workspace_file", "id": "conv-1/a.html"},
            {"type": "workspace_file", "conversation_id": "../other-user", "path": "a.html"},
        ],
    )
    async def test_a_target_missing_its_fields_is_422(
        self, client: AsyncClient, target: dict[str, str]
    ) -> None:
        response = await client.post(f"{BASE}/state", json={"target": target})
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


class TestDownload:
    async def test_a_link_the_viewer_may_open_saves_its_file_as_an_attachment(
        self, unauthed_client: AsyncClient, known_slug: AsyncMock
    ) -> None:
        snapshot = LinkSnapshot(
            filename="q3.csv",
            mime="text/csv",
            size_bytes=3,
            render=RenderMode.TEXT,
            content_id="c" * 26,
        )
        # An expiry still ahead: the route reads the clock to know the link is live.
        link = _LINK.model_copy(update={"snapshot": snapshot, "expires_at": _EXPIRES})
        with (
            patch(f"{_ENDPOINT}.openable_link", AsyncMock(return_value=link)),
            patch(f"{_ENDPOINT}.read_snapshot", AsyncMock(return_value=b"a,b")) as read,
        ):
            response = await unauthed_client.get(f"{BASE}/{SLUG}/download")

        assert response.status_code == 200
        assert response.content == b"a,b"
        assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''q3.csv"
        read.assert_awaited_once_with("owner", "c" * 26)


class TestShortLinkPdf:
    async def test_a_link_the_viewer_may_open_serves_its_pdf(
        self, unauthed_client: AsyncClient, known_slug: AsyncMock
    ) -> None:
        link = _LINK.model_copy(
            update={"target": RecordTarget(type=ShortLinkTargetType.OPENUI_ARTIFACT, id="t1")}
        )
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
                f"{_OPENUI_TARGET}.owner_artifact_pdf",
                AsyncMock(return_value=(artifact, b"%PDF-1.7")),
            ) as export,
        ):
            response = await unauthed_client.get(
                f"{BASE}/{SLUG}/pdf", headers={"user-agent": "Safari/605"}
            )

        assert response.status_code == 200
        known_slug.assert_awaited_once_with(SLUG)
        assert openable.await_args.args == (_LINK, _SIGNED_OUT)
        assert response.content == b"%PDF-1.7"
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"] == 'attachment; filename="Q3 plan.pdf"'
        export.assert_awaited_once_with("owner", "t1")

    async def test_a_type_that_prints_no_file_has_no_pdf(
        self, unauthed_client: AsyncClient, known_slug: AsyncMock
    ) -> None:
        with patch(f"{_ENDPOINT}.openable_link", AsyncMock(return_value=_LINK)):
            response = await unauthed_client.get(f"{BASE}/{SLUG}/pdf")

        assert (response.status_code, response.json()["code"]) == (404, "link_not_found")

    async def test_a_signed_in_viewer_is_checked_as_themself(
        self, client: AsyncClient, test_app: FastAPI, known_slug: AsyncMock
    ) -> None:
        test_app.dependency_overrides[get_optional_user] = lambda: FAKE_USER
        denied = LinkDeniedError.for_denial(LinkDenial.FORBIDDEN)
        try:
            with patch(f"{_ENDPOINT}.openable_link", AsyncMock(side_effect=denied)) as openable:
                response = await client.get(f"{BASE}/{SLUG}/pdf")
        finally:
            del test_app.dependency_overrides[get_optional_user]

        assert response.status_code == 403
        assert openable.await_args.args[1].user_id == FAKE_USER.user_id

    async def test_a_gated_link_refuses_a_signed_out_viewer(
        self, unauthed_client: AsyncClient, known_slug: AsyncMock
    ) -> None:
        denied = LinkDeniedError.for_denial(LinkDenial.SIGN_IN_REQUIRED)
        with (
            patch(f"{_ENDPOINT}.openable_link", AsyncMock(side_effect=denied)),
            patch(f"{_OPENUI_TARGET}.owner_artifact_pdf", AsyncMock()) as export,
        ):
            response = await unauthed_client.get(f"{BASE}/{SLUG}/pdf")

        assert response.status_code == 401
        export.assert_not_awaited()


class TestFileRouteLimits:
    """The routes that hand out bytes with no sign-in are bounded per viewer."""

    @pytest.fixture
    def limited(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
        """Turn the limiter on for one viewer of its own, so no other run's counts reach it."""
        monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", "t0ken")
        viewer = str(ipaddress.IPv6Address(uuid.uuid4().int))
        limiter.enabled = True
        try:
            yield {INTERNAL_CALLER_HEADER: "t0ken", VIEWER_IP_HEADER: viewer}
        finally:
            limiter.enabled = False

    @pytest.mark.usefixtures("known_slug")
    @pytest.mark.parametrize(
        ("route", "limit"), [("download", DOWNLOAD_RATE_LIMIT), ("pdf", PDF_EXPORT_RATE_LIMIT)]
    )
    async def test_a_viewer_past_the_limit_is_refused(
        self, unauthed_client: AsyncClient, limited: dict[str, str], route: str, limit: str
    ) -> None:
        allowed = int(limit.split("/")[0])
        denied = LinkDeniedError.for_denial(LinkDenial.NOT_FOUND)
        with patch(f"{_ENDPOINT}.openable_link", AsyncMock(side_effect=denied)):
            codes = [
                (await unauthed_client.get(f"{BASE}/{SLUG}/{route}", headers=limited)).status_code
                for _ in range(allowed + 1)
            ]

        assert codes == [404] * allowed + [429]
