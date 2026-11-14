"""The files a reply delivers: the session artifacts its run and the work it narrates wrote, as artifact_data cards."""

from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from app.constants.chat import ARTIFACT_CARD
from shared.py.conversation_wire import ToolDataEntry


@dataclass(frozen=True)
class ReplyFile:
    """One session artifact a reply carries, addressed by its path under the session's artifacts/."""

    path: str
    content_type: str | None


class _ArtifactCard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event: str
    path: str
    content_type: str | None = None


def reply_files(cards: Iterable[ToolDataEntry]) -> tuple[ReplyFile, ...]:
    """Return each file the cards wrote, once per path, in the order they were written."""
    files: dict[str, ReplyFile] = {}
    for card in cards:
        if card["tool_name"] != ARTIFACT_CARD:
            continue
        written = _ArtifactCard.model_validate(card["data"])
        if written.event == "upsert":
            files.setdefault(written.path, ReplyFile(written.path, written.content_type))
    return tuple(files.values())
