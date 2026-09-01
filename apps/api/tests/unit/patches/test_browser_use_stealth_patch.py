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
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.browser_host.stealth import build_stealth_script
import app.patches.browser_use_stealth_patch as patch_module
from app.services.browser.fingerprint import current_fingerprint_seed


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
        params={
            "source": build_stealth_script(current_fingerprint_seed()),
            "runImmediately": True,
        },
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


@pytest.mark.unit
async def test_injection_failure_logs_the_target_and_error_type(monkeypatch):
    self = SimpleNamespace()
    cdp = _fake_cdp_session("t1")
    _add_script(cdp).side_effect = RuntimeError("cdp down")
    _patch_original(monkeypatch, {"t1": cdp})
    warning = MagicMock()
    monkeypatch.setattr(patch_module.log, "warning", warning)

    await patch_module._get_or_create_cdp_session(self, target_id="t1")

    warning.assert_called_once_with(
        "browser stealth init-script injection failed",
        error_type="RuntimeError",
        target_id="t1",
    )


@pytest.mark.unit
async def test_forwards_self_target_id_and_focus_to_the_original_accessor(monkeypatch):
    self = SimpleNamespace()
    cdp = _fake_cdp_session("t1")
    calls: list[tuple[SimpleNamespace, str | None, bool]] = []

    async def _fake_original(self_arg: SimpleNamespace, target_id=None, focus=True):
        calls.append((self_arg, target_id, focus))
        return cdp

    monkeypatch.setattr(patch_module, "_original_get_or_create_cdp_session", _fake_original)

    await patch_module._get_or_create_cdp_session(self, target_id="t1", focus=False)

    # self must be forwarded unchanged (not e.g. None) — the original accessor
    # is a bound-method call site and needs the real BrowserSession instance.
    assert calls == [(self, "t1", False)]


@pytest.mark.unit
async def test_defaults_target_id_none_and_focus_true(monkeypatch):
    self = SimpleNamespace()
    cdp = _fake_cdp_session("t1")
    calls: list[tuple[SimpleNamespace, str | None, bool]] = []

    async def _fake_original(self_arg: SimpleNamespace, target_id=None, focus=True):
        calls.append((self_arg, target_id, focus))
        return cdp

    monkeypatch.setattr(patch_module, "_original_get_or_create_cdp_session", _fake_original)

    await patch_module._get_or_create_cdp_session(self)

    assert calls == [(self, None, True)]


@pytest.mark.unit
def test_apply_binds_the_wrapper_onto_browser_session():
    real_browser_session = patch_module.BrowserSession
    previous = real_browser_session.get_or_create_cdp_session
    try:
        # Reset to the pre-patch accessor to prove apply() is what rebinds it.
        type.__setattr__(
            real_browser_session,
            "get_or_create_cdp_session",
            patch_module._original_get_or_create_cdp_session,
        )
        assert (
            real_browser_session.get_or_create_cdp_session
            is not patch_module._get_or_create_cdp_session
        )

        patch_module.apply()

        assert (
            real_browser_session.get_or_create_cdp_session
            is patch_module._get_or_create_cdp_session
        )
    finally:
        type.__setattr__(real_browser_session, "get_or_create_cdp_session", previous)
