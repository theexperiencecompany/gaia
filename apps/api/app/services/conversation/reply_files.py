"""The files a reply delivers: the session artifacts its run and the work it narrates wrote, as artifact_data cards."""

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from app.constants.chat import ARTIFACT_CARD
from app.models.conversation_screen_models import ReplyFile
from app.models.tool_data_models import ToolDataEntry


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
            files.setdefault(
                written.path, ReplyFile(path=written.path, content_type=written.content_type)
            )
    return tuple(files.values())
