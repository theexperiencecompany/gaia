"""Unit tests for app.agents.skills.installer — GitHub and inline skill installation."""

from typing import List
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
# Patch targets
# ---------------------------------------------------------------------------
_PATCH_REGISTRY_GET = "app.agents.skills.installer.get_skill"
_PATCH_REGISTRY_INSTALL = "app.agents.skills.installer.install_skill"
_PATCH_REGISTRY_UNINSTALL = "app.agents.skills.installer.uninstall_skill"
_PATCH_GET_VFS = "app.agents.skills.installer._get_vfs"
_PATCH_SKILL_PATH = "app.agents.skills.installer.get_custom_skill_path"
_PATCH_GITHUB_HEADERS = "app.agents.skills.installer.get_github_headers"


# ---------------------------------------------------------------------------
# _parse_github_url
# ---------------------------------------------------------------------------


class TestParseGithubUrl:
    """Tests for _parse_github_url."""

    def test_shorthand_owner_repo(self) -> None:
        owner, repo, path = _parse_github_url("owner/repo")
        assert owner == "owner"
        assert repo == "repo"
        assert path is None

    def test_shorthand_owner_repo_path(self) -> None:
        owner, repo, path = _parse_github_url("owner/repo/skills/my-skill")
        assert owner == "owner"
        assert repo == "repo"
        assert path == "skills/my-skill"

    def test_full_url(self) -> None:
        owner, repo, path = _parse_github_url("https://github.com/owner/repo")
        assert owner == "owner"
        assert repo == "repo"
        assert path is None

    def test_full_url_with_tree_path(self) -> None:
        owner, repo, path = _parse_github_url(
            "https://github.com/owner/repo/tree/main/skills/my-skill"
        )
        assert owner == "owner"
        assert repo == "repo"
        assert path == "skills/my-skill"

    def test_full_url_with_blob_path(self) -> None:
        owner, repo, path = _parse_github_url(
            "https://github.com/owner/repo/blob/main/skills/my-skill"
        )
        assert owner == "owner"
        assert repo == "repo"
        assert path == "skills/my-skill"

    def test_trailing_slash_stripped(self) -> None:
        owner, repo, path = _parse_github_url("owner/repo/")
        assert owner == "owner"
        assert repo == "repo"
        assert path is None

    def test_whitespace_stripped(self) -> None:
        owner, repo, path = _parse_github_url("  owner/repo  ")
        assert owner == "owner"
        assert repo == "repo"

    def test_invalid_single_segment_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid GitHub reference"):
            _parse_github_url("justoneword")

    def test_http_url(self) -> None:
        owner, repo, path = _parse_github_url("https://github.com/owner/repo")
        assert owner == "owner"
        assert repo == "repo"

    def test_deep_path(self) -> None:
        owner, repo, path = _parse_github_url("owner/repo/a/b/c/d")
        assert owner == "owner"
        assert repo == "repo"
        assert path == "a/b/c/d"


# ---------------------------------------------------------------------------
# _fetch_github_contents
# ---------------------------------------------------------------------------


class TestFetchGithubContents:
    """Tests for _fetch_github_contents."""

    @patch(_PATCH_GITHUB_HEADERS, return_value={"Accept": "application/json"})
    async def test_returns_list_on_success(self, mock_headers: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"name": "SKILL.md", "type": "file"}]
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await _fetch_github_contents("owner", "repo", "path", mock_client)
        assert result == [{"name": "SKILL.md", "type": "file"}]

    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_returns_single_file_as_list(self, mock_headers: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"name": "SKILL.md", "type": "file"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await _fetch_github_contents("owner", "repo", "path", mock_client)
        assert result == [{"name": "SKILL.md", "type": "file"}]

    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_404_falls_back_to_master(self, mock_headers: MagicMock) -> None:
        response_404 = MagicMock()
        response_404.status_code = 404

        response_ok = MagicMock()
        response_ok.status_code = 200
        response_ok.json.return_value = [{"name": "SKILL.md"}]
        response_ok.raise_for_status = MagicMock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=[response_404, response_ok])

        result = await _fetch_github_contents("owner", "repo", "path", mock_client)
        assert result == [{"name": "SKILL.md"}]
        # Second call should use master branch
        second_call = mock_client.get.call_args_list[1]
        assert second_call[1]["params"]["ref"] == "master"

    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_404_on_master_raises(self, mock_headers: MagicMock) -> None:
        response_404 = MagicMock()
        response_404.status_code = 404

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=response_404)

        with pytest.raises(ValueError, match="Path not found"):
            await _fetch_github_contents(
                "owner", "repo", "path", mock_client, branch="master"
            )

    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_403_raises_rate_limit(self, mock_headers: MagicMock) -> None:
        response_403 = MagicMock()
        response_403.status_code = 403

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=response_403)

        with pytest.raises(ValueError, match="rate limit"):
            await _fetch_github_contents("owner", "repo", "path", mock_client)


# ---------------------------------------------------------------------------
# _fetch_file_content
# ---------------------------------------------------------------------------


class TestFetchFileContent:
    """Tests for _fetch_file_content."""

    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_returns_text(self, mock_headers: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.text = "file content here"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await _fetch_file_content("https://example.com/file.md", mock_client)
        assert result == "file content here"


# ---------------------------------------------------------------------------
# install_from_github
# ---------------------------------------------------------------------------


class TestInstallFromGithub:
    """Tests for install_from_github."""

    @patch(_PATCH_REGISTRY_INSTALL, new_callable=AsyncMock)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_SKILL_PATH, return_value="/users/u1/skills/executor/my-skill")
    async def test_install_from_github_success(
        self,
        mock_path: MagicMock,
        mock_get_vfs: AsyncMock,
        mock_install: AsyncMock,
    ) -> None:
        skill_md_content = """---
name: my-skill
description: A test skill.
target: executor
---

Do the thing.
"""
        # Mock VFS
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs

        # Mock Skill returned by registry
        mock_skill = MagicMock(spec=Skill)
        mock_install.return_value = mock_skill

        with (
            patch(
                "app.agents.skills.installer._fetch_github_contents",
                new_callable=AsyncMock,
            ) as mock_contents,
            patch(
                "app.agents.skills.installer._fetch_file_content",
                new_callable=AsyncMock,
            ) as mock_file,
        ):
            mock_contents.return_value = [
                {
                    "name": "SKILL.md",
                    "type": "file",
                    "path": "skills/my-skill/SKILL.md",
                    "download_url": "https://raw.example.com/SKILL.md",
                }
            ]
            mock_file.return_value = skill_md_content

            result = await install_from_github("user1", "owner/repo/skills/my-skill")

        assert result is mock_skill
        mock_install.assert_awaited_once()
        # VFS should have SKILL.md written (body only)
        mock_vfs.write.assert_awaited()

    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    async def test_install_no_skill_md_raises(self, mock_get_vfs: AsyncMock) -> None:
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs

        with patch(
            "app.agents.skills.installer._fetch_github_contents",
            new_callable=AsyncMock,
        ) as mock_contents:
            mock_contents.return_value = [
                {"name": "README.md", "type": "file", "path": "README.md"}
            ]

            with pytest.raises(ValueError, match="No SKILL.md"):
                await install_from_github("user1", "owner/repo/skills/my-skill")

    async def test_install_no_path_raises(self) -> None:
        with pytest.raises(ValueError, match="path to the skill folder"):
            await install_from_github("user1", "owner/repo")

    @patch(_PATCH_REGISTRY_INSTALL, new_callable=AsyncMock)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_SKILL_PATH, return_value="/users/u1/skills/custom-target/my-skill")
    async def test_install_target_override(
        self,
        mock_path: MagicMock,
        mock_get_vfs: AsyncMock,
        mock_install: AsyncMock,
    ) -> None:
        skill_md_content = """---
name: my-skill
description: A test skill.
target: executor
---

Body.
"""
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs
        mock_install.return_value = MagicMock(spec=Skill)

        with (
            patch(
                "app.agents.skills.installer._fetch_github_contents",
                new_callable=AsyncMock,
            ) as mock_contents,
            patch(
                "app.agents.skills.installer._fetch_file_content",
                new_callable=AsyncMock,
            ) as mock_file,
        ):
            mock_contents.return_value = [
                {
                    "name": "SKILL.md",
                    "type": "file",
                    "path": "skill/SKILL.md",
                    "download_url": "https://raw.example.com/SKILL.md",
                }
            ]
            mock_file.return_value = skill_md_content

            await install_from_github(
                "user1",
                "owner/repo/skill",
                target_override="gmail_agent",
            )

        # Check the install was called with the override target
        call_kwargs = mock_install.call_args[1]
        assert call_kwargs["target"] == "gmail_agent"

    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    async def test_install_invalid_skill_md_raises(
        self, mock_get_vfs: AsyncMock
    ) -> None:
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs

        invalid_content = """---
name: Invalid Name!
description: Bad.
---

Body.
"""
        with (
            patch(
                "app.agents.skills.installer._fetch_github_contents",
                new_callable=AsyncMock,
            ) as mock_contents,
            patch(
                "app.agents.skills.installer._fetch_file_content",
                new_callable=AsyncMock,
            ) as mock_file,
        ):
            mock_contents.return_value = [
                {
                    "name": "SKILL.md",
                    "type": "file",
                    "path": "skill/SKILL.md",
                    "download_url": "https://example.com/SKILL.md",
                }
            ]
            mock_file.return_value = invalid_content

            with pytest.raises(ValueError, match="Invalid SKILL.md"):
                await install_from_github("user1", "owner/repo/skill")


# ---------------------------------------------------------------------------
# _download_github_dir
# ---------------------------------------------------------------------------


class TestDownloadGithubDir:
    """Tests for _download_github_dir."""

    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_downloads_files_skipping_skill_md(
        self, mock_headers: MagicMock
    ) -> None:
        mock_vfs = AsyncMock()
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        file_response = MagicMock()
        file_response.text = "helper content"
        file_response.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=file_response)

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
        file_list: List[str] = []

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

        # SKILL.md should be skipped, only helper.py downloaded
        assert "helper.py" in file_list
        assert "SKILL.md" not in file_list
        mock_vfs.write.assert_awaited_once()

    @patch(_PATCH_GITHUB_HEADERS, return_value={})
    async def test_recurses_into_subdirectories(self, mock_headers: MagicMock) -> None:
        mock_vfs = AsyncMock()
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # First call: fetch subdirectory contents
        sub_response = MagicMock()
        sub_response.status_code = 200
        sub_response.json.return_value = [
            {
                "name": "util.py",
                "type": "file",
                "path": "skill/lib/util.py",
                "download_url": "https://example.com/util.py",
            }
        ]
        sub_response.raise_for_status = MagicMock()

        file_response = MagicMock()
        file_response.text = "util content"
        file_response.raise_for_status = MagicMock()

        mock_client.get = AsyncMock(side_effect=[sub_response, file_response])

        contents = [
            {
                "name": "lib",
                "type": "dir",
                "path": "skill/lib",
            }
        ]
        file_list: List[str] = []

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

        assert "lib/util.py" in file_list


# ---------------------------------------------------------------------------
# install_from_inline
# ---------------------------------------------------------------------------


class TestInstallFromInline:
    """Tests for install_from_inline."""

    @patch(_PATCH_REGISTRY_INSTALL, new_callable=AsyncMock)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_SKILL_PATH, return_value="/users/u1/skills/executor/test-skill")
    async def test_install_inline_success(
        self,
        mock_path: MagicMock,
        mock_get_vfs: AsyncMock,
        mock_install: AsyncMock,
    ) -> None:
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs
        mock_skill = MagicMock(spec=Skill)
        mock_install.return_value = mock_skill

        result = await install_from_inline(
            user_id="user1",
            name="test-skill",
            description="A test skill.",
            instructions="Do the thing.",
        )

        assert result is mock_skill
        mock_vfs.write.assert_awaited_once()
        mock_install.assert_awaited_once()

        # Check that body-only content was written to VFS
        vfs_write_call = mock_vfs.write.call_args
        written_content = vfs_write_call[0][1]
        assert "---" not in written_content  # no frontmatter in VFS
        assert "Do the thing." in written_content

    @patch(_PATCH_REGISTRY_INSTALL, new_callable=AsyncMock)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_SKILL_PATH, return_value="/users/u1/skills/executor/meta-skill")
    async def test_install_inline_with_metadata(
        self,
        mock_path: MagicMock,
        mock_get_vfs: AsyncMock,
        mock_install: AsyncMock,
    ) -> None:
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs
        mock_install.return_value = MagicMock(spec=Skill)

        await install_from_inline(
            user_id="user1",
            name="meta-skill",
            description="With metadata.",
            instructions="Body.",
            extra_metadata={"author": "tester"},
        )

        call_kwargs = mock_install.call_args[1]
        assert call_kwargs["metadata"] == {"author": "tester"}

    @patch(_PATCH_REGISTRY_INSTALL, new_callable=AsyncMock)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_SKILL_PATH, return_value="/users/u1/skills/gmail_agent/my-skill")
    async def test_install_inline_custom_target(
        self,
        mock_path: MagicMock,
        mock_get_vfs: AsyncMock,
        mock_install: AsyncMock,
    ) -> None:
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs
        mock_install.return_value = MagicMock(spec=Skill)

        await install_from_inline(
            user_id="user1",
            name="my-skill",
            description="Custom target skill.",
            instructions="Body.",
            target="gmail_agent",
        )

        call_kwargs = mock_install.call_args[1]
        assert call_kwargs["target"] == "gmail_agent"

    async def test_install_inline_invalid_name_raises(self) -> None:
        with pytest.raises((ValueError, Exception)):
            await install_from_inline(
                user_id="user1",
                name="Invalid Name!",
                description="Bad.",
                instructions="Body.",
            )

    async def test_install_inline_empty_description_raises(self) -> None:
        with pytest.raises((ValueError, Exception)):
            await install_from_inline(
                user_id="user1",
                name="valid-name",
                description="",
                instructions="Body.",
            )

    @patch(_PATCH_REGISTRY_INSTALL, new_callable=AsyncMock)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_SKILL_PATH, return_value="/users/u1/skills/executor/inline-skill")
    async def test_install_inline_registers_source_as_inline(
        self,
        mock_path: MagicMock,
        mock_get_vfs: AsyncMock,
        mock_install: AsyncMock,
    ) -> None:
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs
        mock_install.return_value = MagicMock(spec=Skill)

        await install_from_inline(
            user_id="user1",
            name="inline-skill",
            description="Inline source test.",
            instructions="Body.",
        )

        call_kwargs = mock_install.call_args[1]
        assert call_kwargs["source"] == SkillSource.INLINE
        assert call_kwargs["files"] == ["SKILL.md"]


# ---------------------------------------------------------------------------
# uninstall_skill_full
# ---------------------------------------------------------------------------


class TestUninstallSkillFull:
    """Tests for uninstall_skill_full."""

    @patch(_PATCH_REGISTRY_UNINSTALL, new_callable=AsyncMock, return_value=True)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_REGISTRY_GET, new_callable=AsyncMock)
    async def test_uninstall_success(
        self,
        mock_get: AsyncMock,
        mock_get_vfs: AsyncMock,
        mock_uninstall: AsyncMock,
    ) -> None:
        mock_skill = MagicMock(spec=Skill)
        mock_skill.name = "test-skill"
        mock_skill.vfs_path = "/users/u1/skills/executor/test-skill"
        mock_get.return_value = mock_skill

        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs

        result = await uninstall_skill_full("user1", "skill-id-1")

        assert result is True
        mock_vfs.delete.assert_awaited_once()
        mock_uninstall.assert_awaited_once_with("user1", "skill-id-1")

    @patch(_PATCH_REGISTRY_GET, new_callable=AsyncMock, return_value=None)
    async def test_uninstall_not_found(self, mock_get: AsyncMock) -> None:
        result = await uninstall_skill_full("user1", "nonexistent")
        assert result is False

    @patch(_PATCH_REGISTRY_UNINSTALL, new_callable=AsyncMock, return_value=True)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_REGISTRY_GET, new_callable=AsyncMock)
    async def test_uninstall_vfs_failure_continues(
        self,
        mock_get: AsyncMock,
        mock_get_vfs: AsyncMock,
        mock_uninstall: AsyncMock,
    ) -> None:
        """VFS delete failure should not prevent registry uninstall."""
        mock_skill = MagicMock(spec=Skill)
        mock_skill.name = "test-skill"
        mock_skill.vfs_path = "/users/u1/skills/executor/test-skill"
        mock_get.return_value = mock_skill

        mock_vfs = AsyncMock()
        mock_vfs.delete = AsyncMock(side_effect=RuntimeError("VFS error"))
        mock_get_vfs.return_value = mock_vfs

        result = await uninstall_skill_full("user1", "skill-id-1")

        # Should still succeed — registry uninstall should proceed
        assert result is True
        mock_uninstall.assert_awaited_once()

    @patch(_PATCH_REGISTRY_UNINSTALL, new_callable=AsyncMock, return_value=False)
    @patch(_PATCH_GET_VFS, new_callable=AsyncMock)
    @patch(_PATCH_REGISTRY_GET, new_callable=AsyncMock)
    async def test_uninstall_registry_returns_false(
        self,
        mock_get: AsyncMock,
        mock_get_vfs: AsyncMock,
        mock_uninstall: AsyncMock,
    ) -> None:
        """If registry uninstall returns False, the function returns False."""
        mock_skill = MagicMock(spec=Skill)
        mock_skill.name = "test-skill"
        mock_skill.vfs_path = "/path"
        mock_get.return_value = mock_skill

        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs

        result = await uninstall_skill_full("user1", "skill-id-1")
        assert result is False
