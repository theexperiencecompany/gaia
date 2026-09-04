"""Gmail attachment hook + registry abort-signal tests.

Covers the Gmail side of file attachments:
- the compose before-hook, which resolves references through the shared
  ``resolve_tool_attachments`` and builds the compose/sent card,
- the draft card's hand-off to the after-hook, which is what gives it the
  ``draft_id`` its Send button needs to send the draft (attachments included),
- the registry contract that lets a hook signal an abort.

The generic capability itself (schema modifier for every toolkit, which tools
the shared before-hook acts on) is tested in ``test_file_upload_hooks.py``.
"""

from types import SimpleNamespace
from unittest.mock import patch

from pydantic import BaseModel
import pytest

from app.utils.composio_hooks import file_upload_hooks
from app.utils.composio_hooks.file_upload_hooks import (
    NATIVE_UPLOAD_PARAM,
    file_upload_schema_modifier,
    resolve_tool_attachments,
)
from app.utils.composio_hooks.gmail_hooks import (
    _compose_recipient_ready,
    _compose_recipients,
    _normalize_compose_body,
    _pending_draft_card,
    _stream_compose_preview,
    gmail_compose_before_hook,
    gmail_create_draft_after_hook,
)
from app.utils.composio_hooks.registry import ComposioHookRegistry, HookAbortError
from app.utils.errors import AppError

HOOKS = "app.utils.composio_hooks.gmail_hooks"
SHARED = "app.utils.composio_hooks.file_upload_hooks"


@pytest.fixture(autouse=True)
def _no_held_card():
    """The held draft card is context state; no test may inherit another's."""
    _pending_draft_card.set(None)
    yield
    _pending_draft_card.set(None)


def _schema(props: dict, required: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(input_parameters={"properties": props, "required": required or []})


def _native_attachment_schema() -> dict:
    return {
        "type": "object",
        "file_uploadable": True,
        "properties": {
            "name": {"type": "string"},
            "mimetype": {"type": "string"},
            "s3key": {"type": "string"},
        },
    }


@pytest.fixture(autouse=True)
def _gmail_upload_param_swapped():
    """Bind the Gmail compose tools the way the real fetch does.

    ``gmail_compose_before_hook`` reads the native param name off the swap the
    schema modifier records at bind time, so a hook test that skips the bind is
    testing a tool the model could never have passed ``attachments`` to.
    """
    file_upload_hooks._swapped_upload_params.clear()
    for tool in ("GMAIL_SEND_EMAIL", "GMAIL_CREATE_EMAIL_DRAFT"):
        file_upload_schema_modifier(
            tool, "gmail", _schema({"attachment": _native_attachment_schema()})
        )
    yield
    file_upload_hooks._swapped_upload_params.clear()


class TestStrictGmailResolution:
    """Gmail resolves strict: anything unexpected in ``attachments`` aborts."""

    def test_no_attachments_is_noop(self):
        params = {"arguments": {"subject": "hi"}, "user_id": "u1"}
        assert (
            resolve_tool_attachments(
                "GMAIL_SEND_EMAIL", "gmail", params, native_param=NATIVE_UPLOAD_PARAM
            )
            == []
        )
        assert "attachment" not in params["arguments"]

    def test_missing_arguments_key_is_noop(self):
        # Exercises the `params.get("arguments", {})` fallback: no arguments at all.
        assert (
            resolve_tool_attachments(
                "GMAIL_SEND_EMAIL", "gmail", {"user_id": "u1"}, native_param=NATIVE_UPLOAD_PARAM
            )
            == []
        )

    def test_single_reference_becomes_a_bare_object(self):
        params = {
            "arguments": {"attachments": [{"url": "https://x/y.pdf"}]},
            "user_id": "u1",
        }
        resolved = [{"name": "y.pdf", "mimetype": "application/pdf", "s3key": "k/1"}]
        with patch(f"{SHARED}.resolve_attachments_sync", return_value=resolved) as res:
            display = resolve_tool_attachments(
                "GMAIL_SEND_EMAIL", "gmail", params, native_param=NATIVE_UPLOAD_PARAM
            )

        # The invoking tool/toolkit are threaded into the resolver.
        assert res.call_args.kwargs == {"tool": "GMAIL_SEND_EMAIL", "toolkit": "gmail"}
        assert res.call_args.args[0] == "u1"
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
        with patch(f"{SHARED}.resolve_attachments_sync", return_value=resolved):
            resolve_tool_attachments(
                "GMAIL_SEND_EMAIL", "gmail", params, native_param=NATIVE_UPLOAD_PARAM
            )
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
        with patch(f"{SHARED}.resolve_attachments_sync", return_value=resolved) as res:
            resolve_tool_attachments(
                "GMAIL_SEND_EMAIL", "gmail", params, native_param=NATIVE_UPLOAD_PARAM
            )
        # The generated model was normalised into an AttachmentReference before resolving.
        passed_refs = res.call_args.args[1]
        assert passed_refs[0].url == "https://x/y.pdf"

    def test_missing_user_id_aborts(self):
        params = {"arguments": {"attachments": [{"url": "https://x"}]}}
        with pytest.raises(HookAbortError, match="user context"):
            resolve_tool_attachments(
                "GMAIL_SEND_EMAIL", "gmail", params, native_param=NATIVE_UPLOAD_PARAM
            )

    def test_non_list_attachments_aborts(self):
        params = {"arguments": {"attachments": "not-a-list"}, "user_id": "u1"}
        with pytest.raises(HookAbortError, match="must be a list"):
            resolve_tool_attachments(
                "GMAIL_SEND_EMAIL", "gmail", params, native_param=NATIVE_UPLOAD_PARAM
            )

    def test_invalid_reference_aborts(self):
        params = {"arguments": {"attachments": [{"name": "no-source"}]}, "user_id": "u1"}
        with pytest.raises(HookAbortError, match="Invalid attachment reference"):
            resolve_tool_attachments(
                "GMAIL_SEND_EMAIL", "gmail", params, native_param=NATIVE_UPLOAD_PARAM
            )

    def test_resolver_failure_becomes_abort(self):
        params = {"arguments": {"attachments": [{"url": "https://bad"}]}, "user_id": "u1"}
        with patch(
            f"{SHARED}.resolve_attachments_sync",
            side_effect=AppError(message="upload failed", status_code=400),
        ):
            with pytest.raises(HookAbortError, match="upload failed"):
                resolve_tool_attachments(
                    "GMAIL_SEND_EMAIL", "gmail", params, native_param=NATIVE_UPLOAD_PARAM
                )


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
            f"{SHARED}.resolve_attachments_sync",
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
        with pytest.raises(HookAbortError) as exc:
            registry.execute_before_hooks("T", "tk", params)
        assert exc.value.reason == "must not run"


class TestNormalizeComposeBody:
    def test_converts_markdown_body_to_html_and_flags(self):
        args = {"body": "**hi**"}
        _normalize_compose_body(args)
        assert args["is_html"] is True
        assert args["body"] != "**hi**"  # converted to HTML
        assert "hi" in args["body"]

    def test_leaves_empty_body_but_still_flags_html(self):
        args: dict = {}
        _normalize_compose_body(args)
        assert args["is_html"] is True
        assert "body" not in args


class TestComposeRecipients:
    def test_forward_string_becomes_single_element_list(self):
        assert _compose_recipients("GMAIL_FORWARD_MESSAGE", {"to_recipients": "a@b.com"}) == [
            "a@b.com"
        ]

    def test_forward_list_passes_through(self):
        assert _compose_recipients(
            "GMAIL_FORWARD_MESSAGE", {"to_recipients": ["a@b.com", "c@d.com"]}
        ) == ["a@b.com", "c@d.com"]

    def test_compose_prepends_recipient_then_extras(self):
        assert _compose_recipients(
            "GMAIL_SEND_EMAIL",
            {"recipient_email": "r@x.com", "extra_recipients": ["e@x.com"]},
        ) == ["r@x.com", "e@x.com"]

    def test_non_list_extra_recipients_are_dropped(self):
        assert _compose_recipients(
            "GMAIL_SEND_EMAIL", {"recipient_email": "r@x.com", "extra_recipients": "oops"}
        ) == ["r@x.com"]


class TestComposeRecipientReady:
    def test_non_compose_tool_is_always_ready(self):
        assert _compose_recipient_ready("GMAIL_REPLY_TO_THREAD", {}) is True

    def test_maps_to_into_recipient_email(self):
        args = {"to": "a@b.com", "subject": "s", "body": "b"}
        assert _compose_recipient_ready("GMAIL_SEND_EMAIL", args) is True
        assert args["recipient_email"] == "a@b.com"

    def test_not_ready_without_recipient(self):
        assert _compose_recipient_ready("GMAIL_SEND_EMAIL", {"subject": "s"}) is False

    def test_not_ready_without_content(self):
        assert _compose_recipient_ready("GMAIL_SEND_EMAIL", {"recipient_email": "a@b"}) is False

    def test_cc_only_counts_as_a_recipient(self):
        assert _compose_recipient_ready("GMAIL_SEND_EMAIL", {"cc": ["a@b"], "subject": "s"}) is True


DRAFT_ARGS = {
    "recipient_email": "r@x.com",
    "extra_recipients": ["e@x.com"],
    "subject": "Subj",
    "body": "Body",
    "thread_id": "t-1",
    "bcc": ["b@x.com"],
    "cc": ["c@x.com"],
    "is_html": True,
}


class TestStreamComposePreview:
    def _capture(self):
        sent: list[dict] = []
        return sent, (lambda payload: sent.append(payload))

    def test_draft_card_is_held_back_until_its_id_exists(self):
        # Streaming it now would render a card whose Send button recomposes the
        # mail from its visible fields, silently dropping every attachment.
        sent, writer = self._capture()
        display = [{"name": "f.pdf", "mimetype": "application/pdf"}]
        with patch(f"{HOOKS}.get_stream_writer", return_value=writer):
            _stream_compose_preview("GMAIL_CREATE_EMAIL_DRAFT", DRAFT_ARGS, display)
        assert sent == []
        assert _pending_draft_card.get()["subject"] == "Subj"

    def test_after_hook_streams_the_held_card_with_every_field(self):
        sent, writer = self._capture()
        display = [{"name": "f.pdf", "mimetype": "application/pdf"}]
        with patch(f"{HOOKS}.get_stream_writer", return_value=writer):
            _stream_compose_preview("GMAIL_CREATE_EMAIL_DRAFT", DRAFT_ARGS, display)
            gmail_create_draft_after_hook(
                "GMAIL_CREATE_EMAIL_DRAFT", "gmail", {"data": {"id": "draft-1"}}
            )
        assert sent == [
            {
                "email_compose_data": [
                    {
                        "to": ["r@x.com", "e@x.com"],
                        "subject": "Subj",
                        "body": "Body",
                        "thread_id": "t-1",
                        "bcc": ["b@x.com"],
                        "cc": ["c@x.com"],
                        "is_html": True,
                        "attachments": display,
                        "draft_id": "draft-1",
                    }
                ]
            }
        ]

    def test_send_streams_under_email_sent_data_key(self):
        sent, writer = self._capture()
        with patch(f"{HOOKS}.get_stream_writer", return_value=writer):
            _stream_compose_preview(
                "GMAIL_SEND_EMAIL", {"recipient_email": "r@x.com", "subject": "s"}, []
            )
        assert list(sent[0].keys()) == ["email_sent_data"]
        assert sent[0]["email_sent_data"][0]["attachments"] == []


class TestCreateDraftAfterHook:
    def _capture(self):
        sent: list[dict] = []
        return sent, (lambda payload: sent.append(payload))

    def test_response_passes_through_untouched(self):
        sent, writer = self._capture()
        response = {"data": {"id": "d-1", "message": {"threadId": "t"}}}
        with patch(f"{HOOKS}.get_stream_writer", return_value=writer):
            _stream_compose_preview("GMAIL_CREATE_EMAIL_DRAFT", DRAFT_ARGS, [])
            assert (
                gmail_create_draft_after_hook("GMAIL_CREATE_EMAIL_DRAFT", "gmail", response)
                is response
            )

    def test_no_held_card_streams_nothing(self):
        sent, writer = self._capture()
        with patch(f"{HOOKS}.get_stream_writer", return_value=writer):
            gmail_create_draft_after_hook(
                "GMAIL_CREATE_EMAIL_DRAFT", "gmail", {"data": {"id": "d-1"}}
            )
        assert sent == []

    def test_a_card_is_streamed_once_only(self):
        sent, writer = self._capture()
        with patch(f"{HOOKS}.get_stream_writer", return_value=writer):
            _stream_compose_preview("GMAIL_CREATE_EMAIL_DRAFT", DRAFT_ARGS, [])
            gmail_create_draft_after_hook(
                "GMAIL_CREATE_EMAIL_DRAFT", "gmail", {"data": {"id": "d-1"}}
            )
            gmail_create_draft_after_hook(
                "GMAIL_CREATE_EMAIL_DRAFT", "gmail", {"data": {"id": "d-2"}}
            )
        assert len(sent) == 1

    def test_response_without_an_id_still_streams_an_attachment_free_card(self):
        # No id means no draft-send path, but with nothing to lose the card still
        # composes fine from its own fields — dropping it would cost the user
        # their compose UI for no gain.
        sent, writer = self._capture()
        with patch(f"{HOOKS}.get_stream_writer", return_value=writer):
            _stream_compose_preview("GMAIL_CREATE_EMAIL_DRAFT", DRAFT_ARGS, [])
            gmail_create_draft_after_hook("GMAIL_CREATE_EMAIL_DRAFT", "gmail", {"data": {}})
        assert "draft_id" not in sent[0]["email_compose_data"][0]

    def test_card_with_attachments_and_no_draft_id_is_not_streamed(self):
        # Every send path open to such a card recomposes the mail from its
        # visible fields, so it would go out without the files it is showing.
        sent, writer = self._capture()
        display = [{"name": "f.pdf", "mimetype": "application/pdf"}]
        with patch(f"{HOOKS}.get_stream_writer", return_value=writer):
            _stream_compose_preview("GMAIL_CREATE_EMAIL_DRAFT", DRAFT_ARGS, display)
            gmail_create_draft_after_hook("GMAIL_CREATE_EMAIL_DRAFT", "gmail", {"data": {}})
        assert sent == []

    def test_card_without_attachments_never_carries_a_draft_id(self):
        # A draft id makes the card read-only in the UI (Send sends the stored
        # draft, ignoring edits). Only a card that must be sent as the draft to
        # keep its files pays that price.
        sent, writer = self._capture()
        with patch(f"{HOOKS}.get_stream_writer", return_value=writer):
            _stream_compose_preview("GMAIL_CREATE_EMAIL_DRAFT", DRAFT_ARGS, [])
            gmail_create_draft_after_hook(
                "GMAIL_CREATE_EMAIL_DRAFT", "gmail", {"data": {"id": "d-1"}}
            )
        assert "draft_id" not in sent[0]["email_compose_data"][0]

    def test_non_dict_data_is_survived(self):
        sent, writer = self._capture()
        with patch(f"{HOOKS}.get_stream_writer", return_value=writer):
            _stream_compose_preview("GMAIL_CREATE_EMAIL_DRAFT", DRAFT_ARGS, [])
            gmail_create_draft_after_hook("GMAIL_CREATE_EMAIL_DRAFT", "gmail", {"data": "oops"})
        assert "draft_id" not in sent[0]["email_compose_data"][0]

    def test_no_writer_does_not_raise(self):
        with patch(f"{HOOKS}.get_stream_writer", return_value=None):
            _stream_compose_preview("GMAIL_CREATE_EMAIL_DRAFT", DRAFT_ARGS, [])
            gmail_create_draft_after_hook(
                "GMAIL_CREATE_EMAIL_DRAFT", "gmail", {"data": {"id": "d-1"}}
            )


class TestBeforeHookUsesTheRecordedParamName:
    """Composio names the upload param per tool; the hook must not assume one."""

    def test_resolution_writes_back_under_the_swapped_name(self):
        file_upload_hooks._swapped_upload_params["GMAIL_SEND_EMAIL"] = "file"
        params = {
            "arguments": {
                "recipient_email": "r@x.com",
                "subject": "s",
                "attachments": [{"url": "https://x/y.pdf"}],
            },
            "user_id": "u1",
        }
        resolved = [{"name": "y.pdf", "mimetype": "application/pdf", "s3key": "k/1"}]
        sent: list[dict] = []
        with (
            patch(f"{SHARED}.resolve_attachments_sync", return_value=resolved) as res,
            patch(f"{HOOKS}.get_stream_writer", return_value=sent.append),
        ):
            out = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        # The upload is attributed to the invoking tool/toolkit, which is what
        # scopes it in Composio's store.
        assert res.call_args.kwargs == {"tool": "GMAIL_SEND_EMAIL", "toolkit": "gmail"}
        assert out["arguments"]["file"] == resolved[0]
        assert "attachment" not in out["arguments"]
        assert sent[0]["email_sent_data"][0]["attachments"] == [
            {"name": "y.pdf", "mimetype": "application/pdf"}
        ]

    def test_unswapped_tool_keeps_its_own_attachments_argument(self):
        # Nothing was swapped, so `attachments` is not ours to rewrite — moving
        # it under a guessed native name would hand Gmail an argument it never
        # declared, and the file would vanish either way.
        file_upload_hooks._swapped_upload_params.clear()
        own = [{"title": "legacy block"}]
        params = {
            "arguments": {"recipient_email": "r@x.com", "subject": "s", "attachments": own},
            "user_id": "u1",
        }
        sent: list[dict] = []
        with (
            patch(f"{SHARED}.resolve_attachments_sync") as res,
            patch(f"{HOOKS}.get_stream_writer", return_value=sent.append),
        ):
            out = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        assert res.called is False
        assert out["arguments"]["attachments"] is own
        assert sent[0]["email_sent_data"][0]["attachments"] == []


class TestBeforeHookHappyPath:
    def test_resolves_normalises_and_cards_the_draft(self):
        sent: list[dict] = []
        params = {
            "arguments": {
                "to": "r@x.com",
                "subject": "Hello",
                "body": "**bold**",
                "attachments": [{"url": "https://x/y.pdf"}],
            },
            "user_id": "u1",
        }
        resolved = [{"name": "y.pdf", "mimetype": "application/pdf", "s3key": "k/1"}]
        with (
            patch(f"{SHARED}.resolve_attachments_sync", return_value=resolved),
            patch(f"{HOOKS}.get_stream_writer", return_value=sent.append),
        ):
            out = gmail_compose_before_hook("GMAIL_CREATE_EMAIL_DRAFT", "gmail", params)
            gmail_create_draft_after_hook(
                "GMAIL_CREATE_EMAIL_DRAFT", "gmail", {"data": {"id": "draft-9"}}
            )

        args = out["arguments"]
        # A single attachment collapses to one FileUploadable object.
        assert args["attachment"] == resolved[0]
        assert "attachments" not in args
        assert args["recipient_email"] == "r@x.com"  # 'to' mapped
        assert args["is_html"] is True and args["body"] != "**bold**"
        card = sent[0]["email_compose_data"][0]
        assert card["attachments"] == [{"name": "y.pdf", "mimetype": "application/pdf"}]
        assert card["subject"] == "Hello"
        # The card the user clicks Send on sends *this draft* — the only path
        # that keeps the attachment it is showing.
        assert card["draft_id"] == "draft-9"

    def test_aborted_draft_leaves_no_card_for_the_next_run(self):
        sent: list[dict] = []
        good = {
            "arguments": {"to": "r@x.com", "subject": "kept", "body": "b"},
            "user_id": "u1",
        }
        bad = {"arguments": {"subject": "no recipient"}, "user_id": "u1"}
        with patch(f"{HOOKS}.get_stream_writer", return_value=sent.append):
            gmail_compose_before_hook("GMAIL_CREATE_EMAIL_DRAFT", "gmail", good)
            gmail_compose_before_hook("GMAIL_CREATE_EMAIL_DRAFT", "gmail", bad)
            gmail_create_draft_after_hook(
                "GMAIL_CREATE_EMAIL_DRAFT", "gmail", {"data": {"id": "d-1"}}
            )
        assert sent == []

    def test_invalid_compose_call_does_not_stream(self):
        sent: list[dict] = []
        params = {"arguments": {"subject": "no recipient"}, "user_id": "u1"}
        with patch(f"{HOOKS}.get_stream_writer", return_value=sent.append):
            gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        assert sent == []


class TestComposePreviewDefaults:
    def test_missing_fields_fall_back_to_empty_defaults(self):
        # Exercises every `.get(key, default)` default so a missing field renders
        # as the empty value on the card rather than dropping out.
        sent: list[dict] = []
        with patch(f"{HOOKS}.get_stream_writer", return_value=sent.append):
            _stream_compose_preview("GMAIL_CREATE_EMAIL_DRAFT", {"recipient_email": "r@x.com"}, [])
            gmail_create_draft_after_hook("GMAIL_CREATE_EMAIL_DRAFT", "gmail", {"data": {}})
        assert sent[0]["email_compose_data"][0] == {
            "to": ["r@x.com"],
            "subject": "",
            "body": "",
            "thread_id": "",
            "bcc": [],
            "cc": [],
            "is_html": False,
            "attachments": [],
        }

    def test_recipients_default_to_empty_recipient_and_no_extras(self):
        assert _compose_recipients("GMAIL_SEND_EMAIL", {}) == [""]
        assert _compose_recipients("GMAIL_FORWARD_MESSAGE", {}) == []

    def test_empty_recipient_email_falls_back_to_to(self):
        # recipient_email present-but-empty is not remapped; the `or ...get("to")`
        # branch is what makes the call ready, so it must be exercised.
        assert (
            _compose_recipient_ready(
                "GMAIL_SEND_EMAIL", {"recipient_email": "", "to": "x@y.com", "subject": "s"}
            )
            is True
        )

    def test_recipient_ready_reads_every_recipient_field(self):
        # Each of recipient_email / to / cc / bcc independently satisfies the check.
        for field in ("recipient_email", "to", "cc", "bcc"):
            assert (
                _compose_recipient_ready("GMAIL_SEND_EMAIL", {field: "v", "subject": "s"}) is True
            )
        # Body alone (no subject) also counts as content.
        assert _compose_recipient_ready("GMAIL_SEND_EMAIL", {"to": "a", "body": "b"}) is True
