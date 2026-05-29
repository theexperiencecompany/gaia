"""Behavior spec for app.agents.skills.installer — skill installation orchestration.

The installer fetches skill content (GitHub or inline), parses SKILL.md, writes
body-only content to the VFS, and registers flat metadata in MongoDB. These tests
import the real functions and mock ONLY at the I/O boundary (httpx client, VFS
singleton, the MongoDB-backed registry functions). Every asserted behavior maps to
a real return value, raised exception, or the exact payload handed to a boundary.

UNIT: _parse_github_url(url) -> (owner, repo, path | None)
EXPECTED: Normalize shorthand and full GitHub URLs into (owner, repo, path).
MECHANISM: strip+rstrip("/"); regex match full URL (tree|blob); else split on "/".
MUST-CATCH:
  - shorthand "owner/repo" -> path is None; "owner/repo/a/b" -> path "a/b" (not truncated)
  - full URL https://github.com/o/r -> ("o","r",None)
  - tree/blob URL extracts the trailing path segment, NOT the branch
  - trailing slash + surrounding whitespace are stripped before parsing
  - a single bare segment raises ValueError with the "Invalid GitHub reference" message

UNIT: _fetch_github_contents(owner, repo, path, client, branch="main") -> list[dict]
EXPECTED: GET the contents API; on 404@main retry master; on 404@master raise
          "Path not found"; on 403 raise rate-limit error; wrap a dict response in a list.
MECHANISM: client.get(url, params={"ref": branch}, headers=...); branch-based recursion.
MUST-CATCH:
  - request URL embeds owner/repo/path and the FIRST call uses ref="main"
  - 404 on main retries with ref="master" and returns that body
  - 404 on master raises ValueError "Path not found: owner/repo/path"
  - 403 raises ValueError mentioning the rate limit (no fallback fetch)
  - a single-object JSON body is returned wrapped as a one-element list
  - a non-404/403 error status raises via resp.raise_for_status()

UNIT: _fetch_file_content(download_url, client) -> str
EXPECTED: GET the url, raise_for_status, return resp.text.
MUST-CATCH: returns the raw body text; an HTTP error from raise_for_status propagates.

UNIT: install_from_github(user_id, repo_url, skill_path?, target_override?) -> Skill
EXPECTED: require a folder path, locate SKILL.md, validate+parse it, write the
          body-only SKILL.md to VFS, recurse the rest of the dir, register in MongoDB,
          return the installed Skill.
MUST-CATCH:
  - no path (owner/repo with no folder) raises "path to the skill folder"
  - missing SKILL.md raises "No SKILL.md"
  - invalid SKILL.md frontmatter raises "Invalid SKILL.md"
  - VFS receives BODY ONLY (no frontmatter) at "<vfs_dir>/SKILL.md" with source="github"
    metadata and the computed source_url (.../tree/main/<base_path>)
  - install_skill is called with the parsed name/description/target/body and SkillSource.GITHUB
  - target_override wins over frontmatter target; without it the frontmatter target is used
  - explicit skill_path is appended to the URL path before fetch + source_url
  - returns exactly the Skill object install_skill produced

UNIT: _download_github_dir(...) -> None (mutates file_list, writes to VFS)
EXPECTED: skip SKILL.md, write each file (body + source metadata), recurse into dirs.
MUST-CATCH:
  - SKILL.md entries are skipped (never re-written, never appended to file_list)
  - a file entry is written to "<vfs_base>/<relative_path>" with its downloaded content
    and source="github" metadata; its relative path is appended to file_list
  - a dir entry triggers a recursive fetch and its child files land in file_list

UNIT: install_from_inline(user_id, name, description, instructions, target, extra_metadata?) -> Skill
EXPECTED: generate SKILL.md, validate, parse back, write body-only to VFS, register.
MUST-CATCH:
  - VFS receives the instructions body WITHOUT frontmatter, with source="inline" metadata
  - install_skill receives SkillSource.INLINE, files=["SKILL.md"], the body, target, metadata
  - custom target propagates; extra_metadata propagates
  - invalid name / empty description raise ValueError (validation runs before any VFS write)
  - returns exactly the Skill install_skill produced

UNIT: uninstall_skill_full(user_id, skill_id) -> bool
EXPECTED: load skill; if absent return False; else delete VFS (recursive) then registry.
MUST-CATCH:
  - unknown skill -> False, with NO VFS delete and NO registry uninstall attempted
  - happy path deletes the skill's vfs_path recursively then returns the registry result
  - a VFS delete failure is swallowed; registry uninstall still runs
  - the function returns the registry uninstall result verbatim (True AND False)

EQUIVALENT MUTANTS (allowed survivors, justified): module/function docstrings and the
arguments to log.set/log.info/log.warning. Their return values are never used and the
unit tier forbids asserting on the logging framework, so str/bool mutations confined to
those call sites are behavior-preserving for every observable contract.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.agents.skills.installer import (
    _download_github_dir,
    _fetch_file_content,
    _fetch_github_contents,
    _parse_github_url,
    install_from_github,
    install_from_inline,
    uninstall_skill_full,
)
from app.agents.skills.models import Skill, SkillSource

# ---------------------------------------------------------------------------
# Patch targets (module-singleton I/O boundaries only)
# ---------------------------------------------------------------------------
_PATCH_REGISTRY_GET = "app.agents.skills.installer.get_skill"
_PATCH_REGISTRY_INSTALL = "app.agents.skills.installer.install_skill"
_PATCH_REGISTRY_UNINSTALL = "app.agents.skills.installer.uninstall_skill"
_PATCH_GET_VFS = "app.agents.skills.installer._get_vfs"
_PATCH_SKILL_PATH = "app.agents.skills.installer.get_custom_skill_path"
_PATCH_GITHUB_HEADERS = "app.agents.skills.installer.get_github_headers"
_PATCH_FETCH_CONTENTS = "app.agents.skills.installer._fetch_github_contents"
_PATCH_FETCH_FILE = "app.agents.skills.installer._fetch_file_content"

_SKILL_MD = """---
name: my-skill
description: A test skill.
target: executor
---

Do the thing.
"""


def _ok_response(json_body: object) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_body
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# _parse_github_url
# ---------------------------------------------------------------------------


class TestParseGithubUrl:
    def test_shorthand_owner_repo_has_no_path(self) -> None:
        assert _parse_github_url("owner/repo") == ("owner", "repo", None)

    def test_shorthand_keeps_full_nested_path(self) -> None:
        # Every segment after owner/repo must be preserved, not truncated.
        assert _parse_github_url("owner/repo/a/b/c/d") == ("owner", "repo", "a/b/c/d")

    def test_full_url_no_path(self) -> None:
        assert _parse_github_url("https://github.com/owner/repo") == ("owner", "repo", None)

    def test_tree_url_extracts_path_not_branch(self) -> None:
        # The branch ("main") must be discarded; only the skill path is kept.
        owner, repo, path = _parse_github_url(
            "https://github.com/owner/repo/tree/main/skills/my-skill"
        )
        assert (owner, repo, path) == ("owner", "repo", "skills/my-skill")

    def test_blob_url_extracts_path(self) -> None:
        owner, repo, path = _parse_github_url(
            "https://github.com/owner/repo/blob/dev/skills/my-skill"
        )
        assert (owner, repo, path) == ("owner", "repo", "skills/my-skill")

    def test_strips_trailing_slash_and_surrounding_whitespace(self) -> None:
        assert _parse_github_url("  owner/repo/  ") == ("owner", "repo", None)

    def test_single_segment_raises_with_message(self) -> None:
        with pytest.raises(ValueError) as exc:
            _parse_github_url("justoneword")
        # The offending reference and the period+space before the guidance must both
        # be present (the f-string interpolates the bad ref then ". " then the hint).
        assert str(exc.value).startswith("Invalid GitHub reference: justoneword. Use ")


# ---------------------------------------------------------------------------
# _fetch_github_contents
# ---------------------------------------------------------------------------


class TestFetchGithubContents:
    @patch(_PATCH_GITHUB_HEADERS, return_value={"Accept": "application/json"})
    async def test_success_targets_correct_url_and_main_branch(
        self, mock_headers: MagicMock
    ) -> None:
        body = [{"name": "SKILL.md", "type": "file"}]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=_ok_response(body))

        result = await _fetch_github_contents("octo", "proj", "skills/x", mock_client)

        assert result == body
        url_arg = mock_client.get.call_args[0][0]
        assert url_arg == "https://api.github.com/repos/octo/proj/contents/skills/x"
        # First (only) call must request the default branch.
        assert mock_client.get.call_args[1]["params"]["ref"] == "main"
        assert mock_client.get.call_args[1]["headers"] == {"Accept": "application/json"}

    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_single_dict_body_wrapped_in_list(self, mock_headers: MagicMock) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=_ok_response({"name": "SKILL.md", "type": "file"}))

        result = await _fetch_github_contents("o", "r", "p", mock_client)
        assert result == [{"name": "SKILL.md", "type": "file"}]

    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_404_main_retries_master_and_returns_body(self, mock_headers: MagicMock) -> None:
        response_404 = MagicMock(status_code=404)
        master_body = [{"name": "SKILL.md"}]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=[response_404, _ok_response(master_body)])

        result = await _fetch_github_contents("o", "r", "p", mock_client)

        assert result == master_body
        assert mock_client.get.call_args_list[0][1]["params"]["ref"] == "main"
        assert mock_client.get.call_args_list[1][1]["params"]["ref"] == "master"

    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_404_on_master_raises_path_not_found(self, mock_headers: MagicMock) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=404))

        with pytest.raises(ValueError) as exc:
            await _fetch_github_contents("o", "r", "p", mock_client, branch="master")
        assert str(exc.value) == "Path not found: o/r/p"
        # Master 404 must NOT trigger another fetch (no infinite fallback).
        assert mock_client.get.call_count == 1

    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_403_raises_rate_limit_without_fallback(self, mock_headers: MagicMock) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=403))

        with pytest.raises(ValueError, match="rate limit"):
            await _fetch_github_contents("o", "r", "p", mock_client)
        assert mock_client.get.call_count == 1

    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_other_error_status_raises_via_raise_for_status(
        self, mock_headers: MagicMock
    ) -> None:
        resp = MagicMock(status_code=500)
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=resp)
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=resp)

        with pytest.raises(httpx.HTTPStatusError):
            await _fetch_github_contents("o", "r", "p", mock_client)


# ---------------------------------------------------------------------------
# _fetch_file_content
# ---------------------------------------------------------------------------


class TestFetchFileContent:
    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_returns_body_text(self, mock_headers: MagicMock) -> None:
        resp = MagicMock(text="file content here")
        resp.raise_for_status = MagicMock()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=resp)

        result = await _fetch_file_content("https://example.com/file.md", mock_client)

        assert result == "file content here"
        assert mock_client.get.call_args[0][0] == "https://example.com/file.md"

    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_http_error_propagates(self, mock_headers: MagicMock) -> None:
        resp = MagicMock()
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=resp)
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=resp)

        with pytest.raises(httpx.HTTPStatusError):
            await _fetch_file_content("https://example.com/missing.md", mock_client)


# ---------------------------------------------------------------------------
# install_from_github
# ---------------------------------------------------------------------------


class TestInstallFromGithub:
    @patch(_PATCH_REGISTRY_INSTALL, new_callable=AsyncMock)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_SKILL_PATH, return_value="/users/u1/skills/executor/my-skill")
    @patch(_PATCH_FETCH_FILE, new_callable=AsyncMock)
    @patch(_PATCH_FETCH_CONTENTS, new_callable=AsyncMock)
    async def test_writes_body_only_and_registers_with_github_contract(
        self,
        mock_contents: AsyncMock,
        mock_file: AsyncMock,
        mock_path: MagicMock,
        mock_get_vfs: AsyncMock,
        mock_install: AsyncMock,
    ) -> None:
        mock_contents.return_value = [
            {
                "name": "SKILL.md",
                "type": "file",
                "path": "skills/my-skill/SKILL.md",
                "download_url": "https://raw.example.com/SKILL.md",
            }
        ]
        mock_file.return_value = _SKILL_MD
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs
        produced = MagicMock(spec=Skill)
        mock_install.return_value = produced

        result = await install_from_github("user1", "owner/repo/skills/my-skill")

        assert result is produced

        # VFS write contract: body-only content at <vfs_dir>/SKILL.md, github source.
        vfs_args, vfs_kwargs = mock_vfs.write.call_args
        assert vfs_args[0] == "/users/u1/skills/executor/my-skill/SKILL.md"
        assert vfs_args[1] == "Do the thing."  # body only, frontmatter stripped
        assert "---" not in vfs_args[1]
        assert vfs_args[2] == "user1"
        assert vfs_kwargs["metadata"]["source"] == "github"
        assert (
            vfs_kwargs["metadata"]["source_url"]
            == "https://github.com/owner/repo/tree/main/skills/my-skill"
        )

        # Registry contract: parsed metadata + body + GITHUB source + computed source_url.
        ik = mock_install.call_args[1]
        assert ik["user_id"] == "user1"
        assert ik["name"] == "my-skill"
        assert ik["description"] == "A test skill."
        assert ik["target"] == "executor"
        assert ik["vfs_path"] == "/users/u1/skills/executor/my-skill"
        assert ik["source"] == SkillSource.GITHUB
        assert ik["source_url"] == "https://github.com/owner/repo/tree/main/skills/my-skill"
        assert ik["body_content"] == "Do the thing."
        assert ik["files"] == ["SKILL.md"]

    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_FETCH_CONTENTS, new_callable=AsyncMock)
    async def test_missing_skill_md_raises_with_location_in_message(
        self, mock_contents: AsyncMock, mock_get_vfs: AsyncMock
    ) -> None:
        mock_contents.return_value = [{"name": "README.md", "type": "file", "path": "README.md"}]
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs

        with pytest.raises(ValueError) as exc:
            await install_from_github("user1", "owner/repo/skills/my-skill")
        msg = str(exc.value)
        # The message identifies the searched location and explains the requirement.
        assert "No SKILL.md found in owner/repo/skills/my-skill" in msg
        assert "A valid skill must contain a SKILL.md file" in msg
        mock_vfs.write.assert_not_awaited()

    async def test_no_folder_path_raises_before_any_fetch(self) -> None:
        with pytest.raises(ValueError) as exc:
            await install_from_github("user1", "owner/repo")
        msg = str(exc.value)
        assert "Provide a path to the skill folder within the repo" in msg
        assert "use skill_path parameter" in msg

    @patch(_PATCH_REGISTRY_INSTALL, new_callable=AsyncMock)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_SKILL_PATH, return_value="/users/u1/skills/gmail_agent/my-skill")
    @patch(_PATCH_FETCH_FILE, new_callable=AsyncMock)
    @patch(_PATCH_FETCH_CONTENTS, new_callable=AsyncMock)
    async def test_target_override_wins_over_frontmatter(
        self,
        mock_contents: AsyncMock,
        mock_file: AsyncMock,
        mock_path: MagicMock,
        mock_get_vfs: AsyncMock,
        mock_install: AsyncMock,
    ) -> None:
        mock_contents.return_value = [
            {
                "name": "SKILL.md",
                "type": "file",
                "path": "skill/SKILL.md",
                "download_url": "https://raw.example.com/SKILL.md",
            }
        ]
        mock_file.return_value = _SKILL_MD  # frontmatter target: executor
        mock_get_vfs.return_value = AsyncMock()
        mock_install.return_value = MagicMock(spec=Skill)

        await install_from_github("user1", "owner/repo/skill", target_override="gmail_agent")

        # Override must be used both to compute the VFS path and to register.
        assert mock_path.call_args[0][1] == "gmail_agent"
        assert mock_install.call_args[1]["target"] == "gmail_agent"

    @patch(_PATCH_REGISTRY_INSTALL, new_callable=AsyncMock)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_SKILL_PATH, return_value="/users/u1/skills/executor/my-skill")
    @patch(_PATCH_FETCH_FILE, new_callable=AsyncMock)
    @patch(_PATCH_FETCH_CONTENTS, new_callable=AsyncMock)
    async def test_without_override_uses_frontmatter_target(
        self,
        mock_contents: AsyncMock,
        mock_file: AsyncMock,
        mock_path: MagicMock,
        mock_get_vfs: AsyncMock,
        mock_install: AsyncMock,
    ) -> None:
        mock_contents.return_value = [
            {
                "name": "SKILL.md",
                "type": "file",
                "path": "skill/SKILL.md",
                "download_url": "https://raw.example.com/SKILL.md",
            }
        ]
        mock_file.return_value = _SKILL_MD  # frontmatter target: executor
        mock_get_vfs.return_value = AsyncMock()
        mock_install.return_value = MagicMock(spec=Skill)

        await install_from_github("user1", "owner/repo/skill")

        assert mock_path.call_args[0][1] == "executor"
        assert mock_install.call_args[1]["target"] == "executor"

    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_FETCH_FILE, new_callable=AsyncMock)
    @patch(_PATCH_FETCH_CONTENTS, new_callable=AsyncMock)
    async def test_invalid_skill_md_raises_before_vfs_write(
        self,
        mock_contents: AsyncMock,
        mock_file: AsyncMock,
        mock_get_vfs: AsyncMock,
    ) -> None:
        mock_contents.return_value = [
            {
                "name": "SKILL.md",
                "type": "file",
                "path": "skill/SKILL.md",
                "download_url": "https://example.com/SKILL.md",
            }
        ]
        # This name yields TWO validation errors, exercising the "; " joiner.
        mock_file.return_value = "---\nname: Bad--Name\ndescription: ok\n---\n\nBody.\n"
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs

        with pytest.raises(ValueError) as exc:
            await install_from_github("user1", "owner/repo/skill")
        msg = str(exc.value)
        assert msg.startswith("Invalid SKILL.md: ")
        # Both errors must be surfaced, joined with "; ".
        assert "lowercase alphanumeric" in msg
        assert "consecutive hyphens" in msg
        assert "; " in msg
        mock_vfs.write.assert_not_awaited()

    @patch(_PATCH_REGISTRY_INSTALL, new_callable=AsyncMock)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_SKILL_PATH, return_value="/users/u1/skills/executor/my-skill")
    @patch(_PATCH_FETCH_FILE, new_callable=AsyncMock)
    @patch(_PATCH_FETCH_CONTENTS, new_callable=AsyncMock)
    async def test_explicit_skill_path_is_appended_to_url_path(
        self,
        mock_contents: AsyncMock,
        mock_file: AsyncMock,
        mock_path: MagicMock,
        mock_get_vfs: AsyncMock,
        mock_install: AsyncMock,
    ) -> None:
        mock_contents.return_value = [
            {
                "name": "SKILL.md",
                "type": "file",
                "path": "repo-skills/inner/SKILL.md",
                "download_url": "https://raw.example.com/SKILL.md",
            }
        ]
        mock_file.return_value = _SKILL_MD
        mock_get_vfs.return_value = AsyncMock()
        mock_install.return_value = MagicMock(spec=Skill)

        # With no URL path, base_path starts empty -> f"/{skill_path}" must be
        # stripped of its leading slash so the API path is "inner", not "/inner".
        await install_from_github("user1", "owner/repo", skill_path="inner")

        # source_url must reflect the stripped base path, and the fetch must target it.
        assert mock_contents.call_args[0][2] == "inner"
        assert (
            mock_install.call_args[1]["source_url"]
            == "https://github.com/owner/repo/tree/main/inner"
        )

    @patch(_PATCH_REGISTRY_INSTALL, new_callable=AsyncMock)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_SKILL_PATH, return_value="/users/u1/skills/executor/my-skill")
    @patch(_PATCH_FETCH_FILE, new_callable=AsyncMock)
    @patch(_PATCH_FETCH_CONTENTS, new_callable=AsyncMock)
    async def test_url_path_and_skill_path_joined_with_separator(
        self,
        mock_contents: AsyncMock,
        mock_file: AsyncMock,
        mock_path: MagicMock,
        mock_get_vfs: AsyncMock,
        mock_install: AsyncMock,
    ) -> None:
        mock_contents.return_value = [
            {
                "name": "SKILL.md",
                "type": "file",
                "path": "repo-skills/inner/SKILL.md",
                "download_url": "https://raw.example.com/SKILL.md",
            }
        ]
        mock_file.return_value = _SKILL_MD
        mock_get_vfs.return_value = AsyncMock()
        mock_install.return_value = MagicMock(spec=Skill)

        # url path "repo-skills" + skill_path "inner" must join WITH a "/" separator.
        await install_from_github("user1", "owner/repo/repo-skills", skill_path="inner")

        assert mock_contents.call_args[0][2] == "repo-skills/inner"
        assert (
            mock_install.call_args[1]["source_url"]
            == "https://github.com/owner/repo/tree/main/repo-skills/inner"
        )


# ---------------------------------------------------------------------------
# _download_github_dir
# ---------------------------------------------------------------------------


class TestDownloadGithubDir:
    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_skips_skill_md_and_writes_other_file(self, mock_headers: MagicMock) -> None:
        mock_vfs = AsyncMock()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        file_resp = MagicMock(text="helper content")
        file_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=file_resp)

        contents = [
            {
                "name": "SKILL.md",
                "type": "file",
                "path": "skill/SKILL.md",
                "download_url": "https://example.com/SKILL.md",
            },
            {
                "name": "helper.py",
                "type": "file",
                "path": "skill/helper.py",
                "download_url": "https://example.com/helper.py",
            },
        ]
        file_list: list[str] = []

        await _download_github_dir(
            vfs=mock_vfs,
            user_id="user1",
            vfs_base="/skills/my-skill",
            owner="owner",
            repo="repo",
            remote_path="skill",
            contents=contents,
            file_list=file_list,
            source_url="https://github.com/owner/repo",
            client=mock_client,
        )

        # SKILL.md skipped entirely; only helper.py written + tracked.
        assert file_list == ["helper.py"]
        vfs_args, vfs_kwargs = mock_vfs.write.call_args
        assert vfs_args[0] == "/skills/my-skill/helper.py"
        assert vfs_args[1] == "helper content"
        assert vfs_args[2] == "user1"
        assert vfs_kwargs["metadata"]["source"] == "github"
        assert vfs_kwargs["metadata"]["source_url"] == "https://github.com/owner/repo"
        mock_vfs.write.assert_awaited_once()

    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_recurses_into_subdirectory(self, mock_headers: MagicMock) -> None:
        mock_vfs = AsyncMock()
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        sub_resp = _ok_response(
            [
                {
                    "name": "util.py",
                    "type": "file",
                    "path": "skill/lib/util.py",
                    "download_url": "https://example.com/util.py",
                }
            ]
        )
        file_resp = MagicMock(text="util content")
        file_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(side_effect=[sub_resp, file_resp])

        contents = [{"name": "lib", "type": "dir", "path": "skill/lib"}]
        file_list: list[str] = []

        await _download_github_dir(
            vfs=mock_vfs,
            user_id="user1",
            vfs_base="/skills/my-skill",
            owner="owner",
            repo="repo",
            remote_path="skill",
            contents=contents,
            file_list=file_list,
            source_url="https://github.com/owner/repo",
            client=mock_client,
        )

        # Child file (relative to remote_path) is written under the recursed path.
        assert file_list == ["lib/util.py"]
        assert mock_vfs.write.call_args[0][0] == "/skills/my-skill/lib/util.py"
        assert mock_vfs.write.call_args[0][1] == "util content"


# ---------------------------------------------------------------------------
# install_from_inline
# ---------------------------------------------------------------------------


class TestInstallFromInline:
    @patch(_PATCH_REGISTRY_INSTALL, new_callable=AsyncMock)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_SKILL_PATH, return_value="/users/u1/skills/executor/test-skill")
    async def test_writes_body_only_and_registers_inline_contract(
        self,
        mock_path: MagicMock,
        mock_get_vfs: AsyncMock,
        mock_install: AsyncMock,
    ) -> None:
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs
        produced = MagicMock(spec=Skill)
        mock_install.return_value = produced

        result = await install_from_inline(
            user_id="user1",
            name="test-skill",
            description="A test skill.",
            instructions="Do the thing.",
        )

        assert result is produced

        # VFS contract: body only (no frontmatter), inline source, computed path.
        vfs_args, vfs_kwargs = mock_vfs.write.call_args
        assert vfs_args[0] == "/users/u1/skills/executor/test-skill/SKILL.md"
        assert "---" not in vfs_args[1]
        assert vfs_args[1] == "Do the thing."
        assert vfs_args[2] == "user1"
        assert vfs_kwargs["metadata"] == {"source": "inline"}

        # Registry contract: INLINE source, single SKILL.md file, parsed fields.
        ik = mock_install.call_args[1]
        assert ik["user_id"] == "user1"
        assert ik["name"] == "test-skill"
        assert ik["description"] == "A test skill."
        assert ik["target"] == "executor"
        assert ik["vfs_path"] == "/users/u1/skills/executor/test-skill"
        assert ik["source"] == SkillSource.INLINE
        assert ik["body_content"] == "Do the thing."
        assert ik["files"] == ["SKILL.md"]

    @patch(_PATCH_REGISTRY_INSTALL, new_callable=AsyncMock)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_SKILL_PATH, return_value="/users/u1/skills/gmail_agent/meta-skill")
    async def test_custom_target_and_extra_metadata_propagate(
        self,
        mock_path: MagicMock,
        mock_get_vfs: AsyncMock,
        mock_install: AsyncMock,
    ) -> None:
        mock_get_vfs.return_value = AsyncMock()
        mock_install.return_value = MagicMock(spec=Skill)

        await install_from_inline(
            user_id="user1",
            name="meta-skill",
            description="With metadata.",
            instructions="Body.",
            target="gmail_agent",
            extra_metadata={"author": "tester"},
        )

        # Target threads through to the VFS path computation AND registration.
        assert mock_path.call_args[0][1] == "gmail_agent"
        ik = mock_install.call_args[1]
        assert ik["target"] == "gmail_agent"
        assert ik["metadata"] == {"author": "tester"}

    async def test_invalid_name_raises_before_vfs(self) -> None:
        with patch(_PATCH_GET_VFS, new_callable=AsyncMock) as mock_get_vfs:
            with pytest.raises(ValueError):
                await install_from_inline(
                    user_id="user1",
                    name="Invalid Name!",
                    description="Bad.",
                    instructions="Body.",
                )
            mock_get_vfs.assert_not_awaited()

    async def test_empty_description_raises_before_vfs(self) -> None:
        with patch(_PATCH_GET_VFS, new_callable=AsyncMock) as mock_get_vfs:
            with pytest.raises(ValueError):
                await install_from_inline(
                    user_id="user1",
                    name="valid-name",
                    description="",
                    instructions="Body.",
                )
            mock_get_vfs.assert_not_awaited()


# ---------------------------------------------------------------------------
# uninstall_skill_full
# ---------------------------------------------------------------------------


class TestUninstallSkillFull:
    @patch(_PATCH_REGISTRY_UNINSTALL, new_callable=AsyncMock, return_value=True)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_REGISTRY_GET, new_callable=AsyncMock)
    async def test_happy_path_deletes_vfs_recursively_then_registry(
        self,
        mock_get: AsyncMock,
        mock_get_vfs: AsyncMock,
        mock_uninstall: AsyncMock,
    ) -> None:
        skill = MagicMock(spec=Skill)
        skill.name = "test-skill"
        skill.vfs_path = "/users/u1/skills/executor/test-skill"
        mock_get.return_value = skill
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs

        result = await uninstall_skill_full("user1", "skill-id-1")

        assert result is True
        # VFS delete targets the skill's own path, recursively, scoped to the user.
        mock_vfs.delete.assert_awaited_once_with(
            "/users/u1/skills/executor/test-skill", user_id="user1", recursive=True
        )
        mock_uninstall.assert_awaited_once_with("user1", "skill-id-1")

    @patch(_PATCH_REGISTRY_UNINSTALL, new_callable=AsyncMock)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_REGISTRY_GET, new_callable=AsyncMock, return_value=None)
    async def test_unknown_skill_returns_false_without_side_effects(
        self,
        mock_get: AsyncMock,
        mock_get_vfs: AsyncMock,
        mock_uninstall: AsyncMock,
    ) -> None:
        result = await uninstall_skill_full("user1", "nonexistent")

        assert result is False
        # No VFS lookup and no registry delete when the skill does not exist.
        mock_get_vfs.assert_not_awaited()
        mock_uninstall.assert_not_awaited()

    @patch(_PATCH_REGISTRY_UNINSTALL, new_callable=AsyncMock, return_value=True)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_REGISTRY_GET, new_callable=AsyncMock)
    async def test_vfs_failure_is_swallowed_and_registry_still_runs(
        self,
        mock_get: AsyncMock,
        mock_get_vfs: AsyncMock,
        mock_uninstall: AsyncMock,
    ) -> None:
        skill = MagicMock(spec=Skill)
        skill.name = "test-skill"
        skill.vfs_path = "/path"
        mock_get.return_value = skill
        mock_vfs = AsyncMock()
        mock_vfs.delete = AsyncMock(side_effect=RuntimeError("VFS error"))
        mock_get_vfs.return_value = mock_vfs

        result = await uninstall_skill_full("user1", "skill-id-1")

        assert result is True
        mock_uninstall.assert_awaited_once_with("user1", "skill-id-1")

    @patch(_PATCH_REGISTRY_UNINSTALL, new_callable=AsyncMock, return_value=False)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_REGISTRY_GET, new_callable=AsyncMock)
    async def test_returns_registry_false_verbatim(
        self,
        mock_get: AsyncMock,
        mock_get_vfs: AsyncMock,
        mock_uninstall: AsyncMock,
    ) -> None:
        skill = MagicMock(spec=Skill)
        skill.name = "test-skill"
        skill.vfs_path = "/path"
        mock_get.return_value = skill
        mock_get_vfs.return_value = AsyncMock()

        result = await uninstall_skill_full("user1", "skill-id-1")
        assert result is False
