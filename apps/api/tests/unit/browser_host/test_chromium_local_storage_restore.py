"""localStorage restore on context creation, the symmetric partner of the dump.

The host dumps per-origin localStorage into storage_state on dispose but used
to re-seed only cookies on the next context, so saved localStorage was stored and
never re-injected (session reuse was cookie-only). These cover the restore:

  * the restore JS if-absent semantics (absent -> set, present -> left alone) and
    its origin-match guard, both mutation-checked,
  * _seed_local_storage registers one restore script per localStorage-bearing
    origin on the context's page, and is a no-op when no origin carries any,
  * create_context wires the restore in after cookies.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.browser_host.chromium import _build_local_storage_restore_js
from tests.unit.browser_host.conftest import FakeMux, install_mux, make_host

_ORIGIN = "https://example.com"
_ENTRIES = [{"name": "token", "value": "abc123"}, {"name": "theme", "value": "dark"}]


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
    """The script must run only when location.origin matches its own origin."""
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
    mux = FakeMux({"Target.attachToTarget": {"sessionId": "page-sess"}})
    host = make_host()
    state = {
        "cookies": [],
        "origins": [
            {"origin": _ORIGIN, "localStorage": [{"name": "token", "value": "abc123"}]},
            {"origin": "https://other.test", "localStorage": [{"name": "k", "value": "v"}]},
        ],
    }

    await host._seed_local_storage(mux, "target-1", state)

    sources = mux.sources_for("Page.addScriptToEvaluateOnNewDocument")
    assert len(sources) == 2
    assert any(_ORIGIN in s for s in sources)
    assert any("https://other.test" in s for s in sources)
    # Scripts are added over the flat page session, then detached.
    assert ("Target.attachToTarget", {"targetId": "target-1", "flatten": True}, None) in mux.calls
    assert all(
        sid == "page-sess"
        for m, _, sid in mux.calls
        if m == "Page.addScriptToEvaluateOnNewDocument"
    )
    assert any(m == "Target.detachFromTarget" for m, _, _ in mux.calls)


@pytest.mark.unit
async def test_seed_local_storage_skips_origins_without_local_storage() -> None:
    """An origin carrying only cookies (empty localStorage) registers nothing."""
    mux = FakeMux({"Target.attachToTarget": {"sessionId": "page-sess"}})
    host = make_host()
    state = {"cookies": [], "origins": [{"origin": _ORIGIN, "localStorage": []}]}

    await host._seed_local_storage(mux, "target-1", state)

    assert mux.calls == []  # no attach, no script, no detach


@pytest.mark.unit
async def test_seed_local_storage_no_origins_is_a_noop() -> None:
    mux = FakeMux({"Target.attachToTarget": {"sessionId": "page-sess"}})
    host = make_host()

    await host._seed_local_storage(mux, "target-1", {"cookies": [], "origins": []})

    assert mux.calls == []


@pytest.mark.unit
async def test_seed_local_storage_detaches_even_when_a_script_add_fails() -> None:
    """The flat page session must be released even if a script registration raises."""

    class _FailingMux(FakeMux):
        async def send_raw(
            self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None
        ) -> dict[str, Any]:
            result = await super().send_raw(method, params, session_id)
            if method == "Page.addScriptToEvaluateOnNewDocument":
                raise RuntimeError("boom")
            return result

    mux = _FailingMux({"Target.attachToTarget": {"sessionId": "page-sess"}})
    host = make_host()
    state = {
        "cookies": [],
        "origins": [{"origin": _ORIGIN, "localStorage": [{"name": "k", "value": "v"}]}],
    }

    with pytest.raises(RuntimeError, match="boom"):
        await host._seed_local_storage(mux, "target-1", state)

    assert any(m == "Target.detachFromTarget" for m, _, _ in mux.calls)


# ---------------------------------------------------------------------------
# create_context — restore is wired in after cookies
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_create_context_registers_restore_when_origins_carry_local_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mux = install_mux(
        monkeypatch,
        FakeMux(
            {
                "Target.createBrowserContext": {"browserContextId": "ctx-1"},
                "Target.createTarget": {"targetId": "target-1"},
                "Target.attachToTarget": {"sessionId": "page-sess"},
            }
        ),
    )
    host = make_host()
    state = {
        "cookies": [],
        "origins": [{"origin": _ORIGIN, "localStorage": [{"name": "token", "value": "abc123"}]}],
    }

    await host.create_context(state)

    sources = mux.sources_for("Page.addScriptToEvaluateOnNewDocument")
    assert len(sources) == 1
    assert _ORIGIN in sources[0]
    # Registered on the page target the context actually created.
    assert ("Target.attachToTarget", {"targetId": "target-1", "flatten": True}, None) in mux.calls


@pytest.mark.unit
async def test_create_context_skips_restore_when_no_local_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mux = install_mux(
        monkeypatch,
        FakeMux(
            {
                "Target.createBrowserContext": {"browserContextId": "ctx-1"},
                "Target.createTarget": {"targetId": "target-1"},
            }
        ),
    )
    host = make_host()

    await host.create_context({"cookies": [], "origins": []})

    assert mux.sources_for("Page.addScriptToEvaluateOnNewDocument") == []
    assert all(m != "Target.attachToTarget" for m, _, _ in mux.calls)


# The exact script, and the exact page session it is registered on: it pins
# the whole string, since the restore runs as page JS and a stray character
# anywhere in it is a syntax error that silently restores nothing.

_EXPECTED_RESTORE_JS = (
    '(() => { if (location.origin !== "https://example.com") return;'
    ' const entries = [{"name": "token", "value": "abc123"}];'
    " for (const e of entries) {"
    " if (localStorage.getItem(e.name) === null)"
    " localStorage.setItem(e.name, e.value); } })()"
)


@pytest.mark.unit
def test_restore_js_is_the_exact_script_the_page_will_run() -> None:
    js = _build_local_storage_restore_js(_ORIGIN, [{"name": "token", "value": "abc123"}])
    assert js == _EXPECTED_RESTORE_JS


@pytest.mark.unit
async def test_seed_local_storage_registers_the_exact_script_and_detaches_that_session() -> None:
    """The saved entries reach the page verbatim, and the flat session is released."""
    mux = FakeMux({"Target.attachToTarget": {"sessionId": "page-sess"}})
    host = make_host()
    state = {
        "cookies": [],
        "origins": [{"origin": _ORIGIN, "localStorage": [{"name": "token", "value": "abc123"}]}],
    }

    await host._seed_local_storage(mux, "target-1", state)

    assert mux.sources_for("Page.addScriptToEvaluateOnNewDocument") == [_EXPECTED_RESTORE_JS]
    assert ("Target.detachFromTarget", {"sessionId": "page-sess"}, None) in mux.calls
