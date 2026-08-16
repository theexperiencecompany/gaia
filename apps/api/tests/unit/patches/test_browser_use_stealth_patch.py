"""Tests for the Browser-Use stealth init-script patch.

`Page.addScriptToEvaluateOnNewDocument` is scoped to the CDP session that
registers it, so the fingerprint script must be injected on every per-target
session — not just the first page. The patch hooks
`BrowserSession.get_or_create_cdp_session`, which Browser-Use routes every page
interaction through, and injects once per target (a repeat call must not stack a
duplicate script; a brand-new tab must get its own injection).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.browser_host.stealth import STEALTH_INIT_SCRIPT
import app.patches.browser_use_stealth_patch as patch_module


def _fake_cdp_session(target_id: str) -> SimpleNamespace:
    add_script = AsyncMock(return_value={"identifier": "1"})
    client = SimpleNamespace(
        send=SimpleNamespace(Page=SimpleNamespace(addScriptToEvaluateOnNewDocument=add_script))
    )
    return SimpleNamespace(target_id=target_id, session_id=f"sess-{target_id}", cdp_client=client)


def _patch_original(monkeypatch, session_by_target: dict[str, SimpleNamespace]) -> None:
    async def _fake_original(self, target_id=None, focus=True):
        return session_by_target[target_id]

    monkeypatch.setattr(patch_module, "_original_get_or_create_cdp_session", _fake_original)


def _add_script(session: SimpleNamespace) -> AsyncMock:
    return session.cdp_client.send.Page.addScriptToEvaluateOnNewDocument


@pytest.mark.unit
async def test_injects_the_stealth_script_on_first_use(monkeypatch):
    self = SimpleNamespace()
    cdp = _fake_cdp_session("t1")
    _patch_original(monkeypatch, {"t1": cdp})

    await patch_module._get_or_create_cdp_session(self, target_id="t1")

    _add_script(cdp).assert_awaited_once_with(
        params={"source": STEALTH_INIT_SCRIPT, "runImmediately": True},
        session_id="sess-t1",
    )


@pytest.mark.unit
async def test_does_not_reinject_for_the_same_target(monkeypatch):
    self = SimpleNamespace()
    cdp = _fake_cdp_session("t1")
    _patch_original(monkeypatch, {"t1": cdp})

    await patch_module._get_or_create_cdp_session(self, target_id="t1")
    await patch_module._get_or_create_cdp_session(self, target_id="t1")

    # Same page revisited → the script is registered exactly once, never stacked.
    assert _add_script(cdp).await_count == 1


@pytest.mark.unit
async def test_injects_again_for_a_new_tab(monkeypatch):
    self = SimpleNamespace()
    tab1, tab2 = _fake_cdp_session("t1"), _fake_cdp_session("t2")
    _patch_original(monkeypatch, {"t1": tab1, "t2": tab2})

    await patch_module._get_or_create_cdp_session(self, target_id="t1")
    await patch_module._get_or_create_cdp_session(self, target_id="t2")

    # The regression the patch fixes: a second tab is fingerprint-naked unless it
    # gets its own injection.
    _add_script(tab1).assert_awaited_once()
    _add_script(tab2).assert_awaited_once()


@pytest.mark.unit
async def test_injection_failure_is_swallowed_and_retried(monkeypatch):
    self = SimpleNamespace()
    cdp = _fake_cdp_session("t1")
    _add_script(cdp).side_effect = [RuntimeError("cdp down"), {"identifier": "1"}]
    _patch_original(monkeypatch, {"t1": cdp})

    # A failed injection must not break the page interaction the agent is doing...
    out = await patch_module._get_or_create_cdp_session(self, target_id="t1")
    assert out is cdp
    # ...and because it failed, the target is not marked done — the next call retries.
    await patch_module._get_or_create_cdp_session(self, target_id="t1")
    assert _add_script(cdp).await_count == 2
