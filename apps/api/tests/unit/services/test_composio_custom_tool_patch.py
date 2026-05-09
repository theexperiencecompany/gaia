"""Tests for the Composio CustomTool monkey patch.

The patch enriches `auth_credentials` with `user_id` and routes the
`execute_request` callable to `composio.tools.proxy`. Since Composio
no longer returns `access_token` in its connected-account credentials,
the patch must keep working when that field is absent.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from composio.core.models.custom_tools import CustomTool
from pydantic import BaseModel

from app.utils.errors import AppError

# Importing the patch module triggers the monkey-patch at import time.
import app.patches.composio_custom_tool_patch  # noqa: F401


class _StubRequestModel(BaseModel):
    foo: str


def _make_tool(
    *,
    auth_credentials: dict,
    toolkit: str | None = "GMAIL",
) -> MagicMock:
    tool = MagicMock()
    tool.request_model = _StubRequestModel
    tool.toolkit = toolkit
    tool.client.tools.proxy = MagicMock(name="proxy")
    tool._CustomTool__get_auth_credentials = MagicMock(return_value=auth_credentials)
    tool.f = MagicMock(return_value={"ok": True})
    return tool


def _invoke(tool: MagicMock, **kwargs: Any) -> Any:
    return CustomTool.__call__(tool, **kwargs)


class TestPatchedCall:
    def test_injects_user_id_into_auth_credentials(self) -> None:
        tool = _make_tool(auth_credentials={})
        result = _invoke(tool, user_id="user_42", foo="bar")

        assert result == {"ok": True}
        call_kwargs = tool.f.call_args.kwargs
        assert call_kwargs["auth_credentials"]["user_id"] == "user_42"

    def test_works_without_access_token_in_credentials(self) -> None:
        tool = _make_tool(auth_credentials={})
        _invoke(tool, user_id="user_42", foo="bar")

        creds = tool.f.call_args.kwargs["auth_credentials"]
        assert "access_token" not in creds
        assert creds == {"user_id": "user_42"}

    def test_preserves_other_credential_fields(self) -> None:
        tool = _make_tool(auth_credentials={"refresh_token": "rt", "scope": "x"})
        _invoke(tool, user_id="user_42", foo="bar")

        creds = tool.f.call_args.kwargs["auth_credentials"]
        assert creds["refresh_token"] == "rt"
        assert creds["scope"] == "x"
        assert creds["user_id"] == "user_42"

    def test_passes_proxy_as_execute_request(self) -> None:
        tool = _make_tool(auth_credentials={})
        _invoke(tool, user_id="user_42", foo="bar")

        assert tool.f.call_args.kwargs["execute_request"] is tool.client.tools.proxy

    def test_validates_request_model(self) -> None:
        tool = _make_tool(auth_credentials={})
        _invoke(tool, user_id="user_42", foo="bar")

        request = tool.f.call_args.kwargs["request"]
        assert isinstance(request, _StubRequestModel)
        assert request.foo == "bar"

    def test_skips_credentials_when_no_toolkit(self) -> None:
        tool = _make_tool(auth_credentials={}, toolkit=None)
        _invoke(tool, user_id="user_42", foo="bar")

        # Tool without toolkit is called with only the request — no credentials,
        # no execute_request — proving the patch's bypass branch still works.
        call_kwargs = tool.f.call_args.kwargs
        assert "auth_credentials" not in call_kwargs
        assert "execute_request" not in call_kwargs
        tool._CustomTool__get_auth_credentials.assert_not_called()

    def test_missing_user_id_raises_app_error(self) -> None:
        tool = _make_tool(auth_credentials={})
        with pytest.raises(AppError) as exc:
            _invoke(tool, foo="bar")
        assert "Missing user_id" in exc.value.message


@pytest.mark.parametrize("user_id", ["", None])
def test_empty_or_none_user_id_raises_app_error(user_id: str | None) -> None:
    tool = _make_tool(auth_credentials={})
    with pytest.raises(AppError):
        _invoke(tool, user_id=user_id, foo="bar")
