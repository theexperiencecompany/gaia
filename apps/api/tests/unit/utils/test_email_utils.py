"""Unit tests for app.utils.email_utils."""

import pytest

from app.utils.email_utils import derive_name_from_email, own_first_name


@pytest.mark.unit
class TestOwnFirstName:
    def test_a_name_the_user_gave_yields_its_first_word(self) -> None:
        assert own_first_name("  Aryan   Randeriya ", "delivered+dev@resend.dev") == "Aryan"

    @pytest.mark.parametrize(
        ("name", "email"),
        [
            ("Delivered", "delivered+dev@resend.dev"),
            ("Jane Doe", "jane.doe@example.com"),
            (None, "a@b.c"),
            ("   ", "a@b.c"),
        ],
    )
    def test_a_blank_or_email_derived_name_is_no_name(self, name: str | None, email: str) -> None:
        """Regression: the brief greeted "Dear Delivered", the signup fallback from the email."""
        assert own_first_name(name, email) is None

    def test_without_an_email_any_name_is_the_users_own(self) -> None:
        assert own_first_name("Delivered", None) == "Delivered"


@pytest.mark.unit
class TestDeriveNameFromEmail:
    @pytest.mark.parametrize(
        ("email", "expected"),
        [
            ("aryan.randeriya@example.com", "Aryan Randeriya"),
            ("john_doe@example.com", "John Doe"),
            ("jane-doe@example.com", "Jane Doe"),
            ("mary.jane_watson-parker@example.com", "Mary Jane Watson Parker"),
            ("aryan@example.com", "Aryan"),
            ("aryan+newsletter@example.com", "Aryan"),
            ("john.doe+gaia.signup@example.com", "John Doe"),
            ("john.doe83@example.com", "John Doe"),
            ("jdoe2@example.com", "Jdoe"),
            ("ARYAN.RANDERIYA@EXAMPLE.COM", "Aryan Randeriya"),
            ("  aryan.randeriya@example.com  ", "Aryan Randeriya"),
            ("john..doe@example.com", "John Doe"),
            (".john.doe.@example.com", "John Doe"),
        ],
    )
    def test_presentable_names(self, email: str, expected: str) -> None:
        assert derive_name_from_email(email) == expected

    @pytest.mark.parametrize(
        ("email", "expected"),
        [
            # Only the FIRST "@" ends the local part: a stray second "@" belongs
            # to the domain, never to the derived name.
            ("john.doe@sub@example.com", "John Doe"),
            # Only the FIRST "+" starts the plus-tag: everything after it is
            # dropped, including further "+" segments.
            ("john.doe+gaia+signup@example.com", "John Doe"),
            ("john.doe+a+b+c@example.com", "John Doe"),
        ],
    )
    def test_only_the_first_delimiter_bounds_the_name(self, email: str, expected: str) -> None:
        assert derive_name_from_email(email) == expected

    @pytest.mark.parametrize(
        ("email", "expected"),
        [
            ("12345@example.com", "12345"),
            ("...@example.com", "..."),
            ("@example.com", ""),
        ],
    )
    def test_degenerate_local_parts_fall_back_to_the_raw_local_part(
        self, email: str, expected: str
    ) -> None:
        assert derive_name_from_email(email) == expected
