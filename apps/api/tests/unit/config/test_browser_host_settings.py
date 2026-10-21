"""The browser host's own settings: a blank key is no key.

Compose spells an unset key ${BROWSER_HOST_KEY:-}, an empty string; read as a
key, it made every request fail authentication while the websocket URLs left
it out, so the host refused itself.
"""

import pytest

from app.config.browser_host_settings import BrowserHostSettings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("given", "read"), [("", None), ("k" * 32, "k" * 32)])
def test_a_blank_host_key_reads_as_unset_and_a_real_one_as_itself(
    monkeypatch: pytest.MonkeyPatch, given: str, read: str | None
) -> None:
    monkeypatch.setenv("BROWSER_HOST_KEY", given)

    assert read == BrowserHostSettings().BROWSER_HOST_KEY
