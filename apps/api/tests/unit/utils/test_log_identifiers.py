"""hash_platform_user_id must produce the digest the bots log, so user_hash joins across surfaces.

The expected digests are the fixed cross-language vectors pinned in
libs/shared/py/tests/test_logging.py against hashLogIdentifier in the bots.
"""

import pytest

from app.config.settings import settings
from app.utils.log_identifiers import hash_platform_user_id

_KEYED_WITH_S3CRET = "h_d374762a95f913ec"
_UNKEYED = "h_15e2b0d3c33891eb"


class TestHashPlatformUserId:
    def test_it_keys_the_hash_with_the_dedicated_log_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BOT_LOG_HASH_SECRET", "s3cret")
        monkeypatch.setattr(settings, "GAIA_BOT_API_KEY", "a-different-bot-key")

        assert hash_platform_user_id("123456789") == _KEYED_WITH_S3CRET

    def test_the_log_secret_is_used_even_when_no_bot_key_is_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BOT_LOG_HASH_SECRET", "s3cret")
        monkeypatch.setattr(settings, "GAIA_BOT_API_KEY", None)

        assert hash_platform_user_id("123456789") == _KEYED_WITH_S3CRET

    def test_without_a_log_secret_it_falls_back_to_the_bot_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BOT_LOG_HASH_SECRET", None)
        monkeypatch.setattr(settings, "GAIA_BOT_API_KEY", "s3cret")

        assert hash_platform_user_id("123456789") == _KEYED_WITH_S3CRET

    def test_with_no_key_at_all_it_hashes_unkeyed_like_the_bots(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BOT_LOG_HASH_SECRET", None)
        monkeypatch.setattr(settings, "GAIA_BOT_API_KEY", None)

        assert hash_platform_user_id("123456789") == _UNKEYED

    def test_two_users_never_share_a_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "BOT_LOG_HASH_SECRET", "s3cret")

        assert hash_platform_user_id("123456789") != hash_platform_user_id("987654321")
