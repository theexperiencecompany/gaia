"""Unit tests for the Composio GitHub tools schemas (github_tools.py)."""

from app.models.composio_schemas.github_tools import GitHubListRepositoriesData


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
