"""hash_platform_user_id must produce the digest the bots log, so user_hash joins across surfaces.

The expected digests are the fixed cross-language vectors pinned in
libs/shared/py/tests/test_logging.py against hashLogIdentifier in the bots.
"""

import pytest

from app.config.settings import settings
from app.utils.log_identifiers import (
    hash_link_viewer,
    hash_platform_user_id,
    hash_short_link_slug,
    user_text_shape,
)
from shared.py.logging import hash_log_identifier

_DIGEST_OF_123456789_UNDER_THE_TEST_LOG_SALT = "h_d374762a95f913ec"
_DIGEST_OF_123456789_UNSALTED = "h_15e2b0d3c33891eb"


class TestHashPlatformUserId:
    def test_it_keys_the_hash_with_the_dedicated_log_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BOT_LOG_HASH_SECRET", "s3cret")
        monkeypatch.setattr(settings, "GAIA_BOT_API_KEY", "a-different-bot-key")

        assert hash_platform_user_id("123456789") == _DIGEST_OF_123456789_UNDER_THE_TEST_LOG_SALT

    def test_the_log_secret_is_used_even_when_no_bot_key_is_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BOT_LOG_HASH_SECRET", "s3cret")
        monkeypatch.setattr(settings, "GAIA_BOT_API_KEY", None)

        assert hash_platform_user_id("123456789") == _DIGEST_OF_123456789_UNDER_THE_TEST_LOG_SALT

    def test_without_a_log_secret_it_falls_back_to_the_bot_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BOT_LOG_HASH_SECRET", None)
        monkeypatch.setattr(settings, "GAIA_BOT_API_KEY", "s3cret")

        assert hash_platform_user_id("123456789") == _DIGEST_OF_123456789_UNDER_THE_TEST_LOG_SALT

    def test_with_no_key_at_all_it_hashes_unkeyed_like_the_bots(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BOT_LOG_HASH_SECRET", None)
        monkeypatch.setattr(settings, "GAIA_BOT_API_KEY", None)

        assert hash_platform_user_id("123456789") == _DIGEST_OF_123456789_UNSALTED

    def test_two_users_never_share_a_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "BOT_LOG_HASH_SECRET", "s3cret")

        assert hash_platform_user_id("123456789") != hash_platform_user_id("987654321")


class TestHashShortLinkSlug:
    def test_it_keys_the_slug_hash_like_every_other_log_hash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BOT_LOG_HASH_SECRET", "s3cret")

        assert hash_short_link_slug("123456789") == _DIGEST_OF_123456789_UNDER_THE_TEST_LOG_SALT


class TestHashLinkViewer:
    def test_it_hashes_address_and_browser_together_under_the_log_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BOT_LOG_HASH_SECRET", "s3cret")

        assert hash_link_viewer("203.0.113.9", "Safari/605") == hash_log_identifier(
            "203.0.113.9|Safari/605", "s3cret"
        )

    def test_the_same_address_in_another_browser_is_another_viewer(self) -> None:
        assert hash_link_viewer("203.0.113.9", "Safari/605") != hash_link_viewer(
            "203.0.113.9", "Firefox/130"
        )


class TestUserTextShape:
    def test_it_records_the_length_and_the_keyed_hash_never_the_words(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BOT_LOG_HASH_SECRET", "s3cret")

        assert user_text_shape("123456789") == {
            "length": 9,
            "hash": _DIGEST_OF_123456789_UNDER_THE_TEST_LOG_SALT,
        }
