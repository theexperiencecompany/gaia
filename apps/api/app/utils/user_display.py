"""The name GAIA shows and greets a user by; None whenever the user never gave one."""

from app.models.user_models import UserDocument


def display_name(user: UserDocument) -> str | None:
    """Return the user's name with its whitespace collapsed; None when blank."""
    return " ".join((user.name or "").split()) or None


def display_first_name(user: UserDocument) -> str | None:
    """Return the first word of the user's name, the one a friend would greet them by."""
    full = display_name(user)
    return full.partition(" ")[0] if full else None
