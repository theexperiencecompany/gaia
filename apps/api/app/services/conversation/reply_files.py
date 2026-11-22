"""The files a reply delivers: the session artifacts its run and the work it narrates wrote, as artifact_data cards."""

from collections.abc import Iterable

from app.constants.chat import ARTIFACT_CARD
from app.models.artifact_models import ArtifactCard
from shared.py.conversation_wire import ReplyFile, ToolDataEntry


def reply_files(cards: Iterable[ToolDataEntry], opens_at: str) -> tuple[ReplyFile, ...]:
    """Return each file the cards wrote, once per path, in the order they were written, each opening on opens_at and carrying its link."""
    files: dict[str, ReplyFile] = {}
    for card in cards:
        if card["tool_name"] != ARTIFACT_CARD:
            continue
        written = ArtifactCard.model_validate(card["data"])
        if written.event != "upsert":
            continue
        held = files.get(written.path)
        if held is None:
            files[written.path] = ReplyFile(
                path=written.path,
                content_type=written.content_type,
                opens_at=opens_at,
                short_url=written.short_url,
            )
        elif held.short_url is None and written.short_url is not None:
            # A reconcile card carries no link; the write that attached one does.
            files[written.path] = held.model_copy(update={"short_url": written.short_url})
    return tuple(files.values())
