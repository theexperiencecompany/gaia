"""Generic file-upload hooks: model capability across all Composio toolkits.

Covers the shape-scoped contract:
- the schema modifier finds the tool's native upload param by Composio's
  ``file_uploadable`` marker (whatever it is named), swaps it for friendly
  ``attachments``, and records the swap,
- the before-hook acts only on the tools that swap produced — a tool we never
  touched keeps its own ``attachments`` argument, whatever it means to it,
- for a tool we did swap, anything unexpected in ``attachments`` aborts rather
  than reaching the tool.
"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import BaseModel
import pytest

from app.constants.email import EMAIL_ATTACHMENTS_PARAM_DESCRIPTION
from app.models.mail_models import AttachmentReference
from app.utils.composio_hooks import file_upload_hooks
from app.utils.composio_hooks.file_upload_hooks import (
    file_upload_before_hook,
    file_upload_schema_modifier,
    find_native_upload_param,
    resolve_tool_attachments,
    swapped_upload_param,
)
from app.utils.composio_hooks.registry import HookAbortError
from app.utils.errors import AppError

HOOKS = "app.utils.composio_hooks.file_upload_hooks"


@pytest.fixture(autouse=True)
def _clean_swap_registry():
    """The swap registry is module-level state; no test may inherit another's."""
    file_upload_hooks._swapped_upload_params.clear()
    yield
    file_upload_hooks._swapped_upload_params.clear()


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


class TestFindNativeUploadParam:
    def test_marked_attachment_matches(self):
        assert (
            find_native_upload_param(_schema({"attachment": _native_attachment_schema()}))
            == "attachment"
        )

    def test_marked_param_under_any_other_name_matches(self):
        # Composio names the upload param per tool; matching only "attachment"
        # would silently skip every toolkit that picked a different name.
        assert (
            find_native_upload_param(
                _schema({"file": _native_attachment_schema(), "channels": {"type": "string"}})
            )
            == "file"
        )

    def test_nested_marker_in_anyof_matches(self):
        assert (
            find_native_upload_param(
                _schema({"attachment": {"anyOf": [_native_attachment_schema(), {"type": "null"}]}})
            )
            == "attachment"
        )

    def test_marker_wins_on_non_object_shape(self):
        # The object-shape heuristic alone would miss this; the marker is the
        # authoritative signal, so a marked string-typed node still matches.
        assert (
            find_native_upload_param(
                _schema({"attachment": {"type": "string", "file_uploadable": True}})
            )
            == "attachment"
        )

    def test_legacy_bare_object_no_longer_matches(self):
        # A bare object without marker or s3key fingerprint is indistinguishable
        # from Graph-style passthrough objects — claiming it would corrupt calls
        # like OUTLOOK_ADD_MAIL_ATTACHMENT, so it must not match.
        assert find_native_upload_param(_schema({"attachment": {"type": "object"}})) is None

    def test_legacy_s3key_shape_still_matches(self):
        unmarked = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "mimetype": {"type": "string"},
                "s3key": {"type": "string"},
            },
        }
        assert find_native_upload_param(_schema({"attachment": unmarked})) == "attachment"

    def test_legacy_s3key_shape_under_another_name_does_not_match(self):
        # Unmarked, so the only signal is the conventional param name; an s3key
        # fingerprint anywhere else is too weak to claim.
        unmarked = {"type": "object", "properties": {"s3key": {"type": "string"}}}
        assert find_native_upload_param(_schema({"payload": unmarked})) is None

    def test_scalar_attachment_id_does_not_match(self):
        assert find_native_upload_param(_schema({"attachment": {"type": "string"}})) is None

    def test_marked_items_of_a_list_param_match(self):
        # A param that takes several files is still that param.
        assert (
            find_native_upload_param(
                _schema({"files": {"type": "array", "items": _native_attachment_schema()}})
            )
            == "files"
        )

    def test_marker_under_one_of_matches(self):
        assert (
            find_native_upload_param(
                _schema({"attachment": {"oneOf": [_native_attachment_schema(), {"type": "null"}]}})
            )
            == "attachment"
        )

    def test_marker_under_all_of_matches(self):
        assert (
            find_native_upload_param(
                _schema({"attachment": {"allOf": [_native_attachment_schema()]}})
            )
            == "attachment"
        )

    def test_marker_in_tuple_form_items_matches(self):
        # JSON Schema also allows `items` as a list (positional/tuple form).
        assert (
            find_native_upload_param(
                _schema({"files": {"type": "array", "items": [_native_attachment_schema()]}})
            )
            == "files"
        )

    def test_array_of_unmarked_items_does_not_match(self):
        # An `items` dict is only interesting when the item itself is marked;
        # claiming every array param would delete params tools depend on.
        assert (
            find_native_upload_param(
                _schema({"attachment": {"type": "array", "items": {"type": "string"}}})
            )
            is None
        )

    def test_non_dict_property_does_not_match(self):
        assert find_native_upload_param(_schema({"attachment": "not-a-schema"})) is None

    def test_unmarked_variants_do_not_match(self):
        # Every branch walked, nothing marked: the walk must not claim the param.
        assert (
            find_native_upload_param(
                _schema(
                    {
                        "attachment": {
                            "anyOf": [{"type": "string"}],
                            "oneOf": [{"type": "integer"}],
                            "allOf": [{"type": "null"}],
                            "items": [{"type": "boolean"}],
                        }
                    }
                )
            )
            is None
        )

    def test_composite_param_merely_containing_a_file_does_not_match(self):
        # Claiming `message` would delete the param the tool needs and write a
        # bare {name, mimetype, s3key} back under it — the tool becomes uncallable.
        composite = {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "file": _native_attachment_schema(),
            },
        }
        assert find_native_upload_param(_schema({"message": composite})) is None

    def test_a_composite_param_does_not_shadow_the_real_upload_param(self):
        composite = {
            "type": "object",
            "properties": {"file": _native_attachment_schema()},
        }
        # Dict order puts the composite first; the real param must still win.
        assert (
            find_native_upload_param(
                _schema({"message": composite, "attachment": _native_attachment_schema()})
            )
            == "attachment"
        )

    def test_slack_style_blocks_do_not_match(self):
        assert find_native_upload_param(_schema({"attachments": {"type": "array"}})) is None

    def test_already_swapped_schema_does_not_match(self):
        schema = _schema({"attachment": _native_attachment_schema()})
        out = file_upload_schema_modifier("OUTLOOK_SEND_EMAIL", "outlook", schema)
        assert find_native_upload_param(out) is None

    def test_non_dict_input_parameters_do_not_match(self):
        assert find_native_upload_param(SimpleNamespace(input_parameters=None)) is None


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

    def test_swap_records_the_native_param_name(self):
        schema = _schema({"file": _native_attachment_schema()}, required=["file"])
        file_upload_schema_modifier("SLACK_UPLOAD_FILE", "slack", schema)
        assert file_upload_hooks._swapped_upload_params["SLACK_UPLOAD_FILE"] == "file"
        assert "file" not in schema.input_parameters["required"]

    def test_passthrough_records_nothing(self):
        file_upload_schema_modifier("SLACK_SEND_MESSAGE", "slack", _schema({"attachments": {}}))
        assert file_upload_hooks._swapped_upload_params == {}

    def test_friendly_param_carries_the_agent_facing_instructions(self):
        # The description is the only instruction the model gets on how to
        # reference a file; an empty one leaves it guessing at the shape.
        schema = _schema({"attachment": _native_attachment_schema()})
        out = file_upload_schema_modifier("OUTLOOK_SEND_EMAIL", "outlook", schema)
        assert (
            out.input_parameters["properties"]["attachments"]["description"]
            == EMAIL_ATTACHMENTS_PARAM_DESCRIPTION
        )

    def test_friendly_param_is_a_valid_array_of_reference_objects(self):
        # The whole JSON-Schema skeleton is the contract the model fills: a
        # wrong key or type here leaves it unable to pass a file at all, and
        # nothing else in the stack would notice.
        schema = _schema({"attachment": _native_attachment_schema()})
        out = file_upload_schema_modifier("OUTLOOK_SEND_EMAIL", "outlook", schema)
        friendly = out.input_parameters["properties"]["attachments"]
        assert set(friendly) == {"type", "description", "items"}
        assert friendly["type"] == "array"
        assert set(friendly["items"]) == {"type", "properties"}
        assert friendly["items"]["type"] == "object"
        item_props = friendly["items"]["properties"]
        assert set(item_props) == {"workspace_path", "url", "name"}
        assert all(prop["type"] == "string" for prop in item_props.values())

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

    def test_composite_param_survives_the_modifier(self):
        composite = {
            "type": "object",
            "properties": {"text": {"type": "string"}, "file": _native_attachment_schema()},
        }
        schema = _schema({"message": composite}, required=["message"])
        before = deepcopy(schema.input_parameters["properties"])
        out = file_upload_schema_modifier("SOME_COMPOSITE_TOOL", "tk", schema)
        assert out.input_parameters["properties"] == before
        assert file_upload_hooks._swapped_upload_params == {}

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

    def test_slack_unmarked_file_param_passes_through(self):
        # SLACK_UPLOAD_OR_CREATE_A_FILE_IN_SLACK takes `file` as a plain string
        # path — no marker, nothing to swap, nothing to break.
        schema = _schema({"file": {"type": "string"}, "channels": {"type": "string"}})
        before = deepcopy(schema.input_parameters["properties"])
        out = file_upload_schema_modifier("SLACK_UPLOAD_OR_CREATE_A_FILE_IN_SLACK", "slack", schema)
        assert out.input_parameters["properties"] == before

    def test_slack_message_blocks_string_passes_through(self):
        # SLACK_SEND_MESSAGE's `attachments` is a JSON-string of legacy blocks
        # ("NOT for file/image uploads") — the plural key must never trigger.
        schema = _schema({"attachments": {"type": "string"}, "text": {"type": "string"}})
        before = deepcopy(schema.input_parameters["properties"])
        out = file_upload_schema_modifier("SLACK_SEND_MESSAGE", "slack", schema)
        assert out.input_parameters["properties"] == before


class TestResolveToolAttachments:
    def test_references_resolve_into_the_native_param(self):
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
                "OUTLOOK_SEND_EMAIL", "outlook", params, native_param="attachment"
            )
        assert res.call_args.args[0] == "u1"
        assert res.call_args.kwargs == {"tool": "OUTLOOK_SEND_EMAIL", "toolkit": "outlook"}
        assert params["arguments"]["attachment"] == resolved[0]
        assert "attachments" not in params["arguments"]
        assert display == [{"name": "deck.pdf", "mimetype": "application/pdf"}]

    def test_resolution_writes_back_under_the_tools_own_param_name(self):
        params = {"arguments": {"attachments": [{"url": "https://x/y.png"}]}, "user_id": "u1"}
        resolved = [{"name": "y.png", "mimetype": "image/png", "s3key": "k/2"}]
        with patch(f"{HOOKS}.resolve_attachments_sync", return_value=resolved):
            resolve_tool_attachments("SLACK_UPLOAD_FILE", "slack", params, native_param="file")
        assert params["arguments"]["file"] == resolved[0]
        assert "attachment" not in params["arguments"]

    def test_several_files_stay_a_list(self):
        params = {
            "arguments": {"attachments": [{"url": "https://x/1"}, {"url": "https://x/2"}]},
            "user_id": "u1",
        }
        resolved = [
            {"name": "1", "mimetype": "application/pdf", "s3key": "k/1"},
            {"name": "2", "mimetype": "application/pdf", "s3key": "k/2"},
        ]
        with patch(f"{HOOKS}.resolve_attachments_sync", return_value=resolved):
            resolve_tool_attachments("T", "tk", params, native_param="attachment")
        assert params["arguments"]["attachment"] == resolved

    def test_single_dict_reference_is_accepted(self):
        params = {"arguments": {"attachments": {"url": "https://x/y.pdf"}}, "user_id": "u1"}
        resolved = [{"name": "y.pdf", "mimetype": "application/pdf", "s3key": "k/1"}]
        with patch(f"{HOOKS}.resolve_attachments_sync", return_value=resolved) as res:
            resolve_tool_attachments("T", "tk", params, native_param="attachment")
        assert len(res.call_args.args[1]) == 1

    def test_display_falls_back_to_empty_strings_per_field(self):
        # Composio's uploader always sets both, but the card renders whatever is
        # here — a missing key must not put "None" in front of the user.
        params = {"arguments": {"attachment": {"s3key": "k"}}, "user_id": "u1"}
        assert resolve_tool_attachments("T", "tk", params, native_param="attachment") == [
            {"name": "", "mimetype": ""}
        ]

    def test_no_attachments_derives_display_from_native(self):
        params = {
            "arguments": {
                "attachment": {"name": "a.pdf", "mimetype": "application/pdf", "s3key": "k"}
            },
            "user_id": "u1",
        }
        assert resolve_tool_attachments("T", "tk", params, native_param="attachment") == [
            {"name": "a.pdf", "mimetype": "application/pdf"}
        ]

    def test_non_list_aborts(self):
        params = {"arguments": {"attachments": "not-a-list"}, "user_id": "u1"}
        with pytest.raises(HookAbortError, match="must be a list"):
            resolve_tool_attachments("GMAIL_SEND_EMAIL", "gmail", params, native_param="attachment")

    def test_empty_string_attachments_aborts(self):
        # Falsy but not a valid no-op: it must abort, not silently send unattached.
        params = {"arguments": {"attachments": ""}, "user_id": "u1"}
        with pytest.raises(HookAbortError, match="must be a list"):
            resolve_tool_attachments("GMAIL_SEND_EMAIL", "gmail", params, native_param="attachment")

    def test_empty_dict_attachments_aborts(self):
        params = {"arguments": {"attachments": {}}, "user_id": "u1"}
        with pytest.raises(HookAbortError, match="Invalid attachment reference"):
            resolve_tool_attachments("GMAIL_SEND_EMAIL", "gmail", params, native_param="attachment")

    def test_empty_list_attachments_is_a_noop(self):
        # An explicit empty list is the one supported falsy value: attach nothing,
        # and never write the native param or touch the friendly one.
        params = {"arguments": {"attachments": []}, "user_id": "u1"}
        assert resolve_tool_attachments("T", "tk", params, native_param="attachment") == []
        assert params["arguments"] == {"attachments": []}

    def test_reference_without_a_source_aborts(self):
        params = {"arguments": {"attachments": [{"name": "no-source"}]}, "user_id": "u1"}
        with pytest.raises(HookAbortError, match="Invalid attachment reference"):
            resolve_tool_attachments("GMAIL_SEND_EMAIL", "gmail", params, native_param="attachment")

    def test_broken_reference_still_aborts_loudly(self):
        params = {"arguments": {"attachments": [{"url": "https://bad"}]}, "user_id": "u1"}
        with (
            patch(
                f"{HOOKS}.resolve_attachments_sync",
                side_effect=AppError(message="upload failed", status_code=400),
            ),
            pytest.raises(HookAbortError, match="upload failed"),
        ):
            resolve_tool_attachments(
                "OUTLOOK_SEND_EMAIL", "outlook", params, native_param="attachment"
            )

    def test_references_without_user_abort(self):
        params = {"arguments": {"attachments": [{"url": "https://x"}]}}
        with pytest.raises(HookAbortError, match="user context"):
            resolve_tool_attachments("T", "tk", params, native_param="attachment")

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
            resolve_tool_attachments("GMAIL_SEND_EMAIL", "gmail", params, native_param="attachment")
        assert res.call_args.args[1][0].url == "https://x/y.pdf"


class TestSwappedUploadParamAccessor:
    def test_reports_the_recorded_name(self):
        file_upload_schema_modifier(
            "SLACK_UPLOAD_FILE", "slack", _schema({"file": _native_attachment_schema()})
        )
        assert swapped_upload_param("SLACK_UPLOAD_FILE") == "file"

    def test_reports_nothing_for_a_tool_we_never_swapped(self):
        assert swapped_upload_param("SLACK_SEND_MESSAGE") is None


class TestGenericBeforeHook:
    def test_tool_we_never_swapped_is_left_alone(self):
        # SLACK_SEND_MESSAGE's own `attachments` are legacy message blocks. They
        # carry a `url` key, so shape alone would claim them — only the record of
        # our own schema swap distinguishes ours from the tool's.
        blocks = [{"title": "hi", "url": "https://example.com/x"}]
        params = {"arguments": {"attachments": blocks}, "user_id": "u1"}
        with patch(f"{HOOKS}.resolve_attachments_sync") as res:
            out = file_upload_before_hook("SLACK_SEND_MESSAGE", "slack", params)
        assert res.called is False
        assert out is params
        assert params["arguments"]["attachments"] is blocks

    def test_swapped_tool_resolves_into_its_own_param(self):
        file_upload_schema_modifier(
            "SLACK_UPLOAD_FILE", "slack", _schema({"file": _native_attachment_schema()})
        )
        params = {"arguments": {"attachments": [{"url": "https://x/y.png"}]}, "user_id": "u1"}
        resolved = [{"name": "y.png", "mimetype": "image/png", "s3key": "k/1"}]
        with patch(f"{HOOKS}.resolve_attachments_sync", return_value=resolved) as res:
            out = file_upload_before_hook("SLACK_UPLOAD_FILE", "slack", params)
        assert out["arguments"]["file"] == resolved[0]
        assert "attachments" not in out["arguments"]
        # The upload is scoped to the invoking tool/toolkit in Composio's store.
        assert res.call_args.kwargs == {"tool": "SLACK_UPLOAD_FILE", "toolkit": "slack"}

    def test_swapped_tool_aborts_on_garbage(self):
        file_upload_schema_modifier(
            "OUTLOOK_SEND_EMAIL", "outlook", _schema({"attachment": _native_attachment_schema()})
        )
        params = {"arguments": {"attachments": "legacy-string"}, "user_id": "u1"}
        with pytest.raises(HookAbortError, match="must be a list"):
            file_upload_before_hook("OUTLOOK_SEND_EMAIL", "outlook", params)
