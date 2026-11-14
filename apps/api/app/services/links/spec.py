"""The link target registry: every per-type fact about what a heygaia.link can point at.

The service, the routes and the preview builder never branch on a target type;
they look its spec up here. Adding a type is one ShortLinkTargetType member and
one module under targets/ registered below.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from app.models.short_link_models import (
    LinkSnapshot,
    PublicShortLinkView,
    ShortLinkTargetType,
)


@dataclass(frozen=True, slots=True)
class SnapshotSource:
    """A file as its owner holds it now, to be published as a link's snapshot.

    data is None when the file is over the snapshot size cap, so it is never read.
    """

    filename: str
    declared_mime: str
    size_bytes: int
    data: bytes | None


@dataclass(frozen=True, slots=True)
class PreviewFacts:
    """What a public or unlisted link's chat preview shows: a real title and, where the type has one, an image."""

    title: str
    image_url: str | None


Projector = Callable[[str, str, LinkSnapshot | None], Awaitable[PublicShortLinkView | None]]
Previewer = Callable[[str, str, LinkSnapshot | None], Awaitable[PreviewFacts | None]]
SourceReader = Callable[[str, str], Awaitable[SnapshotSource | None]]


@dataclass(frozen=True, slots=True)
class LinkTargetSpec:
    """One target type's view, preview and (for files) snapshot source.

    Every reader takes (owner_id, target_id) and reads under the link's owner,
    never a viewer; None means the owner has no such target. project is the
    only mapping from a stored document to what a recipient sees. source is set
    for types whose link serves bytes: those are published as a snapshot when
    the link is minted, and project then reads the snapshot, never the live file;
    the snapshot it gets has no content_id when the link may not serve its bytes.
    """

    type: ShortLinkTargetType
    #: The preview line a gated or kind-only preview shows ("A brief from GAIA").
    kind_line: str
    project: Projector
    preview: Previewer
    source: SourceReader | None = None


def build_registry(
    specs: tuple[LinkTargetSpec, ...],
) -> Mapping[ShortLinkTargetType, LinkTargetSpec]:
    """Index specs by type; raise when a type has no spec or two."""
    registry: dict[ShortLinkTargetType, LinkTargetSpec] = {}
    for spec in specs:
        if spec.type in registry:
            raise ValueError(f"two link target specs for {spec.type}")
        registry[spec.type] = spec
    missing = set(ShortLinkTargetType) - registry.keys()
    if missing:
        raise ValueError(f"no link target spec for {sorted(missing)}")
    return registry
