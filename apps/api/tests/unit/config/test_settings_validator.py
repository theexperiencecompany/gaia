"""The registered settings groups, exercised through a fresh validator.

The module-level ``settings_validator`` singleton registers its groups at
import time, so nothing that only imports the module ever runs the
registration again. These tests construct their own validator, which is what
makes the registration observable at all — and what lets the mutation gate
reach a verdict on it.
"""

from types import SimpleNamespace

from app.config.settings import CommonSettings
from app.config.settings_validator import SettingsGroup, SettingsValidator
from tests.helpers import captured_wide_event

POSTHOG_GROUP = "Posthog Analytics"
POSTHOG_FIELDS = {name for name in CommonSettings.model_fields if name.startswith("POSTHOG_")}


def _missing_keys(
    missing: list[tuple[SettingsGroup, list[str]]], group_name: str
) -> list[str] | None:
    for group, keys in missing:
        if group.name == group_name:
            return keys
    return None


def test_a_configured_posthog_is_not_reported_missing() -> None:
    """The group's keys must be the settings attribute names verbatim: a key
    that never matches an attribute leaves the group reported missing however
    the app is configured."""
    settings_obj = SimpleNamespace(**dict.fromkeys(POSTHOG_FIELDS, "set"))

    missing = SettingsValidator().validate_settings(settings_obj)

    assert _missing_keys(missing, POSTHOG_GROUP) is None


def test_an_unconfigured_posthog_reports_every_posthog_setting() -> None:
    missing = SettingsValidator().validate_settings(SimpleNamespace())

    assert set(_missing_keys(missing, POSTHOG_GROUP) or []) == POSTHOG_FIELDS


async def test_missing_posthog_is_not_warned_about_in_production() -> None:
    """Analytics is optional in production — a missing token must not raise a
    CRITICAL on every boot, while a genuinely required group still does."""
    validator = SettingsValidator()
    validator.configure(show_warnings=True, is_production=True)
    validator.validate_settings(SimpleNamespace())

    async with captured_wide_event() as event:
        validator.log_validation_results()

    warned = {warning["group_name"] for warning in event["warnings"]}
    assert POSTHOG_GROUP not in warned
    assert "MongoDB Connection" in warned


async def test_missing_posthog_is_warned_about_outside_production() -> None:
    validator = SettingsValidator()
    validator.configure(show_warnings=True, is_production=False)
    validator.validate_settings(SimpleNamespace())

    async with captured_wide_event() as event:
        validator.log_validation_results()

    posthog_warnings = [w for w in event["warnings"] if w["group_name"] == POSTHOG_GROUP]
    assert [set(w["missing_keys"]) for w in posthog_warnings] == [POSTHOG_FIELDS]
