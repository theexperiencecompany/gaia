"""The derived-name cleanup clears exactly the names signup guessed from the email, and only on --apply."""

from unittest.mock import AsyncMock, patch

import pytest
from scripts.clear_email_derived_names import (
    DerivedName,
    clear_email_derived_names,
    derive_name_from_email,
)

from app.models.user_models import UserDocument

REPO = "scripts.clear_email_derived_names.user_repository"
GUESSED = UserDocument(id="u-guessed", name="Aryan Randeriya", email="aryan.randeriya@x.com")
CHOSEN = UserDocument(id="u-chosen", name="Ari", email="aryan.randeriya@x.com")
CASED = UserDocument(id="u-cased", name="aryan randeriya", email="aryan.randeriya@x.com")


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
            ("john.doe@sub@example.com", "John Doe"),
            ("john.doe+a+b+c@example.com", "John Doe"),
        ],
    )
    def test_matches_what_signup_stored(self, email: str, expected: str) -> None:
        assert derive_name_from_email(email) == expected

    @pytest.mark.parametrize(
        ("email", "expected"),
        [("12345@example.com", "12345"), ("...@example.com", "..."), ("@example.com", "")],
    )
    def test_degenerate_local_parts_were_stored_raw(self, email: str, expected: str) -> None:
        assert derive_name_from_email(email) == expected


@pytest.mark.unit
class TestClearEmailDerivedNames:
    async def test_a_dry_run_reports_only_exact_guesses_and_writes_nothing(self) -> None:
        with patch(REPO) as repo:
            repo.find_named_with_email = AsyncMock(return_value=[GUESSED, CHOSEN, CASED])
            repo.clear_name_if_unchanged = AsyncMock()

            result = await clear_email_derived_names(dry_run=True)

        assert result.scanned == 3
        assert result.candidates == [DerivedName(user_id="u-guessed", name="Aryan Randeriya")]
        repo.clear_name_if_unchanged.assert_not_awaited()

    async def test_apply_clears_each_guess_while_it_is_still_the_stored_name(self) -> None:
        with patch(REPO) as repo:
            repo.find_named_with_email = AsyncMock(return_value=[GUESSED, CHOSEN])
            repo.clear_name_if_unchanged = AsyncMock(return_value=True)

            result = await clear_email_derived_names(dry_run=False)

        repo.clear_name_if_unchanged.assert_awaited_once_with("u-guessed", "Aryan Randeriya")
        assert (result.cleared, result.changed_since_scan) == (1, 0)

    async def test_a_name_changed_since_the_scan_is_kept_and_counted(self) -> None:
        with patch(REPO) as repo:
            repo.find_named_with_email = AsyncMock(return_value=[GUESSED])
            repo.clear_name_if_unchanged = AsyncMock(return_value=False)

            result = await clear_email_derived_names(dry_run=False)

        assert (result.cleared, result.changed_since_scan) == (0, 1)
