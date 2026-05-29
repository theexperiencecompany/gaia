"""Tests for the Composio CustomTool monkey patch.

BEHAVIOR SPEC
=============

UNIT: app/patches/composio_custom_tool_patch.py :: _patched_call
  (installed at import time as ``CustomTool.__call__``)
EXPECTED: Given **kwargs that include ``user_id``, validate the remaining kwargs
          against the tool's ``request_model``, then invoke the wrapped function
          ``self.f``. For a toolkit-bound tool, fetch the connected-account auth
          credentials, copy them, inject ``user_id``, and route the proxy callable
          as ``execute_request``. For a toolkit-less tool, call ``self.f`` with the
          request only. A missing/empty/None ``user_id`` raises ``AppError`` and
          never touches auth credentials.
MECHANISM: user_id = kwargs.get("user_id"); if not user_id -> raise AppError(...);
           del kwargs["user_id"]; normalized = _to_dict_recursive(kwargs);
           request = request_model.model_validate(normalized);
           if toolkit is None: return f(request=request);
           creds = dict(__get_auth_credentials(user_id)); creds["user_id"] = user_id;
           return f(request=request, execute_request=client.tools.proxy,
                    auth_credentials=creds).
MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - user_id is injected into auth_credentials under the exact key "user_id"   [multi-tenant contract]
  - the injected value is the caller's user_id, not a constant/default account
  - __get_auth_credentials is called with the caller's user_id (correct account lookup)
  - the original credential dict is COPIED (caller's dict not mutated by injection)
  - pre-existing credential fields survive the injection
  - execute_request is exactly client.tools.proxy (provider requests route via proxy)
  - the validated request is a real request_model instance carrying the kwargs
  - kwargs are validated AFTER user_id is removed (user_id never reaches request_model)
  - toolkit-less tools are called with request only — no auth fetch, no execute_request
  - falsy user_id ("" / None) and absent user_id raise AppError with the right message
  - on the error path, no auth credentials are fetched
  - the wrapped function's return value is propagated unchanged
EQUIVALENT MUTANTS (allowed survivors, justified):
  - L88 module-level ``CustomTool.__call__ = _patched_call`` is outside any def and
    is exercised implicitly by every test (every call goes through the patch); it is
    not in the mutation scope of the targeted functions.

UNIT: app/patches/composio_custom_tool_patch.py :: _to_dict_recursive
EXPECTED: Recursively normalize a value to plain dict/list/scalar. A BaseModel becomes
          its ``model_dump()``; a dict maps each value through the function; a list maps
          each item; any other value is returned unchanged.
MECHANISM: isinstance(obj, BaseModel) -> obj.model_dump();
           isinstance(obj, dict) -> {k: _rec(v)}; isinstance(obj, list) -> [_rec(i)];
           else -> obj.
MUST-CATCH:
  - a top-level BaseModel is converted via model_dump (class-mismatch normalization)
  - a BaseModel nested inside a dict value is converted (recursion into dict values)
  - a BaseModel nested inside a list is converted (recursion into list items)
  - scalars (int / str / None) pass through unchanged
EQUIVALENT MUTANTS: none.
"""

from typing import Any
from unittest.mock import MagicMock

from composio.core.models.custom_tools import CustomTool
from pydantic import BaseModel
import pytest

# Importing the patch module triggers the monkey-patch at import time.
import app.patches.composio_custom_tool_patch  # noqa: F401
from app.patches.composio_custom_tool_patch import _to_dict_recursive
from app.utils.errors import AppError


class _NestedField(BaseModel):
    value: str


class _RequestModel(BaseModel):
    foo: str
    nested: _NestedField | None = None


def _make_tool(
    *,
    auth_credentials: dict | None = None,
    toolkit: str | None = "GMAIL",
    return_value: Any = None,
) -> CustomTool:
    """Build a REAL ``CustomTool`` whose only mocked surface is the I/O boundary.

    ``client`` (the Composio HTTP client) is the external dependency: its
    ``tools.proxy`` is the request executor and ``connected_accounts.list`` is the
    auth lookup. We construct a genuine ``CustomTool`` around a real wrapped
    function so the real ``_patched_call`` runs end-to-end, and only stub the
    name-mangled ``__get_auth_credentials`` (which performs the HTTP account
    lookup) at that boundary.
    """
    sentinel = {"ok": True} if return_value is None else return_value

    def tool_fn(
        request: _RequestModel,
        execute_request: Any = None,
        auth_credentials: Any = None,
    ) -> Any:
        """A real custom tool function for the patch to drive."""
        tool_fn.received = {  # type: ignore[attr-defined]
            "request": request,
            "execute_request": execute_request,
            "auth_credentials": auth_credentials,
        }
        return sentinel

    tool_fn.received = None  # type: ignore[attr-defined]

    client = MagicMock(name="composio_client")
    client.tools.proxy = MagicMock(name="proxy")

    tool = CustomTool(f=tool_fn, client=client, toolkit=toolkit)
    if toolkit is not None:
        tool._CustomTool__get_auth_credentials = MagicMock(  # type: ignore[attr-defined]
            name="get_auth_credentials",
            return_value=auth_credentials if auth_credentials is not None else {},
        )
    return tool


def _received(tool: CustomTool) -> dict[str, Any]:
    return tool.f.received  # type: ignore[attr-defined]


class TestPatchedCallToolkitBound:
    def test_injects_caller_user_id_into_auth_credentials(self) -> None:
        tool = _make_tool(auth_credentials={})
        result = tool(user_id="user_42", foo="bar")

        assert result == {"ok": True}
        assert _received(tool)["auth_credentials"]["user_id"] == "user_42"

    def test_fetches_credentials_for_the_caller_user_id(self) -> None:
        tool = _make_tool(auth_credentials={})
        tool(user_id="user_42", foo="bar")

        tool._CustomTool__get_auth_credentials.assert_called_once_with("user_42")  # type: ignore[attr-defined]

    def test_does_not_mutate_the_source_credentials_dict(self) -> None:
        source = {"refresh_token": "rt"}
        tool = _make_tool(auth_credentials=source)
        tool(user_id="user_42", foo="bar")

        # The patch copies before injecting, so the dict returned by the auth
        # lookup must stay free of the injected user_id.
        assert source == {"refresh_token": "rt"}
        assert _received(tool)["auth_credentials"] == {
            "refresh_token": "rt",
            "user_id": "user_42",
        }

    def test_preserves_other_credential_fields(self) -> None:
        tool = _make_tool(auth_credentials={"refresh_token": "rt", "scope": "x"})
        tool(user_id="user_42", foo="bar")

        creds = _received(tool)["auth_credentials"]
        assert creds == {"refresh_token": "rt", "scope": "x", "user_id": "user_42"}

    def test_routes_proxy_as_execute_request(self) -> None:
        tool = _make_tool(auth_credentials={})
        tool(user_id="user_42", foo="bar")

        assert _received(tool)["execute_request"] is tool.client.tools.proxy

    def test_validates_request_model_without_user_id(self) -> None:
        tool = _make_tool(auth_credentials={})
        tool(user_id="user_42", foo="bar")

        request = _received(tool)["request"]
        assert isinstance(request, _RequestModel)
        assert request.foo == "bar"
        # user_id was removed before validation, so it is not a request field.
        assert not hasattr(request, "user_id")

    def test_normalizes_pydantic_kwargs_before_validation(self) -> None:
        # A Pydantic instance from a *different* class (mirrors Composio's
        # dynamically-generated models) is passed as a kwarg value. The patch
        # normalizes it to a plain dict via _to_dict_recursive before
        # model_validate runs, so the foreign class is accepted and round-trips.
        class _ForeignNested(BaseModel):
            value: str

        tool = _make_tool(auth_credentials={})
        tool(user_id="user_42", foo="bar", nested=_ForeignNested(value="deep"))

        request = _received(tool)["request"]
        assert isinstance(request.nested, _NestedField)
        assert request.nested.value == "deep"

    def test_propagates_wrapped_return_value(self) -> None:
        tool = _make_tool(auth_credentials={}, return_value={"status": "sent"})
        result = tool(user_id="user_42", foo="bar")

        assert result == {"status": "sent"}


class TestPatchedCallToolkitless:
    def test_calls_function_with_request_only(self) -> None:
        tool = _make_tool(toolkit=None)
        result = tool(user_id="user_42", foo="bar")

        assert result == {"ok": True}
        received = _received(tool)
        assert isinstance(received["request"], _RequestModel)
        assert received["request"].foo == "bar"
        # No toolkit -> no auth fetch, no execute_request routed.
        assert received["execute_request"] is None
        assert received["auth_credentials"] is None

    def test_does_not_fetch_credentials_without_toolkit(self) -> None:
        tool = _make_tool(toolkit=None)
        # The auth-fetch boundary must never be reached on the bypass branch.
        tool._CustomTool__get_auth_credentials = MagicMock(  # type: ignore[attr-defined]
            name="get_auth_credentials"
        )
        tool(user_id="user_42", foo="bar")

        tool._CustomTool__get_auth_credentials.assert_not_called()  # type: ignore[attr-defined]


class TestPatchedCallMissingUserId:
    def test_absent_user_id_raises_app_error(self) -> None:
        tool = _make_tool(auth_credentials={})
        with pytest.raises(AppError) as exc:
            tool(foo="bar")

        err = exc.value
        assert err.message == "Missing user_id when invoking Composio custom tool"
        assert err.status_code == 500
        # The structured error carries debugging context for wide events.
        assert err.why == "The CustomTool was invoked without a user_id kwarg"
        assert err.fix == "Caller must pass user_id; do not rely on a default account"
        # meta identifies the failing tool by name (getattr(self, "name", None)).
        assert err.meta == {"tool": tool.name}
        assert tool.name == "gmail_tool_fn"

    def test_error_path_does_not_fetch_credentials(self) -> None:
        tool = _make_tool(auth_credentials={})
        with pytest.raises(AppError):
            tool(foo="bar")

        tool._CustomTool__get_auth_credentials.assert_not_called()  # type: ignore[attr-defined]

    def test_error_path_does_not_invoke_wrapped_function(self) -> None:
        tool = _make_tool(auth_credentials={})
        with pytest.raises(AppError):
            tool(foo="bar")

        assert _received(tool) is None

    @pytest.mark.parametrize("user_id", ["", None])
    def test_falsy_user_id_raises_app_error(self, user_id: str | None) -> None:
        tool = _make_tool(auth_credentials={})
        with pytest.raises(AppError) as exc:
            tool(user_id=user_id, foo="bar")

        assert exc.value.message == "Missing user_id when invoking Composio custom tool"


class TestToDictRecursive:
    def test_top_level_basemodel_becomes_model_dump(self) -> None:
        class _M(BaseModel):
            a: int
            b: str

        assert _to_dict_recursive(_M(a=1, b="x")) == {"a": 1, "b": "x"}

    def test_basemodel_nested_in_dict_value_is_converted(self) -> None:
        class _M(BaseModel):
            a: int

        result = _to_dict_recursive({"outer": _M(a=7), "plain": "keep"})
        assert result == {"outer": {"a": 7}, "plain": "keep"}

    def test_basemodel_nested_in_list_is_converted(self) -> None:
        class _M(BaseModel):
            a: int

        result = _to_dict_recursive([_M(a=1), "plain", _M(a=2)])
        assert result == [{"a": 1}, "plain", {"a": 2}]

    def test_scalars_pass_through_unchanged(self) -> None:
        assert _to_dict_recursive(7) == 7
        assert _to_dict_recursive("text") == "text"
        assert _to_dict_recursive(None) is None
