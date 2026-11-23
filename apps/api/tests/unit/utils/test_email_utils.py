"""Unit tests for app.utils.email_utils."""

import pytest

from app.utils.email_utils import canonical_email, normalize_email


@pytest.mark.unit
class TestCanonicalEmail:
    def test_it_trims_and_lowercases_the_whole_address(self) -> None:
        assert canonical_email("  Aryan.R@Example.COM ") == "aryan.r@example.com"

    def test_a_mailto_link_resolves_to_the_canonical_address(self) -> None:
        assert normalize_email("mailto: Aryan@Example.com ?subject=Hi") == "aryan@example.com"
