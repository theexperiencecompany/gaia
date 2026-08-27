"""Unit tests for the pure helpers and workflow assembly in intelligence_service.

These cover the parts of the onboarding DAG that hold no I/O: title truncation,
trigger mapping/serialization, prompt context rendering, and reconstruction of
persisted onboarding subdocuments. The LLM call in `_generate_workflow_specs` is
the only boundary faked here.

Production bugs found while writing these tests and fixed at the root are marked
with a "BUG:" comment.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.onboarding import NOT_SPECIFIED, OAUTH_INTEGRATION_NAME_BY_ID
from app.models.onboarding_models import (
    EmailSummary,
    InboxTriage,
    OnboardingWorkflowSummary,
    WorkflowsReadyPayload,
    WritingStyleExampleBlocks,
    WritingStyleProfile,
)
from app.models.workflow_models import SuggestedTrigger, TriggerConfig, TriggerType
from app.services.onboarding.intelligence_service import (
    _DEFAULT_WORKFLOW_CRON,
    _TODO_TITLE_MAX_CHARS,
    _WORKFLOW_SPEC_MAX_ATTEMPTS,
    OnboardingContext,
    _build_trigger_config_from_suggestion,
    _build_workflow_prompt_context,
    _find_workflow_trigger_schema,
    _generate_workflow_specs,
    _serialize_trigger_for_payload,
    _triage_from_doc,
    _truncate_title,
    _workflow_integration_ids,
    _WorkflowList,
    _WorkflowSpec,
    _writing_style_from_doc,
)

MODULE = "app.services.onboarding.intelligence_service"


def _triage(**overrides: Any) -> InboxTriage:
    payload: dict[str, Any] = {
        "total_scanned": 100,
        "total_unread": 12,
        "summary": "Busy inbox",
        "important_emails": [
            EmailSummary(sender="a@x.com", subject="Contract", why_important="deadline")
        ],
        "patterns": ["lots of newsletters"],
    }
    payload.update(overrides)
    return InboxTriage(**payload)


def _style(summary: str = "Terse and direct") -> WritingStyleProfile:
    return WritingStyleProfile(
        summary=summary,
        example=WritingStyleExampleBlocks(greeting="Hi,", body=["Thanks."], signoff="Best,"),
    )


# ---------------------------------------------------------------------------
# _truncate_title
# ---------------------------------------------------------------------------


class TestTruncateTitle:
    def test_short_title_is_untouched(self) -> None:
        assert _truncate_title("Draft the contract") == "Draft the contract"

    def test_title_exactly_at_the_limit_is_untouched(self) -> None:
        # Must contain spaces: a space-free title survives an off-by-one on the
        # length check unchanged, so it cannot detect one.
        title = " ".join(c * 8 for c in "abcdefghi")
        assert len(title) == _TODO_TITLE_MAX_CHARS

        assert _truncate_title(title) == title

    def test_one_char_over_the_limit_is_trimmed(self) -> None:
        # The boundary that decides whether truncation happens at all.
        assert len(_truncate_title("a" * (_TODO_TITLE_MAX_CHARS + 1))) == _TODO_TITLE_MAX_CHARS

    def test_trims_on_a_word_boundary(self) -> None:
        # 79 chars, so the 80-char head ends on the space before "qqqq" and the
        # whole run of complete words survives.
        head = "aaaa bbbb cccc dddd eeee ffff gggg hhhh iiii jjjj kkkk llll mmmm nnnn oooo pppp"
        assert len(head) == 79

        assert _truncate_title(f"{head} qqqq") == head

    def test_partial_word_at_the_limit_is_dropped_whole(self) -> None:
        # 87 chars: the 80-char head lands three characters into the "h" word, so
        # the result must end at the "g" word rather than keep a "hhh" fragment.
        title = " ".join(c * 10 for c in "abcdefgh")
        assert len(title) == 87

        assert _truncate_title(title) == " ".join(c * 10 for c in "abcdefg")

    def test_never_exceeds_the_limit(self) -> None:
        assert len(_truncate_title("word " * 60)) <= _TODO_TITLE_MAX_CHARS

    def test_unbroken_run_falls_back_to_a_hard_cut(self) -> None:
        # No space in the head at all — a word-boundary trim has nothing to cut on.
        assert _truncate_title("a" * 200) == "a" * _TODO_TITLE_MAX_CHARS

    # BUG: a title whose only space in the first 80 chars is the leading one made
    # `head.rsplit(" ", 1)[0]` return "", creating a todo with an empty title.
    def test_leading_space_does_not_produce_an_empty_title(self) -> None:
        out = _truncate_title(" " + "a" * 200)
        assert out != ""
        assert len(out) == _TODO_TITLE_MAX_CHARS


# ---------------------------------------------------------------------------
# _serialize_trigger_for_payload
# ---------------------------------------------------------------------------


def _trigger_wire(config: TriggerConfig) -> dict[str, Any]:
    """The trigger exactly as it reaches the client, inside `workflows_ready`."""
    payload = WorkflowsReadyPayload(
        status_text="",
        workflows=[
            OnboardingWorkflowSummary(
                id="wf_1",
                title="t",
                description="d",
                categories=[],
                trigger=_serialize_trigger_for_payload(config),
            )
        ],
    )
    return dict(payload.to_wire()["workflows"][0]["trigger"])


class TestSerializeTriggerForPayload:
    # BUG: this used `str(trigger_config.type)`. TriggerType subclasses str via
    # Enum, so str() renders "TriggerType.SCHEDULE" — while the workflow API
    # serializes the same field the frontend reads as "schedule".
    @pytest.mark.parametrize(
        "trigger_type", [TriggerType.MANUAL, TriggerType.SCHEDULE, TriggerType.INTEGRATION]
    )
    def test_type_is_the_wire_value_not_the_enum_repr(self, trigger_type: TriggerType) -> None:
        payload = _trigger_wire(TriggerConfig(type=trigger_type))

        assert payload["type"] == trigger_type.value
        assert "TriggerType" not in payload["type"]

    def test_matches_the_canonical_api_serialization(self) -> None:
        # Same field, two endpoints — the frontend types them identically.
        config = TriggerConfig(type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON)
        assert _trigger_wire(config)["type"] == config.model_dump(mode="json")["type"]

    def test_cron_expression_is_included_when_set(self) -> None:
        config = TriggerConfig(type=TriggerType.SCHEDULE, cron_expression="0 6 * * 1")
        assert _trigger_wire(config)["cron_expression"] == "0 6 * * 1"

    def test_optional_keys_are_omitted_when_unset(self) -> None:
        assert _trigger_wire(TriggerConfig(type=TriggerType.MANUAL)) == {"type": "manual"}

    def test_timezone_and_trigger_name_are_included_when_set(self) -> None:
        config = TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="GMAIL_NEW_GMAIL_MESSAGE",
            timezone="Europe/London",
        )
        payload = _trigger_wire(config)

        assert payload["trigger_name"] == "GMAIL_NEW_GMAIL_MESSAGE"
        assert payload["timezone"] == "Europe/London"


# ---------------------------------------------------------------------------
# _build_trigger_config_from_suggestion
# ---------------------------------------------------------------------------


class TestBuildTriggerConfigFromSuggestion:
    @pytest.mark.parametrize("suggestion", [None, SuggestedTrigger(type="")])
    def test_absent_suggestion_falls_back_to_the_default_schedule(
        self, suggestion: SuggestedTrigger | None
    ) -> None:
        config = _build_trigger_config_from_suggestion(suggestion)

        assert config.type is TriggerType.SCHEDULE
        assert config.cron_expression == _DEFAULT_WORKFLOW_CRON

    def test_manual_suggestion_maps_to_a_manual_trigger(self) -> None:
        config = _build_trigger_config_from_suggestion(SuggestedTrigger(type="manual"))

        assert config.type is TriggerType.MANUAL
        assert config.cron_expression is None

    def test_type_matching_is_case_insensitive(self) -> None:
        # The LLM emits "Manual"/"MANUAL" as readily as "manual".
        assert (
            _build_trigger_config_from_suggestion(SuggestedTrigger(type="MANUAL")).type
            is TriggerType.MANUAL
        )

    def test_schedule_suggestion_keeps_its_cron(self) -> None:
        config = _build_trigger_config_from_suggestion(
            SuggestedTrigger(type="schedule", cron_expression="30 7 * * 1-5")
        )

        assert config.type is TriggerType.SCHEDULE
        assert config.cron_expression == "30 7 * * 1-5"

    def test_cron_whitespace_is_stripped(self) -> None:
        config = _build_trigger_config_from_suggestion(
            SuggestedTrigger(type="schedule", cron_expression="  0 8 * * *  ")
        )
        assert config.cron_expression == "0 8 * * *"

    @pytest.mark.parametrize("cron", [None, "", "   "])
    def test_blank_cron_falls_back_to_the_default(self, cron: str | None) -> None:
        # A whitespace-only cron would otherwise be persisted and never fire.
        config = _build_trigger_config_from_suggestion(
            SuggestedTrigger(type="schedule", cron_expression=cron)
        )
        assert config.cron_expression == _DEFAULT_WORKFLOW_CRON

    def test_unknown_type_falls_back_to_the_default_schedule(self) -> None:
        config = _build_trigger_config_from_suggestion(SuggestedTrigger(type="telepathy"))

        assert config.type is TriggerType.SCHEDULE
        assert config.cron_expression == _DEFAULT_WORKFLOW_CRON

    def test_integration_without_a_trigger_name_falls_back(self) -> None:
        config = _build_trigger_config_from_suggestion(SuggestedTrigger(type="integration"))
        assert config.type is TriggerType.SCHEDULE

    def test_unknown_trigger_slug_falls_back(self) -> None:
        config = _build_trigger_config_from_suggestion(
            SuggestedTrigger(type="integration", trigger_name="NOT_A_REAL_TRIGGER")
        )
        assert config.type is TriggerType.SCHEDULE

    def test_known_config_free_slug_becomes_an_integration_trigger(self) -> None:
        slug = _a_slug_without_config_schema()
        config = _build_trigger_config_from_suggestion(
            SuggestedTrigger(type="integration", trigger_name=slug)
        )

        assert config.type is TriggerType.INTEGRATION
        assert config.trigger_name == slug

    def test_slug_needing_config_falls_back_to_a_schedule(self) -> None:
        # Those triggers need typed trigger_data this generic path cannot build;
        # registering one without it would create a trigger that never fires.
        slug = _a_slug_with_config_schema()
        config = _build_trigger_config_from_suggestion(
            SuggestedTrigger(type="integration", trigger_name=slug)
        )

        assert config.type is TriggerType.SCHEDULE
        assert config.trigger_name is None


def _a_slug_without_config_schema() -> str:
    from app.config.oauth_config import OAUTH_INTEGRATIONS

    for integration in OAUTH_INTEGRATIONS:
        for tc in integration.associated_triggers or []:
            schema = tc.workflow_trigger_schema
            if schema and not schema.config_schema:
                return str(schema.slug)
    pytest.skip("no config-free workflow trigger schema registered")


def _a_slug_with_config_schema() -> str:
    from app.config.oauth_config import OAUTH_INTEGRATIONS

    for integration in OAUTH_INTEGRATIONS:
        for tc in integration.associated_triggers or []:
            schema = tc.workflow_trigger_schema
            if schema and schema.config_schema:
                return str(schema.slug)
    pytest.skip("no config-bearing workflow trigger schema registered")


# ---------------------------------------------------------------------------
# _find_workflow_trigger_schema
# ---------------------------------------------------------------------------


class TestFindWorkflowTriggerSchema:
    def test_finds_a_registered_slug(self) -> None:
        slug = _a_slug_without_config_schema()
        schema = _find_workflow_trigger_schema(slug)

        assert schema is not None
        assert schema.slug == slug

    def test_unknown_slug_returns_none(self) -> None:
        assert _find_workflow_trigger_schema("DEFINITELY_NOT_A_SLUG") is None

    def test_lookup_is_exact_not_prefix(self) -> None:
        slug = _a_slug_without_config_schema()
        assert _find_workflow_trigger_schema(slug[:-1]) is None


# ---------------------------------------------------------------------------
# _workflow_integration_ids
# ---------------------------------------------------------------------------


class TestWorkflowIntegrationIds:
    def test_spec_categories_win_over_the_user_selection(self) -> None:
        # Writing the whole selection onto every workflow would claim Slack on a
        # Notion-only workflow.
        spec = _WorkflowSpec(title="t", description="d", categories=["notion"])
        assert _workflow_integration_ids(spec, ["slack", "gmail"]) == ["notion"]

    def test_duplicate_categories_are_collapsed_in_order(self) -> None:
        spec = _WorkflowSpec(title="t", description="d", categories=["gmail", "slack", "gmail"])
        assert _workflow_integration_ids(spec, None) == ["gmail", "slack"]

    def test_falls_back_to_the_selection_when_no_categories(self) -> None:
        spec = _WorkflowSpec(title="t", description="d", categories=[])
        assert _workflow_integration_ids(spec, ["slack"]) == ["slack"]

    def test_returns_none_when_nothing_is_known(self) -> None:
        # None, not [] — an empty list would pin the workflow to zero integrations
        # instead of leaving step generation unconstrained.
        spec = _WorkflowSpec(title="t", description="d", categories=[])
        assert _workflow_integration_ids(spec, None) is None
        assert _workflow_integration_ids(spec, []) is None


# ---------------------------------------------------------------------------
# _build_workflow_prompt_context
# ---------------------------------------------------------------------------


def _prompt(**overrides: Any) -> str:
    payload: dict[str, Any] = {
        "profession": "lawyer",
        "focus": "close the Q3 deals",
        "has_gmail": True,
        "triage": None,
        "writing_style": None,
        "clarify_answers": None,
        "selected_integrations": None,
    }
    payload.update(overrides)
    selected = payload.pop("selected_integrations")
    ctx = OnboardingContext(
        user_id="user-42",
        name="Ann",
        profession=payload["profession"],
        focus=payload["focus"],
        has_gmail=payload["has_gmail"],
        triage=payload["triage"],
        writing_style=payload["writing_style"],
        clarify_answers=payload["clarify_answers"] or [],
    )
    return _build_workflow_prompt_context(ctx, selected)


class TestBuildWorkflowPromptContext:
    def test_profession_and_focus_reach_the_prompt(self) -> None:
        out = _prompt()
        assert "lawyer" in out
        assert "close the Q3 deals" in out

    def test_blank_profession_falls_back_to_a_generic_noun(self) -> None:
        # Exact line, not a substring: "professional" appears in the template's
        # own prose, so a mangled fallback would still read as present.
        assert "- Profession: professional\n" in _prompt(profession="")

    def test_blank_focus_is_marked_not_specified(self) -> None:
        assert NOT_SPECIFIED in _prompt(focus="")

    def test_triage_patterns_and_senders_are_summarized(self) -> None:
        out = _prompt(triage=_triage())
        assert "lots of newsletters" in out
        assert "a@x.com" in out

    def test_patterns_are_capped_at_three(self) -> None:
        triage = _triage(patterns=[f"p{i}" for i in range(10)])
        out = _prompt(triage=triage)

        assert "p2" in out
        assert "p3" not in out

    def test_senders_are_capped_at_five(self) -> None:
        triage = _triage(
            important_emails=[
                EmailSummary(sender=f"s{i}@x.com", subject="s", why_important="w") for i in range(8)
            ]
        )
        out = _prompt(triage=triage)

        assert "s4@x.com" in out
        assert "s5@x.com" not in out

    def test_missing_triage_is_labelled_rather_than_left_blank(self) -> None:
        out = _prompt(triage=None)
        assert "no patterns detected" in out
        assert "no email data" in out

    def test_triage_with_empty_lists_is_labelled_too(self) -> None:
        out = _prompt(triage=_triage(patterns=[], important_emails=[]))
        assert "no patterns detected" in out
        assert "no email data" in out

    def test_writing_style_summary_is_truncated(self) -> None:
        out = _prompt(writing_style=_style("z" * 300))
        assert "z" * 150 in out
        assert "z" * 151 not in out

    def test_missing_writing_style_is_labelled(self) -> None:
        assert "- Writing style: not analyzed\n" in _prompt(writing_style=None)

    def test_clarify_answers_reach_the_prompt(self) -> None:
        """The template weights this above the inbox signals — dropping it makes
        every generated workflow generic while the prompt still renders fine."""
        out = _prompt(clarify_answers=[{"kind": "blocker", "value": "hiring is slow"}])

        assert "Clarifying context the user just shared:" in out
        assert "- Blocker: hiring is slow" in out

    def test_no_clarify_answers_renders_no_section(self) -> None:
        assert "Clarifying context" not in _prompt(clarify_answers=None)

    def test_selected_integrations_render_with_friendly_names(self) -> None:
        integration_id = next(iter(OAUTH_INTEGRATION_NAME_BY_ID))
        out = _prompt(selected_integrations=[integration_id])

        assert OAUTH_INTEGRATION_NAME_BY_ID[integration_id] in out
        assert "Preferred integrations" in out

    def test_unknown_integration_ids_are_dropped(self) -> None:
        out = _prompt(selected_integrations=["not_a_real_integration"])
        assert "not_a_real_integration" not in out
        assert "Preferred integrations" not in out

    def test_no_integration_section_when_none_selected(self) -> None:
        assert "Preferred integrations" not in _prompt(selected_integrations=None)

    @pytest.mark.parametrize("has_gmail", [True, False])
    def test_gmail_flag_is_reflected(self, has_gmail: bool) -> None:
        assert str(has_gmail) in _prompt(has_gmail=has_gmail)


# ---------------------------------------------------------------------------
# _triage_from_doc
# ---------------------------------------------------------------------------


class TestTriageFromDoc:
    def test_round_trips_a_persisted_subdoc(self) -> None:
        raw = {
            "total_scanned": 120,
            "total_unread": 9,
            "summary": "Busy",
            "patterns": ["newsletters"],
            "important_emails": [
                {"sender": "a@x.com", "subject": "Contract", "why_important": "deadline"}
            ],
        }
        triage = _triage_from_doc(raw)

        assert triage is not None
        assert triage.total_scanned == 120
        assert triage.total_unread == 9
        assert triage.summary == "Busy"
        assert triage.patterns == ["newsletters"]
        assert triage.important_emails[0].sender == "a@x.com"

    @pytest.mark.parametrize("raw", [None, "", [], 0, "a string"])
    def test_non_dict_input_yields_none(self, raw: object) -> None:
        assert _triage_from_doc(raw) is None

    def test_empty_dict_yields_a_zeroed_triage(self) -> None:
        triage = _triage_from_doc({})

        assert triage is not None
        assert triage.total_scanned == 0
        assert triage.summary == ""
        assert triage.important_emails == []

    def test_numeric_strings_are_coerced(self) -> None:
        # Mongo may hand back stringified counters from older writes.
        triage = _triage_from_doc({"total_scanned": "42", "total_unread": "7"})
        assert triage is not None
        assert triage.total_scanned == 42

    def test_null_counters_become_zero_not_none(self) -> None:
        triage = _triage_from_doc({"total_scanned": None, "total_unread": None})
        assert triage is not None
        assert (triage.total_scanned, triage.total_unread) == (0, 0)

    def test_non_dict_email_entries_are_skipped(self) -> None:
        triage = _triage_from_doc(
            {
                "important_emails": [
                    "garbage",
                    {"sender": "a@x.com", "subject": "s", "why_important": "w"},
                ]
            }
        )

        assert triage is not None
        assert len(triage.important_emails) == 1

    def test_uncoercible_counter_is_reported_as_none(self) -> None:
        # int("abc") raises ValueError — the caller must get None, not a crash.
        assert _triage_from_doc({"total_scanned": "abc"}) is None

    def test_email_entry_missing_required_fields_yields_none(self) -> None:
        assert _triage_from_doc({"important_emails": [{"sender": "a@x.com"}]}) is None

    def test_patterns_are_stringified(self) -> None:
        triage = _triage_from_doc({"patterns": [1, "two"]})
        assert triage is not None
        assert triage.patterns == ["1", "two"]


# ---------------------------------------------------------------------------
# _writing_style_from_doc
# ---------------------------------------------------------------------------


class TestWritingStyleFromDoc:
    def test_round_trips_a_persisted_subdoc(self) -> None:
        raw = {
            "summary": "Terse",
            "example": {"greeting": "Hi,", "body": ["Thanks."], "signoff": "Best,"},
            "user_edited_summary": "My own words",
        }
        style = _writing_style_from_doc(raw)

        assert style is not None
        assert style.summary == "Terse"
        assert style.example.body == ["Thanks."]
        assert style.user_edited_summary == "My own words"

    @pytest.mark.parametrize("raw", [None, "", [], "a string"])
    def test_non_dict_input_yields_none(self, raw: object) -> None:
        assert _writing_style_from_doc(raw) is None

    @pytest.mark.parametrize("summary", [None, "", "   "])
    def test_blank_summary_yields_none(self, summary: str | None) -> None:
        # A style with no summary has nothing to show the user or prompt with.
        raw = {"summary": summary, "example": {"body": ["x"]}}
        assert _writing_style_from_doc(raw) is None

    def test_summary_is_stripped(self) -> None:
        style = _writing_style_from_doc({"summary": "  Terse  ", "example": {"body": ["x"]}})
        assert style is not None
        assert style.summary == "Terse"

    @pytest.mark.parametrize("example", [None, "not a dict", []])
    def test_missing_or_malformed_example_yields_none(self, example: object) -> None:
        assert _writing_style_from_doc({"summary": "Terse", "example": example}) is None

    def test_example_failing_validation_yields_none(self) -> None:
        # body has min_length=1; an empty list must not raise out of the helper.
        assert _writing_style_from_doc({"summary": "Terse", "example": {"body": []}}) is None

    def test_absent_user_edited_summary_is_none(self) -> None:
        style = _writing_style_from_doc({"summary": "Terse", "example": {"body": ["x"]}})
        assert style is not None
        assert style.user_edited_summary is None


# ---------------------------------------------------------------------------
# _generate_workflow_specs
# ---------------------------------------------------------------------------


def _spec_list(n: int = 4) -> _WorkflowList:
    return _WorkflowList(
        workflows=[_WorkflowSpec(title=f"t{i}", description=f"d{i}") for i in range(n)]
    )


class TestGenerateWorkflowSpecs:
    async def test_returns_the_first_successful_result(self) -> None:
        expected = _spec_list()
        with patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=expected)) as llm:
            assert await _generate_workflow_specs("u1", "prompt") is expected

        assert llm.await_count == 1

    async def test_retries_until_one_attempt_succeeds(self) -> None:
        expected = _spec_list()
        llm = AsyncMock(side_effect=[ValueError("bad json"), expected])
        with patch(f"{MODULE}.ainvoke_structured", llm):
            assert await _generate_workflow_specs("u1", "prompt") is expected

        assert llm.await_count == 2

    async def test_gives_up_after_the_attempt_cap(self) -> None:
        llm = AsyncMock(side_effect=ValueError("bad json"))
        with (
            patch(f"{MODULE}.ainvoke_structured", llm),
            pytest.raises(RuntimeError, match="failed after 3 attempts"),
        ):
            await _generate_workflow_specs("u1", "prompt")

        assert llm.await_count == _WORKFLOW_SPEC_MAX_ATTEMPTS

    async def test_final_failure_keeps_the_underlying_cause(self) -> None:
        # The fallback path logs this; losing the cause makes it undiagnosable.
        cause = ValueError("bad json")
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(side_effect=cause)),
            pytest.raises(RuntimeError) as excinfo,
        ):
            await _generate_workflow_specs("u1", "prompt")

        assert excinfo.value.__cause__ is cause

    async def test_prompt_and_label_reach_the_llm(self) -> None:
        llm = AsyncMock(return_value=_spec_list())
        with patch(f"{MODULE}.ainvoke_structured", llm):
            await _generate_workflow_specs("u1", "the prompt")

        args, kwargs = llm.await_args
        assert args[0] is _WorkflowList
        assert args[1] == "the prompt"
        assert kwargs["label"] == "onboarding_workflow_suggestions"

    # BUG: the retry loop also re-checked `len(workflows) == 4` and ended with a
    # RuntimeError for "wrong count". `_WorkflowList` already pins the list to
    # exactly 4, so neither branch could ever run — a wrong count arrives as a
    # ValidationError and is retried through the normal failure path.
    @pytest.mark.parametrize("count", [0, 3, 5])
    def test_spec_list_rejects_any_count_but_four(self, count: int) -> None:
        with pytest.raises(Exception, match="workflows"):
            _spec_list(count)
