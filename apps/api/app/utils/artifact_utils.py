"""Builders for the artifact_data chunks streamed and persisted per turn."""

import re
from urllib.parse import quote, unquote

from app.config.settings import settings
from app.constants.artifacts import ARTIFACT_URL_PATH_TEMPLATE

# A markdown link or image target naming a file under the session's artifacts/, as the agent writes it.
_ARTIFACT_LINK_TARGET = re.compile(
    r"(?<=\]\()(?:/workspace/sessions/[^/\s()]+/|\.?/)?artifacts/(?P<path>[^)\s]+)"
)


def artifact_url_base(conversation_id: str) -> str:
    """Public backend URL base under which this conversation's artifacts are served.

    A file written to artifacts/<name> is fetchable at <base>/<name>.
    Single source of truth for the screen's link resolution and the agent-facing session banner.
    """
    return f"{settings.HOST}{ARTIFACT_URL_PATH_TEMPLATE.format(conversation_id=conversation_id)}"


def resolve_artifact_links(text: str, conversation_id: str) -> str:
    """Point every markdown link and image at a sandbox artifact path to the URL that serves the file."""
    base = artifact_url_base(conversation_id)
    return _ARTIFACT_LINK_TARGET.sub(
        lambda found: f"{base}/{quote(unquote(found['path']), safe='/')}", text
    )
