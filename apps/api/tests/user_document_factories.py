"""UserDocument sample values, apart from tests/factories.py so the conftest import chain never names the newest user models."""

from datetime import UTC, datetime

from app.config.feature_flags import FeatureFlag
from app.constants.briefing import BriefingFrequency
from app.models.briefing_models import BriefingSchedule
from app.models.first_steps_models import FirstStepsState
from app.models.notification.notification_models import QuietHours
from app.models.user_models import (
    BriefingBootstrap,
    BriefingDormancy,
    DayZeroHello,
    OnboardingSubdocument,
    ShuffleBag,
    UserDocument,
)

_USER_SAMPLE_STAMP = datetime(2024, 5, 1, tzinfo=UTC)

# One distinct non-default sample per declared UserDocument field type, matched by
# the first type name found in the field's annotation (order matters: the nested
# models are named before the primitives their annotations also mention).
_USER_SAMPLE_BY_TYPE: tuple[tuple[str, object], ...] = (
    ("OnboardingSubdocument", OnboardingSubdocument(focus="ops")),
    ("BriefingBootstrap", BriefingBootstrap(pending=True, since=_USER_SAMPLE_STAMP)),
    ("BriefingDormancy", BriefingDormancy(idle_days=2, date="2024-05-01")),
    ("DayZeroHello", DayZeroHello(sent_at=_USER_SAMPLE_STAMP, platform="telegram")),
    ("ShuffleBag", {"edition_family": ShuffleBag(order=["postal", "memo"], index=1)}),
    ("FirstStepsState", FirstStepsState(collapsed=True, collapsed_at=_USER_SAMPLE_STAMP)),
    ("QuietHours", QuietHours(start_hour=1, end_hour=6)),
    ("BriefingSchedule", BriefingSchedule(frequency=BriefingFrequency.WEEKDAYS, hour=7)),
    ("FeatureFlag", {FeatureFlag.BROWSER_OBSCURA: True}),
    ("datetime", _USER_SAMPLE_STAMP),
    ("bool", True),
    ("int", 3),
    ("list", ["item"]),
    ("dict", {"k": "v"}),
)


def user_document_sample_values() -> dict[str, object]:
    """Return a non-default value for every declared UserDocument field but id."""
    return {
        name: next(
            (
                value
                for type_name, value in _USER_SAMPLE_BY_TYPE
                if type_name in str(field.annotation)
            ),
            f"{name}-value",
        )
        for name, field in UserDocument.model_fields.items()
        if name != "id"
    }
