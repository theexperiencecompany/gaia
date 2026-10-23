"""Workspace upload naming: collision-free, sanitized, bounded."""

import pytest

from app.services.files.naming import workspace_upload_name


def test_prefixes_the_file_id_so_distinct_files_cannot_collide() -> None:
    assert workspace_upload_name("f-1", "image.png") == "f-1_image.png"


def test_sanitizes_the_display_name() -> None:
    assert workspace_upload_name("f-1", "my screenshot (1).png") == "f-1_my_screenshot__1_.png"


def test_caps_the_component_at_the_filesystem_limit() -> None:
    name = workspace_upload_name("f-1", "a" * 400 + ".png")

    assert name.startswith("f-1_")
    assert len(name.encode()) == 255


def test_rejects_a_name_that_sanitizes_away() -> None:
    with pytest.raises(ValueError):
        workspace_upload_name("f-1", "...")
