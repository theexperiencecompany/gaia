"""A top-level load the site never answers is stopped once per tab, and nothing else is."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

import app.services.browser.stalled_loads as stalled_loads
from app.services.browser.stalled_loads import StalledLoads

TAB = "TAB-1"
Handler = Callable[[Any, str | None], None]


class _FakeClient:
    """Records the Page handlers StalledLoads registers and every stopLoading it sends."""

    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {}
        self.stopped: list[str] = []
        self.register = SimpleNamespace(
            Page=SimpleNamespace(
                frameStartedNavigating=lambda h: self.handlers.__setitem__("started", h),
                frameNavigated=lambda h: self.handlers.__setitem__("committed", h),
                frameStoppedLoading=lambda h: self.handlers.__setitem__("stopped", h),
            )
        )
        self.send = SimpleNamespace(Page=SimpleNamespace(stopLoading=self._stop_loading))

    async def _stop_loading(self, session_id: str) -> dict[str, Any]:
        self.stopped.append(session_id)
        return {}


def _browser(client: _FakeClient) -> Any:
    sessions = {"S1": TAB, "S2": TAB}
    return SimpleNamespace(
        cdp_client=client,
        session_manager=SimpleNamespace(get_target_id_from_session_id=sessions.get),
    )


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.fixture
async def watched(monkeypatch: pytest.MonkeyPatch) -> tuple[StalledLoads, _FakeClient]:
    monkeypatch.setattr(stalled_loads, "BROWSER_LOAD_STALL_SECONDS", 0)
    client = _FakeClient()
    guard = StalledLoads(_browser(client))
    await guard.attach(SimpleNamespace())
    return guard, client


def _start(
    client: _FakeClient, session: str, frame: str = TAB, kind: str = "differentDocument"
) -> None:
    event = {
        "frameId": frame,
        "url": "http://example.com:81/",
        "loaderId": "L",
        "navigationType": kind,
    }
    client.handlers["started"](event, session)


@pytest.mark.unit
class TestStalledLoads:
    async def test_an_unanswered_load_is_stopped_and_reported(
        self, watched: tuple[StalledLoads, _FakeClient]
    ) -> None:
        guard, client = watched
        _start(client, "S1")
        await _settle()
        assert client.stopped == ["S1"]
        [note] = guard.take()
        assert "http://example.com:81/" in note
        assert guard.take() == []

    async def test_a_committed_load_is_left_alone(
        self, watched: tuple[StalledLoads, _FakeClient]
    ) -> None:
        guard, client = watched
        _start(client, "S1")
        client.handlers["committed"]({"frame": {"id": TAB}, "type": "Navigation"}, "S1")
        await _settle()
        assert client.stopped == []
        assert guard.take() == []

    async def test_two_sessions_on_one_tab_stop_it_once(
        self, watched: tuple[StalledLoads, _FakeClient]
    ) -> None:
        guard, client = watched
        _start(client, "S1")
        _start(client, "S2")
        await _settle()
        assert len(client.stopped) == 1
        assert len(guard.take()) == 1

    async def test_frames_and_same_document_navigations_are_ignored(
        self, watched: tuple[StalledLoads, _FakeClient]
    ) -> None:
        guard, client = watched
        _start(client, "S1", frame="IFRAME-1")
        _start(client, "S1", kind="sameDocument")
        await _settle()
        assert client.stopped == []
        assert guard.take() == []

    async def test_a_retry_after_a_stall_gets_a_full_window_of_its_own(
        self, watched: tuple[StalledLoads, _FakeClient], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        guard, client = watched
        _start(client, "S1")
        await _settle()
        guard.take()
        monkeypatch.setattr(stalled_loads, "BROWSER_LOAD_STALL_SECONDS", 3600)
        _start(client, "S1")
        await _settle()
        assert client.stopped == ["S1"]
        assert guard.take() == []
        guard.close()
