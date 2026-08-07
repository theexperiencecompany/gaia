"""Unit tests for app.agents.skills.installer.install_from_github.

Covers the real install path: GitHub Contents API fetch (respx-mocked, no real
network), SKILL.md validation, the allowed_targets guard, and recursive
sub-directory download. VFS writes (ensure_user_skills_dir/write_skill_file)
and the Mongo-backed install_skill registry call are mocked — those have their
own dedicated tests (storage layer, test_skills_registry.py).
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from app.agents.skills.installer import install_from_github
from app.agents.skills.utils import GITHUB_API_BASE

pytestmark = pytest.mark.unit

_SKILL_MD_CONTENT = """\
---
name: my-skill
description: A test skill installed from GitHub
target: executor
---

Do the thing when asked.
"""


def _contents_entry(name: str, entry_type: str, path: str, download_url: str | None = None):
    return {
        "name": name,
        "path": path,
        "type": entry_type,
        "download_url": download_url or f"https://raw.githubusercontent.com/org/repo/main/{path}",
    }


@pytest.fixture
def storage_seams():
    """Mock only the VFS write boundary and the Mongo registry call — the
    real HTTP fetch/parse/validation/recursion logic under test is untouched."""
    with (
        patch(
            "app.agents.skills.installer.ensure_user_skills_dir",
            new_callable=AsyncMock,
        ),
        patch(
            "app.agents.skills.installer.write_skill_file",
            new_callable=AsyncMock,
        ) as write_mock,
        patch(
            "app.agents.skills.installer.install_skill",
            new_callable=AsyncMock,
        ) as install_mock,
    ):
        install_mock.return_value = AsyncMock(name="my-skill")
        yield write_mock, install_mock


class TestInstallFromGithubSuccess:
    async def test_installs_skill_and_writes_body_only_skill_md(self, storage_seams):
        write_mock, install_mock = storage_seams
        with respx.mock:
            respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/my-skill").mock(
                return_value=httpx.Response(
                    200,
                    json=[_contents_entry("SKILL.md", "file", "skills/my-skill/SKILL.md")],
                )
            )
            respx.get(
                "https://raw.githubusercontent.com/org/repo/main/skills/my-skill/SKILL.md"
            ).mock(return_value=httpx.Response(200, text=_SKILL_MD_CONTENT))

            result = await install_from_github(user_id="u1", repo_url="org/repo/skills/my-skill")

        assert result is not None
        install_mock.assert_awaited_once()
        call_kwargs = install_mock.await_args.kwargs
        assert call_kwargs["name"] == "my-skill"
        assert call_kwargs["target"] == "executor"
        # Body-only (frontmatter stripped) must reach VFS, not the raw SKILL.md.
        write_call = write_mock.await_args_list[0]
        assert write_call.args[2] == "SKILL.md"
        assert "---" not in write_call.args[3]
        assert "Do the thing when asked." in write_call.args[3]

    async def test_nested_subdirectory_files_are_downloaded_and_listed(self, storage_seams):
        """A skill with a resources/ subfolder must recurse into it and record
        every downloaded file, not just the top-level SKILL.md."""
        write_mock, install_mock = storage_seams
        with respx.mock:
            respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/my-skill").mock(
                return_value=httpx.Response(
                    200,
                    json=[
                        _contents_entry("SKILL.md", "file", "skills/my-skill/SKILL.md"),
                        _contents_entry("resources", "dir", "skills/my-skill/resources"),
                    ],
                )
            )
            respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/my-skill/resources").mock(
                return_value=httpx.Response(
                    200,
                    json=[
                        _contents_entry(
                            "reference.md",
                            "file",
                            "skills/my-skill/resources/reference.md",
                        ),
                    ],
                )
            )
            respx.get(
                "https://raw.githubusercontent.com/org/repo/main/skills/my-skill/SKILL.md"
            ).mock(return_value=httpx.Response(200, text=_SKILL_MD_CONTENT))
            respx.get(
                "https://raw.githubusercontent.com/org/repo/main/skills/my-skill/resources/reference.md"
            ).mock(return_value=httpx.Response(200, text="# Reference\nExtra detail."))

            result = await install_from_github(user_id="u1", repo_url="org/repo/skills/my-skill")

        assert result is not None
        install_mock.assert_awaited_once()
        files = install_mock.await_args.kwargs["files"]
        assert "SKILL.md" in files
        assert "resources/reference.md" in files
        written_paths = [c.args[2] for c in write_mock.await_args_list]
        assert "resources/reference.md" in written_paths


class TestInstallFromGithubValidation:
    async def test_missing_skill_md_raises_value_error(self, storage_seams):
        with respx.mock:
            respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/empty").mock(
                return_value=httpx.Response(
                    200, json=[_contents_entry("README.md", "file", "skills/empty/README.md")]
                )
            )
            # raises wraps only the call: with the mock setup inside it too, a
            # ValueError from respx would have satisfied the assertion without
            # install_from_github ever running.
            with pytest.raises(ValueError, match="No SKILL.md found"):
                await install_from_github(user_id="u1", repo_url="org/repo/skills/empty")

    async def test_disallowed_target_raises_value_error(self, storage_seams):
        """allowed_targets blocks installing a skill scoped to an integration
        the user hasn't connected — this is the REST endpoint's own guard,
        enforced here at the source so agent-tool callers get it too."""
        with respx.mock:
            respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/my-skill").mock(
                return_value=httpx.Response(
                    200,
                    json=[_contents_entry("SKILL.md", "file", "skills/my-skill/SKILL.md")],
                )
            )
            respx.get(
                "https://raw.githubusercontent.com/org/repo/main/skills/my-skill/SKILL.md"
            ).mock(return_value=httpx.Response(200, text=_SKILL_MD_CONTENT))

            # See above: only the call under test belongs inside raises.
            with pytest.raises(ValueError, match="not available"):
                await install_from_github(
                    user_id="u1",
                    repo_url="org/repo/skills/my-skill",
                    allowed_targets={"some_other_agent"},
                )

    async def test_target_override_takes_precedence_over_frontmatter(self, storage_seams):
        write_mock, install_mock = storage_seams
        with respx.mock:
            respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/my-skill").mock(
                return_value=httpx.Response(
                    200,
                    json=[_contents_entry("SKILL.md", "file", "skills/my-skill/SKILL.md")],
                )
            )
            respx.get(
                "https://raw.githubusercontent.com/org/repo/main/skills/my-skill/SKILL.md"
            ).mock(return_value=httpx.Response(200, text=_SKILL_MD_CONTENT))

            await install_from_github(
                user_id="u1",
                repo_url="org/repo/skills/my-skill",
                target_override="gmail_agent",
                allowed_targets={"gmail_agent"},
            )

        assert install_mock.await_args.kwargs["target"] == "gmail_agent"

    async def test_no_skill_path_raises_value_error(self, storage_seams):
        with pytest.raises(ValueError, match="Provide a path"):
            await install_from_github(user_id="u1", repo_url="org/repo")
