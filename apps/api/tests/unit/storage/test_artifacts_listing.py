"""Layer 2 — artifact listing: the os.scandir walk + stat_artifact.

`_list_files` is pure (takes a Path) so it runs against a real tmpdir — this is
filesystem logic, the filesystem is the boundary, not something to mock. The
stat_artifact tests patch the JuiceFS mount root to a tmpdir, including a
SYMLINKED root to lock in the resolve-anchor fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.storage.sessions.artifacts import _list_files, list_artifacts, stat_artifact

pytestmark = pytest.mark.unit


def _write(base: Path, rel: str, data: str = "x") -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data)


# ---- _list_files (pure, real tmpdir) ---------------------------------------


def test_lists_files_recursively_with_relative_paths(tmp_path: Path) -> None:
    _write(tmp_path, "top.txt", "ab")
    _write(tmp_path, "a/deep.md", "xyz")
    _write(tmp_path, "a/b/nested.json", "{}")

    out = _list_files(tmp_path)
    by_path = {i.path: i for i in out}
    assert set(by_path) == {"top.txt", "a/deep.md", "a/b/nested.json"}
    assert by_path["top.txt"].size_bytes == 2
    assert by_path["a/deep.md"].content_type == "text/markdown"


def test_output_is_sorted_by_path(tmp_path: Path) -> None:
    for rel in ["z.txt", "a.txt", "m/n.txt"]:
        _write(tmp_path, rel)
    paths = [i.path for i in _list_files(tmp_path)]
    assert paths == sorted(paths)


def test_symlinks_are_skipped_not_followed(tmp_path: Path) -> None:
    _write(tmp_path, "real.txt", "ok")
    (tmp_path / "evil_file.lnk").symlink_to("/etc/passwd")
    (tmp_path / "evil_dir").symlink_to("/etc", target_is_directory=True)  # must NOT be walked into

    paths = {i.path for i in _list_files(tmp_path)}
    assert paths == {"real.txt"}, f"symlinks leaked into the listing: {paths}"


def test_missing_base_returns_empty(tmp_path: Path) -> None:
    assert _list_files(tmp_path / "does-not-exist") == []


def test_empty_dir_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    assert _list_files(tmp_path / "empty") == []


# ---- stat_artifact / list_artifacts (patched mount root) -------------------


@pytest.fixture
def mount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "jfs"
    root.mkdir()
    monkeypatch.setattr("app.services.storage.juicefs._mount_root", lambda: root)
    return root


def _artifacts_dir(mount: Path, user: str, conv: str) -> Path:
    d = mount / "users" / user / "sessions" / conv / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def test_list_artifacts_reads_session_tree(mount: Path) -> None:
    adir = _artifacts_dir(mount, "u1", "c1")
    (adir / "out.md").write_text("hello")
    (adir / "sub").mkdir()
    (adir / "sub" / "x.json").write_text("{}")

    out = await list_artifacts("u1", "c1")
    assert {i.path for i in out} == {"out.md", "sub/x.json"}


async def test_stat_artifact_returns_info_for_regular_file(mount: Path) -> None:
    adir = _artifacts_dir(mount, "u1", "c1")
    (adir / "r.md").write_text("hello")
    info = await stat_artifact("u1", "c1", "r.md")
    assert info is not None
    assert info.path == "r.md"
    assert info.size_bytes == 5
    assert info.content_type == "text/markdown"


async def test_stat_artifact_returns_none_for_missing(mount: Path) -> None:
    _artifacts_dir(mount, "u1", "c1")
    assert await stat_artifact("u1", "c1", "nope.md") is None


async def test_stat_artifact_returns_none_for_directory(mount: Path) -> None:
    adir = _artifacts_dir(mount, "u1", "c1")
    (adir / "adir").mkdir()
    assert await stat_artifact("u1", "c1", "adir") is None


async def test_stat_artifact_path_is_clean_when_mount_root_is_symlinked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression for the resolve-asymmetry: _contained resolves `target`
    # (follows the symlinked root), so the returned path must be anchored on the
    # RESOLVED base — else os.path.relpath emits a '../'-laden path that breaks
    # the artifact-event key vs the watcher's live events.
    real = tmp_path / "real_mount"
    real.mkdir()
    link = tmp_path / "link_mount"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr("app.services.storage.juicefs._mount_root", lambda: link)

    adir = real / "users" / "u1" / "sessions" / "c1" / "artifacts"
    adir.mkdir(parents=True)
    (adir / "report.md").write_text("hi")

    info = await stat_artifact("u1", "c1", "report.md")
    assert info is not None
    assert info.path == "report.md", (
        f"expected clean relative path, got {info.path!r} — relpath anchored on "
        f"the unresolved (symlinked) base"
    )
