"""Unit tests for Pydantic model validation across chat, message, and user models."""

from pydantic import ValidationError
import pytest

from app.models.chat_models import (
    BatchSyncRequest,
    ConversationModel,
    ConversationSource,
    ConversationSyncItem,
    ImageData,
    MessageModel,
    SourceCategory,
    SystemPurpose,
    UpdateMessagesRequest,
)
from app.models.memory_models import (
    CreateMemoryRequest,
    MemoryEntry,
    MemorySearchResult,
)
from app.models.message_models import (
    FileData,
    MessageRequestWithHistory,
    ReplyToMessageData,
    SelectedWorkflowData,
)
from app.models.user_models import (
    OnboardingNeed,
    OnboardingPreferences,
    OnboardingRequest,
    UserUpdateResponse,
)


class TestConversationModel:
    def test_valid_minimal(self):
        m = ConversationModel(conversation_id="conv_1")
        assert m.conversation_id == "conv_1"
        assert m.description == "New Chat"
        assert m.is_system_generated is False
        assert m.system_purpose is None
        assert m.is_unread is False

    def test_valid_with_all_fields(self):
        m = ConversationModel(
            conversation_id="conv_2",
            description="Work Chat",
            is_system_generated=True,
            system_purpose=SystemPurpose.EMAIL_PROCESSING,
            is_unread=True,
            source=ConversationSource.WEB,
        )
        assert m.system_purpose == SystemPurpose.EMAIL_PROCESSING
        assert m.source == ConversationSource.WEB

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            ConversationModel()

    def test_system_purpose_enum_values(self):
        assert SystemPurpose.EMAIL_PROCESSING.value == "email_processing"
        assert SystemPurpose.REMINDER_PROCESSING.value == "reminder_processing"
        assert SystemPurpose.WORKFLOW_EXECUTION.value == "workflow_execution"
        assert SystemPurpose.OTHER.value == "other"

    def test_conversation_source_enum_values(self):
        assert ConversationSource.WEB.value == "web"
        assert ConversationSource.MOBILE.value == "mobile"
        assert ConversationSource.TELEGRAM.value == "telegram"
        assert ConversationSource.DISCORD.value == "discord"
        assert ConversationSource.SLACK.value == "slack"
        assert ConversationSource.WHATSAPP.value == "whatsapp"
        assert ConversationSource.WORKFLOW_SYSTEM.value == "workflow_system"

    def test_all_conversation_source_values_accepted_in_model(self):
        for source in ConversationSource:
            m = ConversationModel(conversation_id="conv_src", source=source)
            assert m.source == source


class TestMessageModel:
    def test_valid_minimal(self):
        m = MessageModel(type="user", response="Hello")
        assert m.type == "user"
        assert m.response == "Hello"
        assert m.image_data is None
        assert m.tool_data is None

    def test_with_image_data(self):
        m = MessageModel(
            type="assistant",
            response="Here is your image",
            image_data=ImageData(url="https://img.com/1.png", prompt="a cat"),
        )
        assert m.image_data.url == "https://img.com/1.png"

    def test_with_tool_data(self):
        m = MessageModel(
            type="assistant",
            response="Done",
            tool_data=[{"tool_name": "search", "data": {"query": "test"}, "timestamp": None}],
        )
        assert len(m.tool_data) == 1
        assert m.tool_data[0]["tool_name"] == "search"

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            MessageModel(type="user")

        with pytest.raises(ValidationError):
            MessageModel(response="Hello")


class TestFileData:
    def test_valid_minimal(self):
        f = FileData(fileId="f1", url="https://files.com/1", filename="doc.pdf")
        assert f.type == "file"
        assert f.message == "File uploaded successfully"

    def test_custom_type(self):
        f = FileData(
            fileId="f1",
            url="https://files.com/1",
            filename="img.png",
            type="image",
        )
        assert f.type == "image"


class TestSelectedWorkflowData:
    def test_valid(self):
        w = SelectedWorkflowData(
            id="wf_1",
            title="My Workflow",
            description="Does things",
            steps=[{"name": "step1", "action": "do"}],
        )
        assert w.id == "wf_1"
        assert len(w.steps) == 1

    def test_missing_steps(self):
        with pytest.raises(ValidationError):
            SelectedWorkflowData(
                id="wf_1",
                title="My Workflow",
                description="Does things",
            )


class TestReplyToMessageData:
    def test_valid(self):
        r = ReplyToMessageData(id="msg_1", content="Original", role="user")
        assert r.id == "msg_1"

    def test_missing_fields(self):
        with pytest.raises(ValidationError):
            ReplyToMessageData(id="msg_1")


class TestMessageRequestWithHistory:
    def test_valid(self):
        m = MessageRequestWithHistory(
            message="Hello",
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert m.message == "Hello"
        assert len(m.messages) == 1
        assert m.fileIds == []

    def test_missing_messages(self):
        with pytest.raises(ValidationError):
            MessageRequestWithHistory(message="Hello")


class TestUpdateMessagesRequest:
    def test_valid(self):
        r = UpdateMessagesRequest(
            conversation_id="conv_1",
            messages=[
                MessageModel(type="user", response="Hey"),
            ],
        )
        assert r.conversation_id == "conv_1"
        assert len(r.messages) == 1


class TestBatchSyncRequest:
    def test_valid(self):
        r = BatchSyncRequest(
            conversations=[
                ConversationSyncItem(conversation_id="c1", last_updated="2024-01-01T00:00:00Z"),
                ConversationSyncItem(conversation_id="c2"),
            ]
        )
        assert len(r.conversations) == 2
        assert r.conversations[1].last_updated is None


class TestOnboardingRequest:
    def test_valid(self):
        r = OnboardingRequest(
            profession="Engineer",
            needs=["inbox", "calendar"],
            timezone="America/New_York",
        )
        assert r.profession == "Engineer"
        assert [n.value for n in r.needs] == ["inbox", "calendar"]

    def test_multiline_profession_rejected(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(profession="Eng\nineer", needs=["inbox"])

    def test_profession_without_a_letter_rejected(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(profession="12345", needs=["inbox"])

    def test_profession_written_as_a_sentence_accepted(self):
        r = OnboardingRequest(profession="I'm a founder, designer & dad", needs=["inbox"])
        assert r.profession == "I'm a founder, designer & dad"

    def test_preferences_and_request_share_the_profession_rule(self):
        """The two models once disagreed and the wizard hung on the stricter one."""
        typed = "I'm a founder, designer & dad"
        assert OnboardingPreferences(profession=typed).profession == typed
        with pytest.raises(ValidationError):
            OnboardingPreferences(profession="Eng\nineer")

    def test_typed_need_alone_answers_q2(self):
        r = OnboardingRequest(profession="Founder", other_need=" chasing invoices ")
        assert r.needs == []
        assert r.other_need == "chasing invoices"

    def test_no_q2_answer_rejected(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(profession="Founder", needs=[], other_need="  ")

    def test_empty_profession(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(profession="", needs=["inbox"])

    def test_profession_stripped(self):
        r = OnboardingRequest(profession="  Engineer  ", needs=["inbox"])
        assert r.profession == "Engineer"

    def test_profession_at_max_length_accepted(self):
        profession_50 = "Engineer" + " " * (50 - len("Engineer"))
        r = OnboardingRequest(profession=profession_50, needs=["inbox"])
        assert len(r.profession) <= 50

    def test_profession_exceeds_max_length_rejected(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(profession="E" * 51, needs=["inbox"])

    # --- needs (Q2) ---

    def test_needs_required(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(profession="Engineer")

    def test_empty_needs_rejected(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(profession="Engineer", needs=[])

    def test_unknown_need_rejected(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(profession="Engineer", needs=["world_peace"])

    def test_duplicate_needs_deduped_in_order(self):
        r = OnboardingRequest(profession="Engineer", needs=["todos", "inbox", "todos"])
        assert [n.value for n in r.needs] == ["todos", "inbox"]

    def test_a_name_is_not_part_of_the_contract(self):
        """The name is derived from the email server-side; an extra key is ignored."""
        r = OnboardingRequest(profession="Engineer", needs=["inbox"], name="Mallory")
        assert not hasattr(r, "name")

    # --- timezone validator ---

    def test_valid_timezone_accepted(self):
        r = OnboardingRequest(profession="Engineer", needs=["inbox"], timezone="America/New_York")
        assert r.timezone == "America/New_York"

    def test_invalid_timezone_rejected(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(profession="Engineer", needs=["inbox"], timezone="Mars/Phobos")

    def test_none_timezone_accepted(self):
        r = OnboardingRequest(profession="Engineer", needs=["inbox"], timezone=None)
        assert r.timezone is None

    def test_timezone_omitted_defaults_to_none(self):
        r = OnboardingRequest(profession="Engineer", needs=["inbox"])
        assert r.timezone is None


class TestOnboardingPreferences:
    def test_valid(self):
        p = OnboardingPreferences(
            profession="Developer",
            response_style="brief",
            custom_instructions="Be concise",
        )
        assert p.profession == "Developer"

    def test_empty_string_normalized_to_none(self):
        p = OnboardingPreferences(profession="", response_style="", custom_instructions="")
        assert p.profession is None
        assert p.response_style is None
        assert p.custom_instructions is None

    def test_profession_too_long(self):
        with pytest.raises(ValidationError):
            OnboardingPreferences(profession="x" * 51)

    def test_custom_instructions_too_long(self):
        with pytest.raises(ValidationError):
            OnboardingPreferences(custom_instructions="x" * 501)

    def test_needs_default_to_none(self):
        assert OnboardingPreferences(profession="Developer").needs is None

    def test_needs_accept_the_allowed_keys(self):
        p = OnboardingPreferences(needs=["inbox", "calendar", "reach"])
        assert p.needs == [
            OnboardingNeed.INBOX,
            OnboardingNeed.CALENDAR,
            OnboardingNeed.REACH,
        ]
        assert p.model_dump()["needs"] == ["inbox", "calendar", "reach"]

    def test_needs_reject_an_unknown_key(self):
        with pytest.raises(ValidationError):
            OnboardingPreferences(needs=["inbox", "telepathy"])


class TestUserUpdateResponse:
    def test_valid(self):
        r = UserUpdateResponse(
            user_id="u1",
            name="Alice",
            email="alice@example.com",
        )
        assert r.picture is None


class TestMemoryModels:
    def test_memory_entry_defaults(self):
        e = MemoryEntry(content="Test memory")
        assert e.id is None
        assert e.category_path == ""
        assert e.is_latest is True
        assert e.is_forgotten is False
        assert e.relevance_score is None

    def test_memory_entry_full(self):
        e = MemoryEntry(
            id="m1",
            content="User likes Python",
            category_path="preferences",
            relevance_score=0.95,
        )
        assert e.relevance_score == 0.95
        assert e.category_path == "preferences"

    def test_memory_search_result_defaults(self):
        r = MemorySearchResult()
        assert r.memories == []
        assert r.total_count == 0

    def test_create_memory_request(self):
        r = CreateMemoryRequest(content="Remember this")
        assert r.category_path is None

    def test_create_memory_request_missing_content(self):
        with pytest.raises(ValidationError):
            CreateMemoryRequest()


class TestConversationSourceCoerce:
    """ConversationSource.coerce parses raw values into the enum (or None)."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("whatsapp", ConversationSource.WHATSAPP),
            ("web", ConversationSource.WEB),
            ("background", ConversationSource.BACKGROUND),
            (ConversationSource.SLACK, ConversationSource.SLACK),
        ],
    )
    def test_valid_values_coerce_to_enum(self, raw, expected):
        assert ConversationSource.coerce(raw) is expected

    @pytest.mark.parametrize("raw", [None, "", "nonsense", "gmail"])
    def test_invalid_values_return_none(self, raw):
        assert ConversationSource.coerce(raw) is None


class TestSourceCategoryFromSource:
    """SourceCategory.from_source maps a specific channel to its category."""

    @pytest.mark.parametrize(
        "source,category",
        [
            ("web", SourceCategory.UI),
            ("mobile", SourceCategory.UI),
            ("whatsapp", SourceCategory.BOT),
            ("telegram", SourceCategory.BOT),
            ("discord", SourceCategory.BOT),
            ("slack", SourceCategory.BOT),
            (ConversationSource.WHATSAPP, SourceCategory.BOT),
            ("workflow_system", SourceCategory.BG),
            ("background", SourceCategory.BG),
            (None, SourceCategory.BG),
            ("nonsense", SourceCategory.BG),
        ],
    )
    def test_category_mapping(self, source, category):
        assert SourceCategory.from_source(source) is category
