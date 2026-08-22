"""Unit tests for the Composio GitHub tools schemas (github_tools.py)."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.github_tools import (
    GitHubListRepositoriesData,
    GitHubListRepositoriesInput,
    GitHubRepository,
)


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
    def test_invalid_sort_literal(self, sort: str) -> None:
        with pytest.raises(ValidationError):
            GitHubListRepositoriesInput(sort=sort)

    @pytest.mark.parametrize("repo_type", ["starred", "forked", ""])
    def test_invalid_type_literal(self, repo_type: str) -> None:
        with pytest.raises(ValidationError):
            GitHubListRepositoriesInput(type=repo_type)

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
