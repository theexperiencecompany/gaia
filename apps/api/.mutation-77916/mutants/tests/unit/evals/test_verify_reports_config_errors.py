"""A misconfigured machine must not read as a clean bill of health.

Two defects, one incident. `E2B_DOMAIN` is injected empty by Infisical, so
`DevelopmentSettings` rejects it the moment a suite's loader touches app
settings. That surfaced as:

    [verify] quality: could not load cases: ValueError: quality-openui-...:
             1 validation error for DevelopmentSettings

— which blamed a named case for the machine's config, and then printed an
all-zero falsifiability report and **exited 0**. Zero cases and zero defects
look identical, so the checker everyone relies on to confirm their work
reported green on a suite it had never opened.
"""

from __future__ import annotations

import pydantic
import pytest
from scripts.evals.__main__ import _load_failure


class _Settings(pydantic.BaseModel):
    E2B_DOMAIN: str = pydantic.Field(min_length=1)


def _validation_error() -> pydantic.ValidationError:
    with pytest.raises(pydantic.ValidationError) as raised:
        _Settings(E2B_DOMAIN="")
    return raised.value


def test_a_settings_failure_is_named_as_a_configuration_error() -> None:
    message = _load_failure(_validation_error())
    assert "CONFIGURATION ERROR" in message
    assert "not a case defect" in message
    assert "E2B_DOMAIN" in message


def test_it_survives_being_wrapped_in_another_exception() -> None:
    """The real one arrived wrapped, prefixed with a case id, from quality's
    openui policy loader — so the whole cause chain has to be inspected."""
    try:
        raise ValueError("quality-openui-no-fence-greeting: boom") from _validation_error()
    except ValueError as wrapped:
        message = _load_failure(wrapped)
    assert "CONFIGURATION ERROR" in message
    assert "E2B_DOMAIN" in message


def test_a_real_case_defect_is_not_mislabelled_as_configuration() -> None:
    """Mutation guard: the classifier must still be able to say 'your cases'."""
    message = _load_failure(ValueError("quality case c-1: duplicate case id"))
    assert "CONFIGURATION ERROR" not in message
    assert "duplicate case id" in message


def test_the_openui_policy_loader_no_longer_relabels_a_settings_error() -> None:
    """Root cause: it caught bare ValueError, and ValidationError IS one."""
    from scripts.evals.suites.quality import OpenUIPolicyError, _apply_openui_policy_criteria

    with pytest.raises(OpenUIPolicyError) as raised:
        _apply_openui_policy_criteria("some-case", {"openui_policy": "not-a-direction"})
    assert "some-case" in str(raised.value), "a real policy defect must still name its case"
    assert issubclass(OpenUIPolicyError, ValueError), "callers catching ValueError must still work"
