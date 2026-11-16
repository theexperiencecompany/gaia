"""Builders for the artifact_data chunks streamed and persisted per turn."""

from pathlib import PurePosixPath
import re
from urllib.parse import quote, unquote

from app.config.settings import settings
from app.constants.artifacts import ARTIFACT_URL_PATH_TEMPLATE

# A markdown link or image target naming a file under the session's artifacts/, as the agent writes it.
_ARTIFACT_LINK_TARGET = re.compile(
    r"(?<=\]\()(?:/workspace/sessions/[^/\s()]+/|\.?/)?artifacts/(?P<path>[^)\s]+)"
)
# A sandbox session path written as prose or code, ending before trailing punctuation.
_BARE_SESSION_PATH = re.compile(
    r"(?<!\]\()(?P<label>\[?)(?P<tick>`?)/workspace/sessions/[^/\s`()]+/"
    r"(?P<path>[^\s`()\[\]]*[^\s`()\[\].,;:!?'\"])(?P=tick)"
)
_ARTIFACTS_DIR = "artifacts/"


def artifact_url_base(conversation_id: str) -> str:
    """Public backend URL base under which this conversation's artifacts are served.

    A file written to artifacts/<name> is fetchable at <base>/<name>.
    Single source of truth for the screen's link resolution and the agent-facing session banner.
    """
    return f"{settings.HOST}{ARTIFACT_URL_PATH_TEMPLATE.format(conversation_id=conversation_id)}"


def resolve_sandbox_paths(text: str, conversation_id: str) -> str:
    """Replace every sandbox path in text with what a user can open: an artifact's URL, else the file's name.

    Markdown link targets get the URL; a bare path becomes a link named by the file, or the name alone
    when the file sits outside artifacts/ and nothing serves it.
    """
    base = artifact_url_base(conversation_id)

    def served(path: str) -> str:
        return f"{base}/{quote(unquote(path), safe='/')}"

    def named(found: re.Match[str]) -> str:
        path = found["path"]
        name = PurePosixPath(path).name
        # A link's own label, or a file nothing serves, keeps only the name.
        if found["label"] or not path.startswith(_ARTIFACTS_DIR):
            return f"{found['label']}{name}"
        return f"[{name}]({served(path.removeprefix(_ARTIFACTS_DIR))})"

    linked = _ARTIFACT_LINK_TARGET.sub(lambda found: served(found["path"]), text)
    return _BARE_SESSION_PATH.sub(named, linked)
