"""The registration-scope catalog: which fields a trigger accepts and needs.

The required set is what stops a per-resource watch registering against nothing,
so it is checked field by field, and a drift guard proves every required name is
a real field on its config class.
"""

from typing import get_args

import pytest

from app.models.trigger_configs import (
    GitHubPrEventConfig,
    GmailNewMessageConfig,
    TriggerConfigData,
)
from app.services.triggers.scope_catalog import (
    REQUIRED_SCOPE,
    TRIGGER_CONFIG_CLASSES,
    ScopeField,
    _config_classes,
    _scope_type_label,
    scope_fields_for,
)

pytestmark = pytest.mark.unit


class TestConfigClasses:
    """_config_classes maps every trigger name to the class that declares it."""

    def test_it_maps_each_trigger_name_to_its_owning_config_class(self) -> None:
        classes = _config_classes()

        assert classes["github_pr_event"] is GitHubPrEventConfig
        assert classes["gmail_new_message"] is GmailNewMessageConfig

    def test_it_covers_every_union_member(self) -> None:
        # One entry per config class; a wrong index or an early return would drop some.
        member_count = len(get_args(get_args(TriggerConfigData)[0]))
        assert len(_config_classes()) == member_count


class TestScopeTypeLabel:
    def test_a_list_annotation_is_list_of_text(self) -> None:
        assert _scope_type_label(list[str]) == "list of text"

    def test_an_int_is_integer_and_a_bool_is_boolean_and_a_str_is_text(self) -> None:
        assert _scope_type_label(int) == "integer"
        assert _scope_type_label(bool) == "true/false"
        assert _scope_type_label(str) == "text"

    def test_an_unknown_annotation_falls_back_to_text(self) -> None:
        # float is neither a list origin nor in the label table, so it hits the default.
        assert _scope_type_label(float) == "text"


class TestScopeFieldsFor:
    def test_a_per_resource_trigger_returns_its_required_field(self) -> None:
        assert scope_fields_for("github_pr_event") == (
            ScopeField(
                name="repos",
                type="list of text",
                description="List of repositories in owner/repo format",
                required=True,
            ),
        )

    def test_an_account_level_trigger_has_no_scope_fields(self) -> None:
        assert scope_fields_for("gmail_new_message") == ()

    def test_an_unknown_trigger_has_no_scope_fields(self) -> None:
        assert scope_fields_for("not_a_trigger") == ()

    def test_scalar_and_boolean_and_list_fields_get_distinct_type_labels(self) -> None:
        # calendar carries all three shapes, so it exercises every _scope_type_label arm.
        by_name = {f.name: f for f in scope_fields_for("calendar_event_starting_soon")}

        assert by_name["calendar_ids"].type == "list of text"
        assert by_name["minutes_before_start"].type == "integer"
        assert by_name["include_all_day"].type == "true/false"

    def test_a_string_field_is_labelled_text(self) -> None:
        (team_id,) = scope_fields_for("linear_issue_created")

        assert team_id.type == "text"

    def test_only_the_required_fields_are_marked_required(self) -> None:
        # A trigger with an optional field alongside a required one must not mark
        # the optional one (sheets: spreadsheet_ids required, sheet_names not).
        by_name = {f.name: f for f in scope_fields_for("google_sheets_new_row")}

        assert by_name["spreadsheet_ids"].required is True
        assert by_name["sheet_names"].required is False


class TestRequiredScopeIntegrity:
    def test_every_required_field_exists_on_its_config_class(self) -> None:
        # A required name that is not a real field would silently never be enforced.
        for trigger_name, required in REQUIRED_SCOPE.items():
            config_class = TRIGGER_CONFIG_CLASSES[trigger_name]
            fields = set(config_class.model_fields) - {"trigger_name"}
            assert required <= fields, f"{trigger_name}: {required - fields} not on the config"

    def test_the_config_class_map_covers_a_known_trigger(self) -> None:
        assert "github_pr_event" in TRIGGER_CONFIG_CLASSES
        assert TRIGGER_CONFIG_CLASSES["github_pr_event"].__name__ == "GitHubPrEventConfig"
