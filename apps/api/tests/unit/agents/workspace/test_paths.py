"""Filename sanitization for session workspace paths."""

import pytest

from app.agents.workspace.paths import safe_upload_filename


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
