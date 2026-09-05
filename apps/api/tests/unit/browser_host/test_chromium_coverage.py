"""Coverage-focused tests for chromium.py missing lines.

Covers helper conversions, _headless_shell_beside, _resolve_chromium_path,
and ChromiumHost internals with mocked Playwright/subprocess/CDP.
"""

from __future__ import annotations

import asyncio
import contextlib
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
from app.config.settings import settings
from app.constants.browser import BROWSER_VIEWPORT_HEIGHT, BROWSER_VIEWPORT_WIDTH
from app.constants.log_tags import LogTag

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
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    host._sessions["s1"] = s
    assert host.get("s1") is s


@pytest.mark.unit
def test_touch_updates_monotonic(monkeypatch: pytest.MonkeyPatch) -> None:
    host = ChromiumHost()
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
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
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
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
    s = HostSession(
        session_id="s1",
        context_id="ctx1",
        target_id="t1",
        created_at=0,
        last_activity_at=5.0,
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
def test_require_cdp_raises_when_none() -> None:
    host = ChromiumHost()
    with pytest.raises(RuntimeError, match="not connected"):
        host._require_cdp()


@pytest.mark.unit
def test_require_cdp_returns_when_set() -> None:
    host = ChromiumHost()
    fake = MagicMock()
    host._cdp = fake
    assert host._require_cdp() is fake


@pytest.mark.unit
def test_get_internal_raises_session_not_found() -> None:
    host = ChromiumHost()
    with pytest.raises(SessionNotFoundError):
        host._get("ghost")


@pytest.mark.unit
def test_get_internal_returns_session() -> None:
    host = ChromiumHost()
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
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
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    host._sessions["s1"] = s
    host._pending_slots = 1  # 1 session + 1 pending = 2 => at capacity
    from app.browser_host.chromium import AtCapacityError

    with pytest.raises(AtCapacityError):
        await host._reserve_slot()


# ---------------------------------------------------------------------------
# _dispose_context_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_dispose_context_id_noop_when_chromium_down() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=1)  # dead
    host._cdp_call = AsyncMock()
    await host._dispose_context_id("ctx1")
    host._cdp_call.assert_not_called()


@pytest.mark.unit
async def test_dispose_context_id_calls_cdp_when_up() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp_call = AsyncMock(return_value={})
    await host._dispose_context_id("ctx1")
    host._cdp_call.assert_awaited_once_with(
        "Target.disposeBrowserContext", {"browserContextId": "ctx1"}
    )


@pytest.mark.unit
async def test_dispose_context_id_suppresses_exception() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp_call = AsyncMock(side_effect=RuntimeError("boom"))

    await host._dispose_context_id("ctx1")

    # Swallowing is only correct if it actually TRIED first — a mutant that
    # skips the CDP call entirely would also "not raise".
    host._cdp_call.assert_awaited_once_with(
        "Target.disposeBrowserContext", {"browserContextId": "ctx1"}
    )


@pytest.mark.unit
async def test_dispose_context_id_noop_when_proc_none() -> None:
    host = ChromiumHost()
    host._proc = None
    host._cdp_call = AsyncMock()
    await host._dispose_context_id("ctx1")
    host._cdp_call.assert_not_called()


# ---------------------------------------------------------------------------
# _seed_cookies
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_seed_cookies_no_cookies() -> None:
    host = ChromiumHost()
    host._cdp_call = AsyncMock()
    await host._seed_cookies("ctx1", {"cookies": [], "origins": []})
    host._cdp_call.assert_not_called()
    await host._seed_cookies("ctx1", {"cookies": None, "origins": []})
    # second still not called
    host._cdp_call.assert_not_called()


@pytest.mark.unit
async def test_seed_cookies_with_cookies() -> None:
    host = ChromiumHost()
    host._cdp_call = AsyncMock(return_value={})
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
    await host._seed_cookies("ctx1", state)
    host._cdp_call.assert_awaited_once()
    args = host._cdp_call.call_args
    assert args[0][0] == "Storage.setCookies"
    assert args[0][1]["browserContextId"] == "ctx1"
    assert len(args[0][1]["cookies"]) == 1


# ---------------------------------------------------------------------------
# _dump_storage_state
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_dump_storage_state_when_chromium_down() -> None:
    host = ChromiumHost()
    host._proc = None  # chromium_up false
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
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
    host._cdp_call = AsyncMock(side_effect=[{"cookies": [cdp_cookie]}, []])
    # patch _dump_origins to return known
    host._dump_origins = AsyncMock(
        return_value=[
            {"origin": "https://example.com", "localStorage": [{"name": "k", "value": "v"}]}
        ]
    )
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    # _cdp_call first returns cookies, but we also stubbed _dump_origins, so need to adapt:
    # Actually _dump_storage_state calls _cdp_call for Storage.getCookies then _dump_origins.
    # With our side_effect we only mock first call, second call is via _dump_origins stub, so make _cdp_call return cookies for first.
    host._cdp_call = AsyncMock(return_value={"cookies": [cdp_cookie]})
    host._dump_origins = AsyncMock(
        return_value=[
            {"origin": "https://example.com", "localStorage": [{"name": "k", "value": "v"}]}
        ]
    )
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
    host._cdp_call = AsyncMock(return_value={"targetInfos": []})
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    result = await host._dump_origins(s)
    assert result == []


@pytest.mark.unit
async def test_dump_origins_single_page_with_storage() -> None:
    host = ChromiumHost()
    # sequence: getTargets, attachToTarget, Runtime.evaluate, detachFromTarget
    host._cdp_call = AsyncMock(
        side_effect=[
            {"targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx1"}]},
            {"sessionId": "sess-t1"},
            {
                "result": {
                    "value": {
                        "origin": "https://example.com",
                        "localStorage": [{"name": "k", "value": "v"}],
                    }
                }
            },
            {},
        ]
    )
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    result = await host._dump_origins(s)
    assert len(result) == 1
    assert result[0]["origin"] == "https://example.com"


@pytest.mark.unit
async def test_dump_origins_filters_other_context_and_non_page() -> None:
    host = ChromiumHost()
    host._cdp_call = AsyncMock(
        side_effect=[
            {
                "targetInfos": [
                    {"targetId": "t1", "type": "page", "browserContextId": "other"},
                    {"targetId": "t2", "type": "background_page", "browserContextId": "ctx1"},
                    {"targetId": "t3", "type": "page", "browserContextId": "ctx1"},
                ]
            },
            {"sessionId": "sess-t3"},
            {
                "result": {
                    "value": {
                        "origin": "https://example.com",
                        "localStorage": [{"name": "k", "value": "v"}],
                    }
                }
            },
            {},
        ]
    )
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    result = await host._dump_origins(s)
    assert len(result) == 1
    # only t3 should be visited, so attach was for t3
    assert host._cdp_call.call_args_list[1][0][1]["targetId"] == "t3"


@pytest.mark.unit
async def test_dump_origins_empty_value_skipped() -> None:
    host = ChromiumHost()
    host._cdp_call = AsyncMock(
        side_effect=[
            {"targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx1"}]},
            {"sessionId": "sess-t1"},
            {"result": {"value": None}},
            {},
        ]
    )
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    result = await host._dump_origins(s)
    assert result == []


@pytest.mark.unit
async def test_dump_origins_missing_origin_skipped() -> None:
    host = ChromiumHost()
    host._cdp_call = AsyncMock(
        side_effect=[
            {"targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx1"}]},
            {"sessionId": "sess-t1"},
            {"result": {"value": {"origin": "", "localStorage": [{"name": "k", "value": "v"}]}}},
            {},
        ]
    )
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    result = await host._dump_origins(s)
    assert result == []


@pytest.mark.unit
async def test_dump_origins_empty_localstorage_skipped() -> None:
    host = ChromiumHost()
    host._cdp_call = AsyncMock(
        side_effect=[
            {"targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx1"}]},
            {"sessionId": "sess-t1"},
            {"result": {"value": {"origin": "https://example.com", "localStorage": []}}},
            {},
        ]
    )
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    result = await host._dump_origins(s)
    assert result == []


@pytest.mark.unit
async def test_dump_origins_missing_result_key_yields_no_origin_not_a_crash() -> None:
    # The "result" key's default must be a dict ({}), not None, or the
    # chained ``.get("value")`` blows up with AttributeError instead of
    # cleanly skipping this page.
    host = ChromiumHost()
    host._cdp_call = AsyncMock(
        side_effect=[
            {"targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx1"}]},
            {"sessionId": "sess-t1"},
            {},  # Runtime.evaluate response missing the "result" key entirely
            {},
        ]
    )
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    result = await host._dump_origins(s)
    assert result == []


@pytest.mark.unit
async def test_dump_origins_detaches_even_when_evaluate_raises() -> None:
    host = ChromiumHost()
    # evaluate raises, detach must still be called
    host._cdp_call = AsyncMock(
        side_effect=[
            {"targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx1"}]},
            {"sessionId": "sess-t1"},
            RuntimeError("eval boom"),
            {},
        ]
    )
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    with pytest.raises(RuntimeError, match="eval boom"):
        await host._dump_origins(s)
    # detach still awaited
    assert host._cdp_call.call_count == 4


# ---------------------------------------------------------------------------
# _focused_page_meta
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_focused_page_meta_when_chromium_down() -> None:
    host = ChromiumHost()
    host._proc = None
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    url, title = await host._focused_page_meta(s)
    assert url is None and title is None


@pytest.mark.unit
async def test_focused_page_meta_returns_url_title() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp_call = AsyncMock(
        return_value={
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
    )
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    url, title = await host._focused_page_meta(s)
    assert url == "https://example.com"
    assert title == "Example"


@pytest.mark.unit
async def test_focused_page_meta_no_matching_page_returns_none() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp_call = AsyncMock(
        return_value={
            "targetInfos": [
                {"type": "page", "browserContextId": "other", "url": "https://other.com"}
            ]
        }
    )
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    url, title = await host._focused_page_meta(s)
    assert url is None and title is None


# ---------------------------------------------------------------------------
# focused_target_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_focused_target_id_returns_primary_when_no_pages() -> None:
    host = ChromiumHost()
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t-primary", created_at=0, last_activity_at=0
    )
    host._sessions["s1"] = s
    host._cdp_call = AsyncMock(return_value={"targetInfos": []})
    result = await host.focused_target_id("s1")
    assert result == "t-primary"


@pytest.mark.unit
async def test_focused_target_id_returns_primary_when_present() -> None:
    host = ChromiumHost()
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t-primary", created_at=0, last_activity_at=0
    )
    host._sessions["s1"] = s
    host._cdp_call = AsyncMock(
        return_value={
            "targetInfos": [
                {"type": "page", "browserContextId": "ctx1", "targetId": "t-other"},
                {"type": "page", "browserContextId": "ctx1", "targetId": "t-primary"},
            ]
        }
    )
    result = await host.focused_target_id("s1")
    assert result == "t-primary"


@pytest.mark.unit
async def test_focused_target_id_fallback_to_most_recent() -> None:
    host = ChromiumHost()
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t-primary", created_at=0, last_activity_at=0
    )
    host._sessions["s1"] = s
    host._cdp_call = AsyncMock(
        return_value={
            "targetInfos": [
                {"type": "page", "browserContextId": "ctx1", "targetId": "t1"},
                {"type": "page", "browserContextId": "ctx1", "targetId": "t2"},
            ]
        }
    )
    result = await host.focused_target_id("s1")
    assert result == "t2"


@pytest.mark.unit
async def test_focused_target_id_filters_by_context_and_type() -> None:
    host = ChromiumHost()
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t-primary", created_at=0, last_activity_at=0
    )
    host._sessions["s1"] = s
    host._cdp_call = AsyncMock(
        return_value={
            "targetInfos": [
                {"type": "background_page", "browserContextId": "ctx1", "targetId": "bg"},
                {"type": "page", "browserContextId": "other", "targetId": "other"},
                {"type": "page", "browserContextId": "ctx1", "targetId": "t-good"},
            ]
        }
    )
    result = await host.focused_target_id("s1")
    assert result == "t-good"


@pytest.mark.unit
async def test_focused_target_id_excludes_a_page_from_another_context() -> None:
    """type=="page" AND matching context — an ``or`` would leak cross-context
    pages into the candidate list even though our session can't see them."""
    host = ChromiumHost()
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t-primary", created_at=0, last_activity_at=0
    )
    host._sessions["s1"] = s
    host._cdp_call = AsyncMock(
        return_value={
            "targetInfos": [
                {"type": "page", "browserContextId": "other-ctx", "targetId": "cross-target"},
            ]
        }
    )
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
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=10, last_activity_at=20
    )
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
    s = HostSession(
        session_id="s1",
        context_id="ctx1",
        target_id="t1",
        created_at=0,
        last_activity_at=0,
        dead=False,
    )
    host._sessions["s1"] = s
    host._proc = None
    host._focused_page_meta = AsyncMock(return_value=(None, None))
    info = await host.session_info("s1")
    assert info["live"] is False


@pytest.mark.unit
async def test_session_info_live_false_when_dead() -> None:
    host = ChromiumHost()
    s = HostSession(
        session_id="s1",
        context_id="ctx1",
        target_id="t1",
        created_at=0,
        last_activity_at=0,
        dead=True,
    )
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
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    host._sessions["s1"] = s
    host._cdp_call = AsyncMock(return_value={"targetInfos": []})
    result = await host.healthz()
    assert result["sessions"] == 1
    assert result["ok"] is True


@pytest.mark.unit
async def test_healthz_cdp_exception_reports_unresponsive(monkeypatch: pytest.MonkeyPatch) -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp_call = AsyncMock(side_effect=RuntimeError("wedged"))
    result = await host.healthz()
    assert result["ok"] is False
    assert result["cdp_responsive"] is False


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
# create_context / dispose_context integration with mocked _cdp_call
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_create_context_without_storage_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp_call = AsyncMock(
        side_effect=[
            {"browserContextId": "ctx-1"},
            {},
            {"targetId": "t-1"},
        ]
    )
    session = await host.create_context(None)
    assert session.context_id == "ctx-1"
    assert session.target_id == "t-1"
    assert host.get(session.session_id) is not None
    assert host._pending_slots == 0


@pytest.mark.unit
async def test_create_context_with_storage_state_seeds_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp_call = AsyncMock(
        side_effect=[
            {"browserContextId": "ctx-1"},
            {},
            {"targetId": "t-1"},
            {},  # seed cookies
        ]
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
    # 4 calls: createBrowserContext, setDownloadBehavior, createTarget, setCookies
    assert host._cdp_call.call_count == 4


@pytest.mark.unit
async def test_create_context_failure_disposes_context_and_releases_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp_call = AsyncMock(
        side_effect=[
            {"browserContextId": "ctx-1"},
            RuntimeError("setDownloadBehavior boom"),
        ]
    )
    host._dispose_context_id = AsyncMock()
    with pytest.raises(RuntimeError, match="boom"):
        await host.create_context(None)
    assert host._pending_slots == 0
    host._dispose_context_id.assert_awaited_once_with("ctx-1")


@pytest.mark.unit
async def test_create_context_at_capacity_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 1)
    host = ChromiumHost()
    host._sessions["existing"] = HostSession(
        session_id="existing", context_id="ctx0", target_id="t0", created_at=0, last_activity_at=0
    )
    from app.browser_host.chromium import AtCapacityError

    with pytest.raises(AtCapacityError):
        await host.create_context(None)


@pytest.mark.unit
async def test_dispose_context_success(monkeypatch: pytest.MonkeyPatch) -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    host._sessions["s1"] = s
    host._dump_storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    host._dispose_context_id = AsyncMock()
    result = await host.dispose_context("s1")
    assert result == {"cookies": [], "origins": []}
    assert host.get("s1") is None
    host._dispose_context_id.assert_awaited_once_with("ctx1")


@pytest.mark.unit
async def test_dispose_context_raises_when_unknown() -> None:
    host = ChromiumHost()
    with pytest.raises(SessionNotFoundError):
        await host.dispose_context("ghost")


@pytest.mark.unit
async def test_dispose_context_pop_tolerates_concurrent_removal() -> None:
    """The finally block's pop must not KeyError if another coroutine (e.g.
    the idle reaper) already removed this session while the dump was in flight."""
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    host._sessions["s1"] = s

    async def _dump_and_vanish(_session: HostSession) -> dict[str, Any]:
        host._sessions.pop("s1", None)
        return {"cookies": [], "origins": []}

    host._dump_storage_state = _dump_and_vanish
    host._dispose_context_id = AsyncMock()

    result = await host.dispose_context("s1")

    assert result == {"cookies": [], "origins": []}
    host._dispose_context_id.assert_awaited_once_with("ctx1")


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
    mock_cdp = MagicMock()
    mock_cdp.start = AsyncMock()
    with patch.object(chromium, "CDPClient", return_value=mock_cdp):
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
    mock_cdp = MagicMock()
    mock_cdp.start = AsyncMock()
    with patch.object(chromium, "CDPClient", return_value=mock_cdp):
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
    mock_cdp = MagicMock()
    mock_cdp.start = AsyncMock()
    with patch.object(chromium, "CDPClient", return_value=mock_cdp):
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
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 0.5)

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
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 0.5)

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
    mock_cdp = MagicMock()
    mock_cdp.stop = AsyncMock()
    host._cdp = mock_cdp
    mock_proc = MagicMock(returncode=None)
    mock_proc.terminate = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.kill = MagicMock()
    host._proc = mock_proc
    host._root_ws_url = "ws://x"
    await host._shutdown_chromium()
    mock_cdp.stop.assert_awaited_once()
    assert host._cdp is None
    assert host._proc is None
    assert host._root_ws_url is None
    mock_proc.terminate.assert_called_once()


@pytest.mark.unit
async def test_shutdown_chromium_cdp_stop_failure_suppressed() -> None:
    host = ChromiumHost()
    mock_cdp = MagicMock()
    mock_cdp.stop = AsyncMock(side_effect=RuntimeError("boom"))
    host._cdp = mock_cdp
    host._proc = None
    await host._shutdown_chromium()
    assert host._cdp is None


@pytest.mark.unit
async def test_shutdown_chromium_kills_when_terminate_times_out() -> None:
    host = ChromiumHost()
    host._cdp = None
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
    host._cdp = None
    host._proc = None
    host._root_ws_url = None
    await host._shutdown_chromium()
    assert host._cdp is None
    assert host._proc is None


@pytest.mark.unit
async def test_shutdown_chromium_proc_already_dead_no_terminate() -> None:
    host = ChromiumHost()
    host._cdp = None
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
    s_old = HostSession(
        session_id="old",
        context_id="ctx-old",
        target_id="t1",
        created_at=0,
        last_activity_at=now - 20,
        viewer_count=0,
    )
    s_fresh = HostSession(
        session_id="fresh",
        context_id="ctx-fresh",
        target_id="t2",
        created_at=0,
        last_activity_at=now - 5,
        viewer_count=0,
    )
    s_watched = HostSession(
        session_id="watched",
        context_id="ctx-watched",
        target_id="t3",
        created_at=0,
        last_activity_at=now - 20,
        viewer_count=1,
    )
    host._sessions = {"old": s_old, "fresh": s_fresh, "watched": s_watched}
    host._dispose_context_id = AsyncMock()
    await host._reap_idle()
    assert "old" not in host._sessions
    assert "fresh" in host._sessions
    assert "watched" in host._sessions
    host._dispose_context_id.assert_awaited_once_with("ctx-old")


@pytest.mark.unit
async def test_reap_idle_skips_when_none_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 300)
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    s = HostSession(
        session_id="s1",
        context_id="ctx1",
        target_id="t1",
        created_at=0,
        last_activity_at=time.monotonic(),
        viewer_count=0,
    )
    host._sessions["s1"] = s
    host._dispose_context_id = AsyncMock()
    await host._reap_idle()
    host._dispose_context_id.assert_not_called()


@pytest.mark.unit
async def test_recover_crash_marks_dead_clears_and_relaunches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = ChromiumHost()
    s1 = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    s2 = HostSession(
        session_id="s2", context_id="ctx2", target_id="t2", created_at=0, last_activity_at=0
    )
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
# _cdp_call wrapper
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_cdp_call_wrapper_raises_when_no_cdp() -> None:
    host = ChromiumHost()
    host._cdp = None
    with pytest.raises(RuntimeError, match="not connected"):
        await host._cdp_call("Page.enable")


@pytest.mark.unit
async def test_cdp_call_wrapper_forwards_to_cdp_call_fn() -> None:
    host = ChromiumHost()
    fake_cdp = MagicMock()
    host._cdp = fake_cdp
    with patch.object(chromium, "cdp_call", new=AsyncMock(return_value={"ok": 1})) as mock_cdp_call:
        result = await host._cdp_call("Target.getTargets", {"a": 1}, session_id="sess", timeout=5.0)
        assert result == {"ok": 1}
        mock_cdp_call.assert_awaited_once_with(
            fake_cdp, "Target.getTargets", {"a": 1}, session_id="sess", timeout=5.0
        )


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
    ghost = HostSession(
        session_id="ghost",
        context_id="ctx-ghost",
        target_id="t",
        created_at=0,
        last_activity_at=0,
        viewer_count=0,
    )
    # Inject a FakeSessions that pretends ghost is in values() for stale computation
    # but returns None on get (simulating concurrent deletion).
    fake = FakeSessions({"ghost": ghost})
    # Override values() to still return the ghost so stale = ["ghost"]
    # get() returns None, so the loop hits `if session is None: continue`
    host._sessions = fake
    host._dispose_context_id = AsyncMock()
    with patch.object(chromium.time, "monotonic", return_value=9999):
        with patch.object(chromium.settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 1):
            await host._reap_idle()
    host._dispose_context_id.assert_not_called()


@pytest.mark.unit
async def test_reap_idle_continues_past_a_gone_session_to_reap_the_next_one() -> None:
    """A session vanishing mid-sweep must skip only that one entry, not abort
    the whole sweep — a ``break`` here would strand every stale session after it."""
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    first = HostSession(
        session_id="first", context_id="ctx-first", target_id="t1", created_at=0, last_activity_at=0
    )
    gone = HostSession(
        session_id="gone", context_id="ctx-gone", target_id="t2", created_at=0, last_activity_at=0
    )
    last = HostSession(
        session_id="last", context_id="ctx-last", target_id="t3", created_at=0, last_activity_at=0
    )
    # Insertion order matters: `stale` is built by iterating self._sessions,
    # so processing order is first -> gone -> last.
    host._sessions = {"first": first, "gone": gone, "last": last}

    async def _dispose_first_and_steal_gone(context_id: str) -> None:
        if context_id == "ctx-first":
            # Simulate another coroutine removing "gone" while "first" is
            # being disposed, so its own lookup later in this sweep is None.
            del host._sessions["gone"]

    host._dispose_context_id = AsyncMock(side_effect=_dispose_first_and_steal_gone)

    with patch.object(chromium.time, "monotonic", return_value=9999):
        with patch.object(chromium.settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 1):
            await host._reap_idle()

    # "gone" is skipped (its lookup is None), but the sweep must continue on
    # to reap "last" rather than aborting the whole sweep right there.
    host._dispose_context_id.assert_any_await("ctx-last")
    assert "last" not in host._sessions


@pytest.mark.unit
async def test_reap_idle_pop_tolerates_concurrent_removal() -> None:
    """The pop of a stale session must not KeyError if another coroutine
    (e.g. ``dispose_context``) removed it between the lookup and the lock."""
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    stale = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
    host._sessions = {"s1": stale}
    host._dispose_context_id = AsyncMock()

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

    host._dispose_context_id.assert_awaited_once_with("ctx1")


@pytest.mark.unit
async def test_reap_idle_handles_missing_on_second_lookup_with_real_dict() -> None:
    # Simple sanity: empty sessions should not dispose anything (covers no-stale path)
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._dispose_context_id = AsyncMock()
    with patch.object(chromium.time, "monotonic", return_value=9999):
        with patch.object(chromium.settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 1):
            await host._reap_idle()
    host._dispose_context_id.assert_not_called()


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
# Additional coverage: real-stack tests with minimal mocking (external deps only)
# ---------------------------------------------------------------------------
# These tests drive the REAL internal methods via a low-level CDP fake at
# send_raw, so the intermediate layers (cdp_call, _cdp_call, _seed_cookies,
# _dump_storage_state, etc.) are exercised instead of being replaced.
# ---------------------------------------------------------------------------


class _LowLevelCDPFake:
    """Fake at send_raw level so real cdp_call/_cdp_call are exercised."""

    def __init__(self, responses: dict[str, dict[str, object]] | None = None) -> None:
        self.responses: dict[str, dict[str, object]] = responses or {}
        self.calls: list[tuple[str, dict[str, object] | None, str | None]] = []

    async def send_raw(
        self, method: str, params: dict[str, object] | None = None, session_id: str | None = None
    ) -> dict[str, object]:
        self.calls.append((method, params, session_id))
        if method in self.responses:
            return self.responses[method]
        # sensible defaults per method
        if method == "Target.createBrowserContext":
            return {"browserContextId": "ctx-low"}
        if method == "Target.createTarget":
            return {"targetId": "t-low"}
        if method == "Target.getTargets":
            return {"targetInfos": []}
        if method == "Storage.getCookies":
            return {"cookies": []}
        if method == "Browser.setDownloadBehavior":
            return {}
        if method == "Storage.setCookies":
            return {}
        if method == "Target.disposeBrowserContext":
            return {}
        if method == "Target.attachToTarget":
            return {"sessionId": "sess-attach"}
        if method == "Runtime.evaluate":
            return {"result": {"value": None}}
        if method == "Target.detachFromTarget":
            return {}
        return {}


def _host_with_low_fake(responses: dict[str, dict[str, object]] | None = None) -> ChromiumHost:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp = _LowLevelCDPFake(responses)
    return host


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
async def test_cdp_call_wrapper_uses_bounded_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    host = _host_with_low_fake()

    # make send_raw hang so cdp_call's wait_for triggers CDPTimeoutError via _cdp_call
    async def hanging_send_raw(*_a: object, **_kw: object) -> dict[str, object]:
        await asyncio.Event().wait()
        return {}

    host._cdp.send_raw = hanging_send_raw
    # patch the module-level timeout to be tiny so the test is fast
    monkeypatch.setattr(chromium, "_CDP_CALL_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(CDPTimeoutError):
        await host._cdp_call("Target.getTargets", {}, timeout=0.05)


@pytest.mark.unit
async def test_create_context_end_to_end_real_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host = _host_with_low_fake(
        {
            "Target.createBrowserContext": {"browserContextId": "ctx-e2e"},
            "Target.createTarget": {"targetId": "t-e2e"},
        }
    )
    session = await host.create_context(None)
    assert session.context_id == "ctx-e2e"
    assert session.target_id == "t-e2e"
    assert host.get(session.session_id) is session
    assert host._pending_slots == 0
    # verify low-level calls were made (proves real _cdp_call/cdp_call exercised)
    methods = [c[0] for c in host._cdp.calls]
    assert "Target.createBrowserContext" in methods
    assert "Browser.setDownloadBehavior" in methods
    assert "Target.createTarget" in methods


@pytest.mark.unit
async def test_create_context_with_storage_state_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host = _host_with_low_fake()
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
    methods = [c[0] for c in host._cdp.calls]
    assert "Storage.setCookies" in methods
    # verify cookie shape passed to CDP
    for m, p, _ in host._cdp.calls:
        if m == "Storage.setCookies":
            assert p is not None
            assert len(p["cookies"]) == 1


@pytest.mark.unit
async def test_create_context_empty_storage_state_does_not_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host = _host_with_low_fake()
    state = {"cookies": [], "origins": []}
    await host.create_context(state)
    methods = [c[0] for c in host._cdp.calls]
    assert "Storage.setCookies" not in methods


@pytest.mark.unit
async def test_create_context_failure_before_context_id_no_dispose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)

    class FailFirst:
        async def send_raw(
            self,
            method: str,
            params: dict[str, object] | None = None,
            session_id: str | None = None,
        ) -> dict[str, object]:
            if method == "Target.createBrowserContext":
                raise RuntimeError("early boom")
            return {}

    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp = FailFirst()
    # patch _dispose_context_id to detect if it was called
    host._dispose_context_id = AsyncMock()
    with pytest.raises(RuntimeError, match="early boom"):
        await host.create_context(None)
    assert host._pending_slots == 0
    host._dispose_context_id.assert_not_called()


@pytest.mark.unit
async def test_dispose_context_end_to_end_real_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    host = _host_with_low_fake(
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
        }
    )
    s = HostSession(
        session_id="s-e2e",
        context_id="ctx-low",
        target_id="t-low",
        created_at=0,
        last_activity_at=0,
    )
    host._sessions["s-e2e"] = s
    result = await host.dispose_context("s-e2e")
    assert result["cookies"][0]["name"] == "a"
    assert host.get("s-e2e") is None
    # dispose should have been called via real _dispose_context_id -> _cdp_call
    methods = [c[0] for c in host._cdp.calls]
    assert "Target.disposeBrowserContext" in methods


@pytest.mark.unit
async def test_dispose_context_when_chromium_down_returns_empty_and_clears() -> None:
    host = ChromiumHost()
    host._proc = None  # down
    s = HostSession(
        session_id="s-down",
        context_id="ctx-down",
        target_id="t-down",
        created_at=0,
        last_activity_at=0,
    )
    host._sessions["s-down"] = s
    host._cdp = _LowLevelCDPFake()
    # _dump_storage_state will early return empty when chromium_up is False
    result = await host.dispose_context("s-down")
    assert result == {"cookies": [], "origins": []}
    assert host.get("s-down") is None


@pytest.mark.unit
async def test_dispose_context_dump_failure_still_clears_and_logs() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    s = HostSession(
        session_id="s-fail",
        context_id="ctx-fail",
        target_id="t-fail",
        created_at=0,
        last_activity_at=0,
    )
    host._sessions["s-fail"] = s
    host._dump_storage_state = AsyncMock(side_effect=RuntimeError("dump boom"))
    host._dispose_context_id = AsyncMock()
    with patch.object(chromium.log, "error") as mock_err:
        with pytest.raises(RuntimeError, match="dump boom"):
            await host.dispose_context("s-fail")
        # error log for disposed without saving
        assert mock_err.called
    assert host.get("s-fail") is None
    host._dispose_context_id.assert_awaited_once_with("ctx-fail")


@pytest.mark.unit
async def test_seed_cookies_empty_via_real_path() -> None:
    host = _host_with_low_fake()
    await host._seed_cookies("ctx-low", {"cookies": [], "origins": []})
    assert len(host._cdp.calls) == 0
    await host._seed_cookies("ctx-low", {"cookies": None, "origins": []})
    assert len(host._cdp.calls) == 0


@pytest.mark.unit
async def test_seed_cookies_with_real_cdp_call() -> None:
    host = _host_with_low_fake()
    state = {"cookies": [{"name": "n", "value": "v", "domain": "ex.com"}], "origins": []}
    await host._seed_cookies("ctx-low", state)
    assert host._cdp.calls[0][0] == "Storage.setCookies"


@pytest.mark.unit
async def test_dump_storage_state_real_with_cookies_and_origins() -> None:
    host = _host_with_low_fake(
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
        }
    )
    s = HostSession(
        session_id="s1", context_id="ctx-low", target_id="t1", created_at=0, last_activity_at=0
    )
    result = await host._dump_storage_state(s)
    assert len(result["cookies"]) == 1
    assert result["origins"][0]["origin"] == "https://ex.com"


@pytest.mark.unit
async def test_dump_origins_real_multiple_pages() -> None:
    # Use a fake that returns two pages sequentially
    call_idx = 0

    class MultiPageFake:
        async def send_raw(
            self,
            method: str,
            params: dict[str, object] | None = None,
            session_id: str | None = None,
        ) -> dict[str, object]:
            nonlocal call_idx
            call_idx += 1
            if method == "Target.getTargets":
                return {
                    "targetInfos": [
                        {"targetId": "t1", "type": "page", "browserContextId": "ctx-low"},
                        {"targetId": "t2", "type": "page", "browserContextId": "ctx-low"},
                    ]
                }
            if method == "Target.attachToTarget":
                return {"sessionId": f"sess-{params['targetId']}"}
            if method == "Runtime.evaluate":
                return {
                    "result": {
                        "value": {
                            "origin": "https://ex.com",
                            "localStorage": [{"name": "k", "value": "v"}],
                        }
                    }
                }
            if method == "Target.detachFromTarget":
                return {}
            return {}

    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp = MultiPageFake()
    s = HostSession(
        session_id="s1", context_id="ctx-low", target_id="t1", created_at=0, last_activity_at=0
    )
    result = await host._dump_origins(s)
    assert len(result) == 2


@pytest.mark.unit
async def test_focused_page_meta_real() -> None:
    host = _host_with_low_fake(
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
        }
    )
    s = HostSession(
        session_id="s1", context_id="ctx-low", target_id="t1", created_at=0, last_activity_at=0
    )
    url, title = await host._focused_page_meta(s)
    assert url == "https://ex.com"
    assert title == "T"


@pytest.mark.unit
async def test_healthz_real_responsive_and_unresponsive(monkeypatch: pytest.MonkeyPatch) -> None:
    # responsive
    host = _host_with_low_fake({"Target.getTargets": {"targetInfos": []}})
    host._sessions["s1"] = HostSession(
        session_id="s1", context_id="ctx-low", target_id="t1", created_at=0, last_activity_at=0
    )
    res = await host.healthz()
    assert res["ok"] is True
    assert res["cdp_responsive"] is True
    # unresponsive via hanging send_raw
    host2 = ChromiumHost()
    host2._proc = MagicMock(returncode=None)

    async def hanging(*_a: object, **_kw: object) -> dict[str, object]:
        await asyncio.Event().wait()
        return {}

    fake = MagicMock()
    fake.send_raw = hanging
    host2._cdp = fake
    monkeypatch.setattr(chromium, "_CDP_HEALTH_TIMEOUT_SECONDS", 0.05)
    res2 = await host2.healthz()
    assert res2["ok"] is False
    assert res2["cdp_responsive"] is False


@pytest.mark.unit
async def test_session_info_real(monkeypatch: pytest.MonkeyPatch) -> None:
    host = _host_with_low_fake(
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
        }
    )
    s = HostSession(
        session_id="s1", context_id="ctx-low", target_id="t1", created_at=0, last_activity_at=123.0
    )
    host._sessions["s1"] = s
    info = await host.session_info("s1")
    assert info["session_id"] == "s1"
    assert info["live"] is True
    assert info["url"] == "https://ex.com"


@pytest.mark.unit
async def test_focused_target_id_real() -> None:
    host = _host_with_low_fake(
        {
            "Target.getTargets": {
                "targetInfos": [
                    {"type": "page", "browserContextId": "ctx-low", "targetId": "t-other"},
                    {"type": "page", "browserContextId": "ctx-low", "targetId": "t-primary"},
                ]
            }
        }
    )
    s = HostSession(
        session_id="s1",
        context_id="ctx-low",
        target_id="t-primary",
        created_at=0,
        last_activity_at=0,
    )
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
    mock_cdp = MagicMock()
    mock_cdp.start = AsyncMock()
    with patch.object(chromium, "CDPClient", return_value=mock_cdp):
        await host._launch()
    args = chromium.asyncio.create_subprocess_exec.call_args[0]
    assert "--remote-debugging-port=0" in args
    assert "--headless" in args
    assert any("max-old-space-size=512" in a for a in args)
    assert any("window-size" in a for a in args)
    assert host._user_data_dir is not None
    assert host._cdp is mock_cdp
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
    host._cdp = None
    host._proc = None
    host._root_ws_url = None
    await host._shutdown_chromium()
    assert host._cdp is None
    assert host._proc is None


@pytest.mark.unit
async def test_reap_idle_via_real_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 10)
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    now = 5000.0
    monkeypatch.setattr(chromium.time, "monotonic", lambda: now)
    s_stale = HostSession(
        session_id="stale",
        context_id="ctx-stale",
        target_id="t",
        created_at=0,
        last_activity_at=now - 20,
        viewer_count=0,
    )
    s_keep = HostSession(
        session_id="keep",
        context_id="ctx-keep",
        target_id="t",
        created_at=0,
        last_activity_at=now - 5,
        viewer_count=0,
    )
    host._sessions = {"stale": s_stale, "keep": s_keep}
    host._dispose_context_id = AsyncMock()
    await host._reap_idle()
    assert "stale" not in host._sessions
    assert "keep" in host._sessions
    host._dispose_context_id.assert_awaited_once_with("ctx-stale")


@pytest.mark.unit
async def test_recover_crash_real_marks_dead() -> None:
    host = ChromiumHost()
    s = HostSession(
        session_id="s1", context_id="ctx1", target_id="t1", created_at=0, last_activity_at=0
    )
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
    s = HostSession(
        session_id="sv",
        context_id="ctx",
        target_id="t",
        created_at=0,
        last_activity_at=0,
        viewer_count=0,
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
# Exact CDP payloads, exact log records, exact boundaries
# ---------------------------------------------------------------------------
# The tests above prove the shapes that come *back*. These pin what the host
# actually sends to Chromium (method names, params, the session a call is
# routed to), what it writes into the wide event, and where each boundary
# flips — the parts a fake keyed only on method name never checks.
# ---------------------------------------------------------------------------


class _QueuedCDPFake:
    """Recording fake whose per-method answers can vary call to call."""

    def __init__(self, queues: dict[str, list[dict[str, Any]]]) -> None:
        self.queues = {method: list(items) for method, items in queues.items()}
        self.calls: list[tuple[str, dict[str, Any] | None, str | None]] = []

    async def send_raw(
        self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append((method, params, session_id))
        queue = self.queues.get(method)
        if not queue:
            return {}
        return queue.pop(0)


def _session(session_id: str = "s1", context_id: str = "ctx1") -> HostSession:
    return HostSession(
        session_id=session_id,
        context_id=context_id,
        target_id="t1",
        created_at=0.0,
        last_activity_at=0.0,
    )


class _Wedged(RuntimeError):
    """A distinctive exception type so ``error_type=`` is provably the real one."""


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
    host = _host_with_low_fake(
        {
            "Target.createBrowserContext": {"browserContextId": "ctx-x"},
            "Target.createTarget": {"targetId": "t-x"},
        }
    )

    session = await host.create_context(None)

    assert host._cdp.calls == [
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
    host = _host_with_low_fake()

    session = await host.create_context(None)

    assert session == HostSession(
        session_id=session.session_id,
        context_id="ctx-low",
        target_id="t-low",
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
    host = _host_with_low_fake()

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
    host = _host_with_low_fake({"Target.createBrowserContext": {"browserContextId": "ctx-seed"}})
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

    seeds = [c for c in host._cdp.calls if c[0] == "Storage.setCookies"]
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
async def test_create_context_disposes_the_orphan_context_when_the_target_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A context created before the failure has no session to carry it — drop it."""
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host = _host_with_low_fake({"Target.createBrowserContext": {"browserContextId": "ctx-orphan"}})
    real_send = host._cdp.send_raw

    async def fail_on_target(
        method: str, params: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        if method == "Target.createTarget":
            raise _Wedged("no target")
        return await real_send(method, params, session_id)

    host._cdp.send_raw = fail_on_target

    with pytest.raises(_Wedged):
        await host.create_context(None)

    assert (
        "Target.disposeBrowserContext",
        {"browserContextId": "ctx-orphan"},
        None,
    ) in host._cdp.calls
    assert host._sessions == {}
    assert host._pending_slots == 0


# --- dispose_context ---


@pytest.mark.unit
async def test_dispose_context_returns_the_dump_and_logs_a_clean_disposal() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._sessions["s1"] = _session()
    dump = {"cookies": [], "origins": [{"origin": "https://a.test", "localStorage": []}]}
    host._dump_storage_state = AsyncMock(return_value=dump)
    host._dispose_context_id = AsyncMock()

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
    host._sessions["s1"] = _session()
    host._dump_storage_state = AsyncMock(side_effect=_Wedged("dump died"))
    host._dispose_context_id = AsyncMock()

    with patch.object(chromium, "log") as mock_log:
        with pytest.raises(_Wedged):
            await host.dispose_context("s1")

    mock_log.set.assert_called_once_with(browser={"session_id": "s1", "operation": "dispose"})
    mock_log.error.assert_called_once_with(
        f"{LogTag.BROWSER} browser context disposed without saving its storage state",
        error_type="StorageDumpFailed",
    )
    mock_log.info.assert_not_called()


# --- _dispose_context_id ---


@pytest.mark.unit
async def test_dispose_context_id_sends_the_context_scoped_payload() -> None:
    host = _host_with_low_fake()

    await host._dispose_context_id("ctx-bye")

    assert host._cdp.calls == [
        ("Target.disposeBrowserContext", {"browserContextId": "ctx-bye"}, None)
    ]


@pytest.mark.unit
async def test_dispose_context_id_warns_with_the_real_failure_type() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp_call = AsyncMock(side_effect=_Wedged("nope"))

    with patch.object(chromium, "log") as mock_log:
        await host._dispose_context_id("ctx1")

    mock_log.warning.assert_called_once_with(
        f"{LogTag.BROWSER} browser host context dispose failed",
        error_type="_Wedged",
    )


# --- _dump_storage_state / _dump_origins ---


@pytest.mark.unit
async def test_dump_storage_state_reads_cookies_scoped_to_the_session_context() -> None:
    host = _host_with_low_fake(
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
        }
    )

    state = await host._dump_storage_state(_session(context_id="ctx-dump"))

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
    assert ("Storage.getCookies", {"browserContextId": "ctx-dump"}, None) in host._cdp.calls


@pytest.mark.unit
async def test_dump_origins_sends_the_exact_attach_evaluate_detach_sequence() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp = _QueuedCDPFake(
        {
            "Target.getTargets": [
                {"targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx1"}]}
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

    origins = await host._dump_origins(_session())

    assert origins == [{"origin": "https://a.test", "localStorage": [{"name": "k", "value": "v"}]}]
    assert host._cdp.calls == [
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
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp = _QueuedCDPFake(
        {
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

    origins = await host._dump_origins(_session())

    assert [o["origin"] for o in origins] == ["https://one.test", "https://two.test"]
    assert [c[2] for c in host._cdp.calls if c[0] == "Runtime.evaluate"] == ["sess-1", "sess-2"]
    assert [c[1] for c in host._cdp.calls if c[0] == "Target.detachFromTarget"] == [
        {"sessionId": "sess-1"},
        {"sessionId": "sess-2"},
    ]


# --- _focused_page_meta / focused_target_id ---


@pytest.mark.unit
async def test_focused_page_meta_asks_chromium_for_every_target() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp_call = AsyncMock(
        return_value={
            "targetInfos": [
                {
                    "type": "page",
                    "browserContextId": "ctx1",
                    "url": "https://a.test/x",
                    "title": "A",
                }
            ]
        }
    )

    assert await host._focused_page_meta(_session()) == ("https://a.test/x", "A")
    host._cdp_call.assert_awaited_once_with("Target.getTargets", {})


@pytest.mark.unit
async def test_focused_target_id_asks_chromium_for_every_target_and_prefers_the_newest() -> None:
    host = ChromiumHost()
    host._sessions["s1"] = _session()
    host._cdp_call = AsyncMock(
        return_value={
            "targetInfos": [
                {"type": "page", "browserContextId": "ctx1", "targetId": "t-a"},
                {"type": "page", "browserContextId": "ctx1", "targetId": "t-b"},
                {"type": "page", "browserContextId": "ctx1", "targetId": "t-c"},
            ]
        }
    )

    assert await host.focused_target_id("s1") == "t-c"
    host._cdp_call.assert_awaited_once_with("Target.getTargets", {})


# --- healthz ---


@pytest.mark.unit
async def test_healthz_probes_with_the_tighter_health_budget() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp_call = AsyncMock(return_value={"targetInfos": []})

    await host.healthz()

    host._cdp_call.assert_awaited_once_with(
        "Target.getTargets", {}, timeout=chromium._CDP_HEALTH_TIMEOUT_SECONDS
    )


@pytest.mark.unit
async def test_healthz_logs_the_real_failure_type_when_the_probe_blows_up() -> None:
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    host._cdp_call = AsyncMock(side_effect=_Wedged("wedged"))

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
    host._sessions["old"] = HostSession(
        session_id="old",
        context_id="ctx-old",
        target_id="t1",
        created_at=0.0,
        last_activity_at=900.0,
    )
    host._dispose_context_id = AsyncMock()

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
    host._sessions = {"s1": _session("s1"), "s2": _session("s2")}
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
    cdp = MagicMock()
    cdp.start = AsyncMock()

    with patch.object(chromium, "CDPClient", return_value=cdp) as cdp_ctor:
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
    cdp_ctor.assert_called_once_with("ws://ready")
    cdp.start.assert_awaited_once()
    assert host._root_ws_url == "ws://ready"
    assert host._cdp is cdp
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
    host._cdp = None
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
    cdp = MagicMock()
    cdp.stop = AsyncMock(side_effect=_Wedged("dead socket"))
    host._cdp = cdp
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
    assert host._cdp is None
    assert host._root_ws_url is None
    assert host._chromium_path is None
    assert host._user_data_dir is None


@pytest.mark.unit
def test_remove_viewer_drops_exactly_one_watcher() -> None:
    host = ChromiumHost()
    session = _session()
    session.viewer_count = 2
    host._sessions["s1"] = session

    host.remove_viewer("s1")

    assert session.viewer_count == 1


@pytest.mark.unit
def test_require_cdp_and_get_name_what_is_missing() -> None:
    host = ChromiumHost()

    with pytest.raises(RuntimeError) as no_cdp:
        host._require_cdp()
    with pytest.raises(SessionNotFoundError) as no_session:
        host._get("ghost")

    assert str(no_cdp.value) == "browser host CDP client is not connected"
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
