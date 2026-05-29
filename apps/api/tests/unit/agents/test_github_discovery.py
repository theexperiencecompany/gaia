"""Tests for app.agents.skills.github_discovery.

BEHAVIOR SPEC
=============

UNIT: github_discovery.py :: DiscoveredSkill
EXPECTED: Frozen dataclass; to_dict() emits exactly the 5 string keys with the
          instance values; subagent_id defaults to "global".
MUST-CATCH:
  - to_dict carries name/description/path/repo_url/subagent_id verbatim
  - the default subagent_id is the literal "global", not "" or "executor"

UNIT: github_discovery.py :: _fetch_git_tree
EXPECTED: GET the Git Tree API for owner/repo/branch; on 200 return (tree, branch);
          on 404 for branch=="main" retry once against "master"; on 403 log + return
          ([], branch); other statuses raise_for_status; tree defaults to [] if absent.
MECHANISM: httpx.AsyncClient().get(url, params={"recursive":"1"}, headers=...).
MUST-CATCH:
  - URL targets /repos/{owner}/{repo}/git/trees/{branch} (owner & repo & branch real)
  - recursive=1 param is sent (full-tree contract)
  - 404 on "main" recurses to "master" and the resolved branch flips to master
  - 404 fallback only triggers for branch=="main" (a 404 on master raises)
  - 403 returns ([], branch) without raising
  - check_tree_truncated runs on the parsed data on the success path
  - tree key missing -> [] (not KeyError)

UNIT: github_discovery.py :: _fetch_single_file_content
EXPECTED: GET raw URL; 200 -> (path, text); 404 -> None; any exception -> None.
MUST-CATCH:
  - raw URL is {RAW_BASE}/{owner}/{repo}/{branch}/{path}
  - returns the path and body text as a tuple on success
  - 404 short-circuits to None (before raise_for_status)
  - network exception is swallowed -> None

UNIT: github_discovery.py :: _fetch_file_contents_batch
EXPECTED: Fan out _fetch_single_file_content per path concurrently; keep only
          non-None, non-exception tuples.
MUST-CATCH:
  - one path per input is fetched, results preserve successful tuples
  - None results are dropped
  - a raised exception in a task is dropped (return_exceptions path)

UNIT: github_discovery.py :: _parse_skill_from_content
EXPECTED: parse SKILL.md -> DiscoveredSkill(name, description, path=folder_path,
          repo_url, subagent_id=metadata.target); parse failure -> None.
MUST-CATCH:
  - name/description/target map to the DiscoveredSkill fields
  - folder_path & repo_url are passed through, not the file content
  - parse error -> None (swallowed)

UNIT: github_discovery.py :: discover_skills_from_repo
EXPECTED: parse repo url -> fetch tree -> find SKILL.md files -> sort by priority
          -> batch fetch -> parse each -> list; empty tree -> []; no skill files -> [];
          stop at MAX_SKILLS_PER_REPO.
MUST-CATCH:
  - empty tree returns [] (no further fetching)
  - tree present but zero SKILL.md files returns []
  - valid skill content yields a DiscoveredSkill with the parsed name & folder path
  - skills are emitted in folder-priority order (root before deep folders)
  - unparseable content is skipped, valid ones still returned
  - the count is capped at MAX_SKILLS_PER_REPO

UNIT: github_discovery.py :: get_skill_from_repo
EXPECTED: same discovery, return first skill whose name == skill_name, else None;
          empty tree -> None.
MUST-CATCH:
  - empty tree returns None before any content fetch
  - returns the skill matching the requested name (not the first skill)
  - no name match -> None

EQUIVALENT MUTANTS (allowed survivors, justified): see notes at module bottom.
"""

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
from app.agents.skills.utils import GITHUB_API_BASE, GITHUB_RAW_BASE

MODULE = "app.agents.skills.github_discovery"


def _skill_md(name: str, description: str = "Does a thing", target: str = "executor") -> str:
    """Build a real SKILL.md document parseable by the production parser."""
    return (
        f"---\nname: {name}\ndescription: {description}\nsubagent_id: {target}\n---\n\n"
        f"# {name}\n\nBody content.\n"
    )


def _http_response(status_code: int, *, json_data: dict | None = None, text: str = "") -> MagicMock:
    """A stand-in httpx.Response. raise_for_status raises on >=400 like the real one."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _client_yielding(get_impl: object) -> MagicMock:
    """An async-context-manager httpx client whose .get is `get_impl`."""
    client = AsyncMock()
    client.get = get_impl
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ---------------------------------------------------------------------------
# DiscoveredSkill
# ---------------------------------------------------------------------------


class TestDiscoveredSkill:
    def test_to_dict_carries_every_field(self):
        skill = DiscoveredSkill(
            name="my-skill",
            description="A skill",
            path="skills/my-skill",
            repo_url="https://github.com/owner/repo",
            subagent_id="executor",
        )
        assert skill.to_dict() == {
            "name": "my-skill",
            "description": "A skill",
            "path": "skills/my-skill",
            "repo_url": "https://github.com/owner/repo",
            "subagent_id": "executor",
        }

    def test_default_subagent_id_is_global(self):
        skill = DiscoveredSkill(name="s", description="d", path="p", repo_url="r")
        assert skill.subagent_id == "global"


# ---------------------------------------------------------------------------
# _fetch_git_tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchGitTree:
    async def test_success_returns_tree_and_branch_with_recursive_param(self):
        captured: dict = {}

        async def fake_get(url, params=None, headers=None):
            captured["url"] = url
            captured["params"] = params
            return _http_response(
                200,
                json_data={"tree": [{"path": "a/SKILL.md", "type": "blob"}], "truncated": False},
            )

        client = _client_yielding(fake_get)
        with (
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client),
            patch(f"{MODULE}.get_github_headers", return_value={}),
        ):
            # branch omitted -> the default "main" is used and reaches the URL.
            entries, branch = await _fetch_git_tree("octo", "myrepo")

        assert entries == [{"path": "a/SKILL.md", "type": "blob"}]
        assert branch == "main"
        assert captured["url"] == f"{GITHUB_API_BASE}/repos/octo/myrepo/git/trees/main"
        assert captured["params"] == {"recursive": "1"}

    async def test_missing_tree_key_returns_empty_list(self):
        async def fake_get(url, params=None, headers=None):
            return _http_response(200, json_data={"truncated": False})

        client = _client_yielding(fake_get)
        with (
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client),
            patch(f"{MODULE}.get_github_headers", return_value={}),
        ):
            entries, branch = await _fetch_git_tree("octo", "myrepo", "main")

        assert entries == []
        assert branch == "main"

    async def test_404_on_main_falls_back_to_master(self):
        async def fake_get(url, params=None, headers=None):
            if url.endswith("/main"):
                return _http_response(404)
            assert url.endswith("/master")
            return _http_response(
                200, json_data={"tree": [{"path": "x", "type": "blob"}], "truncated": False}
            )

        client = _client_yielding(fake_get)
        with (
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client),
            patch(f"{MODULE}.get_github_headers", return_value={}),
        ):
            entries, branch = await _fetch_git_tree("octo", "myrepo", "main")

        assert branch == "master"
        assert entries == [{"path": "x", "type": "blob"}]

    async def test_404_on_master_raises_no_further_fallback(self):
        """Fallback is gated on branch=='main'; a 404 on master must raise."""

        async def fake_get(url, params=None, headers=None):
            return _http_response(404)

        client = _client_yielding(fake_get)
        with (
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client),
            patch(f"{MODULE}.get_github_headers", return_value={}),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await _fetch_git_tree("octo", "myrepo", "master")

    async def test_403_rate_limited_returns_empty_without_raising(self):
        async def fake_get(url, params=None, headers=None):
            return _http_response(403)

        client = _client_yielding(fake_get)
        with (
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client),
            patch(f"{MODULE}.get_github_headers", return_value={}),
        ):
            entries, branch = await _fetch_git_tree("octo", "myrepo", "main")

        assert entries == []
        assert branch == "main"

    async def test_truncated_tree_emits_warning(self):
        async def fake_get(url, params=None, headers=None):
            return _http_response(200, json_data={"tree": [], "truncated": True})

        client = _client_yielding(fake_get)
        with (
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client),
            patch(f"{MODULE}.get_github_headers", return_value={}),
            patch(f"{MODULE}.check_tree_truncated") as mock_check,
        ):
            await _fetch_git_tree("octo", "myrepo", "main")

        mock_check.assert_called_once_with({"tree": [], "truncated": True}, "octo", "myrepo")


# ---------------------------------------------------------------------------
# _fetch_single_file_content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchSingleFileContent:
    async def test_success_returns_path_and_text_from_raw_url(self):
        captured: dict = {}

        async def fake_get(url, headers=None):
            captured["url"] = url
            return _http_response(200, text="# Real content")

        client = _client_yielding(fake_get)
        with (
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client),
            patch(f"{MODULE}.get_github_headers", return_value={}),
        ):
            result = await _fetch_single_file_content("octo", "repo", "skills/a/SKILL.md", "dev")

        assert result == ("skills/a/SKILL.md", "# Real content")
        assert captured["url"] == f"{GITHUB_RAW_BASE}/octo/repo/dev/skills/a/SKILL.md"

    async def test_404_returns_none_without_raising(self):
        resp = _http_response(404)

        async def fake_get(url, headers=None):
            return resp

        client = _client_yielding(fake_get)
        with (
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client),
            patch(f"{MODULE}.get_github_headers", return_value={}),
        ):
            result = await _fetch_single_file_content("octo", "repo", "missing.md", "main")

        assert result is None
        # The 404 branch short-circuits to None BEFORE raise_for_status — it is a
        # distinct path from the generic-exception path.
        resp.raise_for_status.assert_not_called()

    async def test_network_exception_returns_none(self):
        async def fake_get(url, headers=None):
            raise httpx.ConnectError("boom")

        client = _client_yielding(fake_get)
        with (
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client),
            patch(f"{MODULE}.get_github_headers", return_value={}),
        ):
            result = await _fetch_single_file_content("octo", "repo", "bad.md", "main")

        assert result is None


# ---------------------------------------------------------------------------
# _fetch_file_contents_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchFileContentsBatch:
    async def test_keeps_successes_and_drops_none(self):
        with patch(
            f"{MODULE}._fetch_single_file_content",
            new_callable=AsyncMock,
            side_effect=[("a.md", "content_a"), None, ("c.md", "content_c")],
        ):
            results = await _fetch_file_contents_batch("o", "r", ["a.md", "b.md", "c.md"], "main")

        assert results == [("a.md", "content_a"), ("c.md", "content_c")]

    async def test_drops_raised_exceptions(self):
        with patch(
            f"{MODULE}._fetch_single_file_content",
            new_callable=AsyncMock,
            side_effect=[RuntimeError("boom"), ("ok.md", "ok")],
        ):
            results = await _fetch_file_contents_batch("o", "r", ["bad.md", "ok.md"], "main")

        assert results == [("ok.md", "ok")]


# ---------------------------------------------------------------------------
# _parse_skill_from_content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestParseSkillFromContent:
    async def test_maps_real_frontmatter_to_discovered_skill(self):
        content = _skill_md("my-skill", description="Helps with stuff", target="gmail_agent")

        skill = await _parse_skill_from_content(
            content, "skills/my-skill", "https://github.com/o/r"
        )

        assert skill == DiscoveredSkill(
            name="my-skill",
            description="Helps with stuff",
            path="skills/my-skill",
            repo_url="https://github.com/o/r",
            subagent_id="gmail_agent",
        )

    async def test_invalid_content_returns_none(self):
        skill = await _parse_skill_from_content(
            "no frontmatter here", "skills/x", "https://github.com/o/r"
        )
        assert skill is None


# ---------------------------------------------------------------------------
# discover_skills_from_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDiscoverSkillsFromRepo:
    async def test_empty_tree_returns_empty(self):
        with (
            patch(
                f"{MODULE}._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=([], "main"),
            ),
            patch(f"{MODULE}._fetch_file_contents_batch", new_callable=AsyncMock) as mock_batch,
        ):
            result = await discover_skills_from_repo("owner/repo")

        assert result == []
        mock_batch.assert_not_called()

    async def test_tree_without_skill_files_returns_empty(self):
        tree = [{"path": "README.md", "type": "blob"}, {"path": "src/app.py", "type": "blob"}]
        with (
            patch(
                f"{MODULE}._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ),
            patch(f"{MODULE}._fetch_file_contents_batch", new_callable=AsyncMock) as mock_batch,
        ):
            result = await discover_skills_from_repo("owner/repo")

        assert result == []
        mock_batch.assert_not_called()

    async def test_discovers_skill_with_real_path_and_name(self):
        tree = [{"path": "skills/alpha/SKILL.md", "type": "blob"}]
        with (
            patch(
                f"{MODULE}._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ) as mock_tree,
            patch(
                f"{MODULE}._fetch_file_contents_batch",
                new_callable=AsyncMock,
                return_value=[("skills/alpha/SKILL.md", _skill_md("alpha", target="executor"))],
            ),
        ):
            result = await discover_skills_from_repo("owner/repo")

        assert len(result) == 1
        assert result[0] == DiscoveredSkill(
            name="alpha",
            description="Does a thing",
            path="skills/alpha",
            repo_url="https://github.com/owner/repo",
            subagent_id="executor",
        )
        # Omitted branch defaults to "main" and is forwarded to the tree fetch.
        mock_tree.assert_awaited_once_with("owner", "repo", "main")

    async def test_sorts_by_folder_priority_root_first(self):
        """find_skill_files + priority sort runs for real: root skill outranks a deep one."""
        tree = [
            {"path": "deep/nested/SKILL.md", "type": "blob"},
            {"path": "SKILL.md", "type": "blob"},
        ]
        batch = [
            ("deep/nested/SKILL.md", _skill_md("deep-skill")),
            ("SKILL.md", _skill_md("root-skill")),
        ]
        captured_paths: dict = {}

        async def fake_batch(owner, repo, paths, branch):
            captured_paths["order"] = list(paths)
            return batch

        with (
            patch(
                f"{MODULE}._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ),
            patch(f"{MODULE}._fetch_file_contents_batch", side_effect=fake_batch),
        ):
            result = await discover_skills_from_repo("owner/repo")

        # Root (priority 0) is fetched before the deep folder (priority 10).
        assert captured_paths["order"] == ["SKILL.md", "deep/nested/SKILL.md"]
        assert {s.name for s in result} == {"root-skill", "deep-skill"}

    async def test_skips_unparseable_keeps_valid(self):
        tree = [
            {"path": "skills/good/SKILL.md", "type": "blob"},
            {"path": "skills/bad/SKILL.md", "type": "blob"},
        ]
        with (
            patch(
                f"{MODULE}._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ),
            patch(
                f"{MODULE}._fetch_file_contents_batch",
                new_callable=AsyncMock,
                return_value=[
                    ("skills/good/SKILL.md", _skill_md("good")),
                    ("skills/bad/SKILL.md", "garbage, no frontmatter"),
                ],
            ),
        ):
            result = await discover_skills_from_repo("owner/repo")

        assert [s.name for s in result] == ["good"]

    async def test_caps_at_max_skills_limit(self):
        count = 7
        tree = [{"path": f"skills/{i}/SKILL.md", "type": "blob"} for i in range(count)]
        contents = [(f"skills/{i}/SKILL.md", _skill_md(f"skill-{i}")) for i in range(count)]
        with (
            patch(
                f"{MODULE}._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ),
            patch(
                f"{MODULE}._fetch_file_contents_batch",
                new_callable=AsyncMock,
                return_value=contents,
            ),
            patch(f"{MODULE}.MAX_SKILLS_PER_REPO", 5),
        ):
            result = await discover_skills_from_repo("owner/repo")

        assert len(result) == 5


# ---------------------------------------------------------------------------
# get_skill_from_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSkillFromRepo:
    async def test_empty_tree_returns_none(self):
        with (
            patch(
                f"{MODULE}._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=([], "main"),
            ),
            patch(f"{MODULE}._fetch_file_contents_batch", new_callable=AsyncMock) as mock_batch,
        ):
            result = await get_skill_from_repo("o/r", "my-skill")

        assert result is None
        mock_batch.assert_not_called()

    async def test_returns_the_named_skill_not_the_first(self):
        tree = [
            {"path": "skills/first/SKILL.md", "type": "blob"},
            {"path": "skills/wanted/SKILL.md", "type": "blob"},
        ]
        with (
            patch(
                f"{MODULE}._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ) as mock_tree,
            patch(
                f"{MODULE}._fetch_file_contents_batch",
                new_callable=AsyncMock,
                return_value=[
                    ("skills/first/SKILL.md", _skill_md("first")),
                    ("skills/wanted/SKILL.md", _skill_md("wanted")),
                ],
            ),
        ):
            result = await get_skill_from_repo("octo/myrepo", "wanted")

        assert result is not None
        assert result.name == "wanted"
        assert result.path == "skills/wanted"
        # repo_url is built from the parsed owner/repo, not blanked.
        assert result.repo_url == "https://github.com/octo/myrepo"
        # The default branch "main" propagates to the tree fetch when omitted.
        mock_tree.assert_awaited_once_with("octo", "myrepo", "main")

    async def test_no_name_match_returns_none(self):
        tree = [{"path": "skills/other/SKILL.md", "type": "blob"}]
        with (
            patch(
                f"{MODULE}._fetch_git_tree",
                new_callable=AsyncMock,
                return_value=(tree, "main"),
            ),
            patch(
                f"{MODULE}._fetch_file_contents_batch",
                new_callable=AsyncMock,
                return_value=[("skills/other/SKILL.md", _skill_md("other"))],
            ),
        ):
            result = await get_skill_from_repo("o/r", "nonexistent")

        assert result is None
