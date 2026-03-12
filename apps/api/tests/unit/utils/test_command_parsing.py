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
        assert cmd == "  echo hello"
        assert redirect == (">", "output.txt")

    def test_no_filepath_after_redirect(self):
        """A lone > without a filename should not parse as redirect."""
        cmd, redirect = extract_output_redirect("echo >")
        # The '>' itself becomes the filepath candidate, but prefix is empty
        # so no redirect operator is found before it
        assert redirect is None

    def test_only_redirect_operator(self):
        _, redirect = extract_output_redirect(">")
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
        # The escaped quote inside the path is preserved as-is; the outer quotes delimit the path
        assert cmd == "echo test"
        assert redirect == (">", r"path\"quoted.txt")

    def test_redirect_operator_immediately_after_command_no_space(self):
        """Redirect operator attached directly to command with no separating space."""
        cmd, redirect = extract_output_redirect("pwd>/tmp/here.txt")
        assert cmd == "pwd"
        assert redirect == (">", "/tmp/here.txt")

    def test_only_whitespace(self):
        """Whitespace-only input yields no redirect."""
        _, redirect = extract_output_redirect("   ")
        assert redirect is None

    def test_malformed_no_operator(self):
        """Plain word with no redirect operator returns the input unchanged."""
        cmd, redirect = extract_output_redirect("justcommand")
        assert cmd == "justcommand"
        assert redirect is None

    def test_redirect_to_path_with_special_chars(self):
        """Path containing hyphens, underscores and dots is extracted correctly."""
        cmd, redirect = extract_output_redirect("run-script > /var/log/my_app.log")
        assert cmd == "run-script"
        assert redirect == (">", "/var/log/my_app.log")

    def test_redirect_to_relative_path_with_dots(self):
        """Relative path using dot-segments is preserved verbatim."""
        cmd, redirect = extract_output_redirect("make > ../build/output.txt")
        assert cmd == "make"
        assert redirect == (">", "../build/output.txt")

    def test_multiple_redirect_operators_only_last_matters(self):
        """When the filepath token itself starts with >>, that is parsed as no-space append."""
        cmd, redirect = extract_output_redirect("cat file.txt >>out.log")
        assert cmd == "cat file.txt"
        assert redirect == (">>", "out.log")

    def test_append_redirect_to_path_with_spaces(self):
        """Append redirect with a quoted path that has spaces is parsed correctly."""
        cmd, redirect = extract_output_redirect("echo data >> 'my output file.log'")
        assert cmd == "echo data"
        assert redirect == (">>", "my output file.log")
