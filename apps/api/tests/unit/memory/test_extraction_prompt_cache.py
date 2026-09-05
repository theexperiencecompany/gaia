"""The extraction request's cacheable prefix must not move when memory grows.

The memory lane is billed against a byte-prefix cache: a request resumes from
cache only up to the first byte that differs from the previous one. Extraction
sends [system prompt, transcript, volatile tail] and the transcript is by far
the largest part (~9.8k of ~11.3k tokens in production), so it only ever gets
cached if everything ahead of it is byte-identical between calls.

The folder tree used to sit at the very end of the system prompt, immediately
ahead of the transcript. It grows as the user's memory accumulates, so filing a
fact into a new folder moved the boundary and the whole transcript re-sent at
full price behind it. It now rides the trailing volatile message instead.

These assert on the assembled messages rather than on a hit rate, because the
hit rate is a provider-side number we cannot observe in a unit test.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from langchain_core.messages import BaseMessage
import pytest

from app.memory.extraction import StoredMemoryState, extract_memories
from app.memory.schemas import ExtractedMemoryBatch

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
_TRANSCRIPT = [
    {"role": "user", "content": "my sister Priya's birthday is in March"},
    {"role": "assistant", "content": "Noted."},
]

_HINTS = "Prefer commitments the sender made in the thread."
# Verbatim, because this preamble is the only thing standing between a
# per-integration hint and the rules it must not override — a model reading a
# reworded or missing version treats the hint as a peer of the prompt.
_HINTS_SECTION = (
    "\n## Integration-specific extraction focus\n\n"
    "The notes below say WHAT to prioritize for this integration. They "
    "supplement the rules above and never override them: output format, "
    "fact rules, folders, importance, temporal fields, and the "
    "stranger/noise gate always follow this prompt.\n"
    f"{_HINTS}\n"
)
_JOURNAL_HEADING = "## Today's journal so far (do NOT repeat these events, even reworded)\n"
_FACTS_HEADING = "\n## Recently stored facts (do NOT re-extract these)\n"


async def _messages_for(
    folder_tree: str,
    recent_facts: list[str] | None = None,
    journaled_today: list[str] | None = None,
    user_name: str = "Aryan",
    extraction_hints: str | None = None,
) -> list[BaseMessage]:
    """The messages one extraction call would send, for a given memory state."""
    with patch(
        "app.memory.extraction._invoke_structured",
        new=AsyncMock(return_value=ExtractedMemoryBatch()),
    ) as invoke:
        await extract_memories(
            _TRANSCRIPT,
            user_id="u1",
            user_name=user_name,
            stored=StoredMemoryState(
                folder_tree=folder_tree,
                recent_facts=recent_facts or [],
                journaled_today=journaled_today or [],
            ),
            extraction_hints=extraction_hints,
            current_date=_WHEN,
        )
    return invoke.await_args.args[1]


def _tail(messages: Sequence[BaseMessage]) -> str:
    """The trailing volatile message — where every stored input is rendered."""
    return str(messages[-1].content)


def _prefix_through_transcript(messages: Sequence[BaseMessage]) -> str:
    """Everything up to and including the transcript — the part that must be
    byte-identical between calls for the transcript to stay cached."""
    return "".join(str(m.content) for m in messages[:2])


class TestTheCacheablePrefixSurvivesMemoryGrowth:
    async def test_a_new_folder_does_not_move_the_prefix(self) -> None:
        """Filing one fact into a new folder must not re-send the transcript."""
        before = await _messages_for("relationships\npreferences")
        after = await _messages_for("relationships\npreferences\nwork/gaia")

        assert _prefix_through_transcript(before) == _prefix_through_transcript(after), (
            "the folder tree moved the cacheable prefix, so the whole transcript "
            "re-sends uncached whenever the user's memory gains a folder"
        )

    async def test_newly_stored_facts_do_not_move_the_prefix(self) -> None:
        """Same guarantee for the other per-call input that grows."""
        before = await _messages_for("relationships", recent_facts=["likes oat milk"])
        after = await _messages_for(
            "relationships", recent_facts=["likes oat milk", "sister is Priya"]
        )

        assert _prefix_through_transcript(before) == _prefix_through_transcript(after)

    async def test_the_tail_itself_caches_through_the_journal_while_facts_churn(self) -> None:
        """The tail is over half of a real extraction call (measured live:
        cached tokens stop at system+transcript, ~47%, and everything behind is
        tail). Within the tail, churn rates differ wildly: the journal only
        APPENDS during a day, while the recent-facts window ROLLS on every
        ingestion. Byte-prefix caches reward putting the append-only part
        first — with the rolling window ahead of the journal, one new fact
        re-sends the whole journal on every single extraction, forever.

        Between two consecutive extractions where the journal appended and the
        facts rolled, the tails must share a byte prefix that still contains
        the whole earlier journal.
        """
        journal = ["went for a run", "met Priya for lunch"]
        before = _tail(
            await _messages_for(
                "relationships",
                recent_facts=["fact one", "fact two"],
                journaled_today=journal,
            )
        )
        after = _tail(
            await _messages_for(
                "relationships",
                # the window rolled: oldest dropped, newest arrived
                recent_facts=["fact two", "fact three"],
                journaled_today=[*journal, "shipped the release"],
            )
        )

        shared = 0
        for a, b in zip(before, after):
            if a != b:
                break
            shared += 1
        common = before[:shared]
        # The heading is part of the shared bytes AND a model-facing dedup
        # directive — its emphasis ("do NOT repeat") is written that way on
        # purpose, so it is asserted verbatim rather than case-insensitively.
        assert "## Today's journal so far (do NOT repeat these events, even reworded)" in common
        assert "went for a run" in common and "met Priya for lunch" in common, (
            "the rolling facts window sits ahead of the append-only journal, so "
            f"the shared tail prefix ends before the journal (only {shared} chars "
            "survive) and the whole journal re-sends on every extraction"
        )

    async def test_the_folder_tree_is_still_actually_sent(self) -> None:
        """Moving it must not drop it: the model still files facts by folder."""
        messages = await _messages_for("relationships\nwork/gaia")

        assert "work/gaia" in _tail(messages), (
            "the folder tree left the system prompt but never arrived in the tail"
        )

    async def test_a_user_with_no_folders_yet_still_gets_a_readable_section(self) -> None:
        """A brand-new user has an empty tree. The section still has to say so
        in words: the model reads it to decide where to file that user's very
        first fact, and an empty heading — or the literal "None" — is what it
        would otherwise be filing against."""
        tail = _tail(await _messages_for(""))

        assert "## Existing memory folders\n\n(no folders yet)" in tail, (
            f"the empty-tree placeholder did not render as written, got: {tail[-120:]!r}"
        )

    async def test_every_extraction_carries_the_user_s_memory_session_key(self) -> None:
        """The sticky-routing chain is what keeps consecutive extractions
        landing on the upstream that already holds this user's transcript
        prefixes. Asserted one seam lower than the other tests — at the
        client-call boundary — because the key is added by the real config
        builder, and patching above it would test nothing."""
        with patch(
            "app.memory.extraction.ainvoke_structured_gemini",
            new=AsyncMock(return_value=ExtractedMemoryBatch()),
        ) as invoke:
            await extract_memories(
                _TRANSCRIPT,
                user_id="u1",
                user_name="Aryan",
                stored=StoredMemoryState(folder_tree="relationships"),
                current_date=_WHEN,
            )

        config = invoke.await_args.kwargs["config"]
        assert config["configurable"]["session_id"] == "memory-u1"
        # The key must never displace the spend attribution it merges beside.
        assert config["configurable"]["user_id"] == "u1"
        assert "memory_internal" in config["tags"]

    async def test_the_folder_guidance_stays_in_the_stable_prompt(self) -> None:
        """Only the mutable tree moves; the instructions on how to use it are
        byte-stable and belong in the cached prefix."""
        messages = await _messages_for("relationships")

        assert "category_path" in str(messages[0].content)

    async def test_the_stable_prompt_is_byte_identical_across_users(self) -> None:
        """The system prompt used to open with the user's NAME, so every user
        needed their own warm copy of the ~4.8k-token system+schema prefix and
        no user's traffic could warm another's — measured in production: 87%
        of extraction calls read zero cached tokens. One universal prompt is
        the only version any upstream ever has to hold."""
        for_aryan = await _messages_for("relationships", user_name="Aryan")
        for_dhruv = await _messages_for("relationships", user_name="Dhruv")

        assert str(for_aryan[0].content) == str(for_dhruv[0].content), (
            "the system prompt differs between users, so the shared prefix "
            "dies at the first occurrence of the name and no user's calls can "
            "warm the cache for anyone else's"
        )

    async def test_the_user_s_name_rides_the_tail_ahead_of_the_date(self) -> None:
        """The model still needs the real name (facts are written in the third
        person about a named person, and "the user's girlfriend" as fact
        content would be useless). It moves to the volatile tail, FIRST —
        within the tail order is by churn rate and the name never changes,
        while the date already churns daily."""
        tail = _tail(await _messages_for("relationships"))

        # Verbatim: this sentence is the instruction that makes facts use the
        # real name instead of "the user" — its wording is load-bearing, not
        # decoration (the CI mutation gate proved looser asserts let it rot).
        assert (
            "The user in this transcript (`user:`) is Aryan. "
            "Write every fact using this real name." in tail
        )
        assert tail.index("Aryan") < tail.index("Today is"), (
            "the name churns less than the date, so placing it behind the "
            "date re-sends it uncached every day for no reason"
        )

    async def test_a_missing_name_never_renders_as_the_literal_none(self) -> None:
        messages = await _messages_for("relationships", user_name="the user")

        assert "None's" not in str(messages[0].content)
        assert "None's" not in _tail(messages)


class TestTheStoredStateIsRenderedIntoTheTail:
    """``StoredMemoryState`` is the extractor's whole picture of what memory
    already holds. Every field has to arrive in the tail in a shape the model
    can read: the two list fields as one bullet per line, and — when they are
    empty — as words saying so rather than a bare heading, which the model
    would otherwise read as "nothing was looked up" instead of "nothing yet".
    """

    async def test_every_recently_stored_fact_gets_its_own_bullet(self) -> None:
        tail = _tail(
            await _messages_for("relationships", recent_facts=["likes oat milk", "sister is Priya"])
        )

        assert tail.endswith(f"{_FACTS_HEADING}- likes oat milk\n- sister is Priya")

    async def test_an_empty_fact_window_says_so_in_words(self) -> None:
        tail = _tail(await _messages_for("relationships"))

        assert tail.endswith(f"{_FACTS_HEADING}(none yet)")

    async def test_every_journal_entry_gets_its_own_bullet(self) -> None:
        tail = _tail(
            await _messages_for(
                "relationships", journaled_today=["went for a run", "met Priya for lunch"]
            )
        )

        assert f"{_JOURNAL_HEADING}- went for a run\n- met Priya for lunch\n" in tail

    async def test_an_empty_journal_says_so_in_words(self) -> None:
        tail = _tail(await _messages_for("relationships"))

        assert f"{_JOURNAL_HEADING}(empty)\n" in tail


class TestIntegrationHintsRideTheVeryEndOfTheTail:
    """Per-run hints churn hardest, so they sit last. They also arrive from an
    integration rather than from this prompt, which is why they are wrapped in a
    preamble that ranks them below it — without that framing a hint reads as an
    instruction of equal standing and can override the fact rules.
    """

    async def test_the_hints_arrive_under_the_preamble_that_subordinates_them(self) -> None:
        tail = _tail(await _messages_for("relationships", extraction_hints=_HINTS))

        assert tail.endswith(_HINTS_SECTION)

    async def test_a_run_without_hints_appends_nothing_at_all(self) -> None:
        """Not "no hints text" — nothing. A placeholder here would be bytes the
        model has to read on every hint-less extraction, which is most of them.
        """
        with_hints = _tail(await _messages_for("relationships", extraction_hints=_HINTS))
        without_hints = _tail(await _messages_for("relationships"))

        assert without_hints == with_hints.removesuffix(_HINTS_SECTION)
