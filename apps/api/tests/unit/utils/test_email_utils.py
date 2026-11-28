"""Unit tests for app.utils.email_utils."""

import pytest

from app.utils.email_utils import canonical_email, mask_email, normalize_email


@pytest.mark.unit
class TestCanonicalEmail:
    def test_it_trims_and_lowercases_the_whole_address(self) -> None:
        assert canonical_email("  Aryan.R@Example.COM ") == "aryan.r@example.com"

    def test_a_mailto_link_resolves_to_the_canonical_address(self) -> None:
        assert normalize_email("mailto: Aryan@Example.com ?subject=Hi") == "aryan@example.com"


@pytest.mark.unit
class TestMaskEmail:
    def test_it_keeps_two_letters_and_the_domain(self) -> None:
        assert mask_email("aryan@heygaia.io") == "ar***@heygaia.io"

    def test_a_one_letter_name_is_still_masked(self) -> None:
        assert mask_email("a@b.co") == "a***@b.co"

    def test_the_domain_is_what_follows_the_last_at_sign(self) -> None:
        assert mask_email('"a@b"@heygaia.io') == '"a***@heygaia.io'
