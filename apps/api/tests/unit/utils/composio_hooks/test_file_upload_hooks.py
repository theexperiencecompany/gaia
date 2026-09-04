"""Generic file-upload hooks: model capability across all Composio toolkits.

Covers the shape-scoped contract:
- the schema modifier swaps Composio's native ``attachment`` for friendly
  ``attachments`` on any tool carrying it (Outlook-like), while Slack-style
  ``attachments`` blocks, scalar params, and already-swapped schemas pass
  through untouched,
- the lenient before-hook resolves genuine file references for any tool but
  leaves foreign ``attachments`` payloads alone — strictness (abort on
  anything unexpected) stays the Gmail hook's contract, tested alongside it.
"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import BaseModel
import pytest

from app.models.mail_models import AttachmentReference
from app.utils.composio_hooks.file_upload_hooks import (
    file_upload_before_hook,
    file_upload_schema_modifier,
    has_native_upload_param,
    resolve_tool_attachments,
)
from app.utils.composio_hooks.registry import HookAbortError
from app.utils.errors import AppError

HOOKS = "app.utils.composio_hooks.file_upload_hooks"


def _schema(props: dict, required: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(input_parameters={"properties": props, "required": required or []})


def _native_attachment_schema() -> dict:
    # Mirrors the SDK: FileUploadable emits file_uploadable into its own schema
    # node (model_config json_schema_extra), alongside type/properties.
    return {
        "type": "object",
        "file_uploadable": True,
        "properties": {
            "name": {"type": "string"},
            "mimetype": {"type": "string"},
            "s3key": {"type": "string"},
        },
    }


class TestHasNativeUploadParam:
    def test_marked_attachment_matches(self):
        assert has_native_upload_param(_schema({"attachment": _native_attachment_schema()}))

    def test_nested_marker_in_anyof_matches(self):
        assert has_native_upload_param(
            _schema({"attachment": {"anyOf": [_native_attachment_schema(), {"type": "null"}]}})
        )

    def test_marker_wins_on_non_object_shape(self):
        # The object-shape heuristic alone would miss this; the marker is the
        # authoritative signal, so a marked string-typed node still matches.
        assert has_native_upload_param(
            _schema({"attachment": {"type": "string", "file_uploadable": True}})
        )

    def test_legacy_bare_object_no_longer_matches(self):
        # A bare object without marker or s3key fingerprint is indistinguishable
        # from Graph-style passthrough objects — claiming it would corrupt calls
        # like OUTLOOK_ADD_MAIL_ATTACHMENT, so it must not match.
        assert not has_native_upload_param(_schema({"attachment": {"type": "object"}}))

    def test_legacy_s3key_shape_still_matches(self):
        unmarked = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "mimetype": {"type": "string"},
                "s3key": {"type": "string"},
            },
        }
        assert has_native_upload_param(_schema({"attachment": unmarked}))

    def test_scalar_attachment_id_does_not_match(self):
        assert not has_native_upload_param(_schema({"attachment": {"type": "string"}}))

    def test_slack_style_blocks_do_not_match(self):
        assert not has_native_upload_param(_schema({"attachments": {"type": "array"}}))

    def test_already_swapped_schema_does_not_match(self):
        schema = _schema({"subject": {"type": "string"}})
        out = file_upload_schema_modifier("OUTLOOK_SEND_EMAIL", "outlook", schema)
        assert not has_native_upload_param(out)

    def test_non_dict_input_parameters_do_not_match(self):
        assert not has_native_upload_param(SimpleNamespace(input_parameters=None))


class TestFileUploadSchemaModifier:
    def test_outlook_like_tool_gets_friendly_attachments(self):
        schema = _schema(
            {"attachment": _native_attachment_schema(), "subject": {"type": "string"}},
            required=["attachment"],
        )
        out = file_upload_schema_modifier("OUTLOOK_SEND_EMAIL", "outlook", schema)
        props = out.input_parameters["properties"]
        assert "attachment" not in props
        assert props["attachments"]["type"] == "array"
        assert "attachment" not in out.input_parameters["required"]

    def test_item_properties_derive_from_the_reference_model(self):
        schema = _schema({"attachment": _native_attachment_schema()})
        out = file_upload_schema_modifier("OUTLOOK_SEND_EMAIL", "outlook", schema)
        props = out.input_parameters["properties"]["attachments"]["items"]["properties"]
        assert set(props) == set(AttachmentReference.model_fields)
        for name, field in AttachmentReference.model_fields.items():
            assert props[name]["description"] == field.description

    def test_slack_style_schema_passes_through(self):
        blocks = {"type": "array"}
        schema = _schema({"attachments": blocks, "text": {"type": "string"}})
        # Snapshot: the modifier mutates properties in place, so comparing
        # against the live `props` object would be tautological.
        before = deepcopy(schema.input_parameters["properties"])
        out = file_upload_schema_modifier("SLACK_SEND_MESSAGE", "slack", schema)
        assert out.input_parameters["properties"] == before
        assert "attachments" in before  # the assertion above is not vacuous

    def test_scalar_attachment_passes_through(self):
        schema = _schema({"attachment": {"type": "string"}})
        before = deepcopy(schema.input_parameters["properties"])
        out = file_upload_schema_modifier("SOME_TOOL", "some", schema)
        assert out.input_parameters["properties"] == before

    def test_modifier_is_idempotent(self):
        schema = _schema({"attachment": _native_attachment_schema()})
        once = file_upload_schema_modifier("T", "tk", schema)
        twice = file_upload_schema_modifier("T", "tk", once)
        assert set(twice.input_parameters["properties"]) == {"attachments"}

    def test_legacy_unmarked_bare_object_passes_through(self):
        schema = _schema({"attachment": {"type": "object"}})
        out = file_upload_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert out.input_parameters["properties"] == {"attachment": {"type": "object"}}


class TestRealToolkitShapes:
    """Modifier contract against real Composio schema shapes.

    Fixtures mirror docs.composio.dev/toolkit pages (outlook, slack): the
    rendered types there are what the modifier must classify correctly.
    """

    def test_gmail_marked_object_swaps(self):
        schema = _schema(
            {"attachment": _native_attachment_schema(), "subject": {"type": "string"}},
            required=["attachment"],
        )
        out = file_upload_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert out.input_parameters["properties"]["attachments"]["type"] == "array"
        assert "attachment" not in out.input_parameters["required"]

    def test_outlook_path_string_passes_through(self):
        # OUTLOOK_SEND_EMAIL / OUTLOOK_CREATE_DRAFT render `attachment` as a
        # plain string ("File(s) to attach. Accepts a single file or a list of
        # files.") — the transformed path form the model fills directly.
        schema = _schema(
            {
                "attachment": {"type": "string"},
                "subject": {"type": "string"},
            }
        )
        before = deepcopy(schema.input_parameters["properties"])
        out = file_upload_schema_modifier("OUTLOOK_SEND_EMAIL", "outlook", schema)
        assert out.input_parameters["properties"] == before

    def test_outlook_graph_object_passes_through(self):
        # OUTLOOK_ADD_MAIL_ATTACHMENT's `attachment` is a Graph-style object
        # (contentBytes/contentType alternatives) — not a FileUploadable, so
        # swapping in our s3key form would corrupt the call.
        schema = _schema(
            {
                "attachment": {
                    "type": "object",
                    "properties": {
                        "contentBytes": {"type": "string"},
                        "contentType": {"type": "string"},
                        "odata_type": {"type": "string"},
                    },
                },
                "message_id": {"type": "string"},
            }
        )
        before = deepcopy(schema.input_parameters["properties"])
        out = file_upload_schema_modifier("OUTLOOK_ADD_MAIL_ATTACHMENT", "outlook", schema)
        assert out.input_parameters["properties"] == before

    def test_slack_upload_file_param_passes_through(self):
        # SLACK_UPLOAD_OR_CREATE_A_FILE_IN_SLACK takes `file` (string path),
        # not `attachment` — nothing to swap, nothing to break.
        schema = _schema({"file": {"type": "string"}, "channels": {"type": "string"}})
        before = deepcopy(schema.input_parameters["properties"])
        out = file_upload_schema_modifier(
            "SLACK_UPLOAD_OR_CREATE_A_FILE_IN_SLACK", "slack", schema
        )
        assert out.input_parameters["properties"] == before

    def test_slack_message_blocks_string_passes_through(self):
        # SLACK_SEND_MESSAGE's `attachments` is a JSON-string of legacy blocks
        # ("NOT for file/image uploads") — the plural key must never trigger.
        schema = _schema({"attachments": {"type": "string"}, "text": {"type": "string"}})
        before = deepcopy(schema.input_parameters["properties"])
        out = file_upload_schema_modifier("SLACK_SEND_MESSAGE", "slack", schema)
        assert out.input_parameters["properties"] == before


class TestMultiToolResolution:
    """Before-hook behavior threaded per toolkit (docs-shaped params)."""

    def test_outlook_evidence_resolves_with_outlook_attribution(self):
        params = {
            "arguments": {
                "to": "a@b.com",
                "attachments": [{"workspace_path": "sessions/c/deck.pdf"}],
            },
            "user_id": "u1",
        }
        resolved = [{"name": "deck.pdf", "mimetype": "application/pdf", "s3key": "k/9"}]
        with patch(f"{HOOKS}.resolve_attachments_sync", return_value=resolved) as res:
            display = resolve_tool_attachments(
                "OUTLOOK_SEND_EMAIL", "outlook", params, strict=False
            )
        assert res.call_args.kwargs == {"tool": "OUTLOOK_SEND_EMAIL", "toolkit": "outlook"}
        assert params["arguments"]["attachment"] == resolved[0]
        assert display == [{"name": "deck.pdf", "mimetype": "application/pdf"}]

    def test_outlook_path_string_needs_no_resolution(self):
        # Transformed path form: the model fills `attachment` directly, so the
        # hook stands down and Composio's own substitution owns the upload.
        arguments = {"to": "a@b.com", "attachment": "/workspace/sessions/c/deck.pdf"}
        params = {"arguments": arguments, "user_id": "u1"}
        with patch(f"{HOOKS}.resolve_attachments_sync") as res:
            assert (
                resolve_tool_attachments("OUTLOOK_SEND_EMAIL", "outlook", params, strict=False)
                == []
            )
        assert res.called is False
        assert params["arguments"] is arguments

    def test_slack_upload_path_needs_no_resolution(self):
        arguments = {"channels": "C123", "file": "/workspace/sessions/c/shot.png"}
        params = {"arguments": arguments, "user_id": "u1"}
        with patch(f"{HOOKS}.resolve_attachments_sync") as res:
            assert (
                resolve_tool_attachments(
                    "SLACK_UPLOAD_OR_CREATE_A_FILE_IN_SLACK", "slack", params, strict=False
                )
                == []
            )
        assert res.called is False
        assert params["arguments"] is arguments

    def test_slack_message_blocks_string_passes_through(self):
        arguments = {"channel": "C123", "attachments": '[{"text": "hi"}]'}
        params = {"arguments": arguments, "user_id": "u1"}
        with patch(f"{HOOKS}.resolve_attachments_sync") as res:
            assert (
                resolve_tool_attachments("SLACK_SEND_MESSAGE", "slack", params, strict=False)
                == []
            )
        assert res.called is False
        assert params["arguments"] is arguments


class TestLenientResolve:
    def test_evidence_list_resolves_for_any_toolkit(self):
        params = {
            "arguments": {"attachments": [{"url": "https://x/y.pdf"}]},
            "user_id": "u1",
        }
        resolved = [{"name": "y.pdf", "mimetype": "application/pdf", "s3key": "k/1"}]
        with patch(f"{HOOKS}.resolve_attachments_sync", return_value=resolved) as res:
            display = resolve_tool_attachments("OUTLOOK_SEND_EMAIL", "outlook", params, strict=False)

        assert res.call_args.args[0] == "u1"
        assert res.call_args.kwargs == {"tool": "OUTLOOK_SEND_EMAIL", "toolkit": "outlook"}
        assert params["arguments"]["attachment"] == resolved[0]
        assert "attachments" not in params["arguments"]
        assert display == [{"name": "y.pdf", "mimetype": "application/pdf"}]

    def test_foreign_block_list_passes_through_untouched(self):
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "hi"}}]
        params = {"arguments": {"attachments": blocks}, "user_id": "u1"}
        with patch(f"{HOOKS}.resolve_attachments_sync") as res:
            assert (
                resolve_tool_attachments("SLACK_SEND_MESSAGE", "slack", params, strict=False)
                == []
            )
        assert res.called is False
        assert params["arguments"]["attachments"] is blocks

    def test_non_list_foreign_value_passes_through(self):
        params = {"arguments": {"attachments": "legacy-string"}, "user_id": "u1"}
        with patch(f"{HOOKS}.resolve_attachments_sync") as res:
            assert (
                resolve_tool_attachments("SLACK_SEND_MESSAGE", "slack", params, strict=False)
                == []
            )
        assert res.called is False

    def test_no_attachments_derives_display_from_native(self):
        params = {
            "arguments": {
                "attachment": {"name": "a.pdf", "mimetype": "application/pdf", "s3key": "k"}
            },
            "user_id": "u1",
        }
        assert resolve_tool_attachments("T", "tk", params, strict=False) == [
            {"name": "a.pdf", "mimetype": "application/pdf"}
        ]

    def test_broken_reference_still_aborts_loudly(self):
        params = {"arguments": {"attachments": [{"url": "https://bad"}]}, "user_id": "u1"}
        with patch(
            f"{HOOKS}.resolve_attachments_sync",
            side_effect=AppError(message="upload failed", status_code=400),
        ):
            with pytest.raises(HookAbortError, match="upload failed"):
                resolve_tool_attachments("OUTLOOK_SEND_EMAIL", "outlook", params, strict=False)

    def test_evidence_without_user_aborts(self):
        params = {"arguments": {"attachments": [{"url": "https://x"}]}}
        with pytest.raises(HookAbortError, match="user context"):
            resolve_tool_attachments("T", "tk", params, strict=False)


class TestStrictResolve:
    def test_non_list_aborts(self):
        params = {"arguments": {"attachments": "not-a-list"}, "user_id": "u1"}
        with pytest.raises(HookAbortError, match="must be a list"):
            resolve_tool_attachments("GMAIL_SEND_EMAIL", "gmail", params, strict=True)

    def test_evidence_free_garbage_aborts(self):
        params = {"arguments": {"attachments": [{"name": "no-source"}]}, "user_id": "u1"}
        with pytest.raises(HookAbortError, match="Invalid attachment reference"):
            resolve_tool_attachments("GMAIL_SEND_EMAIL", "gmail", params, strict=True)

    def test_generated_model_items_are_coerced(self):
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
            resolve_tool_attachments("GMAIL_SEND_EMAIL", "gmail", params, strict=True)
        assert res.call_args.args[1][0].url == "https://x/y.pdf"


class TestGenericBeforeHook:
    def test_foreign_payload_leaves_params_unchanged(self):
        blocks = [{"type": "section"}]
        params = {"arguments": {"attachments": blocks}, "user_id": "u1"}
        with patch(f"{HOOKS}.resolve_attachments_sync") as res:
            out = file_upload_before_hook("SLACK_SEND_MESSAGE", "slack", params)
        assert res.called is False
        assert out is params
        assert params["arguments"]["attachments"] is blocks

    def test_file_references_resolve_for_any_tool(self):
        params = {
            "arguments": {"attachments": [{"url": "https://x/y.pdf"}]},
            "user_id": "u1",
        }
        resolved = [{"name": "y.pdf", "mimetype": "application/pdf", "s3key": "k/1"}]
        with patch(f"{HOOKS}.resolve_attachments_sync", return_value=resolved):
            out = file_upload_before_hook("OUTLOOK_SEND_EMAIL", "outlook", params)
        assert out["arguments"]["attachment"] == resolved[0]
