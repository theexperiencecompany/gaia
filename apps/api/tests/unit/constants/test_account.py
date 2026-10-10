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
    account_mutation_refusal,
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


# ---------------------------------------------------------------------------
# write/edit refusal mapping — every account path must name the right tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("rel_path", "expected_tool"),
    [
        ("account/notifications.json", "update_notification_settings"),
        ("account/preferences.json", "update_preferences"),
        ("account/custom-instructions.json", "update_custom_instructions"),
        ("account/voices/selected.json", "set_selected_voice"),
        ("account/voices/catalog.json", "set_selected_voice"),
        ("account/linked-accounts/telegram.json", "manage_linked_account"),
    ],
)
def test_refusal_points_at_the_mutation_tool_that_owns_the_change(
    rel_path: str, expected_tool: str
) -> None:
    refusal = account_mutation_refusal(rel_path)
    assert refusal is not None
    assert "read-only" in refusal
    assert expected_tool in refusal


@pytest.mark.unit
@pytest.mark.parametrize("rel_path", ["account/subscription.json", "account/usage.json"])
def test_billing_truth_names_no_tool_because_none_exists(rel_path: str) -> None:
    # Exact text: this refusal is shown to the user verbatim, so the wording
    # is part of the contract — no tool to point at, the sentence stands alone.
    assert account_mutation_refusal(rel_path) == (
        f"Error: {rel_path} is a read-only projection of the user's account "
        "and cannot be modified by editing it."
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "rel_path",
    ["account/GUIDE.md", "account/guides/usage.md", "account/some-unknown-file.txt"],
)
def test_every_other_path_under_account_is_refused_too(rel_path: str) -> None:
    refusal = account_mutation_refusal(rel_path)
    assert refusal is not None
    assert rel_path in refusal


@pytest.mark.unit
@pytest.mark.parametrize(
    "rel_path",
    ["scratch/notes.json", "todos/meta.json", "memory/core.md"],
)
def test_non_account_paths_are_never_refused(rel_path: str) -> None:
    assert account_mutation_refusal(rel_path) is None


@pytest.mark.unit
def test_unknown_subtree_files_still_map_to_their_area_for_the_refusal() -> None:
    # A future voices/linked-accounts file not yet in the data registry must
    # still refuse with the right tool, not fall through to the generic text.
    refusal = account_mutation_refusal("account/voices/new-projection.json")
    assert "set_selected_voice" in refusal
    refusal = account_mutation_refusal("account/linked-accounts/future.json")
    assert "manage_linked_account" in refusal
