"""REGISTRY: every link target type's spec, checked complete at import."""

from collections.abc import Mapping

from app.models.short_link_models import ShortLinkTargetType
from app.services.links.spec import LinkTargetSpec, build_registry
from app.services.links.targets import (
    briefing,
    openui_artifact,
    session_artifact,
    todo_deliverable,
    workflow_run,
)

REGISTRY: Mapping[ShortLinkTargetType, LinkTargetSpec] = build_registry(
    (
        todo_deliverable.SPEC,
        briefing.SPEC,
        session_artifact.SPEC,
        workflow_run.SPEC,
        openui_artifact.SPEC,
    )
)
