"""
Unit tests for MongoVFS.grep_content — server-side grep with all new flags.

MongoDB is mocked at the collection level so no live DB is required.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.vfs.mongo_vfs import MongoVFS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = "u1"
BASE_PATH = f"/users/{USER_ID}/docs"


def _make_collection_mock(docs: list[dict[str, Any]]) -> MagicMock:
    """Mock vfs_nodes_collection.find(...).limit(...) → to_list → docs."""
    limited_cursor = AsyncMock()
    limited_cursor.to_list = AsyncMock(return_value=docs)

    find_cursor = MagicMock()
    find_cursor.limit = MagicMock(return_value=limited_cursor)

    col = MagicMock()
    col.find = MagicMock(return_value=find_cursor)
    return col


def _doc(name: str, content: str) -> dict[str, Any]:
    return {
        "path": f"{BASE_PATH}/{name}",
        "name": name,
        "content": content,
    }


def _vfs() -> MongoVFS:
    return MongoVFS()


# ---------------------------------------------------------------------------
# Basic functionality (regression tests against pre-existing behavior)
# ---------------------------------------------------------------------------


class TestGrepContentBasic:
    async def test_returns_files_with_matching_lines(self) -> None:
        docs = [_doc("a.txt", "hello world\nno match here")]
        col = _make_collection_mock(docs)
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                "hello", user_id=USER_ID, base_path=BASE_PATH
            )
        assert len(results) == 1
        assert results[0]["name"] == "a.txt"
        assert len(results[0]["matches"]) == 1
        assert results[0]["matches"][0]["line_num"] == 1

    async def test_returns_empty_when_no_docs_match(self) -> None:
        col = _make_collection_mock([])
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                "xyz", user_id=USER_ID, base_path=BASE_PATH
            )
        assert results == []

    async def test_relative_name_computed_from_base_path(self) -> None:
        docs = [_doc("report.md", "summary here")]
        col = _make_collection_mock(docs)
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                "summary", user_id=USER_ID, base_path=BASE_PATH
            )
        assert results[0]["name"] == "report.md"

    async def test_match_entry_has_is_context_false(self) -> None:
        docs = [_doc("f.txt", "match line")]
        col = _make_collection_mock(docs)
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                "match", user_id=USER_ID, base_path=BASE_PATH
            )
        assert results[0]["matches"][0]["is_context"] is False


# ---------------------------------------------------------------------------
# include_globs / exclude_globs — query structure
# ---------------------------------------------------------------------------


class TestGrepContentGlobFilters:
    async def test_include_globs_adds_name_regex_to_query(self) -> None:
        col = _make_collection_mock([])
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            await _vfs().grep_content(
                "hello",
                user_id=USER_ID,
                base_path=BASE_PATH,
                include_globs=["*.py"],
            )
        query_arg = col.find.call_args[0][0]
        assert "name" in query_arg
        assert "$regex" in query_arg["name"]

    async def test_exclude_globs_adds_not_to_name_query(self) -> None:
        col = _make_collection_mock([])
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            await _vfs().grep_content(
                "hello",
                user_id=USER_ID,
                base_path=BASE_PATH,
                exclude_globs=["*.pyc"],
            )
        query_arg = col.find.call_args[0][0]
        assert "name" in query_arg
        assert "$not" in query_arg["name"]

    async def test_include_and_exclude_both_set(self) -> None:
        col = _make_collection_mock([])
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            await _vfs().grep_content(
                "hello",
                user_id=USER_ID,
                base_path=BASE_PATH,
                include_globs=["*.py"],
                exclude_globs=["test_*"],
            )
        query_arg = col.find.call_args[0][0]
        assert "name" in query_arg
        assert "$regex" in query_arg["name"]
        assert "$not" in query_arg["name"]

    async def test_no_globs_no_name_key_in_query(self) -> None:
        col = _make_collection_mock([])
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            await _vfs().grep_content("hello", user_id=USER_ID, base_path=BASE_PATH)
        query_arg = col.find.call_args[0][0]
        assert "name" not in query_arg


# ---------------------------------------------------------------------------
# invert=True
# ---------------------------------------------------------------------------


class TestGrepContentInvert:
    async def test_invert_returns_non_matching_lines(self) -> None:
        docs = [_doc("f.txt", "hello world\nfoo bar\nbaz")]
        col = _make_collection_mock(docs)
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                "hello",
                user_id=USER_ID,
                base_path=BASE_PATH,
                invert=True,
            )
        assert len(results) == 1
        match_lines = [m["line"] for m in results[0]["matches"]]
        assert "foo bar" in match_lines
        assert "baz" in match_lines
        assert "hello world" not in match_lines

    async def test_invert_all_lines_match_returns_empty(self) -> None:
        docs = [_doc("f.txt", "hello\nhello again")]
        col = _make_collection_mock(docs)
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                "hello",
                user_id=USER_ID,
                base_path=BASE_PATH,
                invert=True,
            )
        # All lines in the file matched the pattern → no non-matching lines → file excluded
        assert results == []

    async def test_invert_entries_are_not_context(self) -> None:
        docs = [_doc("f.txt", "a\nb\nc")]
        col = _make_collection_mock(docs)
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                "b",
                user_id=USER_ID,
                base_path=BASE_PATH,
                invert=True,
            )
        assert len(results) == 1
        lines = [m["line"] for m in results[0]["matches"]]
        assert "a" in lines  # non-matching lines returned
        assert "c" in lines
        assert "b" not in lines  # matching line excluded
        assert all(m["is_context"] is False for m in results[0]["matches"])


# ---------------------------------------------------------------------------
# only_matching=True
# ---------------------------------------------------------------------------


class TestGrepContentOnlyMatching:
    async def test_only_matching_returns_matched_portion(self) -> None:
        docs = [_doc("f.txt", "the cat sat on the mat")]
        col = _make_collection_mock(docs)
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                r"c\w+",
                user_id=USER_ID,
                base_path=BASE_PATH,
                only_matching=True,
            )
        assert len(results) == 1
        match_lines = [m["line"] for m in results[0]["matches"]]
        assert "cat" in match_lines
        assert "the cat sat on the mat" not in match_lines

    async def test_only_matching_multiple_per_line_creates_multiple_entries(self) -> None:
        docs = [_doc("f.txt", "cat bat hat")]
        col = _make_collection_mock(docs)
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                r"\w+at",
                user_id=USER_ID,
                base_path=BASE_PATH,
                only_matching=True,
            )
        assert len(results) == 1
        match_lines = [m["line"] for m in results[0]["matches"]]
        assert "cat" in match_lines
        assert "bat" in match_lines
        assert "hat" in match_lines

    async def test_only_matching_false_returns_full_line(self) -> None:
        docs = [_doc("f.txt", "hello world")]
        col = _make_collection_mock(docs)
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                "hello",
                user_id=USER_ID,
                base_path=BASE_PATH,
                only_matching=False,
            )
        assert results[0]["matches"][0]["line"] == "hello world"


# ---------------------------------------------------------------------------
# Context lines (before_context / after_context)
# ---------------------------------------------------------------------------


class TestGrepContentContextLines:
    async def test_after_context_includes_lines_after_match(self) -> None:
        docs = [_doc("f.txt", "line1\nline2\nmatch\nline4\nline5")]
        col = _make_collection_mock(docs)
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                "match",
                user_id=USER_ID,
                base_path=BASE_PATH,
                after_context=2,
            )
        assert len(results) == 1
        matches = results[0]["matches"]
        # match (line3) + line4 (ctx) + line5 (ctx)
        assert len(matches) == 3
        assert matches[0]["is_context"] is False
        assert matches[0]["line_num"] == 3
        assert matches[1]["is_context"] is True
        assert matches[1]["line_num"] == 4
        assert matches[2]["is_context"] is True
        assert matches[2]["line_num"] == 5

    async def test_before_context_includes_lines_before_match(self) -> None:
        docs = [_doc("f.txt", "line1\nline2\nmatch\nline4")]
        col = _make_collection_mock(docs)
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                "match",
                user_id=USER_ID,
                base_path=BASE_PATH,
                before_context=2,
            )
        assert len(results) == 1
        matches = results[0]["matches"]
        # line1 (ctx) + line2 (ctx) + match
        assert len(matches) == 3
        assert matches[0]["is_context"] is True
        assert matches[0]["line_num"] == 1
        assert matches[2]["is_context"] is False
        assert matches[2]["line_num"] == 3

    async def test_separator_inserted_between_non_contiguous_groups(self) -> None:
        lines = [f"L{i}" for i in range(1, 12)]
        docs = [_doc("f.txt", "\n".join(lines))]
        col = _make_collection_mock(docs)
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                "L2$|L10$",
                user_id=USER_ID,
                base_path=BASE_PATH,
                after_context=1,
            )
        assert len(results) == 1
        matches = results[0]["matches"]
        sep_entries = [m for m in matches if m["line"] == "--" and m["line_num"] == 0]
        assert len(sep_entries) == 1

    async def test_no_context_no_separator(self) -> None:
        docs = [_doc("f.txt", "match1\nno\nmatch2")]
        col = _make_collection_mock(docs)
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                "match",
                user_id=USER_ID,
                base_path=BASE_PATH,
                after_context=0,
                before_context=0,
            )
        assert len(results) == 1
        sep_entries = [m for m in results[0]["matches"] if m["line"] == "--"]
        assert len(sep_entries) == 0

    async def test_context_disabled_when_invert(self) -> None:
        """Context lines should NOT be returned when invert=True."""
        docs = [_doc("f.txt", "before\nno_match\nafter")]
        col = _make_collection_mock(docs)
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
            results = await _vfs().grep_content(
                "no_match",
                user_id=USER_ID,
                base_path=BASE_PATH,
                invert=True,
                before_context=1,
                after_context=1,
            )
        assert len(results) == 1
        # Only "before" and "after" (non-matching), no context entries
        assert all(m["is_context"] is False for m in results[0]["matches"])
