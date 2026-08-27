"""Unit tests for the account-center workspace sync glue.

Every source (payment provider, Redis-backed usage, Mongo user, ElevenLabs
catalog, platform links, JuiceFS) is mocked at its seam; the logic under test
is the projection assembly, the per-group failure isolation, and the
changed-body-only materialization contract.

Bodies are asserted as PARSED JSON compared whole, not by substring. A
substring check ("'plan_type': 'pro' is in there somewhere") leaves every other
field in the document unasserted, so a builder can drop or corrupt a field and
the test stays green — which is exactly what the mutation lane caught here. The
body IS the contract: the agent reads these files.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.account import ACCOUNT_DIR, ACCOUNT_LINKED_ACCOUNTS_DIRNAME
from app.models.payment_models import PlanType
from app.schemas.usage import FeatureUsageSummary, UsageBudget
from app.services import account_fs
from app.services.platform_link_service import Platform
from tests.helpers import captured_wide_event

MODULE = "app.services.account_fs"
USER_ID = "user-1"

_BUDGET = UsageBudget.model_validate(
    {
        "daily": {"percentage": 0.0, "reset_time": "2026-01-02T00:00:00+00:00"},
        "monthly": {"percentage": 12.5, "reset_time": "2026-02-01T00:00:00+00:00"},
        "per_request_token_ceiling": 300_000,
    }
)
# Every optional field carries a NON-default value on purpose: a projection that
# drops `monthly` or `features` still serializes identically when the source has
# the defaults, so a fixture full of defaults cannot detect the field going missing.
_FEATURES = {
    "chat": FeatureUsageSummary.model_validate(
        {
            "title": "Chat",
            "description": "Messages sent",
            "upgrade": {"day": 500, "month": 10_000},
            "periods": {
                "day": {
                    "used": 3,
                    "limit": 100,
                    "percentage": 3.0,
                    "reset_time": "2026-01-02T00:00:00+00:00",
                    "remaining": 97,
                }
            },
        }
    )
}


def _voice(voice_id: str = "v-1", name: str = "Rachel", starred: bool = False):
    return SimpleNamespace(voice_id=voice_id, name=name, starred=starred)


def _subscription_status(
    plan_type: PlanType | None = PlanType.PRO,
    current_plan: dict | None = None,
    subscription: dict | None = None,
):
    return SimpleNamespace(
        plan_type=plan_type,
        current_plan=(
            {"name": "Pro", "amount": 15, "currency": "$", "duration": "month"}
            if current_plan is None
            else current_plan
        ),
        subscription={"status": "active"} if subscription is None else subscription,
    )


@pytest.fixture
def sources():
    """Patch every account source with a working default; tests override one.

    Yields the mocks so a test can assert WHICH user each source was queried
    for — the bodies alone cannot show that, since a mock answers the same for
    every argument.
    """
    catalog = SimpleNamespace(voices=[_voice()], selected_voice_id="v-1")
    linked = {"telegram": {"connectedAt": "2026-01-01", "username": "dh", "displayName": "Dh"}}
    subscription_status = AsyncMock(return_value=_subscription_status())
    usage_summary = AsyncMock(
        return_value=SimpleNamespace(plan_type="pro", budget=_BUDGET, features=_FEATURES)
    )
    channel_preferences = AsyncMock(return_value={"email": True})
    users = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                timezone="UTC",
                onboarding={
                    "preferences": {
                        "response_style": "brief",
                        "custom_instructions": "Be terse.",
                    }
                },
            )
        )
    )
    voices = AsyncMock(return_value=catalog)
    linked_platforms = AsyncMock(return_value=linked)
    with (
        patch(f"{MODULE}.payment_service.get_user_subscription_status", new=subscription_status),
        patch(f"{MODULE}.build_usage_summary", new=usage_summary),
        patch(f"{MODULE}.fetch_channel_preferences", new=channel_preferences),
        patch(f"{MODULE}.user_repository", new=users),
        patch(f"{MODULE}.list_voices", new=voices),
        patch(f"{MODULE}.PlatformLinkService.get_linked_platforms", new=linked_platforms),
    ):
        yield SimpleNamespace(
            subscription_status=subscription_status,
            usage_summary=usage_summary,
            channel_preferences=channel_preferences,
            users=users,
            voices=voices,
            linked_platforms=linked_platforms,
        )


async def _build(user_id: str = USER_ID) -> tuple[list[dict], set[str]]:
    return await account_fs.build_account_projections(user_id)


def _ids(files: list[dict]) -> set[str]:
    return {f["id"] for f in files}


async def _raw(group: str, user_id: str = USER_ID) -> str:
    """The serialized body of one projected group, exactly as it hits disk."""
    files, _ = await _build(user_id)
    return next(f for f in files if f["id"] == group)["body"]


async def _body(group: str, user_id: str = USER_ID) -> dict:
    """The parsed JSON body of one projected group."""
    return json.loads(await _raw(group, user_id))


def _serialized(payload: dict) -> str:
    """The exact on-disk form: 2-space indent, one trailing newline.

    Built with stdlib json rather than the projection model, so this asserts the
    format independently instead of re-running the code under test.
    """
    return json.dumps(payload, indent=2) + "\n"


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

    async def test_each_group_lands_at_its_own_path_under_account(self, sources) -> None:
        """The id -> path mapping, pinned per group.

        Asserting only the shared ``account/`` prefix lets any two groups swap
        paths, or every group collapse onto one file, without a test noticing.
        """
        files, _ = await _build()
        paths = {f["id"]: f["path"] for f in files}

        for group in (
            "subscription",
            "usage",
            "notifications",
            "preferences",
            "custom-instructions",
            "voices/catalog",
            "voices/selected",
        ):
            assert paths[group] == f"{ACCOUNT_DIR}/{group}.json"
        for platform in Platform:
            assert paths[f"linked-{platform.value}"] == (
                f"{ACCOUNT_DIR}/{ACCOUNT_LINKED_ACCOUNTS_DIRNAME}/{platform.value}.json"
            )

    async def test_bodies_are_indented_json_with_a_trailing_newline(self, sources) -> None:
        """The on-disk format itself: 2-space indent, one trailing newline.

        These files are read by a human and diffed by the materializer's
        content check, so the serialization is part of the contract.
        """
        files, _ = await _build()
        subscription = next(f for f in files if f["id"] == "subscription")

        assert subscription["body"].endswith("}\n")
        assert '\n  "plan_type"' in subscription["body"]


@pytest.mark.unit
class TestSourceIdentity:
    async def test_every_source_is_queried_for_the_requested_user(self, sources) -> None:
        """Each builder must pass the user id through to its source.

        Nothing else in this file can catch a builder that queries the wrong
        user (or None): the mocked sources answer identically whatever they are
        asked, so the body comes out right while the data belongs to someone
        else. In production that is one user's plan, usage and linked accounts
        projected into another user's workspace.
        """
        await _build("user-42")

        sources.subscription_status.assert_awaited_once_with("user-42")
        sources.usage_summary.assert_awaited_once_with("user-42")
        sources.channel_preferences.assert_awaited_once_with("user-42")
        assert [call.args for call in sources.voices.await_args_list] == [
            ("user-42",),
            ("user-42",),
        ]
        sources.linked_platforms.assert_awaited_once_with("user-42")
        assert {call.args[0] for call in sources.users.get.await_args_list} == {"user-42"}

    async def test_sync_builds_the_projections_for_the_requested_user(self, sources) -> None:
        with (
            patch(f"{MODULE}._is_mounted", return_value=True),
            patch(f"{MODULE}.user_workspace_path", return_value="/mnt/jfs/users/user-42"),
            patch(f"{MODULE}.materialize_account_files", return_value=0),
        ):
            await account_fs.sync_account_files("user-42")

        sources.subscription_status.assert_awaited_once_with("user-42")


@pytest.mark.unit
class TestProjectionBodies:
    """Each builder's serialized body, compared whole."""

    async def test_subscription_body(self, sources) -> None:
        assert await _raw("subscription") == _serialized(
            {
                "plan_type": "pro",
                "plan_name": "Pro",
                "price": "$ 15 / month",
                "status": "active",
                "cancel_scheduled": False,
            }
        )

    async def test_subscription_without_an_amount_has_no_price(self, sources) -> None:
        with patch(
            f"{MODULE}.payment_service.get_user_subscription_status",
            new=AsyncMock(return_value=_subscription_status(current_plan={"name": "Trial"})),
        ):
            body = await _body("subscription")

        assert body["price"] is None
        assert body["plan_name"] == "Trial"

    async def test_subscription_price_omits_a_missing_currency_and_duration(self, sources) -> None:
        """The price string is assembled from three optional plan fields."""
        with patch(
            f"{MODULE}.payment_service.get_user_subscription_status",
            new=AsyncMock(return_value=_subscription_status(current_plan={"amount": 9})),
        ):
            body = await _body("subscription")

        assert body["price"] == "9 / period"

    async def test_subscription_falls_back_to_free_when_the_provider_has_no_plan(
        self, sources
    ) -> None:
        with patch(
            f"{MODULE}.payment_service.get_user_subscription_status",
            new=AsyncMock(
                return_value=_subscription_status(plan_type=None, current_plan={}, subscription={})
            ),
        ):
            body = await _body("subscription")

        assert body == {
            "plan_type": PlanType.FREE.value,
            "plan_name": None,
            "price": None,
            "status": None,
            "cancel_scheduled": False,
        }

    async def test_subscription_reports_a_scheduled_cancellation(self, sources) -> None:
        with patch(
            f"{MODULE}.payment_service.get_user_subscription_status",
            new=AsyncMock(
                return_value=_subscription_status(
                    subscription={"status": "active", "cancel_at_next_billing_date": True}
                )
            ),
        ):
            body = await _body("subscription")

        assert body["cancel_scheduled"] is True
        assert body["status"] == "active"

    async def test_usage_body(self, sources) -> None:
        assert await _raw("usage") == _serialized(
            {
                "plan_type": "pro",
                "daily": {"percentage": 0.0, "reset_time": "2026-01-02T00:00:00+00:00"},
                "monthly": {"percentage": 12.5, "reset_time": "2026-02-01T00:00:00+00:00"},
                "per_request_token_ceiling": 300_000,
                "features": {
                    "chat": {
                        "title": "Chat",
                        "description": "Messages sent",
                        "upgrade": {"day": 500, "month": 10_000},
                        "periods": {
                            "day": {
                                "used": 3,
                                "limit": 100,
                                "percentage": 3.0,
                                "reset_time": "2026-01-02T00:00:00+00:00",
                                "remaining": 97,
                            }
                        },
                    }
                },
            }
        )

    async def test_notifications_body_carries_every_channel_flag(self, sources) -> None:
        with patch(
            f"{MODULE}.fetch_channel_preferences",
            new=AsyncMock(return_value={"email": True, "telegram": False}),
        ):
            assert await _raw("notifications") == _serialized(
                {"channels": {"email": True, "telegram": False}}
            )

    async def test_preferences_body(self, sources) -> None:
        assert await _raw("preferences") == _serialized(
            {"response_style": "brief", "timezone": "UTC"}
        )

    async def test_preferences_without_a_user_has_no_timezone(self, sources) -> None:
        with patch(f"{MODULE}.user_repository", get=AsyncMock(return_value=None)):
            assert await _body("preferences") == {"response_style": None, "timezone": None}

    async def test_preferences_ignore_a_non_dict_preferences_blob(self, sources) -> None:
        """Mongo's ``onboarding.preferences`` is an untyped blob.

        A string or a list there must read as "no preferences", not blow up the
        whole projection pass.
        """
        with patch(
            f"{MODULE}.user_repository",
            get=AsyncMock(
                return_value=SimpleNamespace(timezone="UTC", onboarding={"preferences": "brief"})
            ),
        ):
            assert await _body("preferences") == {"response_style": None, "timezone": "UTC"}

    async def test_preferences_survive_a_missing_onboarding_document(self, sources) -> None:
        with patch(
            f"{MODULE}.user_repository",
            get=AsyncMock(return_value=SimpleNamespace(timezone="UTC", onboarding=None)),
        ):
            assert await _body("preferences") == {"response_style": None, "timezone": "UTC"}

    async def test_custom_instructions_body(self, sources) -> None:
        assert await _raw("custom-instructions") == _serialized({"instructions": "Be terse."})

    async def test_custom_instructions_are_null_when_unset(self, sources) -> None:
        with patch(
            f"{MODULE}.user_repository",
            get=AsyncMock(
                return_value=SimpleNamespace(
                    timezone="UTC", onboarding={"preferences": {"response_style": "brief"}}
                )
            ),
        ):
            assert await _body("custom-instructions") == {"instructions": None}

    async def test_voice_catalog_body(self, sources) -> None:
        with patch(
            f"{MODULE}.list_voices",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    voices=[_voice(), _voice("v-2", "Adam", starred=True)],
                    selected_voice_id="v-1",
                )
            ),
        ):
            assert await _raw("voices/catalog") == _serialized(
                {
                    "voices": [
                        {"voice_id": "v-1", "name": "Rachel", "starred": False},
                        {"voice_id": "v-2", "name": "Adam", "starred": True},
                    ]
                }
            )

    async def test_voice_catalog_is_empty_when_the_provider_returns_none(self, sources) -> None:
        with patch(
            f"{MODULE}.list_voices",
            new=AsyncMock(return_value=SimpleNamespace(voices=[], selected_voice_id=None)),
        ):
            assert await _body("voices/catalog") == {"voices": []}

    async def test_voice_selected_body_resolves_the_name_from_the_catalog(self, sources) -> None:
        with patch(
            f"{MODULE}.list_voices",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    voices=[_voice(), _voice("v-2", "Adam")], selected_voice_id="v-2"
                )
            ),
        ):
            assert await _raw("voices/selected") == _serialized({"voice_id": "v-2", "name": "Adam"})

    async def test_voice_selected_name_is_null_when_the_id_is_not_in_the_catalog(
        self, sources
    ) -> None:
        """A selected id the catalog no longer offers still projects the id."""
        with patch(
            f"{MODULE}.list_voices",
            new=AsyncMock(
                return_value=SimpleNamespace(voices=[_voice()], selected_voice_id="v-gone")
            ),
        ):
            assert await _body("voices/selected") == {"voice_id": "v-gone", "name": None}

    async def test_voice_selected_is_all_null_when_nothing_is_selected(self, sources) -> None:
        with patch(
            f"{MODULE}.list_voices",
            new=AsyncMock(return_value=SimpleNamespace(voices=[_voice()], selected_voice_id=None)),
        ):
            assert await _body("voices/selected") == {"voice_id": None, "name": None}

    async def test_linked_platform_body_for_a_connected_account(self, sources) -> None:
        assert await _raw("linked-telegram") == _serialized(
            {
                "platform": "telegram",
                "connected": True,
                "connected_at": "2026-01-01",
                "username": "dh",
                "display_name": "Dh",
            }
        )

    async def test_linked_platform_body_for_an_unconnected_account(self, sources) -> None:
        assert await _body("linked-discord") == {
            "platform": "discord",
            "connected": False,
            "connected_at": None,
            "username": None,
            "display_name": None,
        }

    async def test_linked_platform_omits_fields_the_provider_did_not_send(self, sources) -> None:
        """A link record carrying only a timestamp still projects as connected."""
        with patch(
            f"{MODULE}.PlatformLinkService.get_linked_platforms",
            new=AsyncMock(return_value={"slack": {"connectedAt": "2026-02-02"}}),
        ):
            assert await _body("linked-slack") == {
                "platform": "slack",
                "connected": True,
                "connected_at": "2026-02-02",
                "username": None,
                "display_name": None,
            }


@pytest.mark.unit
class TestSourceFailureIsolation:
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

    async def test_a_failing_source_logs_the_group_and_the_error_type(self, sources) -> None:
        """The swallow is only defensible if the failure is observable.

        ``_safe_body`` returns None so the pass continues; the error event is
        the ONLY record that a provider broke, so its fields are the contract.
        """
        async with captured_wide_event() as event:
            with patch(
                f"{MODULE}.build_usage_summary",
                new=AsyncMock(side_effect=RuntimeError("redis down")),
            ):
                await _build()

        (error,) = event["errors"]
        assert "account projection failed" in error["msg"]
        assert error["group"] == "usage"
        assert error["user"] == {"id": USER_ID}
        assert error["error_type"] == "RuntimeError"
        assert error["error"] == "redis down"

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
        assert failed == {
            f"{ACCOUNT_DIR}/{ACCOUNT_LINKED_ACCOUNTS_DIRNAME}/{p.value}.json" for p in Platform
        }

    async def test_a_failing_link_source_logs_every_preserved_path(self, sources) -> None:
        async with captured_wide_event() as event:
            with patch(
                f"{MODULE}.PlatformLinkService.get_linked_platforms",
                new=AsyncMock(side_effect=RuntimeError("mongo down")),
            ):
                await _build()

        (error,) = event["errors"]
        assert "linked accounts skipped" in error["msg"]
        assert error["user"] == {"id": USER_ID}
        assert error["error_type"] == "RuntimeError"
        assert error["error"] == "mongo down"
        assert error["preserved"] == sorted(
            f"{ACCOUNT_DIR}/{ACCOUNT_LINKED_ACCOUNTS_DIRNAME}/{p.value}.json" for p in Platform
        )

    async def test_two_independent_failures_skip_only_their_own_groups(self, sources) -> None:
        with (
            patch(f"{MODULE}.list_voices", new=AsyncMock(side_effect=RuntimeError("a"))),
            patch(
                f"{MODULE}.fetch_channel_preferences", new=AsyncMock(side_effect=RuntimeError("b"))
            ),
        ):
            files, failed = await _build()

        assert failed == {
            f"{ACCOUNT_DIR}/voices/catalog.json",
            f"{ACCOUNT_DIR}/voices/selected.json",
            f"{ACCOUNT_DIR}/notifications.json",
        }
        assert {"subscription", "usage", "preferences"} <= _ids(files)


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

    async def test_sync_forwards_the_failed_paths_so_they_are_not_pruned(self, sources) -> None:
        """The preserve set has to reach the materializer to do anything.

        Dropping it here is invisible from the projection tests — they assert
        ``build_account_projections`` returns it — and would silently restore
        the bug where a provider outage deletes a valid account view.
        """
        with (
            patch(f"{MODULE}._is_mounted", return_value=True),
            patch(f"{MODULE}.user_workspace_path", return_value="/mnt/jfs/users/user-1"),
            patch(f"{MODULE}.list_voices", new=AsyncMock(side_effect=RuntimeError("down"))),
            patch(f"{MODULE}.materialize_account_files", return_value=0) as materialize,
        ):
            await account_fs.sync_account_files(USER_ID)

        assert materialize.call_args.args[2] == {
            f"{ACCOUNT_DIR}/voices/catalog.json",
            f"{ACCOUNT_DIR}/voices/selected.json",
        }
