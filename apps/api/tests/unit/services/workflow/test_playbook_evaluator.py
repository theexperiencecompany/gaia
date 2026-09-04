"""Resolving a playbook step's placeholders against the run that is happening.

The asymmetry is the whole point and every test here defends one half of it: a
``$last_run`` naming a tool the previous run never called is a first replay with
no history and must resolve to ``None``, while every other miss — a ``$last_run``
path the tool's recorded result lacks, an unresolvable ``$steps`` / ``$trigger``
/ ``$user`` — means the playbook is stale and must stop the run by name.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.models.playbook_models import ask_slot_key
from app.models.workflow_execution_models import RECORD_CUT_MARKER, RecordedCall
from app.services.workflow.playbook.evaluator import (
    PlaceholderError,
    PlaybookUser,
    RunContext,
    StepResult,
    _resolve_time,
    fill_ask_slots,
    last_run_index,
    resolve_args,
    resolve_value,
)

NOW = datetime(2026, 3, 14, 9, 30, tzinfo=ZoneInfo("Europe/Berlin"))


def _context(
    *,
    steps: dict[str, StepResult] | None = None,
    trigger: dict[str, object] | None = None,
    last_run: dict[str, object] | None = None,
    asks: dict[str, str] | None = None,
    user: PlaybookUser | None = None,
    now: datetime = NOW,
) -> RunContext:
    return RunContext(
        user=user or PlaybookUser(email="ada@example.com", name="Ada", timezone="Europe/Berlin"),
        now=now,
        trigger=trigger or {},
        steps=steps or {},
        last_run=last_run or {},
        asks=asks or {},
    )


def _assert_actionable(error: PlaceholderError, token: str) -> None:
    """Every placeholder failure has to name the token and say what to do next.

    The playbook author only ever sees this triple. A run that stops with a
    nameless message, or with no ``why``/``fix``, leaves them holding a dead
    workflow and no way to repair it.
    """
    assert token in error.message
    assert error.why
    assert error.fix


def test_now_and_today_render_the_workflow_zone() -> None:
    context = _context()
    assert resolve_value("$now", context) == "2026-03-14T09:30:00+01:00"
    assert resolve_value("$today", context) == "2026-03-14"


def test_now_renders_to_the_second_not_the_microsecond() -> None:
    """A worker's clock carries microseconds and some APIs reject the longer
    form as not RFC 3339; a ``$now`` and any offset on it read to the second."""
    context = _context(now=NOW.replace(microsecond=624690))
    assert resolve_value("$now", context) == "2026-03-14T09:30:00+01:00"
    assert resolve_value("$now + 1h", context) == "2026-03-14T10:30:00+01:00"


def test_time_offsets_move_forward_and_back() -> None:
    context = _context()
    assert resolve_value("$today + 1d", context) == "2026-03-15"
    assert resolve_value("$now - 2h", context) == "2026-03-14T07:30:00+01:00"


def test_a_time_offset_is_applied_only_when_both_halves_are_present() -> None:
    """Called directly, because the grammar can only ever hand this function an
    amount and a unit together — the offset group in the token regex is all or
    nothing. The guard is what keeps that a grammar detail: with half an offset
    it resolves to the plain moment, where reading either half alone would index
    the unit table with ``None`` or call ``int(None)`` and stop the run partway
    through building a tool argument.
    """
    assert _resolve_time("today", "+", None, "d", NOW) == "2026-03-14"
    assert _resolve_time("today", "+", "1", None, NOW) == "2026-03-14"
    assert _resolve_time("today", "+", "1", "d", NOW) == "2026-03-15"


def test_user_fields_resolve_from_the_profile() -> None:
    context = _context()
    assert resolve_value("$user.email", context) == "ada@example.com"
    assert resolve_value("$user.name", context) == "Ada"
    assert resolve_value("$user.timezone", context) == "Europe/Berlin"


def test_trigger_resolves_a_nested_json_path() -> None:
    context = _context(trigger={"events": [{"id": "evt_9"}]})
    assert resolve_value("$trigger.events.0.id", context) == "evt_9"


def test_steps_resolve_by_id_and_by_file() -> None:
    context = _context(
        steps={"inbox": StepResult(value={"count": 12}, file="/workspace/inbox.json")}
    )
    assert resolve_value("$steps.inbox.count", context) == 12
    assert resolve_value("$steps.inbox.file", context) == "/workspace/inbox.json"


def test_fill_ask_slots_substitutes_the_text_the_model_wrote_by_key() -> None:
    """A slot is addressed by its step and its argument path, and comes out as
    the plain text the ask call wrote. Substituting under any other key would
    leave the slot's dict standing where a tool argument belongs."""
    filled = fill_ask_slots(
        {"to": "a@b.com", "subject": {"$ask": "Write a subject line"}},
        {"mail.subject": "Here is your morning digest."},
        key_prefix="mail",
    )
    assert filled == {"to": "a@b.com", "subject": "Here is your morning digest."}


def test_last_run_resolves_a_cursor_from_the_previous_run() -> None:
    context = _context(last_run={"GMAIL_FETCH": {"next_page": "tok_2"}})
    assert resolve_value("$last_run.GMAIL_FETCH.next_page", context) == "tok_2"


def test_unresolvable_last_run_is_none_not_an_error() -> None:
    """A first replay follows an agentic run, so there is nothing to look back at."""
    context = _context(last_run={})
    assert resolve_value("$last_run.GMAIL_FETCH.next_page", context) is None
    assert resolve_value("$last_run.GMAIL_FETCH", context) is None


def test_a_whole_value_last_run_with_no_history_is_left_out_of_the_args() -> None:
    """``None`` reached a tool parameter that is not Optional and failed
    validation at call time; leaving the key out lets the tool's default apply."""
    resolved = resolve_args(
        {"page_token": "$last_run.GMAIL_FETCH.next_page", "max_results": 10}, _context()
    )
    assert resolved == {"max_results": 10}


def test_a_null_inside_a_nested_value_is_kept_as_written() -> None:
    """Only a top-level whole-value placeholder is dropped: a null nested in a
    structure is data the tool is meant to see, as is a literal null."""
    resolved = resolve_args(
        {"filter": {"cursor": "$last_run.GMAIL_FETCH.next_page"}, "label": None}, _context()
    )
    assert resolved == {"filter": {"cursor": None}, "label": None}


def test_a_last_run_path_the_tool_did_not_return_stops_the_run_by_name() -> None:
    """The previous run DID call the tool, so "not there" is not "no history":
    it is a shape the playbook expects and the tool no longer returns. Resolving
    it to ``None`` sent the tool a null cursor and silently restarted from page
    one, repeating every side effect of the run before."""
    context = _context(last_run={"GMAIL_FETCH": {"other": 1}})
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$last_run.GMAIL_FETCH.next_page", context)
    _assert_actionable(caught.value, "$last_run.GMAIL_FETCH.next_page")
    assert caught.value.message == (
        "$last_run.GMAIL_FETCH.next_page is not in what GMAIL_FETCH returned last run"
    )
    assert caught.value.why == ("the previous run's result for that tool has no value at that path")
    assert caught.value.fix == ("re-author the playbook against a run whose result has this shape")


def test_a_last_run_result_recorded_as_text_cannot_be_addressed_into() -> None:
    """A digest that was not JSON (a truncated or plain-text result) has no
    fields; addressing one must say so rather than resolve to ``None``."""
    context = _context(last_run={"GMAIL_FETCH": "12 messages, next page tok_2"})
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$last_run.GMAIL_FETCH.next_page", context)
    _assert_actionable(caught.value, "$last_run.GMAIL_FETCH.next_page")
    # A different `why` from the JSON-shaped miss above: "recorded as text" is
    # the author's cue to look at the tool's output, not at their own path.
    assert caught.value.why == (
        "that result was recorded as text, not JSON, so it has no fields to address"
    )


def test_a_last_run_value_that_is_really_null_resolves_to_none() -> None:
    """A recorded JSON ``null`` (the last page's empty cursor) is a resolved
    value, distinct from a path that is not there at all."""
    context = _context(last_run={"GMAIL_FETCH": {"next_page": None}})
    assert resolve_value("$last_run.GMAIL_FETCH.next_page", context) is None


def test_an_unknown_dollar_word_is_literal_text_whole_value_and_embedded() -> None:
    """Only the closed namespaces are placeholders. A recorded ``bash`` step
    legitimately says ``echo $HOME``, and ``$nowhere`` is not ``$now`` + text, so
    both reach the tool exactly as written rather than raising or being cut."""
    context = _context()
    assert resolve_value("$HOME", context) == "$HOME"
    assert resolve_value("echo $HOME $1", context) == "echo $HOME $1"
    assert (
        resolve_value("Email $sender.name on $today", context) == "Email $sender.name on 2026-03-14"
    )
    assert resolve_value("$nowhere", context) == "$nowhere"


def test_unresolvable_step_raises_and_names_the_placeholder() -> None:
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$steps.missing.count", _context())
    _assert_actionable(caught.value, "$steps.missing.count")
    assert caught.value.message == "$steps.missing.count points at a step that has not run"
    assert caught.value.why == "no earlier step in this replay is named 'missing'"
    assert caught.value.fix == (
        "reference a step that runs before this one, or rewrite the playbook"
    )


def test_unresolvable_step_field_raises_and_names_the_placeholder() -> None:
    context = _context(steps={"inbox": StepResult(value={"count": 12})})
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$steps.inbox.total", context)
    _assert_actionable(caught.value, "$steps.inbox.total")
    # Names the step whose result fell short, not merely "somewhere": the author
    # has to know which recorded call stopped matching reality.
    assert caught.value.message == "$steps.inbox.total is not in step 'inbox''s result"


def test_unresolvable_trigger_raises_and_names_the_placeholder() -> None:
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$trigger.email.subject", _context(trigger={"events": []}))
    _assert_actionable(caught.value, "$trigger.email.subject")
    # The whole triple, not fragments: the author is told which token, where it
    # was looked for by a name they recognise, and what to do about it.
    assert caught.value.message == "$trigger.email.subject is not in the trigger payload"
    assert caught.value.why == (
        "the value the playbook expects to read is absent from what actually came back"
    )
    assert caught.value.fix == "re-author the playbook against a run that produced this shape"


def test_empty_user_field_raises_and_names_the_placeholder() -> None:
    blank = PlaybookUser(email="", name="Ada", timezone="UTC")
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$user.email", _context(user=blank))
    assert "$user.email" in caught.value.message
    _assert_actionable(caught.value, "$user.email")


def test_whole_value_placeholder_preserves_the_resolved_type() -> None:
    context = _context(
        steps={"inbox": StepResult(value={"count": 12, "ids": ["a", "b"], "done": True})}
    )
    resolved = resolve_args(
        {
            "max_results": "$steps.inbox.count",
            "ids": "$steps.inbox.ids",
            "flag": "$steps.inbox.done",
        },
        context,
    )
    assert resolved["max_results"] == 12
    assert resolved["ids"] == ["a", "b"]
    assert resolved["flag"] is True


def test_embedded_placeholder_interpolates_into_the_surrounding_string() -> None:
    context = _context(steps={"inbox": StepResult(value={"count": 12})})
    resolved = resolve_value("Found $steps.inbox.count messages on $today", context)
    assert resolved == "Found 12 messages on 2026-03-14"


def test_embedded_unresolvable_last_run_leaves_nothing_behind() -> None:
    resolved = resolve_value("cursor=$last_run.GMAIL_FETCH.next_page", _context())
    assert resolved == "cursor="


def test_non_string_and_plain_string_values_pass_through_untouched() -> None:
    context = _context()
    resolved = resolve_args(
        {"limit": 25, "enabled": False, "ratio": 0.5, "label": "daily digest", "none": None},
        context,
    )
    assert resolved == {
        "limit": 25,
        "enabled": False,
        "ratio": 0.5,
        "label": "daily digest",
        "none": None,
    }


def test_placeholders_nested_in_lists_and_dicts_resolve() -> None:
    context = _context(trigger={"to": "team@example.com"})
    resolved = resolve_args(
        {"message": {"recipients": ["$trigger.to"], "sent_on": "$today"}}, context
    )
    assert resolved == {"message": {"recipients": ["team@example.com"], "sent_on": "2026-03-14"}}


def test_an_offset_on_a_non_time_root_is_rejected() -> None:
    """An offset silently ignored on $trigger would hand a tool the wrong window."""
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$trigger.at + 1d", _context(trigger={"at": "x"}))
    _assert_actionable(caught.value, "$trigger.at")
    assert caught.value.why == "only $now and $today take an offset"
    assert caught.value.fix == "drop the offset from $trigger"


def test_last_run_index_keeps_the_most_recent_call_per_tool() -> None:
    index = last_run_index(
        [
            RecordedCall(tool_name="GMAIL_FETCH", result_digest='{"next_page": "tok_1"}'),
            RecordedCall(tool_name="GMAIL_FETCH", result_digest='{"next_page": "tok_2"}'),
            RecordedCall(tool_name="SLACK_POST", result_digest="posted"),
        ]
    )
    assert index["GMAIL_FETCH"] == {"next_page": "tok_2"}
    assert index["SLACK_POST"] == "posted"


def test_a_field_on_a_time_root_is_rejected() -> None:
    """$now resolves to a time, so $now.hour addresses nothing.

    Letting it through would resolve to the whole timestamp under a name that
    promises one component, and the tool would silently get the wrong argument.
    """
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$now.hour", _context())
    _assert_actionable(caught.value, "$now.hour")


def test_unknown_user_field_is_rejected_and_names_the_real_ones() -> None:
    """The author has to be told the closed set, or they will keep guessing."""
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$user.phone", _context())
    _assert_actionable(caught.value, "$user.phone")
    assert caught.value.why == "$user exposes email, name, timezone and nothing else"
    assert caught.value.fix == "address one of those fields"


def test_a_slot_the_ask_call_never_wrote_stops_the_run_by_its_key() -> None:
    """A slot the model never wrote must stop the run naming the key it was
    listed under, not send the slot's dict or an empty string to the tool."""
    with pytest.raises(PlaceholderError) as caught:
        fill_ask_slots(
            {"subject": {"$ask": "Write a subject line"}},
            {"mail.body": "hi"},
            key_prefix="mail",
        )
    _assert_actionable(caught.value, "mail.subject")
    assert caught.value.message == "mail.subject was never written"
    assert caught.value.why == "the run's ask call produced no text for that slot"
    assert caught.value.fix == (
        "write one entry per slot listed, keyed exactly as the slot is listed"
    )


def test_fill_ask_slots_reaches_a_slot_nested_in_a_list_inside_a_dict() -> None:
    """Slots hide wherever an argument nests, and the key spells the whole path.

    Filling only top-level arguments would leave the raw ``{"$ask": ...}`` dict
    inside a structured payload, and the tool would receive it as data.
    """
    args = {"message": {"blocks": [{"text": {"$ask": "Write the digest body"}}]}}
    key = ask_slot_key("send", ("message", "blocks", 0, "text"))
    assert key == "send.message.blocks.0.text"

    filled = fill_ask_slots(args, {key: "Three meetings today."}, key_prefix="send")

    assert filled == {"message": {"blocks": [{"text": "Three meetings today."}]}}


def test_a_slot_that_reached_resolution_unfilled_stops_the_run() -> None:
    """``fill_ask_slots`` runs before ``resolve_args`` and leaves none behind, so
    a slot met here means the step was resolved without being filled. Passing
    the slot's dict through would send a tool ``{"$ask": ...}`` as an argument."""
    with pytest.raises(PlaceholderError) as caught:
        resolve_value({"$ask": "Write a subject line"}, _context())
    _assert_actionable(caught.value, "$ask")
    assert caught.value.message == "an $ask slot was not filled before resolution"
    # The whole triple: this is a bug in the run's own order, and the two lines
    # that say which order was skipped are the only thing pointing at it.
    assert caught.value.why == (
        "the run resolved this step's arguments without first filling its ask slots"
    )
    assert caught.value.fix == "fill the step's ask slots before resolving its arguments"


def test_dollar_ask_in_a_string_is_literal_text_not_a_placeholder() -> None:
    """``$ask`` left the placeholder vocabulary when asks moved inline: a slot is
    a value, not a reference into a table. Resolving ``$ask.body`` as a token
    again would either raise on a perfectly good literal or substitute text
    where the author wrote characters."""
    context = _context(asks={"mail.body": "Here is your digest."})
    assert resolve_value("$ask.body", context) == "$ask.body"
    assert resolve_value("Sent $ask.body today", context) == "Sent $ask.body today"


def test_a_step_placeholder_with_no_field_resolves_to_the_whole_result() -> None:
    """$steps.inbox on its own is the step's entire result, not a miss."""
    context = _context(steps={"inbox": StepResult(value={"count": 12})})
    assert resolve_value("$steps.inbox", context) == {"count": 12}


def test_nested_step_path_splits_at_the_step_id_not_the_last_dot() -> None:
    """The step id is the FIRST segment; splitting from the right would look up
    a step called ``inbox.page`` and fail a playbook that is perfectly valid."""
    context = _context(steps={"inbox": StepResult(value={"page": {"next": "tok_7"}})})
    assert resolve_value("$steps.inbox.page.next", context) == "tok_7"


def test_nested_last_run_path_splits_at_the_tool_name_not_the_last_dot() -> None:
    """Same split for $last_run, which is keyed by tool name."""
    context = _context(last_run={"GMAIL_FETCH": {"page": {"next": "tok_7"}}})
    assert resolve_value("$last_run.GMAIL_FETCH.page.next", context) == "tok_7"


def test_a_tool_name_keeps_every_leading_character() -> None:
    """Only the separating dot is stripped from a path.

    Trimming anything else would silently rename the tool, and a cursor the
    playbook depends on would resolve to None on every replay.
    """
    context = _context(last_run={"XERO_INVOICES": {"cursor": "inv_3"}})
    assert resolve_value("$last_run.XERO_INVOICES.cursor", context) == "inv_3"


def test_out_of_range_list_index_stops_the_run_by_name() -> None:
    """A stale playbook indexing past the end must raise PlaceholderError, not
    IndexError: only the named error reaches the user as something repairable."""
    context = _context(trigger={"events": [{"id": "evt_9"}]})
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$trigger.events.1.id", context)
    _assert_actionable(caught.value, "$trigger.events.1.id")


def test_non_numeric_index_into_a_list_stops_the_run_by_name() -> None:
    """A field name applied to a list is a stale playbook, not a crash."""
    context = _context(trigger={"events": [{"id": "evt_9"}]})
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$trigger.events.id", context)
    _assert_actionable(caught.value, "$trigger.events.id")


def test_indexing_into_a_scalar_stops_the_run_by_name() -> None:
    """Walking past a leaf value must fail loudly rather than resolve to None."""
    context = _context(steps={"inbox": StepResult(value={"count": 12})})
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$steps.inbox.count.0", context)
    _assert_actionable(caught.value, "$steps.inbox.count.0")


def test_embedded_structured_value_renders_as_json() -> None:
    """A dict interpolated into a prompt must arrive as JSON the model can read,
    not as Python repr with single quotes."""
    context = _context(steps={"inbox": StepResult(value={"page": {"next": "tok_7"}})})
    resolved = resolve_value("cursor=$steps.inbox.page", context)
    assert resolved == 'cursor={"next": "tok_7"}'


def test_embedded_value_that_is_not_json_serialisable_still_renders() -> None:
    """A trigger payload can carry a datetime. Rendering it must not blow up the
    run with a TypeError halfway through building a tool argument."""
    context = _context(trigger={"when": NOW})
    resolved = resolve_value("due $trigger.when", context)
    assert "2026-03-14 09:30:00+01:00" in resolved


class TestACutRecordedValueIsNotReplayed:
    def test_a_last_run_string_cut_when_stored_raises_instead_of_paging_from_nowhere(self) -> None:
        context = _context(last_run={"list_events": {"next_page_token": "abc" + RECORD_CUT_MARKER}})

        with pytest.raises(PlaceholderError) as caught:
            resolve_args({"page_token": "$last_run.list_events.next_page_token"}, context)

        # Names the argument, so the author knows which one to re-record rather
        # than being told only that "something" was cut.
        assert caught.value.message == (
            "page_token: the recorded value was cut when it was stored and cannot be replayed"
        )

    def test_a_cut_value_nested_in_a_dict_argument_raises_too(self) -> None:
        """The stub is no more replayable one level down: a cursor nested inside a
        filter object still pages from nowhere, so the top-level-only guard that
        let it through was a hole."""
        context = _context(last_run={"list_events": {"page": "abc" + RECORD_CUT_MARKER}})

        with pytest.raises(PlaceholderError) as caught:
            resolve_args({"query": {"cursor": "$last_run.list_events.page"}}, context)

        assert caught.value.message == (
            "query: the recorded value was cut when it was stored and cannot be replayed"
        )

    def test_a_cut_value_nested_in_a_list_argument_raises_too(self) -> None:
        context = _context(last_run={"list_events": {"page": "abc" + RECORD_CUT_MARKER}})

        with pytest.raises(PlaceholderError) as caught:
            resolve_args({"cursors": ["$last_run.list_events.page"]}, context)

        assert caught.value.message == (
            "cursors: the recorded value was cut when it was stored and cannot be replayed"
        )

    def test_a_cut_value_interpolated_into_a_longer_string_raises_too(self) -> None:
        """Interpolation moves the marker off the end of the string; the value is
        still a stub, so ``endswith`` was the wrong test."""
        context = _context(last_run={"list_events": {"page": "abc" + RECORD_CUT_MARKER}})

        with pytest.raises(PlaceholderError) as caught:
            resolve_args({"url": "?page=$last_run.list_events.page&limit=50"}, context)

        assert caught.value.message == (
            "url: the recorded value was cut when it was stored and cannot be replayed"
        )
