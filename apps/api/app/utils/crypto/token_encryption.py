"""At-rest encryption for OAuth/integration tokens (C2).

Uses Fernet (AES-128-CBC + HMAC-SHA256) under a key derived from the app's
``TOKEN_ENCRYPTION_KEY`` setting. Values are tagged with a short prefix so
the decrypt path can distinguish ciphertext from legacy plaintext rows
and support a live migration — existing rows stay readable while new
writes are encrypted. A periodic re-encryption job should walk the
plaintext rows and update them.
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, Text
from sqlalchemy.types import TypeDecorator

_CIPHERTEXT_PREFIX = "enc1:"


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from an arbitrary secret string."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Optional[Fernet]:
    """Return a Fernet instance, or ``None`` if no key is configured.

    In production the startup self-check in ``lifespan.py`` refuses to
    boot without a key. In development, missing keys degrade to no-op
    (plaintext) so local dev doesn't require generating a key.
    """
    # Pulled from env directly to avoid a circular import on settings at
    # module load time — this module is imported by SQLAlchemy models.
    key = os.getenv("TOKEN_ENCRYPTION_KEY")
    if not key:
        return None
    return Fernet(_derive_fernet_key(key))


def encrypt_at_rest(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a value for storage. Pass-through when no key is configured."""
    if plaintext is None:
        return None
    fernet = _get_fernet()
    if not fernet:
        return plaintext
    token = fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
    return f"{_CIPHERTEXT_PREFIX}{token}"


def decrypt_at_rest(stored: Optional[str]) -> Optional[str]:
    """Decrypt a stored value. Legacy unencrypted rows pass through.

    Rows written before this change have no prefix and are returned as-is
    (plaintext). Rows written after have the ``enc1:`` prefix and are
    decrypted via the configured key. A value with the prefix that fails
    to decrypt raises — we never want to silently return a bad token to
    the OAuth refresh path.
    """
    if stored is None:
        return None
    if not stored.startswith(_CIPHERTEXT_PREFIX):
        return stored
    ciphertext = stored[len(_CIPHERTEXT_PREFIX) :].encode("ascii")
    fernet = _get_fernet()
    if not fernet:
        # We have ciphertext but no key — this is a misconfiguration.
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY missing but encrypted rows exist in DB"
        )
    try:
        return fernet.decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("encrypted token failed MAC verification") from exc


class EncryptedText(TypeDecorator):
    """SQLAlchemy column type that transparently encrypts/decrypts TEXT.

    Apply to any column that holds an OAuth access/refresh token, full
    provider token JSON, or client registration material. Existing
    plaintext rows remain readable until rewritten.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):  # type: ignore[override]
        return encrypt_at_rest(value)

    def process_result_value(self, value, dialect):  # type: ignore[override]
        return decrypt_at_rest(value)


class EncryptedString(TypeDecorator):
    """EncryptedText for String columns (shorter VARCHAR-backed fields)."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):  # type: ignore[override]
        return encrypt_at_rest(value)

    def process_result_value(self, value, dialect):  # type: ignore[override]
        return decrypt_at_rest(value)
