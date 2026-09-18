"""Coverage-focused tests for chromium.py missing lines.

Covers helper conversions, _headless_shell_beside, _resolve_chromium_path,
and ChromiumHost internals with mocked Playwright/subprocess/CDP.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.browser_host import chromium
from app.browser_host.chromium import (
    CDPTimeoutError,
    ChromiumHost,
    HostSession,
    SessionNotFoundError,
    _cdp_cookie_to_storage_state,
    _headless_shell_beside,
    _resolve_chromium_path,
    _storage_state_cookie_to_cdp,
    cdp_call,
)
from app.browser_host.metrics import ProcessSampler
from app.config.settings import settings
from app.constants.browser import (
    BROWSER_VIEWPORT_HEIGHT,
    BROWSER_VIEWPORT_WIDTH,
    BrowserEngine,
)
from app.constants.log_tags import LogTag
from tests.unit.browser_host.conftest import (
    FakeMux,
    install_mux,
    make_host,
    make_session,
)


@pytest.fixture(autouse=True)
def _pin_chromium_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin BROWSER_ENGINE to Chromium; the host default is now Obscura."""
    monkeypatch.setattr(settings, "BROWSER_ENGINE", BrowserEngine.CHROMIUM)


# ---------------------------------------------------------------------------
# _headless_shell_beside
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_headless_shell_beside_no_chromium_parent_returns_none(tmp_path: Path) -> None:
    # Path that has no parent starting with "chromium-"
    chromium = tmp_path / "some" / "other" / "chrome"
    chromium.parent.mkdir(parents=True, exist_ok=True)
    assert _headless_shell_beside(chromium) is None


@pytest.mark.unit
def test_headless_shell_beside_shell_root_missing_returns_none(tmp_path: Path) -> None:
    # Create chromium-1234 parent but no sibling headless dir
    rev_dir = tmp_path / "chromium-1234"
    rev_dir.mkdir()
    chromium = rev_dir / "chrome" / "chrome"
    chromium.parent.mkdir(parents=True, exist_ok=True)
    assert _headless_shell_beside(chromium) is None


@pytest.mark.unit
def test_headless_shell_beside_finds_headless_shell_binary(tmp_path: Path) -> None:
    rev_dir = tmp_path / "chromium-1234"
    rev_dir.mkdir()
    shell_root = tmp_path / "chromium_headless_shell-1234"
    shell_root.mkdir()
    binary = shell_root / "headless_shell"
    binary.write_text("fake")
    # chromium path that has rev_dir as a parent
    chromium = rev_dir / "chrome-linux" / "chrome"
    chromium.parent.mkdir(parents=True, exist_ok=True)
    found = _headless_shell_beside(chromium)
    assert found is not None
    assert found == binary


@pytest.mark.unit
def test_headless_shell_beside_shell_root_exists_but_no_binary_returns_none(tmp_path: Path) -> None:
    rev_dir = tmp_path / "chromium-9999"
    rev_dir.mkdir()
    shell_root = tmp_path / "chromium_headless_shell-9999"
    shell_root.mkdir()
    chromium = rev_dir / "chrome"
    chromium.parent.mkdir(parents=True, exist_ok=True)
    assert _headless_shell_beside(chromium) is None


@pytest.mark.unit
def test_headless_shell_beside_finds_chrome_headless_shell_variant(tmp_path: Path) -> None:
    rev_dir = tmp_path / "chromium-7777"
    rev_dir.mkdir()
    shell_root = tmp_path / "chromium_headless_shell-7777"
    shell_root.mkdir()
    binary = shell_root / "subdir" / "chrome-headless-shell"
    binary.parent.mkdir(parents=True)
    binary.write_text("x")
    chromium = rev_dir / "chrome"
    chromium.parent.mkdir(parents=True, exist_ok=True)
    found = _headless_shell_beside(chromium)
    assert found == binary


@pytest.mark.unit
def test_headless_shell_beside_prefers_first_binary_name(tmp_path: Path) -> None:
    rev_dir = tmp_path / "chromium-1111"
    rev_dir.mkdir()
    shell_root = tmp_path / "chromium_headless_shell-1111"
    shell_root.mkdir()
    # create both names — rglob will find headless_shell first if we iterate in order
    a = shell_root / "headless_shell"
    a.write_text("a")
    chromium = rev_dir / "chrome"
    chromium.parent.mkdir(parents=True, exist_ok=True)
    found = _headless_shell_beside(chromium)
    assert found == a


# ---------------------------------------------------------------------------
# _resolve_chromium_path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_chromium_path_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    override = tmp_path / "my-chromium"
    monkeypatch.setattr(settings, "BROWSER_HOST_CHROMIUM_PATH", str(override))
    assert _resolve_chromium_path() == str(override)


@pytest.mark.unit
def test_resolve_chromium_path_uses_headless_shell_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_CHROMIUM_PATH", None)

    fake_full = Path("/tmp/cache/ms-playwright/chromium-1187/chrome-linux/chrome")

    mock_playwright = MagicMock()
    mock_playwright.chromium.executable_path = str(fake_full)
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_playwright)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    fake_shell = Path(
        "/tmp/cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell"
    )

    with (
        patch.object(chromium, "sync_playwright", return_value=mock_ctx),
        patch.object(chromium, "_headless_shell_beside", return_value=fake_shell) as mock_beside,
    ):
        result = _resolve_chromium_path()
        assert result == str(fake_shell)
        mock_beside.assert_called_once_with(fake_full)


@pytest.mark.unit
def test_resolve_chromium_path_falls_back_to_full_when_no_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_CHROMIUM_PATH", None)
    fake_full = Path("/tmp/cache/ms-playwright/chromium-1187/chrome-linux/chrome")
    mock_playwright = MagicMock()
    mock_playwright.chromium.executable_path = str(fake_full)
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_playwright)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with (
        patch.object(chromium, "sync_playwright", return_value=mock_ctx),
        patch.object(chromium, "_headless_shell_beside", return_value=None),
    ):
        assert _resolve_chromium_path() == str(fake_full)


# ---------------------------------------------------------------------------
# cookie conversion
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cdp_cookie_to_storage_state_basic() -> None:
    cdp_cookie = {
        "name": "a",
        "value": "b",
        "domain": "example.com",
        "path": "/",
        "expires": 123,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    }
    out = _cdp_cookie_to_storage_state(cdp_cookie)
    assert out["name"] == "a"
    assert out["value"] == "b"
    assert out["domain"] == "example.com"
    assert out["path"] == "/"
    assert out["expires"] == 123
    assert out["httpOnly"] is True
    assert out["secure"] is True
    assert out["sameSite"] == "Lax"


@pytest.mark.unit
def test_cdp_cookie_to_storage_state_defaults_and_no_samesite() -> None:
    cdp_cookie: dict = {
        "name": "x",
        "value": "y",
        "domain": "example.com",
        "path": "/foo",
    }
    out = _cdp_cookie_to_storage_state(cdp_cookie)
    assert out["expires"] == -1
    assert out["httpOnly"] is False
    assert out["secure"] is False
    assert "sameSite" not in out


@pytest.mark.unit
def test_cdp_cookie_to_storage_state_empty_samesite_not_included() -> None:
    cdp_cookie = {
        "name": "x",
        "value": "y",
        "domain": "example.com",
        "path": "/",
        "sameSite": "",
    }
    out = _cdp_cookie_to_storage_state(cdp_cookie)
    assert "sameSite" not in out


@pytest.mark.unit
def test_storage_state_cookie_to_cdp_basic() -> None:
    cookie = {
        "name": "n",
        "value": "v",
        "domain": "example.com",
        "path": "/a",
        "secure": True,
        "httpOnly": True,
        "expires": 999,
        "sameSite": "Strict",
    }
    out = _storage_state_cookie_to_cdp(cookie)
    assert out["name"] == "n"
    assert out["value"] == "v"
    assert out["domain"] == "example.com"
    assert out["path"] == "/a"
    assert out["secure"] is True
    assert out["httpOnly"] is True
    assert out["expires"] == 999
    assert out["sameSite"] == "Strict"


@pytest.mark.unit
def test_storage_state_cookie_to_cdp_defaults() -> None:
    cookie: dict = {"name": "n", "value": "v", "domain": "example.com"}
    out = _storage_state_cookie_to_cdp(cookie)
    assert out["path"] == "/"
    assert out["secure"] is False
    assert out["httpOnly"] is False
    assert "expires" not in out
    assert "sameSite" not in out


@pytest.mark.unit
def test_storage_state_cookie_to_cdp_zero_expires_not_included() -> None:
    cookie: dict = {"name": "n", "value": "v", "domain": "example.com", "expires": 0}
    out = _storage_state_cookie_to_cdp(cookie)
    assert "expires" not in out


@pytest.mark.unit
def test_storage_state_cookie_to_cdp_negative_expires_not_included() -> None:
    cookie: dict = {"name": "n", "value": "v", "domain": "example.com", "expires": -1}
    out = _storage_state_cookie_to_cdp(cookie)
    assert "expires" not in out


@pytest.mark.unit
def test_storage_state_cookie_to_cdp_expires_exactly_one_is_included() -> None:
    # The boundary the ``> 0`` check exists for: 1 is the smallest expiry that
    # must survive. A ``> 1`` mutant drops exactly this value.
    cookie: dict = {"name": "n", "value": "v", "domain": "example.com", "expires": 1}
    out = _storage_state_cookie_to_cdp(cookie)
    assert out["expires"] == 1


@pytest.mark.unit
def test_storage_state_cookie_to_cdp_empty_samesite_not_included() -> None:
    cookie: dict = {"name": "n", "value": "v", "domain": "example.com", "sameSite": ""}
    out = _storage_state_cookie_to_cdp(cookie)
    assert "sameSite" not in out


# ---------------------------------------------------------------------------
# cdp_call success path
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_cdp_call_success_returns_value() -> None:
    fake = MagicMock()
    fake.send_raw = AsyncMock(return_value={"ok": 1})
    result = await cdp_call(fake, "Page.enable", {"a": 1}, timeout=1.0)
    assert result == {"ok": 1}
    fake.send_raw.assert_awaited_once_with("Page.enable", {"a": 1}, session_id=None)


@pytest.mark.unit
async def test_cdp_call_forwards_session_id() -> None:
    fake = MagicMock()
    fake.send_raw = AsyncMock(return_value={"x": 1})
    await cdp_call(fake, "Runtime.evaluate", {"expr": "1"}, session_id="sess123", timeout=1.0)
    fake.send_raw.assert_awaited_once_with("Runtime.evaluate", {"expr": "1"}, session_id="sess123")


# ---------------------------------------------------------------------------
# ChromiumHost helpers: root_ws_url / chromium_up / get / touch / viewer
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_root_ws_url_raises_when_not_started() -> None:
    host = ChromiumHost()
    with pytest.raises(RuntimeError, match="not started"):
        _ = host.root_ws_url


@pytest.mark.unit
def test_root_ws_url_returns_when_started() -> None:
    host = ChromiumHost()
    host._root_ws_url = "ws://127.0.0.1:1234"
    assert host.root_ws_url == "ws://127.0.0.1:1234"


@pytest.mark.unit
def test_chromium_up_false_when_no_proc() -> None:
    host = ChromiumHost()
    assert host.chromium_up is False


@pytest.mark.unit
def test_chromium_up_false_when_returncode_not_none() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=1)
    assert host.chromium_up is False


@pytest.mark.unit
def test_chromium_up_true_when_returncode_none() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    assert host.chromium_up is True


@pytest.mark.unit
def test_get_returns_none_for_unknown() -> None:
    host = ChromiumHost()
    assert host.get("ghost") is None


@pytest.mark.unit
def test_get_returns_session() -> None:
    host = ChromiumHost()
    s = make_session(session_id="s1", context_id="ctx1", target_id="t1", last_activity_at=0)
    host._sessions["s1"] = s
    assert host.get("s1") is s


@pytest.mark.unit
def test_touch_updates_monotonic(monkeypatch: pytest.MonkeyPatch) -> None:
    host = ChromiumHost()
    s = make_session(session_id="s1", context_id="ctx1", target_id="t1", last_activity_at=0)
    host._sessions["s1"] = s
    monkeypatch.setattr(time, "monotonic", lambda: 42.0)
    host.touch("s1")
    assert s.last_activity_at == 42.0


@pytest.mark.unit
def test_touch_noop_for_unknown() -> None:
    host = ChromiumHost()

    host.touch("ghost")

    # Not just "did not raise": an unknown id must not be registered as a
    # side effect of being touched.
    assert host._sessions == {}


@pytest.mark.unit
def test_add_viewer_increments_and_touches(monkeypatch: pytest.MonkeyPatch) -> None:
    host = ChromiumHost()
    s = make_session(session_id="s1", context_id="ctx1", target_id="t1", last_activity_at=0)
    host._sessions["s1"] = s
    monkeypatch.setattr(time, "monotonic", lambda: 99.0)
    host.add_viewer("s1")
    assert s.viewer_count == 1
    assert s.last_activity_at == 99.0
    host.add_viewer("s1")
    assert s.viewer_count == 2


@pytest.mark.unit
def test_add_viewer_noop_for_unknown() -> None:
    host = ChromiumHost()

    host.add_viewer("ghost")

    # A phantom viewer on an unknown id would pin a session the reaper
    # can never collect, so the registry must stay empty.
    assert host._sessions == {}


@pytest.mark.unit
def test_remove_viewer_decrements_and_clamps(monkeypatch: pytest.MonkeyPatch) -> None:
    host = ChromiumHost()
    s = replace(
        make_session(session_id="s1", context_id="ctx1", target_id="t1", last_activity_at=5.0),
        viewer_count=1,
    )
    host._sessions["s1"] = s
    monkeypatch.setattr(time, "monotonic", lambda: 100.0)
    host.remove_viewer("s1")
    assert s.viewer_count == 0
    assert s.last_activity_at == 100.0
    host.remove_viewer("s1")
    assert s.viewer_count == 0  # clamped


@pytest.mark.unit
def test_remove_viewer_noop_for_unknown() -> None:
    host = ChromiumHost()

    host.remove_viewer("ghost")

    assert host._sessions == {}


@pytest.mark.unit
def test_get_internal_raises_session_not_found() -> None:
    host = ChromiumHost()
    with pytest.raises(SessionNotFoundError):
        host._get("ghost")


@pytest.mark.unit
def test_get_internal_returns_session() -> None:
    host = ChromiumHost()
    s = make_session(session_id="s1", context_id="ctx1", target_id="t1", last_activity_at=0)
    host._sessions["s1"] = s
    assert host._get("s1") is s


# ---------------------------------------------------------------------------
# _reserve_slot
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_reserve_slot_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 2)
    host = ChromiumHost()
    await host._reserve_slot()
    assert host._pending_slots == 1
    await host._reserve_slot()
    assert host._pending_slots == 2


@pytest.mark.unit
async def test_reserve_slot_at_capacity_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 1)
    host = ChromiumHost()
    await host._reserve_slot()
    from app.browser_host.chromium import AtCapacityError

    with pytest.raises(AtCapacityError):
        await host._reserve_slot()


@pytest.mark.unit
async def test_reserve_slot_counts_existing_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 2)
    host = ChromiumHost()
    s = make_session(session_id="s1", context_id="ctx1", target_id="t1", last_activity_at=0)
    host._sessions["s1"] = s
    host._pending_slots = 1  # 1 session + 1 pending = 2 => at capacity
    from app.browser_host.chromium import AtCapacityError

    with pytest.raises(AtCapacityError):
        await host._reserve_slot()


# --- memory-based admission (the real gate; the count is only a backstop) ---


@pytest.mark.unit
async def test_reserve_slot_admits_past_the_old_static_cap_when_memory_is_ample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With headroom (and the count backstop disabled), admission isn't capped at a small count."""
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (100.0, 100_000.0))
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 0)  # 0 = no count backstop
    host = ChromiumHost()
    for _ in range(50):
        await host._reserve_slot()
    assert host._pending_slots == 50  # far past the old static cap of 6


@pytest.mark.unit
async def test_reserve_slot_refuses_when_projected_usage_exceeds_high_watermark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Near the memory limit a new session is refused rather than risking an OOM."""
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (980.0, 1000.0))  # 98% used
    monkeypatch.setattr(settings, "BROWSER_HOST_MEMORY_HIGH_WATERMARK", 0.85)
    host = ChromiumHost()
    from app.browser_host.chromium import AtCapacityError

    with pytest.raises(AtCapacityError):
        await host._reserve_slot()


@pytest.mark.unit
async def test_reserve_slot_reserves_for_pending_creates_so_a_burst_cannot_overshoot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each in-flight create is charged an estimate, so a burst can't all pass at once."""
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (700.0, 1000.0))
    monkeypatch.setattr(settings, "BROWSER_HOST_MEMORY_HIGH_WATERMARK", 0.85)  # hard = 850
    monkeypatch.setattr(settings, "BROWSER_HOST_SESSION_COST_FLOOR_MB", 50)
    host = ChromiumHost()
    from app.browser_host.chromium import AtCapacityError

    # 700 + n*50 must stay <= 850: three admit (750/800/850), the fourth (900) is refused.
    await host._reserve_slot()
    await host._reserve_slot()
    await host._reserve_slot()
    assert host._pending_slots == 3
    with pytest.raises(AtCapacityError):
        await host._reserve_slot()


@pytest.mark.unit
async def test_estimate_session_cost_is_measured_average_floored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_SESSION_COST_FLOOR_MB", 50)
    host = ChromiumHost()
    host._base_memory_mb = 100.0
    host._sessions = {
        f"s{i}": make_session(session_id=f"s{i}", context_id="c", target_id="t", last_activity_at=0)
        for i in range(3)
    }
    # overhead 300 / 3 sessions = 100/session, above the floor
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (400.0, 1000.0))
    assert host._estimate_session_cost_mb() == 100.0
    # overhead 60 / 3 = 20/session, below the floor -> floored
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (160.0, 1000.0))
    assert host._estimate_session_cost_mb() == 50.0


@pytest.mark.unit
async def test_reap_idle_shortens_ttl_under_memory_pressure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Above the soft watermark an idle session past the shortened TTL is reaped early."""
    monkeypatch.setattr(settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 300)
    monkeypatch.setattr(settings, "BROWSER_HOST_MEMORY_SOFT_WATERMARK", 0.75)
    host = make_host()
    # 100s idle: within the full 300s TTL, but past the pressure TTL (300/4 = 75s).
    idle = make_session(
        session_id="s1",
        context_id="c1",
        target_id="t1",
        last_activity_at=time.monotonic() - 100,
    )
    host._sessions = {"s1": idle}

    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (100.0, 1000.0))  # 10% — no pressure
    await host._reap_idle()
    assert "s1" in host._sessions

    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (800.0, 1000.0))  # 80% — pressure
    await host._reap_idle()
    assert "s1" not in host._sessions
    assert idle.mux.closed is True


# ---------------------------------------------------------------------------
# _close_session_connection
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_close_session_connection_skips_the_dispose_when_chromium_down() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=1)  # dead
    session = make_session()

    await host._close_session_connection(session)

    assert session.mux.calls == []
    # The socket is closed regardless: it is what actually frees the session.
    assert session.mux.closed is True


@pytest.mark.unit
async def test_close_session_connection_disposes_over_that_session_when_up() -> None:
    host = make_host()
    session = make_session(context_id="ctx1")

    await host._close_session_connection(session)

    assert session.mux.calls == [
        ("Target.disposeBrowserContext", {"browserContextId": "ctx1"}, None)
    ]
    assert session.mux.closed is True


@pytest.mark.unit
async def test_close_session_connection_skips_the_dispose_on_an_already_closed_socket() -> None:
    """Disposing over a closed connection would only raise; the close is still what matters."""
    host = make_host()
    session = make_session()
    await session.mux.close()

    await host._close_session_connection(session)

    assert session.mux.calls == []
    assert session.mux.close_count == 2


@pytest.mark.unit
async def test_close_session_connection_still_closes_when_the_dispose_raises() -> None:
    host = make_host()
    session = make_session(
        mux=FakeMux(fail_on_first_call={"Target.disposeBrowserContext": RuntimeError("boom")})
    )

    await host._close_session_connection(session)

    # Swallowing is only correct if it actually TRIED first — a mutant that
    # skips the CDP call entirely would also "not raise".
    assert session.mux.methods == ["Target.disposeBrowserContext"]
    assert session.mux.closed is True


@pytest.mark.unit
async def test_close_session_connection_skips_the_dispose_when_there_is_no_process() -> None:
    host = ChromiumHost()
    host._proc = None
    session = make_session()

    await host._close_session_connection(session)

    assert session.mux.calls == []
    assert session.mux.closed is True


# ---------------------------------------------------------------------------
# _seed_cookies
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_seed_cookies_no_cookies() -> None:
    host = ChromiumHost()
    mux = FakeMux()
    await host._seed_cookies(mux, "ctx1", {"cookies": [], "origins": []})
    assert mux.calls == []
    await host._seed_cookies(mux, "ctx1", {"cookies": None, "origins": []})
    assert mux.calls == []


@pytest.mark.unit
async def test_seed_cookies_with_cookies() -> None:
    host = ChromiumHost()
    mux = FakeMux()
    state = {
        "cookies": [
            {
                "name": "a",
                "value": "b",
                "domain": "example.com",
                "path": "/",
                "expires": -1,
                "httpOnly": False,
                "secure": False,
            },
        ],
        "origins": [],
    }
    await host._seed_cookies(mux, "ctx1", state)
    assert mux.methods == ["Storage.setCookies"]
    sent = mux.params_for("Storage.setCookies")[0]
    assert sent is not None
    assert sent["browserContextId"] == "ctx1"
    assert len(sent["cookies"]) == 1


# ---------------------------------------------------------------------------
# _dump_storage_state
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_dump_storage_state_when_chromium_down() -> None:
    host = ChromiumHost()
    host._proc = None  # chromium_up false
    s = make_session(session_id="s1", context_id="ctx1", target_id="t1", last_activity_at=0)
    result = await host._dump_storage_state(s)
    assert result == {"cookies": [], "origins": []}


@pytest.mark.unit
async def test_dump_storage_state_when_up() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    cdp_cookie = {
        "name": "a",
        "value": "b",
        "domain": "example.com",
        "path": "/",
        "expires": -1,
        "httpOnly": False,
        "secure": False,
    }
    host._dump_origins = AsyncMock(
        return_value=[
            {"origin": "https://example.com", "localStorage": [{"name": "k", "value": "v"}]}
        ]
    )
    s = make_session(mux=FakeMux({"Storage.getCookies": {"cookies": [cdp_cookie]}}))
    result = await host._dump_storage_state(s)
    assert len(result["cookies"]) == 1
    assert result["cookies"][0]["name"] == "a"
    assert result["origins"][0]["origin"] == "https://example.com"


# ---------------------------------------------------------------------------
# _dump_origins
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_dump_origins_no_pages() -> None:
    host = ChromiumHost()
    s = make_session(mux=FakeMux({"Target.getTargets": {"targetInfos": []}}))
    result = await host._dump_origins(s)
    assert result == []


@pytest.mark.unit
async def test_dump_origins_single_page_with_storage() -> None:
    host = ChromiumHost()
    s = make_session(
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx1"}]
                },
                "Target.attachToTarget": {"sessionId": "sess-t1"},
                "Runtime.evaluate": {
                    "result": {
                        "value": {
                            "origin": "https://example.com",
                            "localStorage": [{"name": "k", "value": "v"}],
                        }
                    }
                },
            }
        )
    )
    result = await host._dump_origins(s)
    assert len(result) == 1
    assert result[0]["origin"] == "https://example.com"


@pytest.mark.unit
async def test_dump_origins_filters_other_context_and_non_page() -> None:
    host = ChromiumHost()
    s = make_session(
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [
                        {"targetId": "t1", "type": "page", "browserContextId": "other"},
                        {"targetId": "t2", "type": "background_page", "browserContextId": "ctx1"},
                        {"targetId": "t3", "type": "page", "browserContextId": "ctx1"},
                    ]
                },
                "Target.attachToTarget": {"sessionId": "sess-t3"},
                "Runtime.evaluate": {
                    "result": {
                        "value": {
                            "origin": "https://example.com",
                            "localStorage": [{"name": "k", "value": "v"}],
                        }
                    }
                },
            }
        )
    )
    result = await host._dump_origins(s)
    assert len(result) == 1
    # only t3 should be visited, so attach was for t3
    assert s.mux.params_for("Target.attachToTarget") == [{"targetId": "t3", "flatten": True}]


@pytest.mark.unit
async def test_dump_origins_empty_value_skipped() -> None:
    host = ChromiumHost()
    s = make_session(
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx1"}]
                },
                "Target.attachToTarget": {"sessionId": "sess-t1"},
                "Runtime.evaluate": {"result": {"value": None}},
            }
        )
    )
    result = await host._dump_origins(s)
    assert result == []


@pytest.mark.unit
async def test_dump_origins_missing_origin_skipped() -> None:
    host = ChromiumHost()
    s = make_session(
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx1"}]
                },
                "Target.attachToTarget": {"sessionId": "sess-t1"},
                "Runtime.evaluate": {
                    "result": {
                        "value": {"origin": "", "localStorage": [{"name": "k", "value": "v"}]}
                    }
                },
            }
        )
    )
    result = await host._dump_origins(s)
    assert result == []


@pytest.mark.unit
async def test_dump_origins_empty_localstorage_skipped() -> None:
    host = ChromiumHost()
    s = make_session(
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx1"}]
                },
                "Target.attachToTarget": {"sessionId": "sess-t1"},
                "Runtime.evaluate": {
                    "result": {"value": {"origin": "https://example.com", "localStorage": []}}
                },
            }
        )
    )
    result = await host._dump_origins(s)
    assert result == []


@pytest.mark.unit
async def test_dump_origins_missing_result_key_yields_no_origin_not_a_crash() -> None:
    # The "result" key's default must be a dict ({}), not None, or the
    # chained ``.get("value")`` blows up with AttributeError instead of
    # cleanly skipping this page.
    host = ChromiumHost()
    s = make_session(
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx1"}]
                },
                "Target.attachToTarget": {"sessionId": "sess-t1"},
                "Runtime.evaluate": {},
            }
        )
    )
    result = await host._dump_origins(s)
    assert result == []


@pytest.mark.unit
async def test_dump_origins_detaches_even_when_evaluate_raises() -> None:
    host = ChromiumHost()
    s = make_session(
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx1"}]
                },
                "Target.attachToTarget": {"sessionId": "sess-t1"},
            },
            fail_on_first_call={"Runtime.evaluate": RuntimeError("eval boom")},
        )
    )
    with pytest.raises(RuntimeError, match="eval boom"):
        await host._dump_origins(s)

    # The flat page session must be released even though the evaluate blew up.
    assert s.mux.params_for("Target.detachFromTarget") == [{"sessionId": "sess-t1"}]


# ---------------------------------------------------------------------------
# _focused_page_meta
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_focused_page_meta_when_chromium_down() -> None:
    host = ChromiumHost()
    host._proc = None
    s = make_session(session_id="s1", context_id="ctx1", target_id="t1", last_activity_at=0)
    url, title = await host._focused_page_meta(s)
    assert url is None and title is None


@pytest.mark.unit
async def test_focused_page_meta_returns_url_title() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    s = make_session(
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [
                        {
                            "type": "page",
                            "browserContextId": "ctx1",
                            "url": "https://example.com",
                            "title": "Example",
                        },
                        {
                            "type": "page",
                            "browserContextId": "other",
                            "url": "https://other.com",
                            "title": "Other",
                        },
                    ]
                }
            }
        )
    )
    url, title = await host._focused_page_meta(s)
    assert url == "https://example.com"
    assert title == "Example"


@pytest.mark.unit
async def test_focused_page_meta_no_matching_page_returns_none() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    s = make_session(
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [
                        {"type": "page", "browserContextId": "other", "url": "https://other.com"}
                    ]
                }
            }
        )
    )
    url, title = await host._focused_page_meta(s)
    assert url is None and title is None


# ---------------------------------------------------------------------------
# focused_target_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_focused_target_id_returns_primary_when_no_pages() -> None:
    host = ChromiumHost()
    s = make_session(target_id="t-primary", mux=FakeMux({"Target.getTargets": {"targetInfos": []}}))
    host._sessions["s1"] = s
    result = await host.focused_target_id("s1")
    assert result == "t-primary"


@pytest.mark.unit
async def test_focused_target_id_returns_primary_when_present() -> None:
    host = ChromiumHost()
    s = make_session(
        target_id="t-primary",
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [
                        {"type": "page", "browserContextId": "ctx1", "targetId": "t-other"},
                        {"type": "page", "browserContextId": "ctx1", "targetId": "t-primary"},
                    ]
                }
            }
        ),
    )
    host._sessions["s1"] = s
    result = await host.focused_target_id("s1")
    assert result == "t-primary"


@pytest.mark.unit
async def test_focused_target_id_fallback_to_most_recent() -> None:
    host = ChromiumHost()
    s = make_session(
        target_id="t-primary",
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [
                        {"type": "page", "browserContextId": "ctx1", "targetId": "t1"},
                        {"type": "page", "browserContextId": "ctx1", "targetId": "t2"},
                    ]
                }
            }
        ),
    )
    host._sessions["s1"] = s
    result = await host.focused_target_id("s1")
    assert result == "t2"


@pytest.mark.unit
async def test_focused_target_id_filters_by_context_and_type() -> None:
    host = ChromiumHost()
    s = make_session(
        target_id="t-primary",
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [
                        {"type": "background_page", "browserContextId": "ctx1", "targetId": "bg"},
                        {"type": "page", "browserContextId": "other", "targetId": "other"},
                        {"type": "page", "browserContextId": "ctx1", "targetId": "t-good"},
                    ]
                }
            }
        ),
    )
    host._sessions["s1"] = s
    result = await host.focused_target_id("s1")
    assert result == "t-good"


@pytest.mark.unit
async def test_focused_target_id_excludes_a_page_from_another_context() -> None:
    """Require type=="page" and matching context; an or would leak cross-context pages in."""
    host = ChromiumHost()
    s = make_session(
        target_id="t-primary",
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [
                        {
                            "type": "page",
                            "browserContextId": "other-ctx",
                            "targetId": "cross-target",
                        },
                    ]
                }
            }
        ),
    )
    host._sessions["s1"] = s
    result = await host.focused_target_id("s1")
    assert result == "t-primary"


@pytest.mark.unit
async def test_focused_target_id_raises_for_unknown_session() -> None:
    host = ChromiumHost()
    with pytest.raises(SessionNotFoundError):
        await host.focused_target_id("ghost")


# ---------------------------------------------------------------------------
# session_info
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_session_info_returns_expected_shape() -> None:
    host = ChromiumHost()
    s = make_session(session_id="s1", context_id="ctx1", target_id="t1", last_activity_at=20)
    host._sessions["s1"] = s
    host._proc = MagicMock(returncode=None)
    host._focused_page_meta = AsyncMock(return_value=("https://example.com", "Example"))
    info = await host.session_info("s1")
    assert info["session_id"] == "s1"
    assert info["live"] is True
    assert info["last_activity_at"] == 20
    assert info["url"] == "https://example.com"
    assert info["title"] == "Example"


@pytest.mark.unit
async def test_session_info_live_false_when_chromium_down() -> None:
    host = ChromiumHost()
    s = make_session(
        session_id="s1",
        context_id="ctx1",
        target_id="t1",
        last_activity_at=0,
    )
    host._sessions["s1"] = s
    host._proc = None
    host._focused_page_meta = AsyncMock(return_value=(None, None))
    info = await host.session_info("s1")
    assert info["live"] is False


@pytest.mark.unit
async def test_session_info_live_false_when_dead() -> None:
    host = ChromiumHost()
    s = replace(make_session(session_id="s1", context_id="ctx1", target_id="t1"), dead=True)
    host._sessions["s1"] = s
    host._proc = MagicMock(returncode=None)
    host._focused_page_meta = AsyncMock(return_value=("https://example.com", "Title"))
    info = await host.session_info("s1")
    assert info["live"] is False


@pytest.mark.unit
async def test_session_info_raises_for_unknown() -> None:
    host = ChromiumHost()
    with pytest.raises(SessionNotFoundError):
        await host.session_info("ghost")


# ---------------------------------------------------------------------------
# healthz
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_healthz_chromium_down_reports_not_ok() -> None:
    host = ChromiumHost()
    host._proc = None
    result = await host.healthz()
    assert result["ok"] is False
    assert result["chromium_up"] is False
    assert result["cdp_responsive"] is False
    assert result["sessions"] == 0


@pytest.mark.unit
async def test_healthz_counts_sessions() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    s = make_session(session_id="s1", context_id="ctx1", target_id="t1", last_activity_at=0)
    host._sessions["s1"] = s
    host._root_mux = FakeMux()
    result = await host.healthz()
    assert result["sessions"] == 1
    assert result["ok"] is True


@pytest.mark.unit
async def test_healthz_reports_unresponsive_when_the_root_connection_is_not_open() -> None:
    """An alive process with no root connection is not a healthy host."""
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)

    result = await host.healthz()

    assert result == {"ok": False, "sessions": 0, "chromium_up": True, "cdp_responsive": False}


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_start_resolves_path_launches_and_starts_reaper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = ChromiumHost()
    to_thread_mock = AsyncMock(return_value="/tmp/chrome")
    monkeypatch.setattr(chromium.asyncio, "to_thread", to_thread_mock)
    host._launch = AsyncMock()
    host._reaper_loop = AsyncMock()
    await host.start()
    assert host._chromium_path == "/tmp/chrome"
    # Must resolve the real binary, not just call to_thread with anything.
    to_thread_mock.assert_awaited_once_with(chromium._resolve_chromium_path)
    host._launch.assert_awaited_once()
    assert host._reaper_task is not None
    # cleanup
    host._reaper_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await host._reaper_task


@pytest.mark.unit
async def test_stop_cancels_reaper_and_shuts_down() -> None:
    host = ChromiumHost()
    host._reaper_task = asyncio.create_task(asyncio.sleep(10))
    host._shutdown_chromium = AsyncMock()
    await host.stop()
    assert host._reaper_task is None
    host._shutdown_chromium.assert_awaited_once()


@pytest.mark.unit
async def test_stop_no_reaper_still_shuts_down() -> None:
    host = ChromiumHost()
    host._shutdown_chromium = AsyncMock()
    await host.stop()
    host._shutdown_chromium.assert_awaited_once()


# ---------------------------------------------------------------------------
# create_context / dispose_context integration over a fake session connection
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_create_context_without_storage_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host, mux = _host_and_mux(
        monkeypatch,
        {
            "Target.createBrowserContext": {"browserContextId": "ctx-1"},
            "Target.createTarget": {"targetId": "t-1"},
        },
    )
    session = await host.create_context(None)
    assert session.context_id == "ctx-1"
    assert session.target_id == "t-1"
    assert session.mux is mux
    assert host.get(session.session_id) is not None
    assert host._pending_slots == 0


@pytest.mark.unit
async def test_create_context_with_storage_state_seeds_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host, mux = _host_and_mux(
        monkeypatch,
        {
            "Target.createBrowserContext": {"browserContextId": "ctx-1"},
            "Target.createTarget": {"targetId": "t-1"},
        },
    )
    state = {
        "cookies": [
            {
                "name": "a",
                "value": "b",
                "domain": "example.com",
                "path": "/",
                "secure": False,
                "httpOnly": False,
            }
        ],
        "origins": [],
    }
    session = await host.create_context(state)
    assert session.context_id == "ctx-1"
    assert mux.methods == [
        "Target.createBrowserContext",
        "Browser.setDownloadBehavior",
        "Target.createTarget",
        "Storage.setCookies",
    ]


@pytest.mark.unit
async def test_create_context_failure_disposes_context_and_releases_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host, mux = _host_and_mux(
        monkeypatch,
        {"Target.createBrowserContext": {"browserContextId": "ctx-1"}},
    )
    mux.fail_on_first_call["Browser.setDownloadBehavior"] = RuntimeError("setDownloadBehavior boom")
    with pytest.raises(RuntimeError, match="boom"):
        await host.create_context(None)
    assert host._pending_slots == 0
    # The half-built context dies with the connection that owns it.
    assert mux.closed is True


@pytest.mark.unit
async def test_create_context_at_capacity_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 1)
    host = make_host()
    host._sessions["existing"] = make_session(
        session_id="existing", context_id="ctx0", target_id="t0", last_activity_at=0
    )
    from app.browser_host.chromium import AtCapacityError

    with pytest.raises(AtCapacityError):
        await host.create_context(None)


@pytest.mark.unit
async def test_dispose_context_success() -> None:
    host = make_host()
    s = make_session()
    host._sessions["s1"] = s
    host._dump_storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    result = await host.dispose_context("s1")
    assert result == {"cookies": [], "origins": []}
    assert host.get("s1") is None
    assert s.mux.params_for("Target.disposeBrowserContext") == [{"browserContextId": "ctx1"}]
    assert s.mux.closed is True


@pytest.mark.unit
async def test_dispose_context_raises_when_unknown() -> None:
    host = ChromiumHost()
    with pytest.raises(SessionNotFoundError):
        await host.dispose_context("ghost")


@pytest.mark.unit
async def test_dispose_context_pop_tolerates_concurrent_removal() -> None:
    """The finally block's pop must not KeyError when a concurrent caller already removed the session."""
    host = make_host()
    s = make_session()
    host._sessions["s1"] = s

    async def _dump_and_vanish(_session: HostSession) -> dict[str, Any]:
        host._sessions.pop("s1", None)
        return {"cookies": [], "origins": []}

    host._dump_storage_state = _dump_and_vanish

    result = await host.dispose_context("s1")

    assert result == {"cookies": [], "origins": []}
    assert s.mux.params_for("Target.disposeBrowserContext") == [{"browserContextId": "ctx1"}]
    assert s.mux.closed is True


# ---------------------------------------------------------------------------
# _launch arg composition
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_launch_builds_correct_args_headed_false_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = ChromiumHost()
    fake_path = tmp_path / "headless_shell"
    fake_path.write_text("x")
    host._chromium_path = str(fake_path)
    host._user_data_dir = None
    monkeypatch.setattr(settings, "BROWSER_HOST_JS_HEAP_MB", 512)
    monkeypatch.setattr(settings, "BROWSER_HOST_HEADED", False)
    monkeypatch.setattr(chromium, "CHROME_DEFAULT_ARGS", ("--no-first-run",))
    monkeypatch.setattr(chromium, "_HOST_EXTRA_ARGS", ("--no-sandbox",))
    # patch internals
    monkeypatch.setattr(chromium.tempfile, "mkdtemp", lambda prefix: str(tmp_path / "udir"))
    mock_proc = MagicMock(returncode=None)
    mock_create = AsyncMock(return_value=mock_proc)
    monkeypatch.setattr(chromium.asyncio, "create_subprocess_exec", mock_create)
    host._await_cdp_ready = AsyncMock(return_value="ws://127.0.0.1:9222")
    mock_mux = MagicMock()
    mock_mux.start = AsyncMock()
    with patch.object(chromium, "CdpMux", return_value=mock_mux):
        await host._launch()
    # check args contain expected flags
    args = mock_create.call_args[0]
    assert str(fake_path) in args
    assert "--remote-debugging-port=0" in args
    assert "--headless" in args  # shell => bare flag
    assert "--headless=new" not in args
    assert "--no-sandbox" in args
    assert "--no-first-run" in args
    assert any("max-old-space-size=512" in a for a in args)


@pytest.mark.unit
async def test_launch_headed_false_full_browser_uses_headless_new(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = ChromiumHost()
    fake_path = tmp_path / "chrome"
    fake_path.write_text("x")
    host._chromium_path = str(fake_path)
    monkeypatch.setattr(settings, "BROWSER_HOST_JS_HEAP_MB", 256)
    monkeypatch.setattr(settings, "BROWSER_HOST_HEADED", False)
    monkeypatch.setattr(chromium, "CHROME_DEFAULT_ARGS", ())
    monkeypatch.setattr(chromium, "_HOST_EXTRA_ARGS", ())
    monkeypatch.setattr(chromium.tempfile, "mkdtemp", lambda prefix: str(tmp_path / "udir2"))
    mock_proc = MagicMock(returncode=None)
    monkeypatch.setattr(
        chromium.asyncio, "create_subprocess_exec", AsyncMock(return_value=mock_proc)
    )
    host._await_cdp_ready = AsyncMock(return_value="ws://x")
    mock_mux = MagicMock()
    mock_mux.start = AsyncMock()
    with patch.object(chromium, "CdpMux", return_value=mock_mux):
        await host._launch()
        args = chromium.asyncio.create_subprocess_exec.call_args[0]
        assert "--headless=new" in args


@pytest.mark.unit
async def test_launch_headed_true_no_headless_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = ChromiumHost()
    fake_path = tmp_path / "chrome"
    host._chromium_path = str(fake_path)
    monkeypatch.setattr(settings, "BROWSER_HOST_HEADED", True)
    monkeypatch.setattr(settings, "BROWSER_HOST_JS_HEAP_MB", 256)
    monkeypatch.setattr(chromium, "CHROME_DEFAULT_ARGS", ())
    monkeypatch.setattr(chromium, "_HOST_EXTRA_ARGS", ())
    monkeypatch.setattr(chromium.tempfile, "mkdtemp", lambda prefix: str(tmp_path / "udir3"))
    monkeypatch.setattr(
        chromium.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=MagicMock(returncode=None)),
    )
    host._await_cdp_ready = AsyncMock(return_value="ws://x")
    mock_mux = MagicMock()
    mock_mux.start = AsyncMock()
    with patch.object(chromium, "CdpMux", return_value=mock_mux):
        await host._launch()
        args = chromium.asyncio.create_subprocess_exec.call_args[0]
        assert "--headless" not in args and "--headless=new" not in args


# ---------------------------------------------------------------------------
# _await_cdp_ready
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_await_cdp_ready_success(monkeypatch: pytest.MonkeyPatch) -> None:
    host = ChromiumHost()
    host._user_data_dir = "/tmp/fake"
    host._read_devtools_port = AsyncMock(return_value=9222)

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools"}
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch.object(chromium.httpx, "AsyncClient", return_value=mock_client):
        url = await host._await_cdp_ready()
        assert url == "ws://127.0.0.1:9222/devtools"


@pytest.mark.unit
async def test_await_cdp_ready_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    host = ChromiumHost()
    host._read_devtools_port = AsyncMock(return_value=9222)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools"}
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=[httpx.ConnectError("nope"), mock_resp])

    with patch.object(chromium.httpx, "AsyncClient", return_value=mock_client):
        url = await host._await_cdp_ready()
        assert url == "ws://127.0.0.1:9222/devtools"
        assert mock_client.get.call_count == 2


@pytest.mark.unit
async def test_await_cdp_ready_stops_exactly_at_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At the deadline itself the poll loop must not run one more time."""
    host = ChromiumHost()
    host._read_devtools_port = AsyncMock(return_value=9222)
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 10.0)
    # First monotonic() call computes the deadline (0.0 + 10.0); the second is
    # the while-condition check, landing exactly on that deadline.
    monotonic_values = [0.0, 10.0]

    def _next_monotonic() -> float:
        # asyncio's own scheduler also calls the real time.monotonic (this
        # patches the actual stdlib function), so keep returning the deadline
        # forever after the two values the test cares about are consumed.
        return monotonic_values.pop(0) if monotonic_values else 10.0

    monkeypatch.setattr(chromium.time, "monotonic", _next_monotonic)
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(
        side_effect=AssertionError("must not poll once monotonic() reaches the deadline")
    )

    with patch.object(chromium.httpx, "AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="did not expose"):
            await host._await_cdp_ready()

    mock_client.get.assert_not_called()


@pytest.mark.unit
async def test_await_cdp_ready_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    host = ChromiumHost()
    host._read_devtools_port = AsyncMock(return_value=9222)
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("nope"))
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(chromium, "_CDP_READY_POLL_SECONDS", 0.05)
    with patch.object(chromium.httpx, "AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="did not expose"):
            await host._await_cdp_ready()


# ---------------------------------------------------------------------------
# _read_devtools_port
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_read_devtools_port_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = ChromiumHost()
    host._user_data_dir = str(tmp_path)
    host._proc = MagicMock(returncode=None)
    port_file = tmp_path / "DevToolsActivePort"
    port_file.write_text("9222\n/devtools\n")
    monkeypatch.setattr(chromium, "_CDP_READY_POLL_SECONDS", 0.01)
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 0.5)
    port = await host._read_devtools_port()
    assert port == 9222


@pytest.mark.unit
async def test_read_devtools_port_empty_file_polls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = ChromiumHost()
    host._user_data_dir = str(tmp_path)
    host._proc = MagicMock(returncode=None)
    port_file = tmp_path / "DevToolsActivePort"
    port_file.write_text("")  # empty initially
    monkeypatch.setattr(chromium, "_CDP_READY_POLL_SECONDS", 0.02)
    # Generous, because the read returns the moment the file fills: a tight budget
    # only buys a flake on a loaded box, never a faster test.
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 10.0)

    async def delayed_write():
        await asyncio.sleep(0.06)
        port_file.write_text("9333\n")

    task = asyncio.create_task(delayed_write())
    port = await host._read_devtools_port()
    await task
    assert port == 9333


@pytest.mark.unit
async def test_read_devtools_port_process_died_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = ChromiumHost()
    host._user_data_dir = str(tmp_path)
    host._proc = MagicMock(returncode=1)  # already dead
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 0.5)
    with pytest.raises(RuntimeError, match="exited before publishing"):
        await host._read_devtools_port()


@pytest.mark.unit
async def test_read_devtools_port_timeout_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = ChromiumHost()
    host._user_data_dir = str(tmp_path)
    host._proc = MagicMock(returncode=None)
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 0.15)
    monkeypatch.setattr(chromium, "_CDP_READY_POLL_SECONDS", 0.02)
    with pytest.raises(RuntimeError, match="did not write DevToolsActivePort"):
        await host._read_devtools_port()


@pytest.mark.unit
async def test_read_devtools_port_stops_exactly_at_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At the deadline itself the poll loop must not run one more time."""
    host = ChromiumHost()
    host._user_data_dir = str(tmp_path)
    host._proc = MagicMock(returncode=None)
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 10.0)
    # First monotonic() call computes the deadline (0.0 + 10.0); the second is
    # the while-condition check, landing exactly on that deadline.
    monotonic_values = [0.0, 10.0]

    def _next_monotonic() -> float:
        # asyncio's own scheduler also calls the real time.monotonic (this
        # patches the actual stdlib function), so keep returning the deadline
        # forever after the two values the test cares about are consumed.
        return monotonic_values.pop(0) if monotonic_values else 10.0

    monkeypatch.setattr(chromium.time, "monotonic", _next_monotonic)
    sleep_mock = AsyncMock(
        side_effect=AssertionError("must not poll once monotonic() reaches the deadline")
    )
    monkeypatch.setattr(chromium.asyncio, "sleep", sleep_mock)

    with pytest.raises(RuntimeError, match="did not write DevToolsActivePort"):
        await host._read_devtools_port()

    sleep_mock.assert_not_called()


@pytest.mark.unit
async def test_read_devtools_port_non_digit_then_digit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = ChromiumHost()
    host._user_data_dir = str(tmp_path)
    host._proc = MagicMock(returncode=None)
    port_file = tmp_path / "DevToolsActivePort"
    port_file.write_text("not-a-port\n")
    monkeypatch.setattr(chromium, "_CDP_READY_POLL_SECONDS", 0.02)
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 10.0)

    async def fix_file():
        await asyncio.sleep(0.06)
        port_file.write_text("9444\n")

    task = asyncio.create_task(fix_file())
    port = await host._read_devtools_port()
    await task
    assert port == 9444


# ---------------------------------------------------------------------------
# _shutdown_chromium
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_shutdown_chromium_stops_cdp_and_terminates_proc() -> None:
    host = ChromiumHost()
    mock_mux = MagicMock()
    mock_mux.close = AsyncMock()
    host._root_mux = mock_mux
    mock_proc = MagicMock(returncode=None)
    mock_proc.terminate = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.kill = MagicMock()
    host._proc = mock_proc
    host._root_ws_url = "ws://x"
    await host._shutdown_chromium()
    mock_mux.close.assert_awaited_once()
    assert host._root_mux is None
    assert host._proc is None
    assert host._root_ws_url is None
    mock_proc.terminate.assert_called_once()


@pytest.mark.unit
async def test_shutdown_chromium_cdp_stop_failure_suppressed() -> None:
    host = ChromiumHost()
    mock_mux = MagicMock()
    mock_mux.close = AsyncMock(side_effect=RuntimeError("boom"))
    host._root_mux = mock_mux
    host._proc = None
    await host._shutdown_chromium()
    assert host._root_mux is None


@pytest.mark.unit
async def test_shutdown_chromium_kills_when_terminate_times_out() -> None:
    host = ChromiumHost()
    host._root_mux = None
    mock_proc = MagicMock(returncode=None)
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()

    async def slow_wait():
        await asyncio.sleep(10)

    mock_proc.wait = slow_wait
    host._proc = mock_proc
    with patch.object(chromium.asyncio, "wait_for", side_effect=TimeoutError):
        await host._shutdown_chromium()
    mock_proc.kill.assert_called_once()
    assert host._proc is None


@pytest.mark.unit
async def test_shutdown_chromium_noop_when_no_proc_and_no_cdp() -> None:
    host = ChromiumHost()
    host._root_mux = None
    host._proc = None
    host._root_ws_url = None
    await host._shutdown_chromium()
    assert host._root_mux is None
    assert host._proc is None


@pytest.mark.unit
async def test_shutdown_chromium_proc_already_dead_no_terminate() -> None:
    host = ChromiumHost()
    host._root_mux = None
    mock_proc = MagicMock(returncode=0)
    mock_proc.terminate = MagicMock()
    host._proc = mock_proc
    await host._shutdown_chromium()
    mock_proc.terminate.assert_not_called()
    assert host._proc is None


# ---------------------------------------------------------------------------
# _reap_idle / _recover_crash
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_reap_idle_removes_stale_without_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 10)
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    now = 1000.0
    monkeypatch.setattr(time, "monotonic", lambda: now)
    s_old = make_session(
        session_id="old",
        context_id="ctx-old",
        target_id="t1",
        last_activity_at=now - 20,
    )
    s_fresh = make_session(
        session_id="fresh",
        context_id="ctx-fresh",
        target_id="t2",
        last_activity_at=now - 5,
    )
    s_watched = replace(
        make_session(
            session_id="watched",
            context_id="ctx-watched",
            target_id="t3",
            last_activity_at=now - 20,
        ),
        viewer_count=1,
    )
    host._sessions = {"old": s_old, "fresh": s_fresh, "watched": s_watched}
    await host._reap_idle()
    assert "old" not in host._sessions
    assert "fresh" in host._sessions
    assert "watched" in host._sessions
    assert s_old.mux.params_for("Target.disposeBrowserContext") == [{"browserContextId": "ctx-old"}]
    assert s_old.mux.closed is True
    assert [s_fresh.mux.closed, s_watched.mux.closed] == [False, False]


@pytest.mark.unit
async def test_reap_idle_skips_when_none_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 300)
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    s = make_session(
        session_id="s1",
        context_id="ctx1",
        target_id="t1",
        last_activity_at=time.monotonic(),
    )
    host._sessions["s1"] = s
    await host._reap_idle()
    assert s.mux.calls == []
    assert s.mux.closed is False


@pytest.mark.unit
async def test_recover_crash_marks_dead_clears_and_relaunches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = ChromiumHost()
    s1 = make_session(session_id="s1", context_id="ctx1", target_id="t1", last_activity_at=0)
    s2 = make_session(session_id="s2", context_id="ctx2", target_id="t2", last_activity_at=0)
    host._sessions = {"s1": s1, "s2": s2}
    host._shutdown_chromium = AsyncMock()
    host._launch = AsyncMock()
    await host._recover_crash()
    assert s1.dead is True
    assert s2.dead is True
    assert host._sessions == {}
    host._shutdown_chromium.assert_awaited_once()
    host._launch.assert_awaited_once()


@pytest.mark.unit
async def test_recover_crash_with_no_sessions_still_relaunches() -> None:
    host = ChromiumHost()
    host._shutdown_chromium = AsyncMock()
    host._launch = AsyncMock()
    await host._recover_crash()
    host._shutdown_chromium.assert_awaited_once()
    host._launch.assert_awaited_once()


# ---------------------------------------------------------------------------
# _reaper_loop
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_reaper_loop_recovers_when_chromium_down() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=1)  # chromium_up False
    host._recover_crash = AsyncMock()
    host._reap_idle = AsyncMock()
    call_count = 0

    async def fake_sleep(_sec: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError

    with patch.object(chromium.asyncio, "sleep", side_effect=fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await host._reaper_loop()
    host._recover_crash.assert_awaited_once()
    host._reap_idle.assert_not_called()


@pytest.mark.unit
async def test_reaper_loop_reaps_when_chromium_up() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._recover_crash = AsyncMock()
    host._reap_idle = AsyncMock()
    call_count = 0

    async def fake_sleep(_sec: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError

    with patch.object(chromium.asyncio, "sleep", side_effect=fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await host._reaper_loop()
    host._reap_idle.assert_awaited_once()
    host._recover_crash.assert_not_called()


@pytest.mark.unit
async def test_reaper_loop_swallows_sweep_exception_and_continues() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._reap_idle = AsyncMock(side_effect=[RuntimeError("boom"), None])
    host._recover_crash = AsyncMock()
    call_count = 0

    async def fake_sleep(_sec: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            raise asyncio.CancelledError

    with patch.object(chromium.asyncio, "sleep", side_effect=fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await host._reaper_loop()
    # first sweep failed, second succeeded, both were attempted despite exception
    assert host._reap_idle.call_count == 2


@pytest.mark.unit
async def test_reaper_loop_relabels_chromium_down_after_recovery() -> None:
    # covers the continue after _recover_crash — next iteration should again check
    host = ChromiumHost()
    # first call: up=False -> recover, second: up=True -> reap
    proc_mock = MagicMock(returncode=1)
    host._proc = proc_mock
    host._recover_crash = AsyncMock()
    host._reap_idle = AsyncMock()

    async def fake_recover():
        # simulate that after recovery chromium is up
        host._proc = MagicMock(returncode=None)

    host._recover_crash.side_effect = fake_recover
    call_count = 0

    async def fake_sleep(_sec: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            raise asyncio.CancelledError

    with patch.object(chromium.asyncio, "sleep", side_effect=fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await host._reaper_loop()
    host._recover_crash.assert_awaited_once()
    host._reap_idle.assert_awaited_once()


@pytest.mark.unit
async def test_reap_idle_handles_gone_session_between_stale_and_lock() -> None:
    # covers line 632: session is None after stale list computed (race)
    # Use a custom dict-like that can mock `get` without patching builtin `dict.get`.
    class FakeSessions(dict):
        def get(self, key, default=None):
            # Simulate that stale list was computed with ghost present, but by the time
            # the loop does `self._sessions.get(session_id)` the entry is gone.
            return None

    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    # Create a real session that will be considered stale
    ghost = make_session(
        session_id="ghost",
        context_id="ctx-ghost",
        target_id="t",
        last_activity_at=0,
    )
    # Inject a FakeSessions that pretends ghost is in values() for stale computation
    # but returns None on get (simulating concurrent deletion).
    fake = FakeSessions({"ghost": ghost})
    # Override values() to still return the ghost so stale = ["ghost"]
    # get() returns None, so the loop hits `if session is None: continue`
    host._sessions = fake
    with patch.object(chromium.time, "monotonic", return_value=9999):
        with patch.object(chromium.settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 1):
            await host._reap_idle()
    assert ghost.mux.calls == []
    assert ghost.mux.closed is False


@pytest.mark.unit
async def test_reap_idle_continues_past_a_gone_session_to_reap_the_next_one() -> None:
    """A session vanishing mid-sweep must skip only that one entry, not abort the whole sweep; a break here would strand every stale session after it."""
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    first = make_session(
        session_id="first", context_id="ctx-first", target_id="t1", last_activity_at=0
    )
    gone = make_session(
        session_id="gone", context_id="ctx-gone", target_id="t2", last_activity_at=0
    )
    last = make_session(
        session_id="last", context_id="ctx-last", target_id="t3", last_activity_at=0
    )
    # Insertion order matters: `stale` is built by iterating self._sessions,
    # so processing order is first -> gone -> last.
    host._sessions = {"first": first, "gone": gone, "last": last}

    async def _steal_gone_while_closing_first() -> None:
        # Simulate another coroutine removing "gone" while "first" is being
        # closed, so its own lookup later in this sweep is None.
        host._sessions.pop("gone", None)
        await FakeMux.close(first.mux)

    first.mux.close = _steal_gone_while_closing_first  # type: ignore[method-assign]  # drives the race

    with patch.object(chromium.time, "monotonic", return_value=9999):
        with patch.object(chromium.settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 1):
            await host._reap_idle()

    # "gone" is skipped (its lookup is None), but the sweep must continue on
    # to reap "last" rather than aborting the whole sweep right there.
    assert last.mux.params_for("Target.disposeBrowserContext") == [{"browserContextId": "ctx-last"}]
    assert last.mux.closed is True
    assert "last" not in host._sessions
    assert gone.mux.calls == []


@pytest.mark.unit
async def test_reap_idle_pop_tolerates_concurrent_removal() -> None:
    """The pop of a stale session must not KeyError if another coroutine, like dispose_context, removed it between the lookup and the lock."""
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    stale = make_session(session_id="s1", context_id="ctx1", target_id="t1", last_activity_at=0)
    host._sessions = {"s1": stale}

    with patch.object(chromium.time, "monotonic", return_value=9999):
        with patch.object(chromium.settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 1):
            await host._lock.acquire()
            task = asyncio.create_task(host._reap_idle())
            # Let the reaper run its synchronous prelude (build `stale`, look
            # up the session) and block trying to acquire the lock we hold.
            await asyncio.sleep(0)
            # Simulate a concurrent dispose_context() removing the same
            # session while _reap_idle waits on the lock.
            del host._sessions["s1"]
            host._lock.release()
            await asyncio.wait_for(task, timeout=1.0)

    assert stale.mux.params_for("Target.disposeBrowserContext") == [{"browserContextId": "ctx1"}]
    assert stale.mux.closed is True


@pytest.mark.unit
async def test_reap_idle_handles_missing_on_second_lookup_with_real_dict() -> None:
    # Simple sanity: empty sessions should not dispose anything (covers no-stale path)
    host = make_host()
    host._close_session_connection = AsyncMock()
    with patch.object(chromium.time, "monotonic", return_value=9999):
        with patch.object(chromium.settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 1):
            await host._reap_idle()
    host._close_session_connection.assert_not_called()


@pytest.mark.unit
async def test_reaper_loop_propagates_cancelled_from_reap() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._reap_idle = AsyncMock(side_effect=asyncio.CancelledError)
    host._recover_crash = AsyncMock()
    with patch.object(chromium.asyncio, "sleep", new=AsyncMock()):
        with pytest.raises(asyncio.CancelledError):
            await host._reaper_loop()


@pytest.mark.unit
async def test_reaper_loop_propagates_cancelled_from_recover() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=1)  # chromium_up False -> recover path
    host._recover_crash = AsyncMock(side_effect=asyncio.CancelledError)
    host._reap_idle = AsyncMock()
    with patch.object(chromium.asyncio, "sleep", new=AsyncMock()):
        with pytest.raises(asyncio.CancelledError):
            await host._reaper_loop()


# ---------------------------------------------------------------------------
# Real-stack coverage: drives cdp_call/_cdp_call/_seed_cookies/_dump_storage_state via a low-level CDP fake at send_raw.
# ---------------------------------------------------------------------------


def _host_and_mux(
    monkeypatch: pytest.MonkeyPatch, responses: dict[str, dict[str, Any]] | None = None
) -> tuple[ChromiumHost, FakeMux]:
    """Build a live host plus the one fake connection its sessions and its next create will ride."""
    return make_host(), install_mux(monkeypatch, FakeMux(responses))


@pytest.mark.unit
async def test_cdp_call_timeout_raises_and_logs() -> None:
    class HangingFake:
        async def send_raw(
            self,
            method: str,
            params: dict[str, object] | None = None,
            session_id: str | None = None,
        ) -> dict[str, object]:
            await asyncio.Event().wait()
            return {}

    with patch.object(chromium.log, "error") as mock_err:
        with pytest.raises(CDPTimeoutError) as exc_info:
            await cdp_call(HangingFake(), "Target.getTargets", timeout=0.04)
        assert exc_info.value.args[0] == "Target.getTargets"
        mock_err.assert_called_once()


@pytest.mark.unit
async def test_create_context_end_to_end_real_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host, mux = _host_and_mux(
        monkeypatch,
        {
            "Target.createBrowserContext": {"browserContextId": "ctx-e2e"},
            "Target.createTarget": {"targetId": "t-e2e"},
        },
    )
    session = await host.create_context(None)
    assert session.context_id == "ctx-e2e"
    assert session.target_id == "t-e2e"
    assert host.get(session.session_id) is session
    assert host._pending_slots == 0
    # verify low-level calls were made (proves the real cdp_call was exercised)
    methods = [c[0] for c in mux.calls]
    assert "Target.createBrowserContext" in methods
    assert "Browser.setDownloadBehavior" in methods
    assert "Target.createTarget" in methods


@pytest.mark.unit
async def test_create_context_with_storage_state_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host, mux = _host_and_mux(monkeypatch)
    state: dict[str, object] = {
        "cookies": [
            {
                "name": "a",
                "value": "b",
                "domain": "ex.com",
                "path": "/",
                "secure": False,
                "httpOnly": False,
            }
        ],
        "origins": [],
    }
    session = await host.create_context(state)
    assert session.context_id == "ctx-low"
    methods = [c[0] for c in mux.calls]
    assert "Storage.setCookies" in methods
    # verify cookie shape passed to CDP
    for m, p, _ in mux.calls:
        if m == "Storage.setCookies":
            assert p is not None
            assert len(p["cookies"]) == 1


@pytest.mark.unit
async def test_create_context_empty_storage_state_does_not_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host, mux = _host_and_mux(monkeypatch)
    state = {"cookies": [], "origins": []}
    await host.create_context(state)
    methods = [c[0] for c in mux.calls]
    assert "Storage.setCookies" not in methods


@pytest.mark.unit
async def test_create_context_failure_before_context_id_no_dispose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)

    host, mux = _host_and_mux(monkeypatch)
    mux.fail_on_first_call["Target.createBrowserContext"] = RuntimeError("early boom")

    with pytest.raises(RuntimeError, match="early boom"):
        await host.create_context(None)

    assert host._pending_slots == 0
    # There is no context yet, so nothing is disposed — but the socket still closes.
    assert "Target.disposeBrowserContext" not in mux.methods
    assert mux.closed is True


@pytest.mark.unit
async def test_dispose_context_end_to_end_real_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    host, mux = _host_and_mux(
        monkeypatch,
        {
            "Storage.getCookies": {
                "cookies": [
                    {
                        "name": "a",
                        "value": "b",
                        "domain": "ex.com",
                        "path": "/",
                        "expires": -1,
                        "httpOnly": False,
                        "secure": False,
                    }
                ]
            },
            "Target.getTargets": {"targetInfos": []},
        },
    )
    s = make_session(session_id="s-e2e", context_id="ctx-low", target_id="t-low", mux=mux)
    host._sessions["s-e2e"] = s
    result = await host.dispose_context("s-e2e")
    assert result["cookies"][0]["name"] == "a"
    assert host.get("s-e2e") is None
    # the real _close_session_connection ran over the session's own connection
    assert "Target.disposeBrowserContext" in mux.methods
    assert mux.closed is True


@pytest.mark.unit
async def test_dispose_context_when_chromium_down_returns_empty_and_clears() -> None:
    host = ChromiumHost()
    host._proc = None  # down
    s = make_session(session_id="s-down", context_id="ctx-down", target_id="t-down")
    host._sessions["s-down"] = s
    # _dump_storage_state will early return empty when chromium_up is False
    result = await host.dispose_context("s-down")
    assert result == {"cookies": [], "origins": []}
    assert host.get("s-down") is None
    # Nothing to dispose over a dead engine, but the socket still closes.
    assert s.mux.calls == []
    assert s.mux.closed is True


@pytest.mark.unit
async def test_dispose_context_dump_failure_still_clears_and_logs() -> None:
    host = make_host()
    s = make_session(
        session_id="s-fail",
        context_id="ctx-fail",
        target_id="t-fail",
        last_activity_at=0,
    )
    host._sessions["s-fail"] = s
    host._dump_storage_state = AsyncMock(side_effect=RuntimeError("dump boom"))
    with patch.object(chromium.log, "error") as mock_err:
        with pytest.raises(RuntimeError, match="dump boom"):
            await host.dispose_context("s-fail")
        # error log for disposed without saving
        assert mock_err.called
    assert host.get("s-fail") is None
    assert s.mux.params_for("Target.disposeBrowserContext") == [{"browserContextId": "ctx-fail"}]
    assert s.mux.closed is True


@pytest.mark.unit
async def test_seed_cookies_empty_via_real_path(monkeypatch: pytest.MonkeyPatch) -> None:
    host, mux = _host_and_mux(monkeypatch)
    await host._seed_cookies(mux, "ctx-low", {"cookies": [], "origins": []})
    assert mux.calls == []
    await host._seed_cookies(mux, "ctx-low", {"cookies": None, "origins": []})
    assert mux.calls == []


@pytest.mark.unit
async def test_seed_cookies_with_real_cdp_call(monkeypatch: pytest.MonkeyPatch) -> None:
    host, mux = _host_and_mux(monkeypatch)
    state = {"cookies": [{"name": "n", "value": "v", "domain": "ex.com"}], "origins": []}
    await host._seed_cookies(mux, "ctx-low", state)
    assert mux.calls[0][0] == "Storage.setCookies"


@pytest.mark.unit
async def test_dump_storage_state_real_with_cookies_and_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, mux = _host_and_mux(
        monkeypatch,
        {
            "Storage.getCookies": {
                "cookies": [
                    {
                        "name": "a",
                        "value": "b",
                        "domain": "ex.com",
                        "path": "/",
                        "expires": -1,
                        "httpOnly": False,
                        "secure": False,
                    }
                ]
            },
            "Target.getTargets": {
                "targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx-low"}]
            },
            "Target.attachToTarget": {"sessionId": "sess-1"},
            "Runtime.evaluate": {
                "result": {
                    "value": {
                        "origin": "https://ex.com",
                        "localStorage": [{"name": "k", "value": "v"}],
                    }
                }
            },
        },
    )
    s = make_session(context_id="ctx-low", mux=mux)
    result = await host._dump_storage_state(s)
    assert len(result["cookies"]) == 1
    assert result["origins"][0]["origin"] == "https://ex.com"


@pytest.mark.unit
async def test_dump_origins_real_multiple_pages() -> None:
    class MultiPageMux(FakeMux):
        """Answers attachToTarget with a session id derived from the target asked for."""

        async def send_raw(
            self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None
        ) -> dict[str, Any]:
            result = await super().send_raw(method, params, session_id)
            if method == "Target.attachToTarget" and params is not None:
                return {"sessionId": f"sess-{params['targetId']}"}
            return result

    host = make_host()
    s = make_session(
        context_id="ctx-low",
        mux=MultiPageMux(
            {
                "Target.getTargets": {
                    "targetInfos": [
                        {"targetId": "t1", "type": "page", "browserContextId": "ctx-low"},
                        {"targetId": "t2", "type": "page", "browserContextId": "ctx-low"},
                    ]
                },
                "Runtime.evaluate": {
                    "result": {
                        "value": {
                            "origin": "https://ex.com",
                            "localStorage": [{"name": "k", "value": "v"}],
                        }
                    }
                },
            }
        ),
    )
    result = await host._dump_origins(s)
    assert len(result) == 2
    assert [c[2] for c in s.mux.calls if c[0] == "Runtime.evaluate"] == ["sess-t1", "sess-t2"]


@pytest.mark.unit
async def test_focused_page_meta_real(monkeypatch: pytest.MonkeyPatch) -> None:
    host, mux = _host_and_mux(
        monkeypatch,
        {
            "Target.getTargets": {
                "targetInfos": [
                    {
                        "type": "page",
                        "browserContextId": "ctx-low",
                        "url": "https://ex.com",
                        "title": "T",
                    }
                ]
            }
        },
    )
    s = make_session(context_id="ctx-low", mux=mux)
    url, title = await host._focused_page_meta(s)
    assert url == "https://ex.com"
    assert title == "T"


@pytest.mark.unit
async def test_healthz_real_responsive_and_unresponsive(monkeypatch: pytest.MonkeyPatch) -> None:
    # responsive — the health probe is the one thing that stays on the root connection
    host = make_host()
    host._root_mux = FakeMux({"Target.getTargets": {"targetInfos": []}})
    host._sessions["s1"] = make_session(context_id="ctx-low")
    res = await host.healthz()
    assert res["ok"] is True
    assert res["cdp_responsive"] is True
    # unresponsive via hanging send_raw
    host2 = make_host()

    async def hanging(*_a: object, **_kw: object) -> dict[str, object]:
        await asyncio.Event().wait()
        return {}

    fake = MagicMock()
    fake.send_raw = hanging
    host2._root_mux = fake
    monkeypatch.setattr(chromium, "_CDP_HEALTH_TIMEOUT_SECONDS", 0.05)
    res2 = await host2.healthz()
    assert res2["ok"] is False
    assert res2["cdp_responsive"] is False


@pytest.mark.unit
async def test_session_info_real(monkeypatch: pytest.MonkeyPatch) -> None:
    host, mux = _host_and_mux(
        monkeypatch,
        {
            "Target.getTargets": {
                "targetInfos": [
                    {
                        "type": "page",
                        "browserContextId": "ctx-low",
                        "url": "https://ex.com",
                        "title": "Title",
                    }
                ]
            }
        },
    )
    s = make_session(context_id="ctx-low", mux=mux, last_activity_at=123.0)
    host._sessions["s1"] = s
    info = await host.session_info("s1")
    assert info["session_id"] == "s1"
    assert info["live"] is True
    assert info["url"] == "https://ex.com"


@pytest.mark.unit
async def test_focused_target_id_real(monkeypatch: pytest.MonkeyPatch) -> None:
    host, mux = _host_and_mux(
        monkeypatch,
        {
            "Target.getTargets": {
                "targetInfos": [
                    {"type": "page", "browserContextId": "ctx-low", "targetId": "t-other"},
                    {"type": "page", "browserContextId": "ctx-low", "targetId": "t-primary"},
                ]
            }
        },
    )
    s = make_session(context_id="ctx-low", target_id="t-primary", mux=mux)
    host._sessions["s1"] = s
    tid = await host.focused_target_id("s1")
    assert tid == "t-primary"


@pytest.mark.unit
async def test_launch_real_arg_composition_headed_false_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = ChromiumHost()
    fake = tmp_path / "headless_shell"
    fake.write_text("x")
    host._chromium_path = str(fake)
    monkeypatch.setattr(settings, "BROWSER_HOST_JS_HEAP_MB", 512)
    monkeypatch.setattr(settings, "BROWSER_HOST_HEADED", False)
    monkeypatch.setattr(chromium, "CHROME_DEFAULT_ARGS", ("--no-first-run",))
    monkeypatch.setattr(chromium, "_HOST_EXTRA_ARGS", ("--no-sandbox",))
    monkeypatch.setattr(chromium.tempfile, "mkdtemp", lambda prefix: str(tmp_path / "udir-real"))
    mock_proc = MagicMock(returncode=None)
    monkeypatch.setattr(
        chromium.asyncio, "create_subprocess_exec", AsyncMock(return_value=mock_proc)
    )
    host._await_cdp_ready = AsyncMock(return_value="ws://127.0.0.1:9222")
    mock_mux = MagicMock()
    mock_mux.start = AsyncMock()
    with patch.object(chromium, "CdpMux", return_value=mock_mux):
        await host._launch()
    args = chromium.asyncio.create_subprocess_exec.call_args[0]
    assert "--remote-debugging-port=0" in args
    assert "--headless" in args
    assert any("max-old-space-size=512" in a for a in args)
    assert any("window-size" in a for a in args)
    assert host._user_data_dir is not None
    assert host._root_mux is mock_mux
    assert host._proc is mock_proc


@pytest.mark.unit
async def test_await_cdp_ready_handles_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    host = ChromiumHost()
    host._read_devtools_port = AsyncMock(return_value=9222)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {}  # missing webSocketDebuggerUrl -> KeyError
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 0.35)
    monkeypatch.setattr(chromium, "_CDP_READY_POLL_SECONDS", 0.05)
    # First call returns missing key (KeyError), second succeeds to avoid infinite loop timeout check
    # But our fake always returns missing key, so it will retry until timeout -> RuntimeError
    with patch.object(chromium.httpx, "AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="did not expose"):
            await host._await_cdp_ready()


@pytest.mark.unit
async def test_read_devtools_port_handles_whitespace_and_empty_then_valid(tmp_path: Path) -> None:
    host = ChromiumHost()
    host._user_data_dir = str(tmp_path)
    host._proc = MagicMock(returncode=None)
    port_file = tmp_path / "DevToolsActivePort"
    port_file.write_text("   \n")

    async def fix():
        await asyncio.sleep(0.05)
        port_file.write_text("  8765  \n/devtools\n")

    task = asyncio.create_task(fix())
    port = await host._read_devtools_port()
    await task
    assert port == 8765


@pytest.mark.unit
async def test_shutdown_chromium_clears_state_even_without_cdp() -> None:
    host = ChromiumHost()
    host._root_mux = None
    host._proc = None
    host._root_ws_url = None
    await host._shutdown_chromium()
    assert host._root_mux is None
    assert host._proc is None


@pytest.mark.unit
async def test_reap_idle_via_real_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 10)
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    now = 5000.0
    monkeypatch.setattr(chromium.time, "monotonic", lambda: now)
    s_stale = make_session(
        session_id="stale",
        context_id="ctx-stale",
        target_id="t",
        last_activity_at=now - 20,
    )
    s_keep = make_session(
        session_id="keep",
        context_id="ctx-keep",
        target_id="t",
        last_activity_at=now - 5,
    )
    host._sessions = {"stale": s_stale, "keep": s_keep}
    await host._reap_idle()
    assert "stale" not in host._sessions
    assert "keep" in host._sessions
    assert s_stale.mux.params_for("Target.disposeBrowserContext") == [
        {"browserContextId": "ctx-stale"}
    ]
    assert s_stale.mux.closed is True


@pytest.mark.unit
async def test_recover_crash_real_marks_dead() -> None:
    host = ChromiumHost()
    s = make_session(session_id="s1", context_id="ctx1", target_id="t1", last_activity_at=0)
    host._sessions["s1"] = s
    host._shutdown_chromium = AsyncMock()
    host._launch = AsyncMock()
    await host._recover_crash()
    assert s.dead is True
    assert host._sessions == {}


@pytest.mark.unit
async def test_headless_shell_beside_real_nested(tmp_path: Path) -> None:
    rev = tmp_path / "chromium-2222"
    rev.mkdir()
    shell = tmp_path / "chromium_headless_shell-2222"
    shell.mkdir()
    nested = shell / "a" / "b" / "headless_shell"
    nested.parent.mkdir(parents=True)
    nested.write_text("bin")
    chromium_path = rev / "chrome"
    chromium_path.parent.mkdir(parents=True, exist_ok=True)
    found = _headless_shell_beside(chromium_path)
    assert found == nested


@pytest.mark.unit
def test_cdp_cookie_to_storage_state_real_dict() -> None:
    c = {
        "name": "sess",
        "value": "abc",
        "domain": ".ex.com",
        "path": "/",
        "expires": 0,
        "httpOnly": True,
        "secure": True,
        "sameSite": "None",
    }
    out = _cdp_cookie_to_storage_state(c)
    assert out["name"] == "sess"
    assert out["sameSite"] == "None"


@pytest.mark.unit
def test_storage_state_cookie_to_cdp_real() -> None:
    c: dict[str, object] = {
        "name": "n",
        "value": "v",
        "domain": "ex.com",
        "path": "/a",
        "secure": True,
        "httpOnly": True,
        "expires": 12345,
        "sameSite": "Lax",
    }
    out = _storage_state_cookie_to_cdp(c)
    assert out["expires"] == 12345
    assert out["sameSite"] == "Lax"


@pytest.mark.unit
async def test_touch_and_viewer_real() -> None:
    host = ChromiumHost()
    s = make_session(
        session_id="sv",
        context_id="ctx",
        target_id="t",
        last_activity_at=0,
    )
    host._sessions["sv"] = s
    with patch.object(chromium.time, "monotonic", return_value=42.0):
        host.touch("sv")
        assert s.last_activity_at == 42.0
        host.add_viewer("sv")
        assert s.viewer_count == 1
        host.remove_viewer("sv")
        assert s.viewer_count == 0


# ---------------------------------------------------------------------------
# Exact CDP payloads sent (method, params, routed session), log records, boundaries
# ---------------------------------------------------------------------------


class _Wedged(RuntimeError):
    """A distinctive exception type so error_type= is provably the real one."""


# --- cdp_call ---


@pytest.mark.unit
async def test_cdp_call_timeout_log_names_the_method_and_the_budget() -> None:
    class HangingFake:
        async def send_raw(
            self,
            method: str,
            params: dict[str, Any] | None = None,
            session_id: str | None = None,
        ) -> dict[str, Any]:
            await asyncio.Event().wait()
            return {}

    with patch.object(chromium, "log") as mock_log:
        with pytest.raises(CDPTimeoutError):
            await cdp_call(HangingFake(), "Storage.getCookies", {"a": 1}, timeout=0.04)

    mock_log.error.assert_called_once_with(
        f"{LogTag.BROWSER} browser host CDP call timed out",
        error_type="CDPTimeoutError",
        browser={"cdp_method": "Storage.getCookies", "timeout_seconds": 0.04},
    )


# --- create_context ---


@pytest.mark.unit
async def test_create_context_sends_the_exact_cdp_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host, mux = _host_and_mux(
        monkeypatch,
        {
            "Target.createBrowserContext": {"browserContextId": "ctx-x"},
            "Target.createTarget": {"targetId": "t-x"},
        },
    )

    session = await host.create_context(None)

    assert mux.calls == [
        ("Target.createBrowserContext", {"disposeOnDetach": False}, None),
        ("Browser.setDownloadBehavior", {"behavior": "deny", "browserContextId": "ctx-x"}, None),
        ("Target.createTarget", {"url": "about:blank", "browserContextId": "ctx-x"}, None),
    ]
    assert (session.context_id, session.target_id) == ("ctx-x", "t-x")


@pytest.mark.unit
async def test_create_context_registers_a_session_stamped_now(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    monkeypatch.setattr(chromium, "time", SimpleNamespace(monotonic=lambda: 4242.0))
    host, mux = _host_and_mux(monkeypatch)

    session = await host.create_context(None)

    assert session == HostSession(
        session_id=session.session_id,
        context_id="ctx-low",
        target_id="t-low",
        mux=mux,  # type: ignore[arg-type]  # a CdpMux stand-in
        created_at=4242.0,
        last_activity_at=4242.0,
        viewer_count=0,
        dead=False,
        metrics=session.metrics,
    )
    assert len(session.session_id) == 32
    assert host._sessions == {session.session_id: session}


@pytest.mark.unit
async def test_create_context_logs_the_new_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host, mux = _host_and_mux(monkeypatch)

    with patch.object(chromium, "log") as mock_log:
        session = await host.create_context(None)

    mock_log.set.assert_called_once_with(
        browser={"session_id": session.session_id, "operation": "create"}
    )
    mock_log.info.assert_called_once_with(f"{LogTag.BROWSER} browser context created")


@pytest.mark.unit
async def test_create_context_seeds_the_converted_cookies_into_the_new_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host, mux = _host_and_mux(
        monkeypatch, {"Target.createBrowserContext": {"browserContextId": "ctx-seed"}}
    )
    state: dict[str, Any] = {
        "cookies": [
            {
                "name": "sid",
                "value": "abc",
                "domain": "ex.com",
                "path": "/app",
                "secure": True,
                "httpOnly": True,
                "expires": 99.0,
                "sameSite": "Lax",
            }
        ],
        "origins": [],
    }

    await host.create_context(state)

    seeds = [c for c in mux.calls if c[0] == "Storage.setCookies"]
    assert seeds == [
        (
            "Storage.setCookies",
            {
                "browserContextId": "ctx-seed",
                "cookies": [
                    {
                        "name": "sid",
                        "value": "abc",
                        "domain": "ex.com",
                        "path": "/app",
                        "secure": True,
                        "httpOnly": True,
                        "expires": 99.0,
                        "sameSite": "Lax",
                    }
                ],
            },
            None,
        )
    ]


@pytest.mark.unit
async def test_create_context_drops_the_orphan_connection_when_the_target_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connection opened before the failure has no session to carry it — drop it."""
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host, mux = _host_and_mux(
        monkeypatch,
        {"Target.createBrowserContext": {"browserContextId": "ctx-orphan"}},
    )
    mux.fail_on_first_call["Target.createTarget"] = _Wedged("no target")

    with pytest.raises(_Wedged):
        await host.create_context(None)

    # The orphan context dies with its socket; the idle reaper would never
    # find a connection no session points at.
    assert mux.closed is True
    assert host._sessions == {}
    assert host._pending_slots == 0


# --- dispose_context ---


@pytest.mark.unit
async def test_dispose_context_returns_the_dump_and_logs_a_clean_disposal() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._sessions["s1"] = make_session()
    dump = {"cookies": [], "origins": [{"origin": "https://a.test", "localStorage": []}]}
    host._dump_storage_state = AsyncMock(return_value=dump)

    with patch.object(chromium, "log") as mock_log:
        result = await host.dispose_context("s1")

    assert result == dump
    mock_log.set.assert_called_once_with(browser={"session_id": "s1", "operation": "dispose"})
    mock_log.info.assert_called_once_with(f"{LogTag.BROWSER} browser context disposed")
    mock_log.error.assert_not_called()


@pytest.mark.unit
async def test_dispose_context_reports_the_lost_storage_state_as_an_error() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._sessions["s1"] = make_session()
    host._dump_storage_state = AsyncMock(side_effect=_Wedged("dump died"))

    with patch.object(chromium, "log") as mock_log:
        with pytest.raises(_Wedged):
            await host.dispose_context("s1")

    mock_log.set.assert_called_once_with(browser={"session_id": "s1", "operation": "dispose"})
    mock_log.error.assert_called_once_with(
        f"{LogTag.BROWSER} browser context disposed without saving its storage state",
        error_type="StorageDumpFailed",
    )
    mock_log.info.assert_not_called()


# --- _close_session_connection ---


@pytest.mark.unit
async def test_close_session_connection_sends_the_context_scoped_payload() -> None:
    host = make_host()
    session = make_session(context_id="ctx-bye")

    await host._close_session_connection(session)

    assert session.mux.calls == [
        ("Target.disposeBrowserContext", {"browserContextId": "ctx-bye"}, None)
    ]


@pytest.mark.unit
async def test_close_session_connection_warns_with_the_real_failure_type() -> None:
    host = make_host()
    session = make_session(
        mux=FakeMux(fail_on_first_call={"Target.disposeBrowserContext": _Wedged("nope")})
    )

    with patch.object(chromium, "log") as mock_log:
        await host._close_session_connection(session)

    mock_log.warning.assert_called_once_with(
        f"{LogTag.BROWSER} browser host context dispose failed",
        error_type="_Wedged",
    )


# --- _dump_storage_state / _dump_origins ---


@pytest.mark.unit
async def test_dump_storage_state_reads_cookies_scoped_to_the_session_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, mux = _host_and_mux(
        monkeypatch,
        {
            "Storage.getCookies": {
                "cookies": [
                    {
                        "name": "a",
                        "value": "b",
                        "domain": "ex.com",
                        "path": "/",
                        "expires": 5.0,
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "Strict",
                    }
                ]
            }
        },
    )

    state = await host._dump_storage_state(make_session(context_id="ctx-dump", mux=mux))

    assert state == {
        "cookies": [
            {
                "name": "a",
                "value": "b",
                "domain": "ex.com",
                "path": "/",
                "expires": 5.0,
                "httpOnly": True,
                "secure": True,
                "sameSite": "Strict",
            }
        ],
        "origins": [],
    }
    assert ("Storage.getCookies", {"browserContextId": "ctx-dump"}, None) in mux.calls


@pytest.mark.unit
async def test_dump_origins_sends_the_exact_attach_evaluate_detach_sequence() -> None:
    host = make_host()
    session = make_session(
        mux=FakeMux(
            queues={
                "Target.getTargets": [
                    {
                        "targetInfos": [
                            {"targetId": "t1", "type": "page", "browserContextId": "ctx1"}
                        ]
                    }
                ],
                "Target.attachToTarget": [{"sessionId": "sess-1"}],
                "Runtime.evaluate": [
                    {
                        "result": {
                            "value": {
                                "origin": "https://a.test",
                                "localStorage": [{"name": "k", "value": "v"}],
                            }
                        }
                    }
                ],
            }
        )
    )

    origins = await host._dump_origins(session)

    assert origins == [{"origin": "https://a.test", "localStorage": [{"name": "k", "value": "v"}]}]
    # The whole conversation lands on the session's own connection, in order.
    assert session.mux.calls == [
        ("Target.getTargets", {}, None),
        ("Target.attachToTarget", {"targetId": "t1", "flatten": True}, None),
        (
            "Runtime.evaluate",
            {"expression": chromium._LOCAL_STORAGE_DUMP_JS, "returnByValue": True},
            "sess-1",
        ),
        ("Target.detachFromTarget", {"sessionId": "sess-1"}, None),
    ]


@pytest.mark.unit
async def test_dump_origins_evaluates_each_page_on_its_own_attached_session() -> None:
    host = make_host()
    session = make_session(
        mux=FakeMux(
            queues={
                "Target.getTargets": [
                    {
                        "targetInfos": [
                            {"targetId": "t1", "type": "page", "browserContextId": "ctx1"},
                            {"targetId": "t2", "type": "page", "browserContextId": "ctx1"},
                        ]
                    }
                ],
                "Target.attachToTarget": [{"sessionId": "sess-1"}, {"sessionId": "sess-2"}],
                "Runtime.evaluate": [
                    {
                        "result": {
                            "value": {"origin": "https://one.test", "localStorage": [{"name": "a"}]}
                        }
                    },
                    {
                        "result": {
                            "value": {"origin": "https://two.test", "localStorage": [{"name": "b"}]}
                        }
                    },
                ],
            }
        )
    )

    origins = await host._dump_origins(session)

    assert [o["origin"] for o in origins] == ["https://one.test", "https://two.test"]
    assert [c[2] for c in session.mux.calls if c[0] == "Runtime.evaluate"] == ["sess-1", "sess-2"]
    assert [c[1] for c in session.mux.calls if c[0] == "Target.detachFromTarget"] == [
        {"sessionId": "sess-1"},
        {"sessionId": "sess-2"},
    ]


# --- _focused_page_meta / focused_target_id ---


@pytest.mark.unit
async def test_focused_page_meta_asks_chromium_for_every_target() -> None:
    host = make_host()
    session = make_session(
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [
                        {
                            "type": "page",
                            "browserContextId": "ctx1",
                            "url": "https://a.test/x",
                            "title": "A",
                        }
                    ]
                }
            }
        )
    )

    assert await host._focused_page_meta(session) == ("https://a.test/x", "A")
    # On the session's own connection, never the host's root connection.
    assert session.mux.calls == [("Target.getTargets", {}, None)]


@pytest.mark.unit
async def test_focused_target_id_asks_chromium_for_every_target_and_prefers_the_newest() -> None:
    host = ChromiumHost()
    session = make_session(
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [
                        {"type": "page", "browserContextId": "ctx1", "targetId": "t-a"},
                        {"type": "page", "browserContextId": "ctx1", "targetId": "t-b"},
                        {"type": "page", "browserContextId": "ctx1", "targetId": "t-c"},
                    ]
                }
            }
        )
    )
    host._sessions["s1"] = session

    assert await host.focused_target_id("s1") == "t-c"
    # On the session's own connection, never the host's root connection.
    assert session.mux.calls == [("Target.getTargets", {}, None)]


# --- healthz ---


@pytest.mark.unit
async def test_healthz_probes_the_root_connection_with_the_tighter_health_budget() -> None:
    """The healthcheck must give up inside the orchestrator's timeout, not the 20s call budget."""
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._root_mux = FakeMux()
    probe = AsyncMock(return_value={"targetInfos": []})

    with patch.object(chromium, "cdp_call", new=probe):
        await host.healthz()

    assert probe.await_args.args == (host._root_mux, "Target.getTargets", {})
    assert probe.await_args.kwargs == {"timeout": chromium._CDP_HEALTH_TIMEOUT_SECONDS}


@pytest.mark.unit
async def test_healthz_logs_the_real_failure_type_when_the_probe_blows_up() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    wedged = FakeMux()
    wedged.send_error = _Wedged("wedged")
    host._root_mux = wedged

    with patch.object(chromium, "log") as mock_log:
        result = await host.healthz()

    assert result == {"ok": False, "sessions": 0, "chromium_up": True, "cdp_responsive": False}
    mock_log.error.assert_called_once_with(
        f"{LogTag.BROWSER} browser host CDP is unresponsive",
        error_type="_Wedged",
    )


# --- reaper ---


@pytest.mark.unit
async def test_reap_idle_logs_each_reaped_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 10)
    monkeypatch.setattr(chromium, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._sessions["old"] = make_session(
        session_id="old",
        context_id="ctx-old",
        target_id="t1",
        last_activity_at=900.0,
    )

    with patch.object(chromium, "log") as mock_log:
        await host._reap_idle()

    mock_log.set.assert_called_once_with(browser={"session_id": "old", "operation": "idle_reap"})
    mock_log.info.assert_called_once_with(f"{LogTag.BROWSER} browser context reaped (idle)")


@pytest.mark.unit
async def test_reaper_loop_sleeps_the_configured_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)
        raise asyncio.CancelledError

    monkeypatch.setattr(chromium.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await host._reaper_loop()

    assert slept == [chromium._REAPER_INTERVAL_SECONDS]


@pytest.mark.unit
async def test_reaper_loop_logs_the_real_sweep_failure_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._reap_idle = AsyncMock(side_effect=_Wedged("bad sweep"))
    sleeps = 0

    async def fake_sleep(delay: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(chromium.asyncio, "sleep", fake_sleep)

    with patch.object(chromium, "log") as mock_log:
        with pytest.raises(asyncio.CancelledError):
            await host._reaper_loop()

    mock_log.error.assert_called_once_with(
        f"{LogTag.BROWSER} browser host reaper sweep failed",
        error_type="_Wedged",
    )


@pytest.mark.unit
async def test_recover_crash_logs_how_many_sessions_died() -> None:
    host = ChromiumHost()
    host._sessions = {"s1": make_session("s1"), "s2": make_session("s2")}
    host._shutdown_chromium = AsyncMock()
    host._launch = AsyncMock()

    with patch.object(chromium, "log") as mock_log:
        await host._recover_crash()

    mock_log.error.assert_called_once_with(
        f"{LogTag.BROWSER} browser engine crashed; relaunching",
        browser={"operation": "crash_recover", "dead_sessions": 2},
    )


# --- launch / readiness ---


@pytest.mark.unit
async def test_launch_composes_the_full_argv_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = ChromiumHost()
    binary = tmp_path / "headless_shell"
    binary.write_text("x")
    host._chromium_path = str(binary)
    monkeypatch.setattr(chromium, "CHROME_DEFAULT_ARGS", ("--default-a",))
    monkeypatch.setattr(chromium, "_HOST_EXTRA_ARGS", ("--extra-b",))
    monkeypatch.setattr(settings, "BROWSER_HOST_JS_HEAP_MB", 512)
    monkeypatch.setattr(settings, "BROWSER_HOST_HEADED", False)
    user_dir = str(tmp_path / "udir-argv")
    prefixes: list[str] = []

    def fake_mkdtemp(prefix: str) -> str:
        prefixes.append(prefix)
        return user_dir

    monkeypatch.setattr(chromium.tempfile, "mkdtemp", fake_mkdtemp)
    proc = MagicMock(returncode=None)
    spawn = AsyncMock(return_value=proc)
    monkeypatch.setattr(chromium.asyncio, "create_subprocess_exec", spawn)
    host._await_cdp_ready = AsyncMock(return_value="ws://ready")
    root_mux = MagicMock()
    root_mux.start = AsyncMock()

    with patch.object(chromium, "CdpMux", return_value=root_mux) as mux_ctor:
        await host._launch()

    assert prefixes == ["gaia-browser-host-"]
    assert list(spawn.call_args.args) == [
        str(binary),
        "--remote-debugging-port=0",
        f"--user-data-dir={user_dir}",
        "--default-a",
        "--extra-b",
        "--js-flags=--max-old-space-size=512",
        f"--window-size={BROWSER_VIEWPORT_WIDTH},{BROWSER_VIEWPORT_HEIGHT}",
        "--headless",
    ]
    assert spawn.call_args.kwargs == {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    mux_ctor.assert_called_once_with("ws://ready")
    root_mux.start.assert_awaited_once()
    assert host._root_ws_url == "ws://ready"
    assert host._root_mux is root_mux
    assert host._user_data_dir == user_dir


@pytest.mark.unit
async def test_await_cdp_ready_polls_the_devtools_json_version_endpoint() -> None:
    host = ChromiumHost()
    host._read_devtools_port = AsyncMock(return_value=9333)
    resp = MagicMock()
    resp.json.return_value = {"webSocketDebuggerUrl": "ws://127.0.0.1:9333/devtools/browser/id"}
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=resp)

    with patch.object(chromium.httpx, "AsyncClient", return_value=client):
        url = await host._await_cdp_ready()

    assert url == "ws://127.0.0.1:9333/devtools/browser/id"
    client.get.assert_awaited_once_with("http://127.0.0.1:9333/json/version", timeout=2.0)


@pytest.mark.unit
async def test_await_cdp_ready_gives_up_with_a_named_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = ChromiumHost()
    host._read_devtools_port = AsyncMock(return_value=9222)
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=httpx.ConnectError("nope"))
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(chromium, "_CDP_READY_POLL_SECONDS", 0.01)

    with patch.object(chromium.httpx, "AsyncClient", return_value=client):
        with pytest.raises(RuntimeError) as exc:
            await host._await_cdp_ready()

    assert str(exc.value) == "Chromium did not expose its CDP endpoint in time"


@pytest.mark.unit
async def test_read_devtools_port_takes_the_stripped_first_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chromium writes the port on line 1 and the browser ws path on line 2."""
    host = ChromiumHost()
    host._user_data_dir = str(tmp_path)
    host._proc = MagicMock(returncode=None)
    (tmp_path / "DevToolsActivePort").write_text("  9222  \n/devtools/browser/abc\n")
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(chromium, "_CDP_READY_POLL_SECONDS", 0.01)

    assert await host._read_devtools_port() == 9222


@pytest.mark.unit
async def test_read_devtools_port_failures_are_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(chromium, "_CDP_READY_POLL_SECONDS", 0.01)
    dead = ChromiumHost()
    dead._user_data_dir = str(tmp_path)
    dead._proc = MagicMock(returncode=1)
    silent = ChromiumHost()
    silent._user_data_dir = str(tmp_path)
    silent._proc = MagicMock(returncode=None)

    with pytest.raises(RuntimeError) as exited:
        await dead._read_devtools_port()
    with pytest.raises(RuntimeError) as never_wrote:
        await silent._read_devtools_port()

    assert str(exited.value) == "Chromium exited before publishing its DevTools port"
    assert str(never_wrote.value) == "Chromium did not write DevToolsActivePort in time"


@pytest.mark.unit
async def test_shutdown_chromium_gives_terminate_five_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = ChromiumHost()
    host._root_mux = None
    proc = MagicMock(returncode=None)
    proc.wait = AsyncMock(return_value=0)
    host._proc = proc
    budgets: list[float] = []

    async def fake_wait_for(awaitable: Any, timeout: float) -> Any:
        budgets.append(timeout)
        return await awaitable

    monkeypatch.setattr(chromium.asyncio, "wait_for", fake_wait_for)

    await host._shutdown_chromium()

    assert budgets == [5]
    proc.kill.assert_not_called()


@pytest.mark.unit
async def test_shutdown_chromium_warns_with_the_real_stop_failure_type() -> None:
    host = ChromiumHost()
    root_mux = MagicMock()
    root_mux.close = AsyncMock(side_effect=_Wedged("dead socket"))
    host._root_mux = root_mux
    host._proc = None

    with patch.object(chromium, "log") as mock_log:
        await host._shutdown_chromium()

    mock_log.warning.assert_called_once_with(
        f"{LogTag.BROWSER} browser host CDP stop failed",
        error_type="_Wedged",
    )


# --- start / construction / small internals ---


@pytest.mark.unit
async def test_start_logs_that_the_host_is_up(monkeypatch: pytest.MonkeyPatch) -> None:
    host = ChromiumHost()
    monkeypatch.setattr(chromium.asyncio, "to_thread", AsyncMock(return_value="/bin/chrome"))
    host._launch = AsyncMock()
    host._reaper_loop = AsyncMock()

    with patch.object(chromium, "log") as mock_log:
        await host.start()

    mock_log.info.assert_called_once_with(f"{LogTag.BROWSER} browser host started")
    assert host._reaper_task is not None
    host._reaper_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await host._reaper_task


@pytest.mark.unit
def test_new_host_holds_nothing_and_reserves_nothing() -> None:
    host = ChromiumHost()

    assert host._pending_slots == 0
    assert host._sessions == {}
    assert host._reaper_task is None
    assert host._proc is None
    assert host._root_mux is None
    assert host._root_ws_url is None
    assert host._chromium_path is None
    assert host._user_data_dir is None


@pytest.mark.unit
def test_remove_viewer_drops_exactly_one_watcher() -> None:
    host = ChromiumHost()
    session = make_session()
    session.viewer_count = 2
    host._sessions["s1"] = session

    host.remove_viewer("s1")

    assert session.viewer_count == 1


@pytest.mark.unit
def test_get_names_the_missing_session() -> None:
    host = ChromiumHost()

    with pytest.raises(SessionNotFoundError) as no_session:
        host._get("ghost")

    assert no_session.value.args == ("ghost",)


# --- pure helpers ---


@pytest.mark.unit
def test_headless_shell_beside_rewrites_only_the_first_revision_marker(tmp_path: Path) -> None:
    revision = tmp_path / "chromium-chromium-42"
    revision.mkdir()
    shell_root = tmp_path / "chromium_headless_shell-chromium-42"
    shell_root.mkdir()
    binary = shell_root / "headless_shell"
    binary.write_text("x")

    assert _headless_shell_beside(revision / "chrome") == binary


@pytest.mark.unit
def test_headless_shell_beside_skips_a_directory_named_like_the_binary(tmp_path: Path) -> None:
    revision = tmp_path / "chromium-55"
    revision.mkdir()
    shell_root = tmp_path / "chromium_headless_shell-55"
    shell_root.mkdir()
    (shell_root / "headless_shell").mkdir()
    binary = shell_root / "nested" / "chrome-headless-shell"
    binary.parent.mkdir()
    binary.write_text("x")

    assert _headless_shell_beside(revision / "chrome") == binary


@pytest.mark.unit
def test_storage_state_cookie_to_cdp_carries_every_field_across() -> None:
    out = _storage_state_cookie_to_cdp(
        {
            "name": "n",
            "value": "v",
            "domain": "ex.com",
            "path": "/deep",
            "secure": True,
            "httpOnly": True,
            "expires": 123.5,
            "sameSite": "Lax",
        }
    )

    assert out == {
        "name": "n",
        "value": "v",
        "domain": "ex.com",
        "path": "/deep",
        "secure": True,
        "httpOnly": True,
        "expires": 123.5,
        "sameSite": "Lax",
    }


@pytest.mark.unit
def test_cdp_cookie_to_storage_state_carries_every_field_across() -> None:
    out = _cdp_cookie_to_storage_state(
        {
            "name": "n",
            "value": "v",
            "domain": "ex.com",
            "path": "/deep",
            "expires": 123.5,
            "httpOnly": True,
            "secure": True,
            "sameSite": "Strict",
        }
    )

    assert out == {
        "name": "n",
        "value": "v",
        "domain": "ex.com",
        "path": "/deep",
        "expires": 123.5,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Strict",
    }


# ---------------------------------------------------------------------------
# Supervision, admission, and the resource sampler: memory-pressure and admission-budget flips, no CDP traffic.
# ---------------------------------------------------------------------------


class _FixedSampler:
    """A ProcessSampler stand-in that always yields the same reading."""

    def __init__(self, reading: tuple[float, float] = (10.0, 5.0)) -> None:
        self._reading = reading

    def sample(self) -> tuple[float, float]:
        return self._reading


class _ExitingProc:
    """An engine process whose exit the test drives explicitly."""

    def __init__(self, pid: int = 4242) -> None:
        self.returncode: int | None = None
        self.pid = pid
        self._exited = asyncio.Event()

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def die(self, code: int) -> None:
        self.returncode = code
        self._exited.set()


def _idle_session(idle_for: float) -> HostSession:
    return make_session(
        session_id="s1",
        context_id="c1",
        target_id="t1",
        last_activity_at=time.monotonic() - idle_for,
    )


# --- memory-pressure boundary in the reaper ---


@pytest.mark.unit
async def test_reap_idle_pressure_switch_needs_a_real_limit_and_a_strict_excess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each side of "limit > 0 and used > limit * soft" decides a session's life."""
    monkeypatch.setattr(settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 300)
    monkeypatch.setattr(settings, "BROWSER_HOST_MEMORY_SOFT_WATERMARK", 0.75)

    async def survives_a_100s_idle(used: float, limit: float) -> bool:
        host = make_host()
        host._sessions = {"s1": _idle_session(100)}
        monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (used, limit))
        await host._reap_idle()
        return "s1" in host._sessions

    # No limit reported at all: pressure is unknowable, so the full 300s TTL stands.
    assert await survives_a_100s_idle(100.0, 0.0) is True
    # A 1 MB limit is still a limit — 100 MB over a 0.75 MB watermark is pressure,
    # so the shortened 75s TTL applies and the 100s-idle session goes.
    assert await survives_a_100s_idle(100.0, 1.0) is False
    # Exactly at the watermark is not over it.
    assert await survives_a_100s_idle(750.0, 1000.0) is True
    assert await survives_a_100s_idle(750.1, 1000.0) is False


# --- admission back-off budget ---


@pytest.mark.unit
async def test_reserve_slot_backs_off_and_admits_once_the_reaper_frees_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over the watermark the create waits out the budget instead of 429-ing at once."""
    monkeypatch.setattr(settings, "BROWSER_HOST_MEMORY_HIGH_WATERMARK", 0.85)
    monkeypatch.setattr(settings, "BROWSER_HOST_SESSION_COST_FLOOR_MB", 50)
    monkeypatch.setattr(settings, "BROWSER_HOST_ADMISSION_WAIT_SECONDS", 5)
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 10)
    readings = [(900.0, 1000.0), (700.0, 1000.0)]
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: readings.pop(0))
    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(chromium.asyncio, "sleep", fake_sleep)
    host = ChromiumHost()

    await host._reserve_slot()

    assert host._pending_slots == 1
    assert slept == [chromium._ADMISSION_POLL_SECONDS]


@pytest.mark.unit
async def test_reserve_slot_refuses_immediately_when_the_wait_budget_is_already_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero wait budget means give up on the first look, not back off once more."""
    monkeypatch.setattr(settings, "BROWSER_HOST_MEMORY_HIGH_WATERMARK", 0.85)
    monkeypatch.setattr(settings, "BROWSER_HOST_SESSION_COST_FLOOR_MB", 50)
    monkeypatch.setattr(settings, "BROWSER_HOST_ADMISSION_WAIT_SECONDS", 0)
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 10)
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (900.0, 1000.0))
    monkeypatch.setattr(chromium, "time", SimpleNamespace(monotonic=lambda: 1000.0))

    async def fake_sleep(delay: float) -> None:
        raise AssertionError("the budget was spent; there is nothing left to wait for")

    monkeypatch.setattr(chromium.asyncio, "sleep", fake_sleep)
    host = ChromiumHost()

    from app.browser_host.chromium import AtCapacityError

    with pytest.raises(AtCapacityError):
        await host._reserve_slot()
    assert host._pending_slots == 0


# --- the startup memory baseline ---


@pytest.mark.unit
def test_a_new_host_has_no_memory_baseline_to_subtract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Before start() the baseline is zero, so the estimate is the raw usage."""
    monkeypatch.setattr(settings, "BROWSER_HOST_SESSION_COST_FLOOR_MB", 1)
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (100.0, 1000.0))
    host = ChromiumHost()
    host._sessions = {"s1": make_session()}

    assert host._estimate_session_cost_mb() == 100.0


@pytest.mark.unit
async def test_start_takes_the_baseline_from_used_memory_not_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The baseline is the engine+host floor, so the estimate measures only growth."""
    monkeypatch.setattr(settings, "BROWSER_HOST_SESSION_COST_FLOOR_MB", 1)
    monkeypatch.setattr(chromium.asyncio, "to_thread", AsyncMock(return_value="/tmp/chrome"))
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (300.0, 4000.0))
    host = ChromiumHost()
    host._launch = AsyncMock()
    host._reaper_loop = AsyncMock()
    host._watch_loop = AsyncMock()

    await host.start()

    host._sessions = {"s1": make_session()}
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (400.0, 4000.0))
    # 400 used - 300 baseline = 100 MB attributable to the one live session.
    assert host._estimate_session_cost_mb() == 100.0


@pytest.mark.unit
async def test_start_arms_the_watcher_so_a_crash_recovers_without_the_reaper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery must not wait out the 15s reaper sweep after the engine dies."""
    monkeypatch.setattr(chromium.asyncio, "to_thread", AsyncMock(return_value="/tmp/chrome"))
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (300.0, 4000.0))
    host = ChromiumHost()
    proc = _ExitingProc()
    recovered = asyncio.Event()

    async def launch() -> None:
        host._proc = proc  # type: ignore[assignment]  # a stub for the typed asyncio Process

    async def recover() -> None:
        host._stopping.set()
        recovered.set()

    monkeypatch.setattr(host, "_launch", launch)
    monkeypatch.setattr(host, "_recover_crash", recover)
    host._reaper_loop = AsyncMock()

    await host.start()
    await asyncio.sleep(0)  # let the watcher reach proc.wait()
    proc.die(-11)
    await asyncio.wait_for(recovered.wait(), timeout=1.0)

    assert host._watcher_task is not None
    await _drain(host._watcher_task)


async def _drain(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _parked() -> None:
    """Stands in for the watcher: alive until someone cancels it."""
    await asyncio.Event().wait()


@pytest.mark.unit
async def test_stop_releases_the_watcher_and_can_be_called_twice() -> None:
    """stop() cancels the supervisor, swallows its CancelledError, and clears it."""
    host = ChromiumHost()
    host._watcher_task = asyncio.create_task(_parked())

    await host.stop()

    assert host._watcher_task is None
    await host.stop()  # idempotent: nothing left to cancel


@pytest.mark.unit
async def test_watch_loop_reports_the_crash_with_the_engine_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wide event must name the operation and the returncode that proves the crash."""
    host = ChromiumHost()
    proc = _ExitingProc()
    host._proc = proc  # type: ignore[assignment]  # a stub for the typed asyncio Process

    async def recover() -> None:
        host._stopping.set()

    monkeypatch.setattr(host, "_recover_crash", recover)

    with patch.object(chromium, "log") as mock_log:
        task = asyncio.create_task(host._watch_loop())
        await asyncio.sleep(0)
        proc.die(-11)
        await task

    mock_log.error.assert_called_once_with(
        f"{LogTag.BROWSER} browser engine process exited",
        browser={"operation": "crash_detect", "returncode": -11},
    )


# --- launch preconditions name what is missing ---


@pytest.mark.unit
def test_chromium_command_names_the_unresolved_binary_path() -> None:
    host = ChromiumHost()
    with pytest.raises(RuntimeError, match=r"^chromium_path not set$"):
        host._chromium_command()


@pytest.mark.unit
async def test_read_devtools_port_names_the_missing_user_data_dir() -> None:
    host = ChromiumHost()
    with pytest.raises(RuntimeError, match=r"^user_data_dir not set$"):
        await host._read_devtools_port()


class _CaseSensitiveDir:
    """A Path stand-in whose exists() is case-sensitive on any filesystem.

    macOS's default APFS is case-insensitive, so a real-file test cannot tell
    DevToolsActivePort from devtoolsactiveport — the exact name Chromium
    writes would go unchecked on a developer machine and only break in the Linux
    container. This makes the lookup behave the way production's filesystem does.
    """

    def __init__(self, root: str, name: str = "") -> None:
        self._root = Path(root)
        self._name = name

    def __truediv__(self, name: str) -> _CaseSensitiveDir:
        return _CaseSensitiveDir(str(self._root), name)

    def exists(self) -> bool:
        return self._name in {entry.name for entry in self._root.iterdir()}

    def read_text(self) -> str:
        return (self._root / self._name).read_text()


@pytest.mark.unit
async def test_read_devtools_port_reads_the_exact_file_chromium_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Chromium writes DevToolsActivePort; any other spelling never appears."""
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(chromium, "_CDP_READY_POLL_SECONDS", 0.01)
    monkeypatch.setattr(chromium, "Path", _CaseSensitiveDir)
    (tmp_path / "DevToolsActivePort").write_text("9222\n/devtools/browser/abc\n")
    host = ChromiumHost()
    host._user_data_dir = str(tmp_path)

    assert await host._read_devtools_port() == 9222


# --- the resource sampler follows the engine process ---


@pytest.mark.unit
async def test_launch_samples_the_engine_process_it_just_started(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without a sampler bound to the live pid, every session's metrics stay empty."""
    host = ChromiumHost()
    host._chromium_path = str(tmp_path / "headless_shell")
    monkeypatch.setattr(settings, "BROWSER_HOST_HEADED", True)
    monkeypatch.setattr(chromium.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    monkeypatch.setattr(
        chromium.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=MagicMock(returncode=None, pid=os.getpid())),
    )
    host._await_cdp_ready = AsyncMock(return_value="ws://127.0.0.1:9222")
    mock_mux = MagicMock()
    mock_mux.start = AsyncMock()
    with patch.object(chromium, "CdpMux", return_value=mock_mux):
        await host._launch()

    host._sessions["s1"] = make_session()
    host.sample_resources("s1")

    rss = host._sessions["s1"].metrics.snapshot()["rss_mb"]
    assert rss is not None and rss["count"] == 1


@pytest.mark.unit
async def test_shutdown_drops_the_sampler_so_later_samples_are_silent_no_ops() -> None:
    """Sampling a torn-down engine records nothing rather than exploding."""
    host = ChromiumHost()
    host._proc = None
    host._sampler = _FixedSampler()  # type: ignore[assignment]  # a ProcessSampler stub
    host._sessions["s1"] = make_session()

    await host._shutdown_chromium()
    host.sample_resources("s1")

    assert host._sessions["s1"].metrics.snapshot()["rss_mb"] is None


@pytest.mark.unit
async def test_create_context_records_a_resource_sample_for_the_new_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host, mux = _host_and_mux(monkeypatch)
    host._sampler = _FixedSampler((42.0, 7.0))  # type: ignore[assignment]  # a ProcessSampler stub

    session = await host.create_context(None)

    assert session.metrics.snapshot()["rss_mb"] == {
        "count": 1,
        "min": 42.0,
        "max": 42.0,
        "avg": 42.0,
    }


@pytest.mark.unit
async def test_dispose_context_samples_and_logs_the_final_metrics_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The disposal event carries the session's real metrics under the browser namespace."""
    host, mux = _host_and_mux(monkeypatch)
    host._sampler = _FixedSampler((42.0, 7.0))  # type: ignore[assignment]  # a ProcessSampler stub
    host._sessions["s1"] = make_session()

    with patch.object(chromium, "log") as mock_log:
        await host.dispose_context("s1")

    (namespace,) = mock_log.set_ns.call_args.args
    metrics = mock_log.set_ns.call_args.kwargs["metrics"]
    assert namespace == "browser"
    assert metrics["rss_mb"] == {"count": 1, "min": 42.0, "max": 42.0, "avg": 42.0}


@pytest.mark.unit
async def test_note_navigation_finished_samples_only_a_navigation_the_client_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsolicited load event closes no timing, so it must not sample either."""
    host, mux = _host_and_mux(monkeypatch)
    host._sampler = _FixedSampler((42.0, 7.0))  # type: ignore[assignment]  # a ProcessSampler stub
    host._sessions["s1"] = make_session()

    host.note_navigation_finished("s1")
    assert host._sessions["s1"].metrics.snapshot()["rss_mb"] is None

    host.note_navigation_started("s1")
    host.note_navigation_finished("s1")
    rss = host._sessions["s1"].metrics.snapshot()["rss_mb"]
    assert rss is not None and rss["count"] == 1


@pytest.mark.unit
async def test_launch_binds_the_sampler_to_the_engine_pid_not_the_host_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """psutil.Process(None) is this process; a sampler seeded with None reports API memory, not the browser's."""
    host = ChromiumHost()
    host._chromium_path = str(tmp_path / "headless_shell")
    monkeypatch.setattr(settings, "BROWSER_HOST_HEADED", True)
    monkeypatch.setattr(chromium.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    monkeypatch.setattr(
        chromium.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=MagicMock(returncode=None, pid=31337)),
    )
    host._await_cdp_ready = AsyncMock(return_value="ws://127.0.0.1:9222")
    sampled_pids: list[int | None] = []

    def record(pid: int | None) -> _FixedSampler:
        sampled_pids.append(pid)
        return _FixedSampler()

    monkeypatch.setattr(ProcessSampler, "for_pid", record)
    mock_mux = MagicMock()
    mock_mux.start = AsyncMock()
    with patch.object(chromium, "CdpMux", return_value=mock_mux):
        await host._launch()

    assert sampled_pids == [31337]
