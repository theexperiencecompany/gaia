"""Unit tests for the bot request models in app/models/bot_models.py.

These models are the validation contract between the bot adapters (Discord,
Slack, Telegram, WhatsApp) and the bot API. The models under test carry real
behaviour: a shared ``validate_platform`` field validator and length
constraints on user-supplied strings. The response models are passive data
containers and are exercised only where they enforce a default.

================================ BEHAVIOR SPEC ================================
UNIT: app/models/bot_models.py :: BotChatRequest / CreateLinkTokenRequest /
      ResetSessionRequest (and the shared `validate_platform` field validator)

EXPECTED:
  - `validate_platform` accepts every registered Platform value and returns it
    UNCHANGED; it rejects any unregistered value with a ValueError whose message
    names the offending platform ("Invalid platform '<v>'").
  - `message` (BotChatRequest) requires 1..=32768 chars.
  - `platform_user_id` requires >=1 char on all three request models.
  - Attachment fields (`file_ids`, `file_data`) default to None and, when given,
    coerce nested dicts into FileData instances.
  - Field descriptions are part of the generated OpenAPI/JSON schema contract.

MECHANISM:
  @field_validator("platform") -> if not Platform.is_valid(v): raise ValueError(
  f"Invalid platform '{v}'") ; return v. Field(min_length=..., max_length=...,
  description=...).

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - `not` removed in the validity check -> valid platforms would raise / invalid
    would pass [validate_platform on all 3 models]
  - `return v` -> `return None`: a valid platform must round-trip to the same
    string, never None [all 3 models]
  - the ValueError message literal "Invalid platform '" emptied -> error must
    still name the platform [all 3 models]
  - min_length=1 raised to 2 -> a single-char message / platform_user_id must be
    accepted [message + platform_user_id on all 3 models]
  - max_length=32768 raised to 32769 -> a 32769-char message must be rejected
  - field description strings emptied -> the JSON schema must still carry each
    field's description (OpenAPI contract)
  - @field_validator("platform") field-name emptied -> Pydantic raises at class
    definition; the module fails to import (caught implicitly by every test that
    imports it).
  - BotConversationResponse: `messages` defaults to []; `Config.extra = "allow"`
    -> "" would drop MongoDB-only fields from the model and its dump.

EQUIVALENT MUTANTS (allowed survivors, justified): none.
  The remaining passive response models (BotAuthStatusResponse,
  CreateLinkTokenResponse, BotWorkflowsListResponse, BotWorkflowResponse,
  IntegrationInfo, BotSettingsResponse) are field-only data containers out of
  this file's target scope and are not mutated under the chosen --target-name
  set; the four targeted models above kill every mutant in their scope.
==============================================================================
"""

from pydantic import ValidationError
import pytest

from app.models.bot_models import (
    BotChatRequest,
    BotConversationResponse,
    CreateLinkTokenRequest,
    ResetSessionRequest,
)
from app.services.platform_link_service import Platform

# Every platform the validator must accept, sourced from the real enum so the
# test stays in lockstep with the production list (not a hand-copied constant).
VALID_PLATFORMS = Platform.values()
MESSAGE_MAX_LENGTH = 32768


@pytest.mark.unit
class TestValidatePlatform:
    """The shared `validate_platform` field validator on the three request models."""

    @pytest.mark.parametrize("platform", VALID_PLATFORMS)
    def test_chat_request_accepts_and_returns_each_valid_platform(self, platform: str):
        """A registered platform round-trips unchanged through the validator.

        Kills: `not` removal (valid would raise) and `return v -> return None`
        (value would come back as None instead of the platform string).
        """
        req = BotChatRequest(message="hi", platform=platform, platform_user_id="u1")
        assert req.platform == platform

    @pytest.mark.parametrize("platform", VALID_PLATFORMS)
    def test_create_link_token_accepts_and_returns_each_valid_platform(self, platform: str):
        req = CreateLinkTokenRequest(platform=platform, platform_user_id="u1")
        assert req.platform == platform

    @pytest.mark.parametrize("platform", VALID_PLATFORMS)
    def test_reset_session_accepts_and_returns_each_valid_platform(self, platform: str):
        req = ResetSessionRequest(platform=platform, platform_user_id="u1")
        assert req.platform == platform

    def test_chat_request_rejects_unknown_platform_with_named_message(self):
        """An unregistered platform raises, and the message names it.

        Kills: `not` removal (invalid would pass) and the emptied ValueError
        literal "Invalid platform '".
        """
        with pytest.raises(ValidationError) as exc:
            BotChatRequest(message="hi", platform="myspace", platform_user_id="u1")
        rendered = str(exc.value)
        assert "Invalid platform 'myspace'" in rendered

    def test_create_link_token_rejects_unknown_platform_with_named_message(self):
        with pytest.raises(ValidationError) as exc:
            CreateLinkTokenRequest(platform="myspace", platform_user_id="u1")
        assert "Invalid platform 'myspace'" in str(exc.value)

    def test_reset_session_rejects_unknown_platform_with_named_message(self):
        with pytest.raises(ValidationError) as exc:
            ResetSessionRequest(platform="myspace", platform_user_id="u1")
        assert "Invalid platform 'myspace'" in str(exc.value)


@pytest.mark.unit
class TestStringLengthConstraints:
    """min_length / max_length constraints on user-supplied strings."""

    def test_message_single_char_is_accepted(self):
        """A 1-char message satisfies min_length=1. Kills min_length 1 -> 2."""
        req = BotChatRequest(message="x", platform="discord", platform_user_id="u1")
        assert req.message == "x"

    def test_message_empty_is_rejected(self):
        """An empty message violates min_length=1."""
        with pytest.raises(ValidationError):
            BotChatRequest(message="", platform="discord", platform_user_id="u1")

    def test_message_at_max_length_is_accepted(self):
        """A message of exactly 32768 chars is accepted (the inclusive boundary)."""
        body = "x" * MESSAGE_MAX_LENGTH
        req = BotChatRequest(message=body, platform="discord", platform_user_id="u1")
        assert len(req.message) == MESSAGE_MAX_LENGTH

    def test_message_over_max_length_is_rejected(self):
        """A message of 32769 chars is rejected. Kills max_length 32768 -> 32769."""
        with pytest.raises(ValidationError):
            BotChatRequest(
                message="x" * (MESSAGE_MAX_LENGTH + 1),
                platform="discord",
                platform_user_id="u1",
            )

    def test_chat_request_single_char_platform_user_id_is_accepted(self):
        """A 1-char platform_user_id satisfies min_length=1. Kills 1 -> 2."""
        req = BotChatRequest(message="hi", platform="discord", platform_user_id="i")
        assert req.platform_user_id == "i"

    def test_chat_request_empty_platform_user_id_is_rejected(self):
        with pytest.raises(ValidationError):
            BotChatRequest(message="hi", platform="discord", platform_user_id="")

    def test_create_link_token_single_char_platform_user_id_is_accepted(self):
        req = CreateLinkTokenRequest(platform="discord", platform_user_id="i")
        assert req.platform_user_id == "i"

    def test_create_link_token_empty_platform_user_id_is_rejected(self):
        with pytest.raises(ValidationError):
            CreateLinkTokenRequest(platform="discord", platform_user_id="")

    def test_reset_session_single_char_platform_user_id_is_accepted(self):
        req = ResetSessionRequest(platform="discord", platform_user_id="i")
        assert req.platform_user_id == "i"

    def test_reset_session_empty_platform_user_id_is_rejected(self):
        with pytest.raises(ValidationError):
            ResetSessionRequest(platform="discord", platform_user_id="")


@pytest.mark.unit
class TestAttachmentFields:
    """file_ids / file_data optional attachment fields on BotChatRequest."""

    def test_attachments_default_to_none_when_omitted(self):
        req = BotChatRequest(message="hi", platform="whatsapp", platform_user_id="123")
        assert req.file_ids is None
        assert req.file_data is None

    def test_file_data_dicts_coerce_into_filedata_instances(self):
        req = BotChatRequest(
            message="please analyze",
            platform="whatsapp",
            platform_user_id="1234567890",
            file_ids=["f1", "f2"],
            file_data=[
                {
                    "fileId": "f1",
                    "url": "https://cdn.example/a.pdf",
                    "filename": "a.pdf",
                    "type": "application/pdf",
                }
            ],
        )
        assert req.file_ids == ["f1", "f2"]
        assert req.file_data is not None
        assert req.file_data[0].fileId == "f1"
        assert req.file_data[0].url == "https://cdn.example/a.pdf"


@pytest.mark.unit
class TestSchemaDescriptions:
    """Field descriptions are part of the generated OpenAPI/JSON schema contract.

    Each assertion kills the corresponding `description="..." -> ""` mutation by
    requiring the emitted schema to carry the documented description.
    """

    def test_bot_chat_request_field_descriptions(self):
        props = BotChatRequest.model_json_schema()["properties"]
        assert props["message"]["description"] == "User's message text"
        assert props["platform"]["description"] == "Platform name (discord, slack, etc.)"
        assert props["platform_user_id"]["description"] == "User's ID on the platform"
        assert props["channel_id"]["description"] == "Channel/group ID (None for DM)"
        assert (
            props["file_ids"]["description"]
            == "IDs of files attached to this message (uploaded via /api/v1/upload)."
        )
        assert props["file_data"]["description"] == (
            "Full metadata for attached files. Mirrors the web chat payload so "
            "the agent can resolve URL/filename without an extra DB lookup."
        )

    def test_create_link_token_request_field_descriptions(self):
        props = CreateLinkTokenRequest.model_json_schema()["properties"]
        assert props["platform"]["description"] == "Platform name (discord, telegram, etc.)"
        assert props["platform_user_id"]["description"] == "User's ID on the platform"
        assert props["username"]["description"] == "Username on the platform"
        assert props["display_name"]["description"] == "Display name on the platform"

    def test_reset_session_request_field_descriptions(self):
        props = ResetSessionRequest.model_json_schema()["properties"]
        assert props["platform"]["description"] == "Platform name (discord, slack, etc.)"
        assert props["platform_user_id"]["description"] == "User's ID on the platform"
        assert props["channel_id"]["description"] == "Channel/group ID (None for DM)"


@pytest.mark.unit
class TestBotConversationResponse:
    """BotConversationResponse carries two real behaviours beyond field docs:
    a `messages` default of [] and `Config.extra = "allow"` so MongoDB-only
    fields survive serialization.
    """

    def test_messages_defaults_to_empty_list(self):
        """Omitted messages default to an empty list, not None.

        Kills the `default_factory=list` description-adjacent contract and proves
        the field is list-shaped for downstream consumers.
        """
        resp = BotConversationResponse(conversation_id="c1", user_id="u1")
        assert resp.messages == []

    def test_extra_mongodb_fields_are_preserved(self):
        """`Config.extra = "allow"` keeps unknown MongoDB fields on the model and
        in its dump. Kills `extra = "allow" -> ""` (which would silently drop them).
        """
        resp = BotConversationResponse(
            conversation_id="c1",
            user_id="u1",
            mongo_only_field="kept",
        )
        assert resp.mongo_only_field == "kept"
        assert resp.model_dump()["mongo_only_field"] == "kept"

    def test_field_descriptions(self):
        """Field descriptions are part of the emitted JSON schema contract.

        Kills each `description="..." -> ""` mutation on the model's fields.
        """
        props = BotConversationResponse.model_json_schema()["properties"]
        assert props["conversation_id"]["description"] == "Conversation ID"
        assert props["user_id"]["description"] == "User ID"
        assert props["description"]["description"] == "Conversation description"
        assert props["messages"]["description"] == "List of messages"
        assert props["created_at"]["description"] == "Creation timestamp"
        assert props["updated_at"]["description"] == "Last update timestamp"
