"""Unit tests for TriggerConfig scheduling math — the workflow next-run truth.

This is the model-level computation behind the reported bug ("daily at 9 AM" ran
in UTC). It composes Timezone.parse + cron_utils.get_next_run_time, both covered
in test_timezone.py / test_cron_utils.py; here we assert the composition.
"""

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    UpdateWorkflowRequest,
    Workflow,
)

BASE = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)  # midnight UTC
NEXT_RUN = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)


def _schedule(cron: str = "0 9 * * *", tz: str | None = None) -> TriggerConfig:
    return TriggerConfig(type=TriggerType.SCHEDULE, cron_expression=cron, timezone=tz)


class TestTriggerConfigCalculateNextRun:
    def test_daily_9am_in_kolkata_is_0330_utc(self) -> None:
        # The bug: this must NOT be 09:00 UTC.
        result = _schedule(tz="Asia/Kolkata").calculate_next_run(base_time=BASE)
        assert result == datetime(2025, 1, 1, 3, 30, tzinfo=UTC)

    def test_offset_zone_matches_iana(self) -> None:
        by_name = _schedule(tz="Asia/Kolkata").calculate_next_run(base_time=BASE)
        by_offset = _schedule(tz="+05:30").calculate_next_run(base_time=BASE)
        assert by_name == by_offset

    def test_user_timezone_param_overrides_stored(self) -> None:
        # activate/create pass an explicit user_timezone; it wins over stored.
        tc = _schedule(tz="UTC")
        result = tc.calculate_next_run(base_time=BASE, user_timezone="Asia/Kolkata")
        assert result == datetime(2025, 1, 1, 3, 30, tzinfo=UTC)

    def test_stored_timezone_used_when_no_param(self) -> None:
        result = _schedule(tz="Asia/Kolkata").calculate_next_run(base_time=BASE)
        assert (result.hour, result.minute) == (3, 30)

    def test_none_timezone_computes_in_utc(self) -> None:
        result = _schedule(tz=None).calculate_next_run(base_time=BASE)
        assert result == datetime(2025, 1, 1, 9, 0, tzinfo=UTC)

    def test_default_timezone_is_none_sentinel(self) -> None:
        # Default changed from "UTC" to None so create/update can distinguish a
        # user-chosen zone from an unset one. Omit timezone to exercise the model
        # default (not _schedule(), which passes timezone=None explicitly).
        assert TriggerConfig(type=TriggerType.SCHEDULE).timezone is None

    def test_non_schedule_trigger_returns_none(self) -> None:
        assert TriggerConfig(type=TriggerType.MANUAL).calculate_next_run(base_time=BASE) is None

    def test_no_cron_returns_none(self) -> None:
        assert TriggerConfig(type=TriggerType.SCHEDULE).calculate_next_run(base_time=BASE) is None

    def test_result_is_utc(self) -> None:
        result = _schedule(tz="America/New_York").calculate_next_run(base_time=BASE)
        assert result.tzinfo == UTC


class TestTriggerConfigUpdateNextRun:
    def test_sets_next_run_and_reports_change(self) -> None:
        tc = _schedule(tz="Asia/Kolkata")
        assert tc.next_run is None
        changed = tc.update_next_run(base_time=BASE)
        assert changed is True
        assert tc.next_run == datetime(2025, 1, 1, 3, 30, tzinfo=UTC)

    def test_no_change_reported_when_value_stable(self) -> None:
        tc = _schedule(tz="Asia/Kolkata")
        tc.update_next_run(base_time=BASE)
        # Same base + zone => same next_run => no change on the second call.
        assert tc.update_next_run(base_time=BASE) is False


class TestUpdateWorkflowRequestValidators:
    def test_description_blank_and_whitespace_coerce_to_none(self) -> None:
        assert UpdateWorkflowRequest(description="").description is None
        assert UpdateWorkflowRequest(description="   ").description is None

    def test_description_real_text_is_stripped(self) -> None:
        assert UpdateWorkflowRequest(description="  plan the week  ").description == (
            "plan the week"
        )


def _workflow(**overrides: object) -> Workflow:
    data: dict[str, object] = {
        "user_id": "user-1",
        "title": "Morning brief",
        "description": "d",
        "steps": [],
        "trigger_config": TriggerConfig(
            type=TriggerType.SCHEDULE, cron_expression="0 9 * * *", next_run=NEXT_RUN
        ),
    }
    data.update(overrides)
    return Workflow(**data)


class TestWorkflowSchedulingFieldsFromATriggerConfigModel:
    """``Workflow.__init__`` copies the trigger's schedule onto the
    BaseScheduledTask fields the scheduler actually reads. The dict form of
    ``trigger_config`` is covered by the API layer; this pins the branch taken
    when the value arrives as a ``TriggerConfig`` model — the shape every
    in-process caller passes."""

    def test_next_run_becomes_scheduled_at(self) -> None:
        assert _workflow().scheduled_at == NEXT_RUN

    def test_cron_expression_becomes_repeat(self) -> None:
        assert _workflow().repeat == "0 9 * * *"

    def test_an_explicit_scheduled_at_is_not_overwritten_by_the_trigger(self) -> None:
        """Mapping is a fallback, not an override: a workflow loaded from Mongo
        carries its own scheduled_at, and clobbering it with the trigger's
        next_run would rewind or skip the run the scheduler already booked."""
        booked = datetime(2030, 1, 1, tzinfo=UTC)
        assert _workflow(scheduled_at=booked).scheduled_at == booked

    def test_an_explicit_repeat_is_not_overwritten_by_the_trigger(self) -> None:
        assert _workflow(repeat="0 0 * * *").repeat == "0 0 * * *"

    def test_a_trigger_without_a_schedule_leaves_both_fields_unset(self) -> None:
        """Manual workflows must not look due to the recovery scan."""
        workflow = _workflow(trigger_config=TriggerConfig(type=TriggerType.MANUAL))

        assert workflow.scheduled_at is None
        assert workflow.repeat is None

    @pytest.mark.parametrize("corrupt", [None, 42, "0 9 * * *"])
    def test_a_corrupt_trigger_config_reports_as_a_validation_error(self, corrupt: object) -> None:
        """The schedule mapping runs before pydantic validates, so it reads the
        trigger defensively: a document whose trigger_config is not a config must
        surface the field-level ValidationError, not an AttributeError raised
        from inside __init__ that names nothing the caller can act on."""
        with pytest.raises(ValidationError) as excinfo:
            _workflow(trigger_config=corrupt)

        assert excinfo.value.errors()[0]["loc"] == ("trigger_config",)

    def test_a_missing_user_id_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="user_id is required for workflow creation"):
            Workflow(title="Morning brief", steps=[], trigger_config=_schedule())
