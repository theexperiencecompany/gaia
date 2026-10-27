"""Meta-test: every reader of a graph's "messages" stream builds its answer with HeldReplies.

A driver that concatenates raw AI chunks sends every "Let me check..." step beside a tool
call to the user as part of the answer. That shipped once already: a scheduled Inbox desk
run delivered its whole narration to Telegram, because the executor's driver kept its own
copy of the accumulation that the comms drivers had already fixed. HeldReplies is the one
implementation; a module that streams "messages" without it fails here.
"""

import ast
from pathlib import Path
import subprocess

APP_DIR = Path(__file__).resolve().parents[2] / "app"
HELD_REPLIES_MODULE = "app/agents/core/held_replies.py"


def _git_tracked_app_files() -> list[Path]:
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    out = subprocess.check_output(["git", "ls-files", "apps/api/app"], cwd=root, text=True)
    return [root / p for p in out.splitlines() if p.endswith(".py")]


def _requests_messages_stream(call: ast.Call) -> bool:
    """Whether this call is graph.astream(..., stream_mode=<something naming "messages">)."""
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "astream"):
        return False
    return any(
        keyword.arg == "stream_mode"
        and any(
            isinstance(node, ast.Constant) and node.value == "messages"
            for node in ast.walk(keyword.value)
        )
        for keyword in call.keywords
    )


def streams_messages_without_held_replies(source: str) -> bool:
    """Whether a module reads the "messages" stream but never imports HeldReplies."""
    tree = ast.parse(source)
    reads_messages = any(
        isinstance(node, ast.Call) and _requests_messages_stream(node) for node in ast.walk(tree)
    )
    uses_held_replies = any(
        isinstance(node, ast.ImportFrom)
        and any(alias.name == "HeldReplies" for alias in node.names)
        for node in ast.walk(tree)
    )
    return reads_messages and not uses_held_replies


def test_every_reader_of_the_messages_stream_uses_held_replies() -> None:
    offenders = [
        str(path.relative_to(APP_DIR.parent))
        for path in _git_tracked_app_files()
        if streams_messages_without_held_replies(path.read_text())
    ]
    assert not offenders, (
        'These modules read a graph\'s "messages" stream without HeldReplies '
        "(app/agents/core/held_replies.py), so narration beside a tool call becomes part of "
        f"their answer: {offenders}"
    )


def test_the_check_flags_a_driver_that_concatenates_raw_chunks() -> None:
    """The fence must be able to fail, or a green run proves nothing."""
    bad = (
        "async def drive(graph, state):\n"
        "    text = ''\n"
        "    async for mode, payload in graph.astream(state, stream_mode=['messages', 'updates']):\n"
        "        text += payload[0].text\n"
        "    return text\n"
    )
    good = "from app.agents.core.held_replies import HeldReplies\n" + bad
    no_messages = (
        "async def drive(graph, state):\n    graph.astream(state, stream_mode='updates')\n"
    )

    assert streams_messages_without_held_replies(bad)
    assert not streams_messages_without_held_replies(good)
    assert not streams_messages_without_held_replies(no_messages)
