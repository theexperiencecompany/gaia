"""Unit tests for the instance secret store.

Covers the contract: INSTANCE_SECRET env wins, else the Mongo secrets doc,
else generate and persist atomically; plus Fernet key derivation from the
instance secret.
"""

from base64 import urlsafe_b64encode
from hashlib import sha256
import secrets as stdlib_secrets

from cryptography.fernet import Fernet
import pytest

from app.config.settings import settings
import app.services.runtime.secrets_store as secrets_store_module
from app.services.runtime.secrets_store import fernet_key_from, get_instance_secret
from app.utils.errors import AppError

SECRETS_KEY = "secrets"
SECRET_FIELD = "instance_secret"


class _FakeDoc:
    """Minimal stand-in for InstanceSettingsDocument (only value is read)."""

    def __init__(self, value: dict[str, object]) -> None:
        self.value = value


class FakeInstanceSettingsRepo:
    """In-memory fake of the two repository methods the secret store uses.

    find_by_key and set_if_absent mirror the real semantics, including the
    atomic insert-if-absent result.
    """

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, object]] = {}
        self.find_calls: list[str] = []
        self.set_if_absent_calls: list[tuple[str, dict[str, object]]] = []
        # When set, another pod wins every insert race: set_if_absent stores THIS
        # value instead and reports False.
        self.lost_race_secret: str | None = None

    async def find_by_key(self, key: str) -> _FakeDoc | None:
        self.find_calls.append(key)
        if key in self.docs:
            return _FakeDoc(dict(self.docs[key]))
        return None

    async def set_if_absent(self, key: str, value: dict[str, object]) -> bool:
        self.set_if_absent_calls.append((key, value))
        if key in self.docs:
            return False
        if self.lost_race_secret is not None:
            self.docs[key] = {SECRET_FIELD: self.lost_race_secret}
            return False
        self.docs[key] = dict(value)
        return True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_repo(monkeypatch) -> FakeInstanceSettingsRepo:
    """Wire a fresh fake repo into the secret store module."""
    fake = FakeInstanceSettingsRepo()
    monkeypatch.setattr(secrets_store_module, "instance_settings_repository", fake)
    return fake


# ---------------------------------------------------------------------------
# get_instance_secret — env override
# ---------------------------------------------------------------------------


class TestGetInstanceSecretEnvOverride:
    async def test_env_wins_over_db(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "INSTANCE_SECRET", "env-secret")
        repo = make_repo(monkeypatch)
        repo.docs[SECRETS_KEY] = {SECRET_FIELD: "db-secret"}

        assert await get_instance_secret() == "env-secret"
        assert repo.find_calls == []  # DB never consulted when env provides it

    async def test_empty_env_falls_through_to_db(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "INSTANCE_SECRET", "")
        repo = make_repo(monkeypatch)
        repo.docs[SECRETS_KEY] = {SECRET_FIELD: "db-secret"}

        assert await get_instance_secret() == "db-secret"


# ---------------------------------------------------------------------------
# get_instance_secret — Mongo persistence
# ---------------------------------------------------------------------------


class TestGetInstanceSecretFromDb:
    async def test_existing_doc_value_returned(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "INSTANCE_SECRET", None)
        repo = make_repo(monkeypatch)
        repo.docs[SECRETS_KEY] = {SECRET_FIELD: "stored-secret"}

        assert await get_instance_secret() == "stored-secret"

    async def test_corrupt_doc_raises_instead_of_regenerating(self, monkeypatch) -> None:
        """Raise on a secrets doc missing the field; regenerating would orphan prior ciphertexts."""
        monkeypatch.setattr(settings, "INSTANCE_SECRET", None)
        repo = make_repo(monkeypatch)
        repo.docs[SECRETS_KEY] = {}

        with pytest.raises(AppError):
            await get_instance_secret()

    async def test_blank_secret_in_doc_raises(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "INSTANCE_SECRET", None)
        repo = make_repo(monkeypatch)
        repo.docs[SECRETS_KEY] = {SECRET_FIELD: ""}

        with pytest.raises(AppError):
            await get_instance_secret()


class TestGetInstanceSecretGeneration:
    async def test_generates_and_persists_when_missing(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "INSTANCE_SECRET", None)
        repo = make_repo(monkeypatch)

        generated = await get_instance_secret()

        assert isinstance(generated, str) and len(generated) >= 32
        assert all(c.isalnum() or c in "-_" for c in generated)
        assert repo.set_if_absent_calls == [(SECRETS_KEY, {SECRET_FIELD: generated})]
        # The persisted value is what later reads observe.
        assert await get_instance_secret() == generated
        assert len(repo.set_if_absent_calls) == 1  # second call served from the doc

    async def test_lost_race_returns_winner_secret(self, monkeypatch) -> None:
        """Adopt the winner secret when another pod inserts first; both pods then derive identically."""
        monkeypatch.setattr(settings, "INSTANCE_SECRET", None)
        repo = make_repo(monkeypatch)
        repo.lost_race_secret = "winner-secret"

        assert await get_instance_secret() == "winner-secret"


class TestGetInstanceSecretRefusals:
    """Every refusal says what is wrong and how to recover, and never regenerates."""

    async def test_a_doc_without_the_secret_names_the_field_and_the_restore(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "INSTANCE_SECRET", None)
        repo = make_repo(monkeypatch)
        repo.docs[SECRETS_KEY] = {}

        with pytest.raises(AppError) as refused:
            await get_instance_secret()

        assert refused.value.message == (
            "The 'secrets' instance-settings document carries no 'instance_secret' value"
        )
        assert refused.value.why == (
            "regenerating the secret here would orphan every credential "
            "encrypted and session signed under the previous one"
        )
        assert refused.value.fix == (
            "restore 'instance_secret' into the 'secrets' document "
            "(or set INSTANCE_SECRET in the environment to the original secret)"
        )
        assert repo.set_if_absent_calls == []

    async def test_a_non_string_secret_is_not_a_secret(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "INSTANCE_SECRET", None)
        repo = make_repo(monkeypatch)
        repo.docs[SECRETS_KEY] = {SECRET_FIELD: 12345}

        with pytest.raises(AppError):
            await get_instance_secret()

    async def test_a_lost_race_with_no_winner_row_says_so(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "INSTANCE_SECRET", None)
        repo = make_repo(monkeypatch)

        async def _lose_without_a_row(key: str, value: dict[str, object]) -> bool:
            return False

        monkeypatch.setattr(repo, "set_if_absent", _lose_without_a_row)

        with pytest.raises(AppError) as refused:
            await get_instance_secret()

        assert refused.value.message == (
            "Lost the instance-secret insert race but found no persisted secret"
        )
        assert refused.value.why == (
            "the 'secrets' document vanished between the failed insert and the re-read"
        )
        assert refused.value.fix == (
            "retry; if it persists, check for something deleting instance_settings rows"
        )

    async def test_a_lost_race_to_a_malformed_winner_says_so(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "INSTANCE_SECRET", None)
        repo = make_repo(monkeypatch)
        repo.lost_race_secret = ""

        with pytest.raises(AppError) as refused:
            await get_instance_secret()

        assert refused.value.message == (
            "The raced 'secrets' instance-settings document carries no 'instance_secret' value"
        )
        assert refused.value.why == "a concurrent writer stored a malformed secrets document"
        assert refused.value.fix == (
            "inspect the 'secrets' document and restore a valid instance secret"
        )

    async def test_a_generated_secret_carries_48_random_bytes(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "INSTANCE_SECRET", None)
        make_repo(monkeypatch)

        assert len(await get_instance_secret()) == 64  # 48 bytes, url-safe base64


# ---------------------------------------------------------------------------
# fernet_key_from
# ---------------------------------------------------------------------------


class TestFernetKeyFrom:
    def test_matches_specified_derivation(self) -> None:
        expected = urlsafe_b64encode(sha256(b"known-secret").digest())
        assert fernet_key_from("known-secret") == expected

    def test_usable_as_fernet_key_roundtrip(self) -> None:
        fernet = Fernet(fernet_key_from("another-secret"))
        token = fernet.encrypt(b"payload")
        assert fernet.decrypt(token) == b"payload"

    def test_distinct_secrets_produce_distinct_keys(self) -> None:
        assert fernet_key_from("one") != fernet_key_from("two")

    def test_stdlib_secret_is_also_a_valid_key_source(self) -> None:
        # A freshly generated instance secret must always yield a usable key.
        fernet = Fernet(fernet_key_from(stdlib_secrets.token_urlsafe(48)))
        token = fernet.encrypt(b"x")
        assert fernet.decrypt(token) == b"x"
