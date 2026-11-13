"""The stealth init script carries the user's own fingerprint seed, never the template's placeholder."""

import pytest

from app.browser_host.stealth import build_stealth_script

pytestmark = pytest.mark.unit


def test_the_users_seed_is_baked_into_the_script_in_place_of_the_placeholder() -> None:
    script = build_stealth_script(918273)

    assert "918273" in script
    assert "FINGERPRINT_SEED" not in script


def test_two_users_get_two_different_fingerprints() -> None:
    assert build_stealth_script(1) != build_stealth_script(2)
