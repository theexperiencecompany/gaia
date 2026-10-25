"""A real Chrome launch opens its CDP connection even when the host's session bus never answers.

Regression for the merge-queue runs where every chromium host died with "timed out
during opening handshake": the CI box hands its runners a desktop session bus, and
Chrome dials it on its UI thread after publishing its DevTools port, so a bus that
does not answer holds the websocket upgrade. Linux-only: Chrome uses D-Bus only there.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import socket
import sys

import pytest

from app.browser_host.engine import Engine
from app.constants.browser import BrowserEngine
from tests.integration.real.browser._stack.stack import required_binary

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Chrome dials D-Bus only on Linux"
)


@pytest.fixture
def silent_session_bus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the session bus at a socket that accepts connections and never says a word."""
    path = tmp_path / "bus"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(path))
    listener.listen(64)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={path}")
    yield
    listener.close()


@pytest.mark.usefixtures("silent_session_bus")
async def test_a_chrome_launch_is_not_held_by_a_session_bus_that_never_answers() -> None:
    engine = await Engine.launch(
        BrowserEngine.CHROMIUM, required_binary("CHROMIUM_BIN", "google-chrome"), None
    )
    try:
        assert engine.alive
        assert "Chrome/" in await engine.user_agent()
    finally:
        await engine.shutdown()
