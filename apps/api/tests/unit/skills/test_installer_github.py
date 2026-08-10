"""Unit tests for app.agents.skills.installer.

Covers the full installer surface: GitHub reference parsing, the Contents API
fetch (respx-mocked, no real network) with master-branch fallback and
rate-limit handling, raw file download, recursive sub-directory download,
SKILL.md validation, the allowed_targets guard, and the exact registry/VFS
contract of install_from_github. The inline/update/uninstall paths
(install_from_inline, update_skill_inline, uninstall_skill_full) are covered
with mocked registry/VFS seams and the real SKILL.md generator/parser. VFS
writes (ensure_user_skills_dir/write_skill_file) and the Mongo-backed
registry calls are mocked — those have their own dedicated tests (storage
layer, test_skills_registry.py).
"""

import re
from unittest.mock import AsyncMock, MagicMock, call, patch, sentinel

import httpx
import pytest
import respx

from app.agents.skills.installer import (
    _download_github_dir,
    _fetch_file_content,
    _fetch_github_contents,
    _parse_github_url,
    install_from_github,
    install_from_inline,
    uninstall_skill_full,
    update_skill_inline,
)
from app.agents.skills.models import Skill, SkillSource
from app.agents.skills.utils import GITHUB_API_BASE, get_github_headers
from app.constants.log_tags import LogTag
from app.services.storage import JuiceFSUnavailable

_SKILL_MD_CONTENT = """\
---
name: my-skill
description: A test skill installed from GitHub
target: executor
---

Do the thing when asked.
"""

_RICH_SKILL_MD = """\
---
name: rich-skill
description: Rich metadata skill
target: executor
license: MIT
compatibility: python>=3.12
metadata:
  author: Acme
  version: "1.2.3"
allowed-tools:
  - tool_one
  - tool_two
---

Rich body instructions.
"""

_INVALID_SKILL_MD = """\
---
name: my-skill
---

Body without a description.
"""


def _contents_entry(name: str, entry_type: str, path: str, download_url: str | None = None):
    return {
        "name": name,
        "path": path,
        "type": entry_type,
        "download_url": download_url or f"https://raw.githubusercontent.com/org/repo/main/{path}",
    }


def _github_response(status_code: int, *, json: object = None, text: str | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json
    resp.text = text
    return resp


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


@pytest.fixture
def log_seam():
    with patch("app.agents.skills.installer.log") as log_mock:
        yield log_mock


@pytest.fixture
def full_seams():
    """storage_seams plus the wide-event logger, with a sentinel install
    return so tests can assert result identity."""
    with (
        patch(
            "app.agents.skills.installer.ensure_user_skills_dir",
            new_callable=AsyncMock,
        ) as ensure_mock,
        patch(
            "app.agents.skills.installer.write_skill_file",
            new_callable=AsyncMock,
        ) as write_mock,
        patch(
            "app.agents.skills.installer.install_skill",
            new_callable=AsyncMock,
        ) as install_mock,
        patch("app.agents.skills.installer.log") as log_mock,
    ):
        install_mock.return_value = sentinel.installed_skill
        yield write_mock, install_mock, ensure_mock, log_mock


class TestParseGithubUrl:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("owner/repo", ("owner", "repo", None)),
            ("owner/repo/", ("owner", "repo", None)),
            ("  owner/repo  ", ("owner", "repo", None)),
            ("owner/repo/path/to/skill", ("owner", "repo", "path/to/skill")),
            ("owner/repo/a/b/c", ("owner", "repo", "a/b/c")),
            ("https://github.com/owner/repo", ("owner", "repo", None)),
            ("https://github.com/owner/repo/", ("owner", "repo", None)),
            ("http://github.com/owner/repo", ("owner", "repo", None)),
            (
                "https://github.com/owner/repo/tree/main/path/to/skill",
                ("owner", "repo", "path/to/skill"),
            ),
            (
                "https://github.com/owner/repo/blob/main/path/to/skill",
                ("owner", "repo", "path/to/skill"),
            ),
        ],
    )
    def test_parses_known_forms(self, url: str, expected: tuple[str, str, str | None]):
        assert _parse_github_url(url) == expected

    def test_single_part_raises_with_guidance(self):
        with pytest.raises(
            ValueError,
            match=re.escape(
                "Invalid GitHub reference: owner. "
                "Use 'owner/repo', 'owner/repo/path', or a full GitHub URL."
            ),
        ):
            _parse_github_url("owner")


class TestFetchGithubContents:
    async def test_list_response_and_exact_request(self):
        client = AsyncMock()
        client.get.return_value = _github_response(200, json=[{"name": "SKILL.md"}])

        data = await _fetch_github_contents("org", "repo", "skills/my-skill", client=client)

        assert data == [{"name": "SKILL.md"}]
        client.get.assert_awaited_once_with(
            f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/my-skill",
            params={"ref": "main"},
            headers=get_github_headers(),
        )

    async def test_dict_response_is_wrapped_in_list(self):
        client = AsyncMock()
        entry = {"name": "SKILL.md", "type": "file"}
        client.get.return_value = _github_response(200, json=entry)

        data = await _fetch_github_contents("org", "repo", "skills/my-skill", client=client)

        assert data == [entry]

    async def test_404_on_main_retries_with_master(self):
        client = AsyncMock()
        url = f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/my-skill"
        client.get.side_effect = [
            _github_response(404),
            _github_response(200, json=[{"name": "SKILL.md"}]),
        ]

        data = await _fetch_github_contents("org", "repo", "skills/my-skill", client=client)

        assert data == [{"name": "SKILL.md"}]
        assert client.get.await_count == 2
        assert client.get.await_args_list == [
            call(url, params={"ref": "main"}, headers=get_github_headers()),
            call(url, params={"ref": "master"}, headers=get_github_headers()),
        ]

    async def test_404_on_master_raises_path_not_found(self):
        client = AsyncMock()
        client.get.side_effect = [_github_response(404), _github_response(404)]

        with pytest.raises(ValueError, match=re.escape("Path not found: org/repo/skills/nope")):
            await _fetch_github_contents("org", "repo", "skills/nope", client=client)

        assert client.get.await_count == 2

    async def test_403_rate_limit_raises_and_logs_warning(self, log_seam):
        client = AsyncMock()
        client.get.return_value = _github_response(403)

        with pytest.raises(
            ValueError,
            match=re.escape(
                "GitHub API rate limit exceeded. Please try again later, or set "
                "GITHUB_TOKEN for higher limits (5000/hr vs 60/hr)."
            ),
        ):
            await _fetch_github_contents("org", "repo", "skills/my-skill", client=client)

        log_seam.warning.assert_called_once()
        assert "GitHub API rate limit exceeded" in log_seam.warning.call_args.args[0]

    async def test_other_http_errors_propagate(self):
        client = AsyncMock()
        resp = _github_response(500)
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error",
            request=httpx.Request("GET", f"{GITHUB_API_BASE}/repos/org/repo/contents/x"),
            response=httpx.Response(500),
        )
        client.get.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            await _fetch_github_contents("org", "repo", "skills/my-skill", client=client)


class TestFetchFileContent:
    async def test_returns_raw_text_with_exact_request(self):
        client = AsyncMock()
        client.get.return_value = _github_response(200, text="body content")

        content = await _fetch_file_content("https://raw/org/repo/main/SKILL.md", client=client)

        assert content == "body content"
        client.get.assert_awaited_once_with(
            "https://raw/org/repo/main/SKILL.md",
            headers=get_github_headers(),
        )

    async def test_http_error_propagates(self):
        client = AsyncMock()
        resp = _github_response(500)
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error",
            request=httpx.Request("GET", "https://raw/org/repo/main/SKILL.md"),
            response=httpx.Response(500),
        )
        client.get.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            await _fetch_file_content("https://raw/org/repo/main/SKILL.md", client=client)


class TestDownloadGithubDir:
    async def test_skips_skill_md_and_writes_files_with_relative_paths(self):
        client = AsyncMock()
        file_url = "https://raw/org/repo/main/skills/my-skill/tool.py"
        client.get.return_value = _github_response(200, text="# tool content")
        contents = [
            _contents_entry("SKILL.md", "file", "skills/my-skill/SKILL.md"),
            _contents_entry("tool.py", "file", "skills/my-skill/tool.py", file_url),
        ]
        file_list: list[str] = []

        with patch(
            "app.agents.skills.installer.write_skill_file",
            new_callable=AsyncMock,
        ) as write_mock:
            result = await _download_github_dir(
                user_id="u1",
                skill_name="my-skill",
                owner="org",
                repo="repo",
                remote_path="skills/my-skill",
                contents=contents,
                file_list=file_list,
                client=client,
            )

        assert result is None
        assert file_list == ["tool.py"]
        write_mock.assert_awaited_once_with("u1", "my-skill", "tool.py", "# tool content")
        client.get.assert_awaited_once_with(file_url, headers=get_github_headers())

    async def test_recurses_into_subdirectories(self):
        client = AsyncMock()
        client.get.side_effect = [
            _github_response(
                200,
                json=[
                    _contents_entry(
                        "reference.md",
                        "file",
                        "skills/my-skill/resources/reference.md",
                        "https://raw/org/repo/main/skills/my-skill/resources/reference.md",
                    )
                ],
            ),
            _github_response(200, text="# Reference"),
        ]
        contents = [_contents_entry("resources", "dir", "skills/my-skill/resources")]
        file_list: list[str] = []

        with patch(
            "app.agents.skills.installer.write_skill_file",
            new_callable=AsyncMock,
        ) as write_mock:
            await _download_github_dir(
                user_id="u1",
                skill_name="my-skill",
                owner="org",
                repo="repo",
                remote_path="skills/my-skill",
                contents=contents,
                file_list=file_list,
                client=client,
            )

        assert file_list == ["resources/reference.md"]
        write_mock.assert_awaited_once_with(
            "u1", "my-skill", "resources/reference.md", "# Reference"
        )
        assert client.get.await_count == 2
        assert client.get.await_args_list == [
            call(
                f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/my-skill/resources",
                params={"ref": "main"},
                headers=get_github_headers(),
            ),
            call(
                "https://raw/org/repo/main/skills/my-skill/resources/reference.md",
                headers=get_github_headers(),
            ),
        ]


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


class TestInstallFromGithubContract:
    async def test_passes_exact_registry_and_vfs_contract(self, full_seams):
        """Every install_skill kwarg, the VFS write, the storage path, and the
        wide-event log calls must be exact — any drift here silently breaks
        the skill registry or discovery."""
        write_mock, install_mock, ensure_mock, log_mock = full_seams
        with respx.mock:
            respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/rich-skill").mock(
                return_value=httpx.Response(
                    200,
                    json=[_contents_entry("SKILL.md", "file", "skills/rich-skill/SKILL.md")],
                )
            )
            respx.get(
                "https://raw.githubusercontent.com/org/repo/main/skills/rich-skill/SKILL.md"
            ).mock(return_value=httpx.Response(200, text=_RICH_SKILL_MD))

            result = await install_from_github(
                user_id="u1", repo_url="org/repo/skills/rich-skill"
            )

        assert result is sentinel.installed_skill
        install_mock.assert_awaited_once()
        assert install_mock.await_args.kwargs == {
            "user_id": "u1",
            "name": "rich-skill",
            "description": "Rich metadata skill",
            "target": "executor",
            "vfs_path": "/skills/u1/rich-skill",
            "source": SkillSource.GITHUB,
            "source_url": "https://github.com/org/repo/tree/main/skills/rich-skill",
            "body_content": "Rich body instructions.",
            "files": ["SKILL.md"],
            "license": "MIT",
            "compatibility": "python>=3.12",
            "metadata": {"author": "Acme", "version": "1.2.3"},
            "allowed_tools": ["tool_one", "tool_two"],
        }
        ensure_mock.assert_awaited_once_with("u1")
        write_mock.assert_awaited_once_with("u1", "rich-skill", "SKILL.md", "Rich body instructions.")
        log_mock.set.assert_called_once_with(user_id="u1", skill={"operation": "install"})
        log_mock.set_ns.assert_called_once_with("skill", skill_name="rich-skill")
        assert log_mock.info.call_count == 2
        assert log_mock.info.call_args_list[0].kwargs == {
            "owner": "org",
            "repo": "repo",
            "base_path": "skills/rich-skill",
        }
        assert log_mock.info.call_args_list[1].kwargs == {
            "skill_name": "rich-skill",
            "file_count": 1,
            "target": "executor",
        }

    async def test_full_url_and_skill_path_combine_into_base_path(self, full_seams):
        _, install_mock, _, _ = full_seams
        with respx.mock:
            # Matching this exact contents URL proves base_path ==
            # "skills/my-skill" after combining the URL path with skill_path.
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
                repo_url="https://github.com/org/repo/tree/main/skills",
                skill_path="my-skill",
            )

        assert install_mock.await_args.kwargs["vfs_path"] == "/skills/u1/my-skill"
        assert (
            install_mock.await_args.kwargs["source_url"]
            == "https://github.com/org/repo/tree/main/skills/my-skill"
        )

    async def test_master_branch_fallback_installs_skill(self, full_seams):
        _, install_mock, _, _ = full_seams
        with respx.mock:
            respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/my-skill").mock(
                side_effect=[
                    httpx.Response(404),
                    httpx.Response(
                        200,
                        json=[_contents_entry("SKILL.md", "file", "skills/my-skill/SKILL.md")],
                    ),
                ]
            )
            respx.get(
                "https://raw.githubusercontent.com/org/repo/main/skills/my-skill/SKILL.md"
            ).mock(return_value=httpx.Response(200, text=_SKILL_MD_CONTENT))

            await install_from_github(user_id="u1", repo_url="org/repo/skills/my-skill")

        install_mock.assert_awaited_once()
        assert install_mock.await_args.kwargs["name"] == "my-skill"


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
            with pytest.raises(
                ValueError,
                match=re.escape(
                    "No SKILL.md found in org/repo/skills/empty. "
                    "A valid skill must contain a SKILL.md file."
                ),
            ):
                await install_from_github(user_id="u1", repo_url="org/repo/skills/empty")

    async def test_invalid_skill_md_raises_with_validation_errors(self, storage_seams):
        with respx.mock:
            respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/my-skill").mock(
                return_value=httpx.Response(
                    200,
                    json=[_contents_entry("SKILL.md", "file", "skills/my-skill/SKILL.md")],
                )
            )
            respx.get(
                "https://raw.githubusercontent.com/org/repo/main/skills/my-skill/SKILL.md"
            ).mock(return_value=httpx.Response(200, text=_INVALID_SKILL_MD))

            with pytest.raises(
                ValueError,
                match=re.escape("Invalid SKILL.md: Missing required field: description"),
            ):
                await install_from_github(user_id="u1", repo_url="org/repo/skills/my-skill")

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
            with pytest.raises(
                ValueError,
                match=re.escape(
                    "Target 'executor' is not available. "
                    "Connect the integration before installing a skill scoped to it."
                ),
            ):
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

    async def test_empty_target_override_falls_back_to_frontmatter(self, storage_seams):
        _, install_mock = storage_seams
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
                target_override="",
            )

        assert install_mock.await_args.kwargs["target"] == "executor"

    async def test_no_skill_path_raises_value_error(self, storage_seams):
        with pytest.raises(
            ValueError,
            match=re.escape(
                "Provide a path to the skill folder within the repo. "
                "Example: 'owner/repo/skills/my-skill' or use skill_path parameter."
            ),
        ):
            await install_from_github(user_id="u1", repo_url="org/repo")


def _skill_model(
    skill_id: str = "skill-1",
    name: str = "my-skill",
    description: str = "A test skill",
    target: str = "executor",
    body_content: str | None = "Do the thing when asked.",
) -> Skill:
    return Skill(
        id=skill_id,
        user_id="u1",
        name=name,
        description=description,
        target=target,
        vfs_path=f"/skills/u1/{name}",
        source=SkillSource.INLINE,
        body_content=body_content,
        files=["SKILL.md"],
    )


@pytest.fixture
def update_seams():
    """Mocks for update_skill_inline: the registry lookups, the registry
    update, the VFS write boundary, and the wide-event logger."""
    with (
        patch(
            "app.agents.skills.installer.get_skill",
            new_callable=AsyncMock,
        ) as get_mock,
        patch(
            "app.agents.skills.installer.get_skill_by_name",
            new_callable=AsyncMock,
        ) as get_by_name_mock,
        patch(
            "app.agents.skills.installer.update_skill",
            new_callable=AsyncMock,
        ) as update_mock,
        patch(
            "app.agents.skills.installer.ensure_user_skills_dir",
            new_callable=AsyncMock,
        ) as ensure_mock,
        patch(
            "app.agents.skills.installer.write_skill_file",
            new_callable=AsyncMock,
        ) as write_mock,
        patch("app.agents.skills.installer.log") as log_mock,
    ):
        update_mock.return_value = sentinel.updated_skill
        yield get_mock, get_by_name_mock, update_mock, ensure_mock, write_mock, log_mock


@pytest.fixture
def uninstall_seams():
    """Mocks for uninstall_skill_full: the registry lookups, the VFS delete
    boundary, the registry delete, and the wide-event logger."""
    with (
        patch(
            "app.agents.skills.installer.get_skill",
            new_callable=AsyncMock,
        ) as get_mock,
        patch(
            "app.agents.skills.installer.delete_user_skill",
            new_callable=AsyncMock,
        ) as delete_mock,
        patch(
            "app.agents.skills.installer.uninstall_skill",
            new_callable=AsyncMock,
        ) as uninstall_mock,
        patch("app.agents.skills.installer.log") as log_mock,
    ):
        yield get_mock, delete_mock, uninstall_mock, log_mock


class TestInstallFromInline:
    async def test_passes_exact_registry_and_vfs_contract(self, full_seams):
        """Every install_skill kwarg, the VFS write, the storage path, and the
        wide-event log calls must be exact — the inline path shares the flat
        registry schema with the GitHub path."""
        write_mock, install_mock, ensure_mock, log_mock = full_seams

        result = await install_from_inline(
            user_id="u1",
            name="my-skill",
            description="Inline description",
            instructions="Do the inline thing.",
            target="gmail_agent",
            extra_metadata={"author": "Acme"},
        )

        assert result is sentinel.installed_skill
        ensure_mock.assert_awaited_once_with("u1")
        write_mock.assert_awaited_once_with("u1", "my-skill", "SKILL.md", "Do the inline thing.")
        install_mock.assert_awaited_once()
        assert install_mock.await_args.kwargs == {
            "user_id": "u1",
            "name": "my-skill",
            "description": "Inline description",
            "target": "gmail_agent",
            "vfs_path": "/skills/u1/my-skill",
            "source": SkillSource.INLINE,
            "body_content": "Do the inline thing.",
            "files": ["SKILL.md"],
            "license": None,
            "compatibility": None,
            "metadata": {"author": "Acme"},
            "allowed_tools": [],
        }
        log_mock.set.assert_called_once_with(
            user_id="u1", skill={"operation": "install", "skill_name": "my-skill"}
        )
        log_mock.info.assert_called_once_with(
            f"{LogTag.SKILLS} Created inline skill", skill_name="my-skill", target="gmail_agent"
        )

    async def test_default_target_and_no_metadata(self, storage_seams):
        write_mock, install_mock = storage_seams

        await install_from_inline(
            user_id="u1",
            name="my-skill",
            description="A test skill",
            instructions="Do the thing when asked.",
        )

        install_mock.assert_awaited_once()
        assert install_mock.await_args.kwargs["target"] == "executor"
        assert install_mock.await_args.kwargs["source"] is SkillSource.INLINE
        assert install_mock.await_args.kwargs["metadata"] == {}
        assert install_mock.await_args.kwargs["allowed_tools"] == []
        write_mock.assert_awaited_once_with("u1", "my-skill", "SKILL.md", "Do the thing when asked.")

    async def test_validation_errors_raise_and_abort(self, storage_seams):
        write_mock, install_mock = storage_seams

        with patch(
            "app.agents.skills.installer.validate_skill_content",
            return_value=["error one", "error two"],
        ):
            with pytest.raises(ValueError, match=re.escape("Invalid skill: error one; error two")):
                await install_from_inline(
                    user_id="u1",
                    name="my-skill",
                    description="A test skill",
                    instructions="Do the thing when asked.",
                )

        write_mock.assert_not_awaited()
        install_mock.assert_not_awaited()


class TestUpdateSkillInline:
    async def test_not_found_returns_none(self, update_seams):
        get_mock, get_by_name_mock, update_mock, ensure_mock, write_mock, log_mock = update_seams
        get_mock.return_value = None

        result = await update_skill_inline("u1", "missing-id", description="New desc")

        assert result is None
        get_mock.assert_awaited_once_with("u1", "missing-id")
        get_by_name_mock.assert_not_awaited()
        update_mock.assert_not_awaited()
        ensure_mock.assert_not_awaited()
        write_mock.assert_not_awaited()
        log_mock.set.assert_not_called()

    async def test_description_only_update_keeps_body_and_skips_vfs(self, update_seams):
        get_mock, get_by_name_mock, update_mock, ensure_mock, write_mock, log_mock = update_seams
        get_mock.return_value = _skill_model()

        result = await update_skill_inline("u1", "skill-1", description="Renamed description")

        assert result is sentinel.updated_skill
        get_by_name_mock.assert_not_awaited()
        ensure_mock.assert_not_awaited()
        write_mock.assert_not_awaited()
        update_mock.assert_awaited_once_with(
            "u1",
            "skill-1",
            {
                "description": "Renamed description",
                "target": "executor",
                "body_content": "Do the thing when asked.",
            },
        )
        log_mock.info.assert_called_once_with(
            f"{LogTag.SKILLS} Updated inline skill", skill_name="my-skill", target="executor"
        )

    async def test_none_body_skill_description_update_keeps_empty_body(self, update_seams):
        get_mock, get_by_name_mock, update_mock, ensure_mock, write_mock, _ = update_seams
        get_mock.return_value = _skill_model(body_content=None)

        await update_skill_inline("u1", "skill-1", description="Renamed description")

        get_by_name_mock.assert_not_awaited()
        ensure_mock.assert_not_awaited()
        write_mock.assert_not_awaited()
        update_mock.assert_awaited_once_with(
            "u1",
            "skill-1",
            {
                "description": "Renamed description",
                "target": "executor",
                "body_content": "",
            },
        )

    async def test_skill_metadata_preserved_in_generated_frontmatter(self, update_seams):
        get_mock, get_by_name_mock, update_mock, _, write_mock, _ = update_seams
        skill = _skill_model()
        skill.metadata = {"author": "Acme"}
        get_mock.return_value = skill

        with patch(
            "app.agents.skills.installer.generate_skill_md",
            return_value=_SKILL_MD_CONTENT,
        ) as generate_mock:
            await update_skill_inline("u1", "skill-1", description="Renamed description")

        generate_mock.assert_called_once_with(
            name="my-skill",
            description="Renamed description",
            instructions="Do the thing when asked.",
            target="executor",
            metadata={"author": "Acme"},
        )
        get_by_name_mock.assert_not_awaited()
        write_mock.assert_not_awaited()
        update_mock.assert_awaited_once_with(
            "u1",
            "skill-1",
            {
                "description": "A test skill installed from GitHub",
                "target": "executor",
                "body_content": "Do the thing when asked.",
            },
        )

    async def test_instructions_change_rewrites_vfs_body(self, update_seams):
        get_mock, _, update_mock, ensure_mock, write_mock, _ = update_seams
        get_mock.return_value = _skill_model()

        await update_skill_inline("u1", "skill-1", instructions="New instructions here.")

        ensure_mock.assert_awaited_once_with("u1")
        write_mock.assert_awaited_once_with("u1", "my-skill", "SKILL.md", "New instructions here.")
        update_mock.assert_awaited_once_with(
            "u1",
            "skill-1",
            {
                "description": "A test skill",
                "target": "executor",
                "body_content": "New instructions here.",
            },
        )

    async def test_retarget_checks_clash_with_target_skill(self, update_seams):
        get_mock, get_by_name_mock, update_mock, ensure_mock, write_mock, _ = update_seams
        get_mock.return_value = _skill_model()
        get_by_name_mock.return_value = None

        await update_skill_inline("u1", "skill-1", target="gmail_agent")

        get_by_name_mock.assert_awaited_once_with("u1", "my-skill", "gmail_agent")
        ensure_mock.assert_not_awaited()
        write_mock.assert_not_awaited()
        update_mock.assert_awaited_once_with(
            "u1",
            "skill-1",
            {
                "description": "A test skill",
                "target": "gmail_agent",
                "body_content": "Do the thing when asked.",
            },
        )

    async def test_retarget_clash_with_other_skill_raises(self, update_seams):
        get_mock, get_by_name_mock, update_mock, _, _, _ = update_seams
        get_mock.return_value = _skill_model()
        get_by_name_mock.return_value = _skill_model(skill_id="other-skill")

        with pytest.raises(
            ValueError,
            match=re.escape(
                "A skill named 'my-skill' already targets 'gmail_agent'. Rename or remove it first."
            ),
        ):
            await update_skill_inline("u1", "skill-1", target="gmail_agent")

        update_mock.assert_not_awaited()

    async def test_retarget_same_skill_clash_is_allowed(self, update_seams):
        get_mock, get_by_name_mock, update_mock, _, _, _ = update_seams
        skill = _skill_model()
        get_mock.return_value = skill
        get_by_name_mock.return_value = skill

        result = await update_skill_inline("u1", "skill-1", target="gmail_agent")

        assert result is sentinel.updated_skill
        get_by_name_mock.assert_awaited_once_with("u1", "my-skill", "gmail_agent")
        update_mock.assert_awaited_once()

    async def test_validation_errors_raise_and_abort(self, update_seams):
        get_mock, get_by_name_mock, update_mock, _, _, _ = update_seams
        get_mock.return_value = _skill_model()

        with patch(
            "app.agents.skills.installer.validate_skill_content",
            return_value=["bad target", "no instructions"],
        ):
            with pytest.raises(
                ValueError, match=re.escape("Invalid skill: bad target; no instructions")
            ):
                await update_skill_inline("u1", "skill-1", target="gmail_agent")

        get_by_name_mock.assert_not_awaited()
        update_mock.assert_not_awaited()


class TestUninstallSkillFull:
    async def test_not_found_returns_false(self, uninstall_seams):
        get_mock, delete_mock, uninstall_mock, log_mock = uninstall_seams
        get_mock.return_value = None

        result = await uninstall_skill_full("u1", "missing-id")

        assert result is False
        get_mock.assert_awaited_once_with("u1", "missing-id")
        delete_mock.assert_not_awaited()
        uninstall_mock.assert_not_awaited()
        log_mock.set.assert_not_called()

    async def test_deletes_storage_and_registry_with_exact_args(self, uninstall_seams):
        get_mock, delete_mock, uninstall_mock, log_mock = uninstall_seams
        get_mock.return_value = _skill_model()
        uninstall_mock.return_value = True

        result = await uninstall_skill_full("u1", "skill-1")

        assert result is True
        delete_mock.assert_awaited_once_with("u1", "my-skill")
        uninstall_mock.assert_awaited_once_with("u1", "skill-1")
        log_mock.set.assert_called_once_with(
            user_id="u1",
            skill={"operation": "delete", "skill_id": "skill-1", "skill_name": "my-skill"},
        )
        log_mock.warning.assert_not_called()

    async def test_storage_unavailable_still_uninstalls(self, uninstall_seams):
        get_mock, delete_mock, uninstall_mock, log_mock = uninstall_seams
        get_mock.return_value = _skill_model()
        delete_mock.side_effect = JuiceFSUnavailable("mount down")
        uninstall_mock.return_value = True

        result = await uninstall_skill_full("u1", "skill-1")

        assert result is True
        uninstall_mock.assert_awaited_once_with("u1", "skill-1")
        log_mock.warning.assert_called_once()
        assert (
            log_mock.warning.call_args.args[0]
            == f"{LogTag.SKILLS} storage cleanup skipped (mount unavailable)"
        )
        assert log_mock.warning.call_args.kwargs["error_type"] == "JuiceFSUnavailable"

    async def test_storage_other_error_logged_and_still_uninstalls(self, uninstall_seams):
        get_mock, delete_mock, uninstall_mock, log_mock = uninstall_seams
        get_mock.return_value = _skill_model()
        delete_mock.side_effect = RuntimeError("boom")
        uninstall_mock.return_value = True

        result = await uninstall_skill_full("u1", "skill-1")

        assert result is True
        uninstall_mock.assert_awaited_once_with("u1", "skill-1")
        log_mock.warning.assert_called_once()
        assert log_mock.warning.call_args.args[0] == f"{LogTag.SKILLS} storage cleanup failed"
        assert log_mock.warning.call_args.kwargs["skill_id"] == "skill-1"
        assert log_mock.warning.call_args.kwargs["error_type"] == "RuntimeError"

    async def test_registry_miss_returns_false(self, uninstall_seams):
        get_mock, delete_mock, uninstall_mock, _ = uninstall_seams
        get_mock.return_value = _skill_model()
        uninstall_mock.return_value = False

        result = await uninstall_skill_full("u1", "skill-1")

        assert result is False
        delete_mock.assert_awaited_once_with("u1", "my-skill")
        uninstall_mock.assert_awaited_once_with("u1", "skill-1")
