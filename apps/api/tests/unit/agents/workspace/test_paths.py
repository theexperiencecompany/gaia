"""Filename sanitization for session workspace paths."""

import pytest

from app.agents.workspace.paths import MountRole, classify, safe_upload_filename


def test_keeps_only_the_basename_of_a_posix_path() -> None:
    assert safe_upload_filename("a/b/file.png") == "file.png"


def test_keeps_only_the_basename_of_a_windows_path() -> None:
    assert safe_upload_filename("C:\\dir\\file.png") == "file.png"


def test_replaces_unsafe_characters() -> None:
    assert safe_upload_filename("my file (1).png") == "my_file__1_.png"


def test_strips_non_printable_and_nul_bytes() -> None:
    assert safe_upload_filename("\x00a\x01b.png") == "ab.png"


def test_strips_leading_dots() -> None:
    assert safe_upload_filename(".env") == "env"


def test_caps_the_name_at_the_filesystem_limit() -> None:
    assert len(safe_upload_filename("a" * 300 + ".png")) == 255


@pytest.mark.parametrize("filename", ["", "...", "///", "\x00"])
def test_a_name_that_sanitizes_away_raises(filename: str) -> None:
    with pytest.raises(ValueError):
        safe_upload_filename(filename)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/workspace/skills/a.md", (MountRole.SKILLS, None)),
        ("/workspace/settings/x", (MountRole.SETTINGS, None)),
        ("/workspace/pinned/x", (MountRole.PINNED, None)),
        ("/workspace/.gaia/runs", (MountRole.GAIA_RUNTIME, None)),
        ("/workspace/sessions/c1/scratch/a", (MountRole.SCRATCH, "c1")),
        ("/workspace/sessions/c1/user-uploaded/a", (MountRole.USER_UPLOADED, "c1")),
        ("/workspace/sessions/c1/artifacts/a", (MountRole.ARTIFACTS, "c1")),
        ("/workspace/sessions/c1/other/a", (MountRole.SCRATCH, "c1")),
        ("/workspace/sessions/c1", (MountRole.UNKNOWN, None)),
        ("/workspace", (MountRole.UNKNOWN, None)),
        ("/workspace/elsewhere/a", (MountRole.UNKNOWN, None)),
        ("/tmp/a", (MountRole.UNKNOWN, None)),
    ],
)
def test_classify_routes_each_root_to_its_mount(
    path: str, expected: tuple[MountRole, str | None]
) -> None:
    assert classify(path) == expected
