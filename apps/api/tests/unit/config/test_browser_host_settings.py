"""The browser host's own settings: a blank key is no key; Fortress's persona settings fail loud.

Compose spells an unset key ${BROWSER_HOST_KEY:-}, an empty string; read as a
key, it made every request fail authentication while the websocket URLs left
it out, so the host refused itself.
"""

from pydantic import ValidationError
import pytest

from app.config.browser_host_settings import BrowserHostSettings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("given", "read"), [("", None), ("k" * 32, "k" * 32)])
def test_a_blank_host_key_reads_as_unset_and_a_real_one_as_itself(
    monkeypatch: pytest.MonkeyPatch, given: str, read: str | None
) -> None:
    monkeypatch.setenv("BROWSER_HOST_KEY", given)

    assert read == BrowserHostSettings().BROWSER_HOST_KEY


@pytest.mark.parametrize(("given", "read"), [("", None), ("jwt-key", "jwt-key")])
def test_a_blank_fortress_license_reads_as_unset_and_a_real_one_as_itself(
    monkeypatch: pytest.MonkeyPatch, given: str, read: str | None
) -> None:
    """Compose spells it ${TILION_LICENSE_KEY:-}: a blank one must leave Fortress on ~/.tilion or v1."""
    monkeypatch.setenv("TILION_LICENSE_KEY", given)

    key = BrowserHostSettings().TILION_LICENSE_KEY
    assert (key.get_secret_value() if key is not None else None) == read


@pytest.mark.parametrize(
    ("given", "read"),
    [("", ("en-US", "en")), ("en-US, de ,de-DE", ("en-US", "de", "de-DE"))],
)
def test_fortress_languages_read_as_a_list_and_a_blank_one_as_the_personas(
    monkeypatch: pytest.MonkeyPatch, given: str, read: tuple[str, ...]
) -> None:
    monkeypatch.setenv("FORTRESS_LANGUAGES", given)

    assert read == BrowserHostSettings().FORTRESS_LANGUAGES


def test_fortress_languages_not_led_by_en_us_refuse_to_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Measured: led by en-IN, created contexts send an Accept-Language their JS does not report."""
    monkeypatch.setenv("FORTRESS_LANGUAGES", "en-IN,en")

    with pytest.raises(ValidationError, match="must start with en-US"):
        BrowserHostSettings()


@pytest.mark.parametrize(
    ("given", "read"), [("", "Asia/Kolkata"), ("Europe/Berlin", "Europe/Berlin")]
)
def test_a_fortress_timezone_is_a_known_zone_and_a_blank_one_the_personas(
    monkeypatch: pytest.MonkeyPatch, given: str, read: str
) -> None:
    monkeypatch.setenv("FORTRESS_TIMEZONE", given)
    assert read == BrowserHostSettings().FORTRESS_TIMEZONE

    monkeypatch.setenv("FORTRESS_TIMEZONE", "Mars/Olympus")
    with pytest.raises(ValidationError):
        BrowserHostSettings()
