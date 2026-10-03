"""An ASGI app served on a real loopback port inside the test process, for the stack's own local servers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time

from starlette.types import ASGIApp
import uvicorn

#: How long a local server gets to bind its port before the stack gives up on it.
_START_SECONDS = 30.0
_POLL_SECONDS = 0.05


@dataclass
class LocalServer:
    """One uvicorn server on 127.0.0.1:port, running as a task on the current loop."""

    name: str
    port: int
    server: uvicorn.Server
    task: asyncio.Task[None]

    async def stop(self) -> None:
        self.server.should_exit = True
        await self.task


async def serve_locally(name: str, app: ASGIApp, port: int) -> LocalServer:
    """Start app on port and return once it accepts connections; raise if it exits or never binds."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    deadline = time.monotonic() + _START_SECONDS
    while not server.started:
        if task.done():
            task.result()
            raise RuntimeError(f"{name} on port {port} exited before it started serving")
        if time.monotonic() > deadline:
            task.cancel()
            raise RuntimeError(
                f"{name} did not start serving on port {port} within {_START_SECONDS}s"
            )
        await asyncio.sleep(_POLL_SECONDS)
    return LocalServer(name=name, port=port, server=server, task=task)
