"""``AuthenticatedUser`` must not drift from ``UserDocument``.

``build_user_context()`` spreads an entire ``UserDocument`` into
``request.state.user`` and layers auth-context fields on top, so
``AuthenticatedUser`` has to stay a superset of the document's fields. It can't
simply BE ``UserDocument``: the auth context adds keys the document doesn't have
(``auth_provider``, the per-path flags) and ~205 call sites read the value with
``user["user_id"]``, which a Pydantic model would break at runtime.

That leaves the field list duplicated, so this test is the guard: add a field to
``UserDocument`` without adding it here and CI fails instead of the TypedDict
silently going stale.
"""

from typing import get_type_hints

from app.models.user_models import AuthenticatedUser, UserDocument

# Set by build_user_context()/user_to_legacy_dict(), not present on the document.
AUTH_CONTEXT_ONLY_KEYS = {
    "user_id",
    "auth_provider",
    "impersonated",
    "bot_authenticated",
    "dev_bypass",
    "is_agent_token",
    "_id",
}

# `id` exists on MongoDocument but build_user_context pops `_id` and substitutes
# `user_id`, so the auth context never carries the document's own id field.
DOCUMENT_KEYS_NOT_PROPAGATED = {"id"}


def test_authenticated_user_covers_every_user_document_field() -> None:
    doc_fields = set(UserDocument.model_fields) - DOCUMENT_KEYS_NOT_PROPAGATED
    auth_keys = set(get_type_hints(AuthenticatedUser))

    missing = doc_fields - auth_keys
    assert not missing, (
        f"UserDocument gained {sorted(missing)} but AuthenticatedUser did not. "
        "build_user_context spreads the whole document into request.state.user, "
        "so any new document field must be declared on AuthenticatedUser too."
    )


def test_authenticated_user_declares_no_unknown_fields() -> None:
    """Every key is either a document field or a known auth-context field."""
    doc_fields = set(UserDocument.model_fields)
    auth_keys = set(get_type_hints(AuthenticatedUser))

    unexplained = auth_keys - doc_fields - AUTH_CONTEXT_ONLY_KEYS
    assert not unexplained, (
        f"AuthenticatedUser declares {sorted(unexplained)}, which is neither a "
        "UserDocument field nor a documented auth-context key. Either it was "
        "removed from UserDocument (delete it here too) or it needs adding to "
        "AUTH_CONTEXT_ONLY_KEYS with a reason."
    )


def test_every_auth_context_key_is_actually_set_somewhere() -> None:
    """The auth-context keys must be real — not aspirational."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[3] / "app"
    haystack = "\n".join(p.read_text() for p in src.rglob("*.py") if "test" not in p.name)
    for key in sorted(AUTH_CONTEXT_ONLY_KEYS - {"_id"}):
        assert f'"{key}"' in haystack or f"{key}=" in haystack, (
            f"AuthenticatedUser declares auth-context key {key!r} but nothing in "
            "app/ ever sets it — either it is dead or it was renamed."
        )
