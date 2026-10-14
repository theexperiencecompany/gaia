"""What the user said mid-run, as the guidance and the closing reply both read it."""

import pytest

from app.services.browser.user_notes import what_the_user_said

pytestmark = pytest.mark.unit


def test_a_replacement_is_named_as_one_and_the_rest_is_what_the_user_said_in_order() -> None:
    said = what_the_user_said(
        ["make it quick", "skip the login", "just read the title"],
        ["skip the login", "just read the title"],
        replaced="REPLACED {notes}",
        said="SAID {notes}",
    )

    assert said == 'REPLACED "skip the login", then "just read the title"\n\nSAID "make it quick"'


def test_with_nothing_said_there_is_nothing_to_lead_with() -> None:
    assert what_the_user_said([], [], replaced="REPLACED {notes}", said="SAID {notes}") == ""
    assert (
        what_the_user_said(["8pm"], [], replaced="REPLACED {notes}", said="SAID {notes}")
        == 'SAID "8pm"'
    )
