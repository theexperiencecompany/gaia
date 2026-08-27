"""The matchable-fields catalog must stay honest about the payload models.

Three properties, each of which has failed in a real trigger change before:
coverage against the live trigger list, field names that actually exist, and
declared types that match the payload model's annotation.
"""

from types import UnionType
from typing import Union, get_args, get_origin

from pydantic import BaseModel
import pytest

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.models.trigger_subscription_models import (
    OPERATORS_BY_FIELD_TYPE,
    MatchableFieldType,
    MatchableTrigger,
)
from app.services.triggers.matchable_fields import MATCHABLE_TRIGGERS, get_matchable_trigger

pytestmark = pytest.mark.unit


def _offered_trigger_names() -> set[str]:
    """Every GAIA-facing trigger name the workflow catalog publishes."""
    return {
        trigger.workflow_trigger_schema.slug
        for integration in OAUTH_INTEGRATIONS
        for trigger in integration.associated_triggers
        if trigger.workflow_trigger_schema
    }


def _unwrap_optional(annotation: object) -> object:
    """``str | None`` -> ``str``. Payload fields are optional almost everywhere."""
    if get_origin(annotation) not in (Union, UnionType):
        return annotation
    args = [a for a in get_args(annotation) if a is not type(None)]
    return args[0] if len(args) == 1 else annotation


def _resolve(model: type[BaseModel], dotted_name: str) -> object:
    """The annotation for ``dotted_name`` on ``model``, or None if it does not exist."""
    current: object = model
    for segment in dotted_name.split("."):
        if not (isinstance(current, type) and issubclass(current, BaseModel)):
            return None
        info = current.model_fields.get(segment)
        if info is None:
            return None
        current = _unwrap_optional(info.annotation)
    return current


_EXPECTED_ANNOTATION: dict[MatchableFieldType, object] = {
    MatchableFieldType.STRING: str,
    MatchableFieldType.INTEGER: int,
    MatchableFieldType.NUMBER: float,
    MatchableFieldType.STRING_LIST: list[str],
}

_CATALOG_ITEMS = sorted(MATCHABLE_TRIGGERS.items())


def _covered_prefixes(entry: MatchableTrigger) -> set[str]:
    """Top-level names reached only through a dotted child (``document.id``)."""
    named = set(entry.field_names) | set(entry.excluded)
    return {name.split(".", 1)[0] for name in named if "." in name}


class TestCatalogCoverage:
    def test_catalog_matches_the_offered_trigger_list_exactly(self) -> None:
        # Equality, not a subset: a new trigger with no catalog entry is
        # unsubscribable, and a stale entry points at a trigger nobody can fire.
        assert set(MATCHABLE_TRIGGERS) == _offered_trigger_names()

    @pytest.mark.parametrize(("trigger_name", "entry"), _CATALOG_ITEMS)
    def test_every_payload_field_is_catalogued_or_excluded(
        self, trigger_name: str, entry: MatchableTrigger
    ) -> None:
        named = set(entry.field_names) | set(entry.excluded)
        prefixes = _covered_prefixes(entry)
        unaccounted = {
            field for field in entry.payload_model.model_fields if field not in named | prefixes
        }
        assert not unaccounted, (
            f"{trigger_name}: payload fields neither matchable nor excluded: {sorted(unaccounted)}"
        )

    @pytest.mark.parametrize(("trigger_name", "entry"), _CATALOG_ITEMS)
    def test_nested_payload_fields_are_catalogued_or_excluded(
        self, trigger_name: str, entry: MatchableTrigger
    ) -> None:
        named = set(entry.field_names) | set(entry.excluded)
        for prefix in _covered_prefixes(entry):
            nested = _resolve(entry.payload_model, prefix)
            assert isinstance(nested, type) and issubclass(nested, BaseModel), (
                f"{trigger_name}: dotted names are only allowed over a typed model, "
                f"but {prefix} resolves to {nested!r}"
            )
            unaccounted = {
                f"{prefix}.{field}"
                for field in nested.model_fields
                if f"{prefix}.{field}" not in named
            }
            assert not unaccounted, (
                f"{trigger_name}: nested fields neither matchable nor excluded: "
                f"{sorted(unaccounted)}"
            )


class TestCatalogFields:
    @pytest.mark.parametrize(("trigger_name", "entry"), _CATALOG_ITEMS)
    def test_fields_exist_on_the_payload_model_with_the_declared_type(
        self, trigger_name: str, entry: MatchableTrigger
    ) -> None:
        for field in entry.fields:
            annotation = _resolve(entry.payload_model, field.name)
            assert annotation is not None, (
                f"{trigger_name}.{field.name} is not a field on {entry.payload_model.__name__}"
            )
            assert annotation == _EXPECTED_ANNOTATION[field.type], (
                f"{trigger_name}.{field.name} is declared {field.type} but the payload "
                f"model annotates it {annotation!r}"
            )

    @pytest.mark.parametrize(("trigger_name", "entry"), _CATALOG_ITEMS)
    def test_excluded_names_reference_real_payload_fields(
        self, trigger_name: str, entry: MatchableTrigger
    ) -> None:
        # An exclusion for a field that does not exist documents nothing.
        for name in entry.excluded:
            assert _resolve(entry.payload_model, name) is not None, (
                f"{trigger_name} excludes {name}, which is not a payload field"
            )

    @pytest.mark.parametrize(("trigger_name", "entry"), _CATALOG_ITEMS)
    def test_exclusion_reasons_are_present(
        self, trigger_name: str, entry: MatchableTrigger
    ) -> None:
        for name, reason in entry.excluded.items():
            assert reason.strip(), f"{trigger_name} excludes {name} with no reason"

    @pytest.mark.parametrize(("trigger_name", "entry"), _CATALOG_ITEMS)
    def test_field_names_are_unique(self, trigger_name: str, entry: MatchableTrigger) -> None:
        names = list(entry.field_names)
        assert len(names) == len(set(names)), f"{trigger_name} lists a field twice"

    @pytest.mark.parametrize(("trigger_name", "entry"), _CATALOG_ITEMS)
    def test_every_field_type_has_operators(
        self, trigger_name: str, entry: MatchableTrigger
    ) -> None:
        # A field whose type has no operators can be named but never tested.
        for field in entry.fields:
            assert OPERATORS_BY_FIELD_TYPE[field.type], (
                f"{trigger_name}.{field.name} has type {field.type} with no operators"
            )


class TestLookup:
    def test_returns_the_entry_for_a_known_trigger(self) -> None:
        entry = get_matchable_trigger("gmail_new_message")
        assert entry is not None
        assert "thread_id" in entry.field_names

    def test_returns_none_for_an_unknown_trigger(self) -> None:
        assert get_matchable_trigger("nope_not_a_trigger") is None

    def test_gmail_triggers_share_one_entry(self) -> None:
        # Both fire GMAIL_NEW_GMAIL_MESSAGE and deliver the same payload.
        assert MATCHABLE_TRIGGERS["gmail_new_message"] is MATCHABLE_TRIGGERS["gmail_poll_inbox"]

    def test_field_lookup_finds_a_catalogued_field(self) -> None:
        entry = MATCHABLE_TRIGGERS["gmail_new_message"]
        field = entry.field("thread_id")
        assert field is not None
        assert field.type is MatchableFieldType.STRING

    def test_field_lookup_misses_an_excluded_field(self) -> None:
        entry = MATCHABLE_TRIGGERS["gmail_new_message"]
        assert entry.field("payload") is None
