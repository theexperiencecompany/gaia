"""Gmail attachment hook + registry abort-signal tests.

Covers the agent-facing side of email attachments:
- the schema modifier that swaps Composio's raw ``attachment`` for a friendly
  ``attachments`` reference list,
- the before-hook that resolves those references and, critically, ABORTS the tool
  call (rather than sending mail without the file) when resolution fails,
- the registry contract that lets a hook signal that abort.
"""

from types import SimpleNamespace
from unittest.mock import patch

from pydantic import BaseModel
import pytest

from app.utils.composio_hooks.gmail_hooks import (
    _resolve_compose_attachments,
    gmail_compose_attachments_schema_modifier,
    gmail_compose_before_hook,
)
from app.utils.composio_hooks.registry import ComposioHookRegistry, HookAbortError
from app.utils.errors import AppError

HOOKS = "app.utils.composio_hooks.gmail_hooks"


def _schema(props: dict, required: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(input_parameters={"properties": props, "required": required or []})


class TestAttachmentsSchemaModifier:
    def test_replaces_raw_attachment_with_references(self):
        schema = _schema(
            {"attachment": {"type": "object"}, "subject": {"type": "string"}},
            required=["attachment"],
        )
        out = gmail_compose_attachments_schema_modifier("GMAIL_CREATE_EMAIL_DRAFT", "gmail", schema)
        props = out.input_parameters["properties"]
        assert "attachment" not in props
        assert props["attachments"]["type"] == "array"
        assert "attachment" not in out.input_parameters["required"]


class TestResolveComposeAttachments:
    def test_no_attachments_is_noop(self):
        params = {"arguments": {"subject": "hi"}, "user_id": "u1"}
        assert _resolve_compose_attachments("GMAIL_SEND_EMAIL", "gmail", params) == []
        assert "attachment" not in params["arguments"]

    def test_single_reference_becomes_a_bare_object(self):
        params = {
            "arguments": {"attachments": [{"url": "https://x/y.pdf"}]},
            "user_id": "u1",
        }
        resolved = [{"name": "y.pdf", "mimetype": "application/pdf", "s3key": "k/1"}]
        with patch(f"{HOOKS}.resolve_attachments_sync", return_value=resolved):
            display = _resolve_compose_attachments("GMAIL_SEND_EMAIL", "gmail", params)

        # One file -> a single FileUploadable object (pinned toolkit rejects a list).
        assert params["arguments"]["attachment"] == resolved[0]
        assert "attachments" not in params["arguments"]
        # The stream payload carries name+mimetype only, never the s3key.
        assert display == [{"name": "y.pdf", "mimetype": "application/pdf"}]

    def test_multiple_references_become_a_list(self):
        params = {
            "arguments": {"attachments": [{"url": "https://x/a.pdf"}, {"url": "https://x/b.pdf"}]},
            "user_id": "u1",
        }
        resolved = [
            {"name": "a.pdf", "mimetype": "application/pdf", "s3key": "k/a"},
            {"name": "b.pdf", "mimetype": "application/pdf", "s3key": "k/b"},
        ]
        with patch(f"{HOOKS}.resolve_attachments_sync", return_value=resolved):
            _resolve_compose_attachments("GMAIL_SEND_EMAIL", "gmail", params)
        assert params["arguments"]["attachment"] == resolved

    def test_generated_model_items_are_coerced(self):
        """The agent path delivers Composio-generated Pydantic models, not dicts."""

        class _GenItem(BaseModel):
            workspace_path: str | None = None
            url: str | None = None
            name: str | None = None

        params = {
            "arguments": {"attachments": [_GenItem(url="https://x/y.pdf", name="y.pdf")]},
            "user_id": "u1",
        }
        resolved = [{"name": "y.pdf", "mimetype": "application/pdf", "s3key": "k/1"}]
        with patch(f"{HOOKS}.resolve_attachments_sync", return_value=resolved) as res:
            _resolve_compose_attachments("GMAIL_SEND_EMAIL", "gmail", params)
        # The generated model was normalised into an AttachmentReference before resolving.
        passed_refs = res.call_args.args[1]
        assert passed_refs[0].url == "https://x/y.pdf"

    def test_missing_user_id_aborts(self):
        params = {"arguments": {"attachments": [{"url": "https://x"}]}}
        with pytest.raises(HookAbortError):
            _resolve_compose_attachments("GMAIL_SEND_EMAIL", "gmail", params)

    def test_non_list_attachments_aborts(self):
        params = {"arguments": {"attachments": "not-a-list"}, "user_id": "u1"}
        with pytest.raises(HookAbortError):
            _resolve_compose_attachments("GMAIL_SEND_EMAIL", "gmail", params)

    def test_invalid_reference_aborts(self):
        params = {"arguments": {"attachments": [{"name": "no-source"}]}, "user_id": "u1"}
        with pytest.raises(HookAbortError):
            _resolve_compose_attachments("GMAIL_SEND_EMAIL", "gmail", params)

    def test_resolver_failure_becomes_abort(self):
        params = {"arguments": {"attachments": [{"url": "https://bad"}]}, "user_id": "u1"}
        with patch(
            f"{HOOKS}.resolve_attachments_sync",
            side_effect=AppError(message="upload failed", status_code=400),
        ):
            with pytest.raises(HookAbortError, match="upload failed"):
                _resolve_compose_attachments("GMAIL_SEND_EMAIL", "gmail", params)


class TestBeforeHookPropagatesAbort:
    def test_before_hook_does_not_swallow_abort(self):
        """The whole before-hook is wrapped in try/except; attachment failures must
        still propagate (the tool must NOT run without the requested file)."""
        params = {
            "arguments": {
                "subject": "s",
                "body": "b",
                "recipient_email": "x@y.com",
                "attachments": [{"url": "https://bad"}],
            },
            "user_id": "u1",
        }
        with patch(
            f"{HOOKS}.resolve_attachments_sync",
            side_effect=AppError(message="nope", status_code=400),
        ):
            with pytest.raises(HookAbortError):
                gmail_compose_before_hook("GMAIL_CREATE_EMAIL_DRAFT", "gmail", params)


class TestRegistryAbortContract:
    def test_reraises_abort_but_swallows_other_errors(self):
        registry = ComposioHookRegistry()

        def boom(tool, toolkit, params):
            raise RuntimeError("incidental hook bug")

        def abort(tool, toolkit, params):
            raise HookAbortError("must not run")

        registry.register_before_hook(boom)
        params = {"arguments": {}}
        # An incidental bug is swallowed: the tool call still proceeds.
        assert registry.execute_before_hooks("T", "tk", params) == params

        registry.register_before_hook(abort)
        with pytest.raises(HookAbortError):
            registry.execute_before_hooks("T", "tk", params)
