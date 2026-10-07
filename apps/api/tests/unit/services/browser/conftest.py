"""The browser host as the API's client sees it, for tests of the session lifecycle above it."""

from __future__ import annotations

from typing import Any

from playwright.sync_api import StorageState
import pytest

from app.browser_host.wire import CreatedSession, SessionInfo
from app.constants.browser import BrowserEngine
from app.services.browser import session as session_mod
from app.services.browser.exceptions import BrowserSessionGone


class FakeHostClient:
    """Stands in for host_client: the sessions it opened, the state each holds, and every call made.

    Sessions are numbered s1, s2, ... unless ids are queued; each disposes or is
    read to the state set for it (an empty browser by default). A session in gone
    answers as the host answers a lost one; an error set for a call raises there.
    """

    def __init__(self) -> None:
        self.ids: list[str] = []
        self.engine = BrowserEngine.CHROMIUM
        self.states: dict[str, Any] = {}
        self.gone: set[str] = set()
        self.live = True
        self.create_errors: dict[str, Exception] = {}
        self.delete_errors: dict[str, Exception] = {}
        self.renew_errors: list[Exception] = []
        self.created: list[tuple[StorageState | None, str]] = []
        self.deleted: list[tuple[str, str]] = []
        self.reads: list[tuple[str, str]] = []
        self.renewals: list[tuple[str, str]] = []
        self.probes: list[tuple[str, str, float]] = []

    def _alive(self, session_id: str, host_url: str) -> None:
        if session_id in self.gone:
            raise BrowserSessionGone(
                f"Browser host returned 404 for {host_url}/sessions/{session_id}"
            )

    async def create_session(
        self, storage_state: StorageState | None, host_url: str
    ) -> CreatedSession:
        session_id = self.ids.pop(0) if self.ids else f"s{len(self.created) + 1}"
        if session_id in self.create_errors:
            raise self.create_errors[session_id]
        self.created.append((storage_state, host_url))
        return CreatedSession(
            session_id=session_id,
            cdp_ws=f"ws://host/cdp/{session_id}",
            live_ws=f"ws://host/live/{session_id}",
            engine=self.engine,
        )

    async def delete_session(self, session_id: str, host_url: str) -> StorageState:
        self.deleted.append((session_id, host_url))
        if session_id in self.delete_errors:
            raise self.delete_errors[session_id]
        self._alive(session_id, host_url)
        return self._state(session_id)

    async def get_storage_state(self, session_id: str, host_url: str) -> StorageState:
        self.reads.append((session_id, host_url))
        self._alive(session_id, host_url)
        return self._state(session_id)

    async def renew_session_lease(self, session_id: str, host_url: str) -> None:
        self.renewals.append((session_id, host_url))
        if self.renew_errors:
            raise self.renew_errors.pop(0)
        self._alive(session_id, host_url)

    async def get_session(self, session_id: str, host_url: str, *, timeout: float) -> SessionInfo:
        self.probes.append((session_id, host_url, timeout))
        self._alive(session_id, host_url)
        return SessionInfo(session_id=session_id, live=self.live)

    def _state(self, session_id: str) -> StorageState:
        state: StorageState = self.states.get(session_id, {"cookies": [], "origins": []})
        return state


@pytest.fixture
def host_client(monkeypatch: pytest.MonkeyPatch) -> FakeHostClient:
    """Put a FakeHostClient where the session lifecycle reaches the browser host."""
    fake = FakeHostClient()
    monkeypatch.setattr(session_mod, "host_client", fake)
    return fake
