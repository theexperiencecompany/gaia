"""Tests for app.agents.skills.github_discovery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.agents.skills.github_discovery import (
    DiscoveredSkill,
    _fetch_file_contents_batch,
    _fetch_git_tree,
    _fetch_single_file_content,
    _parse_skill_from_content,
    discover_skills_from_repo,
    get_skill_from_repo,
)


# ---------------------------------------------------------------------------
# DiscoveredSkill
# ---------------------------------------------------------------------------


class TestDiscoveredSkill:
    def test_to_dict(self):
        skill = DiscoveredSkill(
            name="my-skill",
            description="A skill",
            path="skills/my-skill",
            repo_url="https://github.com/owner/repo",
            subagent_id="executor",
        )
        d = skill.to_dict()
        assert d["name"] == "my-skill"
        assert d["path"] == "skills/my-skill"
        assert d["subagent_id"] == "executor"

    def test_default_subagent_id(self):
        skill = DiscoveredSkill(name="s", description="d", path="p", repo_url="r")
        assert skill.subagent_id == "global"


# ---------------------------------------------------------------------------
# _fetch_git_tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchGitTree:
    async def test_successful_fetch(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "tree": [{"path": "a.py", "type": "blob"}],
            "truncated": False,
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "app.agents.skills.github_discovery.get_github_headers", return_value={}
            ),
            patch("app.agents.skills.github_discovery.check_tree_truncated"),
        ):
            entries, branch = await _fetch_git_tree("owner", "repo", "main")

        assert len(entries) == 1
        assert branch == "main"

    async def test_fallback_to_master_on_404(self):
        mock_404 = MagicMock()
        mock_404.status_code = 404
        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.raise_for_status = MagicMock()
        mock_200.json.return_value = {"tree": [{"path": "b.py"}], "truncated": False}

        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "main" in url:
                return mock_404
            return mock_200

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "app.agents.skills.github_discovery.get_github_headers", return_value={}
            ),
            patch("app.agents.skills.github_discovery.check_tree_truncated"),
        ):
            entries, branch = await _fetch_git_tree("owner", "repo", "main")

        assert branch == "master"

    async def test_rate_limited_returns_empty(self):
        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "app.agents.skills.github_discovery.get_github_headers", return_value={}
            ),
        ):
            entries, branch = await _fetch_git_tree("owner", "repo", "main")

        assert entries == []


# ---------------------------------------------------------------------------
# _fetch_single_file_content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchSingleFileContent:
    async def test_successful_fetch(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = "# Content"

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "app.agents.skills.github_discovery.get_github_headers", return_value={}
            ),
        ):
            result = await _fetch_single_file_content(
                "owner", "repo", "SKILL.md", "main"
            )

        assert result == ("SKILL.md", "# Content")

    async def test_returns_none_on_404(self):
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "app.agents.skills.github_discovery.get_github_headers", return_value={}
            ),
        ):
            result = await _fetch_single_file_content(
                "owner", "repo", "missing.md", "main"
            )

        assert result is None

    async def test_returns_none_on_exception(self):
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("fail")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "app.agents.skills.github_discovery.get_github_headers", return_value={}
            ),
        ):
            result = await _fetch_single_file_content("owner", "repo", "bad.md", "main")

        assert result is None


# ---------------------------------------------------------------------------
# _fetch_file_contents_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchFileContentsBatch:
    async def test_gathers_results(self):
        with patch(
            "app.agents.skills.github_discovery._fetch_single_file_content",
            new_callable=AsyncMock,
            side_effect=[
                ("a.md", "content_a"),
                None,
                ("c.md", "content_c"),
            ],
        ):
            results = await _fetch_file_contents_batch(
                "owner", "repo", ["a.md", "b.md", "c.md"], "main"
            )
        assert len(results) == 2

    async def test_handles_exceptions_in_tasks(self):
        with patch(
            "app.agents.skills.github_discovery._fetch_single_file_content",
            new_callable=AsyncMock,
            side_effect=[RuntimeError("boom"), ("ok.md", "ok")],
        ):
            results = await _fetch_file_contents_batch(
                "owner", "repo", ["bad.md", "ok.md"], "main"
            )
        assert len(results) == 1


# ---------------------------------------------------------------------------
# _parse_skill_from_content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestParseSkillFromContent:
    async def test_parses_valid_skill(self):
        metadata = SimpleNamespace(
            name="my-skill",
            description="desc",
            target="executor",
        )
        with patch(
            "app.agents.skills.github_discovery.parse_skill_md",
            return_value=(metadata, "body"),
        ):
            skill = await _parse_skill_from_content(
                "content", "skills/my-skill", "https://github.com/o/r"
            )
        assert skill is not None
        assert skill.name == "my-skill"
        assert skill.path == "skills/my-skill"

    async def test_returns_none_on_parse_error(self):
        with patch(
            "app.agents.skills.github_discovery.parse_skill_md",
            side_effect=ValueError("bad"),
        ):
            skill = await _parse_skill_from_content(
                "bad content", "path", "https://github.com/o/r"
            )
        assert skill is None


# ---------------------------------------------------------------------------
# discover_skills_from_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDiscoverSkillsFromRepo:
    async def test_returns_empty_when_no_tree(self):
        with (
            patch(
                "app.agents.skills.github_discovery.parse_github_url",
                return_value=("owner", "repo"),
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=([], "main"),
            ),
        ):
            result = await discover_skills_from_repo("owner/repo")
        assert result == []

    async def test_returns_empty_when_no_skill_files(self):
        tree = [{"path": "readme.md", "type": "blob"}]
        with (
            patch(
                "app.agents.skills.github_discovery.parse_github_url",
                return_value=("owner", "repo"),
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ),
            patch(
                "app.agents.skills.github_discovery.find_skill_files",
                return_value=[],
            ),
        ):
            result = await discover_skills_from_repo("owner/repo")
        assert result == []

    async def test_discovers_skills(self):
        tree = [{"path": "skills/a/SKILL.md", "type": "blob"}]
        metadata = SimpleNamespace(name="skill-a", description="A", target="executor")
        with (
            patch(
                "app.agents.skills.github_discovery.parse_github_url",
                return_value=("owner", "repo"),
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ),
            patch(
                "app.agents.skills.github_discovery.find_skill_files",
                return_value=["skills/a/SKILL.md"],
            ),
            patch(
                "app.agents.skills.github_discovery.get_folder_priority",
                return_value=1,
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_file_contents_batch",
                new_callable=AsyncMock,
                return_value=[("skills/a/SKILL.md", "content")],
            ),
            patch(
                "app.agents.skills.github_discovery.get_folder_path",
                return_value="skills/a",
            ),
            patch(
                "app.agents.skills.github_discovery.parse_skill_md",
                return_value=(metadata, "body"),
            ),
        ):
            result = await discover_skills_from_repo("owner/repo")
        assert len(result) == 1
        assert result[0].name == "skill-a"

    async def test_respects_max_skills_limit(self):
        tree = [{"path": f"skills/{i}/SKILL.md", "type": "blob"} for i in range(200)]
        skill_files = [f"skills/{i}/SKILL.md" for i in range(200)]
        contents = [(f"skills/{i}/SKILL.md", f"content_{i}") for i in range(200)]

        metadata = SimpleNamespace(name="s", description="d", target="executor")
        with (
            patch(
                "app.agents.skills.github_discovery.parse_github_url",
                return_value=("o", "r"),
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ),
            patch(
                "app.agents.skills.github_discovery.find_skill_files",
                return_value=skill_files,
            ),
            patch(
                "app.agents.skills.github_discovery.get_folder_priority", return_value=1
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_file_contents_batch",
                new_callable=AsyncMock,
                return_value=contents,
            ),
            patch(
                "app.agents.skills.github_discovery.get_folder_path",
                return_value="path",
            ),
            patch(
                "app.agents.skills.github_discovery.parse_skill_md",
                return_value=(metadata, "body"),
            ),
            patch("app.agents.skills.github_discovery.MAX_SKILLS_PER_REPO", 5),
        ):
            result = await discover_skills_from_repo("o/r")
        assert len(result) == 5


# ---------------------------------------------------------------------------
# get_skill_from_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSkillFromRepo:
    async def test_returns_none_when_no_tree(self):
        with (
            patch(
                "app.agents.skills.github_discovery.parse_github_url",
                return_value=("o", "r"),
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=([], "main"),
            ),
        ):
            result = await get_skill_from_repo("o/r", "my-skill")
        assert result is None

    async def test_finds_matching_skill(self):
        metadata = SimpleNamespace(
            name="target-skill", description="d", target="executor"
        )
        with (
            patch(
                "app.agents.skills.github_discovery.parse_github_url",
                return_value=("o", "r"),
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=([{"type": "blob", "path": "SKILL.md"}], "main"),
            ),
            patch(
                "app.agents.skills.github_discovery.find_skill_files",
                return_value=["skills/target/SKILL.md"],
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_file_contents_batch",
                new_callable=AsyncMock,
                return_value=[("skills/target/SKILL.md", "content")],
            ),
            patch(
                "app.agents.skills.github_discovery.get_folder_path",
                return_value="skills/target",
            ),
            patch(
                "app.agents.skills.github_discovery.parse_skill_md",
                return_value=(metadata, "body"),
            ),
        ):
            result = await get_skill_from_repo("o/r", "target-skill")
        assert result is not None
        assert result.name == "target-skill"

    async def test_returns_none_when_skill_not_found(self):
        metadata = SimpleNamespace(
            name="other-skill", description="d", target="executor"
        )
        with (
            patch(
                "app.agents.skills.github_discovery.parse_github_url",
                return_value=("o", "r"),
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=([{"type": "blob"}], "main"),
            ),
            patch(
                "app.agents.skills.github_discovery.find_skill_files",
                return_value=["SKILL.md"],
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_file_contents_batch",
                new_callable=AsyncMock,
                return_value=[("SKILL.md", "content")],
            ),
            patch(
                "app.agents.skills.github_discovery.get_folder_path", return_value=""
            ),
            patch(
                "app.agents.skills.github_discovery.parse_skill_md",
                return_value=(metadata, "body"),
            ),
        ):
            result = await get_skill_from_repo("o/r", "nonexistent")
        assert result is None
