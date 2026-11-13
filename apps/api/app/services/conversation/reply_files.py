"""The files a reply carries: the session artifacts its run wrote, as artifact_data cards."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from app.constants.chat import ARTIFACT_CARD
from app.models.conversation_log_models import Reply
from app.models.tool_data_models import ToolDataEntry


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


def reply_files(reply: Reply) -> tuple[ReplyFile, ...]:
    """Return each file the reply's cards wrote, once per path, in the order they were written."""
    files: dict[str, ReplyFile] = {}
    cards: tuple[ToolDataEntry, ...] = reply.tool_data
    for card in cards:
        if card["tool_name"] != ARTIFACT_CARD:
            continue
        written = _ArtifactCard.model_validate(card["data"])
        if written.event == "upsert":
            files.setdefault(written.path, ReplyFile(written.path, written.content_type))
    return tuple(files.values())
