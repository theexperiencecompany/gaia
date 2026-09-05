"""localStorage restore on context creation — the symmetric partner of the dump.

The host dumps per-origin localStorage into ``storage_state`` on dispose but used
to re-seed only cookies on the next context, so saved localStorage was stored and
never re-injected (session reuse was cookie-only). These cover the restore:

  * the restore JS if-absent semantics (absent -> set, present -> left alone) and
    its origin-match guard, both mutation-checked,
  * ``_seed_local_storage`` registers one restore script per localStorage-bearing
    origin on the context's page, and is a no-op when no origin carries any,
  * ``create_context`` wires the restore in after cookies.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.browser_host.chromium import (
    ChromiumHost,
    _build_local_storage_restore_js,
)
from app.config.settings import settings

_ORIGIN = "https://example.com"
_ENTRIES = [{"name": "token", "value": "abc123"}, {"name": "theme", "value": "dark"}]


class _RecordingCDP:
    """Records every ``send_raw`` call and answers from a per-method response map."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, dict[str, Any] | None, str | None]] = []

    async def send_raw(
        self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append((method, params, session_id))
        return self.responses.get(method, {})

    def sources_for(self, method: str) -> list[str]:
        return [p["source"] for m, p, _ in self.calls if m == method and p is not None]


def _make_host(cdp: _RecordingCDP) -> ChromiumHost:
    host = ChromiumHost()
    host._cdp = cdp
    host._proc = MagicMock(returncode=None)  # chromium_up == True
    return host


# ---------------------------------------------------------------------------
# _build_local_storage_restore_js — if-absent + origin-match semantics
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_restore_js_only_sets_a_key_that_is_absent() -> None:
    """A page value updated during the session must never be clobbered on re-run."""
    js = _build_local_storage_restore_js(_ORIGIN, _ENTRIES)
    # The if-absent guard is the whole point: set only when the page hasn't.
    assert "localStorage.getItem(e.name) === null" in js
    assert "localStorage.setItem(e.name, e.value)" in js
    # setItem is gated behind the null check, never issued unconditionally.
    guard_pos = js.index("localStorage.getItem(e.name) === null")
    set_pos = js.index("localStorage.setItem(e.name, e.value)")
    assert guard_pos < set_pos


@pytest.mark.unit
def test_restore_js_guards_on_the_origin() -> None:
    """The script must run only when ``location.origin`` matches its own origin."""
    js = _build_local_storage_restore_js(_ORIGIN, _ENTRIES)
    assert f'location.origin !== "{_ORIGIN}"' in js
    # The guard returns early, so a mismatched origin writes nothing.
    assert "return;" in js
    assert js.index("location.origin") < js.index("localStorage.setItem")


@pytest.mark.unit
def test_restore_js_embeds_entries_as_json_literals() -> None:
    """Keys and values are serialized as JS literals, not string-interpolated."""
    js = _build_local_storage_restore_js(_ORIGIN, _ENTRIES)
    assert '"token"' in js and '"abc123"' in js
    assert '"theme"' in js and '"dark"' in js


@pytest.mark.unit
def test_restore_js_escapes_hostile_values() -> None:
    """A value containing quotes/scripts is JSON-escaped, not injected raw."""
    js = _build_local_storage_restore_js(_ORIGIN, [{"name": "x", "value": '"</script>'}])
    # json.dumps escapes the quote and the slash so the literal can't break out.
    assert '"\\"<\\/script>"' in js or '"\\"</script>"' in js


# ---------------------------------------------------------------------------
# _seed_local_storage — registers per origin, skips when none
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_seed_local_storage_registers_one_script_per_origin() -> None:
    cdp = _RecordingCDP({"Target.attachToTarget": {"sessionId": "page-sess"}})
    host = _make_host(cdp)
    state = {
        "cookies": [],
        "origins": [
            {"origin": _ORIGIN, "localStorage": [{"name": "token", "value": "abc123"}]},
            {"origin": "https://other.test", "localStorage": [{"name": "k", "value": "v"}]},
        ],
    }

    await host._seed_local_storage("target-1", state)

    sources = cdp.sources_for("Page.addScriptToEvaluateOnNewDocument")
    assert len(sources) == 2
    assert any(_ORIGIN in s for s in sources)
    assert any("https://other.test" in s for s in sources)
    # Scripts are added over the flat page session, then detached.
    assert ("Target.attachToTarget", {"targetId": "target-1", "flatten": True}, None) in cdp.calls
    assert all(
        sid == "page-sess"
        for m, _, sid in cdp.calls
        if m == "Page.addScriptToEvaluateOnNewDocument"
    )
    assert any(m == "Target.detachFromTarget" for m, _, _ in cdp.calls)


@pytest.mark.unit
async def test_seed_local_storage_skips_origins_without_local_storage() -> None:
    """An origin carrying only cookies (empty localStorage) registers nothing."""
    cdp = _RecordingCDP({"Target.attachToTarget": {"sessionId": "page-sess"}})
    host = _make_host(cdp)
    state = {"cookies": [], "origins": [{"origin": _ORIGIN, "localStorage": []}]}

    await host._seed_local_storage("target-1", state)

    assert cdp.calls == []  # no attach, no script, no detach


@pytest.mark.unit
async def test_seed_local_storage_no_origins_is_a_noop() -> None:
    cdp = _RecordingCDP({"Target.attachToTarget": {"sessionId": "page-sess"}})
    host = _make_host(cdp)

    await host._seed_local_storage("target-1", {"cookies": [], "origins": []})

    assert cdp.calls == []


@pytest.mark.unit
async def test_seed_local_storage_detaches_even_when_a_script_add_fails() -> None:
    """The flat page session must be released even if a script registration raises."""

    class _FailingCDP(_RecordingCDP):
        async def send_raw(
            self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None
        ) -> dict[str, Any]:
            await super().send_raw(method, params, session_id)
            if method == "Page.addScriptToEvaluateOnNewDocument":
                raise RuntimeError("boom")
            return self.responses.get(method, {})

    cdp = _FailingCDP({"Target.attachToTarget": {"sessionId": "page-sess"}})
    host = _make_host(cdp)
    state = {
        "cookies": [],
        "origins": [{"origin": _ORIGIN, "localStorage": [{"name": "k", "value": "v"}]}],
    }

    with pytest.raises(RuntimeError, match="boom"):
        await host._seed_local_storage("target-1", state)

    assert any(m == "Target.detachFromTarget" for m, _, _ in cdp.calls)


# ---------------------------------------------------------------------------
# create_context — restore is wired in after cookies
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_create_context_registers_restore_when_origins_carry_local_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    cdp = _RecordingCDP(
        {
            "Target.createBrowserContext": {"browserContextId": "ctx-1"},
            "Target.createTarget": {"targetId": "target-1"},
            "Target.attachToTarget": {"sessionId": "page-sess"},
        }
    )
    host = _make_host(cdp)
    state = {
        "cookies": [],
        "origins": [{"origin": _ORIGIN, "localStorage": [{"name": "token", "value": "abc123"}]}],
    }

    await host.create_context(state)

    sources = cdp.sources_for("Page.addScriptToEvaluateOnNewDocument")
    assert len(sources) == 1
    assert _ORIGIN in sources[0]
    # Registered on the page target the context actually created.
    assert ("Target.attachToTarget", {"targetId": "target-1", "flatten": True}, None) in cdp.calls


@pytest.mark.unit
async def test_create_context_skips_restore_when_no_local_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    cdp = _RecordingCDP(
        {
            "Target.createBrowserContext": {"browserContextId": "ctx-1"},
            "Target.createTarget": {"targetId": "target-1"},
        }
    )
    host = _make_host(cdp)

    await host.create_context({"cookies": [], "origins": []})

    assert cdp.sources_for("Page.addScriptToEvaluateOnNewDocument") == []
    assert all(m != "Target.attachToTarget" for m, _, _ in cdp.calls)
