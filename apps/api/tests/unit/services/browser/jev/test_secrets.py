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


def test_every_secret_typed_in_the_run_stays_masked() -> None:
    """A password change types the old password and then the new one; neither may read back."""
    secrets = TypedSecrets()
    secrets.add("old-secret")
    secrets.add("new-secret")

    assert secrets.redact("old-secret then new-secret") == (
        f"{JEV_SECRET_MASK} then {JEV_SECRET_MASK}"
    )


def test_a_secret_inside_a_longer_one_does_not_leave_the_rest_of_it_readable() -> None:
    secrets = TypedSecrets()
    secrets.add("word")
    secrets.add("password")

    assert secrets.redact("typed password") == f"typed {JEV_SECRET_MASK}"
