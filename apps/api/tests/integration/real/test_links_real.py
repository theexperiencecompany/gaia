"""heygaia.link end to end over REAL MongoDB and Redis: the real routes, service, registry and repositories.

Each test shares something through the owner routes, opens it as one viewer or
another, and reads the outcome back from Mongo and the snapshot store. Only the
viewer's session (a dependency override), the analytics capture and the
workspace file read (a tmp file standing in for JuiceFS) are replaced.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi import FastAPI
from httpx import AsyncClient, Response
from PIL import Image
import pytest

from app.agents.workspace.paths import detect_content_type
from app.api.v1.dependencies.oauth_dependencies import get_optional_user
from app.config.settings import settings
from app.constants.briefing import BriefingKind, EditionFamily
from app.constants.notifications import NotificationKind
from app.constants.short_links import MAX_RESOLVE_MISSES, TRUSTED_REPORTER_MIN_ACCOUNT_AGE_DAYS
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.openui_artifacts import openui_artifact_repository
from app.db.repositories.short_links import short_link_repository
from app.db.repositories.todos import todo_repository
from app.models.brief_document_models import BriefDelivery
from app.models.brief_payload_models import BriefingMood, BriefingPayload
from app.models.conversation_models import ConversationDocument
from app.models.openui_artifact_models import ArtifactKind, OpenUIArtifact
from app.models.short_link_models import (
    LinkAccess,
    LinkSettings,
    RecordTarget,
    ReportReason,
    RevokeReason,
    ShortLink,
    ShortLinkTargetType,
    WorkspaceFileTarget,
)
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.services.blob_store import LocalVolumeBlobStore
from app.services.briefing import store as brief_store
from app.services.links import abuse, content as link_content
from app.services.links.placeholders import link_placeholder, resolve_link_placeholders
from app.services.links.service import attach_link, revoke_all_links_for_user, share
from app.services.render.image import RenderedImage
from app.services.storage import ArtifactInfo
from shared.py.analytics import UserId
from tests.conftest import FAKE_USER

pytestmark = pytest.mark.service

OWNER = FAKE_USER
RECIPIENT = AuthenticatedUser(
    user_id="507f1f77bcf86cd799439022", email="friend@example.com", auth_provider="workos"
)
STRANGER = AuthenticatedUser(
    user_id="507f1f77bcf86cd799439033", email="someone@example.com", auth_provider="workos"
)
REPORTERS = [
    AuthenticatedUser(
        user_id=f"507f1f77bcf86cd7994390{n}", email=f"r{n}@example.com", auth_provider="workos"
    )
    for n in (41, 42, 43)
]
TODO = "todo_deliverable"
FILE = "workspace_file"
OPENUI = "openui_artifact"
ORIGIN_TEMPLATE = "http://{content_id}.u.test/api/v1/usercontent/{content_id}"
BROWSER = "Mozilla/5.0 (Macintosh) Safari/605.1.15"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


class Viewer:
    """Who the next request is from: None is signed out."""

    def __init__(self) -> None:
        self.user: AuthenticatedUser | None = None


@pytest.fixture
def viewer(test_app: FastAPI) -> Iterator[Viewer]:
    current = Viewer()
    test_app.dependency_overrides[get_optional_user] = lambda: current.user
    yield current
    test_app.dependency_overrides.pop(get_optional_user, None)


_COLLECTIONS = ("short_links", "link_reports", "todos", "artifacts", "conversations", "briefings")


@pytest.fixture(autouse=True)
async def _clean(mongo_db, real_redis) -> AsyncIterator[None]:
    for name in _COLLECTIONS:
        await mongo_db[name].delete_many({})
    from app.db.mongodb import indexes

    with patch.object(indexes, "get_async_collection", lambda name: mongo_db[name]):
        await indexes.create_short_link_indexes()
    yield
    for name in _COLLECTIONS:
        await mongo_db[name].delete_many({})


@pytest.fixture
def captured() -> Iterator[list[tuple[UserId, object]]]:
    """Every analytics event the link code captured, in order, with its dedupe when given."""
    events: list[tuple[UserId, object]] = []

    def record(user: UserId, event: object, *rest: object) -> None:
        events.append((user, event))

    with (
        patch("app.services.links.service.capture", side_effect=record),
        patch("app.services.links.content.capture", side_effect=record),
        patch("app.services.links.abuse.capture", side_effect=record),
    ):
        yield events


def _names(events: list[tuple[UserId, object]]) -> list[str]:
    return [type(event).__name__ for _, event in events]


@pytest.fixture
def store(tmp_path: Path) -> Iterator[LocalVolumeBlobStore]:
    volume = LocalVolumeBlobStore(tmp_path / "blobs")
    (tmp_path / "blobs").mkdir()
    with (
        patch("app.services.blob_store._is_mountpoint", return_value=True),
        patch.object(link_content, "link_content_store", return_value=volume),
    ):
        yield volume


@pytest.fixture
def content_origin(monkeypatch: pytest.MonkeyPatch, store: LocalVolumeBlobStore) -> None:
    monkeypatch.setattr(settings, "LINK_CONTENT_URL_TEMPLATE", ORIGIN_TEMPLATE)
    monkeypatch.setattr(settings, "LINK_CONTENT_SIGNING_KEY", "s" * 40)
    monkeypatch.setattr(settings, "SHORTLINK_BASE_URL", "https://heygaia.link")


class Workspace:
    """The owner's workspace files of conversation conv-1, as the workspace-file spec reads them."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, name: str, data: bytes) -> dict[str, str]:
        """Write a file and return its target as the API takes it."""
        (self.root / name).write_bytes(data)
        return {"type": FILE, "conversation_id": "conv-1", "path": name}


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Workspace]:
    root = tmp_path / "artifacts"
    root.mkdir()

    async def stat(_user: str, _conv: str, path: str) -> ArtifactInfo | None:
        file = root / path
        if not file.is_file():
            return None
        return ArtifactInfo(
            path=path,
            size_bytes=file.stat().st_size,
            mtime=0.0,
            content_type=detect_content_type(path),
        )

    async def resolve(_user: str, _conv: str, _role: str, path: str) -> Path:
        return root / path

    mod = "app.services.links.targets.workspace_file"
    with patch(f"{mod}.stat_artifact", stat), patch(f"{mod}.resolve_session_path", resolve):
        yield Workspace(root)


async def _artifact(conversation_id: str) -> str:
    artifact = await openui_artifact_repository.create(
        OpenUIArtifact(
            user_id=OWNER.user_id,
            conversation_id=conversation_id,
            kind=ArtifactKind.REPORT,
            title="Q3 revenue",
            program='root = Report("Q3 revenue", [])',
            brief_hash="b",
            model="m",
        )
    )
    return artifact.id


async def _todo(title: str = "Reply to Acme") -> str:
    return await _todo_for(OWNER, title)


async def _todo_for(owner: AuthenticatedUser, title: str = "Reply to Acme") -> str:
    todo = await todo_repository.create(TodoDocument(user_id=owner.user_id, title=title))
    return todo.id


def _rec(target_type: str, target_id: str) -> dict[str, str]:
    return {"type": target_type, "id": target_id}


async def _share(client: AsyncClient, target: dict[str, str], **link_settings: object) -> dict:
    body: dict[str, object] = {"target": target}
    if link_settings:
        body["settings"] = link_settings
    response = await client.post("/api/v1/l", json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def _open(client: AsyncClient, slug: str, **headers: str) -> Response:
    return await client.get(f"/api/v1/l/{slug}", headers={"user-agent": BROWSER, **headers})


async def _stored(slug: str) -> ShortLink:
    link = await short_link_repository.get_by_slug(slug)
    assert link is not None
    return link


class TestAccessLevels:
    async def test_owner_only_opens_for_the_owner_alone(
        self, client: AsyncClient, viewer: Viewer, captured: list
    ) -> None:
        todo_id = await _todo()
        link = await _share(client, _rec(TODO, todo_id), access="owner")
        slug = link["slug"]
        assert link["access"] == "owner"
        assert link["url"].endswith(f"/{slug}")

        viewer.user = OWNER
        owner_view = await _open(client, slug)
        viewer.user = None
        anonymous = await _open(client, slug)
        viewer.user = STRANGER
        stranger = await _open(client, slug)

        assert owner_view.status_code == 200
        assert owner_view.json()["is_owner"] is True
        assert owner_view.json()["owner_target"] == {"type": TODO, "id": todo_id}
        assert owner_view.headers["cache-control"] == "private, no-store"
        assert (anonymous.status_code, anonymous.json()["code"]) == (401, "link_sign_in_required")
        assert (stranger.status_code, stranger.json()["code"]) == (403, "link_forbidden")
        assert stranger.json()["signed_in_as"] == "someone@example.com"
        assert "title" not in stranger.text
        assert (await _stored(slug)).access is LinkAccess.OWNER
        # The page's server-side read is no viewer's open: only the browser's /opened counts a denial.
        assert _names(captured).count("ShortLinkDenied") == 0
        for denied_viewer in (None, STRANGER):
            viewer.user = denied_viewer
            opened = await client.post(f"/api/v1/l/{slug}/opened", headers={"user-agent": BROWSER})
            assert opened.status_code in (401, 403)
        assert _names(captured).count("ShortLinkDenied") == 2

    async def test_an_unlisted_link_opens_for_anyone_and_says_so(
        self, client: AsyncClient, viewer: Viewer
    ) -> None:
        slug = (await _share(client, _rec(TODO, await _todo())))["slug"]
        opened = await _open(client, slug)
        assert opened.status_code == 200
        assert opened.json()["access"] == "unlisted"
        assert opened.json()["downloadable"] is False
        assert opened.json()["target_type"] == TODO

    async def test_changing_access_takes_effect_on_the_next_open(
        self, client: AsyncClient, viewer: Viewer, captured: list
    ) -> None:
        slug = (await _share(client, _rec(TODO, await _todo())))["slug"]
        assert (await _open(client, slug)).status_code == 200

        changed = await client.patch(f"/api/v1/l/{slug}", json={"access": "owner"})

        assert changed.status_code == 200
        assert changed.json()["access"] == "owner"
        assert (await _open(client, slug)).status_code == 401
        access_changed = [
            event for _, event in captured if type(event).__name__ == "ShortLinkAccessChanged"
        ]
        assert len(access_changed) == 1
        assert (access_changed[0].from_access, access_changed[0].to_access) == ("unlisted", "owner")

    async def test_someone_elses_link_cannot_be_changed(
        self, client: AsyncClient, mongo_db
    ) -> None:
        slug = (await _share(client, _rec(TODO, await _todo())))["slug"]
        await mongo_db["short_links"].update_one(
            {"slug": slug}, {"$set": {"user_id": STRANGER.user_id}}
        )

        response = await client.patch(f"/api/v1/l/{slug}", json={"access": "public"})

        assert response.status_code == 404
        assert (await _stored(slug)).access is LinkAccess.UNLISTED


class TestRevokeRotateExpire:
    async def test_stopping_kills_the_link_and_gaia_attaches_no_new_one(
        self, client: AsyncClient, viewer: Viewer
    ) -> None:
        todo_id = await _todo()
        slug = (await _share(client, _rec(TODO, todo_id)))["slug"]

        stopped = await client.post("/api/v1/l/unshare", json={"target": _rec(TODO, todo_id)})

        assert stopped.json() == {"revoked": True}
        dead = await _open(client, slug)
        assert (dead.status_code, dead.json()["code"]) == (410, "link_revoked")
        assert (await _stored(slug)).revoked_reason is RevokeReason.OWNER
        assert (
            await attach_link(
                OWNER.user_id, RecordTarget(type=ShortLinkTargetType.TODO_DELIVERABLE, id=todo_id)
            )
            is None
        )

    async def test_the_owner_still_opens_what_they_stopped_sharing_or_rotated_away(
        self, client: AsyncClient, viewer: Viewer
    ) -> None:
        todo_id = await _todo()
        old = (await _share(client, _rec(TODO, todo_id)))["slug"]
        new = (await client.post(f"/api/v1/l/{old}/rotate")).json()["slug"]
        await client.post("/api/v1/l/unshare", json={"target": _rec(TODO, todo_id)})

        viewer.user = OWNER
        for slug in (old, new):
            opened = await _open(client, slug)
            assert opened.status_code == 200, opened.text
            assert (opened.json()["is_owner"], opened.json()["view"]["title"]) == (
                True,
                "Reply to Acme",
            )
        viewer.user = STRANGER
        assert (await _open(client, new)).json()["code"] == "link_revoked"

    async def test_the_owner_of_a_stopped_file_sees_its_card_but_never_its_deleted_bytes(
        self, client: AsyncClient, viewer: Viewer, workspace: Workspace, content_origin: None
    ) -> None:
        target = workspace.write("notes.md", b"# private")
        slug = (await _share(client, target))["slug"]
        await client.post("/api/v1/l/unshare", json={"target": target})

        viewer.user = OWNER
        opened = (await _open(client, slug)).json()

        assert (opened["view"]["filename"], opened["view"]["text"]) == ("notes.md", None)
        assert (opened["content"], opened["downloadable"]) == (None, False)
        assert (await client.post(f"/api/v1/l/{slug}/content-token")).status_code == 404
        assert (await client.get(f"/api/v1/l/{slug}/download")).status_code == 404

    async def test_rotation_moves_every_setting_to_a_new_url(
        self, client: AsyncClient, viewer: Viewer
    ) -> None:
        todo_id = await _todo()
        old = await _share(client, _rec(TODO, todo_id), access="owner")

        rotated = await client.post(f"/api/v1/l/{old['slug']}/rotate")

        new = rotated.json()
        assert rotated.status_code == 200
        assert new["slug"] != old["slug"]
        assert new["access"] == "owner"
        viewer.user = OWNER
        assert (await _open(client, new["slug"])).status_code == 200
        gone = await _open(client, old["slug"])
        assert (gone.status_code, gone.json()["code"]) == (410, "link_revoked")
        assert (await _stored(old["slug"])).revoked_reason is RevokeReason.ROTATED
        # GAIA hands over the new URL, not nothing.
        attached = await attach_link(
            OWNER.user_id, RecordTarget(type=ShortLinkTargetType.TODO_DELIVERABLE, id=todo_id)
        )
        assert attached is not None and attached.slug == new["slug"]

    async def test_an_expired_link_is_dead_and_sharing_again_mints_a_fresh_one(
        self, client: AsyncClient, viewer: Viewer, mongo_db
    ) -> None:
        todo_id = await _todo()
        slug = (await _share(client, _rec(TODO, todo_id)))["slug"]
        await mongo_db["short_links"].update_one(
            {"slug": slug}, {"$set": {"expires_at": datetime.now(UTC) - timedelta(minutes=1)}}
        )

        expired = await _open(client, slug)
        assert (expired.status_code, expired.json()["code"]) == (410, "link_expired")
        assert (
            await attach_link(
                OWNER.user_id, RecordTarget(type=ShortLinkTargetType.TODO_DELIVERABLE, id=todo_id)
            )
            is None
        )

        fresh = await _share(client, _rec(TODO, todo_id))

        assert fresh["slug"] != slug
        assert (await _open(client, fresh["slug"])).status_code == 200
        assert (await _stored(slug)).revoked_reason is RevokeReason.EXPIRED

    async def test_an_expiry_in_the_past_is_refused(self, client: AsyncClient) -> None:
        slug = (await _share(client, _rec(TODO, await _todo())))["slug"]
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        response = await client.patch(f"/api/v1/l/{slug}", json={"expires_at": past})
        assert (response.status_code, response.json()["code"]) == (422, "link_expiry_in_past")

    async def test_a_future_expiry_is_kept_and_reported(self, client: AsyncClient) -> None:
        slug = (await _share(client, _rec(TODO, await _todo())))["slug"]
        later = datetime.now(UTC) + timedelta(days=7)
        response = await client.patch(f"/api/v1/l/{slug}", json={"expires_at": later.isoformat()})
        assert response.status_code == 200
        stored = await _stored(slug)
        assert stored.expires_at is not None
        assert abs((stored.expires_at - later).total_seconds()) < 1

    async def test_a_deleted_target_says_so(
        self, client: AsyncClient, viewer: Viewer, mongo_db
    ) -> None:
        todo_id = await _todo()
        slug = (await _share(client, _rec(TODO, todo_id)))["slug"]
        await todo_repository.delete(todo_id, user_id=OWNER.user_id)

        response = await _open(client, slug)

        assert (response.status_code, response.json()["code"]) == (410, "link_target_deleted")

    async def test_an_unknown_slug_is_not_found(self, client: AsyncClient, viewer: Viewer) -> None:
        response = await _open(client, "Zz9Zz9Zz9Zz")
        assert (response.status_code, response.json()["code"]) == (404, "link_not_found")


class TestPreviewMeta:
    async def test_an_unlisted_link_previews_its_title(self, client: AsyncClient) -> None:
        slug = (await _share(client, _rec(TODO, await _todo("Q3 plan"))))["slug"]
        meta = await client.get(f"/api/v1/l/{slug}/meta")
        assert meta.json()["title"] == "Q3 plan"
        assert meta.json()["indexable"] is False
        assert meta.headers["cache-control"] == "public, max-age=300"

    async def test_a_public_link_is_indexable(self, client: AsyncClient) -> None:
        slug = (await _share(client, _rec(TODO, await _todo("Q3 plan")), access="public"))["slug"]
        assert (await client.get(f"/api/v1/l/{slug}/meta")).json()["indexable"] is True

    async def test_a_gated_link_previews_only_its_kind(self, client: AsyncClient) -> None:
        slug = (await _share(client, _rec(TODO, await _todo("Secret merger")), access="owner"))[
            "slug"
        ]
        meta = (await client.get(f"/api/v1/l/{slug}/meta")).json()
        assert meta["title"] == "Shared from GAIA"
        assert "Secret merger" not in str(meta)

    async def test_a_dead_link_discloses_nothing(self, client: AsyncClient) -> None:
        todo_id = await _todo("Secret merger")
        slug = (await _share(client, _rec(TODO, todo_id)))["slug"]
        await client.post("/api/v1/l/unshare", json={"target": _rec(TODO, todo_id)})
        meta = await client.get(f"/api/v1/l/{slug}/meta")
        assert meta.json() == {
            "live": False,
            "target_type": None,
            "access": None,
            "indexable": False,
            "title": "This link is no longer available",
            "description": "Ask the person who shared it for a new one.",
            "image_url": None,
        }
        assert meta.headers["cache-control"] == "public, max-age=60"


class TestOpens:
    async def test_only_a_recipient_counts_once_a_day(
        self, client: AsyncClient, viewer: Viewer, captured: list
    ) -> None:
        slug = (await _share(client, _rec(TODO, await _todo())))["slug"]
        captured.clear()

        viewer.user = OWNER
        as_owner = await client.post(f"/api/v1/l/{slug}/opened", headers={"user-agent": BROWSER})
        viewer.user = None
        await client.post(
            f"/api/v1/l/{slug}/opened", headers={"user-agent": "Slackbot-LinkExpanding 1.0"}
        )
        viewer.user = RECIPIENT
        as_recipient = await client.post(
            f"/api/v1/l/{slug}/opened", headers={"user-agent": BROWSER}
        )

        # One browser call both counts the open and tells the owner apart.
        assert (as_owner.json()["is_owner"], as_recipient.json()["is_owner"]) == (True, False)
        assert as_recipient.json()["view"]["title"] == "Reply to Acme"
        assert _names(captured) == ["ShortLinkOpened"]
        assert captured[0][1].viewer_signed_in is True
        assert captured[0][1].access == "unlisted"


class TestMissLockout:
    async def test_the_twenty_first_unknown_slug_locks_the_viewer_out(
        self, client: AsyncClient, viewer: Viewer
    ) -> None:
        live = (await _share(client, _rec(TODO, await _todo())))["slug"]
        statuses = [
            (await _open(client, f"miss{n:07d}")).status_code for n in range(MAX_RESOLVE_MISSES + 1)
        ]

        assert statuses[:MAX_RESOLVE_MISSES] == [404] * MAX_RESOLVE_MISSES
        assert statuses[MAX_RESOLVE_MISSES] == 429
        locked = await _open(client, live)
        assert (locked.status_code, locked.json()["code"]) == (429, "link_lookup_locked")

    async def test_the_same_unknown_slug_counts_once(
        self, client: AsyncClient, viewer: Viewer
    ) -> None:
        statuses = {
            (await _open(client, "samesamesam")).status_code for _ in range(MAX_RESOLVE_MISSES + 5)
        }
        assert statuses == {404}


class TestSharedFiles:
    async def test_html_is_framed_from_its_own_origin_and_never_on_the_api_host(
        self, client: AsyncClient, viewer: Viewer, workspace: Workspace, content_origin: None
    ) -> None:
        target = workspace.write("report.html", b"<h1>Q3</h1><script>draw()</script>")
        slug = (await _share(client, target))["slug"]

        envelope = (await _open(client, slug)).json()
        content = envelope["content"]
        assert content["render"] == "frame_active"
        assert envelope["view"]["text"] is None
        cid = content["content_id"]
        token = await client.post(f"/api/v1/l/{slug}/content-token")
        url = token.json()["content_url"]
        # The signed URL itself is fetched, so a redirect-inducing shape (a trailing slash) fails here.
        assert url.startswith(f"http://{cid}.u.test/api/v1/usercontent/{cid}?t=")
        path = url.removeprefix(f"http://{cid}.u.test")
        origin_host = f"{cid}.u.test"

        framed = await client.get(path, headers={"host": origin_host, "sec-fetch-dest": "iframe"})
        top_level = await client.get(
            path, headers={"host": origin_host, "sec-fetch-dest": "document"}
        )
        on_api_host = await client.get(path, headers={"sec-fetch-dest": "iframe"})
        no_token = await client.get(
            f"/api/v1/usercontent/{cid}", headers={"host": origin_host, "sec-fetch-dest": "iframe"}
        )

        assert framed.status_code == 200
        assert framed.content == b"<h1>Q3</h1><script>draw()</script>"
        assert framed.headers["content-security-policy"].startswith("sandbox allow-scripts")
        assert "set-cookie" not in framed.headers
        assert (top_level.status_code, top_level.headers["location"]) == (
            302,
            f"https://heygaia.link/{slug}",
        )
        assert on_api_host.status_code == 404
        assert (no_token.status_code, no_token.headers["location"]) == (
            302,
            f"https://heygaia.link/{slug}",
        )

    async def test_a_forwarded_host_counts_only_with_the_content_edge_token(
        self,
        client: AsyncClient,
        viewer: Viewer,
        workspace: Workspace,
        content_origin: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", "i" * 40)
        monkeypatch.setattr(settings, "LINK_CONTENT_EDGE_TOKEN", "e" * 40)
        slug = (await _share(client, workspace.write("n.png", PNG)))["slug"]
        url = (await client.post(f"/api/v1/l/{slug}/content-token")).json()["content_url"]
        cid = url.split("//", 1)[1].split(".", 1)[0]
        path = f"/api/v1/usercontent/{cid}?{url.split('?', 1)[1]}"
        forwarded = {"x-gaia-content-host": f"{cid}.u.test", "sec-fetch-dest": "image"}

        spoofed = await client.get(path, headers=forwarded)
        internal = await client.get(path, headers={**forwarded, "x-gaia-internal": "i" * 40})
        worker = await client.get(path, headers={**forwarded, "x-gaia-content-edge": "e" * 40})

        assert spoofed.status_code == 404
        assert internal.status_code == 404
        assert worker.status_code == 200
        assert worker.headers["content-type"] == "image/png"

    async def test_a_png_named_html_is_only_ever_a_download(
        self, client: AsyncClient, viewer: Viewer, workspace: Workspace, content_origin: None
    ) -> None:
        slug = (await _share(client, workspace.write("evil.html", PNG)))["slug"]

        envelope = (await _open(client, slug)).json()
        download = await client.get(f"/api/v1/l/{slug}/download")

        assert envelope["content"] is None
        assert envelope["view"]["content_type"] == "application/octet-stream"
        assert envelope["downloadable"] is True
        assert (await client.post(f"/api/v1/l/{slug}/content-token")).status_code == 404
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/octet-stream"
        assert download.headers["content-disposition"] == "attachment; filename*=UTF-8''evil.html"
        assert download.content == PNG

    async def test_without_a_content_origin_html_shows_as_source(
        self,
        client: AsyncClient,
        viewer: Viewer,
        workspace: Workspace,
        store: LocalVolumeBlobStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "LINK_CONTENT_URL_TEMPLATE", None)
        slug = (await _share(client, workspace.write("r.html", b"<b>hi</b>")))["slug"]

        envelope = (await _open(client, slug)).json()

        assert envelope["content"] is None
        assert envelope["view"]["text"] == "<b>hi</b>"
        assert (await client.post(f"/api/v1/l/{slug}/content-token")).status_code == 404

    async def test_the_link_serves_the_file_as_shared_even_after_it_changes_on_disk(
        self, client: AsyncClient, viewer: Viewer, workspace: Workspace, store: LocalVolumeBlobStore
    ) -> None:
        target = workspace.write("notes.md", b"# first")
        slug = (await _share(client, target))["slug"]
        workspace.write("notes.md", b"# edited by hand")

        assert (await _open(client, slug)).json()["view"]["text"] == "# first"

    async def test_an_agent_rewrite_moves_the_link_to_the_new_bytes_and_drops_the_old(
        self, client: AsyncClient, viewer: Viewer, workspace: Workspace, store: LocalVolumeBlobStore
    ) -> None:
        target = workspace.write("notes.md", b"# first")
        slug = (await _share(client, target))["slug"]
        first = (await _stored(slug)).snapshot
        assert first is not None and first.content_id is not None

        workspace.write("notes.md", b"# second")
        again = await attach_link(OWNER.user_id, WorkspaceFileTarget.model_validate(target))

        assert again is not None and again.slug == slug
        assert (await _open(client, slug)).json()["view"]["text"] == "# second"
        with pytest.raises(FileNotFoundError):
            await link_content.read_snapshot(OWNER.user_id, first.content_id)

    async def test_an_unchanged_file_is_not_republished(
        self, client: AsyncClient, workspace: Workspace, store: LocalVolumeBlobStore
    ) -> None:
        target = workspace.write("notes.md", b"# same")
        slug = (await _share(client, target))["slug"]
        before = (await _stored(slug)).snapshot

        await attach_link(OWNER.user_id, WorkspaceFileTarget.model_validate(target))

        assert (await _stored(slug)).snapshot == before

    async def test_stopping_deletes_the_bytes_and_the_origin_serves_nothing(
        self, client: AsyncClient, viewer: Viewer, workspace: Workspace, content_origin: None
    ) -> None:
        target = workspace.write("chart.png", PNG)
        slug = (await _share(client, target))["slug"]
        url = (await client.post(f"/api/v1/l/{slug}/content-token")).json()["content_url"]
        cid = url.split("//", 1)[1].split(".", 1)[0]

        await client.post("/api/v1/l/unshare", json={"target": target})

        served = await client.get(
            f"/api/v1/usercontent/{cid}?{url.split('?', 1)[1]}",
            headers={"host": f"{cid}.u.test", "sec-fetch-dest": "image"},
        )
        assert served.status_code == 404
        with pytest.raises(FileNotFoundError):
            await link_content.read_snapshot(OWNER.user_id, cid)

    async def test_rotation_keeps_the_bytes_for_the_new_url(
        self, client: AsyncClient, viewer: Viewer, workspace: Workspace, content_origin: None
    ) -> None:
        slug = (await _share(client, workspace.write("chart.png", PNG)))["slug"]
        new = (await client.post(f"/api/v1/l/{slug}/rotate")).json()["slug"]

        token = await client.post(f"/api/v1/l/{new}/content-token")

        assert token.status_code == 200
        assert (await client.post(f"/api/v1/l/{slug}/content-token")).status_code == 410

    async def test_a_restricted_file_is_shown_by_name_only_at_a_wider_level(
        self, client: AsyncClient, viewer: Viewer, workspace: Workspace, content_origin: None
    ) -> None:
        target = workspace.write("login.html", b"<form><input type=password></form>")
        link = await _share(client, target)

        assert link["content_max_access"] == "owner"
        refused = (await _open(client, link["slug"])).json()
        assert (refused["content"], refused["downloadable"]) == (None, False)
        assert (await client.get(f"/api/v1/l/{link['slug']}/download")).status_code == 404

        await client.patch(f"/api/v1/l/{link['slug']}", json={"access": "owner"})
        viewer.user = OWNER
        assert (await _open(client, link["slug"])).json()["content"]["render"] == "frame_active"

    async def test_a_restricted_file_ships_no_source_text_at_a_wider_level(
        self,
        client: AsyncClient,
        viewer: Viewer,
        workspace: Workspace,
        store: LocalVolumeBlobStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "LINK_CONTENT_URL_TEMPLATE", None)
        target = workspace.write("login.html", b"<form><input type=password></form>")
        slug = (await _share(client, target))["slug"]

        assert (await _open(client, slug)).json()["view"]["text"] is None

        await client.patch(f"/api/v1/l/{slug}", json={"access": "owner"})
        viewer.user = OWNER
        assert (await _open(client, slug)).json()["view"]["text"] is not None

    async def test_the_preview_image_is_served_only_for_open_links(
        self,
        client: AsyncClient,
        viewer: Viewer,
        workspace: Workspace,
        content_origin: None,
        tmp_path: Path,
    ) -> None:
        image = tmp_path / "big.png"
        Image.new("RGB", (300, 200), (10, 120, 200)).save(image)
        slug = (await _share(client, workspace.write("big.png", image.read_bytes())))["slug"]
        meta = (await client.get(f"/api/v1/l/{slug}/meta")).json()
        cid = meta["image_url"].split("//", 1)[1].split(".", 1)[0]
        assert meta["image_url"] == f"http://{cid}.u.test/api/v1/usercontent/{cid}/thumb.jpg"

        thumb_path = f"/api/v1/usercontent/{cid}/thumb.jpg"
        thumb = await client.get(thumb_path, headers={"host": f"{cid}.u.test"})
        assert (thumb.status_code, thumb.headers["content-type"]) == (200, "image/jpeg")

        await client.patch(f"/api/v1/l/{slug}", json={"access": "owner"})
        assert (await client.get(thumb_path, headers={"host": f"{cid}.u.test"})).status_code == 404


async def _accounts(mongo_db, users: list[AuthenticatedUser], age: timedelta) -> None:
    """Store users as accounts made age ago."""
    created_at = datetime.now(UTC) - age
    await mongo_db["users"].delete_many({"_id": {"$in": [ObjectId(u.user_id) for u in users]}})
    await mongo_db["users"].insert_many(
        [{"_id": ObjectId(u.user_id), "email": u.email, "created_at": created_at} for u in users]
    )


ESTABLISHED = timedelta(days=TRUSTED_REPORTER_MIN_ACCOUNT_AGE_DAYS + 1)


class TestReportsAndTakedown:
    async def test_three_fresh_accounts_queue_a_review_but_never_suspend(
        self,
        client: AsyncClient,
        viewer: Viewer,
        workspace: Workspace,
        store: LocalVolumeBlobStore,
        mongo_db,
    ) -> None:
        await _accounts(mongo_db, REPORTERS, timedelta(hours=1))
        slug = (await _share(client, workspace.write("r.html", b"<p>x</p>")))["slug"]

        with patch("app.services.links.abuse.send_email", AsyncMock()) as send_email:
            for reporter in REPORTERS:
                viewer.user = reporter
                await client.post(f"/api/v1/l/{slug}/report", json={"reason": "phishing"})

        assert (await _stored(slug)).suspended is False
        assert (await _open(client, slug)).status_code == 200
        (sent,) = {c.args[0].subject for c in send_email.await_args_list}
        assert sent == "A shared GAIA link needs review"

    async def test_three_established_reporters_suspend_an_active_file_link(
        self,
        client: AsyncClient,
        viewer: Viewer,
        workspace: Workspace,
        store: LocalVolumeBlobStore,
        captured: list,
        mongo_db,
    ) -> None:
        await _accounts(mongo_db, REPORTERS, ESTABLISHED)
        slug = (await _share(client, workspace.write("r.html", b"<p>x</p>")))["slug"]

        for reporter in [REPORTERS[0], REPORTERS[0], REPORTERS[1]]:
            viewer.user = reporter
            reported = await client.post(f"/api/v1/l/{slug}/report", json={"reason": "phishing"})
            assert reported.status_code == 204
        assert (await _open(client, slug)).status_code == 200

        viewer.user = REPORTERS[2]
        await client.post(f"/api/v1/l/{slug}/report", json={"reason": "malware"})

        removed = await _open(client, slug)
        assert (removed.status_code, removed.json()["code"]) == (410, "link_removed")
        assert (await _stored(slug)).suspended is True
        assert _names(captured).count("ShortLinkReported") == 3
        taken_down = [
            event for _, event in captured if type(event).__name__ == "ShortLinkTakenDown"
        ]
        assert [event.reason for event in taken_down] == ["reports_threshold"]

    async def test_signed_out_reports_never_suspend(
        self, client: AsyncClient, viewer: Viewer, workspace: Workspace, store: LocalVolumeBlobStore
    ) -> None:
        slug = (await _share(client, workspace.write("r.html", b"<p>x</p>")))["slug"]
        viewer.user = None
        assert (
            await client.post(f"/api/v1/l/{slug}/report", json={"reason": "phishing"})
        ).status_code == 204
        link = await _stored(slug)
        for n in range(5):
            await abuse.report(link, ReportReason.PHISHING, f"address-{n}", reporter_id=None)
        assert (await _stored(slug)).suspended is False

    async def test_a_link_without_active_content_needs_five_reporters(
        self, client: AsyncClient, viewer: Viewer, mongo_db
    ) -> None:
        reporters = [
            AuthenticatedUser(user_id=f"507f1f77bcf86cd7994391{n:02d}", auth_provider="workos")
            for n in range(5)
        ]
        await _accounts(mongo_db, reporters, ESTABLISHED)
        slug = (await _share(client, _rec(TODO, await _todo())))["slug"]
        for reporter in reporters[:4]:
            viewer.user = reporter
            await client.post(f"/api/v1/l/{slug}/report", json={"reason": "other"})
        assert (await _stored(slug)).suspended is False
        viewer.user = reporters[4]
        await client.post(f"/api/v1/l/{slug}/report", json={"reason": "other"})
        assert (await _stored(slug)).suspended is True

    async def test_takedown_kills_the_link_for_good_and_deletes_its_file(
        self, client: AsyncClient, viewer: Viewer, workspace: Workspace, store: LocalVolumeBlobStore
    ) -> None:
        slug = (await _share(client, workspace.write("r.html", b"<p>x</p>")))["slug"]
        link = await _stored(slug)
        assert link.snapshot is not None and link.snapshot.content_id is not None

        await abuse.take_down(link)
        await abuse.restore(await _stored(slug))

        removed = await _open(client, slug)
        assert (removed.status_code, removed.json()["code"]) == (410, "link_removed")
        assert (await _stored(slug)).revoked_reason is RevokeReason.TAKEDOWN
        with pytest.raises(FileNotFoundError):
            await link_content.read_snapshot(OWNER.user_id, link.snapshot.content_id)
        assert await attach_link(OWNER.user_id, link.target) is None

    async def test_restore_lifts_a_report_suspension(
        self, client: AsyncClient, viewer: Viewer, mongo_db
    ) -> None:
        slug = (await _share(client, _rec(TODO, await _todo())))["slug"]
        await mongo_db["short_links"].update_one({"slug": slug}, {"$set": {"suspended": True}})
        assert (await _open(client, slug)).status_code == 410

        await abuse.restore(await _stored(slug))

        assert (await _open(client, slug)).status_code == 200


class TestDeletingTheSource:
    async def test_deleting_a_chat_kills_the_links_to_its_files_and_artifacts(
        self,
        client: AsyncClient,
        viewer: Viewer,
        workspace: Workspace,
        content_origin: None,
        mongo_db,
    ) -> None:
        await conversation_repository.create(
            ConversationDocument(
                user_id=OWNER.user_id, conversation_id="conv-1", createdAt="2026-11-01T00:00:00Z"
            )
        )
        file_slug = (await _share(client, workspace.write("chart.png", PNG)))["slug"]
        cid = (await _stored(file_slug)).snapshot.content_id
        artifact_id = await _artifact("conv-1")
        artifact_slug = (await _share(client, _rec(OPENUI, artifact_id)))["slug"]
        elsewhere_slug = (await _share(client, _rec(OPENUI, await _artifact("conv-2"))))["slug"]

        with patch("app.services.conversation_service.capture"):
            deleted = await client.delete("/api/v1/conversations/conv-1")

        assert deleted.status_code == 200, deleted.text
        for slug in (file_slug, artifact_slug):
            gone = await _open(client, slug)
            assert (gone.status_code, gone.json()["code"]) == (410, "link_target_deleted")
            assert (await _stored(slug)).revoked_reason is RevokeReason.TARGET_DELETED
        with pytest.raises(FileNotFoundError):
            await link_content.read_snapshot(OWNER.user_id, cid)
        assert await mongo_db["artifacts"].count_documents({"conversation_id": "conv-1"}) == 0
        assert (await _open(client, elsewhere_slug)).status_code == 200


class TestGaiaAttachedLinks:
    async def test_an_attached_link_opens_for_its_owner_alone_and_reaches_them_by_placeholder(
        self, client: AsyncClient, viewer: Viewer
    ) -> None:
        todo_id = await _todo()
        link = await attach_link(
            OWNER.user_id, RecordTarget(type=ShortLinkTargetType.TODO_DELIVERABLE, id=todo_id)
        )
        assert link is not None and link.access is LinkAccess.OWNER

        viewer.user = OWNER
        assert (await _open(client, link.slug)).status_code == 200
        viewer.user = STRANGER
        assert (await _open(client, link.slug)).status_code == 403

        placeholder = link_placeholder(link.target)
        delivered = await resolve_link_placeholders(OWNER.user_id, f"[Your plan]({placeholder})")
        assert delivered == f"[Your plan]({settings.SHORTLINK_BASE_URL}/{link.slug})"
        # Another user's reply cannot resolve this owner's placeholder.
        assert await resolve_link_placeholders(STRANGER.user_id, placeholder) == ""

        viewer.user = OWNER
        rotated = (await client.post(f"/api/v1/l/{link.slug}/rotate")).json()["slug"]
        assert await resolve_link_placeholders(OWNER.user_id, placeholder) == (
            f"{settings.SHORTLINK_BASE_URL}/{rotated}"
        )
        await client.post("/api/v1/l/unshare", json={"target": _rec(TODO, todo_id)})
        assert await resolve_link_placeholders(OWNER.user_id, f"[Your plan]({placeholder})") == (
            "Your plan"
        )


class TestRemovingTheOwner:
    async def test_revoking_all_of_a_users_links_kills_each_and_deletes_their_files(
        self,
        client: AsyncClient,
        viewer: Viewer,
        workspace: Workspace,
        content_origin: None,
        captured: list,
    ) -> None:
        file_slug = (await _share(client, workspace.write("chart.png", PNG)))["slug"]
        cid = (await _stored(file_slug)).snapshot.content_id
        todo_slug = (await _share(client, _rec(TODO, await _todo())))["slug"]
        others = await share(
            RECIPIENT.user_id,
            RecordTarget(type=ShortLinkTargetType.TODO_DELIVERABLE, id=await _todo_for(RECIPIENT)),
            LinkSettings(),
        )
        others_slug = others.slug

        assert await revoke_all_links_for_user(OWNER.user_id) == 2
        assert await revoke_all_links_for_user(OWNER.user_id) == 0

        for slug in (file_slug, todo_slug):
            gone = await _open(client, slug)
            assert (gone.status_code, gone.json()["code"]) == (410, "link_revoked")
            assert (await _stored(slug)).revoked_reason is RevokeReason.ACCOUNT_REMOVED
        with pytest.raises(FileNotFoundError):
            await link_content.read_snapshot(OWNER.user_id, cid)
        assert (await _open(client, others_slug)).status_code == 200
        assert await attach_link(OWNER.user_id, (await _stored(todo_slug)).target) is None
        revoked = [event for _, event in captured if type(event).__name__ == "ShortLinkRevoked"]
        assert [event.reason for event in revoked] == ["account_removed", "account_removed"]


class TestTheBriefsLink:
    async def test_a_stored_brief_mints_its_link_and_the_link_opens_it(
        self, client: AsyncClient, viewer: Viewer, content_origin: None
    ) -> None:
        """Replay runs logged short_link.mint_failed ("Target not found") for every brief."""
        payload = BriefingPayload(
            kicker="THE MORNING BRIEF",
            date="2026-11-09",
            headline="Google Cloud waits",
            lede="One upload.",
            mood=BriefingMood.CLEAR,
            caption="c",
            template_family=EditionFamily.MEMO,
        )
        rendered = RenderedImage(image=b"png", fold=0.4)

        with (
            patch.object(brief_store, "render_edition_png", AsyncMock(return_value=rendered)),
            patch.object(brief_store, "store_edition", AsyncMock(return_value="edition-key")),
        ):
            stored = await brief_store.store_brief(
                OWNER.user_id,
                "2026-11-09",
                BriefingKind.DAILY,
                payload,
                BriefDelivery(push=True, notification_kind=NotificationKind.BRIEFING_DAILY),
            )

        link_url = stored.payload.link or ""
        slug = link_url.removeprefix("https://heygaia.link/")
        link = await _stored(slug)
        assert link.target == RecordTarget(type=ShortLinkTargetType.BRIEFING, id=stored.id)
        assert link_url.startswith("https://heygaia.link/")
        viewer.user = OWNER
        opened = await _open(client, slug)
        assert opened.status_code == 200, opened.text
        assert opened.json()["view"]["headline"] == "Google Cloud waits"


@pytest.fixture(autouse=True)
def _no_support_email() -> Iterator[AsyncMock]:
    with patch("app.services.links.abuse.send_email", AsyncMock()) as send:
        yield send


@pytest.fixture(autouse=True)
def _no_turnstile() -> Iterator[AsyncMock]:
    with patch("app.api.v1.endpoints.short_links.verify_turnstile_token", AsyncMock()) as verify:
        yield verify
