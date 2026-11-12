"""The snapshot backfill: what a dry run counts and what an applied run publishes or revokes.

The repository, the publisher and the file readers are mocked at their seams; the
repository's live_without_snapshot query runs over real Mongo in
tests/contracts/test_short_links_repository.py.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, call, patch

import pytest

from app.models.short_link_models import (
    LinkSnapshot,
    RenderMode,
    RevokeReason,
    ShortLink,
    ShortLinkTargetType,
    ShortLinkUpdate,
)
from app.services.links.backfill import BackfillReport, backfill_snapshots
from app.services.links.spec import LinkTargetSpec, SnapshotSource

_MODULE = "app.services.links.backfill"
SESSION = ShortLinkTargetType.SESSION_ARTIFACT
TODO = ShortLinkTargetType.TODO_DELIVERABLE
SOURCE = SnapshotSource(filename="a.html", declared_mime="text/html", size_bytes=3, data=b"<p>")
SNAPSHOT = LinkSnapshot(
    filename="a.html", mime="text/html", size_bytes=3, render=RenderMode.FRAME_ACTIVE
)


def _link(slug: str, target_id: str) -> ShortLink:
    return ShortLink(slug=slug, user_id="owner", target_type=SESSION, target_id=target_id)


KEPT = _link("kept", "c/a.html")
GONE = _link("gone", "c/b.html")
KEPT_TOO = _link("kept-too", "c/c.html")
GONE_TOO = _link("gone-too", "c/d.html")


@dataclass(frozen=True, slots=True)
class Seams:
    repo: AsyncMock
    source: AsyncMock
    publish: AsyncMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    present = {KEPT.target_id, KEPT_TOO.target_id}
    source = AsyncMock(
        side_effect=lambda _owner, target_id: SOURCE if target_id in present else None
    )
    registry = {
        TODO: LinkTargetSpec(type=TODO, kind_line="", project=AsyncMock(), preview=AsyncMock()),
        SESSION: LinkTargetSpec(
            type=SESSION, kind_line="", project=AsyncMock(), preview=AsyncMock(), source=source
        ),
    }
    with (
        patch(f"{_MODULE}.REGISTRY", registry),
        patch(f"{_MODULE}.short_link_repository") as repo,
        patch(f"{_MODULE}.publish", AsyncMock(return_value=SNAPSHOT)) as publish,
    ):
        repo.live_without_snapshot = AsyncMock(return_value=[KEPT, GONE, KEPT_TOO, GONE_TOO])
        repo.revoke = AsyncMock()
        repo.update = AsyncMock()
        yield Seams(repo=repo, source=source, publish=publish)


async def test_a_dry_run_counts_only_file_types_and_touches_nothing(seams: Seams) -> None:
    report = await backfill_snapshots(apply=False)

    assert report == BackfillReport(pending=4, published=0, target_deleted=0)
    seams.repo.live_without_snapshot.assert_awaited_once_with(SESSION)
    seams.source.assert_not_awaited()
    seams.repo.revoke.assert_not_awaited()
    seams.repo.update.assert_not_awaited()


async def test_an_applied_run_publishes_present_files_and_revokes_deleted_ones(
    seams: Seams,
) -> None:
    report = await backfill_snapshots(apply=True)

    assert report == BackfillReport(pending=4, published=2, target_deleted=2)
    assert seams.source.await_args_list == [
        call("owner", link.target_id) for link in (KEPT, GONE, KEPT_TOO, GONE_TOO)
    ]
    assert seams.publish.await_args_list == [call("owner", SESSION, SOURCE)] * 2
    assert seams.repo.update.await_args_list == [
        call(slug, user_id="owner", update=ShortLinkUpdate(snapshot=SNAPSHOT))
        for slug in ("kept", "kept-too")
    ]
    assert seams.repo.revoke.await_args_list == [
        call("owner", slug, RevokeReason.TARGET_DELETED) for slug in ("gone", "gone-too")
    ]


async def test_nothing_pending_reports_zero(seams: Seams) -> None:
    seams.repo.live_without_snapshot.return_value = []
    assert await backfill_snapshots(apply=True) == BackfillReport(
        pending=0, published=0, target_deleted=0
    )
