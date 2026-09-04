"""Outlook attachment hook: workspace-local paths become grant URLs.

OUTLOOK_SEND_EMAIL / OUTLOOK_CREATE_DRAFT take `attachment` as a path string
Composio fetches itself. URL values and missing keys pass through untouched;
every workspace-local path triggers a mint — whether it arrives bare or inside
a list, since both reach Composio the same way (fail-closed abort when the user
is missing or the mint fails). The `user_id` strip keeps model-supplied
identity out of hook params (mirrors gmail).
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.utils.composio_hooks.outlook_hooks import (
    outlook_attachment_before_hook,
    outlook_hide_user_id_schema_modifier,
)
from app.utils.composio_hooks.registry import HookAbortError

HOOKS = "app.utils.composio_hooks.outlook_hooks"


class TestOutlookHideUserIdSchemaModifier:
    def test_strips_user_id_from_props_and_required(self):
        schema = SimpleNamespace(
            input_parameters={
                "properties": {
                    "user_id": {"type": "string"},
                    "attachment": {"type": "string"},
                },
                "required": ["user_id"],
            }
        )
        out = outlook_hide_user_id_schema_modifier("OUTLOOK_SEND_EMAIL", "outlook", schema)
        assert "user_id" not in out.input_parameters["properties"]
        assert out.input_parameters["required"] == []
        assert "attachment" in out.input_parameters["properties"]

    def test_safe_without_user_id(self):
        schema = SimpleNamespace(
            input_parameters={"properties": {"attachment": {"type": "string"}}}
        )
        out = outlook_hide_user_id_schema_modifier("OUTLOOK_SEND_EMAIL", "outlook", schema)
        assert out.input_parameters["properties"] == {"attachment": {"type": "string"}}


class TestOutlookAttachmentBeforeHook:
    def test_missing_attachment_key_is_noop(self):
        params = {"arguments": {"subject": "hi"}, "user_id": "u1"}
        assert outlook_attachment_before_hook("OUTLOOK_SEND_EMAIL", "outlook", params) is params

    def test_url_value_passes_through(self):
        arguments = {"attachment": "https://drive/download/1"}
        params = {"arguments": arguments, "user_id": "u1"}
        with patch(f"{HOOKS}.mint_share_url") as mint:
            out = outlook_attachment_before_hook("OUTLOOK_SEND_EMAIL", "outlook", params)
        assert mint.called is False
        assert out["arguments"] is arguments

    def test_plain_http_url_passes_through(self):
        # Both schemes are already fetchable by Composio; treating an http URL
        # as a workspace path would send it to the grant minter, which would
        # either fail or hand Outlook a grant for a file that is not ours.
        arguments = {"attachment": "http://drive/download/1"}
        params = {"arguments": arguments, "user_id": "u1"}
        with patch(f"{HOOKS}.mint_share_url") as mint:
            out = outlook_attachment_before_hook("OUTLOOK_SEND_EMAIL", "outlook", params)
        assert mint.called is False
        assert out["arguments"] is arguments

    def test_url_list_passes_through(self):
        arguments = {"attachment": ["https://x/a.pdf"]}
        params = {"arguments": arguments, "user_id": "u1"}
        with patch(f"{HOOKS}.mint_share_url") as mint:
            outlook_attachment_before_hook("OUTLOOK_SEND_EMAIL", "outlook", params)
        assert mint.called is False

    def test_workspace_path_inside_a_list_is_minted(self):
        # "Accepts a single file or a list of files" — a list is a shape the
        # model will pick, and a raw /workspace path in it is just as unfetchable
        # by Composio as a bare one.
        params = {
            "arguments": {"attachment": ["/workspace/sessions/c/deck.pdf"]},
            "user_id": "u1",
        }
        with patch(f"{HOOKS}.mint_share_url", return_value="https://api/s?token=t") as mint:
            out = outlook_attachment_before_hook("OUTLOOK_SEND_EMAIL", "outlook", params)
        assert mint.call_args.kwargs["workspace_path"] == "/workspace/sessions/c/deck.pdf"
        assert out["arguments"]["attachment"] == ["https://api/s?token=t"]

    def test_mixed_list_mints_only_the_workspace_paths(self):
        params = {
            "arguments": {"attachment": ["https://x/a.pdf", "/workspace/b.pdf"]},
            "user_id": "u1",
        }
        with patch(f"{HOOKS}.mint_share_url", return_value="https://api/s?token=t") as mint:
            out = outlook_attachment_before_hook("OUTLOOK_SEND_EMAIL", "outlook", params)
        assert mint.call_count == 1
        assert out["arguments"]["attachment"] == ["https://x/a.pdf", "https://api/s?token=t"]

    def test_workspace_path_in_a_list_without_user_aborts(self):
        params = {"arguments": {"attachment": ["/workspace/a.pdf"]}}
        with pytest.raises(HookAbortError, match="user context"):
            outlook_attachment_before_hook("OUTLOOK_SEND_EMAIL", "outlook", params)

    def test_non_dict_arguments_passes_through(self):
        params = {"arguments": ["not-a-dict"], "user_id": "u1"}
        with patch(f"{HOOKS}.mint_share_url") as mint:
            assert outlook_attachment_before_hook("OUTLOOK_SEND_EMAIL", "outlook", params) is params
        assert mint.called is False

    def test_workspace_path_mints_with_tool_attribution(self):
        params = {
            "arguments": {"attachment": "/workspace/sessions/c/deck.pdf"},
            "user_id": "u1",
        }
        with patch(
            f"{HOOKS}.mint_share_url", return_value="https://api/files/s/tok/deck.pdf"
        ) as mint:
            out = outlook_attachment_before_hook("OUTLOOK_CREATE_DRAFT", "outlook", params)
        assert mint.call_args.kwargs == {
            "user_id": "u1",
            "workspace_path": "/workspace/sessions/c/deck.pdf",
            "tool": "OUTLOOK_CREATE_DRAFT",
            "toolkit": "outlook",
        }
        assert out["arguments"]["attachment"] == "https://api/files/s/tok/deck.pdf"

    def test_missing_user_id_aborts(self):
        params = {"arguments": {"attachment": "/workspace/a.pdf"}}
        with pytest.raises(HookAbortError, match="user context"):
            outlook_attachment_before_hook("OUTLOOK_SEND_EMAIL", "outlook", params)

    def test_mint_failure_aborts_loud(self):
        params = {
            "arguments": {"attachment": "/workspace/missing.pdf"},
            "user_id": "u1",
        }
        with patch(f"{HOOKS}.mint_share_url", side_effect=FileNotFoundError("gone")):
            with pytest.raises(HookAbortError, match="missing.pdf"):
                outlook_attachment_before_hook("OUTLOOK_SEND_EMAIL", "outlook", params)
