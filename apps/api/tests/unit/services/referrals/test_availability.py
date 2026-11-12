"""The referral program's switch: the REFERRALS flag asked for each user, and an off recorded on the wide event."""

import pytest

from app.constants.error_codes import REFERRALS_DISABLED
from app.constants.referrals import (
    REFERRALS_DISABLED_FIX,
    REFERRALS_DISABLED_MESSAGE,
    REFERRALS_DISABLED_WHY,
)
from app.services.referrals.availability import referrals_enabled, require_referrals
from app.utils.errors import AppError
from tests.helpers import captured_wide_event, referrals_off_for

ON_USER = "65f0c0ffee00000000000b01"
OFF_USER = "65f0c0ffee00000000000b02"


async def test_a_user_the_flag_is_on_for_may_refer_and_nothing_is_recorded() -> None:
    with referrals_off_for(OFF_USER):
        async with captured_wide_event() as event:
            assert await referrals_enabled(ON_USER) is True

    assert "referral" not in event


async def test_a_user_the_flag_is_off_for_may_not_and_the_event_records_it() -> None:
    with referrals_off_for(OFF_USER):
        async with captured_wide_event() as event:
            assert await referrals_enabled(OFF_USER) is False

    assert event["referral"] == {"disabled": True}


async def test_only_the_user_the_flag_is_off_for_is_refused_with_a_coded_403() -> None:
    with referrals_off_for(OFF_USER):
        await require_referrals(ON_USER)
        with pytest.raises(AppError) as refused:
            await require_referrals(OFF_USER)

    assert refused.value.status_code == 403
    assert refused.value.to_dict() == {
        "message": REFERRALS_DISABLED_MESSAGE,
        "why": REFERRALS_DISABLED_WHY,
        "fix": REFERRALS_DISABLED_FIX,
        "code": REFERRALS_DISABLED,
    }
