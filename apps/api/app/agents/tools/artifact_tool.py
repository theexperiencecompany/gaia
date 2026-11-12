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
from app.models.openui_artifact_models import ArtifactKind, ArtifactStatus
from app.models.short_link_models import ShortLinkTargetType
from app.services.links.service import optional_short_link
from app.services.openui_artifacts.create import ArtifactCreationError, create_openui_artifact
from app.services.openui_artifacts.generate import ArtifactRequest
from app.templates.docstrings.artifact_tool_docs import CREATE_ARTIFACT


class _DeltaBatcher:
    """Batch the model's token-sized deltas into a few stream frames for one artifact."""

    def __init__(
        self, writer: StreamWriter, stream_id: str, kind: ArtifactKind, title: str
    ) -> None:
        self._writer = writer
        self._header = {"stream_id": stream_id, "kind": kind.value, "title": title}
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
        self._writer({ARTIFACT_DELTA_EVENT: {**self._header, "delta": "".join(self._pending)}})
        self._pending.clear()
        self._size = 0
        self._last_flush = time.monotonic()


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
    stream_id = uuid.uuid4().hex
    batcher = _DeltaBatcher(writer, stream_id, kind, title)
    request = ArtifactRequest(
        kind=kind,
        brief=brief,
        user_id=get_user_id(config),
        conversation_id=get_session_id(config),
        interactive=interactive,
    )
    card = {"stream_id": stream_id, "kind": kind.value, "title": title}
    try:
        artifact = await create_openui_artifact(request, title, batcher.push)
    except ArtifactCreationError as exc:
        batcher.flush()
        writer({ARTIFACT_DONE_EVENT: {**card, "status": ArtifactStatus.FAILED.value}})
        problems = "".join(f"\n- {p}" for p in exc.problems[:10])
        return f"The {kind.value} could not be made ({exc.reason.value}).{problems}"
    except Exception:
        # The card is already on screen streaming; close it, then let the failure surface.
        batcher.flush()
        writer({ARTIFACT_DONE_EVENT: {**card, "status": ArtifactStatus.FAILED.value}})
        raise
    batcher.flush()
    short_url = await optional_short_link(
        request.user_id, ShortLinkTargetType.OPENUI_ARTIFACT, artifact.id
    )
    writer(
        {
            ARTIFACT_DONE_EVENT: {
                **card,
                "status": ArtifactStatus.READY.value,
                "artifact_id": artifact.id,
            }
        }
    )
    link = f" Public link: {short_url}." if short_url else ""
    return (
        f'Created the {kind.value} "{title}". The user sees it as a card in chat and can '
        f"open it there; do not repeat its contents in your reply.{link}"
    )
