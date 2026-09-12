"""Unit tests for the bot platform-linking endpoints.

Split out of ``test_bot_endpoint.py`` to match the route split: these cover
``app/api/v1/endpoints/bot_links.py`` (create-link-token, redeem-link-code,
link-token-info). Assertions are unchanged from the original module — only the
patch targets moved with the code.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from httpx import AsyncClient
import pytest

from app.config.settings import settings
from app.constants.auth import AUDIT_ACTOR_BOT_API, AUDIT_ACTOR_UNAUTHENTICATED
from app.constants.cache import PLATFORM_LINK_TOKEN_PREFIX, PLATFORM_LINK_TOKEN_TTL
from app.constants.general import NEW_MESSAGE_BREAKER
from app.models.bot_models import (
    CreateLinkTokenRequest,
    CreateLinkTokenResponse,
    RedeemLinkCodeRequest,
)
from app.models.payment_models import PlanType
from app.models.platform_models import PlatformLinkCompletion, PlatformLinkResult
from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.outbound_delivery import OutboundResult
from app.services.platform_link_code_service import PlatformLinkCodePayload
from app.utils.errors import AppError
from shared.py.wide_events import log, log_context

from app.api.v1.endpoints.bot_links import (  # isort: skip
    _persist_first_contact,
    create_link_token,
    get_link_token_info,
    redeem_link_code,
)

BOT_BASE = "/api/v1/bot"
PLAN_PATCH = "app.services.platform_link_service.payment_service.get_cached_plan_type"


def _make_request(bot_api_key_valid: bool = True, **extra_state: object) -> MagicMock:
    """Build a fake Request whose .state carries bot auth attributes."""
    state = MagicMock()
    state.bot_api_key_valid = bot_api_key_valid
    state.bot_platform = extra_state.get("bot_platform")
    state.bot_platform_user_id = extra_state.get("bot_platform_user_id")
    state.user = extra_state.get("user")
    state.authenticated = extra_state.get("authenticated", False)
    return state


_CREATE_BODY = CreateLinkTokenRequest(platform="discord", platform_user_id="user123")


async def _create_link_token(
    body: CreateLinkTokenRequest, redis_client: AsyncMock, **state: object
) -> tuple[CreateLinkTokenResponse | HTTPException, dict[str, object]]:
    """Run the handler inside a wide-event boundary.

    Returns the response — or the ``HTTPException`` the header guard raised —
    together with the wide event the call stamped, so a test can assert the
    refusal and its audit trail in one place.
    """
    request = MagicMock()
    request.state = _make_request(**state)
    with (
        patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new=AsyncMock()),
        patch("app.api.v1.endpoints.bot_links.redis_cache") as mock_cache,
    ):
        mock_cache.client = redis_client
        async with log_context("create_link_token_test"):
            result: CreateLinkTokenResponse | HTTPException
            try:
                result = await create_link_token(request, body)
            except HTTPException as exc:
                result = exc
            return result, dict(log.get())


@pytest.fixture(autouse=True)
def _pro_plan_by_default():
    """GAIA is paid-only: default every test in this file to a paying user."""
    with patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.PRO):
        yield


# ---------------------------------------------------------------------------
# POST /bot/create-link-token
# ---------------------------------------------------------------------------


class TestCreateLinkToken:
    """POST /api/v1/bot/create-link-token"""

    @patch("app.api.v1.endpoints.bot_links.redis_cache")
    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_create_link_token_success(
        self,
        mock_auth: AsyncMock,
        mock_redis: MagicMock,
        client: AsyncClient,
    ):
        mock_redis.client = AsyncMock()
        response = await client.post(
            f"{BOT_BASE}/create-link-token",
            json={
                "platform": "discord",
                "platform_user_id": "user123",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert "auth_url" in data

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_create_link_token_validation_error(
        self,
        mock_auth: AsyncMock,
        client: AsyncClient,
    ):
        """Missing required fields returns 422."""
        response = await client.post(
            f"{BOT_BASE}/create-link-token",
            json={},
        )
        assert response.status_code == 422

    async def test_create_link_token_no_api_key(self, client: AsyncClient):
        """Without bot_api_key_valid on request.state, require_bot_api_key raises 401."""
        response = await client.post(
            f"{BOT_BASE}/create-link-token",
            json={"platform": "discord", "platform_user_id": "u1"},
        )
        assert response.status_code == 401

    async def test_the_minted_token_is_the_one_stored_and_the_one_in_the_auth_url(self):
        """The token is the whole link credential: the value handed to the bot,
        the value the confirmation page looks up, and the Redis key must be the
        same string, under the TTL that makes the link short-lived."""
        redis_client = AsyncMock()
        response, _ = await _create_link_token(_CREATE_BODY, redis_client)

        assert response.token
        assert (
            response.auth_url
            == f"{settings.FRONTEND_URL}/auth/link-platform?platform=discord&token={response.token}"
        )
        redis_client.hset.assert_awaited_once_with(
            f"{PLATFORM_LINK_TOKEN_PREFIX}:{response.token}",
            mapping={"platform": "discord", "platform_user_id": "user123"},
        )
        redis_client.expire.assert_awaited_once_with(
            f"{PLATFORM_LINK_TOKEN_PREFIX}:{response.token}", PLATFORM_LINK_TOKEN_TTL
        )

    async def test_the_token_is_minted_with_the_full_32_bytes_of_entropy(self):
        """``link-token-info`` is unauthenticated and the token in its path is the
        whole credential, so the token's WIDTH is the only thing standing between
        a probe and someone's pending link — and nothing about the response shape
        changes when it shrinks."""
        redis_client = AsyncMock()

        with patch(
            "app.api.v1.endpoints.bot_links.secrets.token_urlsafe", return_value="TOKEN"
        ) as mock_token:
            response, _ = await _create_link_token(_CREATE_BODY, redis_client)

        mock_token.assert_called_once_with(32)
        assert response.token == "TOKEN"

    async def test_two_calls_mint_two_different_tokens(self):
        """A reused token would let one bot user's link be redeemed as another's."""
        first, _ = await _create_link_token(_CREATE_BODY, AsyncMock())
        second, _ = await _create_link_token(_CREATE_BODY, AsyncMock())

        assert first.token != second.token

    async def test_the_display_fields_are_stored_only_when_the_bot_sent_them(self):
        """The confirmation page renders these; an absent one must stay absent
        rather than be written as an empty string."""
        redis_client = AsyncMock()
        body = CreateLinkTokenRequest(
            platform="discord",
            platform_user_id="user123",
            username="alice",
            display_name="Alice",
        )
        response, _ = await _create_link_token(body, redis_client)

        assert redis_client.hset.await_args.kwargs["mapping"] == {
            "platform": "discord",
            "platform_user_id": "user123",
            "username": "alice",
            "display_name": "Alice",
        }
        assert response.token

    async def test_issuing_a_token_stamps_the_wide_event_and_the_audit_trail(self):
        """Minting a link credential is auth-grade: the audit entry is the only
        record of which platform account a token was minted for, and it must
        never carry the token itself."""
        redis_client = AsyncMock()
        response, event = await _create_link_token(_CREATE_BODY, redis_client)

        assert event["operation"] == "create_link_token"
        assert event["platform"] == "discord"
        assert event["outcome"] == "success"
        assert event["audit"] == [
            {
                "msg": "platform link token issued",
                "actor": AUDIT_ACTOR_BOT_API,
                "resource": "user123",
                "provider": "discord",
            }
        ]
        assert response.token not in str(event)

    async def test_a_platform_header_mismatch_is_refused_and_audited(self):
        """An API-key holder must not mint a token for a platform it is not
        authenticated as — the refusal names the mismatch and nothing is stored."""
        redis_client = AsyncMock()
        refusal, event = await _create_link_token(
            _CREATE_BODY, redis_client, bot_platform="telegram"
        )

        assert isinstance(refusal, HTTPException)
        assert refusal.status_code == 403
        assert refusal.detail == "Platform in body does not match X-Bot-Platform header"
        assert event["audit"] == [
            {
                "msg": "platform link token rejected",
                "actor": AUDIT_ACTOR_BOT_API,
                "resource": "user123",
                "provider": "discord",
                "reason": "platform_header_mismatch",
            }
        ]
        redis_client.hset.assert_not_awaited()

    async def test_a_platform_user_id_header_mismatch_is_refused_and_audited(self):
        """The second half of the guard: the right platform, someone else's
        handle. Its own reason is what separates it in the audit trail."""
        redis_client = AsyncMock()
        refusal, event = await _create_link_token(
            _CREATE_BODY, redis_client, bot_platform_user_id="SOMEONE_ELSE"
        )

        assert isinstance(refusal, HTTPException)
        assert refusal.status_code == 403
        assert refusal.detail == (
            "platform_user_id in body does not match X-Bot-Platform-User-Id header"
        )
        assert event["audit"] == [
            {
                "msg": "platform link token rejected",
                "actor": AUDIT_ACTOR_BOT_API,
                "resource": "user123",
                "provider": "discord",
                "reason": "platform_user_id_header_mismatch",
            }
        ]
        redis_client.hset.assert_not_awaited()

    async def test_headers_that_match_the_body_mint_the_token(self):
        """The guard compares for INEQUALITY: flipped to `==`, the ordinary case
        where a bot's own headers match its body would refuse every mint."""
        redis_client = AsyncMock()
        response, event = await _create_link_token(
            _CREATE_BODY,
            redis_client,
            bot_platform="discord",
            bot_platform_user_id="user123",
        )

        assert response.token
        assert event["outcome"] == "success"
        redis_client.hset.assert_awaited_once()


# ---------------------------------------------------------------------------
# POST /bot/redeem-link-code
# ---------------------------------------------------------------------------

REDEEM_BODY = {"platform": "telegram", "platform_user_id": "TG42", "code": "CODE123"}
#: What a WhatsApp user typed over the prefill before sending it.
OWN_MESSAGE = "actually, can you sort my inbox before monday?"
PREFS = OnboardingPreferences(profession="founder", needs=[OnboardingNeed.INBOX])
BUBBLES = [
    "Hey. I'm with you on Telegram now.",
    "Your inbox is out of control. Every morning I'll have it sorted and the replies drafted.",
    "One tap and that switches on. The link is live for the next hour:",
    "Gmail: https://gaia.test/connect/abc",
]
PEEK_PATCH = "app.api.v1.endpoints.bot_links.peek_platform_link_code"
DISCARD_PATCH = "app.api.v1.endpoints.bot_links.discard_platform_link_code"
COMPLETE_PATCH = "app.api.v1.endpoints.bot_links.complete_platform_link"
USER_PATCH = "app.api.v1.endpoints.bot_links.get_user_by_id"
CONTACT_PATCH = "app.api.v1.endpoints.bot_links.build_first_contact"
PERSIST_PATCH = "app.api.v1.endpoints.bot_links._persist_first_contact"
# Patched on the class itself, not on a name bound in the endpoint module: the
# endpoint calls it through ``PlatformLinkService``, so both sites see it.
LINKED_LOOKUP_PATCH = (
    "app.services.platform_link_service.PlatformLinkService.get_user_by_platform_id"
)


#: Link completion's own module, patched whole when a test needs the real
#: completion to run (the delivery outcome it reports is what is under test).
COMPLETION_MODULE = "app.services.platform_link_completion"


def _link_result(is_new_link: bool = True) -> PlatformLinkResult:
    return PlatformLinkResult(
        status="linked",
        platform="telegram",
        platform_user_id="TG42",
        connected_at="2026-09-01T00:00:00Z",
        is_new_link=is_new_link,
    )


def _completion(is_new_link: bool = True, delivered: bool = True) -> PlatformLinkCompletion:
    """What the endpoint gets back from link completion."""
    return PlatformLinkCompletion(link=_link_result(is_new_link), first_contact_delivered=delivered)


class TestRedeemLinkCode:
    """POST /api/v1/bot/redeem-link-code"""

    @pytest.fixture(autouse=True)
    def _linked_user(self):
        """The greeting reads the linked user's name, which lives in Mongo.

        Unit tests have no Mongo, so the lookup is stubbed for the whole class
        and returns a user with no name; the tests that care about the name
        override the return value.
        """
        with patch(USER_PATCH, new_callable=AsyncMock, return_value=None) as mock_get_user:
            yield mock_get_user

    @pytest.fixture(autouse=True)
    def _already_linked(self):
        """Whether the presenting platform account is ALREADY linked.

        Reads Mongo, so it is stubbed for the whole class and defaults to
        "nobody": a code that is gone and a handle nobody knows is the expired
        link every rejection test means. The idempotency tests override it.
        """
        with patch(LINKED_LOOKUP_PATCH, new_callable=AsyncMock, return_value=None) as mock_linked:
            yield mock_linked

    @pytest.fixture(autouse=True)
    def _first_contact(self):
        """Composing the bundle reads Mongo (connected integrations) and mints
        Redis-backed connect links. Its copy is proven in
        ``tests/unit/services/onboarding/test_first_contact.py``; here only the
        fact that the endpoint returns whatever it composed matters."""
        with (
            patch(CONTACT_PATCH, new_callable=AsyncMock, return_value=BUBBLES) as mock_contact,
            patch(PERSIST_PATCH, new_callable=AsyncMock),
        ):
            yield mock_contact

    async def test_no_api_key(self, client: AsyncClient):
        response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)
        assert response.status_code == 401

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_happy_path_links_and_hands_the_first_contact_to_completion(
        self, _auth: AsyncMock, client: AsyncClient
    ):
        with (
            patch(
                PEEK_PATCH,
                new_callable=AsyncMock,
                return_value=PlatformLinkCodePayload(user_id="user1", preferences=PREFS),
            ),
            patch(DISCARD_PATCH, new_callable=AsyncMock) as mock_discard,
            patch(
                COMPLETE_PATCH, new_callable=AsyncMock, return_value=_completion()
            ) as mock_complete,
        ):
            response = await client.post(
                f"{BOT_BASE}/redeem-link-code",
                json={**REDEEM_BODY, "username": "tg_user", "display_name": "TG User"},
            )

        assert response.status_code == 200
        # Delivered on the outbound queue, so the bot is handed nothing to send.
        assert response.json() == {"linked": True, "delivered": True, "first_contact": []}
        mock_discard.assert_awaited_once_with("CODE123")
        # The code, not the request body, decides which GAIA user gets linked.
        # The composed first contact travels with the link: completion delivers
        # it on the outbound queue, so the bot has nothing to send.
        mock_complete.assert_awaited_once_with(
            "user1",
            "telegram",
            "TG42",
            profile={"username": "tg_user", "display_name": "TG User"},
            first_contact=BUBBLES,
        )

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_the_bundle_is_composed_for_the_linked_user_not_the_platform_handle(
        self,
        _auth: AsyncMock,
        client: AsyncClient,
        _linked_user: AsyncMock,
        _first_contact: AsyncMock,
    ):
        """The greeting names the GAIA account the code linked and the connect
        links are minted for it, so composing off the platform profile (or off
        nobody) would greet the wrong person and hand out useless links."""
        _linked_user.return_value = {"_id": "user1", "name": "Aryan Randeriya"}
        with (
            patch(
                PEEK_PATCH,
                new_callable=AsyncMock,
                return_value=PlatformLinkCodePayload(user_id="user1", preferences=PREFS),
            ),
            patch(DISCARD_PATCH, new_callable=AsyncMock),
            patch(COMPLETE_PATCH, new_callable=AsyncMock, return_value=_completion()),
        ):
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 200
        _linked_user.assert_awaited_once_with("user1")
        _first_contact.assert_awaited_once_with("user1", "telegram", "Aryan Randeriya", PREFS)

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_the_exchange_is_persisted_so_the_next_turn_has_context(
        self, _auth: AsyncMock, client: AsyncClient, _linked_user: AsyncMock
    ):
        """No chat turn ran, so nothing else writes this. Without it the user's
        next message lands in an empty thread and GAIA has no idea it just
        introduced itself. The request body and the linked user go through
        as-is: the body names the platform thread to write into and the user
        is the actor the write is scoped to."""
        linked_user = {"_id": "user1", "name": "Aryan Randeriya"}
        _linked_user.return_value = linked_user
        with (
            patch(
                PEEK_PATCH,
                new_callable=AsyncMock,
                return_value=PlatformLinkCodePayload(user_id="user1", preferences=PREFS),
            ),
            patch(DISCARD_PATCH, new_callable=AsyncMock),
            patch(COMPLETE_PATCH, new_callable=AsyncMock, return_value=_completion()),
            patch(PERSIST_PATCH, new_callable=AsyncMock) as mock_persist,
        ):
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 200
        mock_persist.assert_awaited_once_with(
            "user1", RedeemLinkCodeRequest(**REDEEM_BODY), linked_user, BUBBLES
        )

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_a_first_contact_the_queue_refused_comes_back_for_the_bot_to_send(
        self, _auth: AsyncMock, client: AsyncClient
    ):
        """The link held, the one message a new user is guaranteed to read did not go out.

        Nothing retries the outbound publish, so a silent failure left the user
        on a linked platform that never said anything. The bubbles come back
        with ``delivered=False`` and the bot sends them itself.
        """
        with (
            patch(
                PEEK_PATCH,
                new_callable=AsyncMock,
                return_value=PlatformLinkCodePayload(user_id="user1", preferences=PREFS),
            ),
            patch(DISCARD_PATCH, new_callable=AsyncMock),
            patch(
                f"{COMPLETION_MODULE}.PlatformLinkService.link_account",
                new_callable=AsyncMock,
                return_value=_link_result(),
            ),
            patch(
                f"{COMPLETION_MODULE}.publish_outbound_message",
                new_callable=AsyncMock,
                return_value=OutboundResult.FAILED,
            ),
            patch(f"{COMPLETION_MODULE}.schedule_account_sync", MagicMock()),
            patch(f"{COMPLETION_MODULE}.capture_event", MagicMock()),
            patch("app.api.v1.endpoints.bot_links.log") as mock_log,
        ):
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 200
        assert response.json() == {
            "linked": True,
            "delivered": False,
            "first_contact": BUBBLES,
        }
        # The wide event is how "did the greeting go out" gets answered in
        # Loki; it must carry the real verdict, not a placeholder.
        mock_log.set.assert_any_call(outcome="success", is_new_link=True, delivered=False)

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_a_delivered_first_contact_is_not_handed_back_as_well(
        self, _auth: AsyncMock, client: AsyncClient
    ):
        """Otherwise the bot sends what the outbound queue already sent."""
        with (
            patch(
                PEEK_PATCH,
                new_callable=AsyncMock,
                return_value=PlatformLinkCodePayload(user_id="user1", preferences=PREFS),
            ),
            patch(DISCARD_PATCH, new_callable=AsyncMock),
            patch(
                f"{COMPLETION_MODULE}.PlatformLinkService.link_account",
                new_callable=AsyncMock,
                return_value=_link_result(),
            ),
            patch(
                f"{COMPLETION_MODULE}.publish_outbound_message",
                new_callable=AsyncMock,
                return_value=OutboundResult.PUBLISHED,
            ),
            patch(f"{COMPLETION_MODULE}.schedule_account_sync", MagicMock()),
            patch(f"{COMPLETION_MODULE}.capture_event", MagicMock()),
            patch("app.api.v1.endpoints.bot_links.log") as mock_log,
        ):
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 200
        assert response.json() == {"linked": True, "delivered": True, "first_contact": []}
        mock_log.set.assert_any_call(outcome="success", is_new_link=True, delivered=True)

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_the_message_the_user_sent_is_the_one_persisted(
        self, _auth: AsyncMock, client: AsyncClient
    ):
        """The WhatsApp prefill is editable, so the text that arrives is theirs."""
        with (
            patch(
                PEEK_PATCH,
                new_callable=AsyncMock,
                return_value=PlatformLinkCodePayload(user_id="user1", preferences=PREFS),
            ),
            patch(DISCARD_PATCH, new_callable=AsyncMock),
            patch(COMPLETE_PATCH, new_callable=AsyncMock, return_value=_completion()),
            patch(PERSIST_PATCH, new_callable=AsyncMock) as mock_persist,
        ):
            response = await client.post(
                f"{BOT_BASE}/redeem-link-code",
                json={**REDEEM_BODY, "first_message": OWN_MESSAGE},
            )

        assert response.status_code == 200
        assert mock_persist.await_args.args[1].first_message == OWN_MESSAGE

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_expired_or_unknown_code_is_rejected_without_linking(
        self, _auth: AsyncMock, client: AsyncClient
    ):
        with (
            patch(PEEK_PATCH, new_callable=AsyncMock, return_value=None),
            patch(DISCARD_PATCH, new_callable=AsyncMock),
            patch(COMPLETE_PATCH, new_callable=AsyncMock) as mock_complete,
        ):
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 400
        assert "expired" in response.json()["message"].lower()
        mock_complete.assert_not_awaited()

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_reused_code_is_rejected_on_the_second_call(
        self, _auth: AsyncMock, client: AsyncClient
    ):
        """Single-use: the store hands the binding over exactly once."""
        payload = PlatformLinkCodePayload(user_id="user1", preferences=PREFS)
        with (
            patch(PEEK_PATCH, new_callable=AsyncMock, side_effect=[payload, None]),
            patch(DISCARD_PATCH, new_callable=AsyncMock),
            patch(COMPLETE_PATCH, new_callable=AsyncMock, return_value=_completion()),
        ):
            first = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)
            second = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert first.status_code == 200
        assert second.status_code == 400

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_a_second_tap_by_the_account_the_code_already_linked_answers_linked(
        self,
        _auth: AsyncMock,
        client: AsyncClient,
        _already_linked: AsyncMock,
        _first_contact: AsyncMock,
    ):
        """Tapping the deep link twice is the normal case on mobile, and the
        second tap arrives with a code that is already spent. The state the code
        asked for is the state we are in, so the answer is the success the first
        tap gave -- being told "that link has expired" under a greeting that is
        still on screen reads as a broken product."""
        with (
            patch(PEEK_PATCH, new_callable=AsyncMock, return_value=None),
            patch(DISCARD_PATCH, new_callable=AsyncMock) as mock_discard,
            patch(COMPLETE_PATCH, new_callable=AsyncMock) as mock_complete,
            patch(PERSIST_PATCH, new_callable=AsyncMock) as mock_persist,
        ):
            _already_linked.return_value = {"_id": "user1", "name": "Aryan Randeriya"}
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 200
        # The first tap's first contact was delivered and is still on screen;
        # the second owes nothing, so the bot is handed nothing to send.
        assert response.json() == {"linked": True, "delivered": True, "first_contact": []}
        _already_linked.assert_awaited_once_with("telegram", "TG42")
        # Every side effect of a first link hangs off completion -- the outbound
        # first-contact publish and the integration_connected capture both. Not
        # calling it is what keeps the user from being greeted, counted and
        # given a synthetic first message a second time.
        mock_complete.assert_not_awaited()
        _first_contact.assert_not_awaited()
        mock_persist.assert_not_awaited()
        mock_discard.assert_not_awaited()

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_a_spent_code_presented_by_an_unlinked_account_still_expires(
        self, _auth: AsyncMock, client: AsyncClient, _already_linked: AsyncMock
    ):
        """The idempotent answer is for the account the code already linked and
        nobody else: a spent code replayed from a different handle is a bearer
        credential being reused, and must stay a dead link."""
        with (
            patch(PEEK_PATCH, new_callable=AsyncMock, return_value=None),
            patch(COMPLETE_PATCH, new_callable=AsyncMock) as mock_complete,
        ):
            _already_linked.return_value = None
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 400
        assert "expired" in response.json()["message"].lower()
        mock_complete.assert_not_awaited()

    async def test_the_idempotent_answer_is_audited_as_a_link_that_already_held(self):
        """A success that writes nothing still has to be findable: without its
        own audit entry and outcome, a second tap is indistinguishable from a
        fresh link in the trail, and from nothing at all in the wide event."""
        body = RedeemLinkCodeRequest(platform="telegram", platform_user_id="TG42", code="CODE123")
        request = MagicMock()
        request.state = _make_request()

        with (
            patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new=AsyncMock()),
            patch(PEEK_PATCH, new_callable=AsyncMock, return_value=None),
            patch(
                LINKED_LOOKUP_PATCH,
                new_callable=AsyncMock,
                return_value={"_id": "user1"},
            ),
        ):
            async with log_context("redeem_link_code_test"):
                result = await redeem_link_code(request, body)
                event = dict(log.get())

        assert result.linked is True
        assert event["user"] == {"id": "user1"}
        assert event["outcome"] == "success"
        assert event["is_new_link"] is False
        assert event["audit"] == [
            {
                "msg": "platform link code already redeemed by this account",
                "actor": "user1",
                "resource": "TG42",
                "provider": "telegram",
            }
        ]
        assert "CODE123" not in str(event)

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_account_linked_elsewhere_returns_409(
        self, _auth: AsyncMock, client: AsyncClient
    ):
        with (
            patch(
                PEEK_PATCH,
                new_callable=AsyncMock,
                return_value=PlatformLinkCodePayload(user_id="user1", preferences=PREFS),
            ),
            patch(DISCARD_PATCH, new_callable=AsyncMock) as mock_discard,
            patch(
                COMPLETE_PATCH,
                new_callable=AsyncMock,
                side_effect=AppError(
                    message="This telegram account is already linked to another GAIA user",
                    status_code=409,
                ),
            ),
        ):
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 409
        # The refusal asks the user to unlink and tap again: the code must still work.
        mock_discard.assert_not_awaited()
        assert "already linked" in response.json()["message"]

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_invalid_platform_is_rejected(self, _auth: AsyncMock, client: AsyncClient):
        response = await client.post(
            f"{BOT_BASE}/redeem-link-code", json={**REDEEM_BODY, "platform": "myspace"}
        )
        assert response.status_code == 422
        # The rejection names the offending platform — a bot operator sending a
        # typo'd platform has to be able to tell what was wrong from the body.
        errors = response.json()["errors"]
        assert [err["loc"] for err in errors] == [["body", "platform"]]
        assert "myspace" in errors[0]["msg"]

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_header_mismatch_is_rejected_before_the_code_is_consumed(
        self, _auth: AsyncMock, client: AsyncClient
    ):
        """An API-key holder must not redeem a code onto someone else's handle."""

        async def _mismatched_request(request):
            request.state.bot_platform = "telegram"
            request.state.bot_platform_user_id = "SOMEONE_ELSE"

        with (
            patch(
                "app.api.v1.endpoints.bot_links.require_bot_api_key",
                new=AsyncMock(side_effect=_mismatched_request),
            ),
            patch(PEEK_PATCH, new_callable=AsyncMock) as mock_peek,
        ):
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 403
        mock_peek.assert_not_awaited()

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_a_platform_mismatch_alone_is_enough_to_reject(
        self, _auth: AsyncMock, client: AsyncClient
    ):
        """The two halves of the guard are independent: a Discord key redeeming a
        Telegram code carries the SAME handle it is authenticated for, so only
        the platform half can catch it."""

        async def _wrong_platform(request):
            request.state.bot_platform = "discord"
            request.state.bot_platform_user_id = "TG42"

        with (
            patch(
                "app.api.v1.endpoints.bot_links.require_bot_api_key",
                new=AsyncMock(side_effect=_wrong_platform),
            ),
            patch(PEEK_PATCH, new_callable=AsyncMock) as mock_peek,
        ):
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 403
        mock_peek.assert_not_awaited()

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_the_expired_code_body_tells_the_user_what_to_do_next(
        self, _auth: AsyncMock, client: AsyncClient
    ):
        """This body is the whole reply a bot user sees when a one-tap link goes
        stale — the why/fix pair is what turns a dead end into a retry."""
        with (
            patch(PEEK_PATCH, new_callable=AsyncMock, return_value=None),
            patch(DISCARD_PATCH, new_callable=AsyncMock),
        ):
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 400
        assert response.json() == {
            "message": "This link has expired or was already used.",
            "why": "the one-tap code is single-use and short-lived",
            "fix": "head back to GAIA on the web and pick your platform again",
        }

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_the_header_mismatch_body_names_the_mismatch(
        self, _auth: AsyncMock, client: AsyncClient
    ):
        async def _mismatched_request(request):
            request.state.bot_platform = "telegram"
            request.state.bot_platform_user_id = "SOMEONE_ELSE"

        with patch(
            "app.api.v1.endpoints.bot_links.require_bot_api_key",
            new=AsyncMock(side_effect=_mismatched_request),
        ):
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 403
        assert response.json() == {
            "message": "Request body does not match the authenticated bot headers"
        }

    async def test_a_matching_header_is_not_treated_as_a_mismatch(self, client: AsyncClient):
        """The guard compares for INEQUALITY: flipped to `==`, the ordinary case
        where the bot's own headers match the body would 403 every redemption."""

        async def _matching_request(request):
            request.state.bot_platform = "telegram"
            request.state.bot_platform_user_id = "TG42"

        with (
            patch(
                "app.api.v1.endpoints.bot_links.require_bot_api_key",
                new=AsyncMock(side_effect=_matching_request),
            ),
            patch(
                PEEK_PATCH,
                new_callable=AsyncMock,
                return_value=PlatformLinkCodePayload(user_id="user1", preferences=PREFS),
            ),
            patch(DISCARD_PATCH, new_callable=AsyncMock),
            patch(COMPLETE_PATCH, new_callable=AsyncMock, return_value=_completion()),
        ):
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 200

    async def test_the_presented_code_is_the_one_redeemed_and_the_plan_is_checked(
        self, client: AsyncClient
    ):
        """The code is the credential and the plan check is the paywall: a call
        that loses either argument links the wrong person, or nobody's plan."""
        with (
            patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new=AsyncMock()),
            patch(
                PEEK_PATCH,
                new_callable=AsyncMock,
                return_value=PlatformLinkCodePayload(user_id="user1", preferences=PREFS),
            ) as mock_peek,
            patch(DISCARD_PATCH, new_callable=AsyncMock) as mock_discard,
            patch(
                "app.api.v1.endpoints.bot_links.require_platform_plan", new_callable=AsyncMock
            ) as mock_plan,
            patch(COMPLETE_PATCH, new_callable=AsyncMock, return_value=_completion()),
        ):
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 200
        mock_peek.assert_awaited_once_with("CODE123")
        mock_plan.assert_awaited_once_with("user1", "telegram")
        # Spent exactly once, and only after the link was written.
        mock_discard.assert_awaited_once_with("CODE123")

    @patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new_callable=AsyncMock)
    async def test_a_plan_wall_leaves_the_code_live_for_the_retry(
        self, _auth: AsyncMock, client: AsyncClient
    ):
        """A lapsed user who taps the link, subscribes, and taps again must not
        be told the link expired: the wall refuses without spending the code."""
        with (
            patch(
                PEEK_PATCH,
                new_callable=AsyncMock,
                return_value=PlatformLinkCodePayload(user_id="user1", preferences=PREFS),
            ),
            patch(DISCARD_PATCH, new_callable=AsyncMock) as mock_discard,
            patch(
                "app.api.v1.endpoints.bot_links.require_platform_plan",
                new=AsyncMock(
                    side_effect=AppError(message="Subscription required", status_code=402)
                ),
            ),
            patch(COMPLETE_PATCH, new_callable=AsyncMock) as mock_complete,
        ):
            response = await client.post(f"{BOT_BASE}/redeem-link-code", json=REDEEM_BODY)

        assert response.status_code == 402
        mock_complete.assert_not_awaited()
        mock_discard.assert_not_awaited()

    async def test_a_successful_redemption_stamps_the_wide_event_and_the_audit_trail(self):
        """Linking a platform account is an auth-grade event: the audit entry is
        the only record of which GAIA user claimed which handle, and the wide
        event is what makes the redemption findable at all."""
        body = RedeemLinkCodeRequest(platform="telegram", platform_user_id="TG42", code="CODE123")
        request = MagicMock()
        request.state = _make_request()

        with (
            patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new=AsyncMock()),
            patch(
                PEEK_PATCH,
                new_callable=AsyncMock,
                return_value=PlatformLinkCodePayload(user_id="user1", preferences=PREFS),
            ),
            patch(DISCARD_PATCH, new_callable=AsyncMock),
            patch("app.api.v1.endpoints.bot_links.require_platform_plan", new=AsyncMock()),
            patch(COMPLETE_PATCH, new_callable=AsyncMock, return_value=_completion()),
        ):
            async with log_context("redeem_link_code_test"):
                result = await redeem_link_code(request, body)
                event = dict(log.get())

        assert result.linked is True
        assert event["operation"] == "redeem_link_code"
        assert event["platform"] == "telegram"
        assert event["user"] == {"id": "user1"}
        assert event["outcome"] == "success"
        assert event["is_new_link"] is True
        assert event["audit"] == [
            {
                "msg": "platform account linked via one-tap code",
                "actor": "user1",
                "resource": "TG42",
                "provider": "telegram",
            }
        ]

    async def test_a_rejected_code_is_audited_with_its_reason_and_never_the_code(self):
        """A probe hammering codes has to be findable, and the audit entry is the
        only place that records it — never carrying the code, which is the
        credential being guessed."""
        body = RedeemLinkCodeRequest(platform="telegram", platform_user_id="TG42", code="CODE123")
        request = MagicMock()
        request.state = _make_request()

        with (
            patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new=AsyncMock()),
            patch(PEEK_PATCH, new_callable=AsyncMock, return_value=None),
            patch(DISCARD_PATCH, new_callable=AsyncMock),
        ):
            async with log_context("redeem_link_code_test"):
                with pytest.raises(AppError) as exc_info:
                    await redeem_link_code(request, body)
                event = dict(log.get())

        assert exc_info.value.status_code == 400
        assert event["audit"] == [
            {
                "msg": "platform link code rejected",
                "actor": AUDIT_ACTOR_BOT_API,
                "resource": "TG42",
                "provider": "telegram",
                "reason": "unknown_or_expired_code",
            }
        ]
        assert "CODE123" not in str(event)

    async def test_a_header_mismatch_is_audited_as_a_mismatch_not_a_bad_code(self):
        """Two rejections share one audit message, so `reason` is the only thing
        separating an expired link from an API key reaching for someone else's
        handle — the second is an attack, the first is a Tuesday."""
        body = RedeemLinkCodeRequest(platform="telegram", platform_user_id="TG42", code="CODE123")
        request = MagicMock()
        request.state = _make_request(bot_platform="telegram", bot_platform_user_id="SOMEONE_ELSE")

        with patch("app.api.v1.endpoints.bot_links.require_bot_api_key", new=AsyncMock()):
            async with log_context("redeem_link_code_test"):
                with pytest.raises(AppError) as exc_info:
                    await redeem_link_code(request, body)
                event = dict(log.get())

        assert exc_info.value.status_code == 403
        assert exc_info.value.message == "Request body does not match the authenticated bot headers"
        assert event["operation"] == "redeem_link_code"
        assert event["platform"] == "telegram"
        assert event["audit"] == [
            {
                "msg": "platform link code rejected",
                "actor": AUDIT_ACTOR_BOT_API,
                "resource": "TG42",
                "provider": "telegram",
                "reason": "platform_header_mismatch",
            }
        ]


# ---------------------------------------------------------------------------
# GET /bot/link-token-info/{token}
# ---------------------------------------------------------------------------


SESSION_PATCH = "app.api.v1.endpoints.bot_links.BotService.get_or_create_session"
UPDATE_PATCH = "app.api.v1.endpoints.bot_links.update_messages"
LOG_PATCH = "app.api.v1.endpoints.bot_links.log"


class TestPersistFirstContact:
    """The redeem endpoint stores the first contact as the bot thread's opening
    turns, through the same write path the chat stream uses."""

    async def test_writes_the_opener_and_the_bundle_as_the_threads_first_turns(self):
        """The opener is what the user actually sent, word for word.

        On WhatsApp and iMessage the prefilled text is editable, so the message
        that arrives is theirs; storing the canned line instead dropped their
        real first question and put words in their mouth.
        """
        body = RedeemLinkCodeRequest(**REDEEM_BODY, first_message=OWN_MESSAGE)
        user = {"_id": "user1", "name": "Aryan Randeriya"}
        with (
            patch(SESSION_PATCH, new_callable=AsyncMock, return_value="conv-1") as session,
            patch(UPDATE_PATCH, new_callable=AsyncMock) as update,
        ):
            await _persist_first_contact("user1", body, user, BUBBLES)

        actor = {"_id": "user1", "name": "Aryan Randeriya", "user_id": "user1"}
        session.assert_awaited_once_with("telegram", "TG42", None, actor, is_dm=True)
        update.assert_awaited_once()
        request = update.await_args.args[0]
        assert update.await_args.kwargs == {"user": actor}
        assert request.conversation_id == "conv-1"
        opener, reply = request.messages
        assert (opener.type, opener.response) == ("user", OWN_MESSAGE)
        assert (reply.type, reply.response) == ("bot", NEW_MESSAGE_BREAKER.join(BUBBLES))
        # Stored the way the chat stream stores turns: UTC with an offset, the
        # opener a beat before the reply so the thread orders the same on reload.
        opener_at, reply_at = (
            datetime.fromisoformat(opener.date),
            datetime.fromisoformat(reply.date),
        )
        assert reply_at.utcoffset() == timedelta(0)
        assert reply_at - opener_at == timedelta(milliseconds=100)

    async def test_a_link_that_carried_no_message_writes_no_user_turn(self):
        """A Telegram deep link is a tap, not a sentence.

        The canned opener used to be stored as the user's own turn, which is a
        message they never sent — and it is what an activation checklist counts
        when it asks whether they have said anything yet.
        """
        with (
            patch(SESSION_PATCH, new_callable=AsyncMock, return_value="conv-1"),
            patch(UPDATE_PATCH, new_callable=AsyncMock) as update,
        ):
            await _persist_first_contact(
                "user1", RedeemLinkCodeRequest(**REDEEM_BODY), None, BUBBLES
            )

        (reply,) = update.await_args.args[0].messages
        assert (reply.type, reply.response) == ("bot", NEW_MESSAGE_BREAKER.join(BUBBLES))

    async def test_a_user_without_a_profile_still_gets_the_thread(self):
        with (
            patch(SESSION_PATCH, new_callable=AsyncMock, return_value="conv-1") as session,
            patch(UPDATE_PATCH, new_callable=AsyncMock),
        ):
            await _persist_first_contact(
                "user1", RedeemLinkCodeRequest(**REDEEM_BODY), None, BUBBLES
            )
        assert session.await_args.args[3] == {"user_id": "user1"}

    async def test_a_failed_write_is_logged_and_never_raised(self):
        """The link already succeeded and the code is spent; a transcript
        failure must not turn that into an error the user cannot retry."""
        with (
            patch(SESSION_PATCH, new_callable=AsyncMock, side_effect=RuntimeError("mongo down")),
            patch(UPDATE_PATCH, new_callable=AsyncMock) as update,
            patch(LOG_PATCH) as mock_log,
        ):
            await _persist_first_contact(
                "user1", RedeemLinkCodeRequest(**REDEEM_BODY), None, BUBBLES
            )
        update.assert_not_awaited()
        # error, not warning: nothing retries this, so the thread is permanently
        # missing the introduction GAIA already sent.
        mock_log.error.assert_called_once_with(
            "could not persist the first-contact exchange",
            user={"id": "user1"},
            provider=REDEEM_BODY["platform"],
            error="mongo down",
            error_type="RuntimeError",
        )
        mock_log.warning.assert_not_called()


class TestGetLinkTokenInfo:
    """GET /api/v1/bot/link-token-info/{token}"""

    @patch("app.api.v1.endpoints.bot_links.redis_cache")
    async def test_link_token_info_success(
        self,
        mock_redis: MagicMock,
        client: AsyncClient,
    ):
        mock_redis.client.hgetall = AsyncMock(
            return_value={
                "platform": "discord",
                "username": "alice",
                "display_name": "Alice",
            }
        )
        response = await client.get(f"{BOT_BASE}/link-token-info/sometoken")
        assert response.status_code == 200
        data = response.json()
        assert data["platform"] == "discord"
        assert data["username"] == "alice"

    @patch("app.api.v1.endpoints.bot_links.redis_cache")
    async def test_link_token_info_not_found(
        self,
        mock_redis: MagicMock,
        client: AsyncClient,
    ):
        mock_redis.client.hgetall = AsyncMock(return_value={})
        response = await client.get(f"{BOT_BASE}/link-token-info/badtoken")
        assert response.status_code == 404

    @patch("app.api.v1.endpoints.bot_links.redis_cache")
    async def test_the_record_is_read_under_the_token_key_and_only_display_fields_returned(
        self, mock_redis: MagicMock, client: AsyncClient
    ):
        """The route is unauthenticated, so the response must carry nothing but
        what the confirmation page shows — never the platform user id."""
        mock_redis.client.hgetall = AsyncMock(
            return_value={
                "platform": "discord",
                "platform_user_id": "user123",
                "username": "alice",
                "display_name": "Alice",
            }
        )
        response = await client.get(f"{BOT_BASE}/link-token-info/sometoken")

        assert response.status_code == 200
        assert response.json() == {
            "platform": "discord",
            "username": "alice",
            "display_name": "Alice",
        }
        mock_redis.client.hgetall.assert_awaited_once_with(
            f"{PLATFORM_LINK_TOKEN_PREFIX}:sometoken"
        )

    async def test_a_presented_token_stamps_the_wide_event_and_the_audit_trail(self):
        with patch("app.api.v1.endpoints.bot_links.redis_cache") as mock_redis:
            mock_redis.client.hgetall = AsyncMock(
                return_value={"platform": "discord", "username": "alice"}
            )
            async with log_context("link_token_info_test"):
                result = await get_link_token_info("sometoken")
                event = dict(log.get())

        assert result.platform == "discord"
        assert event["operation"] == "get_link_token_info"
        assert event["platform"] == "discord"
        assert event["outcome"] == "success"
        assert event["audit"] == [
            {
                "msg": "platform link token presented",
                "actor": AUDIT_ACTOR_UNAUTHENTICATED,
                "provider": "discord",
            }
        ]

    async def test_a_lookup_miss_is_audited_as_a_probe_and_never_carries_the_token(self):
        """The token in the path IS the credential being guessed — the audit
        entry records the probe, the reason, and nothing that was presented."""
        with patch("app.api.v1.endpoints.bot_links.redis_cache") as mock_redis:
            mock_redis.client.hgetall = AsyncMock(return_value={})
            async with log_context("link_token_info_test"):
                with pytest.raises(HTTPException) as exc_info:
                    await get_link_token_info("GUESSED_TOKEN")
                event = dict(log.get())

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Token not found or expired"
        assert event["audit"] == [
            {
                "msg": "platform link token lookup rejected",
                "actor": AUDIT_ACTOR_UNAUTHENTICATED,
                "reason": "unknown_or_expired_token",
            }
        ]
        assert "GUESSED_TOKEN" not in str(event)
