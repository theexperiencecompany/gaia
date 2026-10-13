"""Operator prompts for scripts that already run inside an event loop.

input() blocks the loop, and asyncio.to_thread(input) leaves a thread parked on
stdin that asyncio.run waits for after Ctrl+C, so the script hangs until Enter.
"""

from __future__ import annotations

import asyncio
import sys


async def ainput(prompt: str) -> str:
    """Read one stdin line; at a terminal, Ctrl+C cancels the wait at once. EOF raises EOFError."""
    print(prompt, end="", flush=True)
    fd = sys.stdin.fileno()
    if not sys.stdin.isatty():
        # a redirected file or pipe is not waiting on a person; epoll refuses regular files (EPERM)
        return _line_or_eof(sys.stdin.readline())

    loop = asyncio.get_running_loop()
    line: asyncio.Future[str] = loop.create_future()

    def _on_readable() -> None:
        # a canonical-mode tty is readable only once a whole line is typed
        if not line.done():
            line.set_result(sys.stdin.readline())

    loop.add_reader(fd, _on_readable)
    try:
        return _line_or_eof(await line)
    finally:
        loop.remove_reader(fd)


def _line_or_eof(raw: str) -> str:
    if not raw:
        raise EOFError("stdin closed before an answer was given")
    return raw.rstrip("\n")
