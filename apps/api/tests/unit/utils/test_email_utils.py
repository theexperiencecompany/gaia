"""Unit tests for app.utils.email_utils."""

import pytest

from app.utils.email_utils import derive_name_from_email


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
            ("12345@example.com", "12345"),
            ("...@example.com", "..."),
            ("@example.com", ""),
        ],
    )
    def test_degenerate_local_parts_fall_back_to_the_raw_local_part(
        self, email: str, expected: str
    ) -> None:
        assert derive_name_from_email(email) == expected
