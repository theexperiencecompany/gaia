"""What each tracked item tells the voice pass: a finished one's summary, its size, whether it waits."""

from dataclasses import dataclass

from app.services.briefing import context
from app.services.canvas_markdown import deliverable_markdown, deliverable_size

_ARTIFACT_PREVIEW_CHARS = 240


@dataclass
class ArtifactFact:
    """What the voice pass balances per item.

    A finished item's summary of its deliverable (empty for open work), the deliverable size
    as a HINT (a long research trail behind a one-line decision is not a thing to open), and
    whether it is waiting on the user.
    """

    snippet: str
    chars: int
    action: bool


def _deliverable_snippet(canvas: str) -> str:
    """Return a short, header-free preview of a canvas's deliverable for the voice pass.

    Only what a recipient of its link sees: never GAIA's working notes (its rules, ids,
    learnings), which are its own and not the user's to read.
    """
    lines = [
        ln.strip()
        for ln in deliverable_markdown(canvas).splitlines()
        if ln.strip() and not ln.lstrip().startswith(("#", "<!--", "|", "---"))
    ]
    return " ".join(lines)[:_ARTIFACT_PREVIEW_CHARS].rstrip()


def gather_artifacts(work: context.TrackedWork) -> dict[str, ArtifactFact]:
    """Build, per tracked item, a summary and the voice pass's two signals.

    The signals are whether the deliverable is big and whether it waits on the user.
    """
    out: dict[str, ArtifactFact] = {}
    blocked_ids = {d.id for d in work.blocked}
    # Open work's canvas is GAIA's notes on the way; only finished work has a result to say.
    finished_ids = {d.id for d in work.completed}
    for doc in [*work.completed, *work.running, *work.blocked, *work.failed]:
        todo_id = doc.id
        if todo_id in out:
            continue
        canvas = doc.canvas_content or ""
        out[todo_id] = ArtifactFact(
            snippet=_deliverable_snippet(canvas) if todo_id in finished_ids else "",
            chars=deliverable_size(canvas),
            action=todo_id in blocked_ids,
        )
    return out
