"""Unit tests for the account-center workspace sync glue.

Every source (payment provider, Redis-backed usage, Mongo user, ElevenLabs
catalog, platform links, JuiceFS) is mocked at its seam; the logic under test
is the projection assembly, the per-group failure isolation, and the
changed-body-only materialization contract.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.account import ACCOUNT_DIR
from app.models.payment_models import PlanType
from app.schemas.usage import UsageBudget
from app.services import account_fs
from app.services.platform_link_service import Platform

MODULE = "app.services.account_fs"
USER_ID = "user-1"

_BUDGET = UsageBudget.model_validate(
    {
        "daily": {"percentage": 0.0, "reset_time": "2026-01-02T00:00:00+00:00"},
        "monthly": None,
        "per_request_token_ceiling": 300_000,
    }
)


def _voice(voice_id: str = "v-1", name: str = "Rachel", starred: bool = False):
    return SimpleNamespace(voice_id=voice_id, name=name, starred=starred)


@pytest.fixture
def sources():
    """Patch every account source with a working default; tests override one."""
    catalog = SimpleNamespace(voices=[_voice()], selected_voice_id="v-1")
    linked = {"telegram": {"connectedAt": "2026-01-01", "username": "dh", "displayName": "Dh"}}
    with (
        patch(
            f"{MODULE}.payment_service.get_user_subscription_status",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    plan_type=PlanType.PRO,
                    current_plan={
                        "name": "Pro",
                        "amount": 15,
                        "currency": "$",
                        "duration": "month",
                    },
                    subscription={"status": "active"},
                )
            ),
        ),
        patch(
            f"{MODULE}.build_usage_summary",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    plan_type="pro",
                    budget=_BUDGET,
                    features={},
                )
            ),
        ),
        patch(f"{MODULE}.fetch_channel_preferences", new=AsyncMock(return_value={"email": True})),
        patch(
            f"{MODULE}.user_repository",
            get=AsyncMock(
                return_value=SimpleNamespace(
                    timezone="UTC",
                    onboarding={"preferences": {"response_style": "brief"}},
                )
            ),
        ),
        patch(f"{MODULE}.list_voices", new=AsyncMock(return_value=catalog)),
        patch(
            f"{MODULE}.PlatformLinkService.get_linked_platforms",
            new=AsyncMock(return_value=linked),
        ),
    ):
        yield


async def _build(user_id: str = USER_ID) -> tuple[list[dict], set[str]]:
    return await account_fs.build_account_projections(user_id)


def _ids(files: list[dict]) -> set[str]:
    return {f["id"] for f in files}


@pytest.mark.unit
class TestBuildAccountProjections:
    async def test_one_file_per_group_plus_every_linked_platform(self, sources) -> None:
        files, failed = await _build()

        assert not failed

        expected_groups = {
            "subscription",
            "usage",
            "notifications",
            "preferences",
            "custom-instructions",
            "voices/catalog",
            "voices/selected",
        }
        assert expected_groups <= _ids(files)
        assert _ids(files) & {f"linked-{p.value}" for p in Platform} == {
            f"linked-{p.value}" for p in Platform
        }
        for file in files:
            assert file["path"].startswith(f"{ACCOUNT_DIR}/")
            assert file["body"].endswith("\n")

    async def test_subscription_projection_carries_plan_shape(self, sources) -> None:
        files, _ = await _build()
        subscription = next(f for f in files if f["id"] == "subscription")

        assert '"plan_type": "pro"' in subscription["body"]
        assert '"plan_name": "Pro"' in subscription["body"]
        assert '"cancel_scheduled": false' in subscription["body"]

    async def test_selected_voice_resolves_the_name_from_the_catalog(self, sources) -> None:
        files, _ = await _build()
        selected = next(f for f in files if f["id"] == "voices/selected")

        assert '"voice_id": "v-1"' in selected["body"]
        assert '"name": "Rachel"' in selected["body"]

    async def test_linked_platform_reports_connection_state_only(self, sources) -> None:
        files, _ = await _build()
        telegram = next(f for f in files if f["id"] == "linked-telegram")
        discord = next(f for f in files if f["id"] == "linked-discord")

        assert (
            '"platform": "telegram"' in telegram["body"] and '"connected": true' in telegram["body"]
        )
        assert '"connected_at": "2026-01-01"' in telegram["body"]
        assert '"connected": false' in discord["body"]

    async def test_one_failing_source_skips_only_its_group_and_is_preserved_from_prune(
        self, sources
    ) -> None:
        with patch(
            f"{MODULE}.list_voices", new=AsyncMock(side_effect=RuntimeError("elevenlabs down"))
        ):
            files, failed = await _build()

        ids = _ids(files)
        assert "voices/catalog" not in ids and "voices/selected" not in ids
        # The other groups still refreshed — one flaky provider must not blank
        # the whole account view.
        assert {"subscription", "usage", "notifications"} <= ids
        # The failed group's previous on-disk projection must survive the prune.
        assert failed == {
            f"{ACCOUNT_DIR}/voices/catalog.json",
            f"{ACCOUNT_DIR}/voices/selected.json",
        }

    async def test_failing_link_source_drops_the_linked_files_but_keeps_the_rest(
        self, sources
    ) -> None:
        with patch(
            f"{MODULE}.PlatformLinkService.get_linked_platforms",
            new=AsyncMock(side_effect=RuntimeError("redis down")),
        ):
            files, failed = await _build()

        assert not any(fid.startswith("linked-") for fid in _ids(files))
        assert "subscription" in _ids(files)
        # Failed link source: its stale files are preserved, not re-projected
        # as "not connected" from no data and not pruned away either.
        assert failed == {f"{ACCOUNT_DIR}/linked-accounts/{p.value}.json" for p in Platform}


@pytest.mark.unit
class TestSyncAccountFiles:
    async def test_missing_mount_is_a_zero_sync_not_an_error(self, sources) -> None:
        with (
            patch(f"{MODULE}._is_mounted", return_value=False),
            patch(f"{MODULE}.materialize_account_files") as materialize,
        ):
            assert await account_fs.sync_account_files(USER_ID) == 0
        materialize.assert_not_called()

    async def test_mounted_pass_materializes_the_workspace_path(self, sources) -> None:
        with (
            patch(f"{MODULE}._is_mounted", return_value=True),
            patch(
                f"{MODULE}.user_workspace_path", return_value="/mnt/jfs/users/user-1"
            ) as workspace_path,
            patch(f"{MODULE}.materialize_account_files", return_value=3) as materialize,
        ):
            assert await account_fs.sync_account_files(USER_ID) == 3

            workspace_path.assert_called_once_with(USER_ID)
            args = materialize.call_args.args
        assert args[0] == "/mnt/jfs/users/user-1"
        assert all(f["path"].startswith(f"{ACCOUNT_DIR}/") for f in args[1])
