"""Regression: an update model must not let an explicit null reach a required document field."""

from pydantic import ValidationError
import pytest

from app.models.device_token_models import DeviceTokenUpdate, PlatformType


@pytest.mark.parametrize("field", ["platform", "is_active"])
def test_an_explicit_null_for_a_required_field_is_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        DeviceTokenUpdate.model_validate({field: None})


def test_a_null_device_id_is_allowed_to_clear_it() -> None:
    update = DeviceTokenUpdate(device_id=None)

    assert update.model_dump(exclude_unset=True) == {"device_id": None}


def test_omitted_fields_stay_out_of_the_write() -> None:
    update = DeviceTokenUpdate(platform=PlatformType.ANDROID)

    assert update.model_dump(exclude_unset=True) == {"platform": PlatformType.ANDROID}
