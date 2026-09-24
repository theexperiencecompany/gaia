"""What was typed into a password field never reads back, however a page quotes it."""

import pytest

from app.constants.browser import JEV_SECRET_MASK
from app.services.browser.jev.secrets import TypedSecrets

pytestmark = pytest.mark.unit


def test_a_secret_is_masked_as_typed_and_as_a_url_carries_it() -> None:
    secrets = TypedSecrets()
    secrets.add("pa ss/wörd")

    text = secrets.redact("typed pa ss/wörd; ?pw=pa+ss%2Fw%C3%B6rd; /pa%20ss/w%C3%B6rd")

    assert text == f"typed {JEV_SECRET_MASK}; ?pw={JEV_SECRET_MASK}; /{JEV_SECRET_MASK}"


def test_text_is_untouched_when_nothing_secret_was_typed() -> None:
    assert TypedSecrets().redact("my-text=Aryan") == "my-text=Aryan"
