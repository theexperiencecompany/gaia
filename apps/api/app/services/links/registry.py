"""REGISTRY: every link target type's spec, checked complete at import."""

from collections.abc import Mapping

from app.models.short_link_models import LinkTarget, ShortLinkTargetType
from app.services.links.spec import LinkTargetSpec, build_registry
from app.services.links.targets import (
    briefing,
    openui_artifact,
    todo_deliverable,
    workflow_run,
    workspace_file,
)

SPECS = (
    todo_deliverable.SPEC,
    briefing.SPEC,
    workspace_file.SPEC,
    workflow_run.SPEC,
    openui_artifact.SPEC,
)
REGISTRY: Mapping[ShortLinkTargetType, LinkTargetSpec[LinkTarget]] = build_registry(SPECS)
