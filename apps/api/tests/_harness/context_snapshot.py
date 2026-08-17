"""Render an effective message array as reviewable text, and diff it against a
recorded copy.

Deliberately not a general snapshot library: the value here is that a reviewer
can read the file and answer "should the model be seeing this?" line by line, so
the rendering names each message's slot markers instead of dumping a repr.

Re-record with ``RECORD_CONTEXT_SNAPSHOTS=1``. A snapshot is scaffolding — it
records whatever the code does and so cannot fail meaningfully on its own. Every
snapshot here ships beside real assertions in ``test_context_invariants.py``;
a movement in one of these files is only acceptable when a named test demanded it.
"""

import os
from pathlib import Path

from langchain_core.messages import AnyMessage

SNAPSHOT_DIR = Path(__file__).parent.parent / "unit" / "agents" / "context" / "__snapshots__"

_RECORD_ENV = "RECORD_CONTEXT_SNAPSHOTS"

#: Marker keys that place a message in a prompt slot. Rendered so a reviewer can
#: see *why* a message landed where it did, not just that it did.
_MARKERS = (
    "dynamic_context",
    "memory_message",
    "memory_recall",
    "todo_context",
    "executor_status",
    "time_context",
)


def render(messages: list[AnyMessage]) -> str:
    blocks: list[str] = []
    for index, message in enumerate(messages):
        markers = [name for name in _MARKERS if _has_marker(message, name)]
        header = f"[{index}] {message.type}"
        if message.name:
            header += f" name={message.name}"
        if markers:
            header += f" markers={','.join(markers)}"
        blocks.append(f"{header}\n{_body(message)}")
    return "\n\n".join(blocks) + "\n"


def _has_marker(message: AnyMessage, name: str) -> bool:
    if message.additional_kwargs.get(name):
        return True
    extra = getattr(message, "model_extra", None)
    return bool(isinstance(extra, dict) and extra.get(name))


def _body(message: AnyMessage) -> str:
    content = message.content if isinstance(message.content, str) else str(message.content)
    return "\n".join(f"    {line}" for line in content.splitlines()) or "    <empty>"


def assert_snapshot(name: str, messages: list[AnyMessage]) -> None:
    """Compare ``messages`` against the recorded rendering of ``name``."""
    path = SNAPSHOT_DIR / f"{name}.txt"
    actual = render(messages)

    if os.environ.get(_RECORD_ENV) == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual)
        return

    assert path.exists(), (
        f"No snapshot recorded for {name!r}. Re-run with {_RECORD_ENV}=1 to record it, "
        "then read every line of the result before committing it."
    )
    assert actual == path.read_text(), (
        f"The effective context for {name!r} moved.\n\n"
        "A snapshot movement is only acceptable when a named test demanded it. If one "
        f"did, re-record with {_RECORD_ENV}=1 and say which test in the commit message."
    )
