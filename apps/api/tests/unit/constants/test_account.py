"""Account-center path registry: the map every consumer reads.

The registry is the contract between the materializer, the write/edit refusal,
and the guides — a path that drifts from it lands in the wrong place or gets
refused wrongly, so the mapping itself is what's under test.
"""

import pytest

from app.constants.account import (
    ACCOUNT_DIR,
    ACCOUNT_READ_ONLY_PATHS,
    AccountArea,
    account_area_for,
)


@pytest.mark.unit
def test_every_declared_read_only_path_maps_to_an_area() -> None:
    for rel_path in ACCOUNT_READ_ONLY_PATHS:
        assert account_area_for(rel_path) is not None, rel_path


@pytest.mark.unit
def test_areas_cover_all_seven_account_groups() -> None:
    areas = {account_area_for(p) for p in ACCOUNT_READ_ONLY_PATHS}
    assert areas == set(AccountArea)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("rel_path", "expected"),
    [
        (f"{ACCOUNT_DIR}/subscription.json", AccountArea.SUBSCRIPTION),
        (f"{ACCOUNT_DIR}/usage.json", AccountArea.USAGE),
        (f"{ACCOUNT_DIR}/notifications.json", AccountArea.NOTIFICATIONS),
        (f"{ACCOUNT_DIR}/preferences.json", AccountArea.PREFERENCES),
        (f"{ACCOUNT_DIR}/custom-instructions.json", AccountArea.CUSTOM_INSTRUCTIONS),
        (f"{ACCOUNT_DIR}/voices/catalog.json", AccountArea.VOICE),
        (f"{ACCOUNT_DIR}/voices/selected.json", AccountArea.VOICE),
        (
            f"{ACCOUNT_DIR}/linked-accounts/telegram.json",
            AccountArea.LINKED_ACCOUNTS,
        ),
    ],
)
def test_known_paths_map_to_their_area(rel_path: str, expected: AccountArea) -> None:
    assert account_area_for(rel_path) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "rel_path",
    [
        "account/GUIDE.md",
        "account/guides/usage.md",
        "todos/meta.json",
        "../../etc/passwd",
        "",
    ],
)
def test_non_data_paths_do_not_map(rel_path: str) -> None:
    assert account_area_for(rel_path) is None


@pytest.mark.unit
def test_one_platform_file_exists_per_supported_platform() -> None:
    platforms = {
        p.split("/")[-1].removesuffix(".json")
        for p in ACCOUNT_READ_ONLY_PATHS
        if "linked-accounts" in p
    }
    assert platforms == {"telegram", "whatsapp", "discord", "slack", "imessage"}
