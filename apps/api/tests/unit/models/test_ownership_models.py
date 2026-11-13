"""How a user asked to be told: a chat app they can be messaged on, or nothing."""

from pydantic import ValidationError
import pytest

from app.constants.chat import BOT_CONVERSATION_SOURCES, ConversationSource
from app.models.agent_config import AgentConfigurableView
from app.models.ownership_models import DeliveryPolicy, DeliveryTiming

pytestmark = pytest.mark.unit


class TestDeliveryPolicy:
    def test_the_default_waits_for_the_result_and_asks_nothing_of_the_user(self) -> None:
        policy = DeliveryPolicy()

        assert (policy.timing, policy.may_wake, policy.channel, policy.notify) == (
            DeliveryTiming.WHEN_DONE,
            False,
            None,
            True,
        )

    @pytest.mark.parametrize("channel", sorted(BOT_CONVERSATION_SOURCES))
    def test_any_chat_app_can_be_asked_for(self, channel: ConversationSource) -> None:
        assert DeliveryPolicy(channel=channel).channel is channel

    @pytest.mark.parametrize(
        "channel",
        [
            ConversationSource.WEB,
            ConversationSource.MOBILE,
            ConversationSource.WORKFLOW_SYSTEM,
            ConversationSource.BACKGROUND,
        ],
    )
    def test_a_surface_that_cannot_be_messaged_is_refused(
        self, channel: ConversationSource
    ) -> None:
        with pytest.raises(ValidationError, match="not a chat app"):
            DeliveryPolicy(channel=channel)

    def test_an_unknown_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            DeliveryPolicy.model_validate({"timing": "the_moment", "whenever": True})

    def test_it_survives_the_configurable_a_queued_or_resumed_run_is_rebuilt_from(self) -> None:
        policy = DeliveryPolicy(
            timing=DeliveryTiming.THE_MOMENT, may_wake=True, channel=ConversationSource.SLACK
        )

        view = AgentConfigurableView.model_validate(
            {"delivery_policy": policy.model_dump(mode="json")}
        )

        assert view.delivery_policy == policy

    def test_a_configurable_without_one_means_the_defaults(self) -> None:
        assert AgentConfigurableView.model_validate({}).delivery_policy == DeliveryPolicy()
