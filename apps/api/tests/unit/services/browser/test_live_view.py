"""``_live_view_base`` resolution, the ``create_live_view_link`` code-minting flow,
the raw ``live_view_url`` builder, and the tokened ``render_live_view_page`` HTML.

``test_live_code.py`` already covers the vhost-vs-plain-host branch of
``create_live_view_link`` with an exact-match assertion on the returned URL; this
file targets what that leaves open: the base-URL fallback/precedence logic in
``_live_view_base`` itself, that ``mint_live_code`` is called with the right
arguments in the right order (an ``AsyncMock`` return value alone can't catch an
argument swap), and ``live_view_url``/``render_live_view_page`` — neither of
which any existing test in the suite calls at all.
"""

from unittest.mock import AsyncMock

import pytest

from app.services.browser import live_view


@pytest.mark.unit
def test_live_view_base_prefers_configured_base_url_over_host(monkeypatch):
    monkeypatch.setattr(
        live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.io"
    )
    monkeypatch.setattr(live_view.settings, "HOST", "https://api.heygaia.io")

    assert live_view._live_view_base() == "https://browser.heygaia.io"


@pytest.mark.unit
def test_live_view_base_falls_back_to_host_when_unset(monkeypatch):
    monkeypatch.setattr(live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", None)
    monkeypatch.setattr(live_view.settings, "HOST", "https://api.heygaia.io")

    assert live_view._live_view_base() == "https://api.heygaia.io"


@pytest.mark.unit
def test_live_view_base_falls_back_to_host_when_base_url_is_empty_string(monkeypatch):
    # "" is falsy but not None — the fallback is an `or`, not an `is None` check.
    monkeypatch.setattr(live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", "")
    monkeypatch.setattr(live_view.settings, "HOST", "https://api.heygaia.io")

    assert live_view._live_view_base() == "https://api.heygaia.io"


@pytest.mark.unit
def test_live_view_base_strips_trailing_slash_from_configured_base_url(monkeypatch):
    monkeypatch.setattr(
        live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.io/"
    )
    monkeypatch.setattr(live_view.settings, "HOST", "https://api.heygaia.io")

    assert live_view._live_view_base() == "https://browser.heygaia.io"


@pytest.mark.unit
def test_live_view_base_rstrip_only_strips_slash_not_other_trailing_chars(monkeypatch):
    # Pins the exact character set passed to rstrip(): it must strip "/" only.
    # A mutant padding that literal to "XX/XX" would strip "/" AND "X" — an
    # unrelated character it should never touch — so a base URL ending in "X/"
    # tells the two apart.
    monkeypatch.setattr(
        live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.ioX/"
    )
    monkeypatch.setattr(live_view.settings, "HOST", "https://api.heygaia.io")

    assert live_view._live_view_base() == "https://browser.heygaia.ioX"


@pytest.mark.unit
def test_live_view_base_strips_trailing_slash_from_host_fallback(monkeypatch):
    monkeypatch.setattr(live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", None)
    monkeypatch.setattr(live_view.settings, "HOST", "https://api.heygaia.io/")

    assert live_view._live_view_base() == "https://api.heygaia.io"


@pytest.mark.unit
async def test_create_live_view_link_mints_code_with_session_and_user_in_order(
    monkeypatch,
):
    mint = AsyncMock(return_value="Xk3p9qR2mN4t")
    monkeypatch.setattr(live_view, "mint_live_code", mint)
    monkeypatch.setattr(live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", None)
    monkeypatch.setattr(live_view.settings, "HOST", "https://api.heygaia.io")

    await live_view.create_live_view_link("sess-abc", "user-1")

    # Order matters: swapping the arguments would still return a link (the mock
    # ignores its inputs) but would mint a code for the wrong session/owner pair.
    mint.assert_called_once_with("sess-abc", "user-1")


@pytest.mark.unit
async def test_create_live_view_link_strips_trailing_slash_from_vhost_base(
    monkeypatch,
):
    monkeypatch.setattr(live_view, "mint_live_code", AsyncMock(return_value="Xk3p9qR2mN4t"))
    monkeypatch.setattr(
        live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.io/"
    )

    link = await live_view.create_live_view_link("sess-abc", "user-1")

    assert link == "https://browser.heygaia.io/Xk3p9qR2mN4t"


@pytest.mark.unit
async def test_create_live_view_link_strips_trailing_slash_from_host_fallback(
    monkeypatch,
):
    monkeypatch.setattr(live_view, "mint_live_code", AsyncMock(return_value="Xk3p9qR2mN4t"))
    monkeypatch.setattr(live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", None)
    monkeypatch.setattr(live_view.settings, "HOST", "https://api.heygaia.io/")

    link = await live_view.create_live_view_link("sess-abc", "user-1")

    assert link == "https://api.heygaia.io/live/Xk3p9qR2mN4t"


@pytest.mark.unit
def test_live_view_url_joins_base_and_session_under_the_live_path(monkeypatch):
    monkeypatch.setattr(live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", None)
    monkeypatch.setattr(live_view.settings, "HOST", "https://api.heygaia.io")

    url = live_view.live_view_url("sess-xyz-789")

    # Exact path shape: no vhost-style bare slug here — this is the chat card's
    # own connect URL, always under /live/{session_id}.
    assert url == "https://api.heygaia.io/live/sess-xyz-789"


@pytest.mark.unit
def test_live_view_url_uses_configured_base_when_present(monkeypatch):
    monkeypatch.setattr(
        live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.io"
    )
    monkeypatch.setattr(live_view.settings, "HOST", "https://api.heygaia.io")

    url = live_view.live_view_url("sess-xyz-789")

    assert url == "https://browser.heygaia.io/live/sess-xyz-789"


@pytest.mark.unit
def test_render_live_view_page_escapes_and_embeds_the_session_id():
    page = live_view.render_live_view_page('sess"<script>&</script>')

    # The placeholder is gone and replaced with the html-escaped session id —
    # not the raw, unescaped value (which would be an XSS hole in the viewer
    # page), and not left as the literal placeholder token.
    assert "__SESSION_ID__" not in page
    assert 'sess"<script>&</script>' not in page
    assert "sess&quot;&lt;script&gt;&amp;&lt;/script&gt;" in page
    assert "(sess&quot;&lt;script&gt;&amp;&lt;/script&gt;)" in page


@pytest.mark.unit
def test_render_live_view_page_embeds_the_wordmark_data_uri():
    page = live_view.render_live_view_page("sess-abc")

    assert "__WORDMARK__" not in page
    assert live_view._WORDMARK_DATA_URI in page
    assert f'src="{live_view._WORDMARK_DATA_URI}"' in page


@pytest.mark.unit
def test_render_live_view_page_differs_by_session_id():
    page_a = live_view.render_live_view_page("sess-aaa")
    page_b = live_view.render_live_view_page("sess-bbb")

    assert page_a != page_b
    assert "sess-aaa" in page_a
    assert "sess-bbb" not in page_a
    assert "sess-bbb" in page_b


@pytest.mark.unit
def test_render_live_view_page_maps_pointer_input_via_per_frame_css_size():
    # Regression: pointer math used to assume frame-bitmap pixels == CSS
    # pixels, so takeover clicks landed short on a downscaled stream. The
    # viewer must read the per-frame cssWidth/cssHeight and use a CDP
    # modifiers bitmask for shift/ctrl/meta state.
    page = live_view.render_live_view_page("x")

    assert "cssWidth" in page
    assert "toModifiers" in page


@pytest.mark.unit
def test_render_live_view_page_sends_carriage_return_on_enter_keydown():
    # CDP only fires a key's default action (submit a form, insert a newline)
    # when `text` is set; Enter must send "\r", not the literal key name.
    page = live_view.render_live_view_page("x")

    assert '"\\r"' in page
