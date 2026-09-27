"""After-hooks reshape only a successful call's data; the caller always gets the {data, successful, error} envelope."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

from composio import after_execute
from composio.core.models._modifiers import apply_modifier_by_type
from composio.types import ToolExecutionResponse
import pytest

from app.agents.core.subagents.call_record import is_error_envelope
from app.utils.composio_hooks.registry import hook_registry, master_after_execute_hook
from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

HOOKED_TOOLS = frozenset(
    {
        "GMAIL_CREATE_EMAIL_DRAFT",
        "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID",
        "GMAIL_FETCH_MESSAGE_BY_THREAD_ID",
        "GMAIL_LIST_DRAFTS",
        "GMAIL_GET_DRAFT",
        "GMAIL_FETCH_ATTACHMENT",
        "GMAIL_FETCH_EMAIL_BY_ID",
        "GMAIL_SEND_DRAFT",
        "GMAIL_GET_CONTACTS",
        "GMAIL_SEARCH_PEOPLE",
        "REDDIT_SEARCH_ACROSS_SUBREDDITS",
        "REDDIT_RETRIEVE_REDDIT_POST",
        "REDDIT_RETRIEVE_POST_COMMENTS",
        "REDDIT_CREATE_REDDIT_POST",
        "REDDIT_POST_REDDIT_COMMENT",
        "TWITTER_RECENT_SEARCH",
        "TWITTER_FULL_ARCHIVE_SEARCH",
        "TWITTER_USER_LOOKUP_BY_USERNAME",
        "TWITTER_USER_LOOKUP_BY_USERNAMES",
        "TWITTER_USER_HOME_TIMELINE_BY_USER_ID",
        "TWITTER_FOLLOWERS_BY_USER_ID",
        "TWITTER_FOLLOWING_BY_USER_ID",
        "TWITTER_CREATION_OF_A_POST",
    }
)
TWEETS: ToolExecutionResponse = {
    "data": {
        "data": [{"id": "1", "text": "hello", "author_id": "u1"}],
        "meta": {"result_count": 1},
    },
    "successful": True,
    "error": None,
}


def _failed() -> ToolExecutionResponse:
    return {"data": {}, "successful": False, "error": "Rate limited"}


def _toolkit(tool: str) -> str:
    return tool.split("_", 1)[0].lower()


@pytest.fixture
def writer() -> Iterator[MagicMock]:
    """Capture the frontend stream every hook module writes its cards to."""
    stream = MagicMock()
    with (
        patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer", return_value=stream),
        patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer", return_value=stream),
        patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer", return_value=stream),
    ):
        yield stream


@pytest.mark.unit
class TestAfterHookEnvelope:
    def test_the_registry_knows_every_hooked_tool(self) -> None:
        assert hook_registry.after_hook_tools == HOOKED_TOOLS

    @pytest.mark.parametrize("tool", sorted(HOOKED_TOOLS))
    def test_a_failed_call_reaches_the_caller_untouched_and_streams_nothing(
        self, tool: str, writer: MagicMock
    ) -> None:
        """Regression: a failed call's error was dropped, and create-post hooks streamed a success card for it."""
        result = master_after_execute_hook(tool, _toolkit(tool), _failed())
        assert result == _failed()
        writer.assert_not_called()

    @pytest.mark.parametrize("tool", sorted(HOOKED_TOOLS))
    def test_a_successful_call_keeps_the_envelope_around_its_reshaped_data(
        self, tool: str, writer: MagicMock
    ) -> None:
        result = master_after_execute_hook(
            tool, _toolkit(tool), {"data": {}, "successful": True, "error": None}
        )
        assert set(result) == {"data", "successful", "error"}
        assert result["successful"] is True
        assert result["error"] is None

    def test_the_hook_still_reshapes_the_data_inside_the_envelope(self, writer: MagicMock) -> None:
        reshaped = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "twitter", TWEETS)
        result = master_after_execute_hook("TWITTER_RECENT_SEARCH", "twitter", TWEETS)
        assert result == {"data": reshaped, "successful": True, "error": None}
        assert reshaped != TWEETS["data"]

    @pytest.mark.parametrize(
        ("error", "text"),
        [("Not authorized", "Not authorized"), ({"code": 403}, '{"code": 403}')],
        ids=["string_error", "structured_error"],
    )
    def test_an_error_inside_a_successful_calls_data_marks_it_failed(
        self, error: object, text: str, writer: MagicMock
    ) -> None:
        data = {"error": error}
        result = master_after_execute_hook(
            "TWITTER_RECENT_SEARCH", "twitter", {"data": data, "successful": True, "error": None}
        )
        assert result == {"data": data, "successful": False, "error": text}
        writer.assert_not_called()

    def test_a_falsy_error_inside_the_data_is_not_a_failure(self, writer: MagicMock) -> None:
        result = master_after_execute_hook(
            "TWITTER_RECENT_SEARCH",
            "twitter",
            {"data": {"error": None}, "successful": True, "error": None},
        )
        assert result["successful"] is True
        assert result["error"] is None

    def test_a_tool_without_a_hook_passes_through_untouched(self) -> None:
        response: ToolExecutionResponse = {"data": {"ok": 1}, "successful": True, "error": None}
        assert master_after_execute_hook("SLACK_SEND_MESSAGE", "slack", response) is response


@pytest.mark.unit
class TestEnvelopeThroughTheSdkAndTheErrorDetectors:
    def _through_sdk(self, tool: str, response: ToolExecutionResponse) -> ToolExecutionResponse:
        modifier = after_execute(tools=[tool])(master_after_execute_hook)
        return apply_modifier_by_type(
            [modifier], toolkit=_toolkit(tool), tool=tool, type="after_execute", response=response
        )

    def test_composio_hands_the_envelope_back_as_the_tool_result(self, writer: MagicMock) -> None:
        result = self._through_sdk("TWITTER_RECENT_SEARCH", TWEETS)
        assert result["successful"] is True
        assert result["data"] == twitter_search_after_hook(
            "TWITTER_RECENT_SEARCH", "twitter", TWEETS
        )

    def test_a_failed_call_is_an_error_to_every_downstream_detector(
        self, writer: MagicMock
    ) -> None:
        assert is_error_envelope(self._through_sdk("TWITTER_CREATION_OF_A_POST", _failed()))

    def test_an_error_inside_the_data_is_an_error_to_every_downstream_detector(
        self, writer: MagicMock
    ) -> None:
        response: ToolExecutionResponse = {
            "data": {"error": "Not authorized"},
            "successful": True,
            "error": None,
        }
        assert is_error_envelope(self._through_sdk("GMAIL_GET_CONTACTS", response))

    def test_a_successful_call_is_not_an_error(self, writer: MagicMock) -> None:
        assert not is_error_envelope(self._through_sdk("TWITTER_RECENT_SEARCH", TWEETS))
