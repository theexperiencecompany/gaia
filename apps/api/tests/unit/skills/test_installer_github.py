"""Unit tests for app.agents.skills.installer.install_from_github.

Covers the real install path: GitHub Contents API fetch (respx-mocked, no real
network), SKILL.md validation, the allowed_targets guard, and recursive
sub-directory download. VFS writes (ensure_user_skills_dir/write_skill_file)
and the Mongo-backed install_skill registry call are mocked — those have their
own dedicated tests (storage layer, test_skills_registry.py).
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from app.agents.skills.installer import (
    install_from_github,
    install_from_inline,
    update_skill_inline,
)
from app.agents.skills.models import (
    Skill,
    SkillAuthor,
    SkillInlineCreateRequest,
    SkillSource,
    SkillUpdate,
)
from app.agents.skills.utils import GITHUB_API_BASE
from app.constants.skills import LEARNED_SKILL_METADATA
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import SkillInstalled, SkillUpdated
from tests.helpers import captured_wide_event

#: Analytics attributes events to a real Mongo user id, so the event tests use one.
_UID = "507f1f77bcf86cd799439011"

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
    """Short-circuit urllib.getproxies() with a truthy proxy env; it segfaults inside mutmut's forked workers on macOS, though respx intercepts the transport regardless."""
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
    """Mock only the VFS write boundary and the Mongo registry call.

    The real HTTP fetch/parse/validation/recursion logic under test stays untouched."""
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
        patch(
            "app.agents.skills.registry.skill_repository.find_by_name",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        # The installed record feeds the skill:installed event, so it carries real ids.
        install_mock.return_value = MagicMock(id="sk-1", target="executor")
        yield write_mock, install_mock, ensure_dir_mock


@pytest.fixture
def name_taken():
    """Make the registry report the requested name and target as already taken."""
    with patch(
        "app.agents.skills.registry.skill_repository.find_by_name",
        new_callable=AsyncMock,
        return_value=MagicMock(name="existing-skill"),
    ) as find_mock:
        yield find_mock


class TestInstallFromGithubSuccess:
    async def test_installs_skill_and_writes_body_only_skill_md(self, storage_seams):
        write_mock, install_mock, _ = storage_seams
        with respx.mock:
            contents_route = respx.get(
                f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/my-skill"
            ).mock(
                return_value=httpx.Response(
                    200,
                    json=[_contents_entry("SKILL.md", "file", "skills/my-skill/SKILL.md")],
                )
            )
            respx.get(
                "https://raw.githubusercontent.com/org/repo/main/skills/my-skill/SKILL.md"
            ).mock(return_value=httpx.Response(200, text=_SKILL_MD_CONTENT))

            result = await install_from_github(
                user_id=_UID, repo_url="org/repo/skills/my-skill", author=SkillAuthor.USER
            )

        assert contents_route.calls.last.request.url.params["ref"] == "main"
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
        """Recurse into a resources/ subfolder and record every downloaded file, not just SKILL.md."""
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

            result = await install_from_github(
                user_id=_UID, repo_url="org/repo/skills/my-skill", author=SkillAuthor.USER
            )

        assert result is not None
        install_mock.assert_awaited_once()
        request = install_mock.await_args.args[0]
        files = request.files
        assert files == ["SKILL.md", "resources/reference.md"]
        written_paths = [c.args[2] for c in write_mock.await_args_list]
        assert written_paths == ["SKILL.md", "resources/reference.md"]
        for write_call in write_mock.await_args_list:
            assert write_call.args[0] == _UID
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
                await install_from_github(
                    user_id=_UID, repo_url="org/repo/skills/empty", author=SkillAuthor.USER
                )

    async def test_a_rate_limited_lookup_says_how_to_lift_the_limit(self, storage_seams):
        with respx.mock:
            respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/my-skill").mock(
                return_value=httpx.Response(403, json={"message": "API rate limit exceeded"})
            )
            with pytest.raises(ValueError) as excinfo:
                await install_from_github(
                    user_id=_UID, repo_url="org/repo/skills/my-skill", author=SkillAuthor.USER
                )

        assert str(excinfo.value) == (
            "GitHub API rate limit exceeded. Try again later, or add a GitHub token in "
            "Settings → Providers & Tools (GITHUB_TOKEN in env) for 5000 lookups an hour "
            "instead of 60."
        )

    async def test_disallowed_target_raises_value_error(self, storage_seams):
        """allowed_targets blocks installing a skill scoped to an integration the user hasn't connected, at the source so agent-tool callers get it too."""
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
                    user_id=_UID,
                    repo_url="org/repo/skills/my-skill",
                    allowed_targets={"some_other_agent"},
                    author=SkillAuthor.USER,
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
                user_id=_UID,
                repo_url="org/repo/skills/my-skill",
                target_override="gmail_agent",
                allowed_targets={"gmail_agent"},
                author=SkillAuthor.USER,
            )

        assert install_mock.await_args.args[0].target == "gmail_agent"

    async def test_no_skill_path_raises_value_error(self, storage_seams):
        with pytest.raises(ValueError, match="Provide a path"):
            await install_from_github(user_id=_UID, repo_url="org/repo", author=SkillAuthor.USER)

    async def test_skill_md_without_download_url_raises_value_error(self, storage_seams):
        entry = {**_contents_entry("SKILL.md", "file", "skills/x/SKILL.md"), "download_url": None}
        with respx.mock:
            respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/x").mock(
                return_value=httpx.Response(200, json=[entry])
            )
            with pytest.raises(ValueError, match="no download URL for skills/x/SKILL.md"):
                await install_from_github(
                    user_id=_UID, repo_url="org/repo/skills/x", author=SkillAuthor.USER
                )

    async def test_single_file_contents_response_is_treated_as_one_entry(self, storage_seams):
        """The Contents API answers a file path with one object, not a list."""
        with respx.mock:
            respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/x").mock(
                return_value=httpx.Response(
                    200, json=_contents_entry("SKILL.md", "file", "skills/x/SKILL.md")
                )
            )
            respx.get("https://raw.githubusercontent.com/org/repo/main/skills/x/SKILL.md").mock(
                return_value=httpx.Response(200, text=_SKILL_MD_CONTENT)
            )
            await install_from_github(
                user_id=_UID, repo_url="org/repo/skills/x", author=SkillAuthor.USER
            )

        assert storage_seams[1].await_args.args[0].name == "my-skill"

    async def test_dot_segment_path_is_rejected_before_any_request(self, storage_seams):
        """Httpx collapses dot segments: unchecked, this path sent the server's GitHub token to /user/keys."""
        with respx.mock:
            with pytest.raises(ValueError, match="Invalid GitHub path segment"):
                await install_from_github(
                    user_id=_UID, repo_url="org/repo/../../../../user/keys", author=SkillAuthor.USER
                )


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
    """Every field of the SkillInstallRequest must come from the repo's frontmatter and the fetch, not from defaults."""

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

            await install_from_github(
                user_id=_UID, repo_url="org/repo/skills/my-skill", author=SkillAuthor.USER
            )

        request = install_mock.await_args.args[0]
        assert request.user_id == _UID
        assert request.name == "my-skill"
        assert request.description == "A rich skill from GitHub"
        assert request.target == "executor"
        assert request.vfs_path == f"/skills/{_UID}/my-skill"
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
            _UID,
            SkillInlineCreateRequest(
                name="my-skill",
                description="An inline skill",
                instructions="Do the thing when asked.",
                target="gmail_agent",
            ),
            author=SkillAuthor.USER,
            learned=True,
        )

        assert result is not None
        request = install_mock.await_args.args[0]
        assert request.user_id == _UID
        assert request.name == "my-skill"
        assert request.description == "An inline skill"
        assert request.target == "gmail_agent"
        assert request.vfs_path == f"/skills/{_UID}/my-skill"
        assert request.source is SkillSource.INLINE
        assert request.source_url is None
        assert request.body_content == "Do the thing when asked."
        assert request.files == ["SKILL.md"]
        assert request.metadata == LEARNED_SKILL_METADATA
        write_mock.assert_awaited_once_with(
            _UID, "my-skill", "SKILL.md", "Do the thing when asked."
        )
        ensure_dir_mock.assert_awaited_once_with(_UID)

    async def test_defaults_target_to_executor(self, storage_seams):
        _, install_mock, _ = storage_seams
        await install_from_inline(
            _UID,
            SkillInlineCreateRequest(
                name="my-skill",
                description="An inline skill",
                instructions="Do the thing when asked.",
            ),
            author=SkillAuthor.USER,
        )
        assert install_mock.await_args.args[0].target == "executor"

    async def test_invalid_name_raises_value_error(self, storage_seams):
        with pytest.raises(ValueError):
            await install_from_inline(
                _UID,
                SkillInlineCreateRequest(
                    name="Invalid Name",
                    description="An inline skill",
                    instructions="Do the thing when asked.",
                ),
                author=SkillAuthor.USER,
            )

    async def test_passes_frontmatter_extras_through(self, storage_seams, monkeypatch):
        """generate_skill_md cannot emit license/compatibility/allowed-tools; pin their request mapping via frontmatter carrying them."""
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
            _UID,
            SkillInlineCreateRequest(
                name="my-skill",
                description="An inline skill",
                instructions="Do the thing when asked.",
            ),
            author=SkillAuthor.USER,
        )

        request = install_mock.await_args.args[0]
        assert request.license_name == "MIT"
        assert request.compatibility == "Python >=3.10"
        assert request.allowed_tools == ["web_search"]


class TestNameClashLeavesExistingSkillUntouched:
    """A taken name must be refused before the shared SKILL.md path is written."""

    async def test_inline_install_refuses_before_writing(self, storage_seams, name_taken):
        write_mock, install_mock, _ = storage_seams
        with pytest.raises(AppError) as exc_info:
            await install_from_inline(
                _UID,
                SkillInlineCreateRequest(
                    name="my-skill",
                    description="An inline skill",
                    instructions="Replacement body that must not land on disk.",
                ),
                author=SkillAuthor.USER,
            )
        assert exc_info.value.status_code == 409
        name_taken.assert_awaited_once_with(_UID, "my-skill")
        write_mock.assert_not_awaited()
        install_mock.assert_not_awaited()

    async def test_github_install_refuses_before_writing(self, storage_seams, name_taken):
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
            with pytest.raises(AppError) as exc_info:
                await install_from_github(_UID, "org/repo/skills/my-skill", author=SkillAuthor.USER)
        assert exc_info.value.status_code == 409
        name_taken.assert_awaited_once_with(_UID, "my-skill")
        write_mock.assert_not_awaited()
        install_mock.assert_not_awaited()


class TestSkillEventsComeFromTheInstaller:
    """One event per action, from the one path REST and the agent share."""

    @pytest.mark.usefixtures("storage_seams")
    async def test_an_inline_install_records_who_made_it_and_how(self):
        with patch("app.agents.skills.installer.capture") as capture:
            await install_from_inline(
                _UID,
                SkillInlineCreateRequest(
                    name="my-skill",
                    description="An inline skill",
                    instructions="Do the thing when asked.",
                ),
                author=SkillAuthor.AGENT,
                learned=True,
            )
        capture.assert_called_once_with(
            UserId(_UID),
            SkillInstalled(skill_id="sk-1", target="executor", source="learned", author="agent"),
        )

    async def test_an_update_records_its_author(self, storage_seams):
        current = Skill(
            id="sk-1",
            user_id=_UID,
            name="my-skill",
            description="An inline skill",
            target="executor",
            vfs_path=f"/skills/{_UID}/my-skill",
            source=SkillSource.INLINE,
            body_content="Old steps.",
            installed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        with (
            patch("app.agents.skills.installer.get_skill", new=AsyncMock(return_value=current)),
            patch(
                "app.agents.skills.installer.update_skill",
                new=AsyncMock(return_value=current.model_copy(update={"body_content": "New."})),
            ),
            patch("app.agents.skills.installer.capture") as capture,
        ):
            await update_skill_inline(_UID, "sk-1", instructions="New.", author=SkillAuthor.AGENT)
        capture.assert_called_once_with(
            UserId(_UID), SkillUpdated(target="executor", author="agent")
        )


class TestSkillEventsAndContext:
    @pytest.mark.usefixtures("storage_seams")
    async def test_a_github_install_records_the_installed_skill(self):
        with respx.mock, patch("app.agents.skills.installer.capture") as capture:
            respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/my-skill").mock(
                return_value=httpx.Response(
                    200,
                    json=[_contents_entry("SKILL.md", "file", "skills/my-skill/SKILL.md")],
                )
            )
            respx.get(
                "https://raw.githubusercontent.com/org/repo/main/skills/my-skill/SKILL.md"
            ).mock(return_value=httpx.Response(200, text=_SKILL_MD_CONTENT))
            await install_from_github(_UID, "org/repo/skills/my-skill", author=SkillAuthor.USER)
        capture.assert_called_once_with(
            UserId(_UID),
            SkillInstalled(skill_id="sk-1", target="executor", source="github", author="user"),
        )

    async def test_an_inline_install_is_not_learned_unless_asked(self, storage_seams):
        _, install_mock, _ = storage_seams
        async with captured_wide_event() as event:
            with patch("app.agents.skills.installer.capture") as capture:
                await install_from_inline(
                    _UID,
                    SkillInlineCreateRequest(
                        name="my-skill",
                        description="An inline skill",
                        instructions="Do the thing when asked.",
                    ),
                    author=SkillAuthor.USER,
                )
        capture.assert_called_once_with(
            UserId(_UID),
            SkillInstalled(skill_id="sk-1", target="executor", source="inline", author="user"),
        )
        assert install_mock.await_args.args[0].metadata == {}
        assert event["skill"] == {"operation": "install", "skill_name": "my-skill"}

    async def test_an_update_writes_the_revised_description_target_and_body(self, storage_seams):
        current = Skill(
            id="sk-1",
            user_id=_UID,
            name="my-skill",
            description="An inline skill",
            target="executor",
            vfs_path=f"/skills/{_UID}/my-skill",
            source=SkillSource.INLINE,
            body_content="Old steps.",
            installed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        update = AsyncMock(return_value=current)
        with (
            patch("app.agents.skills.installer.get_skill", new=AsyncMock(return_value=current)),
            patch("app.agents.skills.installer.update_skill", new=update),
        ):
            await update_skill_inline(
                _UID,
                "sk-1",
                description="A sharper description",
                instructions="New steps.",
                author=SkillAuthor.USER,
            )
        update.assert_awaited_once_with(
            _UID,
            "sk-1",
            SkillUpdate(
                description="A sharper description", target="executor", body_content="New steps."
            ),
        )
