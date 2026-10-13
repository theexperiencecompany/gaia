"""Unit tests for app.core.request_context.resolve_caller.

The decorator-facing caller-resolution function: request-scoped context first,
then an explicit user kwarg, then the first positional AuthenticatedUser.
Direct, exact-value tests — this used to be exercised only indirectly through
the decorators that call it.
"""

from app.core.request_context import (
    resolve_caller,
    set_authenticated_user,
)
from app.models.user_models import AuthenticatedUser


def _user(user_id: str) -> AuthenticatedUser:
    return AuthenticatedUser(user_id=user_id)


class TestResolveCaller:
    def test_prefers_the_request_scoped_context_over_everything_else(self):
        context_user = AuthenticatedUser(user_id="context-user", email="a@b.com")
        set_authenticated_user(context_user)
        try:
            result = resolve_caller((), {"user": _user("kwarg-user")})
        finally:
            set_authenticated_user(None)
        assert result is context_user

    def test_falls_back_to_the_user_kwarg_when_no_context_user(self):
        kwarg_user = _user("kwarg-user")
        result = resolve_caller((), {"user": kwarg_user})
        assert result is kwarg_user

    def test_a_user_kwarg_resolves_whatever_the_parameter_is_named(self):
        kwarg_user = _user("current-user")
        result = resolve_caller(("not-a-user",), {"request": object(), "current_user": kwarg_user})
        assert result is kwarg_user

    def test_falls_back_to_the_first_positional_authenticated_user(self):
        candidate = _user("positional-user")
        result = resolve_caller(("not-a-user", 42, candidate), {})
        assert result is candidate

    def test_skips_positional_dicts_that_merely_look_like_a_user(self):
        """A plain dict carrying user_id is not a caller — only the model is."""
        lookalike = {"user_id": "dict-user"}
        with_id = _user("has-id")
        result = resolve_caller((lookalike, with_id), {})
        assert result is with_id

    def test_returns_none_when_nothing_resolves(self):
        assert resolve_caller((), {}) is None
        assert resolve_caller(("just a string", 1, None), {}) is None
        assert resolve_caller((), {"user": {"user_id": "dict-user"}}) is None

    def test_a_non_user_kwarg_does_not_short_circuit_positional_fallback(self):
        """An explicit user=None kwarg must not stop the search; the positional candidate is still tried."""
        candidate = _user("positional-user")
        assert resolve_caller((candidate,), {"user": None}) is candidate

    def test_a_falsy_context_user_does_not_short_circuit_the_kwarg_fallback(self):
        kwarg_user = _user("kwarg-user")
        set_authenticated_user(None)
        result = resolve_caller((), {"user": kwarg_user})
        assert result is kwarg_user
