"""What each tracked item's deliverable tells the voice pass: a summary, its size, whether it waits on the user."""

from dataclasses import dataclass

from app.services.briefing import context
from app.services.canvas_markdown import deliverable_size

_ARTIFACT_PREVIEW_CHARS = 240


@dataclass
class ArtifactFact:
    """What the voice pass balances per item.

    A concrete summary it always voices, the deliverable size as a HINT (not a verdict —
    a long research trail behind a one-line decision is not a thing to open), and whether
    it is waiting on the user. The pass summarises everything and links only what's
    genuinely a deliverable-to-open or waiting on the user.
    """

    snippet: str
    chars: int
    action: bool


def _canvas_snippet(canvas: str) -> str:
    """Return a short, header-free preview of a canvas for the voice pass.

    The pass draws concrete specifics from it (names, counts); it is never shown to the
    user verbatim.
    """
    lines = [
        ln.strip()
        for ln in canvas.splitlines()
        if ln.strip() and not ln.lstrip().startswith(("#", "<!--", "|", "---"))
    ]
    return " ".join(lines)[:_ARTIFACT_PREVIEW_CHARS].rstrip()


def gather_artifacts(work: context.TrackedWork) -> dict[str, ArtifactFact]:
    """Build, per tracked item, a summary and the voice pass's two signals.

    The signals are whether the deliverable is big and whether it waits on the user.
    """
    out: dict[str, ArtifactFact] = {}
    blocked_ids = {d.id for d in work.blocked}
    for doc in [*work.completed, *work.running, *work.blocked, *work.failed]:
        todo_id = doc.id
        if todo_id in out:
            continue
        canvas = doc.canvas_content or ""
        out[todo_id] = ArtifactFact(
            snippet=_canvas_snippet(canvas),
            chars=deliverable_size(canvas),
            action=todo_id in blocked_ids,
        )
    return out
