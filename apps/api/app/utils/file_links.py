"""Turn the sandbox paths an agent writes into links a user can open, given where files are served."""

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from urllib.parse import quote, unquote

from app.constants.artifacts import ARTIFACT_URL_PATH_TEMPLATE

# A markdown link or image whose target names a file under the session's artifacts/, as the agent writes it.
_ARTIFACT_LINK = re.compile(
    r"(?P<image>!?)\[(?P<label>[^\]]*)\]\("
    r"(?:/workspace/sessions/[^/\s()]+/|\.?/)?artifacts/(?P<path>[^)\s]+)"
)
_SESSIONS_ROOT = "/workspace/sessions/"
# A sandbox session path written as prose or code, ending before trailing punctuation.
_BARE_SESSION_PATH = re.compile(
    r"(?<!\]\()(?P<label>\[?)(?P<tick>`?)/workspace/sessions/[^/\s`()]+/"
    r"(?P<path>[^\s`()\[\]]*[^\s`()\[\].,;:!?'\"])(?P=tick)"
)
# The end of streamed text that may still become a sandbox path or a link target: rewriting it now
# would show text the finished path takes back.
_UNFINISHED_PATH_TAIL = re.compile(
    r"\]\([^)\s]*$|\[?`?(?:/workspace/sessions/[^/\s`()]*(?:/[^\s`()\[\]]*)?|"
    + "|".join(re.escape(_SESSIONS_ROOT[:end]) for end in range(len(_SESSIONS_ROOT) - 1, 0, -1))
    + ")?$"
)
_ARTIFACTS_DIR = "artifacts/"


@dataclass(frozen=True)
class FileLinks:
    """Where a conversation's files are served (the API host) and opened (the web app)."""

    api_host: str
    web_app: str

    def artifact_base(self, conversation_id: str) -> str:
        """Return the URL base a file written to artifacts/<name> is fetchable under, as <base>/<name>."""
        return (
            f"{self.api_host}{ARTIFACT_URL_PATH_TEMPLATE.format(conversation_id=conversation_id)}"
        )

    def conversation_page(self, conversation_id: str) -> str:
        """Return the web app page of a conversation, where its files open; what a link in any chat app opens."""
        return f"{self.web_app}/c/{conversation_id}"

    def resolve(self, text: str, conversation_id: str) -> str:
        """Replace every sandbox path in text with what a user can open.

        A link to an artifact opens its conversation in the web app, an image embeds the artifact's URL,
        and a bare path becomes a link named by the file, or the name alone when it sits outside artifacts/.
        """
        base = self.artifact_base(conversation_id)
        page = self.conversation_page(conversation_id)

        def served(path: str) -> str:
            return f"{base}/{quote(unquote(path), safe='/')}"

        def linked_to(found: re.Match[str]) -> str:
            target = served(found.group("path")) if found.group("image") else page
            # The link's closing parenthesis stays where it was written.
            return f"{found.group('image')}[{found.group('label')}]({target}"

        def named(found: re.Match[str]) -> str:
            path = found.group("path")
            name = PurePosixPath(path).name
            # A link's own label, or a file nothing serves, keeps only the name.
            if found.group("label") or not path.startswith(_ARTIFACTS_DIR):
                return f"{found.group('label')}{name}"
            return f"[{name}]({page})"

        return _BARE_SESSION_PATH.sub(named, _ARTIFACT_LINK.sub(linked_to, text))


def unfinished_path_start(text: str) -> int:
    """Return where streamed text may still be writing a sandbox path or link target; len(text) when it is not."""
    found = _UNFINISHED_PATH_TAIL.search(text)
    return found.start() if found else len(text)
