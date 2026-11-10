"""bcrypt hashing for local (self-host) account passwords; bcrypt >= 5 refuses input past 72 bytes."""

import bcrypt

from app.constants.auth import BCRYPT_ROUNDS
from shared.py.wide_events import log


def hash_password(password: str) -> str:
    """Hash a password at the instance's bcrypt cost; raises ValueError past the 72-byte cap."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Whether a password matches its hash; an over-cap password is a mismatch, never an error."""
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError as exc:
        log.warning("over-cap password folded into uniform 401", error_type=type(exc).__name__)
        return False
