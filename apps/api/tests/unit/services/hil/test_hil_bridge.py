"""Attacks on the approval bridge (app/services/hil/bridge.py): its summaries and its decline memory.

* **Remember a decline by its ARGUMENTS.** The memory is keyed on the exact call. Too loose
  and a corrected retry ("send it to Alice instead") is auto-denied without asking; too
  strict and a verbatim retry re-prompts the user for something they just refused.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.hil import (
    APPROVAL_REQUEST_TOOL_NAME,
    HIL_SUMMARY_MAX_ARG_CHARS,
    HIL_SUMMARY_MAX_ARGS,
)
from app.models.hil_models import ApprovalLedgerDocument
from app.services.hil.bridge import (
    build_summary,
    recall_declined_call,
    remember_declined_call,
)
from app.services.hil.utils import GatedCall
from app.utils.general_utils import ELLIPSIS
from shared.py.analytics.catalog.hil import (
    ActionResult,
    ApprovalDecider,
    ApprovalOutcome,
)
from tests.helpers import ledger_facts

from .conftest import CONVERSATION_ID, STREAM_ID, USER_ID

MODULE = "app.services.hil.bridge"

TOOL_CALL = GatedCall(id="call-1", name="send_email", args={"to": "bob@example.com"})

SEPARATOR = ": "  # the colon + space between the browser-task lead-in and its task
ARG_SEPARATOR = "; "  # between a tool label and its arguments, which carry their own colons


class TestDeclineMemory:
    """Keyed on stream, tool and arguments: too loose auto-denies a correction, too strict re-asks a refusal."""

    @pytest.fixture(autouse=True)
    def redis(self):
        store: dict[str, Any] = {}

        async def _set(key: str, value: Any, ttl: int | None = None) -> None:
            store[key] = value

        async def _get(key: str) -> Any:
            return store.get(key)

        with patch(f"{MODULE}.redis_cache") as cache:
            cache.redis = MagicMock()
            cache.set = AsyncMock(side_effect=_set)
            cache.get = AsyncMock(side_effect=_get)
            yield cache

    async def test_the_same_call_is_recalled_with_the_users_own_words(self) -> None:
        args = {"to": "bob@example.com", "subject": "deck"}
        await remember_declined_call(STREAM_ID, "send_email", args, "wrong person")

        outcome = await recall_declined_call(STREAM_ID, "send_email", args)

        assert outcome is not None
        assert outcome.outcome == "denied"
        assert outcome.feedback == "wrong person"

    async def test_a_corrected_retry_is_not_auto_denied(self) -> None:
        # THE reason the key includes the arguments: "send it to Alice instead" is a
        # DIFFERENT call. Auto-denying it would make the correction impossible to carry out.
        await remember_declined_call(STREAM_ID, "send_email", {"to": "bob@example.com"}, "no")

        assert (
            await recall_declined_call(STREAM_ID, "send_email", {"to": "alice@example.com"}) is None
        )

    async def test_the_same_arguments_in_a_different_order_are_the_same_call(self) -> None:
        # Dict ordering is an artefact of how the model emitted the JSON, not a difference
        # in what is being done. Keying on it would re-prompt for an identical retry.
        await remember_declined_call(
            STREAM_ID, "send_email", {"to": "bob@example.com", "subject": "deck"}, "no"
        )

        outcome = await recall_declined_call(
            STREAM_ID, "send_email", {"subject": "deck", "to": "bob@example.com"}
        )

        assert outcome is not None

    async def test_another_tool_with_the_same_arguments_is_a_different_call(self) -> None:
        await remember_declined_call(STREAM_ID, "send_email", {"to": "bob@example.com"}, "no")

        assert (
            await recall_declined_call(STREAM_ID, "delete_email", {"to": "bob@example.com"}) is None
        )

    async def test_a_later_turn_is_not_bound_by_an_earlier_decline(self) -> None:
        # The memory is per-stream (per turn) on purpose: a genuinely new request later
        # must be able to ask again rather than inherit a refusal.
        await remember_declined_call(STREAM_ID, "send_email", {"to": "bob@example.com"}, "no")

        assert (
            await recall_declined_call("stream-2", "send_email", {"to": "bob@example.com"}) is None
        )

    async def test_a_call_never_declined_is_not_recalled(self) -> None:
        assert (
            await recall_declined_call(STREAM_ID, "send_email", {"to": "bob@example.com"}) is None
        )

    async def test_an_auto_refusal_round_trips_its_provenance(self) -> None:
        # The retry message differs ("auto declined" vs "the user declined"), so
        # the provenance must survive the Redis round trip.
        await remember_declined_call(
            STREAM_ID, "send_email", {"to": "bob@example.com"}, "stop spamming", auto=True
        )

        outcome = await recall_declined_call(STREAM_ID, "send_email", {"to": "bob@example.com"})

        assert outcome is not None
        assert outcome.decider is ApprovalDecider.AUTO
        assert outcome.feedback == "stop spamming"

    async def test_a_user_decline_still_reads_as_user_made(self) -> None:
        await remember_declined_call(STREAM_ID, "send_email", {"to": "bob@example.com"}, "no")

        outcome = await recall_declined_call(STREAM_ID, "send_email", {"to": "bob@example.com"})

        assert outcome is not None
        assert outcome.decider is ApprovalDecider.USER

    async def test_unserializable_arguments_do_not_crash_the_gate(self) -> None:
        # Tool args come from an LLM and are only loosely typed. A key derivation that
        # raises here would fail the gate closed on every call carrying an odd value.
        args = {"when": object()}
        await remember_declined_call(STREAM_ID, "send_email", args, "no")

        assert await recall_declined_call(STREAM_ID, "send_email", args) is not None


class TestSummary:
    """The one line the user reads before approving, built deterministically with no LLM on the hot path."""

    def test_the_tool_and_integration_are_both_named(self) -> None:
        summary = build_summary("send_email", {}, "Gmail")

        assert "Send email" in summary
        assert "Gmail" in summary

    def test_scalar_arguments_are_shown_so_the_user_knows_what_they_approve(self) -> None:
        summary = build_summary("send_email", {"to": "bob@example.com"}, None)

        assert "to" in summary
        assert "bob@example.com" in summary

    def test_a_long_value_is_clipped_rather_than_flooding_the_card(self) -> None:
        summary = build_summary("send_email", {"body": "x" * 500}, None)

        assert len(summary) < 200
        assert "x" * (HIL_SUMMARY_MAX_ARG_CHARS + 1) not in summary

    def test_only_a_few_arguments_are_shown(self) -> None:
        args = {f"field_{i}": f"value_{i}" for i in range(10)}

        summary = build_summary("send_email", args, None)

        shown = [name for name in args if name in summary]
        assert len(shown) == HIL_SUMMARY_MAX_ARGS

    def test_a_nested_argument_is_skipped_rather_than_dumped_into_the_card(self) -> None:
        # A raw dict/list in a one-line summary is unreadable, and an attachment payload
        # could be enormous.
        summary = build_summary(
            "send_email", {"attachments": [{"name": "secret.pdf"}], "to": "bob@example.com"}, None
        )

        assert "secret.pdf" not in summary
        assert "bob@example.com" in summary

    def test_a_call_with_no_arguments_still_reads_as_a_sentence(self) -> None:
        assert build_summary("delete_everything", {}, None) == "Delete everything"

    def test_multi_word_tool_names_get_every_underscore_swapped(self) -> None:
        assert build_summary("list_all_todos", {}, None) == "List all todos"

    def test_the_integration_name_is_parenthesized_after_the_label(self) -> None:
        assert build_summary("send_email", {}, "Gmail") == "Send email (Gmail)"

    def test_a_named_account_is_parenthesized_beside_the_integration(self) -> None:
        assert (
            build_summary("send_email", {}, "Gmail", "work@acme.com")
            == "Send email (Gmail, work@acme.com)"
        )

    def test_with_no_integration_the_label_carries_no_parentheses(self) -> None:
        assert build_summary("send_email", {}, None) == "Send email"

    def test_the_label_and_arguments_are_joined_by_a_semicolon(self) -> None:
        assert (
            build_summary("send_email", {"to": "bob"}, None) == f"Send email{ARG_SEPARATOR}to: bob"
        )

    def test_multiple_arguments_are_comma_separated_in_order(self) -> None:
        summary = build_summary("send_email", {"to": "bob", "cc": "al"}, None)

        assert summary == f"Send email{ARG_SEPARATOR}to: bob, cc: al"

    def test_an_argument_value_at_the_clip_boundary_is_shown_in_full(self) -> None:
        value = "a" * HIL_SUMMARY_MAX_ARG_CHARS

        summary = build_summary("send_email", {"note": value}, None)

        assert summary == f"Send email{ARG_SEPARATOR}note: {value}"
        assert ELLIPSIS not in summary

    def test_an_argument_value_one_over_the_boundary_is_clipped_with_an_ellipsis(self) -> None:
        value = "a" * (HIL_SUMMARY_MAX_ARG_CHARS + 1)

        summary = build_summary("send_email", {"note": value}, None)

        assert (
            summary == f"Send email{ARG_SEPARATOR}note: {'a' * HIL_SUMMARY_MAX_ARG_CHARS}{ELLIPSIS}"
        )

    def test_boolean_and_numeric_arguments_are_shown_as_scalars(self) -> None:
        summary = build_summary("set_reminder", {"urgent": True, "count": 3}, None)

        assert summary == f"Set reminder{ARG_SEPARATOR}urgent: True, count: 3"


class TestBrowserTaskSummary:
    """browser_task gets a bespoke summary: the LLM's task argument, not the tool name, so the card reads as what will happen."""

    def test_a_missing_task_argument_falls_back_to_a_generic_line(self) -> None:
        assert build_summary("browser_task", {}, None) == "Start a browser task"

    def test_a_whitespace_only_task_falls_back_to_a_generic_line(self) -> None:
        assert build_summary("browser_task", {"task": "   "}, None) == "Start a browser task"

    def test_the_task_is_stripped_of_surrounding_whitespace(self) -> None:
        summary = build_summary("browser_task", {"task": "  Book a flight  "}, None)

        assert summary == f"Start a browser task{SEPARATOR}Book a flight"

    def test_only_the_first_sentence_is_used_and_its_period_is_dropped(self) -> None:
        summary = build_summary("browser_task", {"task": "Book a flight. Then find a hotel."}, None)

        assert summary == f"Start a browser task{SEPARATOR}Book a flight"

    def test_a_task_with_no_sentence_break_is_used_whole_when_short(self) -> None:
        summary = build_summary("browser_task", {"task": "Book a flight to Tokyo"}, None)

        assert summary == f"Start a browser task{SEPARATOR}Book a flight to Tokyo"

    def test_a_lead_in_exactly_at_the_clip_boundary_is_kept_whole(self) -> None:
        task = "y" * 140  # no ". " in it, so `first` == the whole (stripped) task

        summary = build_summary("browser_task", {"task": task}, None)

        assert summary == f"Start a browser task{SEPARATOR}{task}"
        assert ELLIPSIS not in summary

    def test_a_lead_in_one_over_the_clip_boundary_is_clipped_with_an_ellipsis(self) -> None:
        task = "y" * 141

        summary = build_summary("browser_task", {"task": task}, None)

        assert summary == f"Start a browser task{SEPARATOR}{'y' * 140}{ELLIPSIS}"

    def test_a_long_task_with_no_sentence_break_is_clipped_from_the_full_task(self) -> None:
        task = "x" * 200

        summary = build_summary("browser_task", {"task": task}, None)

        assert summary == f"Start a browser task{SEPARATOR}{'x' * 140}{ELLIPSIS}"

    def test_an_empty_lead_in_before_the_first_period_falls_back_to_the_full_task(self) -> None:
        # task.split(". ", 1)[0] is "" here, so the "0 < len(first)" guard must reject
        # it and fall through to clipping the whole task, not render an empty lead-in.
        summary = build_summary("browser_task", {"task": ". rest of the task"}, None)

        assert summary == f"Start a browser task{SEPARATOR}. rest of the task"

    def test_only_the_first_period_space_is_treated_as_a_sentence_break(self) -> None:
        summary = build_summary("browser_task", {"task": "First. Second. Third."}, None)

        assert summary == f"Start a browser task{SEPARATOR}First"

    def test_a_trailing_period_with_no_further_sentence_is_dropped(self) -> None:
        # No ". " anywhere in the task, so `first` is the whole (stripped) task — only
        # the final `.rstrip(".")` removes the trailing period, not the split.
        summary = build_summary("browser_task", {"task": "Book a flight."}, None)

        assert summary == f"Start a browser task{SEPARATOR}Book a flight"

    def test_the_trailing_strip_removes_only_periods_not_other_characters(self) -> None:
        # `X` is not a character `rstrip(".")` would ever touch — this pins the exact
        # strip set against a mutant that also strips trailing `X`s.
        summary = build_summary("browser_task", {"task": "Book a flightX."}, None)

        assert summary == f"Start a browser task{SEPARATOR}Book a flightX"

    def test_a_one_character_lead_in_is_kept_not_clipped(self) -> None:
        # Pins the lower bound at `0 <`, not `1 <`: a single-character lead-in must
        # still be treated as present and used as-is, not fall through to clip_text.
        summary = build_summary("browser_task", {"task": "A. Rest of stuff here"}, None)

        assert summary == f"Start a browser task{SEPARATOR}A"

    def test_a_140_char_lead_in_from_a_longer_task_is_kept_whole(self) -> None:
        # Distinguishes `<= 140` from `< 140`: here `first` (the lead-in before the
        # first ". ") is exactly 140 chars but `task` (the fallback clip_text source)
        # is much longer, so a boundary off-by-one would clip a sentence that fits.
        task = "y" * 140 + ". additional sentence"

        summary = build_summary("browser_task", {"task": task}, None)

        assert summary == f"Start a browser task{SEPARATOR}{'y' * 140}"
        assert ELLIPSIS not in summary


class TestDeclineMemoryLegacyRecord:
    async def test_a_record_without_provenance_reads_as_the_users_own_decline(self) -> None:
        with patch(f"{MODULE}.redis_cache") as cache:
            cache.redis = MagicMock()
            cache.get = AsyncMock(return_value={"feedback": "no"})

            outcome = await recall_declined_call(STREAM_ID, "send_email", {"to": "bob"})

        assert outcome is not None
        assert outcome.decider is ApprovalDecider.USER
        assert outcome.feedback == "no"


def _card_frame(approval_id: str, *, held: bool = False, **data: object) -> dict[str, object]:
    frame: dict[str, object] = {
        "tool_data": {
            "tool_name": APPROVAL_REQUEST_TOOL_NAME,
            "data": {"approval_id": approval_id, "outcome": None, **data},
        }
    }
    if held:
        frame["_held_approval"] = True
    return frame


def _ledger_row(
    approval_id: str, state: ApprovalOutcome | ActionResult | None = None
) -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        approval_id=approval_id,
        conversation_id=CONVERSATION_ID,
        user_id=USER_ID,
        fingerprint=f"fp-{approval_id}",
        tool_name="send_email",
        summary=f"summary {approval_id}",
        **ledger_facts(state),
    )
