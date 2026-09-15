"""The bot's first contact after a one-tap link: two bubbles, composed by the
server, never by the model.

What has to hold: every pick has a clause and an ask (a missing entry is a
silently skipped pick), only the jobs that are impossible without an account
ask for a link, and the copy reads as speech in GAIA's voice.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.onboarding.first_contact import (
    NEED_ASKS,
    NEED_CLAUSES,
    NEED_INTEGRATIONS,
    NO_PICKS_ASK,
    OTHER_NEED_ASK,
    build_first_contact,
    compose_first_contact,
    compose_link_greeting,
    needed_integration_ids,
)

MODULE = "app.services.onboarding.first_contact"
GMAIL = ("gmail", "https://gaia.test/connect/aaa")
CALENDAR = ("googlecalendar", "https://gaia.test/connect/bbb")


def _prefs(needs: list[OnboardingNeed], other_need: str | None = None) -> OnboardingPreferences:
    return OnboardingPreferences(profession="founder", needs=needs, other_need=other_need)


class TestNeedCopy:
    def test_every_need_has_a_clause(self) -> None:
        assert set(NEED_CLAUSES) == set(OnboardingNeed)

    def test_every_need_has_an_ask(self) -> None:
        assert set(NEED_ASKS) == set(OnboardingNeed)

    def test_only_the_jobs_impossible_without_an_account_ask_for_a_link(self) -> None:
        """Slack, Notion and GitHub are never demanded up front; the playbook
        offers them later, once the answer says where the work lives."""
        assert NEED_INTEGRATIONS == {
            OnboardingNeed.INBOX: ("gmail",),
            OnboardingNeed.CALENDAR: ("googlecalendar",),
            OnboardingNeed.MORNINGS: ("gmail",),
            OnboardingNeed.SALES_LEADS: ("gmail",),
            OnboardingNeed.SALES_CALL_RESEARCH: ("googlecalendar",),
        }

    @pytest.mark.parametrize("clause", list(NEED_CLAUSES.values()), ids=list(NEED_CLAUSES))
    def test_a_clause_is_lowercase_speech_with_no_full_stop(self, clause: str) -> None:
        assert clause[0].islower() or clause.startswith("I ")
        assert not clause.endswith(".")
        assert "!" not in clause

    @pytest.mark.parametrize("ask", list(NEED_ASKS.values()), ids=list(NEED_ASKS))
    def test_an_ask_is_one_short_reasoned_request_they_can_answer(self, ask: str) -> None:
        """A question or a "send me / name / paste" request, ending on the thing
        to do, no shouting, no emoji, and short enough to read on a phone."""
        assert ask.endswith((".", "?"))
        assert "!" not in ask
        assert ask.isascii()
        assert len(ask) <= 120
        assert ask.count("?") <= 1


class TestNeededIntegrationIds:
    def test_picks_dedupe_and_keep_tap_order(self) -> None:
        assert needed_integration_ids(
            _prefs([OnboardingNeed.CALENDAR, OnboardingNeed.INBOX, OnboardingNeed.MORNINGS])
        ) == ["googlecalendar", "gmail"]

    def test_picks_that_connect_nothing_contribute_nothing(self) -> None:
        assert (
            needed_integration_ids(
                _prefs([OnboardingNeed.GRUNT_WORK, OnboardingNeed.PRODUCT_SPECS])
            )
            == []
        )

    def test_no_picks_is_no_links(self) -> None:
        assert needed_integration_ids(_prefs([])) == []


class TestComposeFirstContact:
    def test_the_founder_bundle_reads_end_to_end(self) -> None:
        assert compose_first_contact(
            "telegram",
            "Aryan Randeriya",
            _prefs([OnboardingNeed.INBOX, OnboardingNeed.CALENDAR], other_need="book my travel."),
            [GMAIL, CALENDAR],
        ) == [
            "Hey Aryan, I'm with you on Telegram now.",
            "From here, every morning your inbox comes sorted with replies drafted and you "
            'get a brief before each meeting. You also said "book my travel". That\'s mine too.',
            "Your inbox and your calendar are where I start, and I can't see them yet. "
            "[Connect Gmail](https://gaia.test/connect/aaa) and "
            "[Connect Google Calendar](https://gaia.test/connect/bbb). Either one first.",
        ]

    def test_it_is_a_hello_a_promise_and_a_first_move(self) -> None:
        """Three texts, never a wall; a user who picked nothing gets two."""
        for prefs, links, count in (
            (_prefs([]), [], 2),
            (_prefs([OnboardingNeed.INBOX]), [GMAIL], 3),
            (_prefs([OnboardingNeed.GRUNT_WORK, OnboardingNeed.TOOLS], "x"), [], 3),
            (_prefs([], "x"), [], 3),
        ):
            assert len(compose_first_contact("telegram", None, prefs, links)) == count

    def test_clauses_follow_the_order_the_user_tapped(self) -> None:
        """Their first pick is what they came for, so it leads."""
        _, promise, _ = compose_first_contact(
            "telegram", None, _prefs([OnboardingNeed.CALENDAR, OnboardingNeed.INBOX]), []
        )
        assert promise.index(NEED_CLAUSES[OnboardingNeed.CALENDAR]) < promise.index(
            NEED_CLAUSES[OnboardingNeed.INBOX]
        )

    def test_three_clauses_read_as_a_sentence(self) -> None:
        _, promise, _ = compose_first_contact(
            "telegram",
            None,
            _prefs([OnboardingNeed.INBOX, OnboardingNeed.CALENDAR, OnboardingNeed.GRUNT_WORK]),
            [],
        )
        assert promise == (
            "From here, every morning your inbox comes sorted with replies drafted, you get "
            "a brief before each meeting, and whatever grunt work you hand me gets done."
        )

    def test_one_link_gives_the_reason_and_one_tap(self) -> None:
        first_move = compose_first_contact(
            "imessage", "Dev", _prefs([OnboardingNeed.INBOX]), [GMAIL]
        )[-1]
        assert first_move == (
            "That starts with your inbox, which I can't see yet. "
            "One tap: [Connect Gmail](https://gaia.test/connect/aaa)."
        )

    def test_an_integration_with_no_hand_written_phrase_is_named_from_the_config(
        self,
    ) -> None:
        """Only Gmail and Calendar have hand-written connect copy. Anything else
        falls back to the OAuth config's display name — which is not the raw id:
        "Connect github" reads like a bug report, "Connect GitHub" reads like a
        product. The unlock clause is that same name."""
        first_move = compose_first_contact(
            "telegram", "Dev", _prefs([OnboardingNeed.INBOX]), [("github", "https://g.test/c")]
        )[-1]
        assert first_move == (
            "That starts with GitHub, which I can't see yet. "
            "One tap: [Connect GitHub](https://g.test/c)."
        )
        assert "github," not in first_move  # never the raw id
        assert "Connect None" not in first_move

    def test_a_link_wins_over_a_question_for_mixed_picks(self) -> None:
        """A tap does more than a typed answer, so the connect ask leads."""
        first_move = compose_first_contact(
            "telegram", None, _prefs([OnboardingNeed.GRUNT_WORK, OnboardingNeed.INBOX]), [GMAIL]
        )[-1]
        assert "[Connect Gmail]" in first_move
        assert NEED_ASKS[OnboardingNeed.GRUNT_WORK] not in first_move

    def test_no_links_asks_about_the_first_pick(self) -> None:
        first_move = compose_first_contact(
            "telegram",
            None,
            _prefs([OnboardingNeed.FOUNDER_TEAM_UPDATES, OnboardingNeed.GRUNT_WORK]),
            [],
        )[-1]
        assert first_move == NEED_ASKS[OnboardingNeed.FOUNDER_TEAM_UPDATES]

    def test_an_already_connected_pick_gets_its_connected_ask(self) -> None:
        """Gmail on and inbox picked: no link to hand over, so the ask assumes
        the inbox is running and asks what to flag."""
        first_move = compose_first_contact("telegram", None, _prefs([OnboardingNeed.INBOX]), [])[-1]
        assert first_move == NEED_ASKS[OnboardingNeed.INBOX]
        assert "already on" in first_move

    def test_their_own_words_are_quoted_back_with_trailing_punctuation_trimmed(self) -> None:
        _, promise, _ = compose_first_contact("telegram", None, _prefs([], "Book my travel!!"), [])
        assert promise == 'You also said "Book my travel". That\'s mine too.'

    def test_trimming_their_words_never_eats_a_real_last_letter(self) -> None:
        """Only sentence punctuation comes off the end. ``rstrip`` takes a SET of
        characters, so widening it by one letter silently truncates every answer
        that ends in that letter — "plan X" would be quoted back as "plan"."""
        _, promise, _ = compose_first_contact("telegram", None, _prefs([], "plan X"), [])
        assert promise == 'You also said "plan X". That\'s mine too.'

    def test_only_typed_words_ask_for_a_bit_more(self) -> None:
        first_move = compose_first_contact("telegram", None, _prefs([], "book my travel"), [])[-1]
        assert first_move == OTHER_NEED_ASK

    def test_a_blank_other_need_adds_nothing(self) -> None:
        assert compose_first_contact("telegram", None, _prefs([], "   "), []) == [
            "Hey, I'm with you on Telegram now.",
            NO_PICKS_ASK,
        ]

    def test_a_user_who_picked_nothing_still_gets_a_hello_and_a_first_move(self) -> None:
        assert compose_first_contact("whatsapp", "Dev", _prefs([]), []) == [
            "Hey Dev, I'm with you on WhatsApp now.",
            NO_PICKS_ASK,
        ]

    def test_output_is_stable_across_calls(self) -> None:
        args = ("telegram", "Aryan", _prefs([OnboardingNeed.INBOX]), [GMAIL])
        assert compose_first_contact(*args) == compose_first_contact(*args)


class TestComposeLinkGreeting:
    def test_uses_the_first_name_only_and_opens_the_sentence(self) -> None:
        assert compose_link_greeting("telegram", "Aryan Randeriya") == (
            "Hey Aryan, I'm with you on Telegram now."
        )

    @pytest.mark.parametrize(
        ("platform", "label"),
        [("telegram", "Telegram"), ("whatsapp", "WhatsApp"), ("imessage", "iMessage")],
    )
    def test_each_platform_is_named_the_way_the_user_calls_it(
        self, platform: str, label: str
    ) -> None:
        assert label in compose_link_greeting(platform, "Dev")

    @pytest.mark.parametrize("name", [None, "", "   "])
    def test_an_unknown_name_drops_the_clause_rather_than_greeting_a_blank(
        self, name: str | None
    ) -> None:
        assert compose_link_greeting("telegram", name) == "Hey, I'm with you on Telegram now."


class TestBuildFirstContact:
    async def test_an_already_connected_integration_is_not_re_offered(self) -> None:
        repo = AsyncMock()
        repo.is_connected = AsyncMock(side_effect=lambda _u, i: i == "gmail")
        mint = AsyncMock(side_effect=lambda _u, i: f"https://gaia.test/connect/{i}")
        with (
            patch(f"{MODULE}.user_integration_repository", repo),
            patch(f"{MODULE}.build_connect_link_url", mint),
        ):
            bubbles = await build_first_contact(
                "u1", "telegram", "Aryan", _prefs([OnboardingNeed.INBOX, OnboardingNeed.CALENDAR])
            )
        mint.assert_awaited_once_with("u1", "googlecalendar")
        assert bubbles[-1] == (
            "That starts with your calendar, which I can't see yet. "
            "One tap: [Connect Google Calendar](https://gaia.test/connect/googlecalendar)."
        )

    async def test_the_connected_check_is_asked_about_this_user_and_the_name_is_carried(
        self,
    ) -> None:
        """Two things the bundle-shape assertions above cannot see. The
        already-connected lookup must name the user who just linked — asked about
        anyone else it reads someone else's accounts and either re-offers a link
        they already have or hides one they need. And the name resolved here has
        to reach the greeting, or every first contact opens with a bare "Hey,"."""
        repo = AsyncMock()
        # User-sensitive on purpose: only u1 has Gmail, so a lookup for anybody
        # else comes back "not connected" and re-offers it.
        repo.is_connected = AsyncMock(side_effect=lambda u, i: u == "u1" and i == "gmail")
        mint = AsyncMock(side_effect=lambda _u, i: f"https://gaia.test/connect/{i}")
        with (
            patch(f"{MODULE}.user_integration_repository", repo),
            patch(f"{MODULE}.build_connect_link_url", mint),
        ):
            bubbles = await build_first_contact(
                "u1", "telegram", "Aryan Randeriya", _prefs([OnboardingNeed.INBOX])
            )

        repo.is_connected.assert_awaited_once_with("u1", "gmail")
        # Gmail is already on for u1, so there is no connect link and no ask for it.
        assert bubbles[0] == "Hey Aryan, I'm with you on Telegram now."
        assert "Connect Gmail" not in " ".join(bubbles)

    async def test_a_link_that_could_not_be_minted_is_dropped_not_shipped_dead(self) -> None:
        repo = AsyncMock()
        repo.is_connected = AsyncMock(return_value=False)
        with (
            patch(f"{MODULE}.user_integration_repository", repo),
            patch(f"{MODULE}.build_connect_link_url", AsyncMock(return_value=None)),
        ):
            bubbles = await build_first_contact(
                "u1", "telegram", None, _prefs([OnboardingNeed.INBOX])
            )
        assert bubbles[-1] == NEED_ASKS[OnboardingNeed.INBOX]

    async def test_a_dead_mint_is_recorded_as_an_error_naming_the_user_pick_and_platform(
        self,
    ) -> None:
        """Dropping the link is silent in the product: nothing retries the mint
        and the user simply never connects, so this line is the only trace that
        a first contact shipped without the tap it exists to offer. ``log.error``
        appends message AND kwargs to the wide event's ``errors[]``, which makes
        every field a queryable surface — without them a Gmail mint failing on
        Telegram is indistinguishable from a calendar one failing on WhatsApp,
        and without the user nobody can be told to connect by hand."""
        repo = AsyncMock()
        repo.is_connected = AsyncMock(return_value=False)
        with (
            patch(f"{MODULE}.user_integration_repository", repo),
            patch(f"{MODULE}.build_connect_link_url", AsyncMock(return_value=None)),
            patch(f"{MODULE}.log") as mock_log,
        ):
            await build_first_contact("u1", "telegram", None, _prefs([OnboardingNeed.INBOX]))

        mock_log.error.assert_called_once_with(
            "connect link could not be minted for first contact",
            user={"id": "u1"},
            integration_id="gmail",
            platform="telegram",
        )

    async def test_one_dead_mint_does_not_cost_them_the_links_after_it(self) -> None:
        """Each pick's link is minted on its own, so Redis dropping the Gmail one
        must not swallow the calendar link the next pick needs. Abandoning the
        loop at the first failure ships a first contact with no tap at all."""
        repo = AsyncMock()
        repo.is_connected = AsyncMock(return_value=False)
        mint = AsyncMock(
            side_effect=lambda _u, i: None if i == "gmail" else f"https://gaia.test/connect/{i}"
        )
        with (
            patch(f"{MODULE}.user_integration_repository", repo),
            patch(f"{MODULE}.build_connect_link_url", mint),
        ):
            bubbles = await build_first_contact(
                "u1", "telegram", None, _prefs([OnboardingNeed.INBOX, OnboardingNeed.CALENDAR])
            )

        assert bubbles[-1] == (
            "That starts with your calendar, which I can't see yet. "
            "One tap: [Connect Google Calendar](https://gaia.test/connect/googlecalendar)."
        )
