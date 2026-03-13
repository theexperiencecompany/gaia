"""Unit tests for VFS grep enhancements (-v, -w, -o, -e, -A/-B/-C, --include/--exclude)."""

import argparse

import pytest

from app.agents.tools.vfs_cmd_parser import VFSCommandParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FILE_PATH = "/users/u1/docs/file.txt"
BASE_PATH = "/users/u1/docs"


def _make_args(**kwargs: object) -> argparse.Namespace:
    """Build an argparse.Namespace with sensible grep defaults."""
    defaults: dict[str, object] = {
        "pattern": None,
        "patterns": None,
        "path": ".",
        "ignore_case": False,
        "recursive": False,
        "line_number": True,
        "count": False,
        "files_with_matches": False,
        "invert_match": False,
        "word_regexp": False,
        "only_matching": False,
        "after_context": 0,
        "before_context": 0,
        "context": 0,
        "include_globs": None,
        "exclude_globs": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _parser() -> VFSCommandParser:
    return VFSCommandParser()


# ---------------------------------------------------------------------------
# _prepare_grep_pattern
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareGrepPattern:
    def test_single_positional_pattern(self) -> None:
        args = _make_args(pattern="hello")
        assert VFSCommandParser._prepare_grep_pattern(args) == "hello"

    def test_no_pattern_returns_none(self) -> None:
        args = _make_args(pattern=None, patterns=None)
        assert VFSCommandParser._prepare_grep_pattern(args) is None

    def test_only_e_patterns(self) -> None:
        args = _make_args(pattern=None, patterns=["foo", "bar"])
        result = VFSCommandParser._prepare_grep_pattern(args)
        assert result == "(?:foo)|(?:bar)"

    def test_positional_plus_e_patterns_combined(self) -> None:
        args = _make_args(pattern="hello", patterns=["world", "foo"])
        result = VFSCommandParser._prepare_grep_pattern(args)
        assert result is not None
        assert "(?:hello)" in result
        assert "(?:world)" in result
        assert "(?:foo)" in result
        assert "|" in result

    def test_word_regexp_wraps_in_boundaries(self) -> None:
        args = _make_args(pattern="cat", word_regexp=True)
        result = VFSCommandParser._prepare_grep_pattern(args)
        assert result == r"\b(?:cat)\b"

    def test_word_regexp_with_multiple_patterns(self) -> None:
        args = _make_args(pattern=None, patterns=["cat", "dog"], word_regexp=True)
        result = VFSCommandParser._prepare_grep_pattern(args)
        assert result is not None
        assert result.startswith(r"\b(")
        assert result.endswith(r")\b")
        assert "cat" in result
        assert "dog" in result

    def test_empty_patterns_list_with_no_positional(self) -> None:
        args = _make_args(pattern=None, patterns=[])
        assert VFSCommandParser._prepare_grep_pattern(args) is None


# ---------------------------------------------------------------------------
# _matches_glob_filters
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMatchesGlobFilters:
    def test_no_filters_always_true(self) -> None:
        assert VFSCommandParser._matches_glob_filters("anything.py", None, None) is True

    def test_include_match(self) -> None:
        assert VFSCommandParser._matches_glob_filters("file.py", ["*.py"], None) is True

    def test_include_no_match(self) -> None:
        assert VFSCommandParser._matches_glob_filters("file.js", ["*.py"], None) is False

    def test_exclude_match(self) -> None:
        assert VFSCommandParser._matches_glob_filters("file.pyc", None, ["*.pyc"]) is False

    def test_exclude_no_match(self) -> None:
        assert VFSCommandParser._matches_glob_filters("file.py", None, ["*.pyc"]) is True

    def test_include_and_exclude_both_pass(self) -> None:
        assert (
            VFSCommandParser._matches_glob_filters("util.py", ["*.py"], ["test_*"]) is True
        )

    def test_include_passes_but_exclude_blocks(self) -> None:
        assert (
            VFSCommandParser._matches_glob_filters("test_util.py", ["*.py"], ["test_*"])
            is False
        )

    def test_include_blocks_regardless_of_exclude(self) -> None:
        # Doesn't match include → False (exclude irrelevant)
        assert (
            VFSCommandParser._matches_glob_filters("file.js", ["*.py"], ["test_*"]) is False
        )

    def test_multiple_include_globs_any_match(self) -> None:
        assert (
            VFSCommandParser._matches_glob_filters(
                "index.ts", ["*.py", "*.ts", "*.js"], None
            )
            is True
        )

    def test_multiple_exclude_globs_any_match_blocks(self) -> None:
        assert (
            VFSCommandParser._matches_glob_filters(
                "test_foo.py", None, ["test_*", "conftest*"]
            )
            is False
        )


# ---------------------------------------------------------------------------
# _search_content — basic match
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchContentBasic:
    def test_single_match_returns_correct_entry(self) -> None:
        p = _parser()
        content = "hello world\nfoo bar\nbaz"
        args = _make_args(pattern="hello")
        result = p._search_content(content, "hello", FILE_PATH, BASE_PATH, args)
        assert result is not None
        assert len(result["matches"]) == 1
        m = result["matches"][0]
        assert m["line_num"] == 1
        assert "hello" in m["line"]
        assert m["is_context"] is False

    def test_no_match_returns_none(self) -> None:
        p = _parser()
        result = p._search_content("hello world", "xyz", FILE_PATH, BASE_PATH, _make_args())
        assert result is None

    def test_multiple_matching_lines(self) -> None:
        p = _parser()
        content = "alpha\nbeta\nalpha again"
        result = p._search_content(content, "alpha", FILE_PATH, BASE_PATH, _make_args())
        assert result is not None
        assert len(result["matches"]) == 2
        assert result["matches"][0]["line_num"] == 1
        assert result["matches"][1]["line_num"] == 3

    def test_invalid_regex_falls_back_to_literal(self) -> None:
        p = _parser()
        # "(" is invalid regex — should be treated as literal '('
        content = "hello (world)"
        result = p._search_content(content, "(world", FILE_PATH, BASE_PATH, _make_args())
        assert result is not None
        assert len(result["matches"]) == 1

    def test_case_insensitive_flag(self) -> None:
        p = _parser()
        content = "Hello World"
        result = p._search_content(
            content, "hello", FILE_PATH, BASE_PATH, _make_args(ignore_case=True)
        )
        assert result is not None
        assert len(result["matches"]) == 1

    def test_relative_path_stripped_from_base(self) -> None:
        p = _parser()
        content = "hello"
        result = p._search_content(content, "hello", FILE_PATH, BASE_PATH, _make_args())
        assert result is not None
        assert result["name"] == "file.txt"

    def test_relative_path_preserves_subdir(self) -> None:
        p = _parser()
        content = "hello"
        file_path = "/users/u1/docs/sub/notes.md"
        result = p._search_content(content, "hello", file_path, BASE_PATH, _make_args())
        assert result is not None
        assert result["name"] == "sub/notes.md"

    def test_line_truncated_at_max_length(self) -> None:
        p = _parser()
        long_line = "x" * 500
        result = p._search_content(long_line, "x", FILE_PATH, BASE_PATH, _make_args())
        assert result is not None
        assert len(result["matches"][0]["line"]) <= VFSCommandParser.MAX_LINE_LENGTH + 3


# ---------------------------------------------------------------------------
# _search_content — invert match (-v)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchContentInvert:
    def test_invert_returns_nonmatching_lines(self) -> None:
        p = _parser()
        content = "hello\nworld\nfoo"
        args = _make_args(invert_match=True)
        result = p._search_content(content, "hello", FILE_PATH, BASE_PATH, args)
        assert result is not None
        lines = [m["line"] for m in result["matches"]]
        assert "world" in lines
        assert "foo" in lines
        assert "hello" not in lines

    def test_invert_all_match_returns_none(self) -> None:
        p = _parser()
        content = "hello\nhello again"
        args = _make_args(invert_match=True)
        result = p._search_content(content, "hello", FILE_PATH, BASE_PATH, args)
        assert result is None

    def test_invert_marks_all_entries_not_context(self) -> None:
        p = _parser()
        content = "a\nb\nc"
        args = _make_args(invert_match=True)
        result = p._search_content(content, "b", FILE_PATH, BASE_PATH, args)
        assert result is not None
        lines = [m["line"] for m in result["matches"]]
        assert "a" in lines  # non-matching lines returned
        assert "c" in lines
        assert "b" not in lines  # matching line excluded
        assert all(m["is_context"] is False for m in result["matches"])

    def test_invert_with_context_disabled(self) -> None:
        """Context lines are NOT applied when invert_match is True."""
        p = _parser()
        content = "a\nb\nc"
        # even though context=2 is set, invert disables context
        args = _make_args(invert_match=True, context=2)
        result = p._search_content(content, "b", FILE_PATH, BASE_PATH, args)
        assert result is not None
        # only "a" and "c" (non-matching) — no context lines
        assert all(m["is_context"] is False for m in result["matches"])
        assert len(result["matches"]) == 2


# ---------------------------------------------------------------------------
# _search_content — only matching (-o)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchContentOnlyMatching:
    def test_only_matching_returns_match_group_not_full_line(self) -> None:
        p = _parser()
        content = "the cat sat on the mat"
        args = _make_args(only_matching=True)
        result = p._search_content(content, r"c\w+", FILE_PATH, BASE_PATH, args)
        assert result is not None
        lines = [m["line"] for m in result["matches"]]
        assert "cat" in lines
        # "the ", " sat on the mat" should NOT appear
        assert not any("the" in line for line in lines)

    def test_only_matching_multiple_matches_per_line(self) -> None:
        p = _parser()
        content = "cat bat hat"
        args = _make_args(only_matching=True)
        result = p._search_content(content, r"\w+at", FILE_PATH, BASE_PATH, args)
        assert result is not None
        lines = [m["line"] for m in result["matches"]]
        assert "cat" in lines
        assert "bat" in lines
        assert "hat" in lines
        # All on same line_num = 1
        assert all(m["line_num"] == 1 for m in result["matches"])

    def test_only_matching_ignored_when_invert(self) -> None:
        """With -v, -o has no effect (no regex match to extract)."""
        p = _parser()
        content = "hello\nworld"
        args = _make_args(only_matching=True, invert_match=True)
        result = p._search_content(content, "hello", FILE_PATH, BASE_PATH, args)
        assert result is not None
        # "world" (non-matching line) — shown as full line
        assert result["matches"][0]["line"] == "world"


# ---------------------------------------------------------------------------
# _search_content — context lines (-A/-B/-C)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchContentContext:
    def test_after_context_includes_lines_after_match(self) -> None:
        p = _parser()
        content = "line1\nline2\nmatch\nline4\nline5"
        args = _make_args(after_context=2)
        result = p._search_content(content, "match", FILE_PATH, BASE_PATH, args)
        assert result is not None
        matches = result["matches"]
        # match (line 3) + line4 (ctx) + line5 (ctx)
        assert len(matches) == 3
        assert matches[0]["line_num"] == 3
        assert matches[0]["is_context"] is False
        assert matches[1]["line_num"] == 4
        assert matches[1]["is_context"] is True
        assert matches[2]["line_num"] == 5
        assert matches[2]["is_context"] is True

    def test_before_context_includes_lines_before_match(self) -> None:
        p = _parser()
        content = "line1\nline2\nmatch\nline4"
        args = _make_args(before_context=2)
        result = p._search_content(content, "match", FILE_PATH, BASE_PATH, args)
        assert result is not None
        matches = result["matches"]
        # line1 (ctx) + line2 (ctx) + match (line 3)
        assert len(matches) == 3
        assert matches[0]["line_num"] == 1
        assert matches[0]["is_context"] is True
        assert matches[1]["line_num"] == 2
        assert matches[1]["is_context"] is True
        assert matches[2]["line_num"] == 3
        assert matches[2]["is_context"] is False

    def test_context_flag_applies_both_before_and_after(self) -> None:
        p = _parser()
        content = "a\nb\nmatch\nd\ne"
        args = _make_args(context=1)
        result = p._search_content(content, "match", FILE_PATH, BASE_PATH, args)
        assert result is not None
        matches = result["matches"]
        # b (ctx before) + match + d (ctx after)
        assert len(matches) == 3
        assert matches[0]["line"] == "b"
        assert matches[0]["is_context"] is True
        assert matches[1]["line"] == "match"
        assert matches[1]["is_context"] is False
        assert matches[2]["line"] == "d"
        assert matches[2]["is_context"] is True

    def test_separator_inserted_between_non_contiguous_groups(self) -> None:
        p = _parser()
        # 10 lines, match line2 and line9 with after_context=1 each
        lines = [f"line{i}" for i in range(1, 11)]
        content = "\n".join(lines)
        args = _make_args(after_context=1)
        result = p._search_content(content, "line2|line9", FILE_PATH, BASE_PATH, args)
        assert result is not None
        matches = result["matches"]
        sep_entries = [m for m in matches if m["line"] == "--" and m["line_num"] == 0]
        assert len(sep_entries) == 1

    def test_adjacent_groups_merged_no_separator(self) -> None:
        p = _parser()
        # match line2 and line3 — their after_context windows overlap, no separator
        content = "\n".join(f"L{i}" for i in range(1, 7))
        args = _make_args(after_context=1)
        result = p._search_content(content, "L2|L3", FILE_PATH, BASE_PATH, args)
        assert result is not None
        sep_entries = [m for m in result["matches"] if m["line"] == "--"]
        assert len(sep_entries) == 0

    def test_before_context_clamped_at_start_of_file(self) -> None:
        p = _parser()
        content = "match\nline2\nline3"
        args = _make_args(before_context=5)
        result = p._search_content(content, "match", FILE_PATH, BASE_PATH, args)
        assert result is not None
        # No context before line 1
        assert result["matches"][0]["line_num"] == 1

    def test_after_context_clamped_at_end_of_file(self) -> None:
        p = _parser()
        content = "line1\nline2\nmatch"
        args = _make_args(after_context=5)
        result = p._search_content(content, "match", FILE_PATH, BASE_PATH, args)
        assert result is not None
        # match is last line — no context after
        assert len(result["matches"]) == 1
        assert result["matches"][0]["line_num"] == 3

    def test_context_entries_not_counted_toward_match_limit(self) -> None:
        p = _parser()
        # Create a file where context lines fill up before match limit
        content = "\n".join(["ctx"] * 3 + ["match"] + ["ctx"] * 3)
        args = _make_args(before_context=3, after_context=3)
        result = p._search_content(content, "^match$", FILE_PATH, BASE_PATH, args)
        assert result is not None
        real_matches = [m for m in result["matches"] if not m.get("is_context")]
        assert len(real_matches) == 1


# ---------------------------------------------------------------------------
# _search_single_file — output formatting
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchSingleFile:
    def test_match_line_uses_colon_separator(self) -> None:
        p = _parser()
        content = "hello world"
        args = _make_args(line_number=True)
        result = p._search_single_file(content, "hello", FILE_PATH, BASE_PATH, args)
        assert "file.txt:1: hello world" in result

    def test_context_line_uses_dash_separator(self) -> None:
        p = _parser()
        content = "before\nmatch\nafter"
        args = _make_args(before_context=1, after_context=1, line_number=True)
        result = p._search_single_file(content, "match", FILE_PATH, BASE_PATH, args)
        assert "file.txt-1- before" in result
        assert "file.txt:2: match" in result
        assert "file.txt-3- after" in result

    def test_separator_line_renders_as_double_dash(self) -> None:
        p = _parser()
        lines = [f"L{i}" for i in range(1, 12)]
        content = "\n".join(lines)
        args = _make_args(after_context=1, line_number=True)
        result = p._search_single_file(content, "L1$|L10$", FILE_PATH, BASE_PATH, args)
        assert "\n--\n" in result

    def test_count_counts_only_real_matches(self) -> None:
        p = _parser()
        content = "before\nmatch\nafter"
        args = _make_args(before_context=1, count=True)
        result = p._search_single_file(content, "match", FILE_PATH, BASE_PATH, args)
        assert "1" in result
        assert "Total: 1 matches" in result

    def test_files_with_matches_returns_filename(self) -> None:
        p = _parser()
        content = "hello"
        args = _make_args(files_with_matches=True)
        result = p._search_single_file(content, "hello", FILE_PATH, BASE_PATH, args)
        assert result == "file.txt"

    def test_no_matches_returns_no_matches_message(self) -> None:
        p = _parser()
        result = p._search_single_file(
            "hello", "xyz", FILE_PATH, BASE_PATH, _make_args()
        )
        assert "no matches" in result

    def test_line_number_false_omits_line_num(self) -> None:
        p = _parser()
        content = "hello world"
        args = _make_args(line_number=False)
        result = p._search_single_file(content, "hello", FILE_PATH, BASE_PATH, args)
        # Should NOT contain ":1:" pattern
        assert ":1:" not in result
        assert "file.txt" in result


# ---------------------------------------------------------------------------
# _format_grep_output — multi-file formatting
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatGrepOutput:
    def _match(
        self, line: str, line_num: int = 1, is_context: bool = False
    ) -> dict[str, object]:
        return {"line_num": line_num, "line": line, "is_context": is_context}

    def test_no_results_returns_no_matches_message(self) -> None:
        p = _parser()
        result = p._format_grep_output([], [], "xyz", _make_args(), False)
        assert "no matches" in result

    def test_files_with_matches_returns_sorted_names(self) -> None:
        p = _parser()
        results = [
            {"path": "/u/b.txt", "name": "b.txt", "matches": [self._match("x")]},
            {"path": "/u/a.txt", "name": "a.txt", "matches": [self._match("x")]},
        ]
        args = _make_args(files_with_matches=True)
        output = p._format_grep_output(results, [], "x", args, False)
        lines = output.splitlines()
        assert lines == ["a.txt", "b.txt"]

    def test_count_counts_only_real_matches(self) -> None:
        p = _parser()
        results = [
            {
                "path": "/u/a.txt",
                "name": "a.txt",
                "matches": [
                    self._match("ctx", is_context=True),
                    self._match("real"),
                ],
            }
        ]
        args = _make_args(count=True)
        output = p._format_grep_output(results, [], "real", args, False)
        assert "a.txt: 1" in output
        assert "Total: 1" in output

    def test_multi_file_inserts_separator_between_files(self) -> None:
        p = _parser()
        results = [
            {"path": "/u/a.txt", "name": "a.txt", "matches": [self._match("match")]},
            {"path": "/u/b.txt", "name": "b.txt", "matches": [self._match("match")]},
        ]
        args = _make_args(line_number=True)
        output = p._format_grep_output(results, [], "match", args, False)
        assert "--" in output

    def test_gridfs_note_appended_when_has_gridfs(self) -> None:
        p = _parser()
        results = [
            {"path": "/u/a.txt", "name": "a.txt", "matches": [self._match("x")]},
        ]
        output = p._format_grep_output(results, [], "x", _make_args(), has_gridfs=True)
        assert "GridFS" in output

    def test_gridfs_results_merged_with_server_results(self) -> None:
        p = _parser()
        server = [{"path": "/u/a.txt", "name": "a.txt", "matches": [self._match("x")]}]
        gridfs = [{"path": "/u/b.txt", "name": "b.txt", "matches": [self._match("y")]}]
        args = _make_args(files_with_matches=True)
        output = p._format_grep_output(server, gridfs, "x", args, True)
        lines = output.splitlines()
        # Both files appear
        assert any("a.txt" in l for l in lines)
        assert any("b.txt" in l for l in lines)

    def test_context_line_uses_dash_separator_in_output(self) -> None:
        p = _parser()
        results = [
            {
                "path": "/u/f.txt",
                "name": "f.txt",
                "matches": [
                    self._match("before", line_num=4, is_context=True),
                    self._match("match", line_num=5),
                ],
            }
        ]
        args = _make_args(line_number=True)
        output = p._format_grep_output(results, [], "match", args, False)
        assert "f.txt-4- before" in output
        assert "f.txt:5: match" in output


# ---------------------------------------------------------------------------
# Parser flag integration (argparse correctness)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGrepParserFlags:
    def _grep_parser(self) -> argparse.ArgumentParser:
        return VFSCommandParser()._parsers["grep"]

    def test_invert_flag(self) -> None:
        args = self._grep_parser().parse_args(["hello", "-v"])
        assert args.invert_match is True

    def test_word_regexp_flag(self) -> None:
        args = self._grep_parser().parse_args(["hello", "-w"])
        assert args.word_regexp is True

    def test_only_matching_flag(self) -> None:
        args = self._grep_parser().parse_args(["hello", "-o"])
        assert args.only_matching is True

    def test_e_flag_appends_patterns(self) -> None:
        args = self._grep_parser().parse_args(["-e", "foo", "-e", "bar"])
        assert args.patterns == ["foo", "bar"]
        assert args.pattern is None

    def test_after_context_flag(self) -> None:
        args = self._grep_parser().parse_args(["hello", "-A", "3"])
        assert args.after_context == 3

    def test_before_context_flag(self) -> None:
        args = self._grep_parser().parse_args(["hello", "-B", "2"])
        assert args.before_context == 2

    def test_context_flag(self) -> None:
        args = self._grep_parser().parse_args(["hello", "-C", "5"])
        assert args.context == 5

    def test_include_flag_appends(self) -> None:
        args = self._grep_parser().parse_args(["hello", "--include=*.py"])
        assert args.include_globs == ["*.py"]

    def test_exclude_flag_appends(self) -> None:
        args = self._grep_parser().parse_args(["hello", "--exclude=*.pyc"])
        assert args.exclude_globs == ["*.pyc"]

    def test_multiple_include_flags(self) -> None:
        args = self._grep_parser().parse_args(
            ["hello", "--include=*.py", "--include=*.ts"]
        )
        assert args.include_globs == ["*.py", "*.ts"]

    def test_positional_pattern_is_optional(self) -> None:
        # Should not raise — pattern can be None when -e is used
        args = self._grep_parser().parse_args(["-e", "foo"])
        assert args.pattern is None
        assert args.patterns == ["foo"]

    def test_all_legacy_flags_still_work(self) -> None:
        args = self._grep_parser().parse_args(["hello", "-i", "-r", "-c", "-l"])
        assert args.ignore_case is True
        assert args.recursive is True
        assert args.count is True
        assert args.files_with_matches is True
