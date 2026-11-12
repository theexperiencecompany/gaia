"""The content origin's HTTP contract: only its own host serves a link's bytes, and only while the link lives.

The link lookup and the content store are mocked at their seams; tokens are
signed for real, and the full flow runs over real Mongo in
tests/integration/real/test_links_real.py.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.config.settings import settings
from app.constants.http import CONTENT_HOST_HEADER, INTERNAL_CALLER_HEADER
from app.models.short_link_models import (
    LinkAccess,
    LinkSnapshot,
    RenderMode,
    ShortLink,
    ShortLinkTargetType,
)
from app.services.links.content import issue_content_url
from app.services.links.serving import SNAPSHOT_CACHE_CONTROL, THUMBNAIL_CACHE_CONTROL
from tests.helpers import captured_wide_event

_ENDPOINT = "app.api.v1.endpoints.link_content"
BASE = "/api/v1/usercontent"
CID = "abcdefghijklmnopqrstuvwxyz"
HOST = f"{CID}.u.heygaia.test"
SLUG = "abcdefghijk"
INTERNAL_TOKEN = "i" * 64
PDF_BODY = b"%PDF-1.7"
THUMB_BODY = b"\xff\xd8jpeg"
SNAPSHOT = LinkSnapshot(
    filename="q3.pdf",
    mime="application/pdf",
    size_bytes=len(PDF_BODY),
    render=RenderMode.PDF,
    content_id=CID,
    has_thumbnail=True,
)
LINK = ShortLink(
    slug=SLUG,
    user_id="owner",
    target_type=ShortLinkTargetType.SESSION_ARTIFACT,
    target_id="conv-1/q3.pdf",
    access=LinkAccess.PUBLIC,
    expires_at=datetime.now(UTC) + timedelta(days=1),
    snapshot=SNAPSHOT,
)
NOT_FOUND = {"code": "link_content_not_found", "message": "Not found"}


@dataclass(frozen=True, slots=True)
class Seams:
    lookup: AsyncMock
    read_snapshot: AsyncMock
    read_thumbnail: AsyncMock


@pytest.fixture
def seams(origin: None) -> Iterator[Seams]:
    with (
        patch(f"{_ENDPOINT}.short_link_repository.get_live_by_content_id", AsyncMock()) as lookup,
        patch(f"{_ENDPOINT}.read_snapshot", AsyncMock(return_value=PDF_BODY)) as read_snapshot,
        patch(f"{_ENDPOINT}.read_thumbnail", AsyncMock(return_value=THUMB_BODY)) as read_thumb,
    ):
        lookup.return_value = LINK
        yield Seams(lookup, read_snapshot, read_thumb)


def _token(link: ShortLink = LINK) -> str:
    url, _ = issue_content_url(link, CID, datetime.now(UTC))
    return url.partition("?t=")[2]


def _refused(response_json: dict[str, object]) -> dict[str, object]:
    return {key: response_json.get(key) for key in NOT_FOUND}


class TestServeContent:
    async def test_a_valid_token_on_its_own_host_serves_the_snapshot(
        self, unauthed_client: AsyncClient, seams: Seams
    ) -> None:
        async with captured_wide_event() as event:
            response = await unauthed_client.get(
                f"{BASE}/{CID}",
                params={"t": _token()},
                headers={"host": HOST.upper(), "sec-fetch-dest": "embed"},
            )

        assert response.status_code == 200
        assert response.content == PDF_BODY
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["cache-control"] == SNAPSHOT_CACHE_CONTROL
        assert response.headers["content-disposition"] == "inline"
        seams.lookup.assert_awaited_once_with(CID)
        seams.read_snapshot.assert_awaited_once_with("owner", CID)
        assert event["short_link"] == {"operation": "serve", "fetch_dest": "embed", "render": "pdf"}
        assert CID not in str(event)

    async def test_html_is_served_only_into_an_iframe(
        self, unauthed_client: AsyncClient, seams: Seams
    ) -> None:
        html = SNAPSHOT.model_copy(update={"render": RenderMode.FRAME_ACTIVE, "mime": "text/html"})
        seams.lookup.return_value = LINK.model_copy(update={"snapshot": html})
        token = _token()

        framed = await unauthed_client.get(
            f"{BASE}/{CID}", params={"t": token}, headers={"host": HOST, "sec-fetch-dest": "iframe"}
        )
        opened = await unauthed_client.get(
            f"{BASE}/{CID}",
            params={"t": token},
            headers={"host": HOST, "sec-fetch-dest": "document"},
        )

        assert framed.status_code == 200
        assert framed.headers["content-type"] == "text/html; charset=utf-8"
        assert opened.status_code == 302
        assert opened.headers["location"] == f"{settings.SHORTLINK_BASE_URL}/{SLUG}"

    async def test_a_request_naming_no_host_serves_nothing(
        self, unauthed_client: AsyncClient, seams: Seams
    ) -> None:
        request = unauthed_client.build_request("GET", f"{BASE}/{CID}", params={"t": _token()})
        del request.headers["host"]

        response = await unauthed_client.send(request)

        assert response.status_code == 404
        assert response.json()["code"] == "link_content_not_found"

    async def test_a_stale_token_goes_back_to_the_link(
        self, unauthed_client: AsyncClient, seams: Seams
    ) -> None:
        async with captured_wide_event() as event:
            response = await unauthed_client.get(
                f"{BASE}/{CID}", params={"t": "1.forged"}, headers={"host": HOST}
            )

        assert response.status_code == 302
        assert response.headers["location"] == f"{settings.SHORTLINK_BASE_URL}/{SLUG}"
        assert event["short_link"]["signed_url"] == "stale"
        seams.read_snapshot.assert_not_awaited()

    async def test_no_token_goes_back_to_the_link(
        self, unauthed_client: AsyncClient, seams: Seams
    ) -> None:
        response = await unauthed_client.get(f"{BASE}/{CID}", headers={"host": HOST})
        assert response.status_code == 302

    async def test_the_same_path_on_any_other_host_serves_nothing(
        self, unauthed_client: AsyncClient, seams: Seams
    ) -> None:
        response = await unauthed_client.get(
            f"{BASE}/{CID}",
            params={"t": _token()},
            headers={"host": "api.heygaia.test", CONTENT_HOST_HEADER: HOST},
        )

        assert response.status_code == 404
        assert _refused(response.json()) == NOT_FOUND
        seams.lookup.assert_not_awaited()

    async def test_the_worker_names_the_host_beside_the_internal_token(
        self, unauthed_client: AsyncClient, seams: Seams, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", INTERNAL_TOKEN)
        response = await unauthed_client.get(
            f"{BASE}/{CID}",
            params={"t": _token()},
            headers={
                "host": "api.heygaia.test",
                CONTENT_HOST_HEADER: HOST,
                INTERNAL_CALLER_HEADER: INTERNAL_TOKEN,
            },
        )
        assert response.status_code == 200

    async def test_an_internal_caller_naming_no_host_is_judged_by_its_own(
        self, unauthed_client: AsyncClient, seams: Seams, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", INTERNAL_TOKEN)
        response = await unauthed_client.get(
            f"{BASE}/{CID}",
            params={"t": _token()},
            headers={"host": HOST, INTERNAL_CALLER_HEADER: INTERNAL_TOKEN},
        )
        assert response.status_code == 200

    async def test_a_deployment_without_a_content_origin_serves_nothing(
        self, unauthed_client: AsyncClient, seams: Seams, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = _token()
        monkeypatch.setattr(settings, "LINK_CONTENT_SIGNING_KEY", None)

        response = await unauthed_client.get(
            f"{BASE}/{CID}", params={"t": token}, headers={"host": HOST}
        )

        assert response.status_code == 404
        seams.lookup.assert_not_awaited()

    @pytest.mark.parametrize(
        "link",
        [
            None,
            LINK.model_copy(update={"suspended": True}),
            LINK.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(minutes=1)}),
            LINK.model_copy(update={"snapshot": None}),
            LINK.model_copy(update={"snapshot": SNAPSHOT.model_copy(update={"content_id": None})}),
            LINK.model_copy(
                update={"snapshot": SNAPSHOT.model_copy(update={"max_access": LinkAccess.PEOPLE})}
            ),
        ],
    )
    async def test_a_dead_or_unservable_link_serves_nothing(
        self, unauthed_client: AsyncClient, seams: Seams, link: ShortLink | None
    ) -> None:
        seams.lookup.return_value = link

        response = await unauthed_client.get(
            f"{BASE}/{CID}", params={"t": _token()}, headers={"host": HOST}
        )

        assert response.status_code == 404
        assert _refused(response.json()) == NOT_FOUND
        seams.read_snapshot.assert_not_awaited()


class TestServeThumbnail:
    @pytest.mark.parametrize("access", [LinkAccess.PUBLIC, LinkAccess.UNLISTED])
    async def test_an_open_links_thumbnail_is_served_without_a_token(
        self, unauthed_client: AsyncClient, seams: Seams, access: LinkAccess
    ) -> None:
        seams.lookup.return_value = LINK.model_copy(update={"access": access})

        async with captured_wide_event() as event:
            response = await unauthed_client.get(f"{BASE}/{CID}/thumb.jpg", headers={"host": HOST})

        assert response.status_code == 200
        assert response.content == THUMB_BODY
        assert response.headers["content-type"] == "image/jpeg"
        assert response.headers["cache-control"] == THUMBNAIL_CACHE_CONTROL
        seams.read_thumbnail.assert_awaited_once_with("owner", CID)
        assert event["short_link"] == {"operation": "thumbnail"}

    @pytest.mark.parametrize(
        "link",
        [
            None,
            LINK.model_copy(update={"revoked": True}),
            LINK.model_copy(update={"access": LinkAccess.PEOPLE}),
            LINK.model_copy(update={"access": LinkAccess.OWNER}),
            LINK.model_copy(update={"snapshot": None}),
            LINK.model_copy(
                update={"snapshot": SNAPSHOT.model_copy(update={"has_thumbnail": False})}
            ),
            LINK.model_copy(
                update={"snapshot": SNAPSHOT.model_copy(update={"max_access": LinkAccess.UNLISTED})}
            ),
        ],
    )
    async def test_a_gated_dead_or_imageless_link_serves_no_thumbnail(
        self, unauthed_client: AsyncClient, seams: Seams, link: ShortLink | None
    ) -> None:
        seams.lookup.return_value = link

        response = await unauthed_client.get(f"{BASE}/{CID}/thumb.jpg", headers={"host": HOST})

        assert response.status_code == 404
        assert _refused(response.json()) == NOT_FOUND
        seams.read_thumbnail.assert_not_awaited()

    async def test_a_thumbnail_on_another_host_is_refused(
        self, unauthed_client: AsyncClient, seams: Seams
    ) -> None:
        response = await unauthed_client.get(
            f"{BASE}/{CID}/thumb.jpg", headers={"host": "app.heygaia.test"}
        )
        assert response.status_code == 404
        seams.lookup.assert_not_awaited()
