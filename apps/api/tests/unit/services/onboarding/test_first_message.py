"""How the bot opener strings the user's picks together."""

import pytest

from app.services.onboarding.first_message import _join


@pytest.mark.unit
class TestJoin:
    def test_one_phrase_is_itself(self) -> None:
        assert _join(["a"]) == "a"

    def test_two_phrases_are_comma_separated(self) -> None:
        assert _join(["a", "b"]) == "a, b"

    def test_three_or_more_stay_a_flat_comma_list(self) -> None:
        """The opener is one short line; an Oxford "and" made it read as prose."""
        assert _join(["a", "b", "c"]) == "a, b, c"
        assert _join(["a", "b", "c", "d"]) == "a, b, c, d"
