"""Builders for the artifact_data chunks streamed and persisted per turn."""

from app.config.settings import settings
from app.constants.artifacts import ARTIFACT_URL_PATH_TEMPLATE


def artifact_url_base(conversation_id: str) -> str:
    """Public backend URL base under which this conversation's artifacts are served.

    A file written to artifacts/<name> is fetchable at <base>/<name>.
    Single source of truth for the save-time relative→absolute rewrite and the
    agent-facing session banner.
    """
    return f"{settings.HOST}{ARTIFACT_URL_PATH_TEMPLATE.format(conversation_id=conversation_id)}"
