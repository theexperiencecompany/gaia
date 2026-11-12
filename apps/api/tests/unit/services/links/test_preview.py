"""What a link's chat preview shows at each access level and state; the target reader is mocked at the registry."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.short_link_models import (
    LinkAccess,
    LinkPreviewMeta,
    LinkSnapshot,
    RenderMode,
    ShortLink,
    ShortLinkTargetType,
)
from app.services.links.preview import (
    DEAD_DESCRIPTION,
    DEAD_TITLE,
    GATED_DESCRIPTION,
    GATED_TITLE,
    preview_meta,
)
from app.services.links.spec import LinkTargetSpec, PreviewFacts

TODO = ShortLinkTargetType.TODO_DELIVERABLE
KIND_LINE = "Something GAIA worked on."
DEAD = LinkPreviewMeta(
    live=False,
    target_type=None,
    access=None,
    indexable=False,
    title=DEAD_TITLE,
    description=DEAD_DESCRIPTION,
    image_url=None,
)
SNAPSHOT = LinkSnapshot(
    filename="r.html",
    mime="text/html",
    size_bytes=10,
    render=RenderMode.FRAME_ACTIVE,
    content_id="c" * 26,
)


def _link(**overrides: object) -> ShortLink:
    data: dict[str, object] = {
        "slug": "abcdefghijk",
        "user_id": "owner",
        "target_type": TODO,
        "target_id": "t1",
        "access": LinkAccess.PUBLIC,
    }
    data.update(overrides)
    return ShortLink.model_validate(data)


@pytest.fixture
def previewer() -> Iterator[AsyncMock]:
    read = AsyncMock(return_value=PreviewFacts(title="Q3 plan", image_url="https://img/q3.png"))
    spec = LinkTargetSpec(type=TODO, kind_line=KIND_LINE, project=AsyncMock(), preview=read)
    with patch("app.services.links.preview.REGISTRY", {TODO: spec}):
        yield read


async def test_an_unknown_link_previews_as_gone() -> None:
    assert await preview_meta(None) == DEAD


@pytest.mark.parametrize(
    "dead",
    [
        {"revoked": True},
        {"suspended": True},
        {"expires_at": datetime.now(UTC) - timedelta(minutes=1)},
    ],
)
async def test_a_dead_link_discloses_nothing(previewer: AsyncMock, dead: dict[str, object]) -> None:
    assert await preview_meta(_link(**dead)) == DEAD
    previewer.assert_not_awaited()


async def test_a_link_that_expires_later_still_previews(previewer: AsyncMock) -> None:
    meta = await preview_meta(_link(expires_at=datetime.now(UTC) + timedelta(days=1)))
    assert meta.live is True


@pytest.mark.parametrize("access", [LinkAccess.PEOPLE, LinkAccess.OWNER])
async def test_a_gated_link_previews_only_its_kind(
    previewer: AsyncMock, access: LinkAccess
) -> None:
    assert await preview_meta(_link(access=access)) == LinkPreviewMeta(
        live=True,
        target_type=TODO,
        access=access,
        indexable=False,
        title=GATED_TITLE,
        description=GATED_DESCRIPTION,
        image_url=None,
    )
    previewer.assert_not_awaited()


@pytest.mark.parametrize(
    ("access", "indexable"), [(LinkAccess.PUBLIC, True), (LinkAccess.UNLISTED, False)]
)
async def test_an_open_link_previews_its_real_title_and_image(
    previewer: AsyncMock, access: LinkAccess, indexable: bool
) -> None:
    meta = await preview_meta(_link(access=access, snapshot=SNAPSHOT))

    assert meta == LinkPreviewMeta(
        live=True,
        target_type=TODO,
        access=access,
        indexable=indexable,
        title="Q3 plan",
        description=KIND_LINE,
        image_url="https://img/q3.png",
    )
    previewer.assert_awaited_once_with("owner", "t1", SNAPSHOT)


async def test_a_snapshot_capped_below_the_links_access_is_withheld_from_the_preview(
    previewer: AsyncMock,
) -> None:
    capped = SNAPSHOT.model_copy(update={"max_access": LinkAccess.UNLISTED})
    await preview_meta(_link(access=LinkAccess.PUBLIC, snapshot=capped))
    previewer.assert_awaited_once_with("owner", "t1", None)


async def test_a_deleted_target_previews_as_gone(previewer: AsyncMock) -> None:
    previewer.return_value = None
    assert await preview_meta(_link()) == DEAD
