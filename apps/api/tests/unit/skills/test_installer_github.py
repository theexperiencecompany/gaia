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

from app.agents.skills.installer import install_from_github, install_from_inline
from app.agents.skills.models import SkillSource
from app.agents.skills.utils import GITHUB_API_BASE

_SKILL_MD_CONTENT = """\
---
name: my-skill
description: A test skill installed from GitHub
target: executor
---

Do the thing when asked.
"""


@pytest.fixture(autouse=True)
def _fork_safe_proxy_env(monkeypatch):
    """httpx.AsyncClient() consults urllib.getproxies(), which on macOS falls
    through to the System Configuration framework — a call that segfaults
    inside mutmut's forked worker processes. A truthy proxy environment makes
    urllib short-circuit before that call; respx intercepts the transport, so
    the value never affects what the tests observe."""
    monkeypatch.setenv("no_proxy", "*")


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
        ) as ensure_dir_mock,
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
        yield write_mock, install_mock, ensure_dir_mock


class TestInstallFromGithubSuccess:
    async def test_installs_skill_and_writes_body_only_skill_md(self, storage_seams):
        write_mock, install_mock, _ = storage_seams
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
        request = install_mock.await_args.args[0]
        assert request.name == "my-skill"
        assert request.target == "executor"
        # Body-only (frontmatter stripped) must reach VFS, not the raw SKILL.md.
        write_call = write_mock.await_args_list[0]
        assert write_call.args[2] == "SKILL.md"
        assert "---" not in write_call.args[3]
        assert "Do the thing when asked." in write_call.args[3]

    async def test_nested_subdirectory_files_are_downloaded_and_listed(self, storage_seams):
        """A skill with a resources/ subfolder must recurse into it and record
        every downloaded file, not just the top-level SKILL.md."""
        write_mock, install_mock, _ = storage_seams
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
        request = install_mock.await_args.args[0]
        files = request.files
        assert files == ["SKILL.md", "resources/reference.md"]
        written_paths = [c.args[2] for c in write_mock.await_args_list]
        assert written_paths == ["SKILL.md", "resources/reference.md"]
        for write_call in write_mock.await_args_list:
            assert write_call.args[0] == "u1"
            assert write_call.args[1] == "my-skill"
        reference_write = write_mock.await_args_list[1]
        assert reference_write.args[3] == "# Reference\nExtra detail."


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
        write_mock, install_mock, _ = storage_seams
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

        assert install_mock.await_args.args[0].target == "gmail_agent"

    async def test_no_skill_path_raises_value_error(self, storage_seams):
        with pytest.raises(ValueError, match="Provide a path"):
            await install_from_github(user_id="u1", repo_url="org/repo")


_RICH_SKILL_MD = """\
---
name: my-skill
description: A rich skill from GitHub
target: executor
license: MIT
compatibility: Python >=3.10
allowed-tools:
  - web_search
metadata:
  version: "1"
---

Do the thing when asked.
"""


class TestInstallFromGithubRequestShape:
    """Every field of the SkillInstallRequest must come from the repo's
    frontmatter and the fetch — not from defaults."""

    async def test_builds_full_install_request(self, storage_seams):
        _, install_mock, _ = storage_seams
        with respx.mock:
            respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/my-skill").mock(
                return_value=httpx.Response(
                    200,
                    json=[_contents_entry("SKILL.md", "file", "skills/my-skill/SKILL.md")],
                )
            )
            respx.get(
                "https://raw.githubusercontent.com/org/repo/main/skills/my-skill/SKILL.md"
            ).mock(return_value=httpx.Response(200, text=_RICH_SKILL_MD))

            await install_from_github(user_id="u1", repo_url="org/repo/skills/my-skill")

        request = install_mock.await_args.args[0]
        assert request.user_id == "u1"
        assert request.name == "my-skill"
        assert request.description == "A rich skill from GitHub"
        assert request.target == "executor"
        assert request.vfs_path == "/skills/u1/my-skill"
        assert request.source is SkillSource.GITHUB
        assert request.source_url == "https://github.com/org/repo/tree/main/skills/my-skill"
        assert request.body_content == "Do the thing when asked."
        assert request.files == ["SKILL.md"]
        assert request.license_name == "MIT"
        assert request.compatibility == "Python >=3.10"
        assert request.metadata == {"version": "1"}
        assert request.allowed_tools == ["web_search"]


class TestInstallFromInline:
    async def test_registers_inline_skill_with_round_tripped_metadata(self, storage_seams):
        write_mock, install_mock, ensure_dir_mock = storage_seams
        result = await install_from_inline(
            user_id="u1",
            name="my-skill",
            description="An inline skill",
            instructions="Do the thing when asked.",
            target="gmail_agent",
            extra_metadata={"version": "1"},
        )

        assert result is not None
        request = install_mock.await_args.args[0]
        assert request.user_id == "u1"
        assert request.name == "my-skill"
        assert request.description == "An inline skill"
        assert request.target == "gmail_agent"
        assert request.vfs_path == "/skills/u1/my-skill"
        assert request.source is SkillSource.INLINE
        assert request.source_url is None
        assert request.body_content == "Do the thing when asked."
        assert request.files == ["SKILL.md"]
        assert request.metadata == {"version": "1"}
        write_mock.assert_awaited_once_with(
            "u1", "my-skill", "SKILL.md", "Do the thing when asked."
        )
        ensure_dir_mock.assert_awaited_once_with("u1")

    async def test_defaults_target_to_executor(self, storage_seams):
        _, install_mock, _ = storage_seams
        await install_from_inline(
            user_id="u1",
            name="my-skill",
            description="An inline skill",
            instructions="Do the thing when asked.",
        )
        assert install_mock.await_args.args[0].target == "executor"

    async def test_invalid_name_raises_value_error(self, storage_seams):
        with pytest.raises(ValueError):
            await install_from_inline(
                user_id="u1",
                name="Invalid Name",
                description="An inline skill",
                instructions="Do the thing when asked.",
            )

    async def test_passes_frontmatter_extras_through(self, storage_seams, monkeypatch):
        """generate_skill_md cannot emit license/compatibility/allowed-tools;
        pin their request mapping with frontmatter that carries them."""
        rich_skill_md = (
            "---\n"
            "name: my-skill\n"
            "description: An inline skill\n"
            "target: executor\n"
            "license: MIT\n"
            "compatibility: Python >=3.10\n"
            "allowed-tools:\n"
            "  - web_search\n"
            "---\n\nDo the thing when asked.\n"
        )
        monkeypatch.setattr(
            "app.agents.skills.installer.generate_skill_md", lambda **kwargs: rich_skill_md
        )
        _, install_mock, _ = storage_seams

        await install_from_inline(
            user_id="u1",
            name="my-skill",
            description="An inline skill",
            instructions="Do the thing when asked.",
        )

        request = install_mock.await_args.args[0]
        assert request.license_name == "MIT"
        assert request.compatibility == "Python >=3.10"
        assert request.allowed_tools == ["web_search"]
