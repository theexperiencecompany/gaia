"""Unit tests for Pydantic model validation across chat, message, and user models."""

import pytest
from pydantic import ValidationError

from app.models.chat_models import (
    ConversationModel,
    ConversationSource,
    ImageData,
    MessageModel,
    SystemPurpose,
    UpdateMessagesRequest,
    ConversationSyncItem,
    BatchSyncRequest,
)
from app.models.message_models import (
    FileData,
    MessageRequestWithHistory,
    ReplyToMessageData,
    SelectedWorkflowData,
)
from app.models.user_models import (
    OnboardingData,
    OnboardingPhase,
    OnboardingPreferences,
    OnboardingRequest,
    UserUpdateResponse,
    BioStatus,
)
from app.models.memory_models import (
    MemoryEntry,
    MemoryRelation,
    MemorySearchResult,
    CreateMemoryRequest,
)


@pytest.mark.unit
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


@pytest.mark.unit
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
            tool_data=[
                {"tool_name": "search", "data": {"query": "test"}, "timestamp": None}
            ],
        )
        assert len(m.tool_data) == 1
        assert m.tool_data[0]["tool_name"] == "search"

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            MessageModel(type="user")

        with pytest.raises(ValidationError):
            MessageModel(response="Hello")


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestReplyToMessageData:
    def test_valid(self):
        r = ReplyToMessageData(id="msg_1", content="Original", role="user")
        assert r.id == "msg_1"

    def test_missing_fields(self):
        with pytest.raises(ValidationError):
            ReplyToMessageData(id="msg_1")


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestBatchSyncRequest:
    def test_valid(self):
        r = BatchSyncRequest(
            conversations=[
                ConversationSyncItem(
                    conversation_id="c1", last_updated="2024-01-01T00:00:00Z"
                ),
                ConversationSyncItem(conversation_id="c2"),
            ]
        )
        assert len(r.conversations) == 2
        assert r.conversations[1].last_updated is None


@pytest.mark.unit
class TestOnboardingRequest:
    def test_valid(self):
        r = OnboardingRequest(
            name="Alice",
            profession="Engineer",
            timezone="America/New_York",
        )
        assert r.name == "Alice"

    def test_invalid_name_characters(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(name="Al1ce!", profession="Engineer")

    def test_empty_name(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(name="", profession="Engineer")

    def test_name_stripped(self):
        r = OnboardingRequest(name="  Alice  ", profession="Engineer")
        assert r.name == "Alice"

    def test_invalid_profession(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(name="Alice", profession="Eng1neer!")

    # --- max_length=100 on name ---

    def test_name_at_max_length_accepted(self):
        name_100 = "A" * 100
        r = OnboardingRequest(name=name_100, profession="Engineer")
        assert r.name == name_100

    def test_name_exceeds_max_length_rejected(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(name="A" * 101, profession="Engineer")

    # --- profession max_length=50 ---

    def test_profession_at_max_length_accepted(self):
        profession_50 = "Engineer" + " " * (50 - len("Engineer"))
        r = OnboardingRequest(name="Alice", profession=profession_50)
        # validator strips, so check stripped length is within limit
        assert len(r.profession) <= 50

    def test_profession_exceeds_max_length_rejected(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(name="Alice", profession="E" * 51)

    # --- timezone validator ---

    def test_valid_timezone_accepted(self):
        r = OnboardingRequest(
            name="Alice",
            profession="Engineer",
            timezone="America/New_York",
        )
        assert r.timezone == "America/New_York"

    def test_another_valid_timezone_accepted(self):
        r = OnboardingRequest(
            name="Alice",
            profession="Engineer",
            timezone="Asia/Kolkata",
        )
        assert r.timezone == "Asia/Kolkata"

    def test_utc_timezone_accepted(self):
        r = OnboardingRequest(
            name="Alice",
            profession="Engineer",
            timezone="UTC",
        )
        assert r.timezone == "UTC"

    def test_invalid_timezone_rejected(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(
                name="Alice",
                profession="Engineer",
                timezone="not_a_timezone",
            )

    def test_invalid_timezone_random_string_rejected(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(
                name="Alice",
                profession="Engineer",
                timezone="Foo/Bar",
            )

    def test_none_timezone_accepted(self):
        r = OnboardingRequest(name="Alice", profession="Engineer", timezone=None)
        assert r.timezone is None

    def test_timezone_omitted_defaults_to_none(self):
        r = OnboardingRequest(name="Alice", profession="Engineer")
        assert r.timezone is None


@pytest.mark.unit
class TestOnboardingPreferences:
    def test_valid(self):
        p = OnboardingPreferences(
            profession="Developer",
            response_style="brief",
            custom_instructions="Be concise",
        )
        assert p.profession == "Developer"

    def test_empty_string_normalized_to_none(self):
        p = OnboardingPreferences(
            profession="", response_style="", custom_instructions=""
        )
        assert p.profession is None
        assert p.response_style is None
        assert p.custom_instructions is None

    def test_profession_too_long(self):
        with pytest.raises(ValidationError):
            OnboardingPreferences(profession="x" * 51)

    def test_custom_instructions_too_long(self):
        with pytest.raises(ValidationError):
            OnboardingPreferences(custom_instructions="x" * 501)


@pytest.mark.unit
class TestOnboardingData:
    def test_defaults(self):
        d = OnboardingData()
        assert d.completed is False
        assert d.phase == OnboardingPhase.INITIAL
        assert d.bio_status == BioStatus.PENDING
        assert d.house is None

    def test_all_phases(self):
        for phase in OnboardingPhase:
            d = OnboardingData(phase=phase)
            assert d.phase == phase


@pytest.mark.unit
class TestUserUpdateResponse:
    def test_valid(self):
        r = UserUpdateResponse(
            user_id="u1",
            name="Alice",
            email="alice@example.com",
        )
        assert r.picture is None
        assert r.selected_model is None


@pytest.mark.unit
class TestMemoryModels:
    def test_memory_entry_defaults(self):
        e = MemoryEntry(content="Test memory")
        assert e.id is None
        assert e.user_id == ""
        assert e.metadata == {}
        assert e.categories == []
        assert e.immutable is False
        assert e.relevance_score is None

    def test_memory_entry_full(self):
        e = MemoryEntry(
            id="m1",
            content="User likes Python",
            user_id="u1",
            metadata={"source": "chat"},
            categories=["preferences"],
            relevance_score=0.95,
        )
        assert e.relevance_score == 0.95
        assert e.categories == ["preferences"]

    def test_memory_relation(self):
        r = MemoryRelation(
            source="alice",
            source_type="person",
            relationship="likes",
            target="python",
            target_type="language",
        )
        assert r.source == "alice"
        assert r.relationship == "likes"

    def test_memory_relation_missing_field(self):
        with pytest.raises(ValidationError):
            MemoryRelation(source="alice", relationship="likes")

    def test_memory_search_result_defaults(self):
        r = MemorySearchResult()
        assert r.memories == []
        assert r.relations == []
        assert r.total_count == 0

    def test_create_memory_request(self):
        r = CreateMemoryRequest(content="Remember this")
        assert r.metadata is None

    def test_create_memory_request_missing_content(self):
        with pytest.raises(ValidationError):
            CreateMemoryRequest()
