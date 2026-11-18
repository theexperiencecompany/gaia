"""The link target registry: every per-type fact about what a heygaia.link can point at.

The service, the routes and the preview builder never branch on a target type;
they look its spec up here. Adding a type is one ShortLinkTargetType member and
one module under targets/ registered below.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from app.models.short_link_models import (
    LinkSnapshot,
    LinkTarget,
    LinkViewerKind,
    PublicShortLinkView,
    RecordTarget,
    ShortLink,
    ShortLinkTargetType,
    WorkspaceFileTarget,
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
class ExportedFile:
    """A target rendered as a file to save (an artifact's PDF), with the headers that name it."""

    body: bytes
    media_type: str
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class PreviewFacts:
    """What a public or unlisted link's chat preview shows: a real title and, where the type has one, an image."""

    title: str
    image_url: str | None


T = TypeVar("T", bound=LinkTarget)


@dataclass(frozen=True, slots=True)
class LinkTargetSpec(Generic[T]):
    """One target type's view, preview and (for files) snapshot source, over its target reference T.

    Readers take (owner_id, target) and read under the link's owner, never a
    viewer; None means the owner has no such target. project maps the link as
    served (its snapshot without a content_id when it may not serve the bytes)
    and its target to what this viewer sees. source publishes a file type's bytes at mint.
    """

    #: The reference model this type's targets parse to.
    target: type[T]
    type: ShortLinkTargetType
    #: The preview line a gated or kind-only preview shows ("A brief from GAIA").
    kind_line: str
    project: Callable[[ShortLink, T, LinkViewerKind], Awaitable[PublicShortLinkView | None]]
    preview: Callable[[str, T, LinkSnapshot | None], Awaitable[PreviewFacts | None]]
    source: Callable[[str, T], Awaitable[SnapshotSource | None]] | None = None
    #: This type's targets inside one conversation: (owner_id, conversation_id).
    in_conversation: Callable[[str, str], Awaitable[list[T]]] | None = None
    #: The targets this one links to (a brief's items), whose GAIA-attached links follow its access.
    carries: Callable[[str, T], Awaitable[list[LinkTarget]]] | None = None
    #: The target as a file to save (GET /l/{slug}/export), for types that print one.
    export: Callable[[str, T], Awaitable[ExportedFile]] | None = None


def build_registry(
    specs: tuple[LinkTargetSpec[RecordTarget] | LinkTargetSpec[WorkspaceFileTarget], ...],
) -> Mapping[ShortLinkTargetType, LinkTargetSpec[LinkTarget]]:
    """Index specs by type; raise when a type has no spec or two, or a spec's reference model is not its type's.

    The registry is only ever indexed by a parsed target's own type, so a spec is
    handed exactly the reference model it declares: that is what the cast records.
    """
    registry: dict[ShortLinkTargetType, LinkTargetSpec[LinkTarget]] = {}
    for spec in specs:
        if spec.type in registry:
            raise ValueError(f"two link target specs for {spec.type}")
        if spec.type not in spec.target.TYPES:
            raise ValueError(f"the {spec.type} spec takes {spec.target.__name__} targets")
        registry[spec.type] = cast(LinkTargetSpec[LinkTarget], spec)
    missing = set(ShortLinkTargetType) - registry.keys()
    if missing:
        raise ValueError(f"no link target spec for {sorted(missing)}")
    return registry
