"""Referral codes: minted once per Pro user from their first name, never edited."""

from datetime import UTC, datetime
import re
import secrets
import unicodedata

from pymongo.errors import DuplicateKeyError

from app.config.settings import settings
from app.constants.referrals import (
    CODE_MINT_ATTEMPTS,
    CODE_NAME_FALLBACK,
    CODE_NAME_MAX_LENGTH,
    CODE_SEPARATOR,
    CODE_SUFFIX_ALPHABET,
    CODE_SUFFIX_LENGTH,
    INVITE_PATH,
)
from app.db.repositories.referral_codes import referral_code_repository
from app.db.repositories.users import user_repository
from app.models.referral_models import ReferralCodeDocument
from app.models.user_models import UserDocument
from app.utils.errors import AppError
from shared.py.wide_events import log

_NOT_A_LETTER = re.compile(r"[^a-z]")


async def load_user(user_id: str) -> UserDocument:
    """Return the authenticated user's document; its absence is a broken session, not a referral state."""
    user = await user_repository.get(user_id)
    if user is None:
        raise AppError(message="User not found", status_code=404, meta={"user_id": user_id})
    return user


def first_name_of(user: UserDocument) -> str | None:
    """Return the name a friend knows this user by: their first name, else the first word of their name."""
    if user.first_name:
        return user.first_name
    return user.name.split()[0] if user.name and user.name.split() else None


def _code_name(first_name: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", first_name or "")
    ascii_name = "".join(char for char in decomposed if char.isascii())
    letters = _NOT_A_LETTER.sub("", ascii_name.lower())[:CODE_NAME_MAX_LENGTH]
    return letters or CODE_NAME_FALLBACK


def mint_code(first_name: str | None) -> str:
    """Return a fresh code: the first name in ascii letters, then a short random suffix (aryan-k7f2)."""
    suffix = "".join(secrets.choice(CODE_SUFFIX_ALPHABET) for _ in range(CODE_SUFFIX_LENGTH))
    return f"{_code_name(first_name)}{CODE_SEPARATOR}{suffix}"


def share_link(code: str) -> str:
    """Return the invite link a code is shared as."""
    return f"{settings.FRONTEND_URL}{INVITE_PATH}{code}"


async def ensure_code(user: UserDocument) -> str:
    """Return the user's code, minting it on first ask; a racing mint for the same user returns the winner's."""
    existing = await referral_code_repository.get_for_user(user.id)
    if existing is not None:
        return existing.code
    for _ in range(CODE_MINT_ATTEMPTS):
        candidate = mint_code(first_name_of(user))
        try:
            created = await referral_code_repository.create(
                ReferralCodeDocument(user_id=user.id, code=candidate, created_at=datetime.now(UTC))
            )
        except DuplicateKeyError:
            # Either this user's code landed from another request, or the suffix clashed.
            raced = await referral_code_repository.get_for_user(user.id)
            if raced is not None:
                return raced.code
            continue
        log.set_ns("referral", code_minted=True)
        return created.code
    raise AppError(
        message="Could not create a referral code",
        why=f"{CODE_MINT_ATTEMPTS} random suffixes in a row were already taken",
        meta={"user_id": user.id},
    )
