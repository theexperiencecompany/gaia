from app.utils.command_parsing import extract_output_redirect


class TestExtractOutputRedirect:
    def test_redirect_unquoted_with_space(self):
        cmd, redirect = extract_output_redirect("echo hi > out.txt")
        assert cmd == "echo hi"
        assert redirect == (">", "out.txt")

    def test_redirect_unquoted_no_space(self):
        cmd, redirect = extract_output_redirect("echo hi >out.txt")
        assert cmd == "echo hi"
        assert redirect == (">", "out.txt")

    def test_redirect_append_no_space(self):
        cmd, redirect = extract_output_redirect("echo hi >>out.txt")
        assert cmd == "echo hi"
        assert redirect == (">>", "out.txt")

    def test_redirect_double_quoted_path(self):
        cmd, redirect = extract_output_redirect('echo hi > "my file.txt"')
        assert cmd == "echo hi"
        assert redirect == (">", "my file.txt")

    def test_redirect_single_quoted_path(self):
        cmd, redirect = extract_output_redirect("echo hi > 'my file.txt'")
        assert cmd == "echo hi"
        assert redirect == (">", "my file.txt")

    def test_trailing_whitespace_is_ignored(self):
        cmd, redirect = extract_output_redirect("echo hi > out.txt   \n")
        assert cmd == "echo hi"
        assert redirect == (">", "out.txt")

    def test_does_not_match_redirect_not_at_end(self):
        cmd, redirect = extract_output_redirect("echo hi > out.txt extra")
        assert cmd == "echo hi > out.txt extra"
        assert redirect is None

    def test_does_not_match_when_missing_filepath(self):
        cmd, redirect = extract_output_redirect("echo hi >")
        assert cmd == "echo hi >"
        assert redirect is None

    def test_does_not_match_empty_double_quoted_filepath(self):
        cmd, redirect = extract_output_redirect('echo hi > ""')
        assert cmd == 'echo hi > ""'
        assert redirect is None

    def test_does_not_match_empty_single_quoted_filepath(self):
        cmd, redirect = extract_output_redirect("echo hi > ''")
        assert cmd == "echo hi > ''"
        assert redirect is None

    def test_preserves_escaped_quote_in_double_quoted_filepath(self):
        cmd, redirect = extract_output_redirect('echo hi > "a\\"b.txt"')
        assert cmd == "echo hi"
        assert redirect == (">", 'a\\"b.txt')
