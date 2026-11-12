"""OpenUI artifact events: reports, dashboards and the like that create_artifact writes."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent

__all__ = ["ArtifactCreated", "ArtifactFailed", "ArtifactOpened", "ArtifactPdfExported"]

# The API's ArtifactKind (apps/api/app/models/openui_artifact_models.py) is the source of
# truth; this layer cannot import it, so the event schema restates the closed set.
ArtifactKindName = Literal["dashboard", "report", "plan", "comparison", "memo", "document"]


class ArtifactCreated(ServerEvent):
    """An artifact passed validation and was stored."""

    event: ClassVar[str] = "artifact:created"
    budget_per_user_day: ClassVar[int] = 100

    kind: ArtifactKindName
    components: int
    repairs: int
    output_tokens: int
    first_component_ms: float | None
    total_ms: float
    model: Literal["gpt-6-luna"]


class ArtifactFailed(ServerEvent):
    """create_artifact gave up: a second validation failure, a refusal or a timeout."""

    event: ClassVar[str] = "artifact:failed"
    budget_per_user_day: ClassVar[int] = 100

    kind: ArtifactKindName
    reason: Literal["validation", "refused", "timeout"]
    problem_count: int


class ArtifactOpened(ServerEvent):
    """An artifact was opened in the in-app viewer or through its heygaia.link."""

    event: ClassVar[str] = "artifact:opened"
    budget_per_user_day: ClassVar[int] = 500

    kind: ArtifactKindName
    via: Literal["chat", "link"]


class ArtifactPdfExported(ServerEvent):
    """An artifact was served as a PDF."""

    event: ClassVar[str] = "artifact:pdf_exported"
    budget_per_user_day: ClassVar[int] = 200

    kind: ArtifactKindName
    pages: int
