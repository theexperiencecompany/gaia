"""Instance secret: the root secret that signs sessions and encrypts stored credentials.

INSTANCE_SECRET in the environment is the normal path (the CLI generates it on a
fresh install) and keeps the key apart from the ciphertext. Without it the secret
is generated into Mongo, next to the credentials it encrypts, so a database dump
alone decrypts them. Rotating it invalidates every stored credential and session.
"""

from base64 import urlsafe_b64encode
from hashlib import sha256
import secrets

from app.config.settings import settings
from app.db.repositories.instance_settings import instance_settings_repository
from app.utils.errors import AppError

SECRETS_DOC_KEY = "secrets"
# Mongo field NAME inside the secrets doc — not a credential value (B105).
_INSTANCE_SECRET_FIELD = "instance_secret"  # nosec B105


def fernet_key_from(instance_secret: str) -> bytes:
    """Derive a Fernet key from the instance secret (sha-256 → urlsafe b64)."""
    return urlsafe_b64encode(sha256(instance_secret.encode()).digest())


async def get_instance_secret() -> str:
    """Return the instance's root secret: env value, else the Mongo-held one, else generate into Mongo."""
    # Annotated locally: settings attrs resolve to Any for mypy without the
    # pydantic plugin's help.
    env_secret: str | None = settings.INSTANCE_SECRET
    if env_secret:
        return env_secret

    stored = await instance_settings_repository.find_by_key(SECRETS_DOC_KEY)
    if stored is not None:
        existing = _secret_value(stored.value)
        if existing is not None:
            return existing
        raise AppError(
            message=(
                f"The '{SECRETS_DOC_KEY}' instance-settings document carries no "
                f"'{_INSTANCE_SECRET_FIELD}' value"
            ),
            why=(
                "regenerating the secret here would orphan every credential "
                "encrypted and session signed under the previous one"
            ),
            fix=(
                f"restore '{_INSTANCE_SECRET_FIELD}' into the '{SECRETS_DOC_KEY}' document "
                "(or set INSTANCE_SECRET in the environment to the original secret)"
            ),
        )

    generated = secrets.token_urlsafe(48)
    won_insert = await instance_settings_repository.set_if_absent(
        SECRETS_DOC_KEY, {_INSTANCE_SECRET_FIELD: generated}
    )
    if won_insert:
        return generated

    # Another pod inserted first — adopt its value so both derive the same keys.
    winner = await instance_settings_repository.find_by_key(SECRETS_DOC_KEY)
    if winner is None:
        raise AppError(
            message="Lost the instance-secret insert race but found no persisted secret",
            why=(
                f"the '{SECRETS_DOC_KEY}' document vanished between the failed insert "
                "and the re-read"
            ),
            fix="retry; if it persists, check for something deleting instance_settings rows",
        )
    winner_secret = _secret_value(winner.value)
    if winner_secret is None:
        raise AppError(
            message=(
                f"The raced '{SECRETS_DOC_KEY}' instance-settings document carries no "
                f"'{_INSTANCE_SECRET_FIELD}' value"
            ),
            why="a concurrent writer stored a malformed secrets document",
            fix=f"inspect the '{SECRETS_DOC_KEY}' document and restore a valid instance secret",
        )
    return winner_secret


def _secret_value(value: dict[str, object]) -> str | None:
    """Return the instance secret out of a settings-doc value dict, or None when absent/blank."""
    candidate = value.get(_INSTANCE_SECRET_FIELD)
    if isinstance(candidate, str) and candidate:
        return candidate
    return None
