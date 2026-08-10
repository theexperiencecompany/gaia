"""Unit tests for Composio schema models.

Covers every model in `app/models/composio_schemas/` (base, github,
github_tools, google_calendar, google_docs, google_sheets, linear,
linear_tools, notion, notion_tools, sheets_tools, slack, slack_tools).
"""

from typing import ClassVar

from pydantic import ValidationError
import pytest

from app.models.composio_schemas import (
    ComposioResponse,
    GitHubCommitEventPayload,
    GitHubIssueAddedEventPayload,
    GitHubListRepositoriesData,
    GitHubListRepositoriesInput,
    GitHubPullRequestEventPayload,
    GitHubRepository,
    GitHubStarAddedEventPayload,
    GoogleCalendarEventCreatedPayload,
    GoogleCalendarEventStartingSoonPayload,
    GoogleDocsPageAddedPayload,
    GoogleSheetsGetSheetNamesData,
    GoogleSheetsGetSheetNamesInput,
    GoogleSheetsNewRowPayload,
    GoogleSheetsNewSheetAddedPayload,
    GoogleSheetsSearchSpreadsheetsData,
    GoogleSheetsSearchSpreadsheetsInput,
    GoogleSheetsSpreadsheet,
    LinearCommentAddedPayload,
    LinearGetAllTeamsData,
    LinearGetAllTeamsInput,
    LinearIssueCreatedPayload,
    LinearMember,
    LinearTeam,
    NotionAllPageEventsPayload,
    NotionFetchDataData,
    NotionFetchDataInput,
    NotionItem,
    NotionPageAddedPayload,
    NotionPageUpdatedPayload,
    SlackChannel,
    SlackChannelCreatedPayload,
    SlackListAllChannelsData,
    SlackListAllChannelsInput,
    SlackReceiveMessagePayload,
)

# ---------------------------------------------------------------------------
# base.ComposioResponse
# ---------------------------------------------------------------------------


class TestComposioResponse:
    def test_valid_full(self):
        m = ComposioResponse(successful=True, data={"key": "value"})
        assert m.successful is True
        assert m.data == {"key": "value"}
        assert m.error is None

    def test_valid_with_error(self):
        m = ComposioResponse(successful=False, error="boom", data={})
        assert m.successful is False
        assert m.error == "boom"

    def test_valid_from_attributes(self):
        class Fake:
            successful = True
            error = None
            data: ClassVar[dict[str, int]] = {"n": 1}

        m = ComposioResponse.model_validate(Fake())
        assert m.successful is True
        assert m.data == {"n": 1}

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            ComposioResponse()

    def test_missing_data(self):
        with pytest.raises(ValidationError):
            ComposioResponse(successful=True)

    def test_wrong_type_successful(self):
        with pytest.raises(ValidationError):
            ComposioResponse(successful="notabool", data={})

    def test_wrong_type_data(self):
        with pytest.raises(ValidationError):
            ComposioResponse(successful=True, data=["not", "a", "dict"])


# ---------------------------------------------------------------------------
# github trigger payloads
# ---------------------------------------------------------------------------


class TestGitHubCommitEventPayload:
    def test_valid_minimal(self):
        m = GitHubCommitEventPayload()
        assert m.author is None
        assert m.id is None

    def test_valid_full(self):
        m = GitHubCommitEventPayload(
            author="octocat",
            id="abc123",
            message="fix: stuff",
            timestamp="2025-01-01T00:00:00Z",
            url="https://github.com/org/repo/commit/abc123",
        )
        assert m.author == "octocat"
        assert m.id == "abc123"
        assert m.url == "https://github.com/org/repo/commit/abc123"

    def test_wrong_type_author(self):
        with pytest.raises(ValidationError):
            GitHubCommitEventPayload(author=123)


class TestGitHubPullRequestEventPayload:
    def test_valid_minimal(self):
        m = GitHubPullRequestEventPayload()
        assert m.description == ""
        assert m.number is None

    def test_valid_full(self):
        m = GitHubPullRequestEventPayload(
            action="opened",
            createdAt="2025-01-01T00:00:00Z",
            createdBy="octocat",
            description="Adds docs",
            number=42,
            title="Docs",
            url="https://github.com/org/repo/pull/42",
        )
        assert m.action == "opened"
        assert m.number == 42
        assert m.title == "Docs"

    def test_custom_description(self):
        m = GitHubPullRequestEventPayload(description="hello")
        assert m.description == "hello"

    def test_wrong_type_number(self):
        with pytest.raises(ValidationError):
            GitHubPullRequestEventPayload(number="not-a-number")


class TestGitHubStarAddedEventPayload:
    def test_valid_minimal(self):
        m = GitHubStarAddedEventPayload()
        assert m.action is None
        assert m.user is None

    def test_valid_full(self):
        m = GitHubStarAddedEventPayload(
            action="starred",
            starred_at="2025-01-01T00:00:00Z",
            user="octocat",
        )
        assert m.starred_at == "2025-01-01T00:00:00Z"
        assert m.user == "octocat"


class TestGitHubIssueAddedEventPayload:
    def test_valid_minimal(self):
        m = GitHubIssueAddedEventPayload()
        assert m.description == ""
        assert m.issue_id is None

    def test_valid_full(self):
        m = GitHubIssueAddedEventPayload(
            action="opened",
            createdAt="2025-01-01T00:00:00Z",
            createdBy="octocat",
            description="Bug report",
            issue_id=7,
            number=7,
            title="Bug",
            url="https://github.com/org/repo/issues/7",
        )
        assert m.issue_id == 7
        assert m.number == 7
        assert m.title == "Bug"

    def test_wrong_type_issue_id(self):
        with pytest.raises(ValidationError):
            GitHubIssueAddedEventPayload(issue_id="not-a-number")


# ---------------------------------------------------------------------------
# github_tools
# ---------------------------------------------------------------------------


class TestGitHubListRepositoriesInput:
    def test_defaults(self):
        m = GitHubListRepositoriesInput()
        assert m.page == 1
        assert m.per_page == 30
        assert m.raw_response is False
        assert m.direction is None
        assert m.sort is None
        assert m.type is None
        assert m.visibility is None

    def test_valid_full(self):
        m = GitHubListRepositoriesInput(
            before="2024-01-01",
            direction="asc",
            page=2,
            per_page=50,
            raw_response=True,
            since="2023-01-01",
            sort="pushed",
            type="owner",
            visibility="public",
        )
        assert m.direction == "asc"
        assert m.sort == "pushed"
        assert m.type == "owner"
        assert m.visibility == "public"

    @pytest.mark.parametrize("direction", ["up", "ASC", "sideways"])
    def test_invalid_direction_literal(self, direction):
        with pytest.raises(ValidationError):
            GitHubListRepositoriesInput(direction=direction)

    @pytest.mark.parametrize("sort", ["stars", "name", ""])
    def test_invalid_sort_literal(self, sort):
        with pytest.raises(ValidationError):
            GitHubListRepositoriesInput(sort=sort)

    @pytest.mark.parametrize("type", ["starred", "forked", ""])
    def test_invalid_type_literal(self, type):
        with pytest.raises(ValidationError):
            GitHubListRepositoriesInput(type=type)

    @pytest.mark.parametrize("visibility", ["internal", ""])
    def test_invalid_visibility_literal(self, visibility):
        with pytest.raises(ValidationError):
            GitHubListRepositoriesInput(visibility=visibility)

    def test_page_has_no_ge_constraint(self):
        # The schema declares no minimum for `page`, so 0 and -1 are accepted
        # and "1" coerces to int 1 (pydantic lax mode).
        m = GitHubListRepositoriesInput(page=0)
        assert m.page == 0
        m = GitHubListRepositoriesInput(page=-1)
        assert m.page == -1
        m = GitHubListRepositoriesInput(page="1")
        assert m.page == 1

    def test_invalid_page_type(self):
        with pytest.raises(ValidationError):
            GitHubListRepositoriesInput(page="not-a-number")


class TestGitHubRepository:
    def test_valid_full(self):
        m = GitHubRepository(
            id=1,
            name="gaia",
            full_name="org/gaia",
            private=True,
            owner={"login": "octocat"},
            html_url="https://github.com/org/gaia",
            description="AI",
            fork=False,
            url="https://github.com/org/gaia",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-06-01T00:00:00Z",
            pushed_at="2024-07-01T00:00:00Z",
            default_branch="develop",
        )
        assert m.id == 1
        assert m.full_name == "org/gaia"
        assert m.default_branch == "develop"

    def test_extra_fields_ignored(self):
        m = GitHubRepository(id=1, unknown_field="dropped")
        assert not hasattr(m, "unknown_field")

    def test_valid_from_attributes(self):
        class Fake:
            id = 9
            name = "repo"

        m = GitHubRepository.model_validate(Fake())
        assert m.id == 9
        assert m.name == "repo"

    def test_wrong_type_id(self):
        with pytest.raises(ValidationError):
            GitHubRepository(id="not-an-int")


class TestGitHubListRepositoriesData:
    def test_from_direct_list(self):
        repos = GitHubListRepositoriesData.from_response_data(
            [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        )
        assert len(repos) == 2
        assert repos[0].name == "a"
        assert repos[1].id == 2

    def test_from_repositories_key(self):
        repos = GitHubListRepositoriesData.from_response_data(
            {"repositories": [{"id": 1, "name": "a"}]}
        )
        assert [r.id for r in repos] == [1]

    def test_from_data_key(self):
        repos = GitHubListRepositoriesData.from_response_data({"data": [{"id": 1, "name": "a"}]})
        assert [r.id for r in repos] == [1]

    def test_from_empty_dict(self):
        repos = GitHubListRepositoriesData.from_response_data({})
        assert repos == []

    def test_repositories_key_not_a_list(self):
        repos = GitHubListRepositoriesData.from_response_data({"repositories": {"not": "a list"}})
        assert repos == []

    def test_missing_repo_fields_tolerated(self):
        repos = GitHubListRepositoriesData.from_response_data([{"id": 1}])
        assert repos[0].name is None


# ---------------------------------------------------------------------------
# google_calendar
# ---------------------------------------------------------------------------


class TestGoogleCalendarEventCreatedPayload:
    def test_valid_minimal(self):
        m = GoogleCalendarEventCreatedPayload()
        assert m.event_id is None
        assert m.summary is None

    def test_valid_full(self):
        m = GoogleCalendarEventCreatedPayload(
            calendar_id="primary",
            end_time="2025-01-01T11:00:00Z",
            event_id="evt1",
            organizer_email="a@b.com",
            organizer_name="Alice",
            start_time="2025-01-01T10:00:00Z",
            summary="Standup",
        )
        assert m.event_id == "evt1"
        assert m.summary == "Standup"
        assert m.organizer_email == "a@b.com"

    def test_wrong_type_end_time(self):
        with pytest.raises(ValidationError):
            GoogleCalendarEventCreatedPayload(end_time=123)


class TestGoogleCalendarEventStartingSoonPayload:
    def test_valid_minimal(self):
        m = GoogleCalendarEventStartingSoonPayload()
        assert m.attendees is None
        assert m.countdown_window_minutes is None

    def test_valid_full(self):
        m = GoogleCalendarEventStartingSoonPayload(
            attendees=[{"email": "a@b.com"}],
            calendar_id="primary",
            countdown_window_minutes=10,
            creator_email="c@b.com",
            description="desc",
            event_id="evt1",
            hangout_link="https://meet.google.com/abc",
            html_link="https://calendar.google.com/event",
            location="Room 1",
            organizer_email="a@b.com",
            organizer_self=True,
            start_time="2025-01-01T10:00:00Z",
            status="confirmed",
            summary="Standup",
            updated="2025-01-01T09:00:00Z",
        )
        assert m.countdown_window_minutes == 10
        assert m.organizer_self is True
        assert m.status == "confirmed"

    def test_wrong_type_attendees(self):
        with pytest.raises(ValidationError):
            GoogleCalendarEventStartingSoonPayload(attendees=["not", "a", "dict"])

    def test_wrong_type_countdown(self):
        with pytest.raises(ValidationError):
            GoogleCalendarEventStartingSoonPayload(countdown_window_minutes="ten")


# ---------------------------------------------------------------------------
# google_docs
# ---------------------------------------------------------------------------


class TestGoogleDocsPageAddedPayload:
    def test_valid_full(self):
        m = GoogleDocsPageAddedPayload(
            document={
                "createdTime": "2025-01-01T00:00:00Z",
                "id": "doc123",
                "mimeType": "application/vnd.google-apps.document",
                "modifiedTime": "2025-01-02T00:00:00Z",
                "name": "Notes",
                "lastModifyingUser": {"emailAddress": "a@b.com"},
                "owners": [{"emailAddress": "a@b.com"}],
            }
        )
        assert m.document is not None
        assert m.document.id == "doc123"
        assert m.document.name == "Notes"
        assert m.document.lastModifyingUser == {"emailAddress": "a@b.com"}
        assert m.document.owners == [{"emailAddress": "a@b.com"}]

    def test_document_optional(self):
        m = GoogleDocsPageAddedPayload()
        assert m.document is None

    def test_document_missing_required_field(self):
        with pytest.raises(ValidationError):
            GoogleDocsPageAddedPayload(document={"id": "doc123"})

    def test_document_wrong_type(self):
        with pytest.raises(ValidationError):
            GoogleDocsPageAddedPayload(document="not-a-doc")


# ---------------------------------------------------------------------------
# google_sheets
# ---------------------------------------------------------------------------


class TestGoogleSheetsNewRowPayload:
    def test_valid_minimal(self):
        m = GoogleSheetsNewRowPayload()
        assert m.row_data is None
        assert m.row_number is None

    def test_valid_full(self):
        m = GoogleSheetsNewRowPayload(
            detected_at="2025-01-01T00:00:00Z",
            row_data=["a", "b", "c"],
            row_number=3,
            sheet_name="Sheet1",
            spreadsheet_id="spr123",
        )
        assert m.row_data == ["a", "b", "c"]
        assert m.row_number == 3
        assert m.spreadsheet_id == "spr123"

    def test_wrong_type_row_data(self):
        with pytest.raises(ValidationError):
            GoogleSheetsNewRowPayload(row_data=[1, 2])

    def test_wrong_type_row_number(self):
        with pytest.raises(ValidationError):
            GoogleSheetsNewRowPayload(row_number="three")


class TestGoogleSheetsNewSheetAddedPayload:
    def test_valid_minimal(self):
        m = GoogleSheetsNewSheetAddedPayload()
        assert m.sheet_name is None
        assert m.spreadsheet_id is None

    def test_valid_full(self):
        m = GoogleSheetsNewSheetAddedPayload(
            detected_at="2025-01-01T00:00:00Z",
            sheet_name="Sheet1",
            spreadsheet_id="spr123",
        )
        assert m.sheet_name == "Sheet1"
        assert m.spreadsheet_id == "spr123"


# ---------------------------------------------------------------------------
# linear trigger payloads
# ---------------------------------------------------------------------------


class TestLinearIssueCreatedPayload:
    def test_valid_minimal(self):
        m = LinearIssueCreatedPayload()
        assert m.action is None
        assert m.data is None
        assert m.type is None
        assert m.url is None

    def test_valid_full(self):
        m = LinearIssueCreatedPayload(
            action="create",
            data={"identifier": "ENG-1"},
            type="Issue",
            url="https://linear.app/org/issue/ENG-1",
        )
        assert m.data == {"identifier": "ENG-1"}
        assert m.type == "Issue"

    def test_wrong_type_data(self):
        with pytest.raises(ValidationError):
            LinearIssueCreatedPayload(data=["not", "a", "dict"])


class TestLinearCommentAddedPayload:
    # Identical shape to LinearIssueCreatedPayload — same four optional fields.
    def test_valid_full(self):
        m = LinearCommentAddedPayload(
            action="create",
            data={"body": "hello"},
            type="Comment",
            url="https://linear.app/org/issue/ENG-1#comment-1",
        )
        assert m.data == {"body": "hello"}
        assert m.type == "Comment"

    def test_valid_minimal(self):
        m = LinearCommentAddedPayload()
        assert m.action is None
        assert m.url is None


# ---------------------------------------------------------------------------
# linear_tools
# ---------------------------------------------------------------------------


class TestLinearGetAllTeamsInput:
    def test_valid_empty(self):
        m = LinearGetAllTeamsInput()
        assert m.model_dump() == {}


class TestLinearMember:
    def test_valid_minimal(self):
        m = LinearMember(id="mem1")
        assert m.id == "mem1"
        assert m.name == ""
        assert m.email == ""

    def test_valid_full(self):
        m = LinearMember(id="mem1", name="Alice", email="a@b.com")
        assert m.name == "Alice"
        assert m.email == "a@b.com"

    def test_extra_fields_ignored(self):
        m = LinearMember(id="mem1", displayName="ignored")
        assert not hasattr(m, "displayName")

    def test_missing_id(self):
        with pytest.raises(ValidationError):
            LinearMember()

    def test_wrong_type_email(self):
        with pytest.raises(ValidationError):
            LinearMember(id="mem1", email=123)


class TestLinearTeam:
    def test_valid_minimal(self):
        m = LinearTeam(id="team1")
        assert m.id == "team1"
        assert m.key == ""
        assert m.name == ""
        assert m.members == []

    def test_valid_full(self):
        m = LinearTeam(
            id="team1",
            key="ENG",
            name="Engineering",
            members=[LinearMember(id="mem1", name="Alice")],
        )
        assert m.key == "ENG"
        assert m.members[0].name == "Alice"

    def test_members_from_dicts(self):
        m = LinearTeam.model_validate({"id": "team1", "members": [{"id": "mem1", "name": "Alice"}]})
        assert m.members[0].name == "Alice"

    def test_extra_fields_ignored(self):
        m = LinearTeam(id="team1", icon="ignored")
        assert not hasattr(m, "icon")

    def test_missing_id(self):
        with pytest.raises(ValidationError):
            LinearTeam()

    def test_wrong_type_members(self):
        with pytest.raises(ValidationError):
            LinearTeam(id="team1", members=["not-a-member"])


class TestLinearGetAllTeamsData:
    def test_defaults(self):
        m = LinearGetAllTeamsData()
        assert m.items == []
        assert m.teams == []
        assert m.get_teams() == []

    def test_get_teams_prefers_items(self):
        m = LinearGetAllTeamsData(
            items=[{"id": "t1", "name": "ItemTeam"}],
            teams=[{"id": "t2", "name": "TeamTeam"}],
        )
        teams = m.get_teams()
        assert [t.id for t in teams] == ["t1"]

    def test_get_teams_falls_back_to_teams(self):
        m = LinearGetAllTeamsData(
            items=[],
            teams=[{"id": "t2", "name": "TeamTeam"}],
        )
        teams = m.get_teams()
        assert [t.id for t in teams] == ["t2"]

    def test_get_teams_skips_non_dicts(self):
        # `items` is list[dict], so non-dicts can only exist via model_construct
        # (bypasses validation); get_teams must still filter them out.
        m = LinearGetAllTeamsData.model_construct(items=[{"id": "t1"}, "junk", 42, None])
        teams = m.get_teams()
        assert [t.id for t in teams] == ["t1"]

    def test_get_teams_skips_missing_id(self):
        m = LinearGetAllTeamsData(items=[{"name": "no-id"}])
        with pytest.raises(ValidationError):
            m.get_teams()

    def test_extra_fields_ignored(self):
        m = LinearGetAllTeamsData(items=[], extra="dropped")
        assert not hasattr(m, "extra")


# ---------------------------------------------------------------------------
# notion trigger payloads
# ---------------------------------------------------------------------------


class TestNotionPageAddedPayload:
    def test_valid_full(self):
        m = NotionPageAddedPayload(event_type="page.added", block={"id": "page1"})
        assert m.event_type == "page.added"
        assert m.block == {"id": "page1"}

    def test_block_optional(self):
        m = NotionPageAddedPayload(event_type="page.added")
        assert m.block is None

    def test_missing_event_type(self):
        with pytest.raises(ValidationError):
            NotionPageAddedPayload()

    def test_wrong_type_event_type(self):
        with pytest.raises(ValidationError):
            NotionPageAddedPayload(event_type=123)


class TestNotionPageUpdatedPayload:
    # Same shape as NotionPageAddedPayload — block optional, event_type required.
    def test_valid_full(self):
        m = NotionPageUpdatedPayload(event_type="page.updated", block={"id": "page1"})
        assert m.event_type == "page.updated"
        assert m.block == {"id": "page1"}

    def test_missing_event_type(self):
        with pytest.raises(ValidationError):
            NotionPageUpdatedPayload()


class TestNotionAllPageEventsPayload:
    # Same shape as NotionPageAddedPayload — block optional, event_type required.
    def test_valid_full(self):
        m = NotionAllPageEventsPayload(event_type="page.added", block={"id": "page1"})
        assert m.event_type == "page.added"
        assert m.block == {"id": "page1"}

    def test_missing_event_type(self):
        with pytest.raises(ValidationError):
            NotionAllPageEventsPayload()


# ---------------------------------------------------------------------------
# notion_tools
# ---------------------------------------------------------------------------


class TestNotionFetchDataInput:
    def test_defaults(self):
        m = NotionFetchDataInput(fetch_type="pages")
        assert m.fetch_type == "pages"
        assert m.page_size == 100
        assert m.query is None

    def test_valid_full(self):
        m = NotionFetchDataInput(fetch_type="all", page_size=50, query="roadmap")
        assert m.fetch_type == "all"
        assert m.page_size == 50
        assert m.query == "roadmap"

    @pytest.mark.parametrize("fetch_type", ["pages", "databases", "all"])
    def test_valid_fetch_types(self, fetch_type):
        m = NotionFetchDataInput(fetch_type=fetch_type)
        assert m.fetch_type == fetch_type

    @pytest.mark.parametrize("fetch_type", ["blocks", "PAGES", ""])
    def test_invalid_fetch_type(self, fetch_type):
        with pytest.raises(ValidationError):
            NotionFetchDataInput(fetch_type=fetch_type)

    def test_missing_fetch_type(self):
        with pytest.raises(ValidationError):
            NotionFetchDataInput()

    def test_wrong_type_page_size(self):
        with pytest.raises(ValidationError):
            NotionFetchDataInput(fetch_type="pages", page_size="hundred")


class TestNotionItem:
    def test_valid_minimal(self):
        m = NotionItem(id="page1")
        assert m.id == "page1"
        assert m.title is None
        assert m.type is None
        assert m.url is None

    def test_valid_full(self):
        m = NotionItem(id="page1", title="Roadmap", type="page", url="https://notion.so/page1")
        assert m.title == "Roadmap"
        assert m.type == "page"

    def test_extra_fields_ignored(self):
        m = NotionItem(id="page1", parent_id="ignored")
        assert not hasattr(m, "parent_id")

    def test_missing_id(self):
        with pytest.raises(ValidationError):
            NotionItem()

    def test_wrong_type_id(self):
        with pytest.raises(ValidationError):
            NotionItem(id=123)


class TestNotionFetchDataData:
    def test_defaults(self):
        m = NotionFetchDataData()
        assert m.values == []
        assert m.get_items() == []

    def test_get_items_returns_typed_models(self):
        m = NotionFetchDataData(values=[{"id": "p1", "title": "A"}, {"id": "p2", "title": "B"}])
        items = m.get_items()
        assert isinstance(items[0], NotionItem)
        assert [i.id for i in items] == ["p1", "p2"]

    def test_get_items_skips_non_dicts(self):
        # `values` is list[dict], so non-dicts can only exist via model_construct
        # (bypasses validation); get_items must still filter them out.
        m = NotionFetchDataData.model_construct(values=[{"id": "p1"}, "junk", None, 7])
        items = m.get_items()
        assert [i.id for i in items] == ["p1"]

    def test_get_items_skips_missing_id(self):
        m = NotionFetchDataData(values=[{"title": "no-id"}])
        with pytest.raises(ValidationError):
            m.get_items()

    def test_extra_fields_ignored(self):
        m = NotionFetchDataData(values=[], extra="dropped")
        assert not hasattr(m, "extra")


# ---------------------------------------------------------------------------
# sheets_tools
# ---------------------------------------------------------------------------


class TestGoogleSheetsSearchSpreadsheetsInput:
    def test_defaults(self):
        m = GoogleSheetsSearchSpreadsheetsInput()
        assert m.max_results == 10
        assert m.created_after is None
        assert m.include_trashed is None
        assert m.modified_after is None
        assert m.order_by is None

    def test_valid_full_with_aliases(self):
        m = GoogleSheetsSearchSpreadsheetsInput(
            createdAfter="2024-01-01",
            includeTrashed=True,
            maxResults=25,
            modifiedAfter="2024-02-01",
            orderBy="modifiedTime desc",
        )
        assert m.created_after == "2024-01-01"
        assert m.include_trashed is True
        assert m.max_results == 25
        assert m.modified_after == "2024-02-01"
        assert m.order_by == "modifiedTime desc"

    def test_serializes_with_aliases(self):
        m = GoogleSheetsSearchSpreadsheetsInput(maxResults=5)
        dumped = m.model_dump(by_alias=True)
        assert dumped == {
            "createdAfter": None,
            "includeTrashed": None,
            "maxResults": 5,
            "modifiedAfter": None,
            "orderBy": None,
        }

    def test_field_name_kwargs_are_ignored(self):
        # No populate_by_name: field-name kwargs are silently dropped,
        # so the declared values never land on the model.
        m = GoogleSheetsSearchSpreadsheetsInput(created_after="2024-01-01")
        assert m.created_after is None

    def test_round_trip_model_dump(self):
        m = GoogleSheetsSearchSpreadsheetsInput.model_validate(
            GoogleSheetsSearchSpreadsheetsInput(maxResults=12).model_dump(by_alias=True)
        )
        assert m.max_results == 12

    def test_wrong_type_max_results(self):
        with pytest.raises(ValidationError):
            GoogleSheetsSearchSpreadsheetsInput(maxResults="twenty-five")


class TestGoogleSheetsGetSheetNamesInput:
    def test_valid_minimal(self):
        m = GoogleSheetsGetSheetNamesInput()
        assert m.spreadsheet_id is None

    def test_valid_full(self):
        m = GoogleSheetsGetSheetNamesInput(spreadsheet_id="spr123")
        assert m.spreadsheet_id == "spr123"

    def test_wrong_type(self):
        with pytest.raises(ValidationError):
            GoogleSheetsGetSheetNamesInput(spreadsheet_id=123)


class TestGoogleSheetsSpreadsheet:
    def test_valid_minimal(self):
        m = GoogleSheetsSpreadsheet()
        assert m.id is None
        assert m.owners == []

    def test_valid_full(self):
        m = GoogleSheetsSpreadsheet(
            id="spr123",
            name="Sheet",
            mimeType="application/vnd.google-apps.spreadsheet",
            shared=False,
            owners=[
                {
                    "me": True,
                    "kind": "drive#user",
                    "displayName": "Alice",
                    "emailAddress": "a@b.com",
                }
            ],
        )
        assert m.id == "spr123"
        assert m.owners[0].me is True
        assert m.owners[0].emailAddress == "a@b.com"

    def test_extra_fields_ignored(self):
        m = GoogleSheetsSpreadsheet(id="spr123", unknown="dropped")
        assert not hasattr(m, "unknown")

    def test_wrong_type_owners(self):
        with pytest.raises(ValidationError):
            GoogleSheetsSpreadsheet(owners=["not-a-owner"])


class TestGoogleSheetsSearchSpreadsheetsData:
    def test_defaults(self):
        m = GoogleSheetsSearchSpreadsheetsData()
        assert m.spreadsheets == []

    def test_valid_full(self):
        m = GoogleSheetsSearchSpreadsheetsData(
            spreadsheets=[{"id": "spr1", "name": "A"}, {"id": "spr2", "name": "B"}]
        )
        assert isinstance(m.spreadsheets[0], GoogleSheetsSpreadsheet)
        assert [s.id for s in m.spreadsheets] == ["spr1", "spr2"]

    def test_extra_fields_ignored(self):
        m = GoogleSheetsSearchSpreadsheetsData(spreadsheets=[], extra="dropped")
        assert not hasattr(m, "extra")


class TestGoogleSheetsGetSheetNamesData:
    def test_defaults(self):
        m = GoogleSheetsGetSheetNamesData()
        assert m.sheet_names == []

    def test_valid_full(self):
        m = GoogleSheetsGetSheetNamesData(sheet_names=["Sheet1", "Sheet2"])
        assert m.sheet_names == ["Sheet1", "Sheet2"]

    def test_extra_fields_ignored(self):
        m = GoogleSheetsGetSheetNamesData(sheet_names=[], extra="dropped")
        assert not hasattr(m, "extra")

    def test_wrong_type_sheet_names(self):
        with pytest.raises(ValidationError):
            GoogleSheetsGetSheetNamesData(sheet_names=[1])


# ---------------------------------------------------------------------------
# slack trigger payloads
# ---------------------------------------------------------------------------


class TestSlackReceiveMessagePayload:
    def test_valid_minimal(self):
        m = SlackReceiveMessagePayload()
        assert m.text is None
        assert m.attachments is None

    def test_valid_full(self):
        m = SlackReceiveMessagePayload(
            attachments=[{"id": 1}],
            bot_id="B123",
            channel="C123",
            channel_type="channel",
            team_id="T123",
            text="hello",
            ts="1234567890.123456",
            user="U123",
        )
        assert m.text == "hello"
        assert m.channel == "C123"
        assert m.attachments == [{"id": 1}]
        assert m.ts == "1234567890.123456"

    def test_wrong_type_attachments(self):
        with pytest.raises(ValidationError):
            SlackReceiveMessagePayload(attachments=["not", "a", "dict"])


class TestSlackChannelCreatedPayload:
    def test_valid_minimal(self):
        m = SlackChannelCreatedPayload()
        assert m.created is None
        assert m.name is None

    def test_valid_full(self):
        m = SlackChannelCreatedPayload(
            created=1234567890,
            creator="U123",
            id="C123",
            name="general",
        )
        assert m.created == 1234567890
        assert m.id == "C123"
        assert m.name == "general"

    def test_wrong_type_created(self):
        with pytest.raises(ValidationError):
            SlackChannelCreatedPayload(created="not-a-timestamp")


# ---------------------------------------------------------------------------
# slack_tools
# ---------------------------------------------------------------------------


class TestSlackListAllChannelsInput:
    def test_defaults(self):
        m = SlackListAllChannelsInput()
        assert m.limit == 1
        assert m.channel_name is None
        assert m.cursor is None
        assert m.exclude_archived is None
        assert m.types is None

    def test_valid_full(self):
        m = SlackListAllChannelsInput(
            channel_name="general",
            cursor="xyz",
            exclude_archived=True,
            limit=100,
            types="public_channel",
        )
        assert m.limit == 100
        assert m.types == "public_channel"

    def test_wrong_type_limit(self):
        with pytest.raises(ValidationError):
            SlackListAllChannelsInput(limit="one")


class TestSlackChannel:
    def test_valid_minimal(self):
        m = SlackChannel()
        assert m.id is None
        assert m.name is None

    def test_valid_full(self):
        m = SlackChannel(
            id="C123",
            name="general",
            created=1234567890,
            creator="U123",
            is_archived=False,
            is_channel=True,
            is_general=True,
            is_private=False,
            is_im=False,
            is_mpim=False,
            num_members=42,
        )
        assert m.name == "general"
        assert m.is_general is True
        assert m.num_members == 42

    def test_extra_fields_ignored(self):
        m = SlackChannel(id="C123", topic="ignored")
        assert not hasattr(m, "topic")

    def test_wrong_type_created(self):
        with pytest.raises(ValidationError):
            SlackChannel(created="not-a-timestamp")


class TestSlackListAllChannelsData:
    def test_defaults(self):
        m = SlackListAllChannelsData()
        assert m.channels == []
        assert m.response_metadata is None
        assert m.get_channels() == []
        assert m.next_cursor is None

    def test_get_channels_returns_typed_models(self):
        m = SlackListAllChannelsData(channels=[{"id": "C1"}, {"id": "C2"}])
        channels = m.get_channels()
        assert isinstance(channels[0], SlackChannel)
        assert [c.id for c in channels] == ["C1", "C2"]

    def test_get_channels_skips_non_dicts(self):
        # `channels` is list[dict], so non-dicts can only exist via
        # model_construct (bypasses validation); get_channels must still
        # filter them out.
        m = SlackListAllChannelsData.model_construct(channels=[{"id": "C1"}, "junk", None])
        channels = m.get_channels()
        assert [c.id for c in channels] == ["C1"]

    def test_extra_fields_ignored(self):
        m = SlackListAllChannelsData(channels=[], extra="dropped")
        assert not hasattr(m, "extra")

    def test_next_cursor_present(self):
        m = SlackListAllChannelsData(response_metadata={"next_cursor": "cursor-123"})
        assert m.next_cursor == "cursor-123"

    def test_next_cursor_absent(self):
        m = SlackListAllChannelsData(response_metadata={"no_cursor": "x"})
        assert m.next_cursor is None

    def test_next_cursor_empty_string(self):
        m = SlackListAllChannelsData(response_metadata={"next_cursor": ""})
        assert m.next_cursor == ""

    def test_next_cursor_non_string(self):
        m = SlackListAllChannelsData(response_metadata={"next_cursor": 123})
        assert m.next_cursor is None

    def test_next_cursor_no_metadata(self):
        m = SlackListAllChannelsData()
        assert m.next_cursor is None
