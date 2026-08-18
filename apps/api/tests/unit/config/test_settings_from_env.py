"""``BaseAppSettings.from_env`` — the degraded-boot fallback.

When validation fails, ``from_env`` does not propagate: it logs, fills every
missing ``str``-ish field that has no env var and no non-``None`` default with
``""``, and revalidates. That second attempt is what lets the app boot with an
incomplete environment instead of dying at import.
"""

from pydantic import model_validator
import pytest

from app.config.settings import BaseAppSettings


class _LabelSettings(BaseAppSettings):
    """A settings class whose validation fails until the fallback fills it in.

    ``FALLBACK_LABEL`` defaults to ``None`` — so the loop supplies ``""`` for it
    — while the model validator rejects ``None``, which is what makes the first
    ``model_validate`` raise and the second succeed.
    """

    FALLBACK_LABEL: str | None = None

    @model_validator(mode="after")
    def _require_label(self) -> "_LabelSettings":
        if self.FALLBACK_LABEL is None:
            raise ValueError("FALLBACK_LABEL must be set")
        return self


def test_fallback_fills_missing_field_with_empty_string() -> None:
    settings = _LabelSettings.from_env()

    assert settings.FALLBACK_LABEL == ""


def test_unrecoverable_validation_error_still_raises() -> None:
    """A required field is skipped by the loop, so the retry fails the same way."""

    class _RequiredSettings(BaseAppSettings):
        MANDATORY_LABEL: str

    with pytest.raises(ValueError, match="MANDATORY_LABEL"):
        _RequiredSettings.from_env()
