"""The name GAIA shows and greets a user by is the one they gave, never a guess."""

import pytest

from app.models.user_models import UserDocument
from app.utils.user_display import display_first_name, display_name


@pytest.mark.unit
class TestDisplayName:
    def test_collapses_the_whitespace_of_a_given_name(self) -> None:
        assert display_name(UserDocument(name="  Aryan   Randeriya ")) == "Aryan Randeriya"

    @pytest.mark.parametrize("name", [None, "", "   "])
    def test_a_blank_name_is_no_name(self, name: str | None) -> None:
        assert display_name(UserDocument(name=name)) is None


@pytest.mark.unit
class TestDisplayFirstName:
    def test_a_given_name_yields_its_first_word(self) -> None:
        assert display_first_name(UserDocument(name="  Aryan   Randeriya ")) == "Aryan"

    def test_a_one_word_name_is_its_own_first_name(self) -> None:
        assert display_first_name(UserDocument(name="Cher")) == "Cher"

    def test_the_email_never_stands_in_for_a_missing_name(self) -> None:
        """Regression: the brief greeted "Dear Delivered", a name guessed from delivered+dev@resend.dev."""
        assert display_first_name(UserDocument(name=None, email="delivered+dev@resend.dev")) is None
