"""Tests for the Composio CustomTool monkey patch.

Composio 1.0.0 dispatches custom tools via ``CustomTool.invoke_trusted`` and
deliberately keeps ``user_id`` out of ``auth_credentials``. The patch re-injects
``user_id`` at ``CustomTool.__get_auth_credentials`` (the private method both
dispatch paths funnel through), so GAIA's custom tools can keep reading it.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from composio.core.models.custom_tools import CustomTool

# Importing the patch module triggers the monkey-patch at import time.
import app.patches.composio_custom_tool_patch as patch_module  # noqa: F401

_PRIVATE_AUTH_METHOD = "_CustomTool__get_auth_credentials"


def _call_get_auth(auth_credentials: dict, user_id: str = "user_42") -> dict:
    """Invoke the patched __get_auth_credentials with a stubbed original."""
    tool = MagicMock(spec=CustomTool)
    # The patch wraps the original (captured at import). Re-point the captured
    # original at our stub so we exercise the wrapper in isolation, then restore
    # it so we don't pollute other tests.
    saved = patch_module._original_get_auth_credentials
    patch_module._original_get_auth_credentials = MagicMock(return_value=auth_credentials)
    try:
        bound = getattr(CustomTool, _PRIVATE_AUTH_METHOD)
        return bound(tool, user_id)
    finally:
        patch_module._original_get_auth_credentials = saved


class TestPatchTarget:
    def test_private_method_exists_on_custom_tool(self) -> None:
        # Tripwire: if Composio renames/removes this, the patch import would
        # have already raised. This asserts the coupling point is still present.
        assert hasattr(CustomTool, _PRIVATE_AUTH_METHOD)

    def test_dispatch_funnels_through_patched_method(self) -> None:
        # invoke_trusted is the real dispatch path; __call__ defers to it.
        assert _PRIVATE_AUTH_METHOD.rsplit("__", maxsplit=1)[-1] in inspect.getsource(
            CustomTool.invoke_trusted
        )


class TestPatchedGetAuthCredentials:
    def test_injects_user_id(self) -> None:
        creds = _call_get_auth({}, user_id="user_42")
        assert creds["user_id"] == "user_42"

    def test_preserves_other_credential_fields(self) -> None:
        creds = _call_get_auth({"refresh_token": "rt", "scope": "x"}, user_id="user_42")
        assert creds["refresh_token"] == "rt"
        assert creds["scope"] == "x"
        assert creds["user_id"] == "user_42"

    def test_works_without_access_token(self) -> None:
        creds = _call_get_auth({}, user_id="user_42")
        assert "access_token" not in creds
        assert creds == {"user_id": "user_42"}

    def test_does_not_mutate_original_credentials(self) -> None:
        original_creds: dict = {"refresh_token": "rt"}
        _call_get_auth(original_creds, user_id="user_42")
        assert "user_id" not in original_creds
