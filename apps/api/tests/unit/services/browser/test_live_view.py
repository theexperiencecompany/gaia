"""Cover create_live_view_link, live_view_url and render_live_view_page.

test_live_code.py already covers the vhost-vs-plain-host branch of
create_live_view_link with an exact-match assertion on the returned URL; this
file targets what that leaves open: that mint_live_code is called with the right
arguments in the right order (an AsyncMock return value alone cannot catch an
argument swap), and live_view_url/render_live_view_page, neither of which any
existing test in the suite calls at all.
"""

import base64
from pathlib import Path
import re
from unittest.mock import AsyncMock

import pytest

from app.services.browser import links, live_view

_WORDMARK_PNG = Path(live_view.__file__).parent / "assets" / "gaia_wordmark_white.png"


@pytest.mark.unit
async def test_create_live_view_link_mints_code_with_session_and_user_in_order(
    monkeypatch,
):
    mint = AsyncMock(return_value="Xk3p9qR2mN4t")
    monkeypatch.setattr(live_view, "mint_live_code", mint)
    monkeypatch.setattr(links.settings, "BROWSER_LIVE_VIEW_BASE_URL", None)
    monkeypatch.setattr(links.settings, "HOST", "https://api.heygaia.io")

    await live_view.create_live_view_link("sess-abc", "user-1")

    # Order matters: swapping the arguments would still return a link (the mock
    # ignores its inputs) but would mint a code for the wrong session/owner pair.
    mint.assert_called_once_with("sess-abc", "user-1")


@pytest.mark.unit
def test_live_view_url_joins_base_and_session_under_the_live_path(monkeypatch):
    monkeypatch.setattr(links.settings, "BROWSER_LIVE_VIEW_BASE_URL", None)
    monkeypatch.setattr(links.settings, "HOST", "https://api.heygaia.io")

    url = live_view.live_view_url("sess-xyz-789")

    # Exact path shape: no vhost-style bare slug here — this is the chat card's
    # own connect URL, always under /live/{session_id}.
    assert url == "https://api.heygaia.io/live/sess-xyz-789"


@pytest.mark.unit
def test_a_base_url_configured_with_a_trailing_slash_does_not_double_the_slash(monkeypatch):
    # "https://host/" is how a base is often written in an .env; the join must
    # still yield one slash, or the link 404s on the router's /live/ route.
    monkeypatch.setattr(links.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.io/")

    assert live_view.live_view_url("sess-1") == "https://browser.heygaia.io/live/sess-1"


@pytest.mark.unit
def test_a_base_under_a_path_prefix_loses_only_its_trailing_slash(monkeypatch):
    # Behind a reverse proxy the base carries a path prefix; trimming must touch
    # the slash alone and leave every character of the prefix in place.
    monkeypatch.setattr(links.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://edge.corp/SANDBOX/")

    assert live_view.live_view_url("sess-1") == "https://edge.corp/SANDBOX/live/sess-1"


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
def test_render_live_view_page_inlines_the_wordmark_so_the_page_needs_no_asset_route():
    page = live_view.render_live_view_page("sess-1")

    src = re.search(r'<img src="data:image/png;base64,([^"]+)" alt="GAIA"', page)
    assert src is not None
    assert base64.b64decode(src.group(1)) == _WORDMARK_PNG.read_bytes()
    assert "__WORDMARK__" not in page


@pytest.mark.unit
def test_render_live_view_page_maps_pointer_input_via_per_frame_css_size():
    """Regression: pointer math reads per-frame cssWidth/cssHeight, not bitmap pixels."""
    page = live_view.render_live_view_page("x")

    assert "cssWidth" in page
    assert "toModifiers" in page


@pytest.mark.unit
def test_render_live_view_page_sends_carriage_return_on_enter_keydown():
    # CDP only fires a key's default action (submit a form, insert a newline)
    # when `text` is set; Enter must send "\r", not the literal key name.
    page = live_view.render_live_view_page("x")

    assert '"\\r"' in page
