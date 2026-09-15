"""Unit tests for ``app.core.request_context.resolve_caller``.

The decorator-facing caller-resolution function: request-scoped context first,
then an explicit ``user`` kwarg, then the first positional dict carrying
``user_id``. Direct, exact-value tests — this used to be exercised only
indirectly through the decorators that call it.
"""

from app.core.request_context import (
    resolve_caller,
    set_authenticated_user,
)


class TestResolveCaller:
    def test_prefers_the_request_scoped_context_over_everything_else(self):
        context_user = {"user_id": "context-user", "email": "a@b.com"}
        set_authenticated_user(context_user)
        try:
            result = resolve_caller((), {"user": {"user_id": "kwarg-user"}})
        finally:
            set_authenticated_user(None)
        assert result == context_user

    def test_falls_back_to_the_user_kwarg_when_no_context_user(self):
        kwarg_user = {"user_id": "kwarg-user"}
        result = resolve_caller((), {"user": kwarg_user})
        assert result == kwarg_user

    def test_falls_back_to_the_first_positional_dict_with_user_id(self):
        candidate = {"user_id": "positional-user"}
        result = resolve_caller(("not-a-dict", 42, candidate), {})
        assert result == candidate

    def test_skips_positional_dicts_without_user_id(self):
        no_id = {"email": "no-id@example.com"}
        with_id = {"user_id": "has-id"}
        result = resolve_caller((no_id, with_id), {})
        assert result == with_id

    def test_returns_none_when_nothing_resolves(self):
        assert resolve_caller((), {}) is None
        assert resolve_caller(("just a string", 1, None), {}) is None

    def test_a_falsy_user_kwarg_does_not_short_circuit_positional_fallback(self):
        """An explicit ``user=None``/``user={}`` kwarg must not stop the search —
        it is falsy, so the positional dict is still tried."""
        candidate = {"user_id": "positional-user"}
        assert resolve_caller((candidate,), {"user": None}) == candidate
        assert resolve_caller((candidate,), {"user": {}}) == candidate

    def test_a_falsy_context_user_does_not_short_circuit_the_kwarg_fallback(self):
        kwarg_user = {"user_id": "kwarg-user"}
        set_authenticated_user(None)
        result = resolve_caller((), {"user": kwarg_user})
        assert result == kwarg_user
