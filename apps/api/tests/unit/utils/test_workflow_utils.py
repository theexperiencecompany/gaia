"""Unit tests for ``app.utils.workflow_utils`` helpers."""

from app.models.workflow_models import TriggerConfig, TriggerType
from app.utils.workflow_utils import ensure_trigger_config_object


def test_dict_input_is_validated_into_a_model() -> None:
    config = ensure_trigger_config_object(
        {"type": "schedule", "cron_expression": "0 9 * * *"}
    )
    assert isinstance(config, TriggerConfig)
    assert config.type == TriggerType.SCHEDULE
    assert config.cron_expression == "0 9 * * *"


def test_model_input_passes_through_unchanged() -> None:
    config = TriggerConfig(type=TriggerType.MANUAL)
    assert ensure_trigger_config_object(config) is config
