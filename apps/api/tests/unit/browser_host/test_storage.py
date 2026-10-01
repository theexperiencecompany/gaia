"""A context's storage_state in and out: the restore script and the cookie shapes.

The round trip through a live session is in test_chromium.py; this pins what
that cannot see: the restore script only writes absent keys on its own origin,
and a saved value can never break out of the literal it is embedded in.
"""

from __future__ import annotations

import json

import pytest

from app.browser_host.storage import (
    _cdp_cookie_to_storage_state,
    _storage_state_cookie_to_cdp,
    build_local_storage_restore_js,
)

pytestmark = pytest.mark.unit

_ORIGIN = "https://example.com"


def test_the_restore_writes_only_absent_keys_and_only_on_its_origin() -> None:
    js = build_local_storage_restore_js(_ORIGIN, [{"name": "token", "value": "abc"}])

    assert js == (
        '(() => { if (location.origin !== "https://example.com") return;'
        ' const entries = [{"name": "token", "value": "abc"}];'
        " for (const e of entries) {"
        " if (localStorage.getItem(e.name) === null) localStorage.setItem(e.name, e.value); } })()"
    )


def test_a_hostile_saved_value_stays_inside_its_literal() -> None:
    hostile = [{"name": 'x"); alert(1); ("', "value": "</script><script>alert(2)</script>"}]

    js = build_local_storage_restore_js('https://a.example"); alert(3); ("', hostile)

    assert f"const entries = {json.dumps(hostile)};" in js
    assert "alert(1); (" not in js.replace(json.dumps(hostile), "")


def test_a_saved_cookie_reaches_cdp_with_defaults_for_what_it_omits() -> None:
    sent = _storage_state_cookie_to_cdp({"name": "a", "value": "1", "domain": "x.com"})

    assert sent == {
        "name": "a",
        "value": "1",
        "domain": "x.com",
        "path": "/",
        "secure": False,
        "httpOnly": False,
    }


def test_a_saved_cookie_keeps_the_fields_it_carries() -> None:
    sent = _storage_state_cookie_to_cdp(
        {
            "name": "a",
            "value": "1",
            "domain": "x.com",
            "path": "/app",
            "secure": True,
            "httpOnly": True,
        }
    )

    assert (sent["path"], sent["secure"], sent["httpOnly"]) == ("/app", True, True)


def test_a_session_cookie_is_seeded_without_an_expiry_and_a_real_one_with_it() -> None:
    session_cookie = _storage_state_cookie_to_cdp(
        {"name": "a", "value": "1", "domain": "x.com", "expires": -1, "sameSite": "Strict"}
    )
    zero = _storage_state_cookie_to_cdp(
        {"name": "a", "value": "1", "domain": "x.com", "expires": 0}
    )
    lasting = _storage_state_cookie_to_cdp(
        {"name": "a", "value": "1", "domain": "x.com", "expires": 1_900_000_000}
    )
    first_second = _storage_state_cookie_to_cdp(
        {"name": "a", "value": "1", "domain": "x.com", "expires": 1}
    )

    assert "expires" not in session_cookie
    assert "expires" not in zero
    assert first_second["expires"] == 1
    assert session_cookie["sameSite"] == "Strict"
    assert lasting["expires"] == 1_900_000_000


def test_an_engine_cookie_is_saved_in_storage_state_shape() -> None:
    cookie = {
        "name": "sid",
        "value": "v",
        "domain": ".x.com",
        "path": "/p",
        "expires": 5.0,
        "httpOnly": True,
        "secure": True,
        "size": 4,
    }

    saved = _cdp_cookie_to_storage_state(cookie)

    assert saved == {
        "name": "sid",
        "value": "v",
        "domain": ".x.com",
        "path": "/p",
        "expires": 5.0,
        "httpOnly": True,
        "secure": True,
    }
    assert _cdp_cookie_to_storage_state({**cookie, "sameSite": "None"})["sameSite"] == "None"
