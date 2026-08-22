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

import pytest

from app.constants.account import ACCOUNT_DIR, ACCOUNT_READ_ONLY_PATHS
from app.services.storage.account_vfs import AccountFileProjection, materialize_account_files


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
