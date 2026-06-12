"""Unit tests for the builtin SKILL.md loader.

Exercises the real parsing/loading logic against on-disk temp skill dirs (the
private helpers hold the behavior; load_builtin_skills is just an lru_cached walk
over the real builtin dir).
"""

from pathlib import Path

import pytest

from app.agents.workspace import skill_loader as sl


@pytest.mark.unit
class TestParseFrontmatter:
    def test_parses_scalar_keys_and_strips_quotes(self) -> None:
        raw = (
            '---\nname: "Create PDF"\ntarget: executor\n'
            "description: 'Make a PDF'\n---\nBody line 1\nBody line 2\n"
        )
        meta, body = sl._parse_frontmatter(raw)
        assert meta == {
            "name": "Create PDF",
            "target": "executor",
            "description": "Make a PDF",
        }
        assert body == "Body line 1\nBody line 2\n"

    def test_no_frontmatter_returns_empty_meta_and_full_raw(self) -> None:
        raw = "# Just a heading\nno frontmatter here\n"
        meta, body = sl._parse_frontmatter(raw)
        assert meta == {}
        assert body == raw

    def test_skips_comments_and_blank_lines(self) -> None:
        raw = "---\n# a comment\nname: x\n\ntarget: y\n---\nbody"
        meta, _ = sl._parse_frontmatter(raw)
        assert meta == {"name": "x", "target": "y"}


@pytest.mark.unit
class TestTargetToSubagent:
    @pytest.mark.parametrize(
        "target,expected",
        [
            ("executor", "executor"),  # special alias
            ("gmail_agent", "gmail"),  # <provider>_agent → provider
            ("docgen_agent", "docgen"),
            ("googlecalendar_agent", "googlecalendar"),
            ("weird", "weird"),  # no _agent suffix, not aliased → passthrough
        ],
    )
    def test_maps_target_to_subagent_id(self, target: str, expected: str) -> None:
        assert sl._target_to_subagent(target) == expected


@pytest.mark.unit
class TestLoadResources:
    def test_collects_text_siblings_and_excludes_skill_md(self, tmp_path: Path) -> None:
        (tmp_path / "SKILL.md").write_text("---\nname: x\n---\nbody", encoding="utf-8")
        (tmp_path / "reference.md").write_text("ref", encoding="utf-8")
        (tmp_path / "templates").mkdir()
        (tmp_path / "templates" / "report.typ").write_text("typ", encoding="utf-8")

        res = dict(sl._load_resources(tmp_path))

        assert res == {"reference.md": "ref", "templates/report.typ": "typ"}
        assert "SKILL.md" not in res  # the body is captured separately

    def test_skips_pycache_dotfiles_and_binaries(self, tmp_path: Path) -> None:
        (tmp_path / "reference.md").write_text("ref", encoding="utf-8")
        # __pycache__ can hold TEXT artifacts (logs, etc.): the guard must skip
        # them by location, not lean on the binary-skip fallback.
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "report.cpython-312.pyc").write_bytes(b"\x00\x01binary")
        (cache / "build.log").write_text("a cached text artifact", encoding="utf-8")
        # Dotfiles are project junk, not skill resources (text content here so a
        # missing guard would otherwise pull them in).
        (tmp_path / ".env.local").write_text("SECRET=value", encoding="utf-8")
        # A genuine binary sibling is skipped via the UnicodeDecodeError path.
        (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01")

        res = dict(sl._load_resources(tmp_path))

        assert res == {"reference.md": "ref"}  # only the real text sibling

    def test_paths_are_posix_relative_to_the_skill_dir(self, tmp_path: Path) -> None:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "build.sh").write_text("#!/bin/sh\n", encoding="utf-8")

        rels = [rel for rel, _ in sl._load_resources(tmp_path)]

        assert rels == ["scripts/build.sh"]


@pytest.mark.unit
class TestLoadOne:
    def test_returns_none_without_skill_md(self, tmp_path: Path) -> None:
        (tmp_path / "reference.md").write_text("ref", encoding="utf-8")
        assert sl._load_one(tmp_path) is None

    def test_parses_fields_subagent_id_and_resources(self, tmp_path: Path) -> None:
        (tmp_path / "SKILL.md").write_text(
            "---\nname: Create PDF\ntarget: docgen_agent\ndescription: desc\n---\nThe body.",
            encoding="utf-8",
        )
        (tmp_path / "reference.md").write_text("ref", encoding="utf-8")

        skill = sl._load_one(tmp_path)

        assert skill is not None
        assert skill.slug == tmp_path.name
        assert skill.name == "Create PDF"
        assert skill.target == "docgen_agent"
        assert skill.subagent_id == "docgen"  # _agent suffix stripped
        assert skill.body == "The body."
        assert ("reference.md", "ref") in skill.resources

    def test_name_falls_back_to_slug_and_target_defaults_to_executor(self, tmp_path: Path) -> None:
        (tmp_path / "SKILL.md").write_text("no frontmatter, just body", encoding="utf-8")

        skill = sl._load_one(tmp_path)

        assert skill is not None
        assert skill.name == tmp_path.name  # falls back to dir name
        assert skill.target == "executor"
        assert skill.subagent_id == "executor"
