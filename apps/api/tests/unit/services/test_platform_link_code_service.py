"""Tests for the one-tap platform-linking code.

The code links a bot account to a GAIA user with no login, so minting, the
single-use guarantee, and the exact shape of the deep links (which the adapters
parse back) are the boundaries worth probing.
"""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
import pytest
from redis.exceptions import RedisError

from app.constants.auth import PLATFORM_LINK_CODE_BYTES
from app.constants.cache import (
    PLATFORM_LINK_CODE_CLAIM_ATTEMPTS,
    PLATFORM_LINK_CODE_CLAIM_TTL,
    PLATFORM_LINK_CODE_PREFIX,
    PLATFORM_LINK_CODE_TTL,
)
from app.models.user_models import OnboardingNeed, OnboardingPreferences
import app.services.platform_link_code_service as svc
from app.services.platform_link_code_service import (
    build_handoff_links,
    build_handoff_text,
    claim_platform_link_code,
    discard_platform_link_code,
    mint_platform_link_code,
    release_platform_link_code,
)
from app.utils.errors import AppError

FIRST_MESSAGE = "Hi! I'm a founder. I could use help with my inbox and my todos. Who are you?"
PREFS = OnboardingPreferences(profession="founder", needs=[OnboardingNeed.INBOX])


@pytest.fixture
def fake_store() -> Generator[dict[str, tuple[object, int | None]], None, None]:
    """In-memory stand-in for the Redis single-use store."""
    store: dict[str, tuple[object, int | None]] = {}

    async def _set(key: str, value: object, ttl: int | None = None) -> bool:
        store[key] = (value, ttl)
        return True

    async def _get(key: str, model: type | None = None) -> object | None:
        entry = store.get(key)
        if entry is None:
            return None
        value, _ttl = entry
        if model is None:
            return value
        try:
            return model.model_validate(value)
        except ValidationError:
            # What get_cache does with a record it cannot validate: log and None.
            return None

    async def _get_raw(name: str) -> object | None:
        entry = store.get(name)
        return None if entry is None else entry[0]

    async def _delete(key: str) -> None:
        store.pop(key, None)

    async def _set_nx(name: str, value: str, *, ex: int | None = None, nx: bool = False):
        if nx and name in store:
            return None
        store[name] = (value, ex)
        return True

    redis = MagicMock()
    redis.client.set = AsyncMock(side_effect=_set_nx)
    redis.client.get = AsyncMock(side_effect=_get_raw)

    with (
        patch.object(svc, "set_cache", AsyncMock(side_effect=_set)),
        patch.object(svc, "get_cache", AsyncMock(side_effect=_get)),
        patch.object(svc, "delete_cache", AsyncMock(side_effect=_delete)),
        patch.object(svc, "redis_cache", redis),
    ):
        yield store


def _elapse(store: dict[str, tuple[object, int | None]], seconds: int) -> None:
    """Drop what Redis would have expired after the given number of seconds."""
    for key, (value, ttl) in list(store.items()):
        if ttl is None:
            continue
        if ttl <= seconds:
            del store[key]
        else:
            store[key] = (value, ttl - seconds)


class TestClaimReleaseDiscard:
    async def test_mint_then_claim_returns_the_binding(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        code = await mint_platform_link_code("user1", PREFS)
        claim = await claim_platform_link_code(code)
        assert claim.payload is not None
        assert claim.payload.user_id == "user1"
        assert claim.payload.preferences == PREFS

    async def test_a_second_claim_while_the_first_runs_gets_nothing(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        """Single-use is the claim, not the read."""
        code = await mint_platform_link_code("user1", PREFS)
        assert (await claim_platform_link_code(code)).payload is not None

        second = await claim_platform_link_code(code)
        assert second.payload is None
        assert second.in_flight is True

    async def test_a_marker_that_vanishes_after_a_lost_claim_is_retried(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        """A twin releasing between the lost SET NX and the read must not make a live code look spent."""
        code = await mint_platform_link_code("user1", PREFS)
        real_set = svc.redis_cache.client.set.side_effect
        lost = {"once": False}

        async def _lose_once(name: str, value: str, *, ex: int | None = None, nx: bool = False):
            if not lost["once"]:
                lost["once"] = True
                return None
            return await real_set(name, value, ex=ex, nx=nx)

        svc.redis_cache.client.set.side_effect = _lose_once

        claim = await claim_platform_link_code(code)

        assert claim.payload is not None
        assert claim.in_flight is False

    async def test_a_claim_lost_on_every_attempt_fails_loud_instead_of_claiming_success(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        """Contention that outlasts every retry must not be answered as linked; the user taps again."""
        code = await mint_platform_link_code("user1", PREFS)
        svc.redis_cache.client.set.side_effect = None
        svc.redis_cache.client.set.return_value = None

        with pytest.raises(AppError) as exc:
            await claim_platform_link_code(code)

        assert exc.value.status_code == 503
        assert exc.value.to_dict() == {
            "message": "The link is busy. Please tap it again.",
            "why": "the one-tap code was claimed and released by concurrent redemptions on every attempt",
            "fix": "tap the link again; the code is still valid",
        }
        assert svc.redis_cache.client.set.await_count == PLATFORM_LINK_CODE_CLAIM_ATTEMPTS

    async def test_releasing_leaves_the_code_claimable_again(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        """A refused redemption must leave the code live for the retry the refusal asks for."""
        code = await mint_platform_link_code("user1", PREFS)
        await claim_platform_link_code(code)
        await release_platform_link_code(code)
        assert (await claim_platform_link_code(code)).payload is not None

    async def test_discard_makes_the_code_single_use(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        code = await mint_platform_link_code("user1", PREFS)
        await claim_platform_link_code(code)
        await discard_platform_link_code(code)

        # The binding itself goes, rather than sitting out its half hour.
        assert f"{PLATFORM_LINK_CODE_PREFIX}:{code}" not in fake_store
        spent = await claim_platform_link_code(code)
        # Spent, not in flight: the claim goes with the record, so a later tap
        # is told the code is dead instead of being answered as a twin.
        assert spent.payload is None
        assert spent.in_flight is False

    async def test_a_transient_failure_writing_the_spent_marker_is_retried(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        """One Redis blip at spend time must not leave a live record to redeem again."""
        code = await mint_platform_link_code("user1", PREFS)
        await claim_platform_link_code(code)
        real_set = svc.redis_cache.client.set.side_effect
        calls = 0

        async def _blip_once(*args: object, **kwargs: object) -> bool:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RedisError("connection reset")
            return await real_set(*args, **kwargs)

        svc.redis_cache.client.set.side_effect = _blip_once
        await discard_platform_link_code(code)

        _elapse(fake_store, PLATFORM_LINK_CODE_CLAIM_TTL)
        spent = await claim_platform_link_code(code)
        assert spent.payload is None
        assert spent.in_flight is False

    async def test_a_spend_that_fails_every_attempt_raises_the_last_error(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        code = await mint_platform_link_code("user1", PREFS)
        await claim_platform_link_code(code)
        errors = [RedisError(f"down {n}") for n in range(PLATFORM_LINK_CODE_CLAIM_ATTEMPTS)]
        svc.redis_cache.client.set.side_effect = errors
        svc.redis_cache.client.set.await_count = 0

        with pytest.raises(RedisError) as excinfo:
            await discard_platform_link_code(code)

        assert excinfo.value is errors[-1]
        assert svc.redis_cache.client.set.await_count == PLATFORM_LINK_CODE_CLAIM_ATTEMPTS

    async def test_a_spend_whose_record_delete_fails_still_kills_the_code(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        """delete_cache swallows a failing Redis delete, so a spend cannot rely on it."""
        code = await mint_platform_link_code("user1", PREFS)
        await claim_platform_link_code(code)
        with patch.object(svc, "delete_cache", AsyncMock()):
            await discard_platform_link_code(code)

        # Past the claim's recovery TTL, which is what would have freed a live
        # record for a second redemption and repeated the greeting.
        _elapse(fake_store, PLATFORM_LINK_CODE_CLAIM_TTL)
        spent = await claim_platform_link_code(code)
        assert spent.payload is None
        assert spent.in_flight is False

    async def test_the_claim_carries_the_recovery_ttl(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        """A claim without an expiry strands the code if its redeemer dies."""
        code = await mint_platform_link_code("user1", PREFS)
        await claim_platform_link_code(code)
        value, ttl = fake_store[f"{PLATFORM_LINK_CODE_PREFIX}:claim:{code}"]
        assert value == "1"
        assert ttl == PLATFORM_LINK_CODE_CLAIM_TTL == 300

    async def test_a_spent_code_is_marked_for_the_records_whole_life(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        """The marker outlives the record it replaces, or the spend is not durable."""
        code = await mint_platform_link_code("user1", PREFS)
        await claim_platform_link_code(code)
        await discard_platform_link_code(code)
        value, ttl = fake_store[f"{PLATFORM_LINK_CODE_PREFIX}:claim:{code}"]
        assert value == "spent"
        assert ttl == PLATFORM_LINK_CODE_TTL

    async def test_two_codes_do_not_share_a_claim(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        first = await mint_platform_link_code("user1", PREFS)
        second = await mint_platform_link_code("user2", PREFS)
        await claim_platform_link_code(first)
        assert (await claim_platform_link_code(second)).payload is not None

    async def test_an_unknown_code_stays_unknown_on_the_retry(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        """The claim a missing record hands back has to be the one it took."""
        assert (await claim_platform_link_code("ghost")).in_flight is False
        second = await claim_platform_link_code("ghost")
        assert second.payload is None
        assert second.in_flight is False

    async def test_a_record_that_no_longer_validates_is_a_dead_code(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        """Read as the payload model, so a record that fails validation reads as gone."""
        code = await mint_platform_link_code("user1", PREFS)
        fake_store[f"{PLATFORM_LINK_CODE_PREFIX}:{code}"] = ({"preferences": {}}, 1_800)
        claim = await claim_platform_link_code(code)
        assert claim.payload is None
        assert claim.in_flight is False

    async def test_unknown_code_is_empty(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        claim = await claim_platform_link_code("not-a-real-code")
        assert claim.payload is None
        assert claim.in_flight is False

    async def test_two_mints_have_distinct_codes(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        assert await mint_platform_link_code("u", PREFS) != await mint_platform_link_code(
            "u", PREFS
        )

    async def test_code_is_stored_with_the_thirty_minute_ttl(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        code = await mint_platform_link_code("user1", PREFS)
        _value, ttl = fake_store[f"platform_link_code:{code}"]
        assert ttl == PLATFORM_LINK_CODE_TTL == 1_800

    async def test_the_stored_payload_is_json_native_under_the_prefixed_key(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        """The needs must be stored as str, not OnboardingNeed members — an enum instance is a value only this process can decode."""
        prefs = OnboardingPreferences(
            profession="founder", needs=[OnboardingNeed.INBOX, OnboardingNeed.CALENDAR]
        )
        code = await mint_platform_link_code("user1", prefs)

        assert list(fake_store) == [f"{PLATFORM_LINK_CODE_PREFIX}:{code}"]
        value, ttl = fake_store[f"{PLATFORM_LINK_CODE_PREFIX}:{code}"]
        assert value == {
            "user_id": "user1",
            "preferences": {
                "profession": "founder",
                "needs": ["inbox", "calendar"],
                "response_style": None,
                "other_need": None,
                "custom_instructions": None,
            },
        }
        assert [type(need) for need in value["preferences"]["needs"]] == [str, str]
        assert ttl == PLATFORM_LINK_CODE_TTL

    async def test_code_length_matches_the_adapters_regex(
        self, fake_store: dict[str, tuple[object, int | None]]
    ) -> None:
        """22 urlsafe chars — the exact width the bots' #code pattern accepts."""
        code = await mint_platform_link_code("user1", PREFS)
        assert PLATFORM_LINK_CODE_BYTES == 16
        assert len(code) == 22

    async def test_unstorable_code_fails_loud(self) -> None:
        """A code Redis never accepted would 'expire' the instant the user arrives."""
        with (
            patch.object(svc, "set_cache", AsyncMock(return_value=False)),
            patch.object(svc, "log") as mock_log,
        ):
            with pytest.raises(AppError) as excinfo:
                await mint_platform_link_code("user1", PREFS)
        assert excinfo.value.status_code == 503
        # The whole payload the client renders — a blank or garbled why/fix
        # leaves the user with a dead end instead of a retry.
        assert excinfo.value.to_dict() == {
            "message": "Could not start platform linking. Please retry.",
            "why": "the link code could not be stored (Redis unavailable)",
            "fix": "retry in a moment, or connect the platform from settings with /auth",
        }
        # Loud on the operator side too: the 503 tells the user to retry, and
        # only this line says whose mint died and where. error, not info, so
        # the fields reach the wide event's errors[] rather than a loguru line.
        mock_log.error.assert_called_once_with(
            "could not store the one-tap link code",
            user={"id": "user1"},
            operation="mint_platform_link_code",
        )


class TestHandoffLinks:
    def test_handoff_text_appends_the_code(self) -> None:
        assert build_handoff_text("Hi there!", "abc123") == "Hi there! #abc123"

    def test_telegram_link_carries_the_code_as_a_start_payload(self) -> None:
        with patch.object(svc.settings, "TELEGRAM_BOT_USERNAME", "heygaia_bot"):
            links = build_handoff_links("CODE123", FIRST_MESSAGE)
        assert links["telegram"] == "https://t.me/heygaia_bot?start=CODE123"

    def test_whatsapp_link_urlencodes_the_handoff_text(self) -> None:
        with patch.object(svc.settings, "WHATSAPP_PHONE_NUMBER", "15551234567"):
            links = build_handoff_links("CODE123", "Hi! I'm a founder. Who are you?")
        assert links["whatsapp"] == (
            "https://wa.me/15551234567?text="
            "Hi%21%20I%27m%20a%20founder.%20Who%20are%20you%3F%20%23CODE123"
        )

    def test_imessage_has_no_link_its_number_is_per_user(self) -> None:
        with (
            patch.object(svc.settings, "TELEGRAM_BOT_USERNAME", "heygaia_bot"),
            patch.object(svc.settings, "WHATSAPP_PHONE_NUMBER", "15551234567"),
        ):
            links = build_handoff_links("CODE123", FIRST_MESSAGE)
        assert set(links) == {"telegram", "whatsapp"}

    def test_unconfigured_platform_is_omitted_not_broken(self) -> None:
        with (
            patch.object(svc.settings, "TELEGRAM_BOT_USERNAME", None),
            patch.object(svc.settings, "WHATSAPP_PHONE_NUMBER", None),
        ):
            assert build_handoff_links("CODE123", FIRST_MESSAGE) == {}
