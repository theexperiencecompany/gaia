"""Unit tests for command parsing utilities."""

import pytest

from app.utils.command_parsing import extract_output_redirect


@pytest.mark.unit
class TestExtractOutputRedirect:
    def test_simple_redirect(self):
        cmd, redirect = extract_output_redirect("echo hello > output.txt")
        assert cmd == "echo hello"
        assert redirect == (">", "output.txt")

    def test_append_redirect(self):
        cmd, redirect = extract_output_redirect("echo hello >> output.txt")
        assert cmd == "echo hello"
        assert redirect == (">>", "output.txt")

    def test_double_quoted_path(self):
        cmd, redirect = extract_output_redirect('echo hello > "my file.txt"')
        assert cmd == "echo hello"
        assert redirect == (">", "my file.txt")

    def test_single_quoted_path(self):
        cmd, redirect = extract_output_redirect("echo hello > 'my file.txt'")
        assert cmd == "echo hello"
        assert redirect == (">", "my file.txt")

    def test_no_redirect(self):
        cmd, redirect = extract_output_redirect("echo hello")
        assert cmd == "echo hello"
        assert redirect is None

    def test_empty_string(self):
        cmd, redirect = extract_output_redirect("")
        assert cmd == ""
        assert redirect is None

    def test_redirect_no_space(self):
        cmd, redirect = extract_output_redirect("echo hello >file.txt")
        assert cmd == "echo hello"
        assert redirect == (">", "file.txt")

    def test_append_no_space(self):
        cmd, redirect = extract_output_redirect("echo hello >>file.txt")
        assert cmd == "echo hello"
        assert redirect == (">>", "file.txt")

    def test_double_quoted_append(self):
        cmd, redirect = extract_output_redirect('echo hi >> "log file.txt"')
        assert cmd == "echo hi"
        assert redirect == (">>", "log file.txt")

    def test_whitespace_preserved(self):
        cmd, redirect = extract_output_redirect("  echo hello  > output.txt")
        assert cmd.strip() == "echo hello"
        assert redirect == (">", "output.txt")

    def test_no_filepath_after_redirect(self):
        """A lone > without a filename should not parse as redirect."""
        cmd, redirect = extract_output_redirect("echo >")
        # The '>' itself becomes the filepath candidate, but prefix is empty
        # so no redirect operator is found before it
        assert redirect is None

    def test_only_redirect_operator(self):
        cmd, redirect = extract_output_redirect(">")
        assert redirect is None

    def test_complex_command_with_redirect(self):
        cmd, redirect = extract_output_redirect("ls -la /tmp > listing.txt")
        assert cmd == "ls -la /tmp"
        assert redirect == (">", "listing.txt")

    def test_path_with_directory(self):
        cmd, redirect = extract_output_redirect("cat data > /tmp/output.csv")
        assert cmd == "cat data"
        assert redirect == (">", "/tmp/output.csv")

    def test_double_quoted_path_with_backslash(self):
        """Backslash-escaped quotes inside double quotes."""
        cmd, redirect = extract_output_redirect(r'echo test > "path\"quoted.txt"')
        # The escaped quote should not be treated as the opening quote
        assert redirect is not None
