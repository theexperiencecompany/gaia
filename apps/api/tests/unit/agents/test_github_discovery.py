"""Tests for app.agents.skills.github_discovery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

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
from app.constants.log_tags import LogTag

SKILLS = LogTag.SKILLS


@pytest.fixture(autouse=True)
def mock_log():
    """Replace the module logger so tests can assert exact log lines."""
    with patch("app.agents.skills.github_discovery.log") as logger:
        yield logger


def _mock_http_client(response: MagicMock) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.get.return_value = response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _success_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    return response


def _status_error_response(status_code: int, url: str) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            str(status_code), request=httpx.Request("GET", url), response=response
        )
    )
    return response


# ---------------------------------------------------------------------------
# DiscoveredSkill
# ---------------------------------------------------------------------------


class TestDiscoveredSkill:
    def test_default_subagent_id(self):
        skill = DiscoveredSkill(name="s", description="d", path="p", repo_url="r")
        assert skill.subagent_id == "global"


# ---------------------------------------------------------------------------
# _fetch_git_tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchGitTree:
    async def test_successful_fetch_uses_exact_request(self):
        payload = {"tree": [{"path": "a.py", "type": "blob"}], "truncated": False}
        response = _success_response(payload)
        mock_client = _mock_http_client(response)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ) as client_cls,
            patch("app.agents.skills.github_discovery.get_github_headers", return_value={}),
            patch("app.agents.skills.github_discovery.check_tree_truncated") as check_truncated,
        ):
            entries, branch = await _fetch_git_tree("owner", "repo", "main")

        client_cls.assert_called_once_with(timeout=60.0)
        mock_client.get.assert_awaited_once_with(
            "https://api.github.com/repos/owner/repo/git/trees/main",
            params={"recursive": "1"},
            headers={},
        )
        response.raise_for_status.assert_called_once_with()
        response.json.assert_called_once_with()
        check_truncated.assert_called_once_with(payload, "owner", "repo")
        assert entries == [{"path": "a.py", "type": "blob"}]
        assert branch == "main"

    async def test_default_branch_is_main(self):
        response = _success_response({"tree": [], "truncated": False})
        mock_client = _mock_http_client(response)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch("app.agents.skills.github_discovery.get_github_headers", return_value={}),
            patch("app.agents.skills.github_discovery.check_tree_truncated"),
        ):
            entries, branch = await _fetch_git_tree("owner", "repo")

        mock_client.get.assert_awaited_once_with(
            "https://api.github.com/repos/owner/repo/git/trees/main",
            params={"recursive": "1"},
            headers={},
        )
        assert entries == []
        assert branch == "main"

    async def test_returns_empty_when_tree_key_missing(self):
        payload = {"truncated": False}
        response = _success_response(payload)
        mock_client = _mock_http_client(response)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch("app.agents.skills.github_discovery.get_github_headers", return_value={}),
            patch("app.agents.skills.github_discovery.check_tree_truncated"),
        ):
            entries, branch = await _fetch_git_tree("owner", "repo", "main")

        assert entries == []
        assert branch == "main"

    async def test_falls_back_to_master_on_main_404(self):
        master_payload = {"tree": [{"path": "b.py", "type": "blob"}], "truncated": False}
        urls = []

        async def mock_get(url, **kwargs):
            urls.append(url)
            if url.endswith("/git/trees/master"):
                return _success_response(master_payload)
            return MagicMock(status_code=404)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ) as client_cls,
            patch("app.agents.skills.github_discovery.get_github_headers", return_value={}),
            patch("app.agents.skills.github_discovery.check_tree_truncated") as check_truncated,
        ):
            entries, branch = await _fetch_git_tree("owner", "repo", "main")

        assert urls == [
            "https://api.github.com/repos/owner/repo/git/trees/main",
            "https://api.github.com/repos/owner/repo/git/trees/master",
        ]
        client_cls.assert_called_with(timeout=60.0)
        assert client_cls.call_count == 2
        check_truncated.assert_called_once_with(master_payload, "owner", "repo")
        assert entries == [{"path": "b.py", "type": "blob"}]
        assert branch == "master"

    async def test_rate_limited_returns_empty_and_warns(self, mock_log):
        response = MagicMock(status_code=403)
        mock_client = _mock_http_client(response)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch("app.agents.skills.github_discovery.get_github_headers", return_value={}),
        ):
            entries, branch = await _fetch_git_tree("owner", "repo", "develop")

        assert entries == []
        assert branch == "develop"
        mock_client.get.assert_awaited_once()
        response.raise_for_status.assert_not_called()
        mock_log.warning.assert_called_once_with(
            f"{SKILLS} GitHub rate limited. Set GITHUB_TOKEN for higher limits"
        )

    async def test_404_on_non_main_branch_propagates(self):
        url = "https://api.github.com/repos/owner/repo/git/trees/develop"
        urls = []

        async def mock_get(url, **kwargs):
            urls.append(url)
            return _status_error_response(404, url)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch("app.agents.skills.github_discovery.get_github_headers", return_value={}),
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await _fetch_git_tree("owner", "repo", "develop")

        assert urls == [url]


# ---------------------------------------------------------------------------
# _fetch_single_file_content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchSingleFileContent:
    async def test_successful_fetch_uses_exact_request(self):
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()
        response.text = "# Content"
        mock_client = _mock_http_client(response)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ) as client_cls,
            patch("app.agents.skills.github_discovery.get_github_headers", return_value={}),
        ):
            result = await _fetch_single_file_content("owner", "repo", "SKILL.md", "main")

        client_cls.assert_called_once_with(timeout=30.0)
        mock_client.get.assert_awaited_once_with(
            "https://raw.githubusercontent.com/owner/repo/main/SKILL.md",
            headers={},
        )
        response.raise_for_status.assert_called_once_with()
        assert result == ("SKILL.md", "# Content")

    async def test_returns_none_on_404_without_retry(self, mock_log):
        response = MagicMock(status_code=404)
        mock_client = _mock_http_client(response)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch("app.agents.skills.github_discovery.get_github_headers", return_value={}),
        ):
            result = await _fetch_single_file_content("owner", "repo", "missing.md", "main")

        assert result is None
        mock_client.get.assert_awaited_once_with(
            "https://raw.githubusercontent.com/owner/repo/main/missing.md",
            headers={},
        )
        response.raise_for_status.assert_not_called()
        mock_log.debug.assert_called_once_with(f"{SKILLS} File not found", file_path="missing.md")

    async def test_returns_none_on_http_error(self, mock_log):
        url = "https://raw.githubusercontent.com/owner/repo/main/bad.md"
        mock_client = _mock_http_client(_status_error_response(500, url))

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch("app.agents.skills.github_discovery.get_github_headers", return_value={}),
        ):
            result = await _fetch_single_file_content("owner", "repo", "bad.md", "main")

        assert result is None
        mock_log.debug.assert_called_once_with(
            f"{SKILLS} Failed to fetch file", file_path="bad.md", error_type="HTTPStatusError"
        )

    async def test_returns_none_on_network_error(self, mock_log):
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("fail")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.agents.skills.github_discovery.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch("app.agents.skills.github_discovery.get_github_headers", return_value={}),
        ):
            result = await _fetch_single_file_content("owner", "repo", "bad.md", "main")

        assert result is None
        mock_log.debug.assert_called_once_with(
            f"{SKILLS} Failed to fetch file", file_path="bad.md", error_type="ConnectError"
        )


# ---------------------------------------------------------------------------
# _fetch_file_contents_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchFileContentsBatch:
    async def test_gathers_results_in_order(self):
        fetcher = AsyncMock(side_effect=[("a.md", "content_a"), None, ("c.md", "content_c")])
        with patch("app.agents.skills.github_discovery._fetch_single_file_content", fetcher):
            results = await _fetch_file_contents_batch(
                "owner", "repo", ["a.md", "b.md", "c.md"], "main"
            )

        assert results == [("a.md", "content_a"), ("c.md", "content_c")]
        fetcher.assert_has_awaits(
            [
                call("owner", "repo", "a.md", "main"),
                call("owner", "repo", "b.md", "main"),
                call("owner", "repo", "c.md", "main"),
            ]
        )

    async def test_skips_raised_exceptions_and_base_exception_results(self, mock_log):
        def fetcher_side_effect(owner, repo, path, branch):
            if path == "bad.md":
                raise RuntimeError("boom")
            if path == "interrupt.md":
                return KeyboardInterrupt("ctrl-c")
            return ("ok.md", "ok")

        fetcher = AsyncMock(side_effect=fetcher_side_effect)
        with patch("app.agents.skills.github_discovery._fetch_single_file_content", fetcher):
            results = await _fetch_file_contents_batch(
                "owner", "repo", ["bad.md", "interrupt.md", "ok.md"], "main"
            )

        assert results == [("ok.md", "ok")]
        mock_log.debug.assert_has_calls(
            [
                call(f"{SKILLS} Exception fetching file", error_type="RuntimeError"),
                call(f"{SKILLS} Exception fetching file", error_type="KeyboardInterrupt"),
            ]
        )


# ---------------------------------------------------------------------------
# _parse_skill_from_content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestParseSkillFromContent:
    async def test_parses_valid_skill_with_all_fields(self):
        metadata = SimpleNamespace(name="my-skill", description="desc", target="executor")
        with patch(
            "app.agents.skills.github_discovery.parse_skill_md",
            return_value=(metadata, "body"),
        ) as parse:
            skill = await _parse_skill_from_content(
                "content", "skills/my-skill", "https://github.com/o/r"
            )

        parse.assert_called_once_with("content")
        assert skill == DiscoveredSkill(
            name="my-skill",
            description="desc",
            path="skills/my-skill",
            repo_url="https://github.com/o/r",
            subagent_id="executor",
        )

    async def test_returns_none_on_parse_error(self, mock_log):
        with patch(
            "app.agents.skills.github_discovery.parse_skill_md",
            side_effect=ValueError("bad"),
        ):
            skill = await _parse_skill_from_content("bad content", "path", "https://github.com/o/r")

        assert skill is None
        mock_log.debug.assert_called_once_with(
            f"{SKILLS} Failed to parse SKILL.md", folder_path="path", error_type="ValueError"
        )


# ---------------------------------------------------------------------------
# discover_skills_from_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDiscoverSkillsFromRepo:
    async def test_returns_empty_when_no_tree(self, mock_log):
        with (
            patch(
                "app.agents.skills.github_discovery._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=([], "main"),
            ) as fetch_tree,
            patch("app.agents.skills.github_discovery.find_skill_files") as find_files,
            patch(
                "app.agents.skills.github_discovery._fetch_file_contents_batch",
                new_callable=AsyncMock,
            ) as fetch_batch,
        ):
            result = await discover_skills_from_repo("owner/repo")

        assert result == []
        fetch_tree.assert_awaited_once_with("owner", "repo", "main")
        find_files.assert_not_called()
        fetch_batch.assert_not_called()
        mock_log.info.assert_called_once_with(
            f"{SKILLS} Discovering skills in repo", owner="owner", repo="repo"
        )
        mock_log.warning.assert_called_once_with(
            f"{SKILLS} No tree entries found in repo", owner="owner", repo="repo"
        )

    async def test_returns_empty_when_no_skill_files(self, mock_log):
        tree = [{"path": "readme.md", "type": "blob"}]
        with (
            patch(
                "app.agents.skills.github_discovery._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_file_contents_batch",
                new_callable=AsyncMock,
            ) as fetch_batch,
            patch("app.agents.skills.github_discovery.get_folder_priority") as get_priority,
        ):
            result = await discover_skills_from_repo("owner/repo")

        assert result == []
        fetch_batch.assert_not_called()
        get_priority.assert_not_called()
        mock_log.info.assert_has_calls(
            [
                call(f"{SKILLS} Discovering skills in repo", owner="owner", repo="repo"),
                call(
                    f"{SKILLS} Fetched repo tree",
                    entry_count=1,
                    owner="owner",
                    repo="repo",
                    branch="main",
                ),
                call(f"{SKILLS} No SKILL.md files found in repo", owner="owner", repo="repo"),
            ]
        )

    async def test_discovers_and_sorts_skills(self, mock_log):
        tree = [
            {"path": "skills/a/SKILL.md", "type": "blob"},
            {"path": "SKILL.md", "type": "blob"},
            {"path": "docs/readme.md", "type": "blob"},
            {"path": "z-other/SKILL.md", "type": "blob"},
            {"path": "skills/b/skill.md", "type": "blob"},
            {"path": "assets/", "type": "tree"},
        ]
        parsed = {
            "skills/a/SKILL.md": SimpleNamespace(
                name="a-skill", description="A", target="executor"
            ),
            "SKILL.md": SimpleNamespace(name="root-skill", description="R", target="comms"),
            "z-other/SKILL.md": SimpleNamespace(name="z-skill", description="Z", target="executor"),
            "skills/b/skill.md": SimpleNamespace(name="b-skill", description="B", target="global"),
        }

        def parse_side_effect(content: str):
            for path, metadata in parsed.items():
                if content == f"content of {path}":
                    return metadata, "body"
            raise AssertionError(f"unexpected content: {content!r}")

        with (
            patch(
                "app.agents.skills.github_discovery._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ) as fetch_tree,
            patch(
                "app.agents.skills.github_discovery._fetch_file_contents_batch",
                new_callable=AsyncMock,
                side_effect=lambda owner, repo, paths, branch: [
                    (path, f"content of {path}") for path in paths
                ],
            ) as fetch_batch,
            patch(
                "app.agents.skills.github_discovery.parse_skill_md",
                side_effect=parse_side_effect,
            ) as parse,
        ):
            result = await discover_skills_from_repo("owner/repo")

        fetch_tree.assert_awaited_once_with("owner", "repo", "main")
        fetch_batch.assert_awaited_once_with(
            "owner",
            "repo",
            ["SKILL.md", "skills/a/SKILL.md", "z-other/SKILL.md", "skills/b/skill.md"],
            "main",
        )
        assert [s.name for s in result] == ["root-skill", "a-skill", "z-skill", "b-skill"]
        assert [s.path for s in result] == ["", "skills/a", "z-other", "skills/b"]
        assert [s.repo_url for s in result] == ["https://github.com/owner/repo"] * 4
        assert [s.subagent_id for s in result] == ["comms", "executor", "executor", "global"]
        assert parse.call_count == 4
        mock_log.set.assert_called_once_with(skill={"operation": "list"})
        mock_log.info.assert_has_calls(
            [
                call(f"{SKILLS} Discovering skills in repo", owner="owner", repo="repo"),
                call(
                    f"{SKILLS} Fetched repo tree",
                    entry_count=6,
                    owner="owner",
                    repo="repo",
                    branch="main",
                ),
                call(f"{SKILLS} Found potential skill files", skill_file_count=4),
                call(
                    f"{SKILLS} Found valid skills in repo",
                    skill_count=4,
                    owner="owner",
                    repo="repo",
                ),
            ]
        )
        mock_log.debug.assert_has_calls(
            [
                call(f"{SKILLS} Parsed skill", skill_name="root-skill", folder_path=""),
                call(f"{SKILLS} Parsed skill", skill_name="a-skill", folder_path="skills/a"),
                call(f"{SKILLS} Parsed skill", skill_name="z-skill", folder_path="z-other"),
                call(f"{SKILLS} Parsed skill", skill_name="b-skill", folder_path="skills/b"),
            ]
        )
        mock_log.set_ns.assert_called_once_with("skill", result_count=4)

    async def test_respects_max_skills_limit(self, mock_log):
        tree = [{"path": f"skills/{i}/SKILL.md", "type": "blob"} for i in range(200)]
        contents = [(f"skills/{i}/SKILL.md", f"content_{i}") for i in range(200)]
        metadata = SimpleNamespace(name="s", description="d", target="executor")
        with (
            patch(
                "app.agents.skills.github_discovery._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_file_contents_batch",
                new_callable=AsyncMock,
                return_value=contents,
            ),
            patch(
                "app.agents.skills.github_discovery.parse_skill_md",
                return_value=(metadata, "body"),
            ) as parse,
            patch("app.agents.skills.github_discovery.MAX_SKILLS_PER_REPO", 5),
        ):
            result = await discover_skills_from_repo("o/r")

        assert len(result) == 5
        assert parse.call_count == 5
        mock_log.warning.assert_called_once_with(f"{SKILLS} Reached max skills limit", max_skills=5)
        mock_log.set_ns.assert_called_once_with("skill", result_count=5)


# ---------------------------------------------------------------------------
# get_skill_from_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSkillFromRepo:
    async def test_returns_none_when_no_tree(self, mock_log):
        with (
            patch(
                "app.agents.skills.github_discovery._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=([], "main"),
            ) as fetch_tree,
            patch("app.agents.skills.github_discovery.find_skill_files") as find_files,
            patch(
                "app.agents.skills.github_discovery._fetch_file_contents_batch",
                new_callable=AsyncMock,
            ) as fetch_batch,
        ):
            result = await get_skill_from_repo("o/r", "my-skill")

        assert result is None
        fetch_tree.assert_awaited_once_with("o", "r", "main")
        find_files.assert_not_called()
        fetch_batch.assert_not_called()
        mock_log.set.assert_called_once_with(skill={"operation": "get", "skill_name": "my-skill"})
        mock_log.info.assert_called_once_with(
            f"{SKILLS} Looking for skill in repo", skill_name="my-skill", owner="o", repo="r"
        )

    async def test_finds_matching_skill(self, mock_log):
        tree = [
            {"path": "skills/broken/SKILL.md", "type": "blob"},
            {"path": "skills/other/SKILL.md", "type": "blob"},
            {"path": "skills/target/SKILL.md", "type": "blob"},
        ]
        skill_files = [
            "skills/broken/SKILL.md",
            "skills/other/SKILL.md",
            "skills/target/SKILL.md",
        ]
        contents = [
            ("skills/broken/SKILL.md", "broken content"),
            ("skills/other/SKILL.md", "other content"),
            ("skills/target/SKILL.md", "target content"),
        ]

        def parse_side_effect(content: str):
            if content == "broken content":
                raise ValueError("bad skill")
            if content == "other content":
                return SimpleNamespace(
                    name="other-skill", description="d", target="executor"
                ), "body"
            if content == "target content":
                return SimpleNamespace(
                    name="target-skill", description="d", target="executor"
                ), "body"
            raise AssertionError(f"unexpected content: {content!r}")

        with (
            patch(
                "app.agents.skills.github_discovery._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_file_contents_batch",
                new_callable=AsyncMock,
                return_value=contents,
            ) as fetch_batch,
            patch(
                "app.agents.skills.github_discovery.parse_skill_md",
                side_effect=parse_side_effect,
            ),
        ):
            result = await get_skill_from_repo("o/r", "target-skill")

        assert result == DiscoveredSkill(
            name="target-skill",
            description="d",
            path="skills/target",
            repo_url="https://github.com/o/r",
            subagent_id="executor",
        )
        fetch_batch.assert_awaited_once_with("o", "r", skill_files, "main")
        mock_log.set.assert_called_once_with(
            skill={"operation": "get", "skill_name": "target-skill"}
        )
        mock_log.info.assert_has_calls(
            [
                call(
                    f"{SKILLS} Looking for skill in repo",
                    skill_name="target-skill",
                    owner="o",
                    repo="r",
                ),
                call(
                    f"{SKILLS} Found skill", skill_name="target-skill", folder_path="skills/target"
                ),
            ]
        )
        mock_log.set_ns.assert_called_once_with("skill", success=True)

    async def test_returns_none_when_skill_not_found(self, mock_log):
        tree = [{"path": "skills/other/SKILL.md", "type": "blob"}]
        contents = [("skills/other/SKILL.md", "content")]
        metadata = SimpleNamespace(name="other-skill", description="d", target="executor")
        with (
            patch(
                "app.agents.skills.github_discovery._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ),
            patch(
                "app.agents.skills.github_discovery._fetch_file_contents_batch",
                new_callable=AsyncMock,
                return_value=contents,
            ),
            patch(
                "app.agents.skills.github_discovery.parse_skill_md",
                return_value=(metadata, "body"),
            ),
        ):
            result = await get_skill_from_repo("o/r", "nonexistent")

        assert result is None
        mock_log.info.assert_has_calls(
            [
                call(
                    f"{SKILLS} Looking for skill in repo",
                    skill_name="nonexistent",
                    owner="o",
                    repo="r",
                ),
                call(
                    f"{SKILLS} Skill not found in repo",
                    skill_name="nonexistent",
                    owner="o",
                    repo="r",
                ),
            ]
        )
        mock_log.set_ns.assert_called_once_with("skill", success=False)
