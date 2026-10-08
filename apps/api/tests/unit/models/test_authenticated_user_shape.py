"""AuthenticatedUser must not drift from UserDocument.

build_user_context() copies every UserDocument field into the auth context
and layers the auth-context fields on top, and GET /me serves that object, so
AuthenticatedUser has to stay a superset of the document's fields. It can't
simply BE UserDocument: the auth context adds fields the document doesn't have
(auth_provider, the per-path flags) and is frozen and closed.

That leaves the field list duplicated, so this test is the guard: add a field to
UserDocument without adding it here (and to build_user_context) and CI fails
instead of the model silently going stale.
"""

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from app.config.feature_flags import FeatureFlag
from app.models.first_steps_models import FirstStepsState
from app.models.user_models import AuthenticatedUser, OnboardingSubdocument, UserDocument
from app.utils.auth_utils import build_user_context

# Set by build_user_context(), not present on the document.
AUTH_CONTEXT_ONLY_KEYS = {
    "user_id",
    "auth_provider",
    "impersonated",
    "bot_authenticated",
    "dev_bypass",
}

# `id` exists on MongoDocument; build_user_context carries it as `user_id`.
DOCUMENT_KEYS_NOT_PROPAGATED = {"id"}


_STAMP = datetime(2024, 5, 1, tzinfo=UTC)

# One distinct non-default sample per declared field type, matched by the
# first type name found in the field's annotation (order matters: the nested
# models are named before the primitives their annotations also mention).
_SAMPLE_BY_TYPE: tuple[tuple[str, object], ...] = (
    ("OnboardingSubdocument", OnboardingSubdocument(focus="ops")),
    ("FirstStepsState", FirstStepsState(collapsed=True, collapsed_at=_STAMP)),
    ("FeatureFlag", {FeatureFlag.BROWSER_OBSCURA: True}),
    ("datetime", _STAMP),
    ("bool", True),
    ("int", 3),
    ("list", ["item"]),
    ("dict", {"k": "v"}),
)


def _sample_values() -> dict[str, object]:
    """Return a non-default value for every declared UserDocument field but id."""
    return {
        name: next(
            (value for type_name, value in _SAMPLE_BY_TYPE if type_name in str(field.annotation)),
            f"{name}-value",
        )
        for name, field in UserDocument.model_fields.items()
        if name != "id"
    }


def test_authenticated_user_covers_every_user_document_field() -> None:
    doc_fields = set(UserDocument.model_fields) - DOCUMENT_KEYS_NOT_PROPAGATED
    auth_keys = set(AuthenticatedUser.model_fields)

    missing = doc_fields - auth_keys
    assert not missing, (
        f"UserDocument gained {sorted(missing)} but AuthenticatedUser did not. "
        "build_user_context carries the whole document into request.state.user, "
        "so any new document field must be declared on AuthenticatedUser too."
    )


def test_authenticated_user_declares_no_unknown_fields() -> None:
    """Every field is either a document field or a known auth-context field."""
    doc_fields = set(UserDocument.model_fields)
    auth_keys = set(AuthenticatedUser.model_fields)

    unexplained = auth_keys - doc_fields - AUTH_CONTEXT_ONLY_KEYS
    assert not unexplained, (
        f"AuthenticatedUser declares {sorted(unexplained)}, which is neither a "
        "UserDocument field nor a documented auth-context key. Either it was "
        "removed from UserDocument (delete it here too) or it needs adding to "
        "AUTH_CONTEXT_ONLY_KEYS with a reason."
    )


def test_build_user_context_copies_every_document_field() -> None:
    """A field build_user_context forgets to copy is declared yet never set, the drift this guards."""
    values = _sample_values()
    doc = UserDocument(id="507f1f77bcf86cd799439011", **values)

    user = build_user_context(doc, auth_provider="workos")

    assert user.user_id == "507f1f77bcf86cd799439011"
    for name, value in values.items():
        assert getattr(user, name) == value, f"build_user_context dropped {name}"


def test_authenticated_user_is_frozen_and_closed() -> None:
    user = AuthenticatedUser(user_id="u1")
    with pytest.raises(ValidationError):
        user.user_id = "u2"
    with pytest.raises(ValidationError):
        AuthenticatedUser(user_id="u1", _id="legacy")
    assert user.with_timezone("Asia/Kolkata").timezone == "Asia/Kolkata"
    assert user.timezone is None


def test_every_auth_context_key_is_actually_set_somewhere() -> None:
    """The auth-context keys must be real — not aspirational."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[3] / "app"
    haystack = "\n".join(p.read_text() for p in src.rglob("*.py") if "test" not in p.name)
    for key in sorted(AUTH_CONTEXT_ONLY_KEYS):
        assert f'"{key}"' in haystack or f"{key}=" in haystack, (
            f"AuthenticatedUser declares auth-context key {key!r} but nothing in "
            "app/ ever sets it — either it is dead or it was renamed."
        )
