"""create_artifact: the executor's tool for reports, dashboards and other artifacts."""

import time
from typing import Annotated
import uuid

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.types import StreamWriter

from app.constants.openui_artifacts import (
    ARTIFACT_DELTA_EVENT,
    ARTIFACT_DELTA_FLUSH_CHARS,
    ARTIFACT_DELTA_FLUSH_SECONDS,
    ARTIFACT_DONE_EVENT,
)
from app.decorators import with_doc, with_rate_limiting
from app.models.agent_models import current_stream_writer, get_session_id, get_user_id
from app.models.openui_artifact_models import (
    ArtifactCard,
    ArtifactDelta,
    ArtifactKind,
    ArtifactStatus,
    ArtifactStreamHeader,
)
from app.models.short_link_models import ShortLinkTargetType
from app.services.links.placeholders import LINK_NOTE, link_placeholder
from app.services.links.service import attach_link
from app.services.openui_artifacts.create import ArtifactCreationError, create_openui_artifact
from app.services.openui_artifacts.generate import ArtifactRequest
from app.templates.docstrings.artifact_tool_docs import CREATE_ARTIFACT
from app.utils.timezone import home_timezone_from_config


class _DeltaBatcher:
    """Batch the model's token-sized deltas into a few stream frames for one artifact."""

    def __init__(self, writer: StreamWriter, header: ArtifactStreamHeader) -> None:
        self._writer = writer
        self._header = header
        self._pending: list[str] = []
        self._size = 0
        self._last_flush = time.monotonic()

    async def push(self, delta: str) -> None:
        self._pending.append(delta)
        self._size += len(delta)
        due = time.monotonic() - self._last_flush >= ARTIFACT_DELTA_FLUSH_SECONDS
        if due or self._size >= ARTIFACT_DELTA_FLUSH_CHARS:
            self.flush()

    def flush(self) -> None:
        if not self._pending:
            return
        delta = ArtifactDelta(**self._header.model_dump(mode="json"), delta="".join(self._pending))
        self._writer({ARTIFACT_DELTA_EVENT: delta.model_dump(mode="json")})
        self._pending.clear()
        self._size = 0
        self._last_flush = time.monotonic()


def _write_card(writer: StreamWriter, card: ArtifactCard) -> None:
    writer({ARTIFACT_DONE_EVENT: card.model_dump(mode="json", exclude_none=True)})


@tool
@with_rate_limiting("artifact_creation")
@with_doc(CREATE_ARTIFACT)
async def create_artifact(
    config: RunnableConfig,
    kind: Annotated[ArtifactKind, "What the artifact is"],
    title: Annotated[str, "The artifact's title"],
    brief: Annotated[str, "Every fact the artifact needs, verbatim, and its one-line message"],
    interactive: Annotated[
        bool, "True only when the user asked for inputs to play with: a calculator, a simulator"
    ] = False,
) -> str:
    writer = current_stream_writer()
    header = ArtifactStreamHeader(stream_id=uuid.uuid4().hex, kind=kind, title=title)
    batcher = _DeltaBatcher(writer, header)
    request = ArtifactRequest(
        kind=kind,
        brief=brief,
        user_id=get_user_id(config),
        conversation_id=get_session_id(config),
        today=home_timezone_from_config(config).now().date(),
        interactive=interactive,
    )
    try:
        artifact = await create_openui_artifact(request, title, batcher.push)
    except ArtifactCreationError as exc:
        batcher.flush()
        _write_card(
            writer,
            ArtifactCard(
                **header.model_dump(mode="json"), status=ArtifactStatus.FAILED, reason=exc.reason
            ),
        )
        problems = "".join(f"\n- {p}" for p in exc.problems[:10])
        return f"The {kind.value} could not be made ({exc.reason.value}).{problems}"
    except Exception:
        # The card is already on screen streaming; close it, then let the failure surface.
        batcher.flush()
        _write_card(
            writer, ArtifactCard(**header.model_dump(mode="json"), status=ArtifactStatus.FAILED)
        )
        raise
    batcher.flush()
    link = await attach_link(request.user_id, ShortLinkTargetType.OPENUI_ARTIFACT, artifact.id)
    _write_card(
        writer,
        ArtifactCard(
            **header.model_dump(mode="json"), status=ArtifactStatus.READY, artifact_id=artifact.id
        ),
    )
    link_line = (
        f" {LINK_NOTE} Its link: {link_placeholder(link.target_type, link.target_id)}"
        if link
        else ""
    )
    return (
        f'Created the {kind.value} "{title}". The user sees it as a card in chat and can '
        f"open it there; do not repeat its contents in your reply.{link_line}"
    )
