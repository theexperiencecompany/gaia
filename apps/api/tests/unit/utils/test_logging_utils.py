"""Unit tests for app.utils.logging_utils — log record path shortening."""

from unittest.mock import MagicMock

import pytest

from app.utils.logging_utils import shorten_path


# ---------------------------------------------------------------------------
# shorten_path
# ---------------------------------------------------------------------------


class TestShortenPath:
    """Tests for shorten_path helper."""

    # -- record["file"] with .path attribute --

    def test_path_attribute_deep_nested(self):
        """When record['file'] has a .path attr, uses it and shortens to parent/stem."""
        file_obj = MagicMock()
        file_obj.path = "/home/user/project/app/utils/logging_utils.py"
        record: dict = {"file": file_obj}

        result = shorten_path(record)

        assert result == "utils/logging_utils"
        assert record["short_file"] == "utils/logging_utils"

    def test_path_attribute_two_parts(self):
        """Two-part path returns parent/stem."""
        file_obj = MagicMock()
        file_obj.path = "app/main.py"
        record: dict = {"file": file_obj}

        result = shorten_path(record)

        assert result == "app/main"
        assert record["short_file"] == "app/main"

    def test_path_attribute_single_part(self):
        """Single filename (no directory) returns just the stem."""
        file_obj = MagicMock()
        file_obj.path = "server.py"
        record: dict = {"file": file_obj}

        result = shorten_path(record)

        assert result == "server"
        assert record["short_file"] == "server"

    # -- record["file"] without .path attribute (falls to str()) --

    def test_string_file_deep_nested(self):
        """When record['file'] is a plain string, shortens to parent/stem."""
        record: dict = {"file": "/var/log/app/services/auth.py"}

        result = shorten_path(record)

        assert result == "services/auth"
        assert record["short_file"] == "services/auth"

    def test_string_file_two_parts(self):
        """Two-part string path returns parent/stem."""
        record: dict = {"file": "handlers/event.py"}

        result = shorten_path(record)

        assert result == "handlers/event"
        assert record["short_file"] == "handlers/event"

    def test_string_file_single_part(self):
        """Single filename string returns just the stem."""
        record: dict = {"file": "app.py"}

        result = shorten_path(record)

        assert result == "app"
        assert record["short_file"] == "app"

    # -- edge cases --

    @pytest.mark.parametrize(
        ("file_path", "expected"),
        [
            ("/a/b/c/d/e.py", "d/e"),
            ("a/b.py", "a/b"),
            ("solo.py", "solo"),
            # On POSIX, Path("/root.py").parts == ('/', 'root.py') — 2 parts,
            # so parent part is '/' and result is '//root'.
            ("/root.py", "//root"),
        ],
        ids=[
            "deeply_nested",
            "two_parts",
            "single_file",
            "root_single_file",
        ],
    )
    def test_parametrized_string_paths(self, file_path: str, expected: str):
        """Parametrized tests for various path depths as plain strings."""
        record: dict = {"file": file_path}
        result = shorten_path(record)
        assert result == expected

    @pytest.mark.parametrize(
        ("file_path", "expected"),
        [
            ("/a/b/c/d/e.py", "d/e"),
            ("a/b.py", "a/b"),
            ("solo.py", "solo"),
            ("/root.py", "//root"),
        ],
        ids=[
            "deeply_nested",
            "two_parts",
            "single_file",
            "root_single_file",
        ],
    )
    def test_parametrized_path_attr_paths(self, file_path: str, expected: str):
        """Parametrized tests for various path depths via .path attribute."""
        file_obj = MagicMock()
        file_obj.path = file_path
        record: dict = {"file": file_obj}
        result = shorten_path(record)
        assert result == expected

    def test_extension_stripped_from_stem(self):
        """The file extension is always stripped (stem, not name)."""
        record: dict = {"file": "pkg/module.service.py"}
        result = shorten_path(record)
        # Path.stem strips only the last extension
        assert result == "pkg/module.service"

    def test_no_extension(self):
        """Files without an extension still work."""
        record: dict = {"file": "dir/Makefile"}
        result = shorten_path(record)
        assert result == "dir/Makefile"

    def test_record_mutated_with_short_file(self):
        """Confirms that the record dict is mutated in-place with 'short_file'."""
        record: dict = {"file": "a/b/c.py"}
        shorten_path(record)
        assert "short_file" in record
        assert record["short_file"] == "b/c"

    def test_return_value_matches_record(self):
        """Return value equals the value set on record['short_file']."""
        record: dict = {"file": "x/y/z.py"}
        result = shorten_path(record)
        assert result == record["short_file"]

    def test_path_with_dots_in_directory(self):
        """Directories with dots should not confuse the stem extraction."""
        record: dict = {"file": "/home/user/.config/app/settings.py"}
        result = shorten_path(record)
        assert result == "app/settings"

    def test_windows_style_path_via_path_attr(self):
        """Path objects normalize separators, so Windows-style should still work."""
        file_obj = MagicMock()
        # On macOS/Linux, Path will treat backslashes as part of the name,
        # but if given forward slashes it works cross-platform.
        file_obj.path = "C:/Users/dev/project/module.py"
        record: dict = {"file": file_obj}
        result = shorten_path(record)
        # Path("C:/Users/dev/project/module.py").parts on POSIX:
        # ('C:', 'Users', 'dev', 'project', 'module.py') — >= 2 parts
        assert "module" in result
