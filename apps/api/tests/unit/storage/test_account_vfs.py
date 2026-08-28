"""Account-center VFS materializer: projection, hash-gating, self-healing.

Mongo is the truth; the JSON files under ``account/`` are views. What's under
test here is the on-disk contract — bodies land where the registry says, are
read-only, aren't rewritten when unchanged, and a tampered file (bash `rm`/
`echo`) heals back to the projected content on the next pass.

``tmp_path`` is the real mount root — paths, mode bits and rewrites are
genuine; nothing is mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.constants.account import ACCOUNT_DIR, ACCOUNT_READ_ONLY_PATHS
from app.services.storage.account_vfs import (
    AccountFileProjection,
    _prune_stale_json,
    materialize_account_files,
)


def projection(rel_path: str, payload: dict[str, object]) -> AccountFileProjection:
    """A projection exactly as ``build_account_projections`` emits it."""
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return {"id": rel_path, "path": rel_path, "body": body}


@pytest.mark.unit
def test_every_registered_path_lands_on_disk_with_valid_json(tmp_path: Path) -> None:
    files = [
        projection(
            p,
            {"platform": p.split("/")[-1].removesuffix(".json")}
            if "linked-accounts" in p
            else {"path": p},
        )
        for p in sorted(ACCOUNT_READ_ONLY_PATHS)
    ]
    assert materialize_account_files(tmp_path, files) == len(files)

    for f in files:
        target = tmp_path / f["path"]
        assert target.is_file(), f["path"]
        json.loads(target.read_text())


@pytest.mark.unit
def test_projected_bodies_are_read_only_so_a_raw_edit_cannot_desync(tmp_path: Path) -> None:
    files = [projection(f"{ACCOUNT_DIR}/notifications.json", {})]
    materialize_account_files(tmp_path, files)

    assert (tmp_path / ACCOUNT_DIR / "notifications.json").stat().st_mode & 0o777 == 0o444


@pytest.mark.unit
def test_unchanged_bodies_are_not_rewritten(tmp_path: Path) -> None:
    files = [projection(f"{ACCOUNT_DIR}/preferences.json", {"response_style": "brief"})]
    assert materialize_account_files(tmp_path, files) == 1

    # Same bodies again → zero writes.
    assert materialize_account_files(tmp_path, files) == 0


@pytest.mark.unit
def test_an_unchanged_file_does_not_stop_later_files_from_being_written(
    tmp_path: Path,
) -> None:
    first = projection(f"{ACCOUNT_DIR}/preferences.json", {"response_style": "brief"})
    materialize_account_files(tmp_path, [first])

    second = projection(f"{ACCOUNT_DIR}/usage.json", {"plan_type": "free"})
    assert materialize_account_files(tmp_path, [first, second]) == 1
    assert '"free"' in (tmp_path / ACCOUNT_DIR / "usage.json").read_text()


@pytest.mark.unit
def test_changed_body_is_rewritten(tmp_path: Path) -> None:
    first = [projection(f"{ACCOUNT_DIR}/preferences.json", {"response_style": "brief"})]
    materialize_account_files(tmp_path, first)

    second = [projection(f"{ACCOUNT_DIR}/preferences.json", {"response_style": "detailed"})]
    assert materialize_account_files(tmp_path, second) == 1
    assert '"detailed"' in (tmp_path / ACCOUNT_DIR / "preferences.json").read_text()


@pytest.mark.unit
def test_tampered_file_heals_to_projected_content(tmp_path: Path) -> None:
    files = [projection(f"{ACCOUNT_DIR}/usage.json", {"plan_type": "free"})]
    materialize_account_files(tmp_path, files)

    # bash tamper: rm the projection
    (tmp_path / ACCOUNT_DIR / "usage.json").unlink()

    assert materialize_account_files(tmp_path, files) == 1
    assert (tmp_path / ACCOUNT_DIR / "usage.json").is_file()


@pytest.mark.unit
def test_tampered_file_content_heals_even_when_left_in_place(tmp_path: Path) -> None:
    files = [projection(f"{ACCOUNT_DIR}/usage.json", {"plan_type": "free"})]
    materialize_account_files(tmp_path, files)

    # bash tamper: echo over the projection
    target = tmp_path / ACCOUNT_DIR / "usage.json"
    target.chmod(0o644)
    target.write_text("garbage")

    assert materialize_account_files(tmp_path, files) == 1
    assert '"free"' in target.read_text()


@pytest.mark.unit
def test_stale_projection_leaving_the_manifest_is_pruned(tmp_path: Path) -> None:
    stale = projection(f"{ACCOUNT_DIR}/old-view.json", {})
    materialize_account_files(tmp_path, [stale])
    assert (tmp_path / ACCOUNT_DIR / "old-view.json").is_file()

    assert materialize_account_files(tmp_path, []) == 0
    assert not (tmp_path / ACCOUNT_DIR / "old-view.json").exists()


@pytest.mark.unit
def test_a_kept_file_does_not_stop_the_prune_from_reaching_later_stale_ones(
    tmp_path: Path,
) -> None:
    """The prune SKIPS files it keeps; it must not STOP at them.

    Every existing prune test has one file in the tree, so a loop that gave up
    on its first keeper would still pass them all. With a kept file sorting
    before a stale one, abandoning the walk leaves the stale view on disk
    forever — the exact bug this pass exists to prevent.
    """
    kept_rel = f"{ACCOUNT_DIR}/aaa-kept.json"
    preserved_rel = f"{ACCOUNT_DIR}/bbb-preserved.json"
    stale_rel = f"{ACCOUNT_DIR}/zzz-stale.json"
    materialize_account_files(
        tmp_path,
        [projection(kept_rel, {}), projection(preserved_rel, {}), projection(stale_rel, {})],
    )

    _prune_stale_json(tmp_path / ACCOUNT_DIR, {kept_rel}, {preserved_rel})

    assert (tmp_path / kept_rel).is_file()
    assert (tmp_path / preserved_rel).is_file()
    assert not (tmp_path / stale_rel).exists()


@pytest.mark.unit
def test_stale_read_only_projections_are_made_writable_before_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Projections are written 0444; the prune pass must chmod back to a
    # writable mode before unlinking (required on platforms that refuse to
    # delete read-only files), then remove the stale view.
    stale_rel = f"{ACCOUNT_DIR}/old-view.json"
    materialize_account_files(tmp_path, [projection(stale_rel, {})])

    chmod_calls: list[tuple[Path, int]] = []
    real_chmod = Path.chmod

    def recording_chmod(self: Path, mode: int) -> None:
        chmod_calls.append((self, mode))
        real_chmod(self, mode)

    monkeypatch.setattr(Path, "chmod", recording_chmod)
    _prune_stale_json(tmp_path / ACCOUNT_DIR, set(), set())

    assert chmod_calls == [(tmp_path / stale_rel, 0o644)]
    assert not (tmp_path / stale_rel).exists()


@pytest.mark.unit
def test_prune_tolerates_a_projection_that_vanishes_after_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A concurrent writer can delete a listed projection between the rglob
    # listing and the unlink — the prune must treat the file as gone, not
    # raise FileNotFoundError out of the sync.
    account_root = tmp_path / ACCOUNT_DIR
    account_root.mkdir()
    ghost = account_root / "ghost.json"
    real_rglob = Path.rglob

    def rglob_with_ghost(root: Path, pattern: str) -> Any:
        if root == account_root:
            return iter([ghost])
        return real_rglob(root, pattern)

    monkeypatch.setattr(Path, "rglob", rglob_with_ghost)
    monkeypatch.setattr(Path, "chmod", lambda self, mode: None)

    _prune_stale_json(account_root, set(), set())


@pytest.mark.unit
def test_markdown_guides_are_never_pruned_by_the_data_pass(tmp_path: Path) -> None:
    guide = tmp_path / ACCOUNT_DIR / "GUIDE.md"
    guide.parent.mkdir(parents=True)
    guide.write_text("# account")

    materialize_account_files(tmp_path, [])

    assert guide.read_text() == "# account"


@pytest.mark.unit
def test_nested_directories_are_created_for_subtree_projections(tmp_path: Path) -> None:
    files = [projection(f"{ACCOUNT_DIR}/voices/selected.json", {"voice_id": None})]
    materialize_account_files(tmp_path, files)

    assert (tmp_path / ACCOUNT_DIR / "voices" / "selected.json").is_file()
